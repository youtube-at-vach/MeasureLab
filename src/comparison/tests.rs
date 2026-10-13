use super::*;
fn settings() -> Settings {
    Settings {
        enabled: true,
        size: 1024,
        averages: 4,
        window: Window::Rectangular,
        delay_band_hz: [100.0, 12000.0],
        ..Default::default()
    }
}
fn analyzer(s: Settings) -> Analyzer {
    Analyzer::new(s, 48000, 7, 2, 16, calibration::Set::default())
}

#[test]
fn all_supported_sizes_windows_and_nominal_rates_match_known_tone() {
    for size in SIZES {
        for rate in [44100, 48000, 96000, 192000, 768000] {
            for window in [Window::Rectangular, Window::Hann, Window::BlackmanHarris] {
                let s = Settings {
                    size,
                    window,
                    averages: 2,
                    ..settings()
                };
                let mut a = Analyzer::new(s, rate, 1, 1, 16, calibration::Set::default());
                for n in 0..size * 2 {
                    let p = TAU * 32.0 * n as f64 / size as f64;
                    a.push_pair(
                        (1u64 << 54) + n as u64,
                        [0.1 * p.sin() + 0.3, 0.05 * (p + 0.5).sin() - 0.1],
                    );
                }
                let r = a.result();
                assert_eq!(r.state, State::Valid);
                let b = &r.bins[32];
                assert!((b.gain.unwrap() - 0.5).abs() < 1e-10);
                assert!((b.phase_lead_degrees.unwrap() - 0.5f64.to_degrees()).abs() < 1e-8);
                assert!(
                    (b.phase_delay_seconds.unwrap()
                        + 0.5 / (TAU * 32.0 * rate as f64 / size as f64))
                        .abs()
                        < 1e-12
                );
                assert_eq!(r.nominal_sample_rate_hz, rate);
                assert!(r.delay.is_none());
            }
        }
    }
}
fn sample(n: usize, delay: f64, gain: f64) -> [f64; 2] {
    let wave = |t: f64| {
        (4..=96)
            .map(|k| (TAU * k as f64 * t / 1024.0 + (k * k) as f64 * 0.37).sin() * 0.004)
            .sum::<f64>()
    };
    [wave(n as f64) + 0.2, gain * wave(n as f64 - delay) - 0.1]
}
#[test]
fn known_integer_fractional_delay_and_gain_sign_keep_integer_clock() {
    for (delay, gain, origin) in [
        (0.0, 0.5, 0),
        (7.0, -0.75, 11),
        (2.375, 1e-7, (1u64 << 54) + 7),
        (-4.25, 2.0, 99),
    ] {
        let mut a = analyzer(settings());
        for n in 0..4096 {
            a.push_pair(origin + n as u64, sample(n, delay, gain));
        }
        let r = a.result();
        assert_eq!(r.state, State::Valid);
        assert_eq!(r.sample_range, origin..origin + 4096);
        assert_eq!(r.latest_window, origin + 3072..origin + 4096);
        assert_eq!(r.averaged_windows, 4);
        for k in 4..=96 {
            let b = &r.bins[k];
            assert_eq!(b.state, BinState::Valid);
            assert!((b.gain.unwrap() - gain.abs()).abs() < gain.abs() * 1e-7 + 1e-15);
            let h = Complex::from_polar(
                gain.abs(),
                -TAU * k as f64 * delay / 1024.0
                    + if gain < 0.0 {
                        std::f64::consts::PI
                    } else {
                        0.0
                    },
            );
            assert!((b.transfer_re.unwrap() - h.re).abs() < gain.abs() * 1e-7 + 1e-15);
            assert!((b.transfer_im.unwrap() - h.im).abs() < gain.abs() * 1e-7 + 1e-15);
            assert!((b.coherence.unwrap() - 1.0).abs() < 1e-12);
        }
        let d = r.delay.as_ref().unwrap();
        assert!((d.seconds * 48000.0 - delay).abs() < 1e-6, "{d:?}");
        assert!(d.phase_residual_rms_degrees < 1e-5);
    }
}
#[test]
fn full_complex_dft_and_parseval_match_all_windows() {
    for window in [Window::Rectangular, Window::Hann, Window::BlackmanHarris] {
        let s = Settings {
            window,
            ..settings()
        };
        let mut a = analyzer(s);
        for n in 0..4096 {
            a.push_pair(n as u64, sample(n, 2.375, 0.5));
        }
        let weights: Vec<_> = (0..1024).map(|i| window.weight(i, 1024)).collect();
        let norm = 1.0 / (48000.0 * weights.iter().map(|v| v * v).sum::<f64>());
        let means: [f64; 2] =
            std::array::from_fn(|ch| (0..1024).map(|n| sample(n, 2.375, 0.5)[ch] / 1024.0).sum());
        for k in [0, 3, 4, 17, 72, 96, 97, 512] {
            let xy: [Complex<f64>; 2] = std::array::from_fn(|ch| {
                (0..1024)
                    .map(|n| {
                        Complex::from_polar(
                            (sample(n, 2.375, 0.5)[ch] - means[ch]) * weights[n],
                            -TAU * k as f64 * n as f64 / 1024.0,
                        )
                    })
                    .sum()
            });
            let factor = norm * if k == 0 || k == 512 { 1.0 } else { 2.0 };
            let p = [
                xy[0].norm_sqr() * factor,
                xy[1].norm_sqr() * factor,
                (xy[0].conj() * xy[1]).re * factor,
                (xy[0].conj() * xy[1]).im * factor,
            ];
            let b = &a.result().bins[k];
            for (actual, expected) in [b.reference_psd, b.response_psd, b.cross_re, b.cross_im]
                .into_iter()
                .zip(p)
            {
                assert!((actual - expected).abs() < expected.abs() * 1e-9 + 1e-17);
            }
        }
        let power = a.result().bins.iter().map(|b| b.reference_psd).sum::<f64>()
            * a.result().bin_width_hz();
        let expected = (0..1024)
            .map(|n| ((sample(n, 2.375, 0.5)[0] - means[0]) * weights[n]).powi(2))
            .sum::<f64>()
            / weights.iter().map(|v| v * v).sum::<f64>();
        assert!((power - expected).abs() < 1e-12);
    }
}
#[test]
fn finite_tail_gaps_and_nonfinite_clear_old_averages_without_padding() {
    let mut a = analyzer(settings());
    for n in 0..4096 {
        a.push_pair(n as u64, sample(n, 2.0, 0.5));
    }
    let held = a.result().clone();
    for n in 4096..4600 {
        a.push_pair(n as u64, sample(n, 2.0, 0.5));
    }
    a.gap_to(4600);
    assert_eq!(a.result().bins, held.bins);
    assert_eq!(a.result().sample_range, held.sample_range);
    a.gap_to(4610);
    assert_eq!(a.result().state, State::Missing);
    assert_eq!(a.result().missing_samples, 10);
    assert!(a.result().bins.is_empty());
    a.push_pair(4610, [f64::NAN, 0.0]);
    assert_eq!(a.result().state, State::NonFinite);
    for n in 4611..8707 {
        a.push_pair(n as u64, sample(n, 3.0, 0.25));
    }
    assert_eq!(a.result().state, State::Valid);
    assert_eq!(a.result().sample_range, 4611..8707);
    assert_eq!(a.result().missing_samples, 10);
    assert_eq!(a.result().invalid_samples, 1);
}
#[test]
fn zero_ref_zero_response_single_sine_and_uncorrelated_noise_are_distinct() {
    let mut a = analyzer(settings());
    for n in 0..4096 {
        a.push_pair(n, [0.0, 0.0]);
    }
    assert!(
        a.result()
            .bins
            .iter()
            .all(|b| b.state == BinState::ReferenceLost && b.gain.is_none())
    );
    let mut a = analyzer(settings());
    for n in 0..4096 {
        a.push_pair(n as u64, [sample(n, 0.0, 1.0)[0], 0.0]);
    }
    assert_eq!(a.result().bins[20].gain, Some(0.0));
    assert!(a.result().bins[20].phase_lead_degrees.is_none());
    let mut a = analyzer(Settings {
        window: Window::Hann,
        ..settings()
    });
    for n in 0..4096 {
        let p = TAU * 32.0 * n as f64 / 1024.0;
        a.push_pair(n, [0.125 * p.sin(), 0.0625 * (p + 0.5).sin()]);
    }
    assert!(a.result().delay.is_none());
    assert!((a.result().bins[32].phase_lead_degrees.unwrap() - 0.5f64.to_degrees()).abs() < 1e-9);
    let mut a = analyzer(Settings {
        averages: 128,
        ..settings()
    });
    let mut random = 0xf6378291_u64;
    for n in 0..128 * 1024 {
        let pair = std::array::from_fn(|_| {
            random ^= random << 13;
            random ^= random >> 7;
            random ^= random << 17;
            (random >> 11) as f64 / (1u64 << 53) as f64 - 0.5
        });
        a.push_pair(n, pair);
    }
    let mean = a.result().bins[1..512]
        .iter()
        .map(|b| b.coherence.unwrap())
        .sum::<f64>()
        / 511.0;
    assert!(mean < 0.02, "noise coherence {mean}");
    assert!(
        a.result().bins[1..512]
            .iter()
            .all(|b| b.gain.is_none() && b.state == BinState::Incoherent)
    );
    assert!(a.result().delay.is_none());
}
#[test]
fn signed_channel_calibration_scales_complex_values_and_not_raw_ref_gate() {
    let set = calibration::Set::default()
        .with(
            0,
            Some(
                calibration::Calibration::new(
                    "ref".into(),
                    1,
                    -2.0,
                    10.0,
                    "V".into(),
                    "test".into(),
                )
                .unwrap(),
            ),
        )
        .unwrap()
        .with(
            1,
            Some(
                calibration::Calibration::new(
                    "response".into(),
                    1,
                    4.0,
                    -100.0,
                    "A".into(),
                    "test".into(),
                )
                .unwrap(),
            ),
        )
        .unwrap();
    let mut a = Analyzer::new(settings(), 48000, 1, 1, 2, set);
    for n in 0..4096 {
        a.push_pair(n as u64, sample(n, 0.0, 0.5));
    }
    let b = &a.result().bins[20];
    assert!((b.transfer_re.unwrap() + 1.0).abs() < 1e-10);
    assert!((b.phase_lead_degrees.unwrap().abs() - 180.0).abs() < 1e-8);
}

#[test]
fn non_bin_sine_leakage_does_not_establish_broadband_delay() {
    for window in [Window::Rectangular, Window::Hann, Window::BlackmanHarris] {
        let mut a = analyzer(Settings {
            window,
            ..settings()
        });
        for n in 0..4096 {
            let p = TAU * 32.47 * n as f64 / 1024.0;
            a.push_pair(n, [0.125 * p.sin(), 0.0625 * (p + 0.5).sin()]);
        }
        assert_eq!(a.result().state, State::Valid);
        assert!(
            a.result().delay.is_none(),
            "{window:?}: {:?}",
            a.result().delay
        );
    }
}
#[test]
fn known_fir_complex_response_matches_theory_and_noise_coherence_matches_power_ratio() {
    let mut a = analyzer(settings());
    for n in 0..4096 {
        let wave = |offset: usize| sample(n + 1024 - offset, 0.0, 1.0)[0] - 0.2;
        a.push_pair(
            n as u64,
            [wave(0), 0.5 * wave(0) + 0.3 * wave(1) - 0.1 * wave(2)],
        );
    }
    for k in 4..=96 {
        let h = Complex::new(0.5, 0.0) + Complex::from_polar(0.3, -TAU * k as f64 / 1024.0)
            - Complex::from_polar(0.1, -2.0 * TAU * k as f64 / 1024.0);
        let b = &a.result().bins[k];
        assert!((b.transfer_re.unwrap() - h.re).abs() < 1e-9);
        assert!((b.transfer_im.unwrap() - h.im).abs() < 1e-9);
    }
    let mut a = analyzer(Settings {
        averages: 256,
        minimum_coherence: 0.0,
        ..settings()
    });
    let mut random = 0xc3284391_u64;
    for n in 0..256 * 1024 {
        let mut noise = || {
            random ^= random << 13;
            random ^= random >> 7;
            random ^= random << 17;
            (random >> 11) as f64 / (1u64 << 53) as f64 - 0.5
        };
        let x = noise();
        let y = 0.5 * x + 0.25 * noise();
        a.push_pair(n, [x, y]);
    }
    let coherence = a.result().bins[1..512]
        .iter()
        .map(|b| b.coherence.unwrap())
        .sum::<f64>()
        / 511.0;
    assert!((coherence - 0.8).abs() < 0.01, "{coherence}");
}
