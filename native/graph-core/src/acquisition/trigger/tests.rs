use super::*;
use audio_core::{Producer, frame_queue};

fn setup() -> (Producer<f32>, Acquisition<f32>, Subscription) {
    let format = IoFormat {
        stream_id: "trigger.input".into(),
        generation: 1,
        timebase_id: "trigger.clock".into(),
        clock_domain: "unknown.device".into(),
        rate: [48000, 1],
        input_ids: vec!["right".into(), "left".into()],
        input_ports: vec![1, 0],
        output_ids: Vec::new(),
        output_ports: Vec::new(),
    };
    let (tx, rx) = frame_queue(128, 2, 48000.).unwrap();
    let worker = Acquisition::new(
        rx,
        format,
        FftSpec {
            n: 8,
            hop: 8,
            alignment: 0,
            window: WindowSpec::Boxcar,
        },
        CaptureLimits {
            history: HistoryLimits::frames(32),
            frames_per_poll: 128,
            windows_per_poll: 16,
        },
    )
    .unwrap();
    let view = worker
        .subscribe(
            Average::CumulativePsd,
            Presentation {
                color: "cyan".into(),
                unit: "FS".into(),
            },
        )
        .unwrap();
    (tx, worker, view)
}
fn request(sample: i64) -> TriggerRequest {
    TriggerRequest {
        request_id: "view.a".into(),
        pre: 4,
        post: 4,
        event: TriggerEvent {
            id: "event.1".into(),
            stream_id: "trigger.input".into(),
            generation: 1,
            timebase_id: "trigger.clock".into(),
            sample: Rational {
                numerator: sample,
                denominator: 1,
            },
            source: "virtual".into(),
            kind: "edge".into(),
            polarity: "rising".into(),
            condition_revision: "condition.1".into(),
            validity: Vec::new(),
            received_host_seconds: Some(Rational {
                numerator: 99999,
                denominator: 1,
            }),
        },
    }
}
fn feed(tx: &mut Producer<f32>, worker: &mut Acquisition<f32>, start: usize, frames: usize) {
    let values: Vec<_> = (start..start + frames)
        .flat_map(|n| [n as f32, -(n as f32)])
        .collect();
    tx.write(&values, None, 0).unwrap();
    loop {
        let report = worker.poll().unwrap();
        if report.deliveries == 0 && report.windows.is_empty() {
            break;
        }
    }
}

#[test]
fn pending_retry_shares_continuous_raw_without_consuming_latest_or_average() {
    let (mut tx, mut worker, view) = setup();
    feed(&mut tx, &mut worker, 0, 4);
    let read = worker.capture_trigger(&request(4)).unwrap();
    assert_eq!(read.history.report.pending, [[4, 8]]);
    assert!(read.result.is_none() && read.raw.is_none());
    assert_eq!(worker.trigger_evaluations(), 0);
    feed(&mut tx, &mut worker, 4, 12);
    let a = worker.capture_trigger(&request(4)).unwrap();
    let mut second = request(4);
    second.request_id = "view.b".into();
    second.event.id = "event.2".into();
    second.event.received_host_seconds = None;
    let b = worker.capture_trigger(&second).unwrap();
    assert_eq!(a.fft_origin, "continuous-cache");
    assert!(Arc::ptr_eq(
        a.raw.as_ref().unwrap(),
        b.raw.as_ref().unwrap()
    ));
    assert_eq!(worker.graph().stats().fft_evaluations, 2);
    assert_eq!(worker.trigger_evaluations(), 0);
    let latest = view.take_latest().unwrap();
    assert_eq!(latest.raw().interval(), (8, 16));
    assert_eq!(latest.average_count(), 2);
    assert_eq!(
        a.result.as_ref().unwrap().to_value()["capture"]["trigger"],
        serde_json::to_value(&request(4).event).unwrap()
    );
    assert_ne!(
        a.result.as_ref().unwrap().to_value()["capture"]["result_id"],
        b.result.as_ref().unwrap().to_value()["capture"]["result_id"]
    );
}

#[test]
fn fractional_unaligned_trigger_is_computed_once_without_changing_continuous_state() {
    let (mut tx, mut worker, view) = setup();
    feed(&mut tx, &mut worker, 0, 24);
    let mut r = request(5);
    r.event.sample = Rational {
        numerator: 11,
        denominator: 2,
    };
    let before = serde_json::to_value(worker.graph().stats()).unwrap();
    let a = worker.capture_trigger(&r).unwrap();
    assert_eq!(a.history.report.interval, [1, 9]);
    assert_eq!(
        a.history.fractional_residual,
        Rational {
            numerator: 1,
            denominator: 2
        }
    );
    assert_eq!(a.fft_origin, "computed");
    r.request_id = "delayed.view".into();
    r.event.received_host_seconds = Some(Rational {
        numerator: 111111,
        denominator: 1,
    });
    let b = worker.capture_trigger(&r).unwrap();
    assert_eq!(b.fft_origin, "trigger-cache");
    assert!(Arc::ptr_eq(
        a.raw.as_ref().unwrap(),
        b.raw.as_ref().unwrap()
    ));
    assert_eq!(worker.trigger_evaluations(), 1);
    assert_eq!(
        serde_json::to_value(worker.graph().stats()).unwrap(),
        before
    );
    let Samples::F32(v) = a.history.snapshot.as_ref().unwrap().samples() else {
        panic!()
    };
    let expected: Vec<_> = (1..9).flat_map(|n| [-(n as f32), n as f32]).collect();
    assert_eq!(v, &expected);
    let latest = view.take_latest().unwrap();
    assert_eq!(latest.raw().interval(), (16, 24));
    assert_eq!(latest.average_count(), 3);
}

#[test]
fn owned_trigger_snapshots_survive_eviction_restart_and_stop() {
    let (mut tx, mut worker, view) = setup();
    feed(&mut tx, &mut worker, 0, 16);
    let held = worker.capture_trigger(&request(5)).unwrap();
    let original = held.result.as_ref().unwrap().to_value();
    let Samples::F32(original_samples) = held.history.snapshot.as_ref().unwrap().samples() else {
        panic!()
    };
    let original_samples = original_samples.clone();
    feed(&mut tx, &mut worker, 16, 64);
    let gap = worker.capture_trigger(&request(5)).unwrap();
    assert_eq!(gap.history.report.missing, [[1, 9]]);
    assert!(gap.result.is_none());
    let mut format = worker.format().clone();
    format.generation = 2;
    let (_, rx) = frame_queue(128, 2, 48000.).unwrap();
    worker.restart(rx, format).unwrap();
    assert!(worker.trigger_cache.is_none());
    assert_eq!(
        worker.capture_trigger(&request(5)).err().unwrap(),
        "stale_generation"
    );
    drop(view);
    worker.stop();
    worker.stop();
    assert_eq!(
        worker.capture_trigger(&request(5)).err().unwrap(),
        "capture_not_running"
    );
    assert_eq!(held.result.as_ref().unwrap().to_value(), original);
    let Samples::F32(after) = held.history.snapshot.as_ref().unwrap().samples() else {
        panic!()
    };
    assert_eq!(&original_samples, after);
    let stats = worker.graph().stats();
    assert_eq!(
        (
            stats.nodes,
            stats.subscriptions,
            stats.cache_results,
            stats.in_flight
        ),
        (0, 0, 0, 0)
    );
}

#[test]
fn negative_and_missing_plus_future_intervals_have_no_numeric_result() {
    let (mut tx, mut worker, _view) = setup();
    feed(&mut tx, &mut worker, 0, 2);
    let read = worker.capture_trigger(&request(1)).unwrap();
    assert_eq!(read.history.report.interval, [-3, 5]);
    assert_eq!(read.history.report.missing, [[-3, 0]]);
    assert_eq!(read.history.report.pending, [[2, 5]]);
    assert!(read.raw.is_none() && read.result.is_none());
    assert_eq!(worker.trigger_evaluations(), 0);
}

#[test]
fn queue_gap_is_reported_with_positions_instead_of_zero_fft() {
    let (mut tx, mut worker, _view) = setup();
    let values = vec![1.; 2 * 132];
    // Fixed callback queue keeps the tail; dropped first frames are a gap at their original positions.
    tx.write(&values, None, 0).unwrap();
    let read = worker.poll().unwrap();
    assert!(!read.gaps.is_empty());
    let capture = worker.capture_trigger(&request(4)).unwrap();
    assert_eq!(capture.history.report.status, "gap");
    assert!(capture.raw.is_none() && capture.result.is_none());
    assert_eq!(worker.trigger_evaluations(), 0);
}

#[test]
fn nonfinite_window_preserves_invalid_columns_and_reason() {
    let (mut tx, mut worker, view) = setup();
    let mut data = vec![1.; 32];
    data[6] = f32::NAN;
    tx.write(&data, None, 0).unwrap();
    worker.poll().unwrap();
    let held = worker.capture_trigger(&request(5)).unwrap();
    let result = held.result.unwrap().to_value();
    assert!(held.raw.unwrap().numeric().is_none());
    assert!(
        result["columns"]["peak_fs"]["values"]
            .as_array()
            .unwrap()
            .iter()
            .all(serde_json::Value::is_null)
    );
    assert_eq!(result["validity"][0]["reason"], "nonfinite");
    assert_eq!(result["validity"][0]["channel_id"], "left");
    assert_eq!(worker.trigger_evaluations(), 0);
    assert_eq!(view.take_latest().unwrap().raw().interval(), (8, 16));
}

#[test]
fn invalid_requests_do_not_evaluate_or_mutate_demand() {
    let (mut tx, mut worker, _view) = setup();
    feed(&mut tx, &mut worker, 0, 16);
    let before = serde_json::to_value(worker.graph().stats()).unwrap();
    for fault in 0..8 {
        let mut r = request(5);
        match fault {
            0 => r.request_id.clear(),
            1 => r.pre = u64::MAX,
            2 => r.post += 1,
            3 => r.event.sample.denominator = 0,
            4 => r.event.timebase_id = "foreign".into(),
            5 => r.event.generation = 2,
            6 => r.event.polarity.clear(),
            _ => r.event.received_host_seconds.as_mut().unwrap().denominator = 0,
        }
        assert!(worker.capture_trigger(&r).is_err());
    }
    assert_eq!(worker.trigger_evaluations(), 0);
    assert_eq!(
        serde_json::to_value(worker.graph().stats()).unwrap(),
        before
    );
}

#[test]
fn one_slot_trigger_cache_is_replaced_when_interval_changes() {
    let (mut tx, mut worker, _view) = setup();
    feed(&mut tx, &mut worker, 0, 24);
    let a = worker.capture_trigger(&request(5)).unwrap();
    let b = worker.capture_trigger(&request(6)).unwrap();
    assert!(!Arc::ptr_eq(
        a.raw.as_ref().unwrap(),
        b.raw.as_ref().unwrap()
    ));
    let again = worker.capture_trigger(&request(5)).unwrap();
    assert_eq!(again.fft_origin, "computed");
    assert_eq!(worker.trigger_evaluations(), 3);
    assert_eq!(a.raw.as_ref().unwrap().interval(), (1, 9));
}

#[test]
fn repeated_request_metadata_gets_a_distinct_immutable_result_identity() {
    let (mut tx, mut worker, _view) = setup();
    feed(&mut tx, &mut worker, 0, 16);
    let mut r = request(5);
    let a = worker.capture_trigger(&r).unwrap();
    let original = a.result.as_ref().unwrap().to_value();
    r.event.received_host_seconds = None;
    let b = worker.capture_trigger(&r).unwrap();
    assert!(Arc::ptr_eq(
        a.raw.as_ref().unwrap(),
        b.raw.as_ref().unwrap()
    ));
    assert_ne!(
        original["capture"]["result_id"],
        b.result.as_ref().unwrap().to_value()["capture"]["result_id"]
    );
    assert_eq!(original, a.result.as_ref().unwrap().to_value());
}
