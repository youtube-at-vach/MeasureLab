//! I6d Signal instruments: internal generation, finite input/output Stop,
//! explicit invalid display fixtures, actual popup and tooltip events.
use super::*;

pub(super) struct Retained {
    lockin: lockin::Result,
    comparison: Arc<comparison::Result>,
    input: Option<export::Input>,
    dropped: u64,
    rate: u32,
    running: bool,
    output: bool,
}
impl Retained {
    pub(super) fn new(app: &ScopeApp) -> Self {
        Self {
            lockin: app.lockin_result.clone(),
            comparison: Arc::clone(&app.comparison_result),
            input: app.held_input.clone(),
            dropped: app.dropped,
            rate: app.sample_rate,
            running: app.running(),
            output: !app.generator.stopped(),
        }
    }
}

fn prepare(app: &mut ScopeApp, instrument: &str, target: &str) -> Result<(), String> {
    assert!(app.core.is_none() && !app.running() && app.generator.stopped());
    app.presentation = Presentation::default();
    app.presentation.apply(Action::OpenSingle(match instrument {
        "generator" => Instrument::Generator,
        "lockin" => Instrument::Lockin,
        "comparison" => Instrument::Comparison,
        _ => return Err(format!("Unknown Signal review instrument: {instrument}")),
    }));
    app.shell = shell::Shell::default();
    app.source = Source::Generator;
    app.demo_enabled = false;
    app.core = Some(measurement::Worker::new(app.stft.take_feeder()));
    app.acquisition_mode = acquisition::Mode::Auto;
    app.spectrum_mode = SpectrumMode::Continuous;
    app.lockin_settings = lockin::Settings {
        enabled: true,
        frequency_hz: 750.0,
        time_constant_seconds: 0.005,
        ..Default::default()
    };
    app.comparison_settings = comparison::Settings {
        enabled: true,
        averages: 4,
        ..Default::default()
    };
    app.comparison_frequency_hz = 750.0;
    let mut settings = generator::Settings::default();
    for (i, s) in settings.signals.iter_mut().enumerate() {
        s.enabled = true;
        s.frequency_hz = 750.0;
        s.amplitude_dbfs = 20.0 * (0.125 / (i + 1) as f64).log10();
        s.phase_degrees = i as f64 * 30.0;
    }
    app.generator.configure(settings);
    scope::wait(app, |a| !a.generator.pending)?;
    app.generator.start();
    scope::wait(app, |a| {
        a.generator.status.state == generator::State::Running && !a.generator.starting
    })?;
    let mut driver = Driver::new();
    let locale = i18n::locale();
    i18n::initialize(&driver.ctx, None);
    i18n::set_locale(&driver.ctx, locale.id());
    driver.frame(app, vec![]);
    driver.frame(app, vec![]);
    if !matches!(target, "empty" | "error-empty") {
        driver.click(app, i18n::text("io.start_input"))?;
        scope::wait(app, |a| {
            a.lockin_result.state == lockin::State::Valid
                && a.comparison_result.state == comparison::State::Valid
                && a.analyzer.is_ready()
        })?;
        assert!((app.lockin_result.amplitude_peak.unwrap() - 0.0625).abs() < 1e-8);
        assert!((app.lockin_result.phase_degrees.unwrap() - 30.0).abs() < 1e-6);
        let b = &app.comparison_result.bins[64];
        assert!((b.gain.unwrap() - 0.5).abs() < 1e-9);
        assert!((b.phase_lead_degrees.unwrap() - 30.0).abs() < 1e-7);
        if target == "error" {
            app.fail_input("I6d simulated Signal input error (internal Generator)".into());
            scope::wait(app, |a| a.pending_stop.is_none())?;
        } else if target != "live" {
            driver.frame(app, vec![]);
            driver.click(app, i18n::text("io.stop_input"))?;
            scope::wait(app, |a| a.pending_stop.is_none())?;
        }
    } else if target == "error-empty" {
        app.fail_input("I6d simulated Signal input error (internal Generator)".into());
        scope::wait(app, |a| a.pending_stop.is_none())?;
    }
    if !matches!(
        target,
        "live" | "held" | "error" | "error-empty" | "tooltip-stop" | "tooltip-output"
    ) {
        driver.frame(app, vec![]);
        driver.click(app, i18n::text("generator.stop_output_2"))?;
        scope::wait(app, |a| a.generator.stopped())?;
    }
    if instrument == "generator" {
        let mut settings = app.generator.settings;
        match target {
            "empty" => settings.signals = generator::Signals::empty(),
            "square" | "triangle" | "noise" | "details-noise" => {
                settings.signals[0].waveform = match target {
                    "square" => generator::Waveform::Square,
                    "triangle" => generator::Waveform::Triangle,
                    _ => generator::Waveform::Noise,
                };
            }
            "unassigned" => {
                settings.signals[0].enabled = false;
                settings.signals[0].output_channel = None;
            }
            "collapsed" => app.generator.controls_expanded = false,
            "output-error" => {
                app.generator.select(
                    output::Target::Audio {
                        device_id: "measurelab:test:nonexistent-i6-output".into(),
                        device_name: "I6 nonexistent output (fixture)".into(),
                        channels: 2,
                        pcm: output::device::Pcm::F32,
                        dither: output::dither::Dither::default(),
                    },
                    48000,
                    settings,
                )?;
                scope::wait(app, |a| !a.generator.pending)?;
                app.generator.start();
                scope::wait(app, |a| {
                    matches!(a.generator.status.state, generator::State::Error(_))
                })?;
                println!(
                    "Signal review nonexistent output ID: real manager failure, no physical stream"
                );
            }
            _ => {}
        }
        if settings != app.generator.settings {
            app.generator.configure(settings);
            scope::wait(app, |a| !a.generator.pending)?;
        }
    }
    // Display-only fixtures. Core numerical state transitions have their own tests.
    // Do not let asynchronous replies replace the explicitly labelled fixture.
    if matches!(
        target,
        "disabled"
            | "unavailable"
            | "settling"
            | "ref-loss"
            | "ref-unstable"
            | "missing"
            | "invalid"
            | "filling"
            | "averaging"
            | "incoherent"
            | "response-loss"
            | "pending"
    ) {
        app.core = None;
        app.pending_scope = None;
        if instrument == "lockin" {
            let state = match target {
                "disabled" => lockin::State::Disabled,
                "unavailable" => lockin::State::Unavailable,
                "settling" => lockin::State::Settling,
                "ref-loss" => lockin::State::ReferenceLost,
                "ref-unstable" => lockin::State::ReferenceUnstable,
                "missing" => lockin::State::Missing,
                "invalid" => lockin::State::NonFinite,
                _ => lockin::State::Valid,
            };
            if target == "pending" {
                app.lockin_settings.frequency_hz = 1000.0;
            } else {
                let mut result = lockin::Analyzer::new(app.lockin_settings, app.sample_rate)
                    .result()
                    .clone();
                result.state = state;
                if target == "missing" {
                    result.missing_samples = 64;
                }
                if target == "disabled" {
                    app.lockin_settings.enabled = false;
                    result.settings.enabled = false;
                }
                app.lockin_result = result;
            }
        } else if instrument == "comparison" {
            if target == "pending" {
                app.comparison_settings.averages = 8;
            } else if matches!(target, "ref-loss" | "response-loss" | "incoherent") {
                let r = Arc::make_mut(&mut app.comparison_result);
                let b = &mut r.bins[64];
                b.state = match target {
                    "ref-loss" => comparison::BinState::ReferenceLost,
                    "response-loss" => comparison::BinState::ResponseLost,
                    _ => comparison::BinState::Incoherent,
                };
                b.coherence = (target == "incoherent").then_some(0.1);
                if target == "ref-loss" {
                    b.reference_psd = 0.0;
                }
                if target == "response-loss" {
                    b.response_psd = 0.0;
                }
                b.transfer_re = None;
                b.transfer_im = None;
                b.gain = None;
                b.phase_lead_degrees = None;
                b.phase_delay_seconds = None;
            } else {
                let mut result = comparison::Result::empty(
                    app.comparison_settings,
                    app.sample_rate,
                    app.input_generation,
                    1,
                    2,
                );
                result.state = match target {
                    "disabled" => comparison::State::Disabled,
                    "unavailable" => comparison::State::Unavailable,
                    "averaging" => comparison::State::Averaging,
                    "missing" => comparison::State::Missing,
                    "invalid" => comparison::State::NonFinite,
                    _ => comparison::State::Filling,
                };
                if target == "disabled" {
                    app.comparison_settings.enabled = false;
                    result.settings.enabled = false;
                }
                app.comparison_result = Arc::new(result);
            }
        }
        println!(
            "Signal review synthetic display fixture: {instrument}/{target}; no physical stream"
        );
    }
    if instrument == "lockin" {
        app.lockin_display = match target {
            "cartesian" => settings::LockinDisplay::Cartesian,
            "all" => settings::LockinDisplay::All,
            _ => settings::LockinDisplay::Polar,
        };
    }
    if target == "dithering" {
        let config = output::device::Config {
            rate: 48000,
            channels: 2,
            pcm: output::device::Pcm::F32,
        };
        let id = "measurelab:test:nonexistent-i6-output";
        app.generator.devices = vec![output::device::DeviceInfo {
            id: id.into(),
            name: "I6 output (display fixture)".into(),
            configs: vec![config],
            preferred: config,
        }];
        app.generator.select(
            output::Target::Audio {
                device_id: id.into(),
                device_name: "I6 output (display fixture)".into(),
                channels: 2,
                pcm: config.pcm,
                dither: output::dither::Dither {
                    enabled: true,
                    ..Default::default()
                },
            },
            config.rate,
            app.generator.settings,
        )?;
        scope::wait(app, |a| !a.generator.pending)?;
        app.shell.io = Some(shell::IoTab::Connections);
        println!("Signal review synthetic output selection only; no physical stream opened");
    }
    if target == "preferences-error" {
        app.preferences = preferences::State::visual_review_error();
        app.shell.file_paths = true;
    }
    if instrument == "comparison" && target == "captured" {
        app.presentation.details_visible = false;
    }
    app.created = Instant::now();
    Ok(())
}

pub(super) fn case(app: &mut ScopeApp, name: &str) -> Result<Case, String> {
    let (instrument, target) = name
        .split_once(':')
        .ok_or("Signal review needs instrument:target")?;
    prepare(app, instrument, target)?;
    let mut c = Case {
        steps: vec![],
        labels: vec![],
        popup: false,
        navigation: false,
        search: None,
    };
    let details = target.starts_with("details")
        || matches!(
            target,
            "menu-step"
                | "menu-tau"
                | "menu-integration"
                | "menu-size"
                | "menu-window"
                | "tooltip-applied-values"
        );
    if details {
        app.presentation.details_visible = true;
        app.shell.narrow_details = true;
    }
    match (instrument, target) {
        ("generator", "menu-waveform") => {
            c.steps.push(Step::Click(
                i18n::text("generator.waveform_names.sine").into(),
            ));
            c.labels = generator::Waveform::ALL
                .iter()
                .map(|w| w.display_name().into())
                .collect();
            c.popup = true;
        }
        ("generator", "menu-routing") => {
            c.steps.push(Step::Click(
                i18n::format("generator.out_2", &[("c", "1")]).to_string(),
            ));
            c.labels = vec![
                i18n::text("generator.unassigned").into(),
                i18n::format(
                    "generator.out",
                    &[("ch", "2"), ("else", i18n::text("generator.in_use"))],
                )
                .to_string(),
            ];
            c.popup = true;
        }
        ("generator", "menu-step") => {
            c.steps.push(Step::Click("1".into()));
            c.labels = ["0.01", "0.1", "1", "10", "100"].map(str::to_owned).into();
            c.popup = true;
        }
        ("generator", "tooltip-edit") => {
            c.steps.push(Step::HoverText("750.000".into()));
            c.labels
                .push(i18n::text("generator.enter_focus_to_apply_esc_to_cancel_up_down").into());
        }
        ("generator", "tooltip-applied") => {
            c.steps
                .push(Step::HoverText(i18n::text("generator.applied").into()));
            c.labels.push(
                i18n::format(
                    "generator.applied_fs_hz_nominal_settings_preview_uses_fs_peak",
                    &[("nominal_sample_rate", "48000")],
                )
                .to_string(),
            );
        }
        (_, "tooltip-stop") => {
            c.steps.push(Step::HoverText(
                i18n::text("generator.stop_output_2").into(),
            ));
            c.labels.push(
                i18n::text("generator.stop_generator_output_independently_of_input_and_analysis")
                    .into(),
            );
        }
        (_, "tooltip-output") => {
            // Both header layouts include the actual output state text.
            c.steps
                .push(Step::HoverControl(egui::Id::unique("qa_output_status")));
            c.labels.push(
                i18n::format(
                    "generator.hz_ch_input_stop_holds_the_measurement_output_continues",
                    &[
                        ("label", text::output_target(&app.generator.target)),
                        ("rate", "48000"),
                        ("channels", "2"),
                    ],
                )
                .to_string(),
            );
        }
        ("generator", "tooltip-applied-values") => {
            let s = app.generator.status.settings.signals[0];
            let label = i18n::format(
                "generator.hz_dbfs_peak_lead",
                &[
                    ("frequency_hz", &format!("{:.3}", s.frequency_hz)),
                    ("amplitude_dbfs", &format!("{:.3}", s.amplitude_dbfs)),
                    ("phase_degrees", &format!("{:.3}", s.phase_degrees)),
                ],
            )
            .to_string();
            c.steps
                .extend([Step::ScrollTo(label.clone()), Step::HoverText(label)]);
            c.labels.push(
                i18n::format(
                    "generator.applied_hz_dbfs_peak_lead",
                    &[
                        ("frequency_hz", &s.frequency_hz.to_string()),
                        ("amplitude_dbfs", &s.amplitude_dbfs.to_string()),
                        ("phase_degrees", &s.phase_degrees.to_string()),
                    ],
                )
                .to_string(),
            );
        }
        ("lockin" | "comparison", "menu-ref" | "menu-sig") => {
            let id = match (instrument, target) {
                ("lockin", "menu-ref") => "lockin_ref_primary",
                ("lockin", _) => "lockin_signal_primary",
                (_, "menu-ref") => "comparison_ref_primary",
                _ => "comparison_signal_primary",
            };
            c.steps.push(Step::ClickControl(egui::Id::unique((
                "qa_channel_select",
                id,
            ))));
            c.labels = vec![channel::name(0), channel::name(1)];
            c.popup = true;
        }
        ("lockin", "menu-tau") => {
            c.steps.push(Step::Click(
                i18n::text("lockin.time_constant_presets").into(),
            ));
            c.labels = vec!["1.0000 ms".into(), "10.000 s".into()];
            c.popup = true;
        }
        ("lockin", "menu-integration") => {
            c.steps.push(Step::Click(
                i18n::format(
                    "lockin.integration_samples",
                    &[("integration_samples", "4096")],
                )
                .to_string(),
            ));
            c.labels = ["1024", "4096", "16384", "65536"]
                .map(|n| i18n::format("lockin.samples", &[("n", n)]).to_string())
                .into();
            c.popup = true;
        }
        ("lockin", "tooltip-valid" | "tooltip-invalid") => {
            if target == "tooltip-invalid" {
                app.input_failed = true;
            }
            c.steps
                .push(Step::HoverText(i18n::text("lockin.amplitude_peak").into()));
            c.labels.push(if target == "tooltip-invalid" {
                i18n::text("lockin.no_valid_reading_no_bar_marker_is_shown").into()
            } else {
                i18n::format(
                    "lockin.display_scale_only",
                    &[
                        (
                            "v",
                            &format!("{:+.12e}", app.lockin_result.amplitude_peak.unwrap()),
                        ),
                        ("unit", "FS"),
                    ],
                )
                .to_string()
            });
        }
        ("lockin", "captured") => {
            c.steps
                .push(Step::Click(i18n::text("lockin.measurement_details").into()));
            c.steps.push(Step::ScrollTo(
                i18n::text("lockin.display_bars_auto_scale_they_do_not_change_input").into(),
            ));
            c.labels
                .push(i18n::text("lockin.display_bars_auto_scale_they_do_not_change_input").into());
        }
        ("comparison", "menu-size") => {
            c.steps.push(Step::Click(
                i18n::format("comparison.samples", &[("size", "4096")]).to_string(),
            ));
            c.labels = comparison::SIZES.map(|s| s.to_string()).into();
            c.popup = true;
        }
        ("comparison", "menu-window") => {
            c.steps
                .push(Step::Click(Window::Hann.display_name().into()));
            c.labels = [Window::Rectangular, Window::Hann, Window::BlackmanHarris]
                .map(|w| w.display_name().into())
                .into();
            c.popup = true;
        }
        ("comparison", "menu-span") => {
            c.steps
                .push(Step::Click(i18n::text("comparison.around_reading").into()));
            c.labels = [
                i18n::text("comparison.around_reading"),
                i18n::text("comparison.valid_band"),
                i18n::text("comparison.full_nyquist"),
                i18n::text("comparison.custom"),
            ]
            .map(str::to_owned)
            .into();
            c.popup = true;
        }
        ("comparison", "tooltip-range") => {
            c.steps.push(Step::HoverText(
                i18n::text("comparison.display_range").into(),
            ));
            c.labels.push(
                i18n::text(
                    "comparison.display_only_captured_analysis_validity_thresholds_and_the_phase",
                )
                .into(),
            );
        }
        ("comparison", "captured") => {
            c.steps.extend([
                Step::ScrollTo(i18n::text("comparison.captured_conditions").into()),
                Step::Click(i18n::text("comparison.captured_conditions").into()),
                Step::ScrollTo(
                    i18n::text("comparison.h1_pxy_pxx_scope_spectrum_and_comparison_each_retain")
                        .into(),
                ),
            ]);
            c.labels.push(
                i18n::text("comparison.h1_pxy_pxx_scope_spectrum_and_comparison_each_retain")
                    .into(),
            );
        }
        (_, "details-footer") => {
            let label = match instrument {
                "generator" => i18n::text("generator.output_details"),
                "lockin" => i18n::text(
                    "lockin.physical_ref_and_timing_remain_unverified_no_physical_oscillator",
                ),
                _ => i18n::text(
                    "comparison.ac_comparison_positive_phase_leads_ref_positive_delay_lags",
                ),
            };
            c.steps.push(Step::ScrollTo(label.into()));
            c.labels.push(label.into());
            if instrument == "generator" {
                c.steps.push(Step::Click(label.into()));
                let end = app.generator.status.transition_end[0].to_string();
                let last =
                    i18n::format("generator.selected_transition_ends", &[("i", &end)]).to_string();
                c.steps.push(Step::ScrollTo(last.clone()));
                c.labels.push(last);
            }
        }
        _ => {}
    }
    Ok(c)
}

pub(super) fn verify(app: &ScopeApp, progress: (u64, u64, u64), retained: &Retained) -> bool {
    assert_eq!(app.sample_rate, retained.rate);
    if !retained.running {
        assert_eq!(app.lockin_result, retained.lockin);
        assert_eq!(*app.comparison_result, *retained.comparison);
        assert_eq!(app.held_input, retained.input);
        assert_eq!(app.dropped, retained.dropped);
    }
    let now = scope::progress(app);
    if retained.running && (now.0 <= progress.0 || now.1 <= progress.1) {
        return false;
    }
    if retained.output
        && !matches!(app.generator.status.state, generator::State::Error(_))
        && now.2 <= progress.2
    {
        return false;
    }
    true
}
