use super::*;
use crate::tests::{request, wait};
use graph_core::export::SaveStatus;
use serde_json::Value;

fn submission(result: &MeasurementResult, path: &std::path::Path, format: &str) -> String {
    json!({"generation": result.source().generation, "result_id": result.capture().result_id,
        "destination": path, "format": format})
    .to_string()
}
fn terminal(display: &Display, count: usize) -> Value {
    let deadline = std::time::Instant::now() + Duration::from_secs(5);
    loop {
        let report: Value = serde_json::from_str(&display.poll_saves()).unwrap();
        let receipts = report["receipts"].as_array().unwrap();
        if receipts.len() == count
            && receipts.iter().all(|r| {
                matches!(
                    r["status"]["state"].as_str(),
                    Some("saved" | "failed" | "cancelled")
                )
            })
        {
            return report;
        }
        assert!(std::time::Instant::now() < deadline);
        thread::sleep(Duration::from_millis(2));
    }
}
#[test]
fn presented_pin_survives_analysis_stop_restart_and_full_exchange() {
    for precision in [Precision::F32, Precision::F64] {
        let request = request(precision, 4, false);
        let input = request.input.clone().unwrap();
        let mut display = Display::with_request(request);
        display.subscribe();
        let generation = display.start(false, |_| true).unwrap();
        wait(&display, |s| s.produced >= 2);
        let shown = display.take(generation).unwrap();
        let result = shown.frame.as_ref().unwrap().result.clone();
        display.present(&shown);
        let dir = input.with_extension("save");
        std::fs::create_dir(&dir).unwrap();
        assert!(display.pin_result(generation, &result.capture().result_id));
        wait(&display, |s| s.produced > shown.produced + 2);
        display.present(&display.peek());
        display.shutdown();
        display.start(false, |_| true).unwrap();
        wait(&display, |s| s.produced > 0);
        display.present(&display.peek());
        for (index, kind) in ["json", "csv", "product_json", "product_csv"]
            .into_iter()
            .enumerate()
        {
            let path = dir.join(format!("pinned.{kind}"));
            assert!(display.save_result(&submission(&result, &path, kind)));
            let report = terminal(&display, index + 1);
            assert_eq!(report["receipts"][index]["format"], kind);
            assert_eq!(
                report["receipts"].as_array().unwrap().last().unwrap()["status"]["state"],
                "saved"
            );
            assert_eq!(
                match kind {
                    "json" => MeasurementResult::load(&path, Format::Json),
                    "csv" => MeasurementResult::load(&path, Format::Csv),
                    "product_json" => product::load(&path, ProductFormat::ProductJson),
                    _ => product::load(&path, ProductFormat::ProductCsv),
                }
                .unwrap()
                .to_value(),
                result.to_value()
            );
        }
        display.shutdown();
        drop(display);
        std::fs::remove_file(input).unwrap();
        std::fs::remove_dir_all(dir).unwrap();
    }
}
#[test]
fn invalid_identity_no_result_and_io_failure_do_not_stop_acquisition() {
    let request = request(Precision::F64, 8, false);
    let input = request.input.clone().unwrap();
    let mut display = Display::with_request(request);
    assert!(!display.save_result("{}"));
    assert!(!display.pin_result(1, "missing"));
    display.subscribe();
    let generation = display.start(false, |_| true).unwrap();
    wait(&display, |s| s.produced > 0);
    let shown = display.take(generation).unwrap();
    let result = shown.frame.as_ref().unwrap().result.clone();
    display.present(&shown);
    assert!(!display.pin_result(generation + 1, &result.capture().result_id));
    assert!(display.pin_result(generation, &result.capture().result_id));
    let mut stale: Value = serde_json::from_str(&submission(&result, &input, "json")).unwrap();
    stale["generation"] = json!(generation + 1);
    assert!(!display.save_result(&stale.to_string()));
    assert!(!display.save_result(&submission(&result, &input, "unknown")));
    assert!(!display.save_result(&"x".repeat(16385)));
    let before = std::fs::read(&input).unwrap();
    assert!(display.save_result(&submission(&result, &input, "json")));
    assert_eq!(
        terminal(&display, 1)["receipts"][0]["status"]["state"],
        "failed"
    );
    assert_eq!(std::fs::read(&input).unwrap(), before);
    let destination = input.with_extension("json");
    assert!(display.save_result(&submission(&result, &destination, "json")));
    assert_eq!(
        terminal(&display, 2)["receipts"][1]["status"]["state"],
        "saved"
    );
    assert!(!display.cancel_save(1));
    assert!(!display.cancel_save(100));
    display.close_saves();
    assert!(!display.save_result(&submission(&result, &destination, "json")));
    assert!(
        serde_json::from_str::<Value>(&display.poll_saves()).unwrap()["closed"]
            .as_bool()
            .unwrap()
    );
    wait(&display, |s| s.produced > shown.produced + 2);
    display.shutdown();
    drop(display);
    std::fs::remove_file(input).unwrap();
    std::fs::remove_file(destination).unwrap();
}
#[test]
fn qobject_retirement_dispatches_disk_join_and_retains_actual_outcomes() {
    let request = request(Precision::F64, 4, false);
    let input = request.input.clone().unwrap();
    let mut display = Display::with_request(request);
    display.subscribe();
    let generation = display.start(false, |_| true).unwrap();
    wait(&display, |s| s.produced > 0);
    let shown = display.take(generation).unwrap();
    let result = shown.frame.as_ref().unwrap().result.clone();
    display.present(&shown);
    assert!(display.pin_result(generation, &result.capture().result_id));
    let path = input.with_extension("retired.json");
    assert!(display.save_result(&submission(&result, &path, "json")));
    let ticket = display.saves.tickets[0].clone();
    display.shutdown();
    drop(display);
    let receipt = ticket.wait(Duration::from_secs(5));
    assert!(matches!(
        receipt.status,
        SaveStatus::Saved | SaveStatus::Cancelled
    ));
    if receipt.status == SaveStatus::Saved {
        assert_eq!(
            MeasurementResult::load(&path, Format::Json)
                .unwrap()
                .to_value(),
            result.to_value()
        );
        std::fs::remove_file(path).unwrap();
    } else {
        assert!(!path.exists());
    }
    std::fs::remove_file(input).unwrap();
}

#[test]
fn product_pair_failure_preserves_sidecar_and_recovers_in_same_queue() {
    let request = request(Precision::F64, 4, false);
    let input = request.input.clone().unwrap();
    let mut display = Display::with_request(request);
    display.subscribe();
    let generation = display.start(false, |_| true).unwrap();
    wait(&display, |s| s.produced > 0);
    let shown = display.take(generation).unwrap();
    let result = shown.frame.as_ref().unwrap().result.clone();
    display.present(&shown);
    assert!(display.pin_result(generation, &result.capture().result_id));
    let path = input.with_extension("partial.csv");
    let sidecar = product::sidecar_path(&path);
    std::fs::write(&sidecar, b"existing sidecar").unwrap();
    assert!(display.save_result(&submission(&result, &path, "product_csv")));
    let report = terminal(&display, 1);
    assert_eq!(report["receipts"][0]["format"], "product_csv");
    assert_eq!(report["receipts"][0]["status"]["state"], "failed");
    assert_eq!(report["receipts"][0]["status"]["kind"], "AlreadyExists");
    assert!(path.is_file());
    assert_eq!(std::fs::read(&sidecar).unwrap(), b"existing sidecar");
    assert!(product::load(&path, ProductFormat::ProductCsv).is_err());
    let recovery = input.with_extension("recovery.csv");
    assert!(display.save_result(&submission(&result, &recovery, "product_csv")));
    assert_eq!(
        terminal(&display, 2)["receipts"][1]["status"]["state"],
        "saved"
    );
    assert_eq!(
        product::load(&recovery, ProductFormat::ProductCsv)
            .unwrap()
            .to_value(),
        result.to_value()
    );
    wait(&display, |s| s.produced > shown.produced + 2);
    display.shutdown();
    drop(display);
    for path in [
        input,
        path,
        sidecar,
        product::sidecar_path(&recovery),
        recovery,
    ] {
        std::fs::remove_file(path).unwrap();
    }
}

#[test]
fn blocked_writer_busy_pending_cancel_and_gui_drop_leave_graph_independent() {
    let request = request(Precision::F64, 4, false);
    let input = request.input.clone().unwrap();
    let mut display = Display::with_request(request);
    display.subscribe();
    let generation = display.start(false, |_| true).unwrap();
    wait(&display, |s| s.produced > 0);
    let shown = display.take(generation).unwrap();
    let result = shown.frame.as_ref().unwrap().result.clone();
    display.present(&shown);
    assert!(display.pin_result(generation, &result.capture().result_id));
    let gate = Arc::new((Mutex::new(false), std::sync::Condvar::new()));
    let writer_gate = gate.clone();
    let (entered_tx, entered_rx) = std::sync::mpsc::channel();
    SESSIONS.fetch_add(1, Ordering::SeqCst);
    display.saves.worker = Some(
        SaveWorker::with_writer(2, move |result, path, format| {
            entered_tx.send(()).unwrap();
            let (lock, changed) = &*writer_gate;
            let _guard = changed
                .wait_while(lock.lock().unwrap(), |open| !*open)
                .unwrap();
            SaveFormat::write(result, path, format)
        })
        .unwrap(),
    );
    let path = input.with_extension("blocked.json");
    let cancelled_path = input.with_extension("cancelled.json");
    assert!(display.save_result(&submission(&result, &path, "product_json")));
    entered_rx.recv_timeout(Duration::from_secs(5)).unwrap();
    let writing = display.saves.tickets[0].clone();
    assert_eq!(writing.receipt().status, SaveStatus::Writing);
    assert!(display.save_result(&submission(&result, &cancelled_path, "csv")));
    let pending = display.saves.tickets[1].clone();
    assert_eq!(pending.receipt().status, SaveStatus::Queued);
    assert!(!display.save_result(&submission(&result, &path, "product_csv")));
    assert_eq!(display.saves.rejection.as_deref(), Some("busy"));
    assert!(!display.cancel_save(writing.receipt().operation_id));
    assert!(display.cancel_save(pending.receipt().operation_id));
    assert_eq!(pending.receipt().status, SaveStatus::Cancelled);
    wait(&display, |s| s.produced > shown.produced + 2);
    display.close_saves();
    assert_eq!(writing.receipt().status, SaveStatus::Writing);
    display.shutdown();
    let (done_tx, done_rx) = std::sync::mpsc::channel();
    let control = thread::spawn(move || {
        drop(display);
        done_tx.send(()).unwrap();
    });
    let retired_without_joining_disk = done_rx.recv_timeout(Duration::from_secs(1)).is_ok();
    let (lock, changed) = &*gate;
    *lock.lock().unwrap() = true;
    changed.notify_one();
    control.join().unwrap();
    assert!(
        retired_without_joining_disk,
        "QObject/control teardown blocked on disk"
    );
    assert_eq!(
        writing.wait(Duration::from_secs(5)).status,
        SaveStatus::Saved
    );
    assert_eq!(
        product::load(&path, ProductFormat::ProductJson)
            .unwrap()
            .to_value(),
        result.to_value()
    );
    assert!(!cancelled_path.exists());
    std::fs::remove_file(path).unwrap();
    std::fs::remove_file(input).unwrap();
}
