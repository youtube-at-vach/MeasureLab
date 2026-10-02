use super::*;
use crate::result::{Capture, DeviceBinding, Profile};
use crate::{
    Average, FftKey, Graph, Limits, Precision, Presentation, Rational, Samples, SignalBlock,
    Source, Tap, Timebase, WindowSpec,
};
use std::collections::BTreeMap;
use std::fs;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::mpsc;

const TIMEOUT: Duration = Duration::from_secs(5);
static NEXT_DIRECTORY: AtomicU64 = AtomicU64::new(1);
struct Directory(PathBuf);
impl Directory {
    fn new() -> Self {
        let path = std::env::temp_dir().join(format!(
            "migration-async-save-{}-{}",
            std::process::id(),
            NEXT_DIRECTORY.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir(&path).unwrap();
        Self(path)
    }
    fn file(&self, name: &str) -> PathBuf {
        self.0.join(name)
    }
}
impl Drop for Directory {
    fn drop(&mut self) {
        fs::remove_dir_all(&self.0).unwrap();
    }
}
fn source() -> Source {
    Source {
        stream_id: "input.saved".into(),
        generation: 7,
        channel_ids: vec!["right".into(), "left".into()],
        precision: Precision::F64,
        timebase: Timebase {
            id: "clock.saved".into(),
            revision: 0,
            clock_domain: "fixture".into(),
            generation: 7,
            rate: Rational {
                numerator: 48000,
                denominator: 1,
            },
            nominal_rate: Rational {
                numerator: 48000,
                denominator: 1,
            },
            origin_sample: 0,
            origin_seconds: None,
            origin_kind: "unknown".into(),
            uncertainty_seconds: None,
        },
        route_revision: "route.saved".into(),
        tap: Tap::InputRaw,
        filter_state_revision: "none".into(),
        calibration_revision: "FS".into(),
    }
}
fn capture() -> Capture {
    Capture {
        result_id: "result.saved".into(),
        trigger_id: Some("trigger.saved".into()),
        acquired_host_seconds: None,
        result_host_seconds: None,
        trigger: None,
        clock_mapping: None,
    }
}
fn snapshot(factor: f64) -> Arc<MeasurementResult> {
    let profiles = BTreeMap::from([(
        "left".into(),
        Profile {
            revision: format!("profile.{factor}"),
            device_binding: DeviceBinding {
                device: "fixture".into(),
                port: 0,
            },
            is_calibrated: true,
            v_per_fs: factor,
            applied_interval: [0, 8],
        },
    )]);
    Arc::new(
        MeasurementResult::coherent_tone(
            &source(),
            [0, 8],
            capture(),
            &[0.5, 0.25],
            &profiles,
            vec![1000.0],
            1.0,
        )
        .unwrap(),
    )
}
fn blocked_worker(capacity: usize) -> (SaveWorker, mpsc::Receiver<()>, mpsc::Sender<()>) {
    let (started_tx, started_rx) = mpsc::channel();
    let (release_tx, release_rx) = mpsc::channel();
    let worker = SaveWorker::with_writer(capacity, move |result, path, format| {
        started_tx.send(()).unwrap();
        release_rx.recv_timeout(TIMEOUT).map_err(io::Error::other)?;
        result.save_new(path, format)
    })
    .unwrap();
    (worker, started_rx, release_tx)
}

#[test]
fn capacities_and_invalid_requests_are_rejected_before_admission() {
    assert!(SaveWorker::start(0).is_err());
    assert!(SaveWorker::start(MAX_SAVE_JOBS + 1).is_err());
    let mut worker = SaveWorker::start(1).unwrap();
    for path in [
        PathBuf::new(),
        PathBuf::from("/"),
        PathBuf::from("x".repeat(MAX_PATH_BYTES + 1)),
    ] {
        assert!(matches!(
            worker.submit(snapshot(2.0), path, Format::Json),
            Err(SubmitError::InvalidDestination)
        ));
    }
    let mut doc = snapshot(2.0).to_value();
    doc["capture"]["result_id"] = serde_json::json!("r".repeat(MAX_RESULT_ID_BYTES + 1));
    let result = Arc::new(
        MeasurementResult::decode(&serde_json::to_vec(&doc).unwrap(), Format::Json).unwrap(),
    );
    assert!(matches!(
        worker.submit(result, "unused.json".into(), Format::Json),
        Err(SubmitError::IdentityTooLarge)
    ));
    worker.join().unwrap();
}

#[test]
fn writing_counts_towards_capacity_and_pending_cancel_never_writes() {
    let directory = Directory::new();
    let (mut worker, started, release) = blocked_worker(2);
    let old = snapshot(2.0);
    let first = worker
        .submit(Arc::clone(&old), directory.file("first.json"), Format::Json)
        .unwrap();
    started.recv_timeout(TIMEOUT).unwrap();
    let cancelled = worker
        .submit(
            Arc::clone(&old),
            directory.file("cancelled.csv"),
            Format::Csv,
        )
        .unwrap();
    let busy = matches!(
        worker.submit(Arc::clone(&old), directory.file("busy.json"), Format::Json),
        Err(SubmitError::Busy)
    );
    let too_late = !first.cancel();
    let did_cancel = cancelled.cancel();
    let repeated = !cancelled.cancel();
    let pending = first.wait(Duration::ZERO).status;
    let changed_profile = snapshot(4.0);
    release.send(()).unwrap();
    worker.join().unwrap();
    assert!(busy && too_late && did_cancel && repeated);
    assert_eq!(pending, SaveStatus::Writing);
    assert_eq!(first.receipt().status, SaveStatus::Saved);
    assert_eq!(cancelled.receipt().status, SaveStatus::Cancelled);
    assert!(!directory.file("cancelled.csv").exists());
    assert!(!directory.file("busy.json").exists());
    assert_eq!(Arc::strong_count(&old), 1); // tickets do not pin arrays after completion
    assert_eq!(
        MeasurementResult::load(&directory.file("first.json"), Format::Json)
            .unwrap()
            .to_value(),
        old.to_value()
    );
    assert_ne!(old.to_value(), changed_profile.to_value());
    assert_eq!(first.receipt().generation, 7);
    assert_eq!(first.receipt().interval, [0, 8]);
    assert!(first.receipt().operation_id < cancelled.receipt().operation_id);
}

#[test]
fn close_cancels_only_pending_jobs_and_preserves_actual_writing_outcome() {
    let directory = Directory::new();
    let (mut worker, started, release) = blocked_worker(2);
    let result = snapshot(2.0);
    let weak = Arc::downgrade(&result);
    let first = worker
        .submit(
            Arc::clone(&result),
            directory.file("first.csv"),
            Format::Csv,
        )
        .unwrap();
    started.recv_timeout(TIMEOUT).unwrap();
    let queued = worker
        .submit(result, directory.file("queued.json"), Format::Json)
        .unwrap();
    worker.close(CloseMode::Drain);
    worker.close(CloseMode::CancelPending);
    worker.close(CloseMode::CancelPending);
    let state = first.receipt().status;
    let cancelled = queued.receipt().status;
    let closed = matches!(
        worker.submit(snapshot(2.0), directory.file("closed.json"), Format::Json),
        Err(SubmitError::Closed)
    );
    release.send(()).unwrap();
    worker.join().unwrap();
    worker.join().unwrap();
    assert_eq!(state, SaveStatus::Writing);
    assert_eq!(cancelled, SaveStatus::Cancelled);
    assert!(closed);
    assert_eq!(first.receipt().status, SaveStatus::Saved);
    assert!(weak.upgrade().is_none());
    assert!(!directory.file("queued.json").exists());
}

#[test]
fn io_failure_is_not_saved_and_does_not_poison_the_next_request() {
    let directory = Directory::new();
    let mut worker = SaveWorker::start(1).unwrap();
    let path = directory.file("exists.json");
    fs::write(&path, b"user's existing bytes").unwrap();
    let first = worker
        .submit(snapshot(2.0), path.clone(), Format::Json)
        .unwrap();
    assert!(
        matches!(first.wait(TIMEOUT).status, SaveStatus::Failed { kind, .. } if kind == "AlreadyExists")
    );
    assert_eq!(fs::read(&path).unwrap(), b"user's existing bytes");
    let second = worker
        .submit(
            snapshot(2.0),
            directory.file("absent/failed.json"),
            Format::Json,
        )
        .unwrap();
    assert!(
        matches!(second.wait(TIMEOUT).status, SaveStatus::Failed { kind, .. } if kind == "NotFound")
    );
    for (file, format) in [("result.json", Format::Json), ("result.csv", Format::Csv)] {
        let old = snapshot(2.0);
        let ticket = worker
            .submit(Arc::clone(&old), directory.file(file), format)
            .unwrap();
        assert_eq!(ticket.wait(TIMEOUT).status, SaveStatus::Saved);
        assert_eq!(
            MeasurementResult::load(&directory.file(file), format)
                .unwrap()
                .to_value(),
            old.to_value()
        );
    }
    worker.join().unwrap();
    assert!(fs::read_dir(&directory.0).unwrap().all(|entry| {
        !entry
            .unwrap()
            .file_name()
            .to_string_lossy()
            .ends_with(".tmp")
    }));
}

#[test]
fn blocked_disk_does_not_own_graph_or_stop_shared_fft_progress() {
    let directory = Directory::new();
    let graph = Graph::new(Limits::default()).unwrap();
    let key = FftKey {
        source: source(),
        n: 8,
        hop: 8,
        alignment: 0,
        window: WindowSpec::Boxcar,
        remove_dc: false,
        input_gains: vec![],
    };
    let presentation = Presentation {
        unit: "FS".into(),
        color: "blue".into(),
    };
    let view = graph
        .subscribe(key.clone(), Average::None, presentation.clone())
        .unwrap();
    let other = graph.subscribe(key, Average::None, presentation).unwrap();
    let block = |start| {
        Arc::new(SignalBlock::new(source(), start, Samples::F64(vec![0.25; 16]), vec![]).unwrap())
    };
    for job in graph.schedule(block(0)).unwrap() {
        assert!(job.run());
    }
    let result = Arc::new(
        MeasurementResult::from_fft(
            view.take_latest().unwrap().raw(),
            capture(),
            &BTreeMap::new(),
            1.0,
        )
        .unwrap(),
    );
    let expected = result.to_value();
    let weak = Arc::downgrade(&result);
    let (mut worker, started, release) = blocked_worker(1);
    let ticket = worker
        .submit(result, directory.file("after-shutdown.json"), Format::Json)
        .unwrap();
    started.recv_timeout(TIMEOUT).unwrap();
    for start in [8, 16, 24] {
        for job in graph.schedule(block(start)).unwrap() {
            assert!(job.run());
        }
        let a = view.take_latest().unwrap();
        let b = other.take_latest().unwrap();
        assert!(Arc::ptr_eq(a.raw(), b.raw()));
    }
    let count = graph.stats().fft_evaluations;
    drop(view);
    drop(other);
    graph.shutdown();
    let nodes = graph.stats().nodes;
    release.send(()).unwrap();
    worker.join().unwrap();
    assert_eq!(count, 4);
    assert_eq!(nodes, 0);
    assert_eq!(ticket.receipt().status, SaveStatus::Saved);
    assert!(weak.upgrade().is_none());
    assert_eq!(
        MeasurementResult::load(&directory.file("after-shutdown.json"), Format::Json)
            .unwrap()
            .to_value(),
        expected
    );
}

#[test]
fn drop_cancels_pending_and_joins_the_writer() {
    let directory = Directory::new();
    let (worker, started, release) = blocked_worker(2);
    let first = worker
        .submit(snapshot(2.0), directory.file("first.json"), Format::Json)
        .unwrap();
    started.recv_timeout(TIMEOUT).unwrap();
    let queued = worker
        .submit(snapshot(2.0), directory.file("pending.json"), Format::Json)
        .unwrap();
    // Run Drop on a teardown thread, as a future Qt adapter must do.
    let drop_thread = thread::spawn(move || drop(worker));
    assert_eq!(queued.wait(TIMEOUT).status, SaveStatus::Cancelled);
    release.send(()).unwrap();
    drop_thread.join().unwrap();
    assert_eq!(first.receipt().status, SaveStatus::Saved);
    assert!(!directory.file("pending.json").exists());
}

#[test]
fn drain_completes_both_formats_and_releases_snapshots() {
    let directory = Directory::new();
    let mut worker = SaveWorker::start(2).unwrap();
    let result = snapshot(2.0);
    let weak = Arc::downgrade(&result);
    let json = worker
        .submit(
            Arc::clone(&result),
            directory.file("result.json"),
            Format::Json,
        )
        .unwrap();
    let csv = worker
        .submit(result, directory.file("result.csv"), Format::Csv)
        .unwrap();
    worker.close(CloseMode::Drain);
    worker.join().unwrap();
    assert_eq!(json.receipt().status, SaveStatus::Saved);
    assert_eq!(csv.receipt().status, SaveStatus::Saved);
    assert!(weak.upgrade().is_none());
    assert_eq!(
        MeasurementResult::load(&directory.file("result.json"), Format::Json)
            .unwrap()
            .to_value(),
        MeasurementResult::load(&directory.file("result.csv"), Format::Csv)
            .unwrap()
            .to_value()
    );
}

#[test]
fn worker_panic_reports_unknown_commit_and_cancels_unstarted_requests() {
    let directory = Directory::new();
    let (started_tx, started_rx) = mpsc::channel();
    let (release_tx, release_rx) = mpsc::channel();
    let mut worker = SaveWorker::with_writer(2, move |_, _, _| {
        started_tx.send(()).unwrap();
        release_rx.recv_timeout(TIMEOUT).unwrap();
        panic!("injected writer failure");
    })
    .unwrap();
    let first = worker
        .submit(snapshot(2.0), directory.file("unknown.json"), Format::Json)
        .unwrap();
    started_rx.recv_timeout(TIMEOUT).unwrap();
    let pending = worker
        .submit(snapshot(2.0), directory.file("pending.json"), Format::Json)
        .unwrap();
    release_tx.send(()).unwrap();
    assert!(worker.join().is_err());
    assert!(
        matches!(first.receipt().status, SaveStatus::Failed { kind, .. } if kind == "WorkerPanicked")
    );
    assert_eq!(pending.receipt().status, SaveStatus::Cancelled);
    assert!(matches!(
        worker.submit(snapshot(2.0), directory.file("closed.json"), Format::Json),
        Err(SubmitError::Closed)
    ));
    assert_eq!(fs::read_dir(&directory.0).unwrap().count(), 0);
}

#[test]
fn operation_ids_do_not_wrap_or_consume_capacity_on_rejection() {
    let mut worker = SaveWorker::start(1).unwrap();
    worker.shared.state.lock().unwrap().next_id = u64::MAX;
    assert!(matches!(
        worker.submit(snapshot(2.0), "unused.json".into(), Format::Json),
        Err(SubmitError::OperationIdExhausted)
    ));
    assert_eq!(worker.shared.state.lock().unwrap().outstanding, 0);
    worker.join().unwrap();
}
