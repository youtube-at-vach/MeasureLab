//! Native counterpart of the independently evaluated Python compatibility adapter.
//! Product 1.0 traces are finite projections; the reserved carrier retains the full
//! validated snapshot. CSV and its hash-bound sidecar publish independently.
use crate::result::{Format, MeasurementResult, unique_json};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::fs::{self, OpenOptions};
use std::io::{self, Read, Write};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};

const MAX_BYTES: usize = 256 * 1024 * 1024;
const MAX_VALUES: usize = 4_000_000;
const MARKER: &str = "mig_006_e_snapshot";
const CSV_KIND: &str = "MIG-006-E-product-csv";
const TRACE_KEYS: [&str; 13] = [
    "id",
    "name",
    "source_module",
    "timestamp",
    "plot_type",
    "x_axis",
    "y_axis",
    "y2_axis",
    "x_data",
    "y_data",
    "y2_data",
    "calibration",
    "metadata",
];
static NEXT_TEMP: AtomicU64 = AtomicU64::new(1);

#[derive(Clone, Copy, Debug, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ProductFormat {
    ProductJson,
    ProductCsv,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Axis {
    dimension: String,
    base_unit: String,
    display_unit: String,
    is_log: bool,
}
fn axis(dimension: &str, unit: &str) -> Axis {
    Axis {
        dimension: dimension.into(),
        base_unit: unit.into(),
        display_unit: unit.into(),
        is_log: false,
    }
}
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Calibration {
    is_calibrated: bool,
    input_sensitivity: f64,
    applied_offset_db: f64,
    reference_level: String,
}
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Trace {
    id: String,
    name: String,
    source_module: String,
    timestamp: String,
    plot_type: String,
    x_axis: Axis,
    y_axis: Axis,
    y2_axis: Option<Axis>,
    x_data: Vec<f64>,
    y_data: Vec<f64>,
    y2_data: Option<Vec<f64>>,
    calibration: Calibration,
    metadata: serde_json::Map<String, Value>,
}
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Document {
    version: String,
    traces: Vec<Trace>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Envelope {
    version: u32,
    snapshot: Value,
    omitted: Vec<Value>,
}

fn projection(result: &MeasurementResult) -> Result<Document, String> {
    let snapshot = result.to_value();
    let channels = &result.source().channel_ids;
    let n = result.interval()[1] - result.interval()[0];
    let carrier = Trace {
        id: "mig.snapshot".into(),
        name: "Snapshot metadata (no measurement values)".into(),
        source_module: "MIG-006-E".into(),
        timestamp: String::new(),
        plot_type: "spectrum".into(),
        x_axis: axis("frequency", "Hz"),
        y_axis: axis("unknown", ""),
        y2_axis: None,
        x_data: vec![],
        y_data: vec![],
        y2_data: None,
        calibration: Calibration {
            is_calibrated: false,
            input_sensitivity: 1.0,
            applied_offset_db: 0.0,
            reference_level: "relative".into(),
        },
        metadata: serde_json::Map::new(),
    };
    let mut traces = vec![carrier.clone()];
    let mut omitted = Vec::new();
    let mut count = 0usize;
    // serde_json's default map is ordered, matching Python's sorted(columns).
    for (metric, column) in snapshot["columns"].as_object().unwrap() {
        let values = column["values"].as_array().unwrap();
        let reasons = column["reasons"].as_array().unwrap();
        for index in 0..if metric == "window" {
            1
        } else {
            channels.len()
        } {
            let channel_id = (metric != "window").then(|| &channels[index]);
            let stride = if metric == "window" {
                1
            } else {
                channels.len()
            };
            let indexes: Vec<_> = if metric == "fft_over_n" {
                (2 * index..values.len()).step_by(2 * stride).collect()
            } else if column["shape"].as_array().unwrap().len() == 1 && metric != "window" {
                vec![index]
            } else {
                (index..values.len()).step_by(stride).collect()
            };
            let complex = metric == "fft_over_n";
            let mut reason_values: Vec<_> = indexes.iter().map(|i| reasons[*i].clone()).collect();
            if complex {
                reason_values.extend(indexes.iter().map(|i| reasons[*i + 1].clone()));
            }
            if reason_values.iter().any(|r| !r.is_null()) {
                omitted.push(
                    json!({"metric": metric, "channel_id": channel_id, "reasons": reason_values}),
                );
                continue;
            }
            let (x, x_axis) = if metric == "window" || metric == "inverse_windowed" {
                if n > MAX_VALUES as u64 {
                    return Err("product_numeric_capacity".into());
                }
                (
                    (0..n).map(|v| v as f64).collect(),
                    axis("sample_offset", "sample"),
                )
            } else if column["shape"].as_array().unwrap().len() == 1 {
                (vec![index as f64], axis("channel_index", "1"))
            } else {
                let key = if metric == "psd_v2_hz" {
                    "corrected"
                } else {
                    "nominal"
                };
                (
                    serde_json::from_value(snapshot["axis"][key].clone())
                        .map_err(|e| e.to_string())?,
                    axis("frequency", "Hz"),
                )
            };
            let y: Vec<_> = indexes
                .iter()
                .map(|i| values[*i].as_f64().unwrap())
                .collect();
            let y2: Option<Vec<_>> = complex.then(|| {
                indexes
                    .iter()
                    .map(|i| values[*i + 1].as_f64().unwrap())
                    .collect()
            });
            count = count
                .checked_add(x.len() + y.len() + y2.as_ref().map_or(0, Vec::len))
                .ok_or("product_numeric_capacity")?;
            if count > MAX_VALUES || traces.len() == 1024 {
                return Err("product_numeric_capacity".into());
            }
            let absolute = matches!(metric.as_str(), "rms_v" | "dbv" | "psd_v2_hz" | "spl");
            let profile = channel_id.map(|_| &snapshot["calibration"][index]["profile"]);
            let unit = column["unit"].as_str().unwrap();
            let mut trace = carrier.clone();
            trace.id = format!("mig.{metric}.{index}");
            trace.name = format!("{metric}: {}", channel_id.map_or("window", String::as_str));
            trace.plot_type = if x_axis.dimension == "frequency" {
                "spectrum"
            } else {
                "xy_plot"
            }
            .into();
            trace.x_axis = x_axis;
            trace.y_axis = axis(if absolute { "voltage" } else { "amplitude" }, unit);
            trace.y2_axis = complex.then(|| axis("amplitude", unit));
            trace.x_data = x;
            trace.y_data = y;
            trace.y2_data = y2;
            trace.calibration = Calibration {
                is_calibrated: absolute && profile.is_some_and(|p| p["is_calibrated"] == true),
                input_sensitivity: profile.and_then(|p| p["v_per_fs"].as_f64()).unwrap_or(1.0),
                applied_offset_db: 0.0,
                reference_level: if absolute { "absolute" } else { "relative" }.into(),
            };
            trace.metadata = json!({"metric": metric, "channel_id": channel_id, "precision": column["precision"]}).as_object().unwrap().clone();
            traces.push(trace);
        }
    }
    traces[0].metadata.insert(
        MARKER.into(),
        json!({"version": 1, "snapshot": snapshot, "omitted": omitted}),
    );
    Ok(Document {
        version: "1.0".into(),
        traces,
    })
}

fn decode_document(document: &Document) -> Result<MeasurementResult, String> {
    if document.version != "1.0" || document.traces.is_empty() || document.traces.len() > 1024 {
        return Err("unsupported_product_schema".into());
    }
    let marked: Vec<_> = document
        .traces
        .iter()
        .filter(|t| t.metadata.contains_key(MARKER))
        .collect();
    if marked.len() != 1 || !std::ptr::eq(marked[0], &document.traces[0]) {
        return Err("first_unique_snapshot_carrier_required_legacy_provenance_unknown".into());
    }
    let envelope: Envelope =
        serde_json::from_value(marked[0].metadata[MARKER].clone()).map_err(|e| e.to_string())?;
    if envelope.version != 1 {
        return Err("unsupported_product_envelope".into());
    }
    let result = MeasurementResult::decode(
        &serde_json::to_vec(&envelope.snapshot).map_err(|e| e.to_string())?,
        Format::Json,
    )?;
    let expected = projection(&result)?;
    if serde_json::to_vec(&expected).map_err(|e| e.to_string())?
        != serde_json::to_vec(&document).map_err(|e| e.to_string())?
        || expected.traces[0].metadata[MARKER]["omitted"] != json!(envelope.omitted)
    {
        return Err("product_projection_snapshot_mismatch".into());
    }
    Ok(result)
}

// Do not silently round legacy integer arrays while deserializing to f64.
fn exact_numeric(value: &Value) -> bool {
    let Some(n) = value.as_number() else {
        return false;
    };
    let Some(f) = n.as_f64().filter(|f| f.is_finite()) else {
        return false;
    };
    n.as_i64().is_none_or(|i| i128::from(i) == f as i128)
        && n.as_u64().is_none_or(|i| i128::from(i) == f as i128)
}
fn validate_trace_fields(value: &Value, with_arrays: bool) -> Result<(), String> {
    let map = value.as_object().ok_or("invalid_product_trace")?;
    let fields: Vec<_> = TRACE_KEYS
        .iter()
        .filter(|k| with_arrays || !matches!(**k, "x_data" | "y_data" | "y2_data"))
        .collect();
    if map.len() != fields.len() || fields.iter().any(|k| !map.contains_key(**k)) {
        return Err("invalid_product_trace_fields".into());
    }
    for key in ["input_sensitivity", "applied_offset_db"] {
        if !exact_numeric(&value["calibration"][key]) {
            return Err("invalid_product_calibration".into());
        }
    }
    Ok(())
}
fn json_document(bytes: &[u8]) -> Result<Document, String> {
    let value = parse_json(bytes)?;
    let traces = value["traces"].as_array().ok_or("invalid_product_traces")?;
    if traces.len() > 1024 {
        return Err("product_trace_capacity".into());
    }
    let mut count = 0usize;
    for trace in traces {
        validate_trace_fields(trace, true)?;
        for key in ["x_data", "y_data", "y2_data"] {
            if key == "y2_data" && trace[key].is_null() {
                continue;
            }
            let values = trace[key].as_array().ok_or("invalid_product_array")?;
            count = count
                .checked_add(values.len())
                .ok_or("product_numeric_capacity")?;
            if count > MAX_VALUES || values.iter().any(|v| !exact_numeric(v)) {
                return Err("invalid_product_numeric_array".into());
            }
        }
    }
    serde_json::from_value(value).map_err(|e| e.to_string())
}
pub fn decode_json(bytes: &[u8]) -> Result<MeasurementResult, String> {
    decode_document(&json_document(bytes)?)
}
pub fn encode_json(result: &MeasurementResult) -> Result<Vec<u8>, String> {
    bounded(serde_json::to_vec(&projection(result)?).map_err(|e| e.to_string())?)
}
fn bounded(bytes: Vec<u8>) -> Result<Vec<u8>, String> {
    if bytes.len() > MAX_BYTES {
        Err("product_file_capacity".into())
    } else {
        Ok(bytes)
    }
}
fn parse_json(bytes: &[u8]) -> Result<Value, String> {
    if bytes.len() > MAX_BYTES {
        return Err("product_file_capacity".into());
    }
    // serde_json without arbitrary_precision promotes out-of-range integer
    // tokens to f64. Reject them before parsing, including nested metadata,
    // rather than silently rounding snapshot metadata or its descriptors.
    let (mut i, mut in_string) = (0, false);
    while i < bytes.len() {
        match bytes[i] {
            b'\\' if in_string => i += 1,
            b'"' => in_string = !in_string,
            b'-' | b'0'..=b'9' if !in_string => {
                let start = i;
                while i < bytes.len()
                    && matches!(bytes[i], b'-' | b'+' | b'0'..=b'9' | b'.' | b'e' | b'E')
                {
                    i += 1;
                }
                let token = &bytes[start..i];
                if !token.iter().any(|b| matches!(b, b'.' | b'e' | b'E')) {
                    let token = std::str::from_utf8(token).map_err(|e| e.to_string())?;
                    if token.parse::<i64>().is_err() && token.parse::<u64>().is_err() {
                        return Err("product_integer_outside_64_bit".into());
                    }
                }
                continue;
            }
            _ => (),
        }
        i += 1;
    }
    unique_json(bytes)
}
fn read(path: &Path) -> Result<Vec<u8>, String> {
    let mut bytes = Vec::new();
    fs::File::open(path)
        .map_err(|e| e.to_string())?
        .take(MAX_BYTES as u64 + 1)
        .read_to_end(&mut bytes)
        .map_err(|e| e.to_string())?;
    bounded(bytes)
}
pub fn sidecar_path(path: &Path) -> PathBuf {
    let mut name = path.as_os_str().to_owned();
    name.push(".metadata.json");
    PathBuf::from(name)
}
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Options {
    layout: String,
    delimiter: String,
    include_headers: bool,
    include_metadata: bool,
    utf8_bom: bool,
}
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Sidecar {
    schema_version: u32,
    kind: String,
    csv_sha256: String,
    options: Options,
    descriptors: Vec<Value>,
}
fn hash(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}
fn encode_csv(result: &MeasurementResult) -> Result<(Vec<u8>, Vec<u8>), String> {
    let doc = projection(result)?;
    // A valid existing product option set; no translated labels are needed on a file worker.
    let options = Options {
        layout: "independent".into(),
        delimiter: "comma".into(),
        include_headers: false,
        include_metadata: false,
        utf8_bom: false,
    };
    let columns: Vec<_> = doc
        .traces
        .iter()
        .flat_map(|t| {
            std::iter::once(&t.x_data)
                .chain(std::iter::once(&t.y_data))
                .chain(t.y2_data.iter())
        })
        .collect();
    let mut writer = csv::WriterBuilder::new()
        .terminator(csv::Terminator::CRLF)
        .from_writer(Vec::new());
    for i in 0..columns.iter().map(|c| c.len()).max().unwrap_or(0) {
        writer
            .write_record(
                columns
                    .iter()
                    .map(|c| c.get(i).map_or_else(String::new, |v| v.to_string())),
            )
            .map_err(|e| e.to_string())?;
    }
    let bytes = bounded(writer.into_inner().map_err(|e| e.to_string())?)?;
    let descriptors = doc
        .traces
        .iter()
        .map(|t| {
            let mut value = serde_json::to_value(t).unwrap();
            for key in ["x_data", "y_data", "y2_data"] {
                value.as_object_mut().unwrap().remove(key);
            }
            value
        })
        .collect();
    let sidecar = bounded(
        serde_json::to_vec(&Sidecar {
            schema_version: 1,
            kind: CSV_KIND.into(),
            csv_sha256: hash(&bytes),
            options,
            descriptors,
        })
        .map_err(|e| e.to_string())?,
    )?;
    Ok((bytes, sidecar))
}
fn sanitize(text: &str) -> String {
    let text = text.replace(['\r', '\n'], " ");
    if text.starts_with(['=', '+', '-', '@', '\t']) {
        format!("'{text}")
    } else {
        text
    }
}
fn validate_csv_syntax(text: &str, delimiter: u8, separator: Option<usize>) -> Result<(), String> {
    // csv::Reader tolerates unterminated quotes and silently skips blank records.
    // Reject those before it parses cells; only the exporter metadata separator
    // may be blank. Header labels may still contain quoted commas/newlines.
    let bytes = text.strip_prefix('\u{feff}').unwrap_or(text).as_bytes();
    let (mut i, mut state, mut row) = (0, 0, 0);
    let (mut empty, mut saw_separator) = (true, false);
    while i < bytes.len() {
        let ch = bytes[i];
        if state == 2 {
            if ch == b'"' {
                if bytes.get(i + 1) == Some(&b'"') {
                    i += 1;
                } else {
                    state = 3;
                }
            }
        } else if ch == b'\r' || ch == b'\n' {
            if empty {
                if separator != Some(row) {
                    return Err("product_csv_blank_record".into());
                }
                saw_separator = true;
            } else if separator == Some(row) {
                return Err("missing_product_metadata_separator".into());
            }
            if ch == b'\r' && bytes.get(i + 1) == Some(&b'\n') {
                i += 1;
            }
            row += 1;
            state = 0;
            empty = true;
        } else if ch == delimiter {
            state = 0;
            empty = false;
        } else if ch == b'"' && state == 0 {
            state = 2;
            empty = false;
        } else if ch == b'"' || state == 3 {
            return Err("invalid_product_csv_quote".into());
        } else {
            state = 1;
            empty = false;
        }
        i += 1;
    }
    if state == 2 || (separator.is_some() && !saw_separator) {
        return Err("truncated_product_csv".into());
    }
    Ok(())
}
fn csv_pair_document(bytes: &[u8], metadata: &[u8]) -> Result<Document, String> {
    if bytes.len() > MAX_BYTES {
        return Err("product_file_capacity".into());
    }
    let sidecar: Sidecar =
        serde_json::from_value(parse_json(metadata)?).map_err(|e| e.to_string())?;
    if sidecar.schema_version != 1
        || sidecar.kind != CSV_KIND
        || sidecar.csv_sha256 != hash(bytes)
        || sidecar.options.layout != "independent"
    {
        return Err("mismatched_or_unsupported_product_sidecar".into());
    }
    csv_document(bytes, &sidecar.options, sidecar.descriptors)
}
fn csv_document(bytes: &[u8], opts: &Options, descriptors: Vec<Value>) -> Result<Document, String> {
    if bytes.len() > MAX_BYTES {
        return Err("product_file_capacity".into());
    }
    if opts.layout != "independent"
        || !matches!(opts.delimiter.as_str(), "comma" | "tab")
        || descriptors.len() > 1024
    {
        return Err("unsupported_product_csv_spec".into());
    }
    let mut traces = Vec::new();
    for mut value in descriptors {
        validate_trace_fields(&value, false)?;
        let secondary = !value["y2_axis"].is_null();
        let map = value.as_object_mut().ok_or("invalid_product_descriptor")?;
        for key in ["x_data", "y_data", "y2_data"] {
            if map.contains_key(key) {
                return Err("product_descriptor_contains_arrays".into());
            }
            map.insert(
                key.into(),
                if key == "y2_data" && !secondary {
                    Value::Null
                } else {
                    json!([])
                },
            );
        }
        traces.push(serde_json::from_value::<Trace>(value).map_err(|e| e.to_string())?);
    }
    let text = std::str::from_utf8(bytes).map_err(|e| e.to_string())?;
    if text.starts_with('\u{feff}') && !opts.utf8_bom {
        return Err("unexpected_product_bom".into());
    }
    let delimiter = if opts.delimiter == "comma" {
        b','
    } else {
        b'\t'
    };
    validate_csv_syntax(
        text,
        delimiter,
        opts.include_metadata.then_some(traces.len() + 1),
    )?;
    let mut reader = csv::ReaderBuilder::new()
        .has_headers(false)
        .flexible(true)
        .delimiter(delimiter)
        .from_reader(text.as_bytes());
    let mut records = reader.records();
    // The csv crate skips empty separator lines, which carry no measurement data.
    if opts.include_metadata {
        let mut expected = vec!["# MeasureLab Exported Traces".into()];
        expected.extend(traces.iter().map(|t| {
            format!(
                "# Trace: {} (Source: {}, Timestamp: {})",
                sanitize(&t.name),
                sanitize(&t.source_module),
                t.timestamp
            )
        }));
        for line in expected {
            let row = records
                .next()
                .ok_or("missing_product_metadata")?
                .map_err(|e| e.to_string())?;
            if row.len() != 1 || row[0] != line {
                return Err("product_metadata_mismatch".into());
            }
        }
    }
    let width: usize = traces
        .iter()
        .map(|t| 2 + usize::from(t.y2_axis.is_some()))
        .sum();
    if opts.include_headers
        && records
            .next()
            .ok_or("missing_product_header")?
            .map_err(|e| e.to_string())?
            .len()
            != width
    {
        return Err("product_header_width".into());
    }
    let mut ended = vec![false; traces.len()];
    let mut count = 0usize;
    for record in records {
        let row = record.map_err(|e| e.to_string())?;
        if row.len() != width {
            return Err("product_csv_width".into());
        }
        let numeric = |cell: &str| {
            cell.parse::<f64>()
                .ok()
                .filter(|f| f.is_finite())
                .ok_or("product_csv_numeric")
        };
        let mut offset = 0;
        for (i, t) in traces.iter_mut().enumerate() {
            let size = 2 + usize::from(t.y2_axis.is_some());
            let cells: Vec<_> = row.iter().skip(offset).take(size).collect();
            offset += size;
            if cells.iter().all(|c| c.is_empty()) {
                ended[i] = true;
                continue;
            }
            if ended[i] || cells.iter().any(|c| c.is_empty()) {
                return Err("product_csv_interior_padding".into());
            }
            let values = cells
                .iter()
                .map(|c| numeric(c))
                .collect::<Result<Vec<_>, _>>()?;
            count += values.len();
            if count > MAX_VALUES {
                return Err("product_numeric_capacity".into());
            }
            t.x_data.push(values[0]);
            t.y_data.push(values[1]);
            if let Some(y2) = &mut t.y2_data {
                y2.push(values[2]);
            }
        }
    }
    Ok(Document {
        version: "1.0".into(),
        traces,
    })
}
pub fn decode_csv_pair(bytes: &[u8], metadata: &[u8]) -> Result<MeasurementResult, String> {
    decode_document(&csv_pair_document(bytes, metadata)?)
}
pub fn load(path: &Path, format: ProductFormat) -> Result<MeasurementResult, String> {
    let bytes = read(path)?;
    match format {
        ProductFormat::ProductJson => decode_json(&bytes),
        ProductFormat::ProductCsv => decode_csv_pair(&bytes, &read(&sidecar_path(path))?),
    }
}
fn publish(path: &Path, bytes: &[u8]) -> io::Result<()> {
    let parent = path
        .parent()
        .filter(|p| !p.as_os_str().is_empty())
        .unwrap_or(Path::new("."));
    let temp = parent.join(format!(
        ".migration-product-{}-{}.tmp",
        std::process::id(),
        NEXT_TEMP.fetch_add(1, Ordering::Relaxed)
    ));
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&temp)?;
    let outcome = (|| {
        file.write_all(bytes)?;
        file.flush()?;
        file.sync_all()?;
        drop(file);
        fs::hard_link(&temp, path)
    })();
    let _ = fs::remove_file(temp);
    outcome
}
/// File-worker only. CSV success requires both publications; a sidecar failure may
/// leave an orphan CSV. Never replace a destination or report a partial pair saved.
pub fn save_new(result: &MeasurementResult, path: &Path, format: ProductFormat) -> io::Result<()> {
    match format {
        ProductFormat::ProductJson => {
            publish(path, &encode_json(result).map_err(io::Error::other)?)
        }
        ProductFormat::ProductCsv => {
            let (csv, metadata) = encode_csv(result).map_err(io::Error::other)?;
            publish(path, &csv)?;
            publish(&sidecar_path(path), &metadata)
        }
    }
}

#[cfg(test)]
mod tests;
