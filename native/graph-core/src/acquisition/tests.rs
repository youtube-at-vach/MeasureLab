use super::*;
use crate::Numeric;
use audio_core::{frame_queue, frame_queue_f64};
use std::thread;

fn format(channels: usize) -> IoFormat {
    IoFormat {
        stream_id: "capture.input".into(),
        generation: 1,
        timebase_id: "capture.clock".into(),
        clock_domain: "device.unverified".into(),
        rate: [48000, 1],
        input_ids: (0..channels).map(|c| format!("input.{c}")).collect(),
        input_ports: (0..channels).collect(),
        output_ids: Vec::new(),
        output_ports: Vec::new(),
    }
}
fn spec() -> FftSpec {
    FftSpec {
        n: 8,
        hop: 4,
        alignment: 0,
        window: WindowSpec::Boxcar,
    }
}
fn limits() -> CaptureLimits {
    CaptureLimits {
        history: HistoryLimits::frames(32),
        frames_per_poll: 7,
        windows_per_poll: 2,
    }
}
fn view(worker: &Acquisition<impl CaptureSample>) -> Subscription {
    worker
        .subscribe(
            Average::CumulativePsd,
            Presentation {
                color: "blue".into(),
                unit: "FS".into(),
            },
        )
        .unwrap()
}
fn drain(worker: &mut Acquisition<impl CaptureSample>) -> Vec<PollReport> {
    let mut reports = Vec::new();
    loop {
        let report = worker.poll().unwrap();
        let done = report.deliveries == 0 && report.windows.is_empty();
        reports.push(report);
        if done {
            return reports;
        }
    }
}
#[test]
fn bytes_binding_shared_fft_and_slow_display_are_independent() {
    let (mut tx, rx) = frame_queue(64, 4, 48000.).unwrap();
    let mut f = format(2);
    f.input_ports = vec![3, 1];
    let mut worker = Acquisition::new(rx, f, spec(), limits()).unwrap();
    let first = view(&worker);
    let second = view(&worker);
    let input: Vec<f32> = (0..32)
        .flat_map(|n| [n as f32, -(n as f32), 100., 0.5 * n as f32])
        .collect();
    tx.write(&input, Some(10.), 0).unwrap();
    let reports = drain(&mut worker);
    let raw: Vec<_> = reports
        .iter()
        .flat_map(|r| &r.blocks)
        .flat_map(|b| {
            let Samples::F32(v) = b.samples() else {
                panic!()
            };
            v.clone()
        })
        .collect();
    let expected: Vec<_> = input
        .as_chunks::<4>()
        .0
        .iter()
        .flat_map(|f| [f[3], f[1]])
        .collect();
    assert_eq!(
        raw.iter().map(|x| x.to_bits()).collect::<Vec<_>>(),
        expected.iter().map(|x| x.to_bits()).collect::<Vec<_>>()
    );
    assert_eq!(worker.graph().stats().fft_evaluations, 7);
    assert_eq!(worker.graph().stats().display_replacements, 12);
    let (a, b) = (first.take_latest().unwrap(), second.take_latest().unwrap());
    assert!(Arc::ptr_eq(a.raw(), b.raw()));
    assert_eq!(a.average_count(), 7);
    assert_eq!(a.raw().interval(), (24, 32));
    assert_eq!(
        reports.iter().map(|r| r.timestamps.len()).sum::<usize>(),
        32
    );
    assert_eq!(reports[0].timestamps[0].seconds, Some(10.));
    assert!(worker.key().source.timebase.origin_seconds.is_none());
    assert!(worker.key().source.timebase.uncertainty_seconds.is_none());
}
#[test]
fn f64_bits_survive_irregular_callback_and_poll_chunks() {
    let (mut tx, rx) = frame_queue_f64(64, 8, 48000.).unwrap();
    let mut worker = Acquisition::new(rx, format(8), spec(), limits()).unwrap();
    let subscription = view(&worker);
    let raw: Vec<f64> = (0..32 * 8).map(|x| x as f64 / 7.).collect();
    let mut output: Vec<f64> = Vec::new();
    for data in raw.chunks(5 * 8) {
        tx.write(data, None, 0).unwrap();
        for r in drain(&mut worker) {
            for b in r.blocks {
                let Samples::F64(v) = b.samples() else {
                    panic!()
                };
                output.extend(v);
            }
        }
    }
    assert_eq!(
        raw.iter().map(|x| x.to_bits()).collect::<Vec<_>>(),
        output.iter().map(|x| x.to_bits()).collect::<Vec<_>>()
    );
    assert_eq!(subscription.take_latest().unwrap().average_count(), 7);
}
#[test]
fn overflow_gap_resets_average_and_does_not_compute_zero_fft() {
    let (mut tx, rx) = frame_queue(8, 1, 48000.).unwrap();
    let mut worker = Acquisition::new(rx, format(1), spec(), limits()).unwrap();
    let subscription = view(&worker);
    tx.write(&[1.; 8], None, 0).unwrap();
    drain(&mut worker);
    assert_eq!(subscription.take_latest().unwrap().average_count(), 1);
    tx.write(&[2.; 20], None, 0).unwrap();
    let reports = drain(&mut worker);
    let gaps: Vec<_> = reports.iter().flat_map(|r| &r.gaps).copied().collect();
    assert_eq!(gaps, [[8, 20]]);
    let windows: Vec<_> = reports.iter().flat_map(|r| &r.windows).collect();
    assert_eq!(
        windows.iter().filter(|w| w.history.status == "gap").count(),
        4
    );
    assert!(
        windows
            .iter()
            .filter(|w| w.history.status == "gap")
            .all(|w| w.result_id.is_none() && !w.numeric)
    );
    assert_eq!(worker.graph().stats().fft_evaluations, 2);
    assert_eq!(subscription.take_latest().unwrap().average_count(), 1);
    assert_eq!(
        worker
            .history()
            .unwrap()
            .read_interval(8, 20)
            .unwrap()
            .report
            .missing,
        [[8, 20]]
    );
}
#[test]
fn discontinuity_clears_unread_numeric_and_fences_computed_completion() {
    let (mut tx, rx) = frame_queue(8, 1, 48000.).unwrap();
    let mut worker = Acquisition::new(rx, format(1), spec(), limits()).unwrap();
    let subscription = view(&worker);
    tx.write(&[1.; 8], None, 0).unwrap();
    drain(&mut worker);
    let source = worker.key().source.clone();
    let block = Arc::new(
        SignalBlock::new(source.clone(), 8, Samples::F32(vec![1.; 8]), Vec::new()).unwrap(),
    );
    let completion = worker
        .graph()
        .schedule(block)
        .unwrap()
        .pop()
        .unwrap()
        .compute();
    worker.graph().invalidate_source(&source).unwrap();
    assert!(subscription.take_latest().is_none());
    assert!(!completion.publish());
    assert_eq!(worker.graph().stats().in_flight, 0);
    assert_eq!(worker.graph().stats().cache_results, 0);
}
#[test]
fn large_gap_window_work_and_raw_dequeue_are_bounded_per_poll() {
    let (mut tx, rx) = frame_queue(8, 1, 48000.).unwrap();
    let mut worker = Acquisition::new(rx, format(1), spec(), limits()).unwrap();
    let subscription = view(&worker);
    tx.write(&[1.; 1000], None, 0).unwrap();
    let first = worker.poll().unwrap();
    assert_eq!(first.deliveries, 1);
    assert_eq!(first.windows.len(), 2);
    assert_eq!(first.gaps, [[0, 992]]);
    assert!(first.blocks.is_empty());
    for report in drain(&mut worker) {
        assert!(report.deliveries <= 7);
        assert!(report.timestamps.len() <= 7);
        assert!(report.windows.len() <= 2);
        assert!(
            report
                .blocks
                .iter()
                .map(|b| (b.interval().1 - b.interval().0) as usize)
                .sum::<usize>()
                <= 7
        );
    }
    assert_eq!(worker.history().unwrap().acquired_until(), 1000);
    assert_eq!(
        subscription.take_latest().unwrap().raw().interval(),
        (992, 1000)
    );
}
#[test]
fn backend_flags_and_nonfinite_values_produce_invalid_results_with_reasons() {
    let (mut tx, rx) = frame_queue(32, 2, 48000.).unwrap();
    let mut worker = Acquisition::new(rx, format(2), spec(), limits()).unwrap();
    let subscription = view(&worker);
    let mut data = [1.; 16];
    data[5] = f32::NAN;
    tx.write(&data, None, 16).unwrap();
    let reports = drain(&mut worker);
    assert_eq!(reports.iter().map(|r| r.timestamps.len()).sum::<usize>(), 8);
    assert!(
        reports
            .iter()
            .flat_map(|r| &r.timestamps)
            .all(|t| t.backend_flags == 16 && t.seconds.is_none())
    );
    let result = subscription.take_latest().unwrap();
    assert!(result.raw().numeric().is_none());
    assert_eq!(result.average_count(), 0);
    assert!(
        result
            .raw()
            .validity()
            .iter()
            .any(|v| v.reason == "nonfinite" && v.channel_id.as_deref() == Some("input.1"))
    );
    assert!(
        result
            .raw()
            .validity()
            .iter()
            .any(|v| v.reason == "unsupported" && v.origin == "backend.flags:16")
    );
    tx.write(&[1.; 16], None, 0).unwrap();
    drain(&mut worker);
    assert!(
        subscription
            .take_latest()
            .unwrap()
            .raw()
            .numeric()
            .is_some()
    );
}
#[test]
fn restart_rebinds_channels_and_fences_old_queue_and_pending_result() {
    let (mut old_tx, old_rx) = frame_queue(32, 2, 48000.).unwrap();
    let mut worker = Acquisition::new(old_rx, format(2), spec(), limits()).unwrap();
    let subscription = view(&worker);
    old_tx.write(&[1.; 16], None, 0).unwrap();
    drain(&mut worker);
    let held = subscription.take_latest().unwrap();
    let old = worker.key().source.clone();
    let block = Arc::new(SignalBlock::new(old, 8, Samples::F32(vec![1.; 16]), Vec::new()).unwrap());
    let completion = worker
        .graph()
        .schedule(block)
        .unwrap()
        .pop()
        .unwrap()
        .compute();
    let (mut tx, rx) = frame_queue(32, 4, 48000.).unwrap();
    let mut next = format(2);
    next.generation = 2;
    next.input_ports = vec![3, 0];
    worker.restart(rx, next).unwrap();
    assert!(!completion.publish());
    assert!(subscription.take_latest().is_none());
    subscription.reconfigure(worker.key().clone()).unwrap();
    old_tx.write(&[99.; 16], None, 0).unwrap();
    tx.write(&[2.; 32], None, 0).unwrap();
    drain(&mut worker);
    let fresh = subscription.take_latest().unwrap();
    assert_eq!(fresh.raw().key().source.generation, 2);
    assert_eq!(fresh.average_count(), 1);
    assert_eq!(held.raw().key().source.generation, 1);
    assert_eq!(held.raw().interval(), (0, 8));
    assert_eq!(worker.format().input_ports, [3, 0]);
}
#[test]
fn rejected_restart_keeps_queue_history_demand_and_unread_result() {
    let (mut tx, rx) = frame_queue(32, 1, 48000.).unwrap();
    let mut worker = Acquisition::new(rx, format(1), spec(), limits()).unwrap();
    let subscription = view(&worker);
    tx.write(&[1.; 8], None, 0).unwrap();
    drain(&mut worker);
    let (_, next) = frame_queue(32, 1, 44100.).unwrap();
    let mut f = format(1);
    f.generation = 2;
    assert!(worker.restart(next, f).is_err());
    assert_eq!(worker.history().unwrap().acquired_until(), 8);
    assert_eq!(worker.key().source.generation, 1);
    assert!(subscription.take_latest().is_some());
    tx.write(&[2.; 8], None, 0).unwrap();
    drain(&mut worker);
    assert_eq!(subscription.take_latest().unwrap().average_count(), 3);
}
#[test]
fn no_hidden_demand_and_final_token_or_stop_reclaims_resources() {
    let (mut tx, rx) = frame_queue(64, 1, 48000.).unwrap();
    let mut worker = Acquisition::new(rx, format(1), spec(), limits()).unwrap();
    tx.write(&[1.; 8], None, 0).unwrap();
    drain(&mut worker);
    assert_eq!(worker.graph().stats().fft_evaluations, 0);
    let a = view(&worker);
    let b = view(&worker);
    let save = view(&worker);
    tx.write(&[1.; 8], None, 0).unwrap();
    drain(&mut worker);
    let held = save.take_latest().unwrap();
    drop(a);
    drop(b);
    assert_eq!(worker.graph().stats().subscriptions, 1);
    tx.write(&[1.; 8], None, 0).unwrap();
    drain(&mut worker);
    assert!(save.take_latest().is_some());
    drop(save);
    assert_eq!(worker.graph().stats().nodes, 0);
    assert_eq!(worker.graph().stats().cache_numeric_bytes, 0);
    worker.stop();
    worker.stop();
    assert_eq!(worker.state(), &WorkerState::Stopped);
    assert!(worker.history().is_none());
    assert!(worker.poll().is_err());
    assert!(matches!(held.raw().numeric(), Some(Numeric::F32(_))));
}
#[test]
fn invalid_configuration_and_worker_failure_are_explicit() {
    for fault in 0..5 {
        let (_, rx) = frame_queue(32, 2, 48000.).unwrap();
        let mut f = format(2);
        let mut l = limits();
        let mut s = spec();
        match fault {
            0 => f.input_ports = vec![0, 0],
            1 => f.rate[0] = 44100,
            2 => l.frames_per_poll = 0,
            3 => l.windows_per_poll = 0,
            _ => s.n = 33,
        }
        assert!(Acquisition::new(rx, f, s, l).is_err());
    }
    let (mut tx, rx) = frame_queue(32, 2, 48000.).unwrap();
    let mut l = limits();
    l.history.max_validity_spans = 1;
    let mut worker = Acquisition::new(rx, format(2), spec(), l).unwrap();
    let subscription = view(&worker);
    tx.write(&[f32::NAN; 16], None, 0).unwrap();
    assert_eq!(worker.poll().unwrap_err(), "validity_capacity");
    assert_eq!(
        worker.state(),
        &WorkerState::Failed("validity_capacity".into())
    );
    assert!(worker.history().is_none());
    assert_eq!(worker.graph().stats().nodes, 0);
    assert!(subscription.take_latest().is_none());
}
#[test]
fn threaded_overwrite_preserves_positions_and_owned_values() {
    let (mut tx, rx) = frame_queue_f64(16, 2, 48000.).unwrap();
    let mut worker = Acquisition::new(rx, format(2), spec(), limits()).unwrap();
    let subscription = view(&worker);
    let producer = thread::spawn(move || {
        for start in (0..2048).step_by(16) {
            let v: Vec<_> = (start..start + 16)
                .flat_map(|n| [n as f64, -(n as f64)])
                .collect();
            tx.write(&v, None, 0).unwrap();
            thread::yield_now();
        }
    });
    let mut high = 0;
    while !producer.is_finished() || high < 2048 {
        let report = worker.poll().unwrap();
        for block in report.blocks {
            let Samples::F64(v) = block.samples() else {
                panic!()
            };
            for (offset, row) in v.as_chunks::<2>().0.iter().enumerate() {
                let n = (block.interval().0 + offset as u64) as f64;
                assert_eq!(*row, [n, -n]);
            }
        }
        high = worker.history().unwrap().acquired_until();
        thread::yield_now();
    }
    producer.join().unwrap();
    drain(&mut worker);
    assert!(subscription.take_latest().is_some());
}
#[test]
fn trailing_history_gap_is_missing_and_expires_old_samples() {
    let mut history = History::new(
        prepare(
            &frame_queue(16, 1, 48000.).unwrap().1,
            &format(1),
            &spec(),
            &limits(),
        )
        .unwrap()
        .1
        .source,
        HistoryLimits::frames(8),
    )
    .unwrap();
    history
        .append(
            SignalBlock::new(
                history.source().clone(),
                0,
                Samples::F32(vec![1.; 8]),
                Vec::new(),
            )
            .unwrap(),
        )
        .unwrap();
    let held = history.read_interval(0, 8).unwrap().snapshot.unwrap();
    assert!(history.append_gap([9, 12]).is_err());
    assert_eq!(history.acquired_until(), 8);
    history.append_gap([8, 20]).unwrap();
    let read = history.read_interval(8, 24).unwrap();
    assert_eq!(read.report.missing, [[8, 20]]);
    assert_eq!(read.report.pending, [[20, 24]]);
    assert_eq!(history.retained_frames(), 0);
    assert_eq!(held.interval(), (0, 8));
}
