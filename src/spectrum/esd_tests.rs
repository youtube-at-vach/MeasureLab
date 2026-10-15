use super::*;

fn transient_settings(size: usize) -> Settings {
    let mut settings = Settings {
        size,
        ..Settings::default()
    };
    settings.select_quantity(Quantity::Esd);
    settings
}

#[test]
fn esd_preset_only_applies_on_entry_and_keeps_explicit_edits() {
    let mut settings = transient_settings(4096);
    assert_eq!(settings.window, Window::Rectangular);
    assert_eq!(settings.averages, 1);
    assert!(!settings.remove_dc);
    settings.window = Window::Hann;
    settings.averages = 16;
    settings.remove_dc = true;
    let edited = settings;
    settings.select_quantity(Quantity::Esd);
    assert_eq!(settings, edited);
    settings.select_quantity(Quantity::Psd);
    assert_eq!(settings.window, Window::Hann);
    settings.select_quantity(Quantity::Esd);
    assert_eq!(settings, transient_settings(4096));
}

#[test]
fn esd_impulse_has_exact_one_sided_scaling_at_every_fft_size() {
    for size in FFT_SIZES {
        for precision in [Precision::F64, Precision::F32] {
            let mut analyzer = Analyzer::new(
                Settings {
                    precision,
                    ..transient_settings(size)
                },
                48000,
            );
            assert!(analyzer.energy().is_none());
            let mut samples = vec![0.0; size];
            samples[17] = 0.75;
            analyzer.update_samples(&samples, size as u64);
            let two_sided = (0.75_f64 / 48000.0).powi(2);
            let tolerance = if precision == Precision::F64 {
                3e-12
            } else {
                3e-6
            };
            for (bin, &actual) in analyzer.power().iter().enumerate() {
                let expected = two_sided
                    * if bin == 0 || bin == size / 2 {
                        1.0
                    } else {
                        2.0
                    };
                assert!(
                    (actual / expected - 1.0).abs() < tolerance,
                    "N={size}, {precision:?}, bin={bin}: {actual} != {expected}"
                );
            }
            assert!(
                (analyzer.energy().unwrap() / (0.75_f64.powi(2) / 48000.0) - 1.0).abs() < tolerance
            );
            let reading = analyzer.cursor(6000.0).unwrap();
            assert_eq!(reading.value, analyzer.power()[size / 8]);
            assert!((reading.level_db - 10.0 * reading.value.log10()).abs() < 1e-12);
            assert!((analyzer.db()[size / 8] as f64 - reading.level_db).abs() < 1e-5);
            assert_eq!(reading.window.linear_unit(), "FS²·s/Hz");
            assert_eq!(reading.window.db_unit(), "dB re FS²·s/Hz");
            assert!(analyzer.band(0.0, 24000.0).is_none());
        }
    }
}

#[test]
fn esd_contained_damped_pulse_is_invariant_on_common_frequency_grid() {
    let pulse: Vec<_> = (0..129)
        .map(|i| (-i as f64 / 20.0).exp() * (0.17 * i as f64).cos())
        .collect();
    let mut reference = Vec::new();
    for size in FFT_SIZES {
        let mut samples = vec![0.0; size];
        samples[31..31 + pulse.len()].copy_from_slice(&pulse);
        let mut analyzer = Analyzer::new(transient_settings(size), 48000);
        analyzer.update_samples(&samples, size as u64);
        let common: Vec<_> = (0..=512)
            .map(|bin| analyzer.power()[bin * size / 1024])
            .collect();
        if reference.is_empty() {
            reference = common;
        } else {
            for (actual, expected) in common.iter().zip(&reference) {
                assert!(
                    (actual - expected).abs() < 1e-21 + expected * 3e-12,
                    "N={size}"
                );
            }
        }
        let time_energy = pulse.iter().map(|v| v * v).sum::<f64>() / 48000.0;
        assert!((analyzer.energy().unwrap() / time_energy - 1.0).abs() < 3e-12);
    }
}

#[test]
fn esd_parseval_matches_windowed_time_energy_without_window_gain_correction() {
    for size in [1024, 8192, 65536] {
        let samples: Vec<_> = (0..size)
            .map(|i| {
                let phase = TAU * i as f64 / size as f64;
                0.1 + 0.3 * (31.25 * phase).sin()
                    + if i % 2 == 0 { 0.07 } else { -0.07 }
                    + if i == 13 { 0.5 } else { 0.0 }
            })
            .collect();
        for rate in [8000, 48000, 192000] {
            for window in [Window::Rectangular, Window::Hann, Window::BlackmanHarris] {
                for remove_dc in [false, true] {
                    let mean = if remove_dc {
                        samples.iter().sum::<f64>() / size as f64
                    } else {
                        0.0
                    };
                    let expected = samples
                        .iter()
                        .enumerate()
                        .map(|(i, x)| ((x - mean) * window.weight(i, size)).powi(2))
                        .sum::<f64>()
                        / rate as f64;
                    for precision in [Precision::F64, Precision::F32] {
                        let settings = Settings {
                            window,
                            remove_dc,
                            precision,
                            ..transient_settings(size)
                        };
                        let mut analyzer = Analyzer::new(settings, rate);
                        analyzer.update_samples(&samples, size as u64);
                        let tolerance = if precision == Precision::F64 {
                            3e-12
                        } else {
                            3e-6
                        };
                        assert!(
                            (analyzer.energy().unwrap() / expected - 1.0).abs() < tolerance,
                            "N={size}, Fs={rate}, {window:?}, {precision:?}, remove_dc={remove_dc}"
                        );
                        let mut result = Result::empty(Settings::default(), 48000);
                        analyzer.copy_result(&mut result);
                        assert_eq!(result.energy(), analyzer.energy());
                    }
                }
            }
        }
    }
}

#[test]
fn esd_white_noise_grows_with_duration_while_psd_density_stays_constant() {
    let rate = 48000;
    let variance = 1.0 / 3.0;
    let expected_psd = 2.0 * variance / rate as f64;
    for size in [1024, 4096, 16384, 65536] {
        let settings = transient_settings(size);
        let mut esd = Analyzer::new(settings, rate);
        let mut psd = Analyzer::new(
            Settings {
                quantity: Quantity::Psd,
                ..settings
            },
            rate,
        );
        let mut state = 0x5a71_eb09_1254_8123_u64;
        let mut psd_density = 0.0;
        let mut esd_density = 0.0;
        let band = size / 8..size / 4;
        for frame in 1..=32 {
            let samples: Vec<_> = (0..size)
                .map(|_| {
                    state ^= state << 13;
                    state ^= state >> 7;
                    state ^= state << 17;
                    2.0 * (state >> 11) as f64 / (1_u64 << 53) as f64 - 1.0
                })
                .collect();
            esd.update_samples(&samples, frame * size as u64);
            psd.update_samples(&samples, frame * size as u64);
            psd_density += psd.power()[band.clone()].iter().sum::<f64>() / band.len() as f64;
            esd_density += esd.power()[band.clone()].iter().sum::<f64>() / band.len() as f64;
            for (&e, &p) in esd.power().iter().zip(psd.power()) {
                let expected = p * size as f64 / rate as f64;
                assert!((e - expected).abs() < 1e-20 + expected * 3e-12);
            }
        }
        let duration = size as f64 / rate as f64;
        assert!(
            (psd_density / 32.0 / expected_psd - 1.0).abs() < 0.08,
            "N={size}"
        );
        assert!(
            (esd_density / 32.0 / (expected_psd * duration) - 1.0).abs() < 0.08,
            "N={size}"
        );
    }
}
