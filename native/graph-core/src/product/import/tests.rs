use super::*;
use crate::export::tests::{Directory, snapshot};

fn legacy() -> Value {
    json!({"version": "1.0", "traces": [{
        "id": "old.trace", "name": "旧測定", "source_module": "spectrum",
        "timestamp": "2026-10-02T09:00:00+09:00", "plot_type": "frequency_response",
        "x_axis": axis("frequency", "kHz"), "y_axis": axis("voltage", "dBV"),
        "y2_axis": axis("phase", "deg"), "x_data": [-0.0, 1.0],
        "y_data": [-9.0, -3.5], "y2_data": [-180.0, 0.0],
        "calibration": {"is_calibrated": true, "input_sensitivity": 0.125,
            "applied_offset_db": 2.75, "reference_level": "absolute"},
        "metadata": {"nested": {"note": "unit conversion already applied", "unknown": null}}
    }]})
}
fn bytes(value: &Value) -> Vec<u8> {
    serde_json::to_vec(value).unwrap()
}
fn specification(document: &Value, layout: &str) -> Value {
    let descriptors: Vec<_> = document["traces"]
        .as_array()
        .unwrap()
        .iter()
        .map(|t| {
            let mut descriptor = t.clone();
            for key in ["x_data", "y_data", "y2_data"] {
                descriptor.as_object_mut().unwrap().remove(key);
            }
            descriptor
        })
        .collect();
    json!({"options": {"layout": layout, "delimiter": "comma", "include_headers": false,
        "include_metadata": false, "utf8_bom": false}, "descriptors": descriptors})
}

#[test]
fn legacy_json_retains_values_metadata_and_signed_zero_without_inventing_a_result() {
    let expected = legacy();
    let loaded = import_json(&bytes(&expected)).unwrap();
    assert_eq!(loaded.document(), expected);
    assert!(
        loaded.document()["traces"][0]["x_data"][0]
            .as_f64()
            .unwrap()
            .is_sign_negative()
    );
    assert!(loaded.snapshot().is_none());
    assert!(
        loaded
            .acquisition()
            .as_object()
            .unwrap()
            .values()
            .all(Value::is_null)
    );
    assert_eq!(
        loaded.sample_relation(),
        SampleRelation::OriginalTraceArrays
    );
    // The existing result-only reader continues to reject carrier-free traces.
    assert!(decode_json(&bytes(&expected)).is_err());
    let empty = import_json(br#"{"version":"1.0","traces":[]}"#).unwrap();
    assert!(empty.snapshot().is_none());
}

#[test]
fn legacy_identity_shapes_calibration_and_required_fields_are_validated() {
    for fault in 0..16 {
        let mut doc = legacy();
        let t = &mut doc["traces"][0];
        match fault {
            0 => t["id"] = json!(""),
            1 => {
                let trace = t.clone();
                doc["traces"].as_array_mut().unwrap().push(trace);
            }
            2 => t["y_data"] = json!([]),
            3 => t["y2_axis"] = Value::Null,
            4 => t["y2_data"] = Value::Null,
            5 => {
                t.as_object_mut().unwrap().remove("y2_axis");
            }
            6 => t["y_data"][0] = json!(true),
            7 => t["y_data"][0] = json!(9_007_199_254_740_993u64),
            8 => t["calibration"]["input_sensitivity"] = json!(0.0),
            9 => t["calibration"]["reference_level"] = json!("unknown"),
            10 => t["calibration"]["is_calibrated"] = json!("false"),
            11 => t["x_axis"]["is_log"] = json!(1),
            12 => {
                t["x_axis"].as_object_mut().unwrap().remove("display_unit");
            }
            13 => t["extra"] = Value::Null,
            14 => doc["version"] = json!("2.0"),
            _ => t["metadata"] = Value::Null,
        }
        assert!(import_json(&bytes(&doc)).is_err(), "fault {fault}");
    }
    for payload in [
        b"{\"version\":\"1.0\",\"version\":\"1.0\",\"traces\":[]}".as_slice(),
        br#"{"version":"1.0","traces":[],"bad":NaN}"#,
        br#"{"version":"1.0","traces":[]"#,
    ] {
        assert!(import_json(payload).is_err());
    }
}

#[test]
fn complete_carriers_restore_all_null_reasons_and_never_fall_back_on_damage() {
    let expected = snapshot(2.0);
    let original = encode_json(&expected).unwrap();
    let imported = import_json(&original).unwrap();
    assert_eq!(imported.snapshot().unwrap().to_value(), expected.to_value());
    assert!(!imported.acquisition()["stream_id"].is_null());
    for fault in 0..4 {
        let mut doc = unique_json(&original).unwrap();
        match fault {
            0 => doc["traces"][0]["metadata"][MARKER] = Value::Null,
            1 => doc["traces"][1]["y_data"][0] = json!(999.0),
            2 => doc["traces"].as_array_mut().unwrap().swap(0, 1),
            _ => {
                let t = doc["traces"][0].clone();
                doc["traces"].as_array_mut().unwrap().push(t);
            }
        }
        assert!(import_json(&bytes(&doc)).is_err());
    }
    let (csv, sidecar) = encode_csv(&expected).unwrap();
    assert_eq!(
        import_csv_pair(&csv, &sidecar)
            .unwrap()
            .snapshot()
            .unwrap()
            .to_value(),
        expected.to_value()
    );
    assert!(import_csv_pair(b"modified", &sidecar).is_err());
}

#[test]
fn csv_requires_explicit_descriptors_and_marks_merged_grid_without_recalibration() {
    let doc = legacy();
    for layout in ["independent", "merged"] {
        let payload = b"-0,-9,-180\r\n1,-3.5,0\r\n";
        let imported = import_csv(payload, &bytes(&specification(&doc, layout))).unwrap();
        assert_eq!(imported.document(), doc);
        assert!(imported.snapshot().is_none());
        assert!(imported.acquisition()["timebase"].is_null());
        assert_eq!(
            imported.sample_relation(),
            if layout == "independent" {
                SampleRelation::OriginalTraceArrays
            } else {
                SampleRelation::MergedGridMayBeInterpolated
            }
        );
    }
    assert!(import_csv(b"0,1,2\n", b"{}").is_err());
    for fault in 0..4 {
        let mut spec = specification(&doc, "independent");
        match fault {
            0 => spec["options"]["layout"] = json!("guess"),
            1 => spec["options"]["include_headers"] = json!("false"),
            2 => {
                spec["descriptors"][0]
                    .as_object_mut()
                    .unwrap()
                    .remove("calibration");
            }
            _ => spec["descriptors"][0]["x_data"] = json!([]),
        }
        assert!(import_csv(b"0,1,2\n", &bytes(&spec)).is_err());
    }
}

#[test]
fn csv_rejects_nonfinite_truncated_quotes_width_missing_values_and_interior_padding() {
    let spec = bytes(&specification(&legacy(), "independent"));
    for payload in [
        b"0,NaN,2\n".as_slice(),
        b"0,inf,2\n",
        b"0,1\n",
        b"0,,2\n",
        b"0,1,2\n\n",
        b"\"0,1,2\n",
        b",,\n0,1,2\n",
    ] {
        assert!(import_csv(payload, &spec).is_err(), "payload {payload:?}");
    }
}

#[test]
fn file_import_is_read_only_missing_pairs_fail_and_the_next_import_recovers() {
    let dir = Directory::new();
    let path = dir.file("old.json");
    let original = bytes(&legacy());
    fs::write(&path, &original).unwrap();
    assert!(load_import(&path, ProductFormat::ProductCsv).is_err());
    assert_eq!(
        load_import(&path, ProductFormat::ProductJson)
            .unwrap()
            .document(),
        legacy()
    );
    assert_eq!(fs::read(&path).unwrap(), original);
    let expected = snapshot(2.0);
    let path = dir.file("result.csv");
    save_new(&expected, &path, ProductFormat::ProductCsv).unwrap();
    let before = fs::read(&path).unwrap();
    assert_eq!(
        load_import(&path, ProductFormat::ProductCsv)
            .unwrap()
            .snapshot()
            .unwrap()
            .to_value(),
        expected.to_value()
    );
    assert_eq!(fs::read(&path).unwrap(), before);
}

#[test]
fn out_of_range_integer_tokens_are_never_silently_rounded_in_arrays_or_metadata() {
    let original = String::from_utf8(bytes(&legacy())).unwrap();
    for bad in [
        "18446744073709551617",
        "-9223372036854775809",
        "100000000000000000000000000000000001",
    ] {
        assert!(import_json(original.replace("-9.0", bad).as_bytes()).is_err());
        assert!(
            import_json(
                original
                    .replace("\"unknown\":null", &format!("\"unknown\":{bad}"))
                    .as_bytes()
            )
            .is_err()
        );
    }
    // Digits/escaped quotes inside strings are not numeric tokens.
    let mut value = legacy();
    value["traces"][0]["metadata"]["integer_text"] = json!("\\\"18446744073709551617\"");
    assert_eq!(import_json(&bytes(&value)).unwrap().document(), value);
}

#[test]
fn trace_and_numeric_capacity_limits_reject_oversize_observations() {
    let mut document = json_document(&bytes(&legacy())).unwrap();
    document.traces = vec![document.traces[0].clone(); 1025];
    assert!(import_document(document, SampleRelation::OriginalTraceArrays).is_err());
    let mut document = json_document(&bytes(&legacy())).unwrap();
    let trace = &mut document.traces[0];
    trace.y2_axis = None;
    trace.y2_data = None;
    trace.x_data = vec![0.0; MAX_VALUES / 2 + 1];
    trace.y_data = vec![0.0; MAX_VALUES / 2 + 1];
    assert!(import_document(document, SampleRelation::OriginalTraceArrays).is_err());
}
