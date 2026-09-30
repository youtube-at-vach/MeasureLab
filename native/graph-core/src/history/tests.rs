use super::*;
use crate::{Average, FftKey, Graph, Limits, Presentation, WindowSpec, time};

fn source() -> Source {
    crate::tests::source(2, Precision::F64)
}
fn input(source: &Source, start: u64, frames: usize, validity: Vec<InvalidSpan>) -> SignalBlock {
    SignalBlock::new(
        source.clone(),
        start,
        Samples::F64(
            (start..start + frames as u64)
                .flat_map(|n| [n as f64, -(n as f64)])
                .collect(),
        ),
        validity,
    )
    .unwrap()
}
fn event(sample: i64) -> TriggerEvent {
    let source = source();
    TriggerEvent {
        id: "trigger.1".into(),
        stream_id: source.stream_id,
        generation: source.generation,
        timebase_id: source.timebase.id,
        sample: Rational {
            numerator: sample,
            denominator: 1,
        },
        source: "virtual".into(),
        kind: "edge".into(),
        polarity: "rising".into(),
        condition_revision: "condition.1".into(),
        validity: Vec::new(),
        received_host_seconds: None,
    }
}
fn values(block: &SignalBlock) -> &[f64] {
    match block.samples() {
        Samples::F64(v) => v,
        _ => panic!("wrong precision"),
    }
}
fn graph_key(source: &Source, start: u64, n: usize) -> FftKey {
    FftKey {
        source: source.clone(),
        n,
        hop: n,
        alignment: start,
        window: WindowSpec::Boxcar,
        remove_dc: false,
        input_gains: Vec::new(),
    }
}
fn subscribe(graph: &Graph, key: &FftKey) -> crate::Subscription {
    graph
        .subscribe(
            key.clone(),
            Average::CumulativePsd,
            Presentation {
                color: "blue".into(),
                unit: "FS".into(),
            },
        )
        .unwrap()
}
#[test]
fn ac08_independent_readers_delayed_trigger_and_owned_snapshot() {
    let source = source();
    let mut history = History::new(source.clone(), HistoryLimits::frames(4096)).unwrap();
    for start in (0..2816).step_by(128) {
        history
            .append(input(&source, start, 128, Vec::new()))
            .unwrap();
    }
    let first = history.query(&event(2048), 256, 768).unwrap();
    assert_eq!(first.report.interval, [1792, 2816]);
    let held = first.snapshot.unwrap();
    let mut fast = history.reader(1792);
    let mut slow = history.reader(1792);
    assert!(
        history
            .read_next(&mut fast, 1024)
            .unwrap()
            .snapshot
            .is_some()
    );
    assert_eq!(fast.position(), 2816);
    assert_eq!(slow.position(), 1792);
    history
        .append(input(&source, 2816, 1280, Vec::new()))
        .unwrap();
    let late = history
        .read_next(&mut slow, 1024)
        .unwrap()
        .snapshot
        .unwrap();
    assert_eq!(values(&held), values(&late));
    history
        .append(input(&source, 4096, 1904, Vec::new()))
        .unwrap();
    let expired = history.query(&event(2048), 256, 768).unwrap();
    assert_eq!(expired.report.missing, [[1792, 1904]]);
    assert!(expired.snapshot.is_none());
    assert_eq!(values(&held)[0], 1792.0);
    assert_eq!(history.retained_frames(), 4096);
    assert_eq!(history.retained_numeric_bytes(), 4096 * 2 * 8);
}
#[test]
fn ac09_exact_gap_future_negative_and_fractional_trigger() {
    let source = source();
    let mut history = History::new(source.clone(), HistoryLimits::frames(128)).unwrap();
    history.append(input(&source, 0, 100, Vec::new())).unwrap();
    history.append(input(&source, 104, 6, Vec::new())).unwrap();
    let read = history.query(&event(102), 4, 4).unwrap();
    assert_eq!(read.report.missing, [[100, 104]]);
    let future = history.query(&event(109), 1, 4).unwrap();
    assert_eq!(future.report.pending, [[110, 113]]);
    assert_eq!(future.report.status, "pending");
    let early = history.query(&event(2), 4, 4).unwrap();
    assert_eq!(early.report.missing, [[-2, 0]]);
    let mut fractional = event(-1);
    fractional.sample.denominator = 2;
    let read = history.query(&fractional, 0, 4).unwrap();
    assert_eq!(read.report.interval, [-1, 3]);
    assert_eq!(
        read.fractional_residual,
        Rational {
            numerator: 1,
            denominator: 2
        }
    );
    let mixed = history.read_interval(98, 120).unwrap();
    assert_eq!(mixed.report.status, "gap");
    assert_eq!(mixed.report.missing, [[100, 104]]);
    assert_eq!(mixed.report.pending, [[110, 120]]);
}
#[test]
fn malformed_reads_blocks_and_restart_do_not_change_history() {
    let source = source();
    let mut history = History::new(source.clone(), HistoryLimits::frames(16)).unwrap();
    history.append(input(&source, 0, 8, Vec::new())).unwrap();
    assert_eq!(
        history
            .append(input(&source, 4, 8, Vec::new()))
            .unwrap_err(),
        "overlap_or_reverse"
    );
    let mut changed = source.clone();
    changed.channel_ids.reverse();
    assert_eq!(
        history
            .append(input(&changed, 8, 8, Vec::new()))
            .unwrap_err(),
        "configuration_requires_new_generation"
    );
    assert_eq!(history.acquired_until(), 8);
    assert!(history.read_interval(8, 8).is_err());
    let mut bad = event(4);
    bad.sample.denominator = 0;
    assert!(history.query(&bad, 1, 1).is_err());
    bad = event(4);
    bad.timebase_id = "foreign".into();
    assert_eq!(
        history.query(&bad, 1, 1).err().unwrap(),
        "stream_or_timebase_mismatch"
    );
    assert!(history.restart(source.clone()).is_err());
    let mut newer = source.clone();
    newer.generation += 1;
    newer.timebase.generation += 1;
    let mut old_reader = history.reader(0);
    history.restart(newer.clone()).unwrap();
    assert_eq!(
        history.query(&event(4), 1, 1).err().unwrap(),
        "stale_generation"
    );
    assert_eq!(
        history.read_next(&mut old_reader, 4).err().unwrap(),
        "stale_generation"
    );
    assert!(history.append(input(&source, 8, 8, Vec::new())).is_err());
    history.append(input(&newer, 0, 8, Vec::new())).unwrap();
    assert_eq!(history.acquired_until(), 8);
}
#[test]
fn validity_is_clipped_and_capacity_rejections_are_atomic() {
    let source = source();
    let span = InvalidSpan {
        start: 2,
        end: 6,
        channel_id: Some(source.channel_ids[1].clone()),
        reason: "warmup".into(),
        origin: "filter".into(),
    };
    let mut limits = HistoryLimits::frames(16);
    limits.max_validity_spans = 1;
    let mut history = History::new(source.clone(), limits).unwrap();
    history
        .append(input(&source, 0, 8, vec![span.clone()]))
        .unwrap();
    let read = history.read_interval(4, 8).unwrap();
    assert_eq!(read.snapshot.unwrap().validity()[0].start, 4);
    let second = InvalidSpan {
        start: 8,
        end: 12,
        ..span
    };
    assert_eq!(
        history
            .append(input(&source, 8, 8, vec![second]))
            .unwrap_err(),
        "validity_capacity"
    );
    assert_eq!(history.acquired_until(), 8);
    history.append(input(&source, 16, 32, Vec::new())).unwrap();
    assert_eq!(history.retained_frames(), 16);
    assert_eq!(
        history.read_interval(30, 36).unwrap().report.missing,
        [[30, 32]]
    );
    limits.max_numeric_bytes = 16;
    assert!(History::new(source, limits).is_err());
}
#[test]
fn source_revision_boundaries_are_preserved_and_not_combined() {
    let source = source();
    let mut changed = source.clone();
    changed.route_revision = "route.2".into();
    let mut history = History::new(source.clone(), HistoryLimits::frames(16)).unwrap();
    history.append(input(&source, 0, 8, Vec::new())).unwrap();
    history.append(input(&changed, 8, 8, Vec::new())).unwrap();
    assert_eq!(
        history.read_interval(4, 12).err().unwrap(),
        "mixed_source_conditions"
    );
    assert_eq!(
        history
            .read_interval(8, 16)
            .unwrap()
            .snapshot
            .unwrap()
            .source(),
        &changed
    );
}
#[test]
fn ac08_history_feeds_one_shared_fft_and_gap_does_not_evaluate() {
    let source = source();
    let mut history = History::new(source.clone(), HistoryLimits::frames(64)).unwrap();
    for start in (0..32).step_by(4) {
        history
            .append(input(&source, start, 4, Vec::new()))
            .unwrap();
    }
    let graph = Graph::new(Limits::default()).unwrap();
    let key = graph_key(&source, 8, 16);
    let a = subscribe(&graph, &key);
    let b = subscribe(&graph, &key);
    let read = history.query(&event(12), 4, 12).unwrap();
    for job in graph.schedule_history(&read).unwrap() {
        assert!(job.run());
    }
    let first = a.take_latest().unwrap();
    let second = b.take_latest().unwrap();
    assert!(Arc::ptr_eq(first.raw(), second.raw()));
    assert_eq!(first.raw().interval(), (8, 24));
    assert_eq!(first.raw().key().source, source);
    assert_eq!(graph.stats().fft_evaluations, 1);
    let gap = history.read_interval(-2, 8).unwrap();
    assert_eq!(graph.schedule_history(&gap).err().unwrap(), "gap");
    assert_eq!(graph.stats().fft_evaluations, 1);
}
#[test]
fn validity_reaches_shared_graph_and_resets_average() {
    let source = source();
    let mut history = History::new(source.clone(), HistoryLimits::frames(64)).unwrap();
    history.append(input(&source, 0, 16, Vec::new())).unwrap();
    let graph = Graph::new(Limits::default()).unwrap();
    let key = graph_key(&source, 0, 16);
    let a = subscribe(&graph, &key);
    let b = subscribe(&graph, &key);
    for job in graph
        .schedule_history(&history.read_interval(0, 16).unwrap())
        .unwrap()
    {
        assert!(job.run());
    }
    assert_eq!(a.take_latest().unwrap().average_count(), 1);
    let span = InvalidSpan {
        start: 20,
        end: 21,
        channel_id: None,
        reason: "missing".into(),
        origin: "backend".into(),
    };
    history.append(input(&source, 16, 16, vec![span])).unwrap();
    for job in graph
        .schedule_history(&history.read_interval(16, 32).unwrap())
        .unwrap()
    {
        assert!(job.run());
    }
    let first = a.take_latest().unwrap();
    let second = b.take_latest().unwrap();
    assert!(Arc::ptr_eq(first.raw(), second.raw()));
    assert!(first.raw().numeric().is_none());
    assert_eq!(first.raw().validity()[0].reason, "missing");
    assert_eq!(first.average_count(), 0);
    assert_eq!(graph.stats().fft_evaluations, 1);
}
#[test]
fn restart_rejects_old_completions_blocks_cache_and_snapshots() {
    let source = source();
    let mut history = History::new(source.clone(), HistoryLimits::frames(64)).unwrap();
    history.append(input(&source, 0, 32, Vec::new())).unwrap();
    let graph = Graph::new(Limits::default()).unwrap();
    let key = graph_key(&source, 0, 16);
    let a = subscribe(&graph, &key);
    let b = subscribe(&graph, &key);
    for job in graph
        .schedule(Arc::new(input(&source, 0, 16, Vec::new())))
        .unwrap()
    {
        assert!(job.run());
    }
    let held = a.take_latest().unwrap();
    let completion = graph
        .schedule(Arc::new(input(&source, 16, 16, Vec::new())))
        .unwrap()
        .pop()
        .unwrap()
        .compute();
    let mut newer = source.clone();
    newer.generation = 4;
    newer.timebase.generation = 4;
    history.restart_with_graph(newer.clone(), &graph).unwrap();
    assert_eq!(graph.stats().nodes, 0);
    assert_eq!(graph.stats().cache_results, 0);
    assert!(b.take_latest().is_none());
    assert!(!completion.publish());
    assert_eq!(graph.stats().in_flight, 0);
    assert!(graph.cached(&key, 0).is_none());
    assert!(
        graph
            .schedule(Arc::new(input(&source, 32, 16, Vec::new())))
            .is_err()
    );
    assert!(a.reconfigure(key.clone()).is_err());
    assert!(graph.retire_stream_before(&source.stream_id, 3).is_err());
    let key = graph_key(&newer, 0, 16);
    a.reconfigure(key.clone()).unwrap();
    b.reconfigure(key).unwrap();
    for job in graph
        .schedule(Arc::new(input(&newer, 0, 16, Vec::new())))
        .unwrap()
    {
        assert!(job.run());
    }
    assert_eq!(a.take_latest().unwrap().raw().key().source.generation, 4);
    assert_eq!(held.raw().key().source.generation, 3);
}
#[test]
fn exact_time_unknown_clock_mapping_expiry_and_overflow() {
    let mut left = source().timebase;
    let mut right = left.clone();
    assert_eq!(
        time::relation(&left, &right, None, 1024)
            .unwrap()
            .reason
            .as_deref(),
        Some("unknown_origin")
    );
    left.origin_seconds = Some(Rational {
        numerator: 10,
        denominator: 1,
    });
    assert_eq!(
        time::relation(&left, &right, None, 1024).unwrap().value,
        Some(Rational {
            numerator: 3758,
            denominator: 375
        })
    );
    right.id = "other".into();
    right.clock_domain = "other-device".into();
    assert_eq!(
        time::relation(&left, &right, None, 1024)
            .unwrap()
            .reason
            .as_deref(),
        Some("unsynchronized")
    );
    let mapping = time::ClockMapping {
        from: (left.id.clone(), 3),
        to: (right.id.clone(), 3),
        offset: Rational {
            numerator: 1,
            denominator: 2,
        },
        ratio: Rational {
            numerator: 1,
            denominator: 1,
        },
        valid_interval: [0, 2048],
        method: "exact-fixture".into(),
        uncertainty_samples: None,
    };
    assert_eq!(
        time::relation(&left, &right, Some(&mapping), 1024)
            .unwrap()
            .value,
        Some(Rational {
            numerator: 2049,
            denominator: 2
        })
    );
    assert_eq!(
        time::relation(&left, &right, Some(&mapping), 2048)
            .unwrap()
            .reason
            .as_deref(),
        Some("unsynchronized")
    );
    right.generation += 1;
    assert_eq!(
        time::relation(&left, &right, Some(&mapping), 1024)
            .unwrap()
            .reason
            .as_deref(),
        Some("unsynchronized")
    );
    left.origin_seconds = Some(Rational {
        numerator: i64::MAX,
        denominator: 1,
    });
    assert!(time::relation(&left, &left, None, 48000).is_err());
}

#[test]
fn fragmented_multichannel_history_matches_independent_frame_set_oracle() {
    for channels in [4, 8] {
        for precision in [Precision::F32, Precision::F64] {
            let source = crate::tests::source(channels, precision);
            let mut history = History::new(source.clone(), HistoryLimits::frames(31)).unwrap();
            let mut acquired = std::collections::HashSet::new();
            let mut high = 0_u64;
            for chunk in 0..50 {
                let start = high + (chunk % 5) as u64;
                let length = 1 + (chunk * 7) % 23;
                let numbers: Vec<_> = (start..start + length as u64)
                    .flat_map(|n| (0..channels).map(move |c| (n * 16 + c as u64) as f64))
                    .collect();
                let samples = if precision == Precision::F32 {
                    Samples::F32(numbers.iter().map(|x| *x as f32).collect())
                } else {
                    Samples::F64(numbers)
                };
                history
                    .append(SignalBlock::new(source.clone(), start, samples, Vec::new()).unwrap())
                    .unwrap();
                acquired.extend(start..start + length as u64);
                high = start + length as u64;
                let floor = high.saturating_sub(31);
                assert_eq!(
                    history.retained_frames(),
                    acquired.iter().filter(|&&n| n >= floor).count()
                );
                assert!(
                    history.retained_numeric_bytes()
                        <= 31 * channels * if precision == Precision::F32 { 4 } else { 8 }
                );
                for left in high as i64 - 35..high as i64 + 2 {
                    let end = left + 4;
                    let read = history.read_interval(left, end).unwrap();
                    let mut expected: Vec<[i64; 2]> = Vec::new();
                    for n in left..end.min(high as i64) {
                        if n < floor as i64 || !acquired.contains(&(n as u64)) {
                            if let Some(span) = expected.last_mut().filter(|span| span[1] == n) {
                                span[1] += 1;
                            } else {
                                expected.push([n, n + 1]);
                            }
                        }
                    }
                    assert_eq!(read.report.missing, expected);
                    if let Some(block) = read.snapshot {
                        let observed: Vec<f64> = match block.samples() {
                            Samples::F32(v) => v.iter().map(|x| *x as f64).collect(),
                            Samples::F64(v) => v.clone(),
                        };
                        let reference: Vec<_> = (left..end)
                            .flat_map(|n| (0..channels).map(move |c| (n * 16 + c as i64) as f64))
                            .collect();
                        assert_eq!(observed, reference);
                    } else {
                        assert!(!read.report.missing.is_empty() || !read.report.pending.is_empty());
                    }
                }
            }
        }
    }
}

#[test]
fn failed_coordinated_restart_leaves_history_and_graph_unchanged() {
    let source = source();
    let mut history = History::new(source.clone(), HistoryLimits::frames(16)).unwrap();
    history.append(input(&source, 0, 16, Vec::new())).unwrap();
    let graph = Graph::new(Limits::default()).unwrap();
    let token = subscribe(&graph, &graph_key(&source, 0, 16));
    let mut invalid = source.clone();
    invalid.generation = 4;
    invalid.timebase.generation = 4;
    invalid.timebase.rate.numerator = 0;
    assert!(history.restart_with_graph(invalid, &graph).is_err());
    assert_eq!(history.acquired_until(), 16);
    assert_eq!(graph.stats().nodes, 1);
    for job in graph
        .schedule_history(&history.read_interval(0, 16).unwrap())
        .unwrap()
    {
        assert!(job.run());
    }
    assert!(token.take_latest().is_some());
}
