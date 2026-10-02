use super::*;
use crate::tests::{request, wait};
use std::sync::mpsc;
use std::time::Instant;

fn legacy(n: usize) -> ImportedProduct {
    product::import_json(&serde_json::to_vec(&json!({"version": "1.0", "traces": [{
        "id": "old", "name": "saved", "source_module": "old", "timestamp": "",
        "plot_type": "spectrum", "x_axis": {"dimension": "frequency", "base_unit": "Hz", "display_unit": "kHz", "is_log": true},
        "y_axis": {"dimension": "voltage", "base_unit": "V", "display_unit": "dBV", "is_log": false},
        "y2_axis": null, "x_data": (0..n).map(|i| i as f64).collect::<Vec<_>>(),
        "y_data": (0..n).map(|i| -0.125 * i as f64).collect::<Vec<_>>(), "y2_data": null,
        "calibration": {"is_calibrated": true, "input_sensitivity": 0.5, "applied_offset_db": 3., "reference_level": "absolute"},
        "metadata": {"large_integer": 18446744073709551615u64, "missing": null}
    }]})).unwrap()).unwrap()
}
fn submission(path: &str) -> String {
    json!({"path": path, "format": "product_json"}).to_string()
}
fn terminal(display: &Display, count: usize) -> Value {
    let deadline = Instant::now() + Duration::from_secs(5);
    loop {
        let report: Value = serde_json::from_str(&display.poll_imports()).unwrap();
        let receipts = report["receipts"].as_array().unwrap();
        if receipts.len() == count
            && receipts.iter().all(|r| {
                matches!(
                    r["status"]["state"].as_str(),
                    Some("loaded" | "failed" | "cancelled")
                )
            })
        {
            return report;
        }
        assert!(Instant::now() < deadline, "{report}");
        thread::sleep(Duration::from_millis(2));
    }
}
fn controlled() -> (Display, mpsc::Receiver<u64>, mpsc::Sender<()>) {
    let (started, observed) = mpsc::channel();
    let (release, blocked) = mpsc::channel();
    let mut display = Display::default();
    display
        .imports
        .start(move |_, operation_id| {
            started.send(operation_id).unwrap();
            blocked.recv().unwrap();
            let product = legacy(3);
            Ok(Loaded {
                preview: Arc::new(preview(&product).unwrap()),
                _product: product,
                operation_id,
            })
        })
        .unwrap();
    (display, observed, release)
}
#[test]
fn bounded_pending_cancel_and_latest_request_fence() {
    let (mut display, started, release) = controlled();
    assert!(display.import_product(&submission("first.json")));
    let first = started.recv_timeout(Duration::from_secs(2)).unwrap();
    assert!(!display.cancel_import(first));
    assert!(display.import_product(&submission("second.json")));
    let second = serde_json::from_str::<Value>(&display.poll_imports()).unwrap()["latest"]
        .as_u64()
        .unwrap();
    assert!(!display.import_product(&submission("third.json")));
    assert_eq!(
        serde_json::from_str::<Value>(&display.poll_imports()).unwrap()["rejection"],
        "busy"
    );
    assert!(display.cancel_import(second));
    release.send(()).unwrap();
    let report = terminal(&display, 2);
    assert_eq!(report["receipts"][0]["status"]["state"], "loaded");
    assert_eq!(report["receipts"][1]["status"]["state"], "cancelled");
    assert!(report["preview"].is_null()); // first must never reappear
    assert!(display.import_product(&submission("third.json")));
    let third = started.recv_timeout(Duration::from_secs(2)).unwrap();
    assert!(third > second);
    release.send(()).unwrap();
    let report = terminal(&display, 3);
    assert_eq!(report["latest"], third);
    let preview: Value = serde_json::from_str(report["preview"].as_str().unwrap()).unwrap();
    assert_eq!(preview["has_snapshot"], false);
    assert_eq!(preview["traces"][0]["rows"][1]["y"], "-0.125");
}
#[test]
fn closed_reader_and_qobject_drop_never_wait_for_disk() {
    let (mut display, started, release) = controlled();
    assert!(display.import_product(&submission("reading.json")));
    started.recv_timeout(Duration::from_secs(2)).unwrap();
    assert!(display.import_product(&submission("queued.json")));
    let shared = display.imports.worker.as_ref().unwrap().shared.clone();
    display.close_imports();
    assert!(!display.import_product(&submission("closed.json")));
    let before = Instant::now();
    drop(display);
    assert!(before.elapsed() < Duration::from_millis(100));
    assert_eq!(
        shared.0.lock().unwrap().receipts[1].status,
        Status::Cancelled
    );
    release.send(()).unwrap();
    let deadline = Instant::now() + Duration::from_secs(2);
    while !shared.0.lock().unwrap().receipts[0].status.terminal() {
        assert!(Instant::now() < deadline);
        thread::sleep(Duration::from_millis(2));
    }
    let slot = shared.0.lock().unwrap();
    assert!(slot.displayed.is_none());
    assert_eq!(slot.receipts[0].status, Status::Loaded); // real outcome survives close
}
#[test]
fn sampled_original_values_do_not_recalibrate_or_invent_acquisition() {
    let product = legacy(10000);
    let before = product.to_value();
    let preview: Value = serde_json::from_str(&preview(&product).unwrap()).unwrap();
    assert!(product.snapshot().is_none());
    assert!(
        product
            .acquisition()
            .as_object()
            .unwrap()
            .values()
            .all(Value::is_null)
    );
    let trace = &preview["traces"][0];
    assert_eq!(trace["original_count"], 10000);
    assert_eq!(trace["y_axis"], before["document"]["traces"][0]["y_axis"]);
    let rows = trace["rows"].as_array().unwrap();
    assert_eq!(rows.len(), 256);
    assert_eq!(rows[0]["index"], 0);
    assert_eq!(rows[0]["y"], "-0.0");
    assert_eq!(rows[255]["index"], 9999);
    for row in rows {
        assert_eq!(
            row["y"].as_str().unwrap().parse::<f64>().unwrap(),
            -0.125 * row["index"].as_u64().unwrap() as f64
        );
    }
    assert_eq!(product.to_value(), before); // all metadata and full precision survive
}
#[test]
fn malformed_requests_are_rejected_before_starting_a_reader() {
    let mut display = Display::default();
    for encoded in [
        "{}".to_string(),
        "x".repeat(16385),
        submission(""),
        json!({"path": "x", "format": "csv_spec"}).to_string(),
        json!({"path": "x", "format": "product_json", "spec": "extra"}).to_string(),
        json!({"path": "x", "format": "unknown"}).to_string(),
        json!({"path": "x", "format": "product_json", "other": true}).to_string(),
    ] {
        assert!(!display.import_product(&encoded));
    }
    assert!(display.imports.worker.is_none());
}
#[test]
fn long_unit_or_descriptor_is_rejected_instead_of_silently_shortened() {
    let mut document = legacy(3).document();
    document["traces"][0]["y_axis"]["display_unit"] = json!("V".repeat(257));
    let product = product::import_json(&serde_json::to_vec(&document).unwrap()).unwrap();
    assert_eq!(
        preview(&product),
        Err("import_preview_text_capacity".into())
    );
    assert_eq!(product.document(), document);
}
#[test]
fn older_completion_cannot_appear_while_newer_request_is_reading() {
    let (mut display, started, release) = controlled();
    assert!(display.import_product(&submission("old.json")));
    started.recv_timeout(Duration::from_secs(2)).unwrap();
    assert!(display.import_product(&submission("new.json")));
    release.send(()).unwrap();
    started.recv_timeout(Duration::from_secs(2)).unwrap();
    let report: Value = serde_json::from_str(&display.poll_imports()).unwrap();
    assert_eq!(report["receipts"][0]["status"]["state"], "loaded");
    assert_eq!(report["receipts"][1]["status"]["state"], "reading");
    assert!(report["preview"].is_null());
    release.send(()).unwrap();
    assert!(terminal(&display, 2)["preview"].is_string());
}
#[test]
fn io_failure_recovers_without_changing_acquisition_or_profiles() {
    let request = request(Precision::F64, 4, false);
    let input = request.input.clone().unwrap();
    let file = input.with_extension("product.json");
    std::fs::write(&file, serde_json::to_vec(&legacy(3).document()).unwrap()).unwrap();
    let mut display = Display::with_request(request);
    display.subscribe();
    display.start(false, |_| true).unwrap();
    wait(&display, |s| s.produced > 0);
    let before = display.peek();
    assert!(display.import_product(&submission("/nonexistent/measurelab.json")));
    assert_eq!(
        terminal(&display, 1)["receipts"][0]["status"]["state"],
        "failed"
    );
    assert!(display.import_product(&submission(file.to_str().unwrap())));
    assert_eq!(
        terminal(&display, 2)["receipts"][1]["status"]["state"],
        "loaded"
    );
    wait(&display, |s| s.produced > before.produced + 2);
    assert_eq!(display.peek().generation, before.generation);
    assert_eq!(display.peek().calibration, before.calibration);
    assert!(
        display
            .imports
            .worker
            .as_ref()
            .unwrap()
            .shared
            .0
            .lock()
            .unwrap()
            .displayed
            .as_ref()
            .unwrap()
            ._product
            .snapshot()
            .is_none()
    );
    display.shutdown();
    drop(display);
    std::fs::remove_file(input).unwrap();
    std::fs::remove_file(file).unwrap();
}
