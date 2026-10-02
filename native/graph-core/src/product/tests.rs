use super::*;
use crate::export::{
    CloseMode, SaveStatus, SaveWorker, SubmitError,
    tests::{Directory, snapshot},
};
use std::sync::{Arc, mpsc};
use std::time::Duration;

const TIMEOUT: Duration = Duration::from_secs(5);

#[test]
fn json_and_csv_preserve_all_values_null_reasons_and_profile_snapshot() {
    let result = snapshot(2.0);
    let doc = projection(&result).unwrap();
    assert!(
        doc.traces[0].metadata[MARKER]["omitted"]
            .as_array()
            .unwrap()
            .len()
            >= 3
    );
    assert!(
        doc.traces
            .iter()
            .all(|t| t.x_data.iter().chain(&t.y_data).all(|f| f.is_finite()))
    );
    assert_eq!(
        decode_json(&encode_json(&result).unwrap())
            .unwrap()
            .to_value(),
        result.to_value()
    );
    let (csv, sidecar) = encode_csv(&result).unwrap();
    assert_eq!(
        decode_csv_pair(&csv, &sidecar).unwrap().to_value(),
        result.to_value()
    );
    assert_ne!(result.to_value(), snapshot(4.0).to_value());
}

#[test]
fn json_carrier_projection_and_numeric_corruption_are_rejected() {
    let bytes = encode_json(&snapshot(2.0)).unwrap();
    let original = unique_json(&bytes).unwrap();
    for fault in 0..9 {
        let mut value = original.clone();
        match fault {
            0 => value["version"] = json!("2.0"),
            1 => value["traces"][0]["metadata"][MARKER]["version"] = json!(2),
            2 => {
                value["traces"][0]["metadata"][MARKER]["snapshot"]["columns"]["rms_fs"]["values"]
                    [0] = json!(999.0)
            }
            3 => value["traces"][1]["y_data"][0] = json!(999.0),
            4 => value["traces"][1]["y_data"][0] = json!(9_007_199_254_740_993u64),
            5 => value["traces"][1]["calibration"]["input_sensitivity"] = json!(true),
            6 => value["traces"][0]["metadata"][MARKER]["omitted"] = json!([]),
            7 => value["traces"].as_array_mut().unwrap().swap(0, 1),
            _ => {
                let carrier = value["traces"][0].clone();
                value["traces"].as_array_mut().unwrap().push(carrier);
            }
        }
        assert!(
            decode_json(&serde_json::to_vec(&value).unwrap()).is_err(),
            "fault {fault}"
        );
    }
    let duplicate = String::from_utf8(bytes.clone()).unwrap().replacen(
        "\"version\":\"1.0\"",
        "\"version\":\"1.0\",\"version\":\"1.0\"",
        1,
    );
    assert!(decode_json(duplicate.as_bytes()).is_err());
    assert!(decode_json(&bytes[..bytes.len() - 1]).is_err());
    let mut legacy = original;
    legacy["traces"].as_array_mut().unwrap().remove(0);
    assert!(
        decode_json(&serde_json::to_vec(&legacy).unwrap())
            .unwrap_err()
            .contains("legacy_provenance_unknown")
    );
}

#[test]
fn missing_optional_trace_fields_and_changed_signed_zero_are_rejected() {
    let original = unique_json(&encode_json(&snapshot(2.0)).unwrap()).unwrap();
    for key in ["y2_axis", "y2_data"] {
        let mut value = original.clone();
        value["traces"][0].as_object_mut().unwrap().remove(key);
        assert!(decode_json(&serde_json::to_vec(&value).unwrap()).is_err());
    }
    let mut value = original;
    let index = value["traces"]
        .as_array()
        .unwrap()
        .iter()
        .position(|t| t["x_data"][0].as_f64() == Some(0.0))
        .unwrap();
    value["traces"][index]["x_data"][0] = json!(-0.0);
    assert!(decode_json(&serde_json::to_vec(&value).unwrap()).is_err());
}

#[test]
fn csv_hash_descriptors_padding_and_changed_numeric_table_are_rejected() {
    let (bytes, metadata) = encode_csv(&snapshot(2.0)).unwrap();
    assert!(decode_csv_pair(b"different bytes", &metadata).is_err());
    for fault in 0..6 {
        let mut sidecar = unique_json(&metadata).unwrap();
        let mut csv = bytes.clone();
        match fault {
            0 => sidecar["schema_version"] = json!(2),
            1 => sidecar["options"]["layout"] = json!("merged"),
            2 => sidecar["descriptors"][0]["x_data"] = json!([]),
            3 => sidecar["descriptors"][1]["y_axis"]["display_unit"] = json!("made up"),
            4 => {
                csv.extend_from_slice(&bytes);
                sidecar["csv_sha256"] = json!(hash(&csv));
            }
            _ => {
                csv = String::from_utf8(bytes.clone())
                    .unwrap()
                    .replacen("0,", "999,", 1)
                    .into_bytes();
                sidecar["csv_sha256"] = json!(hash(&csv));
            }
        }
        assert!(
            decode_csv_pair(&csv, &serde_json::to_vec(&sidecar).unwrap()).is_err(),
            "fault {fault}"
        );
    }
}

#[test]
fn csv_lenient_parser_never_accepts_unclosed_quotes_or_blank_data_records() {
    let (bytes, metadata) = encode_csv(&snapshot(2.0)).unwrap();
    let text = String::from_utf8(bytes.clone()).unwrap();
    let malformed = [
        format!("{text}\n"),
        format!("\"{text}"),
        text.replacen(",", "\"x,", 1),
    ];
    for text in malformed {
        let mut sidecar = unique_json(&metadata).unwrap();
        sidecar["csv_sha256"] = json!(hash(text.as_bytes()));
        assert!(decode_csv_pair(text.as_bytes(), &serde_json::to_vec(&sidecar).unwrap()).is_err());
    }
}

#[test]
fn partial_csv_pair_is_failed_existing_sidecar_is_preserved_and_worker_recovers() {
    let directory = Directory::new();
    let result = snapshot(2.0);
    let path = directory.file("orphan.csv");
    fs::write(sidecar_path(&path), b"existing user metadata").unwrap();
    let mut worker = SaveWorker::start_product(1).unwrap();
    let ticket = worker
        .submit(Arc::clone(&result), path.clone(), ProductFormat::ProductCsv)
        .unwrap();
    assert!(
        matches!(ticket.wait(TIMEOUT).status, SaveStatus::Failed { kind, .. } if kind == "AlreadyExists")
    );
    assert!(path.exists());
    assert_eq!(
        fs::read(sidecar_path(&path)).unwrap(),
        b"existing user metadata"
    );
    assert!(load(&path, ProductFormat::ProductCsv).is_err());
    for (file, format) in [
        ("good.json", ProductFormat::ProductJson),
        ("good.csv", ProductFormat::ProductCsv),
    ] {
        let ticket = worker
            .submit(Arc::clone(&result), directory.file(file), format)
            .unwrap();
        assert_eq!(ticket.wait(TIMEOUT).status, SaveStatus::Saved);
        assert_eq!(
            load(&directory.file(file), format).unwrap().to_value(),
            result.to_value()
        );
        let before = fs::read(directory.file(file)).unwrap();
        assert!(save_new(&result, &directory.file(file), format).is_err());
        assert_eq!(fs::read(directory.file(file)).unwrap(), before);
    }
    worker.join().unwrap();
    assert_eq!(Arc::strong_count(&result), 1);
    assert!(
        fs::read_dir(&directory.0).unwrap().all(|e| !e
            .unwrap()
            .file_name()
            .to_string_lossy()
            .ends_with(".tmp"))
    );
}

#[test]
fn product_writer_retains_bounded_admission_cancel_and_drain_contracts() {
    let directory = Directory::new();
    let (started_tx, started_rx) = mpsc::channel();
    let (release_tx, release_rx) = mpsc::channel();
    let mut worker = SaveWorker::with_writer(2, move |result, path, format| {
        started_tx.send(()).unwrap();
        release_rx.recv_timeout(TIMEOUT).map_err(io::Error::other)?;
        save_new(result, path, format)
    })
    .unwrap();
    let result = snapshot(2.0);
    let first = worker
        .submit(
            Arc::clone(&result),
            directory.file("writing.csv"),
            ProductFormat::ProductCsv,
        )
        .unwrap();
    started_rx.recv_timeout(TIMEOUT).unwrap();
    let queued = worker
        .submit(
            Arc::clone(&result),
            directory.file("cancelled.csv"),
            ProductFormat::ProductCsv,
        )
        .unwrap();
    let busy = matches!(
        worker.submit(
            Arc::clone(&result),
            directory.file("busy.json"),
            ProductFormat::ProductJson
        ),
        Err(SubmitError::Busy)
    );
    let too_late = !first.cancel();
    worker.close(CloseMode::CancelPending);
    let cancelled = queued.receipt().status;
    release_tx.send(()).unwrap();
    worker.join().unwrap();
    assert!(busy && too_late);
    assert_eq!(cancelled, SaveStatus::Cancelled);
    assert_eq!(first.receipt().status, SaveStatus::Saved);
    assert!(!directory.file("cancelled.csv").exists());
    assert!(!sidecar_path(&directory.file("cancelled.csv")).exists());
    assert_eq!(
        load(&directory.file("writing.csv"), ProductFormat::ProductCsv)
            .unwrap()
            .to_value(),
        result.to_value()
    );
}
