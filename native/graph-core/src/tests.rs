use super::*;

pub(crate) fn source(channels: usize, precision: Precision) -> Source {
    Source {
        stream_id: "test.session.input".into(),
        generation: 3,
        channel_ids: (0..channels).map(|c| format!("input.{c}")).collect(),
        precision,
        timebase: Timebase {
            id: "test.timebase".into(),
            revision: 1,
            clock_domain: "test.virtual".into(),
            generation: 3,
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
            origin_kind: "virtual".into(),
            uncertainty_seconds: None,
        },
        route_revision: "route.1".into(),
        tap: Tap::InputRaw,
        filter_state_revision: "none".into(),
        calibration_revision: "none".into(),
    }
}
pub(crate) fn key() -> FftKey {
    FftKey {
        source: source(2, Precision::F64),
        n: 16,
        hop: 16,
        alignment: 0,
        window: WindowSpec::Boxcar,
        remove_dc: false,
        input_gains: Vec::new(),
    }
}
fn presentation() -> Presentation {
    Presentation {
        color: "blue".into(),
        unit: "FS peak".into(),
    }
}
fn subscribe(graph: &Graph, key: &FftKey, average: Average) -> Subscription {
    graph
        .subscribe(key.clone(), average, presentation())
        .unwrap()
}
fn block(key: &FftKey, start: u64, amplitude: f64) -> Arc<SignalBlock> {
    let values: Vec<_> = (0..key.n)
        .flat_map(|i| {
            (0..key.source.channel_ids.len()).map(move |c| {
                amplitude
                    * (c + 1) as f64
                    * (std::f64::consts::TAU * 3.0 * i as f64 / key.n as f64 + c as f64 * 0.1).cos()
            })
        })
        .collect();
    let samples = if key.source.precision == Precision::F32 {
        Samples::F32(values.iter().map(|x| *x as f32).collect())
    } else {
        Samples::F64(values)
    };
    Arc::new(SignalBlock::new(key.source.clone(), start, samples, Vec::new()).unwrap())
}
fn execute(graph: &Graph, input: Arc<SignalBlock>) {
    for job in graph.schedule(input).unwrap() {
        assert!(job.run());
    }
}
fn psd_at(snapshot: &Snapshot) -> f64 {
    snapshot.raw.numeric().unwrap().psd()[6]
}

#[test]
fn ac05_shared_complex_result_matches_single_subscription() {
    for channels in [2, 4, 8] {
        for precision in [Precision::F32, Precision::F64] {
            let key = FftKey {
                source: source(channels, precision),
                ..key()
            };
            let graph = Graph::new(Limits::default()).unwrap();
            let spectrum = subscribe(&graph, &key, Average::None);
            let spectrogram = subscribe(&graph, &key, Average::None);
            let input = block(&key, 0, 0.125);
            execute(&graph, Arc::clone(&input));
            let a = spectrum.take_latest().unwrap();
            let b = spectrogram.take_latest().unwrap();
            assert!(Arc::ptr_eq(a.raw(), b.raw()));
            assert_eq!(a.raw.id(), b.raw.id());
            assert_eq!(a.raw.interval(), (0, 16));
            assert_eq!(a.raw.key().source.timebase, key.source.timebase);
            assert_eq!(graph.stats().fft_evaluations, 1);
            let single = Graph::new(Limits::default()).unwrap();
            let token = subscribe(&single, &key, Average::None);
            execute(&single, input);
            let expected = token.take_latest().unwrap();
            assert_eq!(
                a.raw.numeric().unwrap().psd(),
                expected.raw.numeric().unwrap().psd()
            );
            assert_eq!(a.raw.key().source.channel_ids, key.source.channel_ids);
        }
    }
}
#[test]
fn ac06_all_signal_conditions_branch_but_display_and_average_share() {
    let base = key();
    let mut variants = Vec::new();
    macro_rules! change {
        ($field:expr, $value:expr) => {{
            let mut k = base.clone();
            $field(&mut k, $value);
            variants.push(k);
        }};
    }
    change!(|k: &mut FftKey, v| k.window = v, WindowSpec::SymmetricHann);
    change!(|k: &mut FftKey, v| k.hop = v, 8);
    change!(|k: &mut FftKey, v| k.n = v, 8);
    change!(|k: &mut FftKey, v| k.alignment = v, 1);
    change!(|k: &mut FftKey, v| k.remove_dc = v, true);
    change!(
        |k: &mut FftKey, v| k.source.stream_id = v,
        "other.session.input".into()
    );
    change!(
        |k: &mut FftKey, v| k.source.route_revision = v,
        "route.2".into()
    );
    change!(|k: &mut FftKey, v| k.source.tap = v, Tap::OutputMixed);
    change!(
        |k: &mut FftKey, v| k.source.filter_state_revision = v,
        "filter.state.2".into()
    );
    change!(
        |k: &mut FftKey, v| k.source.calibration_revision = v,
        "profile.2".into()
    );
    change!(|k: &mut FftKey, v| k.source.timebase.revision = v, 2);
    change!(
        |k: &mut FftKey, v| k.source.timebase.clock_domain = v,
        "other.clock".into()
    );
    change!(
        |k: &mut FftKey, v| k.source.timebase.origin_seconds = v,
        Some(Rational {
            numerator: 10,
            denominator: 1
        })
    );
    let mut k = base.clone();
    k.source.channel_ids.reverse();
    variants.push(k);
    let mut k = base.clone();
    k.source.generation += 1;
    k.source.timebase.generation += 1;
    variants.push(k);
    let mut k = base.clone();
    k.source.precision = Precision::F32;
    variants.push(k);
    let mut k = base.clone();
    k.input_gains = k
        .source
        .channel_ids
        .iter()
        .map(|id| InputGain::new(id.clone(), "cal.2".into(), 2.0).unwrap())
        .collect();
    variants.push(k);
    for variant in variants {
        let graph = Graph::new(Limits::default()).unwrap();
        let a = subscribe(&graph, &base, Average::None);
        let b = subscribe(&graph, &variant, Average::CumulativePsd);
        assert_eq!(graph.stats().nodes, 2);
        execute(&graph, block(&base, 0, 0.125));
        let original = a.take_latest().unwrap();
        if b.take_latest().is_none() {
            execute(&graph, block(&variant, variant.alignment, 0.125));
        }
        assert_eq!(graph.stats().fft_evaluations, 2);
        assert_eq!(original.raw.key(), &base);
    }
    let graph = Graph::new(Limits::default()).unwrap();
    let a = subscribe(&graph, &base, Average::None);
    let b = graph
        .subscribe(
            base.clone(),
            Average::CumulativePsd,
            Presentation {
                color: "red".into(),
                unit: "dBFS".into(),
            },
        )
        .unwrap();
    execute(&graph, block(&base, 0, 0.125));
    let old = a.take_latest().unwrap();
    let other = b.take_latest().unwrap();
    assert!(Arc::ptr_eq(old.raw(), other.raw()));
    assert_eq!(graph.stats().nodes, 1);
    a.set_presentation(Presentation {
        color: "green".into(),
        unit: "PSD".into(),
    })
    .unwrap();
    execute(&graph, block(&base, 16, 0.25));
    assert_eq!(graph.stats().fft_evaluations, 2);
    assert_eq!(old.presentation().color, "blue");
    assert_eq!(a.take_latest().unwrap().presentation().color, "green");
}
#[test]
fn independent_average_reset_and_slow_view_keep_full_measurement_history() {
    let graph = Graph::new(Limits::default()).unwrap();
    let key = key();
    let slow = subscribe(&graph, &key, Average::CumulativePsd);
    let fast = subscribe(&graph, &key, Average::CumulativePsd);
    execute(&graph, block(&key, 0, 0.125));
    let first = fast.take_latest().unwrap();
    let p = psd_at(&first);
    fast.reset_average().unwrap();
    execute(&graph, block(&key, 16, 0.25));
    let second = fast.take_latest().unwrap();
    let all = slow.take_latest().unwrap();
    assert_eq!(second.average_count(), 1);
    assert_eq!(all.average_count(), 2);
    assert!((second.mean_psd().unwrap()[6] - 4.0 * p).abs() < 1e-16);
    assert!((all.mean_psd().unwrap()[6] - 2.5 * p).abs() < 1e-16);
    let late = subscribe(&graph, &key, Average::CumulativePsd);
    for i in 2..66 {
        execute(&graph, block(&key, i * 16, 0.125));
        fast.take_latest();
    }
    let all = slow.take_latest().unwrap();
    let late = late.take_latest().unwrap();
    assert_eq!(all.average_count(), 66);
    assert_eq!(late.average_count(), 64);
    assert_eq!(graph.stats().fft_evaluations, 66);
    assert!(graph.stats().display_replacements >= 64);
    assert_eq!(first.average_count(), 1);
    assert_eq!(psd_at(&first), p);
    // A missing measurement interval resets average state; skipped GUI snapshots do not.
    execute(&graph, block(&key, 68 * 16, 0.125));
    assert_eq!(slow.take_latest().unwrap().average_count(), 1);
}
#[test]
fn ac07_view_view_session_last_release_and_owned_snapshot() {
    let graph = Graph::new(Limits::default()).unwrap();
    let key = key();
    let a = subscribe(&graph, &key, Average::None);
    let b = subscribe(&graph, &key, Average::None);
    let session = subscribe(&graph, &key, Average::None);
    execute(&graph, block(&key, 0, 0.125));
    let owned = a.take_latest().unwrap();
    let weak = Arc::downgrade(owned.raw());
    drop(a);
    execute(&graph, block(&key, 16, 0.125));
    assert!(b.take_latest().is_some());
    drop(b);
    execute(&graph, block(&key, 32, 0.125));
    assert_eq!(session.take_latest().unwrap().raw.interval(), (32, 48));
    assert_eq!(graph.stats().nodes, 1);
    drop(session);
    assert_eq!(graph.stats().nodes, 0);
    assert_eq!(graph.stats().cache_results, 0);
    assert_eq!(graph.stats().subscriptions, 0);
    assert!(graph.schedule(block(&key, 48, 0.125)).unwrap().is_empty());
    assert!(weak.upgrade().is_some());
    drop(owned);
    assert!(weak.upgrade().is_none());
}
#[test]
fn in_flight_compute_publication_and_aba_do_not_resurrect_released_node() {
    let graph = Graph::new(Limits::default()).unwrap();
    let key = key();
    let old = subscribe(&graph, &key, Average::None);
    let job = graph
        .schedule(block(&key, 0, 0.125))
        .unwrap()
        .pop()
        .unwrap();
    let completion = std::thread::spawn(move || job.compute()).join().unwrap();
    let weak = Arc::downgrade(completion.result());
    assert_eq!(graph.stats().in_flight, 1);
    drop(old);
    let new = subscribe(&graph, &key, Average::None);
    assert!(!completion.publish());
    assert!(new.take_latest().is_none());
    assert!(weak.upgrade().is_none());
    assert!(graph.wait_idle(Duration::from_millis(50)));
    execute(&graph, block(&key, 0, 0.25));
    assert_eq!(graph.stats().fft_evaluations, 2);
    assert!(new.take_latest().is_some());
}
#[test]
fn old_generation_completion_cannot_update_reconfigured_view() {
    let graph = Graph::new(Limits::default()).unwrap();
    let key = key();
    let a = subscribe(&graph, &key, Average::CumulativePsd);
    let b = subscribe(&graph, &key, Average::None);
    let job = graph
        .schedule(block(&key, 0, 0.125))
        .unwrap()
        .pop()
        .unwrap();
    let mut next = key.clone();
    next.source.generation += 1;
    next.source.timebase.generation += 1;
    a.reconfigure(next.clone()).unwrap();
    assert!(job.run());
    assert!(a.take_latest().is_none());
    assert!(b.take_latest().is_some());
    execute(&graph, block(&next, 0, 0.125));
    let result = a.take_latest().unwrap();
    assert_eq!(result.average_count(), 1);
    assert_eq!(result.raw.key().source.generation, 4);
}
#[test]
fn shutdown_during_flight_is_idempotent_and_reclaims_after_completion() {
    let graph = Graph::new(Limits::default()).unwrap();
    let key = key();
    let token = subscribe(&graph, &key, Average::None);
    let completion = graph
        .schedule(block(&key, 0, 0.125))
        .unwrap()
        .pop()
        .unwrap()
        .compute();
    let weak = Arc::downgrade(completion.result());
    graph.shutdown();
    graph.shutdown();
    assert!(!graph.wait_idle(Duration::from_millis(1)));
    assert_eq!(graph.stats().nodes, 0);
    assert_eq!(graph.stats().cache_results, 0);
    assert!(token.take_latest().is_none());
    assert!(!completion.publish());
    assert!(graph.wait_idle(Duration::from_millis(50)));
    assert!(weak.upgrade().is_none());
    assert!(graph.schedule(block(&key, 16, 0.125)).is_err());
    assert!(graph.subscribe(key, Average::None, presentation()).is_err());
}
#[test]
fn job_drop_cancels_reservation_and_last_unsubscribe_skips_fft() {
    let graph = Graph::new(Limits::default()).unwrap();
    let key = key();
    let token = subscribe(&graph, &key, Average::None);
    let job = graph
        .schedule(block(&key, 0, 0.125))
        .unwrap()
        .pop()
        .unwrap();
    drop(job);
    assert!(graph.wait_idle(Duration::from_millis(50)));
    assert_eq!(graph.stats().fft_evaluations, 0);
    let job = graph
        .schedule(block(&key, 16, 0.125))
        .unwrap()
        .pop()
        .unwrap();
    drop(token);
    assert!(!job.run());
    assert_eq!(graph.stats().fft_evaluations, 0);
    assert_eq!(graph.stats().in_flight, 0);
}
#[test]
fn bounded_cache_eviction_prefers_unpinned_and_does_not_mutate_held_result() {
    let graph = Graph::new(Limits {
        cache_results: 2,
        ..Limits::default()
    })
    .unwrap();
    let key = key();
    let a = subscribe(&graph, &key, Average::None);
    execute(&graph, block(&key, 0, 0.125));
    let old = a.take_latest().unwrap();
    let p = psd_at(&old);
    execute(&graph, block(&key, 16, 0.25));
    a.take_latest();
    execute(&graph, block(&key, 32, 0.5));
    a.take_latest();
    assert!(graph.cached(&key, 0).is_some());
    assert!(graph.cached(&key, 16).is_none());
    assert!(graph.cached(&key, 32).is_some());
    assert_eq!(psd_at(&old), p);
    assert_eq!(graph.stats().cache_results, 2);
    let graph = Graph::new(Limits {
        cache_numeric_bytes: 1,
        ..Limits::default()
    })
    .unwrap();
    let token = subscribe(&graph, &key, Average::None);
    execute(&graph, block(&key, 0, 0.125));
    assert_eq!(graph.stats().cache_numeric_bytes, 0);
    assert_eq!(token.take_latest().unwrap().raw.interval(), (0, 16));
}
#[test]
fn invalid_windows_and_nonfinite_failures_reset_average_without_zero_filling() {
    let graph = Graph::new(Limits::default()).unwrap();
    let key = key();
    let a = subscribe(&graph, &key, Average::CumulativePsd);
    execute(&graph, block(&key, 0, 0.125));
    a.take_latest();
    let input = SignalBlock::new(
        key.source.clone(),
        16,
        Samples::F64(vec![0.0; 32]),
        vec![InvalidSpan {
            start: 20,
            end: 24,
            channel_id: Some("input.0".into()),
            reason: "missing".into(),
            origin: "fixture".into(),
        }],
    )
    .unwrap();
    execute(&graph, Arc::new(input));
    let invalid = a.take_latest().unwrap();
    assert!(invalid.raw.numeric().is_none());
    assert_eq!(invalid.raw.validity()[0].start, 20);
    assert_eq!(invalid.average_count(), 0);
    assert_eq!(graph.stats().fft_evaluations, 1);
    let input = SignalBlock::new(
        key.source.clone(),
        32,
        Samples::F64(vec![f64::NAN; 32]),
        Vec::new(),
    )
    .unwrap();
    execute(&graph, Arc::new(input));
    let invalid = a.take_latest().unwrap();
    assert!(invalid.raw.numeric().is_none());
    assert!(invalid.raw.error().is_some());
    execute(&graph, block(&key, 48, 0.125));
    assert_eq!(a.take_latest().unwrap().average_count(), 1);
}
#[test]
fn bounded_inflight_rejection_is_atomic_and_duplicate_windows_are_rejected() {
    let graph = Graph::new(Limits {
        max_in_flight: 1,
        ..Limits::default()
    })
    .unwrap();
    let key = key();
    let a = subscribe(&graph, &key, Average::None);
    let mut different = key.clone();
    different.window = WindowSpec::SymmetricHann;
    let b = subscribe(&graph, &different, Average::None);
    assert!(graph.schedule(block(&key, 0, 0.125)).is_err());
    assert_eq!(graph.stats().in_flight, 0);
    drop(b);
    execute(&graph, block(&key, 0, 0.125));
    assert!(graph.schedule(block(&key, 0, 0.125)).is_err());
    let job = graph
        .schedule(block(&key, 16, 0.125))
        .unwrap()
        .pop()
        .unwrap();
    assert!(graph.schedule(block(&key, 32, 0.125)).is_err());
    assert!(job.run());
    execute(&graph, block(&key, 32, 0.125));
    assert!(a.take_latest().is_some());
}
#[test]
fn invalid_reconfiguration_and_capacity_preserve_old_subscription() {
    let graph = Graph::new(Limits {
        max_nodes: 1,
        max_subscriptions: 2,
        ..Limits::default()
    })
    .unwrap();
    let key = key();
    let a = subscribe(&graph, &key, Average::None);
    let b = subscribe(&graph, &key, Average::None);
    assert!(
        graph
            .subscribe(key.clone(), Average::None, presentation())
            .is_err()
    );
    let mut bad = key.clone();
    bad.hop = 0;
    assert!(a.reconfigure(bad).is_err());
    let mut next = key.clone();
    next.window = WindowSpec::SymmetricHann;
    assert!(a.reconfigure(next.clone()).is_err());
    execute(&graph, block(&key, 0, 0.125));
    assert_eq!(a.take_latest().unwrap().raw.key(), &key);
    drop(b);
    a.reconfigure(next).unwrap();
    assert_eq!(graph.stats().nodes, 1);
}
#[test]
fn block_validation_and_full_key_equality_reject_ambiguous_inputs() {
    let key = key();
    let mut duplicate = key.source.clone();
    duplicate.channel_ids[1] = duplicate.channel_ids[0].clone();
    assert!(SignalBlock::new(duplicate, 0, Samples::F64(vec![0.0; 32]), Vec::new()).is_err());
    assert!(
        SignalBlock::new(
            key.source.clone(),
            0,
            Samples::F32(vec![0.0; 32]),
            Vec::new()
        )
        .is_err()
    );
    assert!(
        SignalBlock::new(
            key.source.clone(),
            0,
            Samples::F64(vec![0.0; 31]),
            Vec::new()
        )
        .is_err()
    );
    assert!(
        SignalBlock::new(
            key.source.clone(),
            u64::MAX,
            Samples::F64(vec![0.0; 32]),
            Vec::new()
        )
        .is_err()
    );
    assert!(InputGain::new("input.0".into(), "cal.1".into(), f64::NAN).is_err());
    let graph = Graph::new(Limits::default()).unwrap();
    let mut wrong = key.clone();
    wrong.source.timebase.rate.denominator = 0;
    assert!(
        graph
            .subscribe(wrong, Average::None, presentation())
            .is_err()
    );
    let mut wrong = key.clone();
    wrong.input_gains = vec![InputGain::new("input.1".into(), "cal.1".into(), 1.0).unwrap()];
    assert!(
        graph
            .subscribe(wrong, Average::None, presentation())
            .is_err()
    );
}
#[test]
fn input_correction_and_dc_removal_change_signal_before_fft() {
    let graph = Graph::new(Limits::default()).unwrap();
    let base = key();
    let plain = subscribe(&graph, &base, Average::None);
    let mut corrected = base.clone();
    corrected.input_gains = corrected
        .source
        .channel_ids
        .iter()
        .map(|id| InputGain::new(id.clone(), "cal.1".into(), 2.0).unwrap())
        .collect();
    let token = subscribe(&graph, &corrected, Average::None);
    execute(&graph, block(&base, 0, 0.125));
    assert!(
        (psd_at(&token.take_latest().unwrap()) / psd_at(&plain.take_latest().unwrap()) - 4.0).abs()
            < 1e-12
    );
    let mut dc = base.clone();
    dc.remove_dc = true;
    let token = subscribe(&graph, &dc, Average::None);
    let input = SignalBlock::new(
        base.source.clone(),
        16,
        Samples::F64(vec![0.25; 32]),
        Vec::new(),
    )
    .unwrap();
    execute(&graph, Arc::new(input));
    assert!(
        token
            .take_latest()
            .unwrap()
            .raw
            .numeric()
            .unwrap()
            .psd()
            .iter()
            .all(|x| *x == 0.0)
    );
}

#[test]
fn dropping_owner_releases_registry_and_tokens_do_not_keep_core_alive() {
    let graph = Graph::new(Limits::default()).unwrap();
    let weak_core = Arc::downgrade(&graph.core);
    let key = key();
    let token = subscribe(&graph, &key, Average::None);
    execute(&graph, block(&key, 0, 0.125));
    let held = token.take_latest().unwrap();
    let weak_result = Arc::downgrade(held.raw());
    drop(graph);
    assert!(weak_core.upgrade().is_none());
    assert!(token.take_latest().is_none());
    assert!(weak_result.upgrade().is_some());
    drop(held);
    assert!(weak_result.upgrade().is_none());
    drop(token);
}

#[test]
fn invalid_support_outside_short_fft_does_not_contaminate_that_branch() {
    let graph = Graph::new(Limits::default()).unwrap();
    let long = key();
    let mut short = long.clone();
    short.n = 8;
    let a = subscribe(&graph, &long, Average::None);
    let b = subscribe(&graph, &short, Average::None);
    let input = SignalBlock::new(
        long.source.clone(),
        0,
        Samples::F64(vec![0.125; 32]),
        vec![InvalidSpan {
            start: 10,
            end: 12,
            channel_id: None,
            reason: "missing".into(),
            origin: "fixture".into(),
        }],
    )
    .unwrap();
    execute(&graph, Arc::new(input));
    assert!(a.take_latest().unwrap().raw.numeric().is_none());
    let valid = b.take_latest().unwrap();
    assert!(valid.raw.validity().is_empty());
    assert!(valid.raw.numeric().is_some());
    assert_eq!(graph.stats().fft_evaluations, 1);
}
