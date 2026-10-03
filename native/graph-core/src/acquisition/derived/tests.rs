use super::*;
use crate::filter::{FilterConfig, FilterLimits, InputConversion};
use crate::history::TriggerEvent;
use audio_core::{Producer, frame_queue, frame_queue_f64};

fn format(channels: usize) -> IoFormat {
    IoFormat {
        stream_id: "input".into(),
        generation: 1,
        timebase_id: "clock".into(),
        clock_domain: "unknown-device".into(),
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
        hop: 8,
        alignment: 0,
        window: WindowSpec::Boxcar,
    }
}
fn limits() -> CaptureLimits {
    CaptureLimits {
        history: HistoryLimits::frames(64),
        frames_per_poll: 32,
        windows_per_poll: 1,
    }
}
fn worker(channels: usize, capacity: usize) -> (Producer<f64>, Acquisition<f64>) {
    let (tx, rx) = frame_queue_f64(capacity, channels, 48000.).unwrap();
    (
        tx,
        Acquisition::new(rx, format(channels), spec(), limits()).unwrap(),
    )
}
fn fir(w: &Acquisition<impl CaptureSample>, centered: bool, rate: i64) -> Filter {
    Filter::new(
        w.key().source.clone(),
        "derived".into(),
        "derived.clock".into(),
        FilterConfig::Fir {
            coefficients: vec![0.25, 0.5, 0.25],
            target_rate: Rational {
                numerator: rate,
                denominator: 1,
            },
            centered,
            revision: "p2-test".into(),
        },
        FilterLimits::default(),
    )
    .unwrap()
}
fn views(w: &Acquisition<impl CaptureSample>, f: &Filter) -> (Subscription, Subscription) {
    let key = FftKey {
        source: f.output_source().clone(),
        n: 8,
        hop: 8,
        alignment: 0,
        window: WindowSpec::Boxcar,
        remove_dc: false,
        input_gains: Vec::new(),
    };
    let subscribe = || {
        w.graph()
            .subscribe(
                key.clone(),
                Average::CumulativePsd,
                Presentation {
                    color: "blue".into(),
                    unit: "FS".into(),
                },
            )
            .unwrap()
    };
    (subscribe(), subscribe())
}
fn input(start: usize, end: usize, channels: usize) -> Vec<f64> {
    (start..end)
        .flat_map(|n| (0..channels).map(move |c| (n + c) as f64))
        .collect()
}
fn drain(w: &mut Acquisition<impl CaptureSample>) -> Vec<PollReport> {
    let mut reports = Vec::new();
    for _ in 0..10000 {
        let r = w.poll().unwrap();
        assert!(r.deliveries <= 32 && r.windows.len() <= 1 && r.filtered_windows.len() <= 1);
        let idle = r.deliveries == 0 && r.windows.is_empty() && r.filtered_windows.is_empty();
        reports.push(r);
        if idle {
            return reports;
        }
    }
    panic!("worker failed to drain")
}
fn output(reports: &[PollReport]) -> Vec<f64> {
    reports
        .iter()
        .flat_map(|r| &r.filtered_blocks)
        .flat_map(|b| {
            let Samples::F64(v) = b.samples() else {
                panic!()
            };
            v.clone()
        })
        .collect()
}

fn f32_fir(w: &Acquisition<f32>) -> Filter {
    Filter::new_with_conversion(
        w.key().source.clone(),
        "derived".into(),
        "derived.clock".into(),
        FilterConfig::Fir {
            coefficients: vec![0.25, 0.5, 0.25],
            target_rate: Rational {
                numerator: 24000,
                denominator: 1,
            },
            centered: false,
            revision: "p2-test".into(),
        },
        FilterLimits::default(),
        Some(InputConversion::F32ToF64Exact),
    )
    .unwrap()
}
fn input32(start: usize, end: usize, channels: usize) -> Vec<f32> {
    input(start, end, channels)
        .iter()
        .map(|v| (*v * 0.123456789) as f32)
        .collect()
}
#[test]
fn explicit_f32_queue_filter_preserves_raw_ports_gap_and_shared_lifetime() {
    for channels in [2, 4, 8] {
        let (mut tx, rx) = frame_queue(32, channels, 48000.).unwrap();
        let mut fmt = format(channels);
        fmt.input_ports.reverse();
        let mut w = Acquisition::new(rx, fmt, spec(), limits()).unwrap();
        let raw = w
            .subscribe(
                Average::None,
                Presentation {
                    color: "raw".into(),
                    unit: "FS".into(),
                },
            )
            .unwrap();
        let f = f32_fir(&w);
        let (a, b) = views(&w, &f);
        w.attach_filter(f, spec(), HistoryLimits::frames(64))
            .unwrap();
        let mut reports = Vec::new();
        let mut cursor = 0;
        while cursor < 1031 {
            let end = if cursor == 100 {
                136
            } else {
                (cursor + 7).min(if cursor < 100 { 100 } else { 1031 })
            };
            tx.write(&input32(cursor, end, channels), None, 0).unwrap();
            reports.extend(drain(&mut w));
            cursor = end;
        }
        let values = output(&reports);
        for m in 0usize..516 {
            for c in 0..channels {
                let expected: f64 = [0.25, 0.5, 0.25]
                    .iter()
                    .enumerate()
                    .filter_map(|(j, h)| {
                        let n = (2 * m).checked_sub(j)?;
                        Some(if (100..104).contains(&n) {
                            0.
                        } else {
                            h * f64::from(input32(n, n + 1, channels)[channels - 1 - c])
                        })
                    })
                    .sum();
                assert_eq!(values[m * channels + c], expected);
            }
        }
        for block in reports.iter().flat_map(|r| &r.blocks) {
            let Samples::F32(actual) = block.samples() else {
                panic!()
            };
            let (start, end) = block.interval();
            let expected: Vec<_> = input32(start as usize, end as usize, channels)
                .chunks_exact(channels)
                .flat_map(|row| row.iter().rev().map(|v| v.to_bits()))
                .collect();
            assert_eq!(
                actual.iter().map(|v| v.to_bits()).collect::<Vec<_>>(),
                expected
            );
        }
        let x = a.take_latest().unwrap();
        let y = b.take_latest().unwrap();
        assert!(Arc::ptr_eq(x.raw(), y.raw()));
        assert_eq!(
            raw.take_latest().unwrap().raw().key().source.precision,
            Precision::F32
        );
        assert_eq!(x.raw().key().source.precision, Precision::F64);
        let metadata = w.filtered_metadata().unwrap();
        assert_eq!(metadata.parent, w.key().source);
        assert_eq!(
            metadata
                .map_position(&Rational {
                    numerator: 1024,
                    denominator: 1
                })
                .unwrap(),
            Rational {
                numerator: 512,
                denominator: 1
            }
        );
        drop(a);
        assert_eq!(w.graph().filter_count(), 1);
        drop(b);
        tx.write(&input32(1031, 1047, channels), None, 0).unwrap();
        assert!(output(&drain(&mut w)).is_empty());
        assert!(w.filtered_history().is_none());
        assert!(raw.take_latest().is_some());
        w.stop();
        assert!(w.history().is_none() && w.queue_stats().is_none());
        assert_eq!(w.graph().stats().subscriptions, 0);
        assert_eq!(x.raw().key().source.precision, Precision::F64);
    }
}
#[test]
fn f32_restart_fences_widened_completion_and_resets_filter_state() {
    let (mut tx, rx) = frame_queue(32, 2, 48000.).unwrap();
    let mut w = Acquisition::new(rx, format(2), spec(), limits()).unwrap();
    let f = f32_fir(&w);
    let (a, b) = views(&w, &f);
    let old = f.output_source().clone();
    w.attach_filter(f, spec(), HistoryLimits::frames(64))
        .unwrap();
    tx.write(&input32(0, 32, 2), None, 0).unwrap();
    drain(&mut w);
    let frozen = a.take_latest().unwrap();
    let completion = w
        .graph()
        .schedule(Arc::new(
            SignalBlock::new(old, 16, Samples::F64(input(16, 24, 2)), vec![]).unwrap(),
        ))
        .unwrap()
        .pop()
        .unwrap()
        .compute();
    let (mut tx2, rx2) = frame_queue(32, 2, 48000.).unwrap();
    let mut fmt = format(2);
    fmt.generation = 2;
    w.restart(rx2, fmt).unwrap();
    assert!(!completion.publish());
    assert!(b.take_latest().is_none() && w.filtered_history().is_none());
    let f = f32_fir(&w);
    let mut key = w.key().clone();
    key.source = f.output_source().clone();
    a.reconfigure(key.clone()).unwrap();
    b.reconfigure(key).unwrap();
    w.attach_filter(f, spec(), HistoryLimits::frames(64))
        .unwrap();
    tx2.write(&input32(0, 32, 2), None, 0).unwrap();
    let reports = drain(&mut w);
    assert!(
        reports
            .iter()
            .flat_map(|r| &r.filtered_blocks)
            .flat_map(|b| b.validity())
            .any(|v| v.reason == "warmup" && v.start == 0)
    );
    assert_eq!(a.take_latest().unwrap().raw().key().source.generation, 2);
    assert_eq!(frozen.raw().key().source.generation, 1);
}

#[test]
fn ac10_queue_gap_finite_sum_and_trigger_mapping_for_2_4_8ch() {
    for channels in [2, 4, 8] {
        for chunk in [1, 7, 32] {
            let (mut tx, mut w) = worker(channels, 32);
            let f = fir(&w, false, 24000);
            let (a, b) = views(&w, &f);
            w.attach_filter(f, spec(), HistoryLimits::frames(64))
                .unwrap();
            let mut reports = Vec::new();
            let mut cursor = 0;
            while cursor < 1031 {
                let end = if cursor == 100 {
                    136
                } else {
                    (cursor + chunk).min(if cursor < 100 { 100 } else { 1031 })
                };
                tx.write(&input(cursor, end, channels), None, 0).unwrap();
                reports.extend(drain(&mut w));
                cursor = end;
            }
            drop(tx);
            reports.push(w.finish_input().unwrap());
            reports.extend(drain(&mut w));
            assert_eq!(
                reports
                    .iter()
                    .flat_map(|r| r.gaps.clone())
                    .collect::<Vec<_>>(),
                vec![[100, 104]]
            );
            let values = output(&reports);
            assert_eq!(values.len(), 516 * channels);
            for m in 0usize..516 {
                for c in 0..channels {
                    let expected: f64 = [0.25, 0.5, 0.25]
                        .iter()
                        .enumerate()
                        .filter_map(|(j, h)| {
                            let n = (2 * m).checked_sub(j)?;
                            Some(if (100..104).contains(&n) {
                                0.
                            } else {
                                h * (n + c) as f64
                            })
                        })
                        .sum();
                    assert_eq!(values[m * channels + c], expected);
                }
            }
            let spans: Vec<_> = reports
                .iter()
                .flat_map(|r| &r.filtered_blocks)
                .flat_map(|b| b.validity())
                .collect();
            for m in 0..516 {
                assert_eq!(
                    spans
                        .iter()
                        .any(|v| v.reason == "gap" && v.start <= m && m < v.end),
                    (50..53).contains(&m)
                );
                assert_eq!(
                    spans
                        .iter()
                        .any(|v| v.reason == "warmup" && v.start <= m && m < v.end),
                    m == 0
                );
            }
            let metadata = w.filtered_metadata().unwrap();
            assert_eq!(
                metadata.signal_delay_output_samples,
                Some(Rational {
                    numerator: 1,
                    denominator: 2
                })
            );
            assert_eq!(metadata.processing_latency_seconds, None);
            let event = TriggerEvent {
                id: "trigger".into(),
                stream_id: metadata.output.stream_id.clone(),
                generation: 1,
                timebase_id: metadata.output.timebase.id.clone(),
                sample: metadata
                    .map_position(&Rational {
                        numerator: 1024,
                        denominator: 1,
                    })
                    .unwrap(),
                source: "mapped-parent".into(),
                kind: "manual".into(),
                polarity: "none".into(),
                condition_revision: "test".into(),
                validity: Vec::new(),
                received_host_seconds: None,
            };
            let read = w.filtered_history().unwrap().query(&event, 4, 4).unwrap();
            assert_eq!(read.report.interval, [508, 516]);
            assert!(read.snapshot.is_some());
            let (x, y) = (a.take_latest().unwrap(), b.take_latest().unwrap());
            assert!(Arc::ptr_eq(x.raw(), y.raw()));
            assert!(x.raw().numeric().is_some());
            let frozen = x.raw().interval();
            w.stop();
            assert_eq!(x.raw().interval(), frozen);
            assert!(w.filtered_history().is_none());
            assert_eq!(w.graph().filter_count(), 0);
        }
    }
}

#[test]
fn centered_explicit_eof_flushes_but_stop_never_flushes() {
    for finish in [false, true] {
        let (mut tx, mut w) = worker(2, 32);
        let f = fir(&w, true, 24000);
        let (_a, _b) = views(&w, &f);
        w.attach_filter(f, spec(), HistoryLimits::frames(64))
            .unwrap();
        tx.write(&[2., 3.], None, 0).unwrap();
        assert_eq!(w.finish_input().unwrap_err(), "capture_queue_not_drained");
        assert_eq!(w.state(), &WorkerState::Running);
        assert!(output(&drain(&mut w)).is_empty());
        drop(tx);
        if finish {
            let r = w.finish_input().unwrap();
            assert_eq!(output(&[r]), vec![1., 1.5]);
            assert!(w.finish_input().is_err());
        }
        w.stop();
        assert_eq!(w.state(), &WorkerState::Stopped);
        assert!(w.filtered_history().is_none());
    }
}

fn sos(w: &Acquisition<f64>) -> Filter {
    Filter::new(
        w.key().source.clone(),
        "derived".into(),
        "derived.clock".into(),
        FilterConfig::Sos {
            coefficients: vec![[1., 0., 0., 1., 0., 0.]],
            revision: "identity".into(),
        },
        FilterLimits::default(),
    )
    .unwrap()
}
#[test]
fn sos_gap_nonfinite_and_backend_flags_are_failures_and_release_everything() {
    for fault in ["gap", "nan", "flags"] {
        let (mut tx, mut w) = worker(2, 8);
        let f = sos(&w);
        let (_a, _b) = views(&w, &f);
        w.attach_filter(f, spec(), HistoryLimits::frames(64))
            .unwrap();
        let n = if fault == "gap" { 12 } else { 8 };
        let mut values = input(0, n, 2);
        if fault == "nan" {
            values[0] = f64::NAN;
        }
        tx.write(&values, None, u32::from(fault == "flags"))
            .unwrap();
        assert_eq!(w.poll().unwrap_err(), "unsupported_iir_gap_or_invalid");
        assert_eq!(
            w.state(),
            &WorkerState::Failed("unsupported_iir_gap_or_invalid".into())
        );
        assert!(
            w.history().is_none() && w.filtered_history().is_none() && w.queue_stats().is_none()
        );
        assert_eq!(w.graph().stats().subscriptions, 0);
        assert_eq!(w.graph().filter_count(), 0);
    }
}
#[test]
fn last_filtered_demand_releases_history_and_raw_continues() {
    let (mut tx, mut w) = worker(2, 32);
    let raw = w
        .subscribe(
            Average::None,
            Presentation {
                color: "red".into(),
                unit: "FS".into(),
            },
        )
        .unwrap();
    let f = fir(&w, false, 24000);
    let (a, b) = views(&w, &f);
    w.attach_filter(f, spec(), HistoryLimits::frames(64))
        .unwrap();
    tx.write(&input(0, 32, 2), None, 0).unwrap();
    drain(&mut w);
    drop(a);
    assert_eq!(w.graph().filter_count(), 1);
    drop(b);
    assert_eq!(w.graph().filter_count(), 0);
    tx.write(&input(32, 64, 2), None, 0).unwrap();
    assert!(output(&drain(&mut w)).is_empty());
    assert!(w.filtered_history().is_none());
    assert_eq!(raw.take_latest().unwrap().raw().interval(), (56, 64));
    assert_eq!(w.state(), &WorkerState::Running);
}
#[test]
fn restart_fences_derived_completion_and_requires_explicit_new_filter() {
    let (mut tx, mut w) = worker(2, 32);
    let f = fir(&w, false, 24000);
    let (a, b) = views(&w, &f);
    let old = f.output_source().clone();
    w.attach_filter(f, spec(), HistoryLimits::frames(64))
        .unwrap();
    tx.write(&input(0, 32, 2), None, 0).unwrap();
    drain(&mut w);
    let frozen = a.take_latest().unwrap();
    let block = Arc::new(
        SignalBlock::new(old.clone(), 16, Samples::F64(input(16, 24, 2)), Vec::new()).unwrap(),
    );
    let completion = w.graph().schedule(block).unwrap().pop().unwrap().compute();
    let (mut tx2, rx2) = frame_queue_f64(32, 2, 48000.).unwrap();
    let mut fmt = format(2);
    fmt.generation = 2;
    w.restart(rx2, fmt).unwrap();
    assert!(!completion.publish());
    assert!(b.take_latest().is_none());
    assert!(w.filtered_history().is_none());
    let f = fir(&w, false, 24000);
    let mut key = w.key().clone();
    key.source = f.output_source().clone();
    a.reconfigure(key.clone()).unwrap();
    b.reconfigure(key).unwrap();
    w.attach_filter(f, spec(), HistoryLimits::frames(64))
        .unwrap();
    tx2.write(&input(0, 32, 2), None, 0).unwrap();
    drain(&mut w);
    assert_eq!(a.take_latest().unwrap().raw().key().source.generation, 2);
    assert_eq!(frozen.raw().key().source.generation, 1);
    assert!(
        w.graph()
            .schedule(Arc::new(
                SignalBlock::new(old, 24, Samples::F64(input(24, 32, 2)), Vec::new()).unwrap()
            ))
            .is_err()
    );
}
#[test]
fn upsampling_backlog_respects_each_poll_budget_without_skipping_windows() {
    let (mut tx, mut w) = worker(2, 32);
    let f = fir(&w, true, 96000);
    let (_a, _b) = views(&w, &f);
    w.attach_filter(f, spec(), HistoryLimits::frames(64))
        .unwrap();
    tx.write(&input(0, 32, 2), None, 0).unwrap();
    let mut reports = drain(&mut w);
    drop(tx);
    reports.push(w.finish_input().unwrap());
    reports.extend(drain(&mut w));
    let starts: Vec<_> = reports
        .iter()
        .flat_map(|r| &r.filtered_windows)
        .map(|e| e.history.interval[0])
        .collect();
    assert_eq!(starts, (0..64).step_by(8).collect::<Vec<_>>());
    assert_eq!(output(&reports).len(), 128);
}
#[test]
fn invalid_late_duplicate_and_f32_configuration_preserve_state() {
    let (mut tx, mut w) = worker(2, 32);
    let f = fir(&w, false, 24000);
    let (_a, _b) = views(&w, &f);
    let mut bad = spec();
    bad.hop = 0;
    assert!(
        w.attach_filter(f.clone(), bad, HistoryLimits::frames(64))
            .is_err()
    );
    assert_eq!(w.graph().filter_count(), 0);
    let mut mismatched = spec();
    mismatched.window = WindowSpec::SymmetricHann;
    assert_eq!(
        w.attach_filter(f.clone(), mismatched, HistoryLimits::frames(64))
            .unwrap_err(),
        "capture_filter_without_exact_demand"
    );
    w.attach_filter(f.clone(), spec(), HistoryLimits::frames(64))
        .unwrap();
    assert!(
        w.attach_filter(f.clone(), spec(), HistoryLimits::frames(64))
            .is_err()
    );
    assert_eq!(w.graph().filter_count(), 1);
    tx.write(&input(0, 8, 2), None, 0).unwrap();
    drain(&mut w);
    assert!(
        w.attach_filter(f, spec(), HistoryLimits::frames(64))
            .is_err()
    );
    let (_, rx) = frame_queue(32, 2, 48000.).unwrap();
    let w = Acquisition::new(rx, format(2), spec(), limits()).unwrap();
    assert_eq!(
        Filter::new(
            w.key().source.clone(),
            "derived".into(),
            "derived.clock".into(),
            FilterConfig::Fir {
                coefficients: vec![1.],
                target_rate: Rational {
                    numerator: 48000,
                    denominator: 1
                },
                centered: false,
                revision: "test".into()
            },
            FilterLimits::default()
        )
        .err()
        .unwrap(),
        "unsupported_filter_source"
    );
}

#[test]
fn too_small_output_history_reports_expired_windows_without_numeric_padding() {
    let (mut tx, mut w) = worker(2, 32);
    let f = fir(&w, true, 96000);
    let (_a, _b) = views(&w, &f);
    w.attach_filter(f, spec(), HistoryLimits::frames(8))
        .unwrap();
    tx.write(&input(0, 32, 2), None, 0).unwrap();
    let reports = drain(&mut w);
    let unavailable: Vec<_> = reports
        .iter()
        .flat_map(|r| &r.filtered_windows)
        .filter(|e| !e.history.missing.is_empty())
        .collect();
    assert!(!unavailable.is_empty());
    assert!(
        unavailable
            .iter()
            .all(|e| !e.numeric && e.result_id.is_none())
    );
    assert!(w.filtered_history().unwrap().retained_frames() <= 8);
}

#[test]
fn small_filter_capacity_fails_owner_and_preserves_retained_snapshot() {
    let (mut tx, mut w) = worker(2, 32);
    let f = Filter::new(
        w.key().source.clone(),
        "derived".into(),
        "derived.clock".into(),
        FilterConfig::Fir {
            coefficients: vec![1.],
            target_rate: Rational {
                numerator: 48000,
                denominator: 1,
            },
            centered: false,
            revision: "capacity-test".into(),
        },
        FilterLimits {
            max_input_frames: 8,
            ..FilterLimits::default()
        },
    )
    .unwrap();
    let (a, _b) = views(&w, &f);
    w.attach_filter(f, spec(), HistoryLimits::frames(64))
        .unwrap();
    tx.write(&input(0, 8, 2), None, 0).unwrap();
    drain(&mut w);
    let frozen = a.take_latest().unwrap();
    // Overflow creates a gap larger than the filter's supported missing-input budget.
    tx.write(&input(8, 64, 2), None, 0).unwrap();
    let mut failure = None;
    for _ in 0..10 {
        if let Err(error) = w.poll() {
            failure = Some(error);
            break;
        }
    }
    assert_eq!(failure.as_deref(), Some("filter_capacity"));
    assert_eq!(w.state(), &WorkerState::Failed("filter_capacity".into()));
    assert!(w.filtered_history().is_none() && w.queue_stats().is_none());
    assert_eq!(frozen.raw().interval(), (0, 8));
    assert!(frozen.raw().numeric().is_some());
}
