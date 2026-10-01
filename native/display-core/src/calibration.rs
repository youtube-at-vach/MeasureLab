//! Session configuration is validated before opening a stream. Never callback-owned.
use super::*;
use graph_core::result::{DeviceBinding, Profile};
use serde::Serialize;

/// Evaluation input only; the applied interval is taken from each actual result.
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ChannelCalibration {
    pub channel_id: String,
    pub revision: String,
    pub device_binding: DeviceBinding,
    pub is_calibrated: bool,
    pub v_per_fs: f64,
}

impl Request {
    pub fn calibration_device(&self) -> String {
        self.live.as_ref().map_or_else(
            || format!("saved:{}", self.format.stream_id),
            |live| live.device.clone(),
        )
    }
    pub(super) fn validate_calibration(&self) -> Result<(), String> {
        if self.calibration.len() > self.format.input_ids.len() {
            return Err("display_calibration_capacity".into());
        }
        let mut ids = HashSet::new();
        for profile in &self.calibration {
            let index = self
                .format
                .input_ids
                .iter()
                .position(|id| id == &profile.channel_id)
                .ok_or("display_calibration_channel")?;
            if !ids.insert(&profile.channel_id) {
                return Err("display_calibration_duplicate".into());
            }
            if profile.revision.trim().is_empty()
                || profile.revision.len() > 256
                || !profile.v_per_fs.is_finite()
                || profile.v_per_fs <= 0.0
            {
                return Err("display_calibration_profile".into());
            }
            if profile.device_binding.device != self.calibration_device()
                || profile.device_binding.port as usize != self.format.input_ports[index]
            {
                return Err("display_calibration_binding".into());
            }
        }
        Ok(())
    }
    pub(super) fn profiles(&self, interval: [u64; 2]) -> BTreeMap<String, Profile> {
        self.calibration
            .iter()
            .map(|p| {
                (
                    p.channel_id.clone(),
                    Profile {
                        revision: p.revision.clone(),
                        device_binding: p.device_binding.clone(),
                        is_calibrated: p.is_calibrated,
                        v_per_fs: p.v_per_fs,
                        applied_interval: interval,
                    },
                )
            })
            .collect()
    }
}

pub(super) fn calibrated_result(
    raw: &FftResult,
    capture: Capture,
    request: &Request,
) -> Result<MeasurementResult, String> {
    let (start, end) = raw.interval();
    MeasurementResult::from_fft(raw, capture, &request.profiles([start, end]), 1.)
}

pub(super) fn save_result(
    result: &MeasurementResult,
    path: &std::path::Path,
    request: &Request,
) -> Result<(), String> {
    result
        .save_new(path, Format::Json)
        .map_err(|e| e.to_string())?;
    if !request.calibration.is_empty() && request.live.is_none() {
        let csv = path.with_extension("csv");
        result
            .save_new(&csv, Format::Csv)
            .map_err(|e| e.to_string())?;
    }
    Ok(())
}

/// Live diagnostic CSV encoding waits until the stream and graph have been stopped.
/// Retain only one bounded decoded result at a time; JSON is the complete snapshot.
#[cfg(any(feature = "live-audio", test))]
pub(super) fn finish_live_evidence(request: &Request) -> Result<(), String> {
    let Some(path) = request
        .evidence
        .as_ref()
        .filter(|_| !request.calibration.is_empty())
    else {
        return Ok(());
    };
    let generation = request.format.generation;
    let normal = format!("generation-{generation}.json");
    let prefix = format!("trigger-{generation}-");
    for entry in std::fs::read_dir(path).map_err(|e| e.to_string())? {
        let entry = entry.map_err(|e| e.to_string())?;
        let name = entry.file_name();
        let Some(name) = name.to_str() else { continue };
        if name != normal && !(name.starts_with(&prefix) && name.ends_with(".result.json")) {
            continue;
        }
        let result = MeasurementResult::load(&entry.path(), Format::Json)?;
        if result.source().generation != generation {
            return Err("display_calibration_evidence_generation".into());
        }
        result
            .save_new(&entry.path().with_extension("csv"), Format::Csv)
            .map_err(|e| e.to_string())?;
    }
    Ok(())
}

#[cfg(test)]
mod tests;
