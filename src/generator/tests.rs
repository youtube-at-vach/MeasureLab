use super::*;

fn tones(hz: f64) -> Settings {
    let mut settings = Settings::default();
    for s in &mut settings.signals {
        s.enabled = true;
        s.frequency_hz = hz;
    }
    settings
}

fn wave(rate: u32, hz: f64, n: u64, peak: f64, phase: f64) -> f64 {
    // Independent absolute-index reference used only within short test runs.
    peak * (TAU * hz * n as f64 / rate as f64 + phase.to_radians()).sin()
}

fn fade(elapsed: u64, length: u64) -> f64 {
    if elapsed >= length {
        1.0
    } else {
        (1.0 - (PI * elapsed as f64 / length as f64).cos()) / 2.0
    }
}

fn advance(engine: &mut Engine, count: usize) {
    for _ in 0..count {
        engine.next_frame().unwrap();
    }
}

#[test]
fn defaults_restore_silent_and_mono_has_no_second_route() {
    let settings = Settings::default();
    assert!(settings.signals.iter().all(|s| !s.enabled));
    assert_eq!(settings.signals[0].amplitude_peak(), 0.1);
    let bytes = serde_json::to_vec(&settings).unwrap();
    let restored: Settings = serde_json::from_slice(&bytes).unwrap();
    let mut engine = Engine::new(48000, 2, restored, 1234).unwrap();
    for n in 1234..1334 {
        assert_eq!(
            engine.next_frame().unwrap(),
            Frame {
                sequence: n,
                samples: [0.0; 16]
            }
        );
    }
    assert_eq!(engine.start(restored, 1), Err(Error::NoEnabledSignals));
    assert_eq!(engine.status().output_generation, 0);
    let mono = Settings::for_channels(1);
    assert_eq!(mono.signals[1].output_channel, None);
    mono.validate(48000, 1).unwrap();
    let mut unavailable = mono;
    unavailable.signals[1].enabled = true;
    assert_eq!(unavailable.validate(48000, 1), Err(Error::Routing(1)));
    let mut unknown = serde_json::to_value(settings).unwrap();
    unknown["running"] = true.into();
    assert!(serde_json::from_value::<Settings>(unknown).is_err());
}

#[test]
fn validation_rejects_nonfinite_ranges_and_routes_without_mutating_applied_state() {
    let settings = tones(997.1);
    let mut engine = Engine::new(48000, 2, settings, 0).unwrap();
    engine.start(settings, 1).unwrap();
    advance(&mut engine, 600);
    let before = engine.status();
    for i in 0..SIGNALS {
        for bad in [
            f64::NAN,
            f64::INFINITY,
            f64::NEG_INFINITY,
            -0.1,
            0.0,
            0.099,
            21600.0,
        ] {
            let mut candidate = settings;
            candidate.signals[i].frequency_hz = bad;
            assert_eq!(engine.configure(candidate, 2), Err(Error::Frequency(i)));
            assert_eq!(engine.status(), before);
        }
        for bad in [f64::NAN, f64::INFINITY, f64::NEG_INFINITY, -120.01, 0.01] {
            let mut candidate = settings;
            candidate.signals[i].amplitude_dbfs = bad;
            assert_eq!(engine.configure(candidate, 2), Err(Error::Amplitude(i)));
            assert_eq!(engine.status(), before);
        }
        for bad in [f64::NAN, f64::INFINITY, f64::NEG_INFINITY, -180.01, 180.01] {
            let mut candidate = settings;
            candidate.signals[i].phase_degrees = bad;
            assert_eq!(engine.configure(candidate, 2), Err(Error::Phase(i)));
            assert_eq!(engine.status(), before);
        }
        let mut candidate = settings;
        candidate.signals[i].output_channel = Some(16);
        assert_eq!(engine.configure(candidate, 2), Err(Error::Routing(i)));
        assert_eq!(engine.status(), before);
    }
    let mut duplicate = settings;
    duplicate.signals[1].output_channel = Some(0);
    assert_eq!(engine.configure(duplicate, 2), Err(Error::DuplicateRouting));
    assert_eq!(engine.configure(settings, 1), Err(Error::Revision));
    assert_eq!(engine.status(), before);
    let frame = engine.next_frame().unwrap();
    assert!((frame.samples[0] - wave(48000, 997.1, 600, 0.1, 0.0)).abs() < 1e-14);
    for rate in [0, MAX_SAMPLE_RATE + 1] {
        assert_eq!(settings.validate(rate, 2), Err(Error::SampleRate));
    }
    for channels in [0, 17] {
        assert_eq!(settings.validate(48000, channels), Err(Error::ChannelCount));
    }
}

#[test]
fn million_sample_sine_matrix_matches_independent_formula_including_start_fade() {
    let mut maximum = 0.0_f64;
    for rate in [44100, 48000, 96000, 192000] {
        for tenths_hz in [1, 7500, 9971, rate as u64 * 9 / 2 - 1] {
            let hz = tenths_hz as f64 / 10.0;
            for dbfs in [0.0, -20.0, -120.0] {
                for phase in [0.0, -90.0, 90.0, 180.0] {
                    let mut settings = tones(hz);
                    settings.signals[0].amplitude_dbfs = dbfs;
                    settings.signals[0].phase_degrees = phase;
                    let mut engine = Engine::new(rate, 2, settings, 0).unwrap();
                    engine.start(settings, 1).unwrap();
                    let length = (rate as f64 * 0.01).ceil() as u64;
                    let peak = 10.0_f64.powf(dbfs / 20.0);
                    for n in 0..1_000_000 {
                        let frame = engine.next_frame().unwrap();
                        assert_eq!(frame.sequence, n);
                        // All matrix frequencies are exact decimal tenths. An
                        // integer rational remainder gives an independent
                        // reference without either a phase recurrence or an
                        // ill-conditioned million-cycle trigonometric argument.
                        let denominator = rate as u128 * 10;
                        let numerator = n as u128 * tenths_hz as u128;
                        let cycle = (numerator % denominator) as f64 / denominator as f64;
                        let expected = peak
                            * (TAU * (cycle + phase / 360.0).rem_euclid(1.0)).sin()
                            * fade(n, length);
                        maximum = maximum.max((frame.samples[0] - expected).abs());
                        assert!(
                            (frame.samples[0] - expected).abs() < 1e-9,
                            "rate={rate} hz={hz} dbfs={dbfs} phase={phase} n={n}"
                        );
                        assert!(frame.samples.iter().all(|x| x.abs() <= 1.0));
                    }
                    assert_eq!(engine.status().state, State::Running);
                    assert_eq!(engine.status().next_sample, 1_000_000);
                }
            }
        }
    }
    eprintln!(
        "Generator f64 matrix: 192 conditions × 1,000,000 samples; maximum absolute error {maximum:e} FS"
    );
}

#[test]
fn frequency_edit_preserves_accumulated_phase_and_other_signal() {
    let mut settings = tones(997.1);
    settings.signals[0].phase_degrees = 90.0;
    let mut engine = Engine::new(48000, 2, settings, 0).unwrap();
    engine.start(settings, 1).unwrap();
    advance(&mut engine, 601);
    settings.signals[0].frequency_hz = 2041.3;
    engine.configure(settings, 2).unwrap();
    assert_eq!(engine.status().applied_sample, 601);
    assert!(!engine.status().transitioning());
    for n in 601..5000 {
        let frame = engine.next_frame().unwrap();
        let phase = TAU * (997.1 * 601.0 + 2041.3 * (n - 601) as f64) / 48000.0 + PI / 2.0;
        assert!((frame.samples[0] - 0.1 * phase.sin()).abs() < 1e-12);
        assert!((frame.samples[1] - wave(48000, 997.1, n, 0.1, 0.0)).abs() < 1e-12);
    }
}

#[test]
fn amplitude_and_shortest_phase_ramps_match_independent_formula_across_retargeting() {
    let mut settings = tones(750.0);
    settings.signals[0].phase_degrees = 170.0;
    let mut engine = Engine::new(48000, 2, settings, 0).unwrap();
    engine.start(settings, 1).unwrap();
    advance(&mut engine, 601);
    settings.signals[0].amplitude_dbfs = -40.0;
    settings.signals[0].phase_degrees = -170.0;
    engine.configure(settings, 2).unwrap();
    assert_eq!(engine.status().transition_end[0], 1081);
    for n in 601..731 {
        let weight = fade(n - 601, 480);
        let expected = wave(
            48000,
            750.0,
            n,
            0.1 + (0.01 - 0.1) * weight,
            170.0 + 20.0 * weight,
        );
        assert!((engine.next_frame().unwrap().samples[0] - expected).abs() < 1e-13);
    }
    let current_amp = 0.1 + (0.01 - 0.1) * fade(130, 480);
    let current_phase = 170.0 + 20.0 * fade(130, 480);
    settings.signals[0].amplitude_dbfs = 0.0;
    settings.signals[0].phase_degrees = 90.0;
    engine.configure(settings, 3).unwrap();
    for n in 731..1500 {
        let weight = fade(n - 731, 480);
        let expected = wave(
            48000,
            750.0,
            n,
            current_amp + (1.0 - current_amp) * weight,
            current_phase + (90.0 - current_phase) * weight,
        );
        assert!((engine.next_frame().unwrap().samples[0] - expected).abs() < 1e-12);
    }
}

#[test]
fn phase_half_turn_uses_positive_direction_and_extends_to_respect_nyquist() {
    let mut settings = tones(44.9);
    let mut engine = Engine::new(100, 2, settings, 0).unwrap();
    engine.start(settings, 1).unwrap();
    advance(&mut engine, 10);
    settings.signals[0].phase_degrees = -180.0;
    engine.configure(settings, 2).unwrap();
    let end = engine.status().transition_end[0];
    assert!(
        end > 11,
        "a one-sample half-turn needs a longer phase transition"
    );
    let length = end - 10;
    for n in 10..end + 1 {
        let offset = 180.0 * fade(n - 10, length);
        let actual = engine.next_frame().unwrap().samples[0];
        assert!((actual - wave(100, 44.9, n, 0.1, offset)).abs() < 1e-13);
        let delta = 0.449 + 0.5 * (fade(n + 1 - 10, length) - fade(n - 10, length));
        assert!(delta < 0.5);
    }
}

#[test]
fn frequency_edit_during_phase_transition_retimes_it_without_a_phase_jump() {
    let mut settings = tones(20.0);
    let mut engine = Engine::new(100, 2, settings, 0).unwrap();
    engine.start(settings, 1).unwrap();
    advance(&mut engine, 10);
    settings.signals[0].phase_degrees = 180.0;
    engine.configure(settings, 2).unwrap();
    advance(&mut engine, 2);
    let carrier = engine.oscillators[0].carrier;
    let phase = engine.oscillators[0].phase.at(12);
    let previous_end = engine.status().transition_end[0];
    settings.signals[0].frequency_hz = 44.9;
    engine.configure(settings, 3).unwrap();
    let end = engine.status().transition_end[0];
    assert!(end > previous_end);
    assert_eq!(engine.status().applied_sample, 12);
    for n in 12..end + 1 {
        let elapsed = n - 12;
        let offset = phase + (0.5 - phase) * fade(elapsed, end - 12);
        let expected = 0.1 * (TAU * (carrier + 0.449 * elapsed as f64 + offset)).sin();
        assert!((engine.next_frame().unwrap().samples[0] - expected).abs() < 1e-13);
        let slope = (0.5 - phase) * (fade(elapsed + 1, end - 12) - fade(elapsed, end - 12));
        assert!(0.449 + slope < 0.5);
    }
}

#[test]
fn stream_recreation_preserves_clock_and_generation_and_exhaustion_is_rejected() {
    let settings = tones(750.0);
    let mut engine = Engine::with_clock(96000, 2, settings, 48000, 7).unwrap();
    engine.configure(settings, 4).unwrap();
    let (mut controller, mut execution) = control::from_engine(engine);
    let revision = controller.start(settings).unwrap();
    assert_eq!(revision, 5);
    execution.begin_block();
    assert_eq!(execution.status().output_generation, 8);
    assert_eq!(execution.status().applied_sample, 48000);
    assert_eq!(execution.next_frame().unwrap().sequence, 48000);
    let mut exhausted = Engine::with_clock(48000, 2, settings, 0, u64::MAX).unwrap();
    let before = exhausted.status();
    assert_eq!(exhausted.start(settings, 1), Err(Error::CounterExhausted));
    assert_eq!(exhausted.status(), before);
    assert_eq!(exhausted.next_frame().unwrap().samples, [0.0; 16]);
}

#[test]
fn off_keeps_phase_running_and_align_smoothly_restores_relative_phase() {
    let mut settings = tones(750.0);
    settings.signals[1].phase_degrees = 30.0;
    let mut engine = Engine::new(48000, 2, settings, 0).unwrap();
    engine.start(settings, 1).unwrap();
    advance(&mut engine, 601);
    settings.signals[0].enabled = false;
    engine.configure(settings, 2).unwrap();
    for n in 601..1301 {
        let frame = engine.next_frame().unwrap();
        let expected = wave(48000, 750.0, n, 0.1, 0.0) * (1.0 - fade(n - 601, 480));
        assert!((frame.samples[0] - expected).abs() < 1e-13);
        assert!((frame.samples[1] - wave(48000, 750.0, n, 0.1, 30.0)).abs() < 1e-13);
    }
    settings.signals[0].enabled = true;
    settings.signals[0].frequency_hz = 997.1;
    engine.configure(settings, 3).unwrap();
    for n in 1301..2001 {
        let phase = TAU * (750.0 * 1301.0 + 997.1 * (n - 1301) as f64) / 48000.0;
        let expected = 0.1 * phase.sin() * fade(n - 1301, 480);
        assert!((engine.next_frame().unwrap().samples[0] - expected).abs() < 1e-13);
    }
    settings.signals[0].frequency_hz = 750.0;
    engine.configure(settings, 4).unwrap();
    let old_carrier = engine.oscillators[0].carrier;
    engine.align_phases(5).unwrap();
    // First aligned frame retains the pre-edit phase; only the ramp moves it.
    let first = engine.next_frame().unwrap();
    assert!((first.samples[0] - 0.1 * (TAU * old_carrier).sin()).abs() < 1e-14);
    for n in 2002..3500 {
        let frame = engine.next_frame().unwrap();
        if n >= 2481 {
            for (ch, phase) in [(0, 0.0), (1, 30.0)] {
                assert!(
                    (frame.samples[ch] - wave(48000, 750.0, n - 2001, 0.1, phase)).abs() < 1e-13
                );
            }
        }
    }
}

#[test]
fn finite_stop_is_idempotent_silent_and_restart_has_new_generation_without_clock_rewind() {
    let settings = tones(997.1);
    let mut engine = Engine::new(48000, 2, settings, 0).unwrap();
    engine.start(settings, 1).unwrap();
    advance(&mut engine, 601);
    engine.stop().unwrap();
    let stopping = engine.status();
    assert_eq!(stopping.stop_sample, Some(601));
    assert_eq!(stopping.state, State::Stopping);
    assert_eq!(engine.start(settings, 2), Err(Error::Stopping));
    assert_eq!(engine.configure(settings, 2), Err(Error::Stopping));
    for n in 601..1200 {
        engine.stop().unwrap();
        let frame = engine.next_frame().unwrap();
        assert!(
            (frame.samples[0] - wave(48000, 997.1, n, 0.1, 0.0) * (1.0 - fade(n - 601, 480))).abs()
                < 1e-13
        );
        assert_eq!(engine.status().stop_sample, stopping.stop_sample);
        if n < 1081 {
            assert_eq!(engine.status().state, State::Stopping);
        } else {
            assert_eq!(frame.samples, [0.0; 16]);
        }
    }
    assert_eq!(engine.status().stopped_at, Some(1082));
    assert_eq!(engine.status().settings, settings);
    engine.start(settings, 2).unwrap();
    assert_eq!(engine.status().output_generation, 2);
    assert_eq!(engine.status().applied_sample, 1200);
    for n in 1200..1800 {
        let frame = engine.next_frame().unwrap();
        assert!(
            (frame.samples[0] - wave(48000, 997.1, n - 1200, 0.1, 0.0) * fade(n - 1200, 480)).abs()
                < 1e-13
        );
    }
}

#[test]
fn stop_during_start_or_live_ramp_uses_current_amplitude() {
    for boundary in [123, 601] {
        let mut settings = tones(750.0);
        let mut engine = Engine::new(48000, 2, settings, 0).unwrap();
        engine.start(settings, 1).unwrap();
        advance(&mut engine, boundary);
        if boundary == 601 {
            settings.signals[0].amplitude_dbfs = 0.0;
            settings.signals[0].phase_degrees = 90.0;
            engine.configure(settings, 2).unwrap();
            advance(&mut engine, 123);
        }
        let n = engine.status().next_sample;
        let current = engine.oscillators[0].amplitude.at(n);
        let phase = engine.oscillators[0].phase.at(n) * 360.0;
        engine.stop().unwrap();
        for elapsed in 0..=480 {
            let expected =
                wave(48000, 750.0, n + elapsed, current, phase) * (1.0 - fade(elapsed, 480));
            assert!((engine.next_frame().unwrap().samples[0] - expected).abs() < 1e-13);
        }
        assert_eq!(engine.status().state, State::Stopped);
    }
}

#[test]
fn routing_is_exclusive_changes_only_while_stopped_and_unused_channels_are_zero() {
    for channels in 1..=16 {
        let mut settings = Settings::for_channels(channels);
        settings.signals[0].enabled = true;
        settings.signals[0].output_channel = Some(channels - 1);
        settings.signals[1].output_channel = (channels > 1).then_some(0);
        settings.signals[1].enabled = channels > 1;
        let mut engine = Engine::new(48000, channels, settings, 0).unwrap();
        engine.start(settings, 1).unwrap();
        for _ in 0..600 {
            let frame = engine.next_frame().unwrap();
            for ch in 0..16 {
                if ch != channels - 1 && !(channels > 1 && ch == 0) {
                    assert_eq!(frame.samples[ch], 0.0);
                }
            }
        }
        if channels > 1 {
            let mut rerouted = settings;
            rerouted.signals[0].output_channel = Some(0);
            rerouted.signals[1].output_channel = Some(channels - 1);
            let before = engine.status();
            assert_eq!(
                engine.configure(rerouted, 2),
                Err(Error::RoutingWhileActive)
            );
            assert_eq!(engine.status(), before);
            engine.stop().unwrap();
            advance(&mut engine, 481);
            engine.configure(rerouted, 2).unwrap();
            assert_eq!(engine.next_frame().unwrap().samples, [0.0; 16]);
        }
    }
}

#[test]
fn huge_integer_sequences_do_not_change_waveform_or_edit_boundaries_and_never_wrap() {
    let first = (1u64 << 53) + 17;
    let mut settings = tones(997.1);
    let mut a = Engine::new(48000, 2, settings, 0).unwrap();
    let mut b = Engine::new(48000, 2, settings, first).unwrap();
    a.start(settings, 1).unwrap();
    b.start(settings, 1).unwrap();
    for local in 0..12000 {
        if local == 700 {
            settings.signals[1].phase_degrees = 90.0;
            a.configure(settings, 2).unwrap();
            b.configure(settings, 2).unwrap();
            assert_eq!(b.status().applied_sample, first + 700);
            assert_eq!(b.status().transition_end[1], first + 1180);
        }
        let x = a.next_frame().unwrap();
        let y = b.next_frame().unwrap();
        assert_eq!(y.sequence, first + x.sequence);
        assert_eq!(x.samples, y.samples);
    }
    let mut terminal = Engine::new(48000, 2, settings, u64::MAX - 2).unwrap();
    let before = terminal.status();
    assert_eq!(terminal.start(settings, 1), Err(Error::CounterExhausted));
    assert_eq!(terminal.status(), before);
    assert_eq!(terminal.next_frame().unwrap().sequence, u64::MAX - 2);
    assert_eq!(terminal.next_frame().unwrap().sequence, u64::MAX - 1);
    assert_eq!(terminal.next_frame(), Err(Error::CounterExhausted));
    assert_eq!(
        terminal.status().state,
        State::Error(Error::CounterExhausted)
    );
    assert_eq!(terminal.start(settings, 1), Err(Error::CounterExhausted));
}

#[test]
fn output_faults_latch_without_automatic_restart_or_clipping() {
    for (value, expected) in [
        (f64::NAN, Error::NonFiniteOutput),
        (2.0, Error::OutputRange),
    ] {
        let mut settings = tones(750.0);
        settings.signals[0].phase_degrees = 90.0;
        let mut engine = Engine::new(48000, 2, settings, 0).unwrap();
        engine.start(settings, 1).unwrap();
        // Simulate an internal invariant failure at an output extremum.
        engine.oscillators[0].amplitude = Ramp::constant(value, 0);
        assert_eq!(engine.next_frame(), Err(expected));
        assert_eq!(engine.status().state, State::Error(expected));
        assert!(!engine.status().transitioning());
        assert_eq!(engine.configure(settings, 2), Err(expected));
        assert_eq!(engine.start(settings, 2), Err(expected));
        assert_eq!(engine.next_frame(), Err(expected));
    }
}

#[test]
fn generated_samples_match_existing_scope_spectrum_and_lockin_numerics() {
    use crate::{
        channel::Pair,
        lockin,
        signal::{History, measure},
        spectrum,
    };
    let mut settings = tones(750.0);
    settings.signals[0].amplitude_dbfs = 20.0 * 0.125_f64.log10();
    settings.signals[1].amplitude_dbfs = 20.0 * 0.0625_f64.log10();
    settings.signals[1].phase_degrees = 30.0;
    let mut engine = Engine::new(48000, 2, settings, 0).unwrap();
    engine.start(settings, 1).unwrap();
    let mut history = History::new(8192);
    let mut lockin = lockin::Analyzer::new(
        lockin::Settings {
            enabled: true,
            frequency_hz: 750.0,
            time_constant_seconds: 0.001,
            ..Default::default()
        },
        48000,
    );
    // This is a numeric integration test, not a common-worker or CPAL test.
    for n in 0..48000 {
        let frame = engine.next_frame().unwrap();
        history.push_at(frame.sequence, &frame.samples[..2]);
        if n >= 1024 {
            lockin.push_pair(frame.sequence, [frame.samples[0], frame.samples[1]]);
        }
    }
    let measured = measure(&history, history.range(), Pair::<2>::default());
    for (ch, peak) in [(0, 0.125), (1, 0.0625)] {
        assert!((measured[ch].rms - peak / 2.0_f64.sqrt()).abs() < 1e-8);
        let mut fft = spectrum::Analyzer::new(
            spectrum::Settings {
                averages: 1,
                ..Default::default()
            },
            48000,
        );
        assert!(fft.update(&history, ch));
        assert!((fft.power()[128].sqrt() - peak).abs() < 1e-8);
        let window = fft.window().unwrap();
        assert_eq!(window.end, 48000);
        assert_eq!(window.start, 39808);
        assert_eq!(window.channel, ch);
    }
    let result = lockin.result();
    assert_eq!(result.state, lockin::State::Valid);
    assert!((result.amplitude_peak.unwrap() - 0.0625).abs() < 1e-8);
    assert!((result.phase_degrees.unwrap() - 30.0).abs() < 1e-6);
    assert!((result.reference_frequency_hz.unwrap() - 750.0).abs() < 1e-7);
}

#[test]
fn bounded_controls_keep_latest_snapshot_ack_at_execution_and_stop_fences_queued_starts() {
    let mut settings = tones(997.1);
    let (mut controller, mut execution) = control::new(48000, 2, settings, 100).unwrap();
    let revision = controller.start(settings).unwrap();
    assert_eq!(revision, 1);
    assert!(controller.poll().is_none());
    assert_eq!(execution.status().state, State::Stopped);
    execution.begin_block();
    execution.next_frame().unwrap();
    execution.end_block();
    let report = controller.poll().unwrap();
    assert_eq!(report.status.state, State::Starting);
    assert_eq!(report.status.applied_sample, 100);
    assert_eq!(report.status.revision, 1);
    for i in 0..100 {
        settings.signals[0].frequency_hz = 1000.0 + i as f64;
        controller.configure(settings).unwrap();
    }
    assert!(!controller.flush());
    assert!(controller.coalesced_requests() > 0);
    execution.begin_block();
    assert!(controller.flush());
    execution.begin_block();
    execution.end_block();
    let report = controller.poll().unwrap();
    assert_eq!(report.status.settings, settings);
    assert_eq!(report.status.revision, 101);
    assert_eq!(report.status.applied_sample, 101);
    assert!(report.rejected.is_none());
    // An already queued Start cannot undo the independently delivered Stop.
    for _ in 0..control::CAPACITY {
        controller.start(settings).unwrap();
    }
    let stop = controller.stop().unwrap();
    execution.begin_block();
    assert_eq!(execution.status().state, State::Stopping);
    for _ in 0..481 {
        execution.next_frame().unwrap();
    }
    execution.end_block();
    let report = controller.poll().unwrap();
    assert_eq!(report.stop_epoch, stop);
    assert_eq!(report.superseded_requests, control::CAPACITY as u64);
    assert_eq!(report.status.state, State::Stopped);
    execution.begin_block();
    assert_eq!(execution.next_frame().unwrap().samples, [0.0; 16]);
    controller.start(settings).unwrap();
    execution.begin_block();
    assert_eq!(execution.status().output_generation, 2);
}

#[test]
fn unsent_start_and_align_survive_coalescing_but_stop_cancels_them() {
    let mut settings = tones(750.0);
    let (mut controller, mut execution) = control::new(48000, 2, settings, 0).unwrap();
    for _ in 0..control::CAPACITY {
        controller.configure(settings).unwrap();
    }
    controller.start(settings).unwrap();
    settings.signals[1].phase_degrees = 90.0;
    controller.configure(settings).unwrap();
    controller.align_phases().unwrap();
    execution.begin_block();
    assert_eq!(execution.status().state, State::Stopped);
    controller.flush();
    execution.begin_block();
    assert_eq!(execution.status().state, State::Starting);
    assert_eq!(execution.status().settings, settings);
    assert_eq!(execution.status().revision, 7);
    for _ in 0..control::CAPACITY {
        controller.configure(settings).unwrap();
    }
    controller.start(settings).unwrap();
    controller.stop().unwrap();
    execution.begin_block();
    assert!(controller.flush());
    for _ in 0..481 {
        execution.next_frame().unwrap();
    }
    execution.begin_block();
    assert_eq!(execution.status().state, State::Stopped);
    assert_eq!(execution.status().output_generation, 1);
}

#[test]
fn stopped_controls_report_rejections_and_feedback_overflow_does_not_stall_generation() {
    let settings = tones(750.0);
    let (mut controller, mut execution) = control::new(48000, 2, settings, 0).unwrap();
    controller.start(settings).unwrap();
    execution.begin_block();
    for _ in 0..100 {
        execution.next_frame().unwrap();
        execution.end_block();
    }
    assert_eq!(execution.status().next_sample, 100);
    controller.poll();
    execution.end_block();
    let report = controller.poll().unwrap();
    assert_eq!(report.lost_reports, 100 - control::CAPACITY as u64);
    let mut rerouted = settings;
    rerouted.signals.swap(0, 1);
    let revision = controller.configure(rerouted).unwrap();
    execution.begin_block();
    execution.end_block();
    let report = controller.poll().unwrap();
    assert_eq!(
        report.rejected,
        Some(control::Rejection {
            revision,
            error: Error::RoutingWhileActive
        })
    );
    assert_eq!(report.status.revision, 1);
    assert_eq!(report.status.settings, settings);
    controller.stop().unwrap();
    controller.start(settings).unwrap();
    execution.begin_block();
    execution.end_block();
    assert_eq!(
        controller.poll().unwrap().rejected.unwrap().error,
        Error::Stopping
    );
    for _ in 0..481 {
        execution.next_frame().unwrap();
    }
    assert_eq!(execution.status().state, State::Stopped);
    execution.fail(Error::NonFiniteOutput);
    controller.start(settings).unwrap();
    execution.begin_block();
    assert_eq!(
        execution.status().state,
        State::Error(Error::NonFiniteOutput)
    );
}

#[test]
fn block_partition_does_not_change_samples_for_identical_application_boundaries() {
    fn render(lengths: &[usize]) -> Vec<Frame> {
        let mut settings = tones(997.1);
        let (mut controller, mut execution) = control::new(48000, 2, settings, 0).unwrap();
        controller.start(settings).unwrap();
        let mut frames = Vec::new();
        let mut block = 0;
        for boundary in [701, 1151, 1801, 2501] {
            while frames.len() < boundary {
                let count = lengths[block % lengths.len()].min(boundary - frames.len());
                execution.begin_block();
                frames.extend((0..count).map(|_| execution.next_frame().unwrap()));
                execution.end_block();
                controller.poll();
                block += 1;
            }
            match boundary {
                701 => {
                    settings.signals[0].frequency_hz = 1501.3;
                    settings.signals[1].phase_degrees = 180.0;
                    controller.configure(settings).unwrap();
                }
                1151 => {
                    controller.align_phases().unwrap();
                }
                1801 => {
                    controller.stop().unwrap();
                }
                _ => {}
            }
        }
        frames
    }
    let single = render(&[1]);
    assert_eq!(single, render(&[127]));
    assert_eq!(single, render(&[7, 513, 1, 256, 3, 1024]));
}
