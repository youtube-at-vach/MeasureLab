//! I6c inventory: real internal Generator/input, finite Stop/Single/error, and
//! dedicated Scope hover targets. No physical streams or unplug tests.
use super::*;

pub(super) fn progress(app: &ScopeApp) -> (u64, u64, u64) {
    let input = app.core.as_ref().map_or((0, 0), |core| {
        (
            core.metrics.input_frames.load(Ordering::Relaxed),
            core.spectrum.metrics.windows.load(Ordering::Relaxed),
        )
    });
    (input.0, input.1, app.generator.status.next_sample)
}

fn wait(app: &mut ScopeApp, ready: impl Fn(&ScopeApp) -> bool) -> Result<(), String> {
    let deadline = Instant::now() + Duration::from_secs(5);
    loop {
        app.poll_audio();
        app.generator.poll();
        app.poll_measurement();
        if ready(app) {
            return Ok(());
        }
        if Instant::now() > deadline {
            return Err(format!(
                "Scope review timed out: {:?}; {:?}",
                app.input_error, app.generator.error
            ));
        }
        std::thread::sleep(Duration::from_millis(5));
    }
}

pub(super) fn case(app: &mut ScopeApp, target: &str) -> Result<Case, String> {
    let state = match target {
        "tooltip-trigger-settings" => "waiting",
        "tooltip-invalid" => "invalid",
        name if name.starts_with("tooltip-") || name.starts_with("menu-") => "held",
        name => name,
    };
    if !matches!(
        state,
        "live"
            | "held"
            | "stopped"
            | "waiting"
            | "single"
            | "incomplete"
            | "error"
            | "error-empty"
            | "invalid"
    ) {
        return Err(format!("Unknown Scope review state: {state}"));
    }
    assert!(app.core.is_none() && !app.running() && app.generator.stopped());
    app.presentation = Presentation::default();
    app.shell = shell::Shell::default();
    app.source = Source::Generator;
    app.demo_enabled = false;
    app.core = Some(measurement::Worker::new(app.stft.take_feeder()));
    app.acquisition_mode = if matches!(state, "waiting" | "single" | "incomplete" | "error-empty") {
        acquisition::Mode::Single
    } else {
        acquisition::Mode::Auto
    };
    app.trigger = Trigger::default();
    if matches!(state, "waiting" | "incomplete" | "error-empty") {
        app.trigger.level = 0.9;
    }
    if state == "invalid" {
        app.calibration.pending = app.calibration.pending.with(
            0,
            Some(calibration::Calibration::new(
                "i6c-overflow-fixture".into(),
                1,
                f64::MAX,
                f64::MAX,
                "V".into(),
                "Synthetic overflowing calibration, not a physical reference".into(),
            )?),
        )?;
    }
    let mut signals = generator::Settings::default();
    for signal in &mut signals.signals {
        signal.enabled = true;
        signal.frequency_hz = 1000.0;
        signal.amplitude_dbfs = -18.0;
    }
    app.generator.configure(signals);
    wait(app, |app| !app.generator.pending)?;
    app.generator.start();
    wait(app, |app| {
        app.generator.status.state == generator::State::Running && !app.generator.starting
    })?;
    let mut driver = Driver::new();
    // Install the product fonts so real Japanese widget labels can be located.
    let locale = i18n::locale();
    i18n::initialize(&driver.ctx, None);
    i18n::set_locale(&driver.ctx, locale.id());
    driver.frame(app, vec![]);
    driver.frame(app, vec![]);
    driver.click(app, i18n::text("io.start_input"))?;
    wait(app, |app| {
        !app.history.is_empty()
            && (matches!(state, "single" | "invalid") || app.analyzer.is_ready())
    })?;
    if state == "single" {
        wait(app, |app| !app.running() && app.pending_stop.is_none())?;
        assert_eq!(app.acquisition_state, acquisition::State::Complete);
    } else if state == "waiting" || state == "error-empty" || state == "incomplete" {
        assert_eq!(
            app.scope_notice(),
            Some(display::ScopeNotice::WaitingForTrigger)
        );
    } else {
        wait(app, |app| !app.scope_range.is_empty())?;
    }
    if matches!(state, "error" | "error-empty") {
        app.fail_input("I6c simulated input error (internal Generator)".into());
        wait(app, |app| app.pending_stop.is_none())?;
        assert!(app.input_error.is_some());
    } else if !matches!(state, "live" | "waiting" | "single") {
        driver.frame(app, vec![]);
        driver.click(app, i18n::text("io.stop_input"))?;
        wait(app, |app| app.pending_stop.is_none())?;
    }
    if state == "stopped" {
        driver.frame(app, vec![]);
        driver.click(app, i18n::text("generator.stop_output_2"))?;
        wait(app, |app| app.generator.stopped())?;
    } else {
        assert_eq!(
            app.generator.status.state,
            generator::State::Running,
            "Input Stop/Single/failure stopped output"
        );
    }
    if state == "invalid" {
        assert_eq!(app.scope_readings[0], Reading::NonFinite);
    } else if !app.scope_range.is_empty() {
        assert!(matches!(app.scope_readings[0], Reading::Valid(_)));
        assert_eq!(app.scope_readings[2], Reading::Unavailable);
    }
    let mut case = Case {
        steps: vec![],
        labels: vec![],
        popup: false,
        navigation: false,
        search: None,
    };
    let mut hover = |label: &str, help: String| {
        case.steps.push(Step::HoverText(label.into()));
        case.labels.push(help);
    };
    match target {
        "live" | "held" | "stopped" | "waiting" | "single" | "incomplete" | "error"
        | "error-empty" | "invalid" => {}
        "tooltip-autoset" => hover(
            i18n::text("oscilloscope.autoset"),
            i18n::text("oscilloscope.automatically_set_time_scale_amplitude_and_trigger_for_a")
                .into(),
        ),
        "tooltip-cursor-a" | "tooltip-cursor-b" => hover(
            if target.ends_with('a') { "A" } else { "B" },
            i18n::text("common.choose_which_cursor_the_next_plot_click_or_drag").into(),
        ),
        "tooltip-clear" => hover(
            i18n::text("common.clear_cursors"),
            i18n::text("common.clear_both_a_b_time_cursors_spectrum_spectrogram_frequency").into(),
        ),
        "tooltip-placed" => {
            app.cursors.set_scope_time(0, 0.3);
            app.cursors.set_scope_time(1, 0.7);
            hover(
                i18n::text("common.placed_a_b"),
                i18n::text("common.stored_cursor_positions_for_this_view_readings_can_be").into(),
            );
        }
        "tooltip-axis" => hover(
            app.scope_axis_label().as_ref(),
            i18n::format(
                "common.selected_ch_axis",
                &[
                    ("scope_selected", "1"),
                    ("display", display::amplitude_help()),
                ],
            )
            .to_string(),
        ),
        "tooltip-time" => hover(
            i18n::text("common.time_ms"),
            i18n::format(
                "common.time_relative_to_the_sweep_reference_t_ms",
                &[("display", display::sample_rate_help())],
            )
            .to_string(),
        ),
        "tooltip-sample" | "tooltip-cursor-values" => {
            case.steps
                .push(Step::HoverControl(egui::Id::unique("qa_scope_plot")));
            let help = if target == "tooltip-sample" {
                let sample = cursor::sample_at_fraction_with_offset(
                    app.scope_range.clone(),
                    0.5,
                    app.scope_sample_offset,
                )
                .ok_or("No sample for plot hover")?;
                app.sample_text(sample)
            } else {
                app.cursors.set_scope_time(0, 0.3);
                app.cursors.set_scope_time(1, 0.7);
                app.cursor_samples()
                    .into_iter()
                    .enumerate()
                    .filter_map(|(index, sample)| {
                        let frame = app.scope_history().get(sample?)?;
                        let values: Vec<_> = app
                            .scope_view_channels()
                            .0
                            .into_iter()
                            .enumerate()
                            .filter_map(|(trace, channel)| {
                                if !app.enabled[trace] {
                                    return None;
                                }
                                let raw = frame.get(channel)?;
                                let value = app.calibration.captured.value(channel, *raw)?;
                                Some(
                                    i18n::format(
                                        "oscilloscope.fs",
                                        &[
                                            ("channel", &channel::name(channel)),
                                            ("raw", &display::number(Some(*raw))),
                                            ("value", &display::number(Some(value))),
                                            ("channel_2", app.calibration.captured.unit(channel)),
                                        ],
                                    )
                                    .to_string(),
                                )
                            })
                            .collect();
                        Some(
                            i18n::format(
                                "oscilloscope.cursor",
                                &[("index", cursor_name(index)), ("join", &values.join(" · "))],
                            )
                            .to_string(),
                        )
                    })
                    .collect::<Vec<_>>()
                    .join("\n")
            };
            case.labels.push(help);
        }
        "tooltip-trigger-top" | "tooltip-trigger-level" => {
            case.steps.push(Step::HoverControl(egui::Id::unique(
                if target.ends_with("top") {
                    "qa_scope_trigger_top"
                } else {
                    "qa_scope_trigger_level"
                },
            )));
            case.labels.push(app.scope_trigger_marker_help());
        }
        "tooltip-trigger" | "tooltip-trigger-settings" => hover(
            app.scope_trigger_marker_status(),
            app.scope_trigger_marker_help(),
        ),
        "tooltip-timebase" => {
            case.steps
                .push(Step::HoverControl(egui::Id::unique("qa_scope_timebase")));
            case.labels.push(
                i18n::format(
                    "oscilloscope.wheel_time_scale_shift_wheel_selected_channel_scale_double",
                    &[
                        ("display", display::div_help()),
                        ("display_2", display::amplitude_help()),
                    ],
                )
                .to_string(),
            );
        }
        "tooltip-channel" | "tooltip-unavailable" | "tooltip-invalid" => {
            let index = if target == "tooltip-unavailable" {
                2
            } else {
                0
            };
            let channel = app.scope_view_channels().0[index];
            case.steps.push(Step::HoverControl(egui::Id::unique((
                "qa_scope_channel",
                index,
            ))));
            case.labels.push(
                i18n::format(
                    "oscilloscope.ch_select_to_edit_this_channel_in_scope_settings",
                    &[
                        ("index", &(index + 1).to_string()),
                        ("channel", &channel::name(channel)),
                        (
                            "else",
                            if index == 2 {
                                i18n::text("oscilloscope.outside_input_channel_range")
                            } else {
                                ""
                            },
                        ),
                        ("index_2", &app.scope_readout_details(index)),
                        ("display", display::div_help()),
                    ],
                )
                .to_string(),
            );
        }
        "tooltip-toggle" => {
            case.steps.push(Step::HoverControl(egui::Id::unique((
                "qa_scope_toggle",
                0usize,
            ))));
            case.labels.push(
                i18n::format(
                    "oscilloscope.show_ch_waveform_keeps_selection_and_measurements",
                    &[("index", "1")],
                )
                .to_string(),
            );
        }
        "tooltip-auto"
        | "tooltip-normal"
        | "tooltip-single"
        | "tooltip-start-single"
        | "tooltip-slider"
        | "tooltip-display"
        | "tooltip-fit"
        | "tooltip-fit-common"
        | "tooltip-units"
        | "tooltip-marker-details"
        | "menu-edge"
        | "menu-source"
        | "menu-display" => {
            app.presentation.details_visible = true;
            app.shell.narrow_details = true;
            let (label, help) = match target {
                "tooltip-auto" => (
                    i18n::text("oscilloscope.auto"),
                    i18n::text("oscilloscope.update_even_without_a_trigger_crossing"),
                ),
                "tooltip-normal" => (
                    i18n::text("oscilloscope.normal"),
                    i18n::text(
                        "oscilloscope.update_on_trigger_crossings_hold_the_last_capture_while",
                    ),
                ),
                "tooltip-single" => (
                    i18n::text("oscilloscope.single"),
                    i18n::text("oscilloscope.capture_once_on_the_next_trigger_crossing"),
                ),
                "tooltip-start-single" => (
                    i18n::text("oscilloscope.start_single_capture"),
                    i18n::text("oscilloscope.start_input_and_wait_for_a_single_triggered_capture"),
                ),
                "tooltip-fit" | "tooltip-fit-common" => (
                    i18n::text("oscilloscope.fit_amplitude"),
                    if target == "tooltip-fit-common" {
                        i18n::text("oscilloscope.fit_visible_channels")
                    } else {
                        i18n::text("oscilloscope.fit_the_selected_channel_s_raw_peak_and_centre")
                    },
                ),
                "tooltip-display" => (
                    i18n::text("oscilloscope.markers"),
                    i18n::text("oscilloscope.markers_t_markers_only_guides_t_markers_and_dotted"),
                ),
                "tooltip-units" => (
                    i18n::text("oscilloscope.fs_full_scale_fs_sample_rate_div_grid_division"),
                    "",
                ),
                "tooltip-marker-details" => {
                    (i18n::text("oscilloscope.t_markers_top_ms_right_level"), "")
                }
                "tooltip-slider" => (
                    i18n::text("oscilloscope.level"),
                    i18n::text("oscilloscope.drag_the_slider_or_value_to_adjust_double_click"),
                ),
                "menu-edge" => (i18n::text("oscilloscope.rising_edge"), ""),
                "menu-source" => (i18n::text("oscilloscope.source"), ""),
                "menu-display" => (i18n::text("oscilloscope.markers"), ""),
                _ => unreachable!(),
            };
            if target == "tooltip-fit-common" {
                app.scope_common_vertical = Some(app.scope_vertical[0]);
            }
            case.steps.push(Step::ScrollTo(label.into()));
            if target == "tooltip-slider" {
                case.steps
                    .push(Step::HoverControl(egui::Id::unique("qa_trigger_level")));
            } else if target == "menu-source" {
                case.steps.push(Step::Click(channel::name(0)));
            } else if target.starts_with("menu-") {
                case.steps.push(Step::Click(label.into()));
            } else {
                case.steps.push(Step::HoverText(label.into()));
            }
            if target.starts_with("menu-") {
                case.popup = true;
                case.labels = match target {
                    "menu-edge" => [
                        i18n::text("oscilloscope.free_run"),
                        i18n::text("oscilloscope.rising_edge"),
                        i18n::text("oscilloscope.falling_edge"),
                    ]
                    .map(|key| key.into())
                    .to_vec(),
                    "menu-display" => [
                        i18n::text("oscilloscope.markers"),
                        i18n::text("oscilloscope.guides"),
                        i18n::text("oscilloscope.off"),
                    ]
                    .map(|key| key.into())
                    .to_vec(),
                    _ => vec![channel::name(0), channel::name(1)],
                };
            } else {
                case.labels.push(match target {
                    "tooltip-units" => format!(
                        "{}\n{}\n{}",
                        display::amplitude_help(),
                        display::sample_rate_help(),
                        display::div_help()
                    ),
                    "tooltip-marker-details" => app.scope_trigger_marker_help(),
                    _ => help.into(),
                });
            }
        }
        _ => return Err(format!("Unknown Scope review: {target}")),
    }
    app.dirty = true;
    Ok(case)
}

pub(super) fn verify(
    app: &ScopeApp,
    ctx: &egui::Context,
    target: &str,
    running: bool,
    output_running: bool,
    before: (u64, u64, u64),
    held: Option<&export::Document>,
) -> bool {
    let after = progress(app);
    if running && (after.0 <= before.0 || after.1 <= before.1) {
        return false;
    }
    if output_running {
        assert_eq!(app.generator.status.state, generator::State::Running);
        if after.2 <= before.2 {
            return false;
        }
    }
    if let Some(held) = held {
        let current = app
            .capture_scope_results()
            .expect("Held Scope became unavailable");
        assert_eq!(current.input, held.input);
        assert_eq!(current.scope, held.scope);
        assert_eq!(current.loss, held.loss);
    }
    if !target.starts_with("tooltip-") && !target.starts_with("menu-") {
        for label in [
            i18n::text("generator.stop_output_2"),
            if running {
                i18n::text("io.stop_input")
            } else {
                i18n::text("io.start_input")
            },
        ] {
            assert_visible(ctx, label);
        }
        let activity = if running && app.scope_range.is_empty() {
            i18n::text("common.waiting")
        } else if running {
            i18n::text("common.live")
        } else if app.scope_range.is_empty() {
            i18n::text("common.not_acquired")
        } else {
            i18n::text("common.held")
        };
        assert_visible(ctx, activity);
        if let Some(notice) = app.scope_notice() {
            assert_visible(ctx, notice.title());
        }
        match target {
            "single" => assert_visible(ctx, i18n::text("oscilloscope.single_complete")),
            "invalid" => assert_visible(ctx, i18n::text("oscilloscope.invalid_value")),
            "error" | "error-empty" => {
                assert_visible(ctx, "I6c simulated input error (internal Generator)")
            }
            _ => {}
        }
    }
    true
}
