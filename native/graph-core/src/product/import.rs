//! File-worker import boundary. Legacy observations never acquire fabricated
//! stream IDs, clocks, calibration revisions or a MeasurementResult.
use super::*;
use std::collections::HashSet;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum SampleRelation {
    OriginalTraceArrays,
    MergedGridMayBeInterpolated,
}

/// Validated traces and, only when a verified carrier exists, the full result.
/// There is no mutable access or unchecked deserialization into this type.
#[derive(Clone, Debug)]
pub struct ImportedProduct {
    document: Document,
    snapshot: Option<MeasurementResult>,
    relation: SampleRelation,
}
impl ImportedProduct {
    pub fn document(&self) -> Value {
        serde_json::to_value(&self.document).expect("finite validated product traces")
    }
    pub fn snapshot(&self) -> Option<&MeasurementResult> {
        self.snapshot.as_ref()
    }
    pub fn sample_relation(&self) -> SampleRelation {
        self.relation
    }
    /// Null means unknown. Trace ID/timestamp/axes cannot establish acquisition
    /// provenance; restored profiles remain result metadata, not active settings.
    pub fn acquisition(&self) -> Value {
        match &self.snapshot {
            None => json!({"stream_id": null, "generation": null, "channel_ids": null,
                "interval": null, "timebase": null, "trigger": null,
                "route_revision": null, "tap": null}),
            Some(result) => {
                let source = result.source();
                json!({"stream_id": source.stream_id, "generation": source.generation,
                    "channel_ids": source.channel_ids, "interval": result.interval(),
                    "timebase": source.timebase, "trigger": result.capture().trigger,
                    "route_revision": source.route_revision, "tap": source.tap})
            }
        }
    }
    pub fn to_value(&self) -> Value {
        json!({"document": self.document(),
            "snapshot": self.snapshot.as_ref().map(MeasurementResult::to_value),
            "acquisition": self.acquisition(), "sample_relation": self.relation})
    }
}

fn validate(document: &Document) -> Result<(), String> {
    if document.version != "1.0" || document.traces.len() > 1024 {
        return Err("unsupported_product_schema".into());
    }
    let mut ids = HashSet::new();
    let mut count = 0usize;
    for trace in &document.traces {
        if trace.id.is_empty() || !ids.insert(&trace.id) {
            return Err("duplicate_or_empty_product_trace_id".into());
        }
        if trace.y2_data.is_some() != trace.y2_axis.is_some()
            || trace.x_data.len() != trace.y_data.len()
            || trace
                .y2_data
                .as_ref()
                .is_some_and(|y| y.len() != trace.x_data.len())
        {
            return Err("product_trace_axis_shape_mismatch".into());
        }
        let calibration = &trace.calibration;
        if !calibration.input_sensitivity.is_finite()
            || calibration.input_sensitivity <= 0.0
            || !calibration.applied_offset_db.is_finite()
            || !matches!(
                calibration.reference_level.as_str(),
                "relative" | "absolute"
            )
        {
            return Err("invalid_product_calibration".into());
        }
        for column in std::iter::once(&trace.x_data)
            .chain(std::iter::once(&trace.y_data))
            .chain(trace.y2_data.iter())
        {
            count = count
                .checked_add(column.len())
                .ok_or("product_numeric_capacity")?;
            if count > MAX_VALUES || column.iter().any(|v| !v.is_finite()) {
                return Err("invalid_product_numeric_array".into());
            }
        }
    }
    Ok(())
}
fn import_document(
    document: Document,
    relation: SampleRelation,
) -> Result<ImportedProduct, String> {
    validate(&document)?;
    let marked = document
        .traces
        .iter()
        .any(|t| t.metadata.contains_key(MARKER));
    let snapshot = if marked {
        if relation != SampleRelation::OriginalTraceArrays {
            return Err("merged_product_snapshot_unsupported".into());
        }
        // A damaged/reserved carrier never falls back to an unknown legacy trace.
        Some(decode_document(&document)?)
    } else {
        None
    };
    Ok(ImportedProduct {
        document,
        snapshot,
        relation,
    })
}

/// Worker-only: allocation, parsing and full snapshot validation are synchronous.
pub fn import_json(bytes: &[u8]) -> Result<ImportedProduct, String> {
    import_document(json_document(bytes)?, SampleRelation::OriginalTraceArrays)
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct CsvSpec {
    options: Options,
    descriptors: Vec<Value>,
}
/// Explicit descriptors/options are mandatory. Translated headers supply neither
/// units nor calibration. Merged values stay on the stored grid without inversion.
pub fn import_csv(bytes: &[u8], specification: &[u8]) -> Result<ImportedProduct, String> {
    let spec: CsvSpec =
        serde_json::from_value(parse_json(specification)?).map_err(|e| e.to_string())?;
    let relation = if spec.options.layout == "independent" {
        SampleRelation::OriginalTraceArrays
    } else {
        SampleRelation::MergedGridMayBeInterpolated
    };
    import_document(
        csv_document(bytes, &spec.options, spec.descriptors)?,
        relation,
    )
}
pub fn import_csv_pair(bytes: &[u8], sidecar: &[u8]) -> Result<ImportedProduct, String> {
    import_document(
        csv_pair_document(bytes, sidecar)?,
        SampleRelation::OriginalTraceArrays,
    )
}
/// No format sniffing, descriptor inference, or current-session profile mutation.
pub fn load_import(path: &Path, format: ProductFormat) -> Result<ImportedProduct, String> {
    let bytes = read(path)?;
    match format {
        ProductFormat::ProductJson => import_json(&bytes),
        ProductFormat::ProductCsv => import_csv_pair(&bytes, &read(&sidecar_path(path))?),
    }
}
pub fn load_csv_with_spec(path: &Path, specification: &Path) -> Result<ImportedProduct, String> {
    import_csv(&read(path)?, &read(specification)?)
}

#[cfg(test)]
mod tests;
