//! Session configuration is validated before opening a stream. Never callback-owned.
use super::*;
use graph_core::result::{DeviceBinding, Profile};
use serde::Serialize;

const MAX_EDIT_BYTES: usize = 16384;

#[derive(Clone, Deserialize)]
#[serde(deny_unknown_fields)]
struct Submission {
    generation: u64,
    revision: u64,
    profiles: Vec<ChannelCalibration>,
}

#[derive(Default)]
pub(super) struct Controller {
    revision: u64,
    command: Option<Submission>,
    config: Option<Request>,
    evidence_revision: Option<u64>,
}

fn receipt(request: &Request, revision: u64, status: &str, reason: Option<&str>) -> String {
    let channels: Vec<_> = request
        .format
        .input_ids
        .iter()
        .zip(&request.format.input_ports)
        .map(|(id, port)| {
            json!({"channel_id": id,
            "device_binding": {"device": request.calibration_device(), "port": port}})
        })
        .collect();
    json!({"schema_version": 1, "generation": request.format.generation,
        "revision": revision, "status": status, "reason": reason,
        "channels": channels, "profiles": request.calibration})
    .to_string()
}

pub(super) fn initialize(owner: &Owner, request: &Request) {
    let mut slot = owner.mailbox.lock().unwrap();
    if !owner.stop.load(Ordering::Acquire) {
        slot.calibration.config = Some(request.clone());
        slot.snapshot.calibration = receipt(request, 0, "ready", None);
    }
}

impl Display {
    /// Qt/control thread: bounded parse and enqueue only. Binding validation and
    /// replacement happen on the analysis owner, never on the audio callback.
    pub fn apply_calibration(&mut self, encoded: &str) -> bool {
        if encoded.len() > MAX_EDIT_BYTES {
            return false;
        }
        let Ok(submission) = serde_json::from_str::<Submission>(encoded) else {
            return false;
        };
        let mut slot = self.mailbox.lock().unwrap();
        if slot.snapshot.state != State::Running
            || self.stop.load(Ordering::Acquire)
            || submission.generation != slot.snapshot.generation
            || submission.revision <= slot.calibration.revision
            || slot.calibration.command.is_some()
        {
            return false;
        }
        let Some(config) = &slot.calibration.config else {
            return false;
        };
        slot.snapshot.calibration = receipt(config, submission.revision, "queued", None);
        slot.calibration.revision = submission.revision;
        slot.calibration.command = Some(submission);
        true
    }
}

pub(super) fn cancel(slot: &mut Mailbox) {
    if let Some(submission) = slot.calibration.command.take()
        && let Some(config) = &slot.calibration.config
    {
        slot.snapshot.calibration = receipt(config, submission.revision, "cancelled", None);
    }
}

/// One atomic replacement before constructing subsequent normal/trigger results.
/// No existing result or shared raw FFT is changed or recalculated. Invalid edits
/// leave all active profiles intact and do not fail acquisition.
pub(super) fn process(
    owner: &Owner,
    notify: &impl Fn(u64) -> bool,
    request: &mut Request,
) -> Result<(), String> {
    let (revision, encoded) = {
        let mut slot = owner.mailbox.lock().unwrap();
        if owner.stop.load(Ordering::Acquire) {
            cancel(&mut slot);
            return Ok(());
        }
        let Some(submission) = slot.calibration.command.take() else {
            return Ok(());
        };
        let previous = std::mem::replace(&mut request.calibration, submission.profiles);
        let error = request.validate_calibration().err();
        if error.is_some() {
            request.calibration = previous;
        } else {
            slot.calibration.evidence_revision = Some(submission.revision);
        }
        let encoded = receipt(
            request,
            submission.revision,
            if error.is_some() {
                "rejected"
            } else {
                "applied"
            },
            error.as_deref(),
        );
        slot.calibration.config = Some(request.clone());
        slot.snapshot.calibration = encoded.clone();
        (submission.revision, encoded)
    };
    // Optional diagnostic evidence, outside the mailbox lock. It is not a product
    // persistence format and contains no expected values sent by the oracle.
    if let Some(directory) = &request.evidence {
        let path = directory.join(format!(
            "calibration-{}-{revision}.json",
            request.format.generation
        ));
        use std::io::Write;
        std::fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(path)
            .and_then(|mut file| file.write_all(encoded.as_bytes()))
            .map_err(|e| e.to_string())?;
    }
    if !owner.notify(notify) {
        owner.stop.store(true, Ordering::Release);
    }
    Ok(())
}

pub(super) fn evidence_revision(owner: &Owner) -> Option<u64> {
    owner
        .mailbox
        .lock()
        .unwrap()
        .calibration
        .evidence_revision
        .take()
}

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
    // Export each saved snapshot's own profile, including sessions whose active
    // profiles were cleared before Stop. Never infer old evidence from final settings.
    let Some(path) = request.evidence.as_ref() else {
        return Ok(());
    };
    let generation = request.format.generation;
    let normal = format!("generation-{generation}.json");
    let prefix = format!("trigger-{generation}-");
    let calibration_prefix = format!("calibration-{generation}-");
    for entry in std::fs::read_dir(path).map_err(|e| e.to_string())? {
        let entry = entry.map_err(|e| e.to_string())?;
        let name = entry.file_name();
        let Some(name) = name.to_str() else { continue };
        if name != normal
            && !((name.starts_with(&prefix) || name.starts_with(&calibration_prefix))
                && name.ends_with(".result.json"))
        {
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
