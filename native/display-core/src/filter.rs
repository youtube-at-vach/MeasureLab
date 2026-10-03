//! Fixed P2 evaluation selection. All configuration/processing is analysis-owned.
use super::*;
use graph_core::Rational;
use graph_core::filter::{Filter, FilterConfig, FilterLimits, InputConversion};
use graph_core::{Samples, Source};
use serde::Serialize;

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct FilterRequest {
    pub input_conversion: Option<InputConversion>,
}
impl Request {
    pub(super) fn input_frames(&self) -> usize {
        self.n * if self.filter.is_some() { 2 } else { 1 }
    }
    pub(super) fn validate_filter(&self) -> Result<(), String> {
        if let Some(filter) = &self.filter
            && (self.format.rate != [48000, 1]
                || !matches!((self.precision, filter.input_conversion),
                    (Precision::F32, Some(InputConversion::F32ToF64Exact)) | (Precision::F64, None))
                // The live raw-save archive uses input-domain contiguous windows.
                || self.save_input_evidence)
        {
            return Err("display_filter_configuration".into());
        }
        Ok(())
    }
}
pub(super) fn prepare<T: CaptureSample>(
    acquisition: &Acquisition<T>,
    request: &Request,
) -> Result<(FftKey, Option<Filter>), String> {
    let Some(selection) = &request.filter else {
        return Ok((acquisition.key().clone(), None));
    };
    let filter = Filter::new_with_conversion(
        acquisition.key().source.clone(),
        format!("{}.fir", request.format.stream_id),
        format!("{}.fir", request.format.timebase_id),
        FilterConfig::Fir {
            coefficients: vec![0.25, 0.5, 0.25],
            target_rate: Rational {
                numerator: 24000,
                denominator: 1,
            },
            centered: false,
            revision: "causal-3tap-v1".into(),
        },
        FilterLimits::default(),
        selection.input_conversion,
    )?;
    let mut key = acquisition.key().clone();
    key.source = filter.output_source().clone();
    Ok((key, Some(filter)))
}
pub(super) fn attach<T: CaptureSample>(
    acquisition: &mut Acquisition<T>,
    request: &Request,
    filter: Option<Filter>,
) -> Result<(), String> {
    if let Some(filter) = filter {
        acquisition.attach_filter(
            filter,
            FftSpec {
                n: request.n,
                hop: request.n,
                alignment: 0,
                window: request.window,
            },
            HistoryLimits::frames(request.n * 8),
        )?;
    }
    Ok(())
}

/// Bounded diagnostic support; raw values stay f32 and logical port order is kept.
pub(super) struct ParentEvidence {
    source: Source,
    interval: [u64; 2],
    bytes: Vec<u8>,
}
pub(super) fn parent_evidence<T: CaptureSample>(
    acquisition: &Acquisition<T>,
    interval: [u64; 2],
) -> Result<Option<ParentEvidence>, String> {
    let Some(metadata) = acquisition.filtered_metadata() else {
        return Ok(None);
    };
    let [start, end] = [
        interval[0]
            .checked_mul(2)
            .ok_or("position_overflow")?
            .saturating_sub(2),
        interval[1].checked_mul(2).ok_or("position_overflow")?,
    ];
    let block = acquisition
        .history()
        .ok_or("live_history_missing")?
        .read_interval(
            i64::try_from(start).map_err(|_| "position_overflow")?,
            i64::try_from(end).map_err(|_| "position_overflow")?,
        )?
        .snapshot
        .ok_or("filter_parent_evidence_missing")?;
    let bytes = match block.samples() {
        Samples::F32(values) => values.iter().flat_map(|v| v.to_le_bytes()).collect(),
        Samples::F64(values) => values.iter().flat_map(|v| v.to_le_bytes()).collect(),
    };
    Ok(Some(ParentEvidence {
        source: metadata.parent,
        interval: [start, end],
        bytes,
    }))
}
impl ParentEvidence {
    pub(super) fn write(self, stem: &std::path::Path) -> Result<(), String> {
        use std::io::Write;
        let precision = if self.source.precision == Precision::F32 {
            "f32"
        } else {
            "f64"
        };
        let metadata = json!({"source": self.source, "interval": self.interval, "byte_count": self.bytes.len()});
        for (path, bytes) in [
            (
                stem.with_extension(format!("parent.{precision}")),
                self.bytes,
            ),
            (
                stem.with_extension("parent.json"),
                serde_json::to_vec_pretty(&metadata).map_err(|e| e.to_string())?,
            ),
        ] {
            std::fs::OpenOptions::new()
                .write(true)
                .create_new(true)
                .open(path)
                .and_then(|mut f| f.write_all(&bytes))
                .map_err(|e| e.to_string())?;
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests;
