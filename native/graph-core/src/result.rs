//! MIG-006-E experimental immutable result/exchange boundary, analysis worker only.
//! Owned snapshots survive graph/profile changes. This is not the product file schema.
use crate::{
    FftResult, InvalidSpan, Numeric, Precision, Rational, Source, TRANSFORM_REVISION, Tap,
};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::collections::{BTreeMap, HashSet};
use std::fs::{self, OpenOptions};
use std::io::{Read, Write};
use std::path::Path;
use std::sync::atomic::{AtomicU64, Ordering};

const MAX_VALUES: usize = 4_000_000;
const MAX_FILE_BYTES: u64 = 256 * 1024 * 1024;
static NEXT_TEMP: AtomicU64 = AtomicU64::new(1);

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DeviceBinding {
    pub device: String,
    pub port: u32,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Profile {
    pub revision: String,
    pub device_binding: DeviceBinding,
    pub is_calibrated: bool,
    pub v_per_fs: f64,
    pub applied_interval: [u64; 2],
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Capture {
    pub result_id: String,
    pub trigger_id: Option<String>,
    pub acquired_host_seconds: Option<Rational>,
    pub result_host_seconds: Option<Rational>,
    #[serde(default)]
    pub trigger: Option<crate::history::TriggerEvent>,
    #[serde(default)]
    pub clock_mapping: Option<crate::time::ClockMapping>,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Calibration {
    channel_id: String,
    profile: Option<Profile>,
    application: String,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Axis {
    dimension: String,
    unit: String,
    nominal: Vec<f64>,
    corrected: Vec<f64>,
    correction: f64,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Column {
    unit: String,
    precision: Precision,
    shape: Vec<usize>,
    values: Vec<Option<f64>>,
    reasons: Vec<Option<String>>,
}
impl Column {
    fn new(unit: &str, precision: Precision, shape: Vec<usize>, values: Vec<f64>) -> Self {
        let reasons = values
            .iter()
            .map(|v| (!v.is_finite()).then(|| "nonfinite".into()))
            .collect();
        Self {
            unit: unit.into(),
            precision,
            shape,
            values: values
                .into_iter()
                .map(|v| v.is_finite().then_some(v))
                .collect(),
            reasons,
        }
    }
    fn invalid(unit: &str, precision: Precision, shape: Vec<usize>, reason: &str) -> Self {
        let count = shape.iter().product();
        Self {
            unit: unit.into(),
            precision,
            shape,
            values: vec![None; count],
            reasons: vec![Some(reason.into()); count],
        }
    }
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Document {
    schema_version: u32,
    capture: Capture,
    operation_revision: String,
    source: Source,
    interval: [u64; 2],
    raw_result_id: Option<[u64; 2]>,
    conditions: Value,
    axis: Axis,
    calibration: Vec<Calibration>,
    columns: BTreeMap<String, Column>,
    validity: Vec<InvalidSpan>,
    error: Option<String>,
}
/// No mutable access and no unchecked Deserialize implementation.
#[derive(Clone, Debug)]
pub struct MeasurementResult(Document);
#[derive(Clone, Copy, Debug)]
pub enum Format {
    Json,
    Csv,
}

fn positive(value: f64) -> bool {
    value.is_finite() && value > 0.0
}
fn calibrated(p: &Calibration) -> Option<f64> {
    p.profile
        .as_ref()
        .filter(|p| p.is_calibrated)
        .map(|p| p.v_per_fs)
}
impl MeasurementResult {
    fn base(
        source: &Source,
        interval: [u64; 2],
        capture: Capture,
        profiles: &BTreeMap<String, Profile>,
        frequencies: Vec<f64>,
        correction: f64,
        operation: (&str, Value),
    ) -> Result<Self, String> {
        if frequencies.len() > MAX_VALUES / 2 {
            return Err("result_numeric_capacity".into());
        }
        let mut result = Self(Document {
            schema_version: 1,
            capture,
            operation_revision: operation.0.into(),
            source: source.clone(),
            interval,
            raw_result_id: None,
            conditions: operation.1,
            axis: Axis {
                dimension: "frequency".into(),
                unit: "Hz".into(),
                corrected: frequencies.iter().map(|v| v * correction).collect(),
                nominal: frequencies,
                correction,
            },
            calibration: source
                .channel_ids
                .iter()
                .map(|id| Calibration {
                    channel_id: id.clone(),
                    profile: profiles.get(id).cloned(),
                    application: "after_analysis".into(),
                })
                .collect(),
            columns: BTreeMap::new(),
            validity: Vec::new(),
            error: None,
        });
        if profiles.keys().any(|id| !source.channel_ids.contains(id)) {
            return Err("unknown_profile_channel".into());
        }
        // Validate before computing or allocating numeric columns.
        result.validate(false)?;
        result.0.columns.clear();
        Ok(result)
    }
    /// Coherent tone scalar contract; does not claim RMS of an arbitrary waveform.
    pub fn coherent_tone(
        source: &Source,
        interval: [u64; 2],
        capture: Capture,
        peaks: &[f64],
        profiles: &BTreeMap<String, Profile>,
        frequencies: Vec<f64>,
        correction: f64,
    ) -> Result<Self, String> {
        if peaks.len() != source.channel_ids.len()
            || peaks.iter().any(|v| v.is_finite() && *v < 0.0)
        {
            return Err("invalid_peak_shape_or_sign".into());
        }
        let mut result = Self::base(
            source,
            interval,
            capture,
            profiles,
            frequencies,
            correction,
            (
                "rms-cosine-v1",
                json!({"signal":"coherent_sine", "peak_to_rms":"sqrt(2)"}),
            ),
        )?;
        let shape = vec![peaks.len()];
        result.0.columns.insert(
            "peak_fs".into(),
            Column::new("FS_peak", Precision::F64, shape.clone(), peaks.to_vec()),
        );
        result.0.columns.insert(
            "rms_fs".into(),
            Column::new(
                "FS_RMS",
                Precision::F64,
                shape,
                peaks.iter().map(|v| v / 2.0_f64.sqrt()).collect(),
            ),
        );
        result.add_absolute()?;
        result.validate(true)?;
        Ok(result)
    }
    /// Copies original analysis arrays, including f32 inverse samples without rounding to display precision.
    pub fn from_fft(
        raw: &FftResult,
        capture: Capture,
        profiles: &BTreeMap<String, Profile>,
        correction: f64,
    ) -> Result<Self, String> {
        let key = raw.key();
        let channels = key.source.channel_ids.len();
        let bins = key.n / 2 + 1;
        if key
            .n
            .checked_mul(channels)
            .and_then(|v| v.checked_mul(12))
            .is_none_or(|v| v > MAX_VALUES)
        {
            return Err("result_numeric_capacity".into());
        }
        let frequencies = (0..bins)
            .map(|i| i as f64 * key.source.timebase.rate_hz() / key.n as f64)
            .collect();
        let (start, end) = raw.interval();
        let mut result = Self::base(
            &key.source,
            [start, end],
            capture,
            profiles,
            frequencies,
            correction,
            (
                TRANSFORM_REVISION,
                serde_json::to_value(key).map_err(|e| e.to_string())?,
            ),
        )?;
        result.0.raw_result_id = Some([raw.id().graph, raw.id().serial]);
        result.0.validity = raw.validity().to_vec();
        result.0.error = raw.error().map(str::to_owned);
        macro_rules! copy_analysis {
            ($a:expr, $inverse:expr) => {{
                let a = $a;
                let mut insert = |name: &str, unit, precision, shape, values| {
                    result
                        .0
                        .columns
                        .insert(name.into(), Column::new(unit, precision, shape, values));
                };
                insert("window", "1", Precision::F64, vec![key.n], a.window.clone());
                insert(
                    "fft_over_n",
                    "FS",
                    Precision::F64,
                    vec![bins, channels, 2],
                    a.fft_over_n.iter().flat_map(|v| [v.re, v.im]).collect(),
                );
                insert(
                    "inverse_windowed",
                    "FS",
                    key.source.precision,
                    vec![key.n, channels],
                    $inverse,
                );
                for (name, unit, values) in [
                    ("peak_fs", "FS_peak", &a.peak_fs),
                    ("tone_rms_fs", "FS_RMS", &a.tone_rms_fs),
                    ("psd_fs2_hz", "FS2/Hz", &a.psd_fs2_hz),
                    ("asd_fs_sqrt_hz", "FS/sqrt(Hz)", &a.asd_fs_sqrt_hz),
                ] {
                    insert(
                        name,
                        unit,
                        Precision::F64,
                        vec![bins, channels],
                        values.clone(),
                    );
                }
                for (name, unit, values) in [
                    ("rms_fs", "FS_RMS", &a.rms_fs),
                    ("integrated_power_fs2", "FS2", &a.integrated_power_fs2),
                    ("time_window_power_fs2", "FS2", &a.time_window_power_fs2),
                ] {
                    insert(name, unit, Precision::F64, vec![channels], values.clone());
                }
            }};
        }
        match raw.numeric() {
            Some(Numeric::F32(a)) => copy_analysis!(
                a,
                a.inverse_windowed.iter().map(|v| f64::from(*v)).collect()
            ),
            Some(Numeric::F64(a)) => copy_analysis!(a, a.inverse_windowed.clone()),
            None => {
                let reason = raw.error().unwrap_or("invalid_input");
                for (name, unit, shape, precision) in
                    column_specs(key.n, channels, key.source.precision)
                {
                    result
                        .0
                        .columns
                        .insert(name.into(), Column::invalid(unit, precision, shape, reason));
                }
            }
        }
        result.add_absolute()?;
        result.validate(true)?;
        Ok(result)
    }
    fn add_absolute(&mut self) -> Result<(), String> {
        let calibration = &self.0.calibration;
        let has_psd = self.0.columns.contains_key("psd_fs2_hz");
        let frequency_correction = self.0.axis.correction;
        let mut scale = |input: &str, output: &str, unit: &str, power: i32| -> Result<(), String> {
            let original = self.0.columns.get(input).ok_or("missing_relative_column")?;
            let mut column = original.clone();
            column.unit = unit.into();
            column.precision = Precision::F64;
            for (i, (value, reason)) in column
                .values
                .iter_mut()
                .zip(&mut column.reasons)
                .enumerate()
            {
                if let Some(factor) = calibrated(&calibration[i % calibration.len()]) {
                    if let Some(v) = value {
                        *v *= factor.powi(power)
                            / if power == 2 {
                                frequency_correction
                            } else {
                                1.0
                            };
                        if !v.is_finite() {
                            *value = None;
                            *reason = Some("nonfinite".into());
                        }
                    }
                } else {
                    *value = None;
                    *reason = Some("uncalibrated".into());
                }
            }
            self.0.columns.insert(output.into(), column);
            Ok(())
        };
        scale("rms_fs", "rms_v", "V_RMS", 1)?;
        if has_psd {
            scale("psd_fs2_hz", "psd_v2_hz", "V2/Hz", 2)?;
        }
        let mut dbv = self.0.columns["rms_v"].clone();
        dbv.unit = "dBV_RMS".into();
        for (v, reason) in dbv.values.iter_mut().zip(&mut dbv.reasons) {
            if let Some(value) = v {
                if *value > 0.0 {
                    *value = 20.0 * value.log10();
                } else {
                    *v = None;
                    *reason = Some("nonpositive".into());
                }
            }
        }
        self.0.columns.insert("dbv".into(), dbv);
        self.0.columns.insert(
            "spl".into(),
            Column::invalid(
                "dBSPL",
                Precision::F64,
                vec![calibration.len()],
                "uncalibrated",
            ),
        );
        Ok(())
    }
    fn validate(&self, with_columns: bool) -> Result<(), String> {
        let d = &self.0;
        let channels = &d.source.channel_ids;
        if d.schema_version != 1
            || !d.source.valid()
            || channels.len() > 32
            || d.capture.result_id.is_empty()
            || d.operation_revision.is_empty()
            || d.interval[0] >= d.interval[1]
            || !d.conditions.is_object()
        {
            return Err("invalid_result_identity".into());
        }
        if d.capture.trigger_id.as_ref().is_some_and(|v| v.is_empty())
            || [
                &d.capture.acquired_host_seconds,
                &d.capture.result_host_seconds,
            ]
            .iter()
            .any(|v| v.as_ref().is_some_and(|v| !v.valid()))
        {
            return Err("invalid_capture_metadata".into());
        }
        if let Some(trigger) = &d.capture.trigger
            && (d.capture.trigger_id.as_deref() != Some(&trigger.id)
                || trigger.stream_id != d.source.stream_id
                || trigger.generation != d.source.generation
                || trigger.timebase_id != d.source.timebase.id
                || !trigger.sample.valid()
                || trigger.source.is_empty()
                || trigger.kind.is_empty()
                || trigger.polarity.is_empty()
                || trigger.condition_revision.is_empty()
                || trigger
                    .received_host_seconds
                    .as_ref()
                    .is_some_and(|r| !r.valid()))
        {
            return Err("invalid_result_trigger".into());
        }
        if let Some(mapping) = &d.capture.clock_mapping
            && (mapping.from != (d.source.timebase.id.clone(), d.source.generation)
                || mapping.to.0.is_empty()
                || mapping.method.is_empty()
                || !mapping.offset.valid()
                || !mapping.ratio.valid()
                || mapping.ratio.numerator <= 0
                || mapping.valid_interval[0] >= mapping.valid_interval[1]
                || i64::try_from(d.interval[0]).is_err()
                || i64::try_from(d.interval[1]).is_err()
                || mapping.valid_interval[0] > d.interval[0] as i64
                || mapping.valid_interval[1] < d.interval[1] as i64
                || mapping
                    .uncertainty_samples
                    .as_ref()
                    .is_some_and(|r| !r.valid() || r.numerator < 0))
        {
            return Err("invalid_result_clock_mapping".into());
        }
        let a = &d.axis;
        if a.dimension != "frequency"
            || a.unit != "Hz"
            || !positive(a.correction)
            || a.nominal.len() != a.corrected.len()
            || a.nominal.len() > MAX_VALUES
            || a.nominal.iter().any(|v| !v.is_finite() || *v < 0.0)
            || a.nominal
                .iter()
                .zip(&a.corrected)
                .any(|(x, y)| !y.is_finite() || x * a.correction != *y)
        {
            return Err("invalid_frequency_axis".into());
        }
        if d.calibration.len() != channels.len() {
            return Err("invalid_calibration_shape".into());
        }
        for (id, c) in channels.iter().zip(&d.calibration) {
            if id != &c.channel_id || c.application != "after_analysis" {
                return Err("invalid_calibration_identity".into());
            }
            if let Some(p) = &c.profile {
                if p.revision.is_empty()
                    || p.device_binding.device.is_empty()
                    || !positive(p.v_per_fs)
                    || p.applied_interval[0] > d.interval[0]
                    || p.applied_interval[1] < d.interval[1]
                {
                    return Err("invalid_calibration_profile".into());
                }
                if p.is_calibrated && d.source.tap != Tap::InputRaw {
                    return Err("absolute_calibration_requires_input_raw".into());
                }
            }
        }
        if d.validity.len() > 4096
            || d.validity.iter().any(|v| {
                v.start >= v.end
                    || v.start < d.interval[0]
                    || v.end > d.interval[1]
                    || v.reason.is_empty()
                    || v.origin.is_empty()
                    || v.channel_id
                        .as_ref()
                        .is_some_and(|id| !channels.contains(id))
            })
        {
            return Err("invalid_result_validity".into());
        }
        if !with_columns {
            return Ok(());
        }
        let mut count = a
            .nominal
            .len()
            .checked_mul(2)
            .ok_or("result_numeric_capacity")?;
        for (name, c) in &d.columns {
            let len = c
                .shape
                .iter()
                .try_fold(1usize, |a, b| a.checked_mul(*b))
                .ok_or("column_shape_overflow")?;
            count = count.checked_add(len).ok_or("column_shape_overflow")?;
            if name.is_empty()
                || c.unit.is_empty()
                || c.shape.is_empty()
                || c.values.len() != len
                || c.reasons.len() != len
                || count > MAX_VALUES
            {
                return Err("invalid_column_shape".into());
            }
            for (v, r) in c.values.iter().zip(&c.reasons) {
                if v.is_none() != r.is_some()
                    || r.as_ref().is_some_and(|r| r.is_empty())
                    || v.is_some_and(|v| {
                        !v.is_finite()
                            || (c.precision == Precision::F32 && f64::from(v as f32) != v)
                    })
                {
                    return Err("invalid_column_value_or_reason".into());
                }
            }
        }
        let expected: BTreeMap<_, _> = if d.raw_result_id.is_some() {
            let n =
                usize::try_from(d.interval[1] - d.interval[0]).map_err(|_| "invalid_fft_length")?;
            if n < 3
                || d.axis.nominal.len() != n / 2 + 1
                || d.raw_result_id.is_some_and(|v| v.contains(&0))
                || d.operation_revision != TRANSFORM_REVISION
            {
                return Err("invalid_fft_result".into());
            }
            if d.conditions["source"]
                != serde_json::to_value(&d.source).map_err(|e| e.to_string())?
                || d.conditions["n"].as_u64() != Some(n as u64)
            {
                return Err("invalid_fft_conditions".into());
            }
            column_specs(n, channels.len(), d.source.precision)
                .into_iter()
                .map(|(name, unit, shape, precision)| (name, (unit, shape, precision)))
                .chain([(
                    "psd_v2_hz",
                    ("V2/Hz", vec![n / 2 + 1, channels.len()], Precision::F64),
                )])
                .collect()
        } else {
            if d.operation_revision != "rms-cosine-v1" {
                return Err("unsupported_result_operation".into());
            }
            [
                ("peak_fs", ("FS_peak", vec![channels.len()], Precision::F64)),
                ("rms_fs", ("FS_RMS", vec![channels.len()], Precision::F64)),
            ]
            .into_iter()
            .collect()
        };
        let expected: BTreeMap<_, _> = expected
            .into_iter()
            .chain([
                ("rms_v", ("V_RMS", vec![channels.len()], Precision::F64)),
                ("dbv", ("dBV_RMS", vec![channels.len()], Precision::F64)),
                ("spl", ("dBSPL", vec![channels.len()], Precision::F64)),
            ])
            .collect();
        if expected.len() != d.columns.len()
            || expected.iter().any(|(name, (unit, shape, precision))| {
                d.columns.get(*name).is_none_or(|c| {
                    c.unit != *unit || &c.shape != shape || &c.precision != precision
                })
            })
        {
            return Err("invalid_column_inventory".into());
        }
        if d.columns["spl"].values.iter().any(Option::is_some) {
            return Err("unsupported_absolute_spl".into());
        }
        // Uncalibrated defaults must never become evidence of absolute calibration.
        for (i, c) in d.calibration.iter().enumerate() {
            for name in ["rms_v", "dbv", "psd_v2_hz"] {
                if let Some(column) = d.columns.get(name)
                    && calibrated(c).is_none()
                    && column
                        .values
                        .iter()
                        .skip(i)
                        .step_by(channels.len())
                        .any(Option::is_some)
                {
                    return Err("uncalibrated_absolute_value".into());
                }
            }
        }
        Ok(())
    }
    pub fn to_value(&self) -> Value {
        serde_json::to_value(&self.0).expect("validated finite result")
    }
    /// Borrow the immutable document fields without serializing every numeric column.
    pub fn source(&self) -> &Source {
        &self.0.source
    }
    pub fn interval(&self) -> [u64; 2] {
        self.0.interval
    }
    pub fn capture(&self) -> &Capture {
        &self.0.capture
    }
    pub fn raw_result_id(&self) -> Option<[u64; 2]> {
        self.0.raw_result_id
    }
    pub fn corrected_frequencies(&self) -> &[f64] {
        &self.0.axis.corrected
    }
    pub fn column_value(&self, name: &str) -> Option<Value> {
        self.0
            .columns
            .get(name)
            .map(|column| serde_json::to_value(column).expect("validated finite column"))
    }
    pub fn validity(&self) -> &[InvalidSpan] {
        &self.0.validity
    }
    pub fn error(&self) -> Option<&str> {
        self.0.error.as_deref()
    }
    pub fn encode(&self, format: Format) -> Result<Vec<u8>, String> {
        match format {
            Format::Json => serde_json::to_vec(&self.0).map_err(|e| e.to_string()),
            Format::Csv => {
                let mut metadata = self.0.clone();
                for c in metadata.columns.values_mut() {
                    c.values.clear();
                    c.reasons.clear();
                }
                let mut rows = vec![
                    vec![
                        "# MIG-006-E exchange v1".into(),
                        serde_json::to_string(&metadata).map_err(|e| e.to_string())?,
                    ],
                    vec![
                        "metric".into(),
                        "index".into(),
                        "value".into(),
                        "reason".into(),
                    ],
                ];
                for (name, c) in &self.0.columns {
                    for (i, (v, r)) in c.values.iter().zip(&c.reasons).enumerate() {
                        rows.push(vec![
                            name.clone(),
                            i.to_string(),
                            v.map_or_else(String::new, |v| v.to_string()),
                            r.clone().unwrap_or_default(),
                        ]);
                    }
                }
                Ok(csv_encode(&rows).into_bytes())
            }
        }
    }
    pub fn decode(bytes: &[u8], format: Format) -> Result<Self, String> {
        if bytes.len() as u64 > MAX_FILE_BYTES {
            return Err("result_file_too_large".into());
        }
        let document: Document = match format {
            Format::Json => {
                serde_json::from_value(unique_json(bytes)?).map_err(|e| e.to_string())?
            }
            Format::Csv => {
                let rows = csv_decode(std::str::from_utf8(bytes).map_err(|e| e.to_string())?)?;
                if rows.len() < 3
                    || rows[0].len() != 2
                    || rows[0][0] != "# MIG-006-E exchange v1"
                    || rows[1] != ["metric", "index", "value", "reason"]
                {
                    return Err("invalid_csv_schema".into());
                }
                let mut d: Document = serde_json::from_value(unique_json(rows[0][1].as_bytes())?)
                    .map_err(|e| e.to_string())?;
                if d.columns
                    .values()
                    .any(|c| !c.values.is_empty() || !c.reasons.is_empty())
                {
                    return Err("csv_metadata_contains_values".into());
                }
                let mut seen = HashSet::new();
                for row in &rows[2..] {
                    if row.len() != 4 {
                        return Err("invalid_csv_row".into());
                    }
                    let c = d.columns.get_mut(&row[0]).ok_or("unknown_csv_metric")?;
                    let index: usize = row[1].parse().map_err(|_| "invalid_csv_index")?;
                    if index != c.values.len() || !seen.insert((row[0].clone(), index)) {
                        return Err("invalid_csv_order_or_duplicate".into());
                    }
                    c.values.push(if row[2].is_empty() {
                        None
                    } else {
                        Some(row[2].parse().map_err(|_| "invalid_csv_numeric")?)
                    });
                    c.reasons.push((!row[3].is_empty()).then(|| row[3].clone()));
                    if seen.len() > MAX_VALUES {
                        return Err("result_file_too_large".into());
                    }
                }
                d
            }
        };
        // Never coerce missing/unknown provenance to zero or infer a legacy timebase.
        let result = Self(document);
        result.validate(true)?;
        Ok(result)
    }
    pub fn write_to(&self, writer: &mut impl Write, format: Format) -> std::io::Result<()> {
        let bytes = self.encode(format).map_err(std::io::Error::other)?;
        writer.write_all(&bytes)?;
        writer.flush()
    }
    /// Publish a complete, synced file without replacing an existing destination.
    /// Hard-link commit requires same-directory filesystem support. No crash-durability claim for directory metadata.
    pub fn save_new(&self, path: &Path, format: Format) -> std::io::Result<()> {
        let parent = path
            .parent()
            .filter(|p| !p.as_os_str().is_empty())
            .unwrap_or(Path::new("."));
        let temp = parent.join(format!(
            ".migration-result-{}-{}.tmp",
            std::process::id(),
            NEXT_TEMP.fetch_add(1, Ordering::Relaxed)
        ));
        let mut file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&temp)?;
        let outcome = (|| {
            self.write_to(&mut file, format)?;
            file.sync_all()?;
            drop(file);
            fs::hard_link(&temp, path)
        })();
        let _ = fs::remove_file(&temp);
        outcome
    }
    pub fn load(path: &Path, format: Format) -> Result<Self, String> {
        let mut bytes = Vec::new();
        fs::File::open(path)
            .map_err(|e| e.to_string())?
            .take(MAX_FILE_BYTES + 1)
            .read_to_end(&mut bytes)
            .map_err(|e| e.to_string())?;
        Self::decode(&bytes, format)
    }
}
fn column_specs(
    n: usize,
    channels: usize,
    precision: Precision,
) -> Vec<(&'static str, &'static str, Vec<usize>, Precision)> {
    let bins = n / 2 + 1;
    vec![
        ("window", "1", vec![n], Precision::F64),
        ("fft_over_n", "FS", vec![bins, channels, 2], Precision::F64),
        ("inverse_windowed", "FS", vec![n, channels], precision),
        ("peak_fs", "FS_peak", vec![bins, channels], Precision::F64),
        (
            "tone_rms_fs",
            "FS_RMS",
            vec![bins, channels],
            Precision::F64,
        ),
        ("psd_fs2_hz", "FS2/Hz", vec![bins, channels], Precision::F64),
        (
            "asd_fs_sqrt_hz",
            "FS/sqrt(Hz)",
            vec![bins, channels],
            Precision::F64,
        ),
        ("rms_fs", "FS_RMS", vec![channels], Precision::F64),
        (
            "integrated_power_fs2",
            "FS2",
            vec![channels],
            Precision::F64,
        ),
        (
            "time_window_power_fs2",
            "FS2",
            vec![channels],
            Precision::F64,
        ),
    ]
}
fn csv_encode(rows: &[Vec<String>]) -> String {
    rows.iter()
        .map(|row| {
            row.iter()
                .map(|cell| format!("\"{}\"", cell.replace('"', "\"\"")))
                .collect::<Vec<_>>()
                .join(",")
                + "\n"
        })
        .collect()
}
fn csv_decode(text: &str) -> Result<Vec<Vec<String>>, String> {
    // Strict quoted RFC4180 subset emitted above; accepts commas, quotes and embedded newlines.
    let mut chars = text.chars().peekable();
    let mut rows = Vec::new();
    let mut row = Vec::new();
    while chars.peek().is_some() {
        if chars.next() != Some('"') {
            return Err("invalid_csv_quote".into());
        }
        let mut cell = String::new();
        loop {
            match chars.next() {
                Some('"') if chars.peek() == Some(&'"') => {
                    chars.next();
                    cell.push('"');
                }
                Some('"') => break,
                Some(ch) => cell.push(ch),
                None => return Err("truncated_csv_cell".into()),
            }
        }
        row.push(cell);
        match chars.next() {
            Some(',') => {}
            Some('\n') => {
                rows.push(std::mem::take(&mut row));
            }
            _ => return Err("invalid_csv_delimiter".into()),
        }
    }
    if !row.is_empty() {
        return Err("truncated_csv_row".into());
    }
    Ok(rows)
}
#[cfg(test)]
mod tests;

/// Reject duplicate keys at every depth before typed schema validation.
fn unique_json(bytes: &[u8]) -> Result<Value, String> {
    use serde::de::{self, MapAccess, SeqAccess, Visitor};
    struct Unique(Value);
    struct UniqueVisitor;
    impl<'de> Deserialize<'de> for Unique {
        fn deserialize<D: serde::Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
            d.deserialize_any(UniqueVisitor).map(Self)
        }
    }
    impl<'de> Visitor<'de> for UniqueVisitor {
        type Value = Value;
        fn expecting(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
            f.write_str("JSON with unique object keys")
        }
        fn visit_bool<E: de::Error>(self, v: bool) -> Result<Value, E> {
            Ok(Value::Bool(v))
        }
        fn visit_i64<E: de::Error>(self, v: i64) -> Result<Value, E> {
            Ok(v.into())
        }
        fn visit_u64<E: de::Error>(self, v: u64) -> Result<Value, E> {
            Ok(v.into())
        }
        fn visit_f64<E: de::Error>(self, v: f64) -> Result<Value, E> {
            serde_json::Number::from_f64(v)
                .map(Value::Number)
                .ok_or_else(|| E::custom("nonfinite JSON"))
        }
        fn visit_str<E: de::Error>(self, v: &str) -> Result<Value, E> {
            Ok(Value::String(v.into()))
        }
        fn visit_string<E: de::Error>(self, v: String) -> Result<Value, E> {
            Ok(Value::String(v))
        }
        fn visit_unit<E: de::Error>(self) -> Result<Value, E> {
            Ok(Value::Null)
        }
        fn visit_seq<A: SeqAccess<'de>>(self, mut a: A) -> Result<Value, A::Error> {
            let mut values = Vec::new();
            while let Some(Unique(v)) = a.next_element()? {
                values.push(v);
            }
            Ok(Value::Array(values))
        }
        fn visit_map<A: MapAccess<'de>>(self, mut a: A) -> Result<Value, A::Error> {
            let mut values = serde_json::Map::new();
            while let Some((key, Unique(v))) = a.next_entry::<String, Unique>()? {
                if values.insert(key, v).is_some() {
                    return Err(de::Error::custom("duplicate JSON key"));
                }
            }
            Ok(Value::Object(values))
        }
    }
    serde_json::from_slice::<Unique>(bytes)
        .map(|v| v.0)
        .map_err(|e| e.to_string())
}
