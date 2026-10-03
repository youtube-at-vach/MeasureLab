use super::*;
use crate::{Average, FftKey, Graph, Limits, Presentation, WindowSpec, tests::source};
use std::sync::Arc;
fn fir(channels: usize, centered: bool) -> Filter {
    Filter::new(
        source(channels, Precision::F64),
        "derived".into(),
        "derived.clock".into(),
        FilterConfig::Fir {
            coefficients: vec![0.25, 0.5, 0.25],
            target_rate: Rational {
                numerator: 24000,
                denominator: 1,
            },
            centered,
            revision: "test".into(),
        },
        FilterLimits::default(),
    )
    .unwrap()
}
fn block(f: &Filter, start: u64, end: u64) -> SignalBlock {
    SignalBlock::new(
        f.input_source().clone(),
        start,
        Samples::F64(
            (start..end)
                .flat_map(|n| {
                    (0..f.input_source().channel_ids.len()).map(move |c| (n + c as u64) as f64)
                })
                .collect(),
        ),
        Vec::new(),
    )
    .unwrap()
}
fn values(block: &SignalBlock) -> &[f64] {
    let Samples::F64(v) = block.samples() else {
        panic!()
    };
    v
}
fn tokens(graph: &Graph, f: &Filter) -> (crate::Subscription, crate::Subscription) {
    let key = FftKey {
        source: f.output_source().clone(),
        n: 16,
        hop: 16,
        alignment: 0,
        window: WindowSpec::Boxcar,
        remove_dc: false,
        input_gains: Vec::new(),
    };
    let make = || {
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
    };
    (make(), make())
}
#[test]
fn ac10_chunks_phase_gap_and_independent_finite_sum() {
    for channels in [1, 2, 4, 8] {
        for pattern in [
            vec![1031],
            vec![1],
            vec![127],
            vec![256],
            vec![3, 128, 1, 7, 256, 2],
        ] {
            let mut f = fir(channels, false);
            let mut output = Vec::new();
            let mut spans = Vec::new();
            let mut cursor = 0;
            let mut i = 0;
            while cursor < 1031 {
                if cursor == 100 {
                    cursor = 104;
                }
                let end = (cursor + pattern[i % pattern.len()]).min(if cursor < 100 {
                    100
                } else {
                    1031
                });
                let input = block(&f, cursor, end);
                if let Some(b) = f.process(&input).unwrap() {
                    output.extend_from_slice(values(&b));
                    spans.extend(b.validity);
                }
                assert!(f.retained_frames() <= 3);
                cursor = end;
                i += 1;
            }
            assert!(f.finish(1031).unwrap().is_none());
            for m in 0usize..516 {
                for c in 0..channels {
                    let expected: f64 = [0.25, 0.5, 0.25]
                        .iter()
                        .enumerate()
                        .filter_map(|(j, h)| {
                            let n = (2 * m).checked_sub(j)?;
                            Some(if (100..104).contains(&n) {
                                0.0
                            } else {
                                h * (n + c) as f64
                            })
                        })
                        .sum();
                    assert_eq!(output[m * channels + c], expected);
                }
                assert_eq!(
                    spans
                        .iter()
                        .any(|s| s.reason == "warmup" && s.start <= m as u64 && (m as u64) < s.end),
                    m == 0
                );
                assert_eq!(
                    spans
                        .iter()
                        .any(|s| s.reason == "gap" && s.start <= m as u64 && (m as u64) < s.end),
                    (50..53).contains(&m)
                );
            }
            let metadata = f.metadata();
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
            assert_eq!(
                metadata.signal_delay_output_samples,
                Some(Rational {
                    numerator: 1,
                    denominator: 2
                })
            );
            assert_eq!(metadata.processing_latency_seconds, None);
        }
    }
}
#[test]
fn centered_waits_and_finish_preserves_endpoint_and_trailing_gap() {
    let mut f = fir(1, true);
    let b = block(&f, 0, 1);
    assert!(f.process(&b).unwrap().is_none());
    let b = block(&f, 1, 2);
    let out = f.process(&b).unwrap().unwrap();
    assert_eq!(values(&out), &[0.25]);
    assert_eq!(out.interval(), (0, 1));
    let last = f.finish(5).unwrap().unwrap();
    assert_eq!(last.interval(), (1, 3));
    assert!(last.validity.iter().any(|s| s.reason == "gap"));
    assert!(
        last.validity
            .iter()
            .any(|s| s.reason == "warmup" && s.end == 3)
    );
    assert!(f.finish(5).is_err());
}
#[test]
fn fir_channel_validity_and_nonfinite_expand_support() {
    let mut f = fir(2, false);
    let mut input = block(&f, 0, 10);
    input.validity.push(InvalidSpan {
        start: 2,
        end: 3,
        channel_id: Some("input.0".into()),
        reason: "missing".into(),
        origin: "device".into(),
    });
    let Samples::F64(v) = &mut input.samples else {
        panic!()
    };
    v[9] = f64::NAN;
    let out = f.process(&input).unwrap().unwrap();
    assert!(values(&out).iter().all(|v| v.is_finite()));
    assert!(out.validity.iter().any(|s| s.start == 1
        && s.end == 3
        && s.channel_id.as_deref() == Some("input.0")
        && s.origin == "device"));
    assert!(out.validity.iter().any(|s| s.start == 2
        && s.end == 4
        && s.channel_id.as_deref() == Some("input.1")
        && s.reason == "nonfinite"));
}
#[test]
fn rejection_does_not_advance_state() {
    let mut f = fir(2, false);
    let b = block(&f, 0, 11);
    f.process(&b).unwrap();
    let mut expected = f.clone();
    let next = block(&f, 11, 31);
    assert!(f.process(&b).is_err());
    let mut bad = block(&f, 11, 31);
    bad.source.route_revision = "changed".into();
    assert!(f.process(&bad).is_err());
    let too_big = block(&f, 11, 65548);
    assert!(f.process(&too_big).is_err());
    assert_eq!(
        values(&f.process(&next).unwrap().unwrap()),
        values(&expected.process(&next).unwrap().unwrap())
    );
}
#[test]
fn shared_graph_filter_lifetime_invalid_fft_and_generation_fence() {
    let graph = Graph::new(Limits::default()).unwrap();
    let f = fir(2, false);
    let output = f.output_source().clone();
    let (a, b) = tokens(&graph, &f);
    let input = block(&f, 0, 32);
    graph.attach_filter(f).unwrap();
    let out = Arc::new(graph.process_filter(&output, &input).unwrap().unwrap());
    for job in graph.schedule(out).unwrap() {
        assert!(job.run());
    }
    let x = a.take_latest().unwrap();
    let y = b.take_latest().unwrap();
    assert!(Arc::ptr_eq(x.raw(), y.raw()));
    assert!(x.raw().numeric().is_none());
    assert_eq!(x.average_count(), 0);
    let mut duplicate = fir(2, false);
    let parent = duplicate.input_source().clone();
    assert!(graph.attach_filter(duplicate.clone()).is_err());
    let input = block(&duplicate, 32, 64);
    let out = Arc::new(graph.process_filter(&output, &input).unwrap().unwrap());
    let completion = graph.schedule(out).unwrap().pop().unwrap().compute();
    graph
        .retire_stream_before(&parent.stream_id, parent.generation + 1)
        .unwrap();
    assert_eq!(graph.filter_count(), 0);
    assert!(!completion.publish());
    assert!(a.take_latest().is_none());
    assert!(graph.process_filter(&output, &input).is_err());
    assert!(a.reconfigure(completion_key(&output)).is_err());
    duplicate.process(&block(&duplicate, 0, 4)).unwrap(); // Independent external state cannot re-enter the retired graph.
    assert!(graph.attach_filter(duplicate).is_err());
    drop(a);
    drop(b);
    graph.shutdown();
    assert_eq!(graph.stats().nodes, 0);
}
fn completion_key(source: &Source) -> FftKey {
    FftKey {
        source: source.clone(),
        n: 16,
        hop: 16,
        alignment: 0,
        window: WindowSpec::Boxcar,
        remove_dc: false,
        input_gains: Vec::new(),
    }
}
#[test]
fn last_token_and_shutdown_release_state() {
    let graph = Graph::new(Limits::default()).unwrap();
    let f = fir(1, false);
    let (a, b) = tokens(&graph, &f);
    graph.attach_filter(f).unwrap();
    drop(a);
    assert_eq!(graph.filter_count(), 1);
    drop(b);
    assert_eq!(graph.filter_count(), 0);
    let f = fir(1, false);
    let (a, b) = tokens(&graph, &f);
    graph.attach_filter(f).unwrap();
    graph.shutdown();
    assert_eq!(graph.filter_count(), 0);
    drop((a, b));
}
#[test]
fn identity_has_coefficients_and_exact_rational_origins() {
    let f = fir(1, false);
    let mut source = f.input_source().clone();
    source.timebase.origin_sample = 3;
    source.timebase.origin_seconds = Some(Rational {
        numerator: 10,
        denominator: 1,
    });
    let other = Filter::new(
        source,
        "derived".into(),
        "derived.clock".into(),
        FilterConfig::Fir {
            coefficients: vec![0.125, 0.75, 0.125],
            target_rate: Rational {
                numerator: 24000,
                denominator: 1,
            },
            centered: false,
            revision: "test".into(),
        },
        FilterLimits::default(),
    )
    .unwrap();
    assert_ne!(
        other.output_source().filter_state_revision,
        f.output_source().filter_state_revision
    );
    assert_eq!(
        other.output_source().timebase.origin_seconds,
        Some(Rational {
            numerator: 159999,
            denominator: 16000
        })
    );
    assert_eq!(
        other
            .metadata()
            .map_position(&Rational {
                numerator: 1025,
                denominator: 2
            })
            .unwrap(),
        Rational {
            numerator: 1025,
            denominator: 4
        }
    );
    assert!(
        rate_ratio(
            &Rational {
                numerator: 0,
                denominator: 1
            },
            &Rational {
                numerator: 1,
                denominator: 1
            }
        )
        .is_err()
    );
}
#[test]
fn sos_chunk_state_and_atomic_invalid_rejection() {
    let h = vec![[0.25, 0.5, 0.25, 1.0, -0.2, 0.1]];
    let mut whole = SosState::new(h.clone(), 4).unwrap();
    let mut split = whole.clone();
    let input: Vec<_> = (0..400).map(|n| (n as f64 * 0.123).sin()).collect();
    let expected = whole.process(&input).unwrap();
    let mut output = Vec::new();
    for x in input.chunks(4) {
        output.extend(split.process(x).unwrap());
    }
    assert_eq!(output, expected);
    assert_eq!(split.final_state(), whole.final_state());
    let before = split.final_state().to_vec();
    assert!(split.process(&[f64::NAN; 4]).is_err());
    assert_eq!(split.final_state(), before);
    let mut f = Filter::new(
        source(4, Precision::F64),
        "sos".into(),
        "sos.clock".into(),
        FilterConfig::Sos {
            coefficients: h,
            revision: "sos".into(),
        },
        FilterLimits::default(),
    )
    .unwrap();
    assert!(f.process(&block(&f, 1, 2)).is_err());
    let b = block(&f, 0, 20);
    let out = f.process(&b).unwrap().unwrap();
    assert_eq!(out.validity[0].reason, "warmup");
    assert_eq!(out.validity[0].end, 20);
}

#[test]
fn rejected_derived_fence_is_atomic_and_restart_resets_phase() {
    let graph = Graph::new(Limits {
        max_subscriptions: 1,
        ..Limits::default()
    })
    .unwrap();
    let f = fir(1, false);
    let parent = f.input_source().clone();
    let output = f.output_source().clone();
    let a = graph
        .subscribe(
            completion_key(&output),
            Average::None,
            Presentation {
                color: "x".into(),
                unit: "FS".into(),
            },
        )
        .unwrap();
    graph.attach_filter(f.clone()).unwrap();
    assert!(
        graph
            .retire_stream_before(&parent.stream_id, parent.generation + 1)
            .is_err()
    );
    assert_eq!(graph.filter_count(), 1);
    let input = block(&f, 0, 32);
    assert!(graph.process_filter(&output, &input).unwrap().is_some());
    drop(a);
    let mut new_parent = parent;
    new_parent.generation += 1;
    new_parent.timebase.generation += 1;
    let replacement = Filter::new(
        new_parent,
        "derived".into(),
        "derived.clock".into(),
        FilterConfig::Fir {
            coefficients: vec![0.25, 0.5, 0.25],
            target_rate: Rational {
                numerator: 24000,
                denominator: 1,
            },
            centered: false,
            revision: "test".into(),
        },
        FilterLimits::default(),
    )
    .unwrap();
    let output = replacement.output_source().clone();
    let a = graph
        .subscribe(
            completion_key(&output),
            Average::None,
            Presentation {
                color: "x".into(),
                unit: "FS".into(),
            },
        )
        .unwrap();
    let input = block(&replacement, 0, 4);
    graph.attach_filter(replacement).unwrap();
    let out = graph.process_filter(&output, &input).unwrap().unwrap();
    assert_eq!(out.interval(), (0, 2));
    assert!(
        out.validity
            .iter()
            .any(|s| s.start == 0 && s.reason == "warmup")
    );
    drop(a);
}
#[test]
fn validity_and_upsample_capacity_rejection_leave_prior_state() {
    let mut f = fir(1, false);
    f.limits.max_validity_spans = 1;
    let input = block(&f, 0, 4);
    // Two distinct invalidity origins exceed the compacted span budget.
    let mut invalid = block(&f, 0, 4);
    invalid.validity.push(InvalidSpan {
        start: 0,
        end: 1,
        channel_id: None,
        reason: "missing".into(),
        origin: "device".into(),
    });
    assert!(f.process(&invalid).is_err());
    assert_eq!(f.cursor, 0);
    assert_eq!(f.retained_frames(), 0);
    assert!(f.process(&input).unwrap().is_some());
    let mut up = Filter::new(
        source(1, Precision::F64),
        "up".into(),
        "up.clock".into(),
        FilterConfig::Fir {
            coefficients: vec![1.0],
            target_rate: Rational {
                numerator: 48000 * 512,
                denominator: 1,
            },
            centered: false,
            revision: "up".into(),
        },
        FilterLimits {
            max_output_frames: 1024,
            ..FilterLimits::default()
        },
    )
    .unwrap();
    assert!(up.process(&block(&up, 0, 3)).is_err());
    assert_eq!(up.cursor, 0);
    assert_eq!(
        values(&up.process(&block(&up, 0, 1)).unwrap().unwrap()).len(),
        512
    );
}

#[test]
fn sos_output_limit_rejection_preserves_state() {
    let mut f = Filter::new(
        source(1, Precision::F64),
        "sos".into(),
        "sos.clock".into(),
        FilterConfig::Sos {
            coefficients: vec![[1.0, 0.0, 0.0, 1.0, 0.0, 0.0]],
            revision: "identity".into(),
        },
        FilterLimits {
            max_output_frames: 2,
            ..FilterLimits::default()
        },
    )
    .unwrap();
    assert!(f.process(&block(&f, 0, 3)).is_err());
    assert_eq!(f.cursor, 0);
    assert_eq!(
        values(&f.process(&block(&f, 0, 2)).unwrap().unwrap()),
        &[0.0, 1.0]
    );
}

fn widening(config: FilterConfig, precision: Precision) -> Result<Filter, String> {
    Filter::new_with_conversion(
        source(2, precision),
        "derived".into(),
        "derived.clock".into(),
        config,
        FilterLimits::default(),
        Some(InputConversion::F32ToF64Exact),
    )
}
fn identity() -> FilterConfig {
    FilterConfig::Fir {
        coefficients: vec![1.],
        target_rate: Rational {
            numerator: 48000,
            denominator: 1,
        },
        centered: false,
        revision: "identity".into(),
    }
}
#[test]
fn explicit_widening_preserves_f32_extremes_and_source_identity() {
    let mut f = widening(identity(), Precision::F32).unwrap();
    let input = vec![
        f32::from_bits(1),
        -f32::from_bits(1),
        f32::MAX,
        -f32::MAX,
        0.,
        -0.,
        1.0000001,
        -1.0000001,
    ];
    let b = SignalBlock::new(
        f.input_source().clone(),
        0,
        Samples::F32(input.clone()),
        vec![],
    )
    .unwrap();
    let before = input.iter().map(|v| v.to_bits()).collect::<Vec<_>>();
    let out = f.process(&b).unwrap().unwrap();
    for (actual, expected) in values(&out).iter().zip(&input) {
        // FIR summation may normalize signed zero; all nonzero finite values widen exactly.
        if *expected != 0. {
            assert_eq!(actual.to_bits(), f64::from(*expected).to_bits());
        } else {
            assert_eq!(*actual, 0.);
        }
    }
    let Samples::F32(raw) = b.samples() else {
        panic!()
    };
    assert_eq!(raw.iter().map(|v| v.to_bits()).collect::<Vec<_>>(), before);
    assert_eq!(f.metadata().parent.precision, Precision::F32);
    assert_eq!(f.metadata().output.precision, Precision::F64);
    assert_eq!(
        f.metadata().input_conversion,
        Some(InputConversion::F32ToF64Exact)
    );
    assert!(
        f.output_source()
            .filter_state_revision
            .contains("f32-to-f64-exact-v1")
    );
    assert_eq!(f.metadata().processing_latency_seconds, None);
    assert!(widening(identity(), Precision::F64).is_err());
    let f64 = Filter::new(
        source(2, Precision::F64),
        "derived".into(),
        "derived.clock".into(),
        identity(),
        FilterLimits::default(),
    )
    .unwrap();
    assert_ne!(f.output_source(), f64.output_source());
    assert!(
        serde_json::to_value(f64.metadata())
            .unwrap()
            .get("input_conversion")
            .is_none()
    );
}
#[test]
fn widening_keeps_invalid_support_and_rejects_sos_atomically() {
    let config = FilterConfig::Fir {
        coefficients: vec![0.25, 0.5, 0.25],
        target_rate: Rational {
            numerator: 24000,
            denominator: 1,
        },
        centered: false,
        revision: "p2".into(),
    };
    let mut f = widening(config, Precision::F32).unwrap();
    let mut v = vec![1.; 20];
    v[9] = f32::NAN;
    let b = SignalBlock::new(
        f.input_source().clone(),
        0,
        Samples::F32(v),
        vec![InvalidSpan {
            start: 2,
            end: 3,
            channel_id: Some("input.0".into()),
            reason: "unsupported".into(),
            origin: "backend.flags:1".into(),
        }],
    )
    .unwrap();
    let out = f.process(&b).unwrap().unwrap();
    assert!(
        out.validity()
            .iter()
            .any(|s| s.start == 1 && s.end == 3 && s.origin == "backend.flags:1")
    );
    assert!(out.validity().iter().any(|s| s.start == 2
        && s.end == 4
        && s.reason == "nonfinite"
        && s.channel_id.as_deref() == Some("input.1")));
    assert!(values(&out).iter().all(|v| v.is_finite()));
    let mut sos = widening(
        FilterConfig::Sos {
            coefficients: vec![[1., 0., 0., 1., 0., 0.]],
            revision: "sos".into(),
        },
        Precision::F32,
    )
    .unwrap();
    let bad = SignalBlock::new(
        sos.input_source().clone(),
        0,
        Samples::F32(vec![1., f32::INFINITY]),
        vec![],
    )
    .unwrap();
    assert_eq!(
        sos.process(&bad).unwrap_err(),
        "unsupported_iir_gap_or_invalid"
    );
    assert_eq!(sos.cursor, 0);
    assert!(sos.sos_state().unwrap().iter().all(|v| *v == 0.));
}
