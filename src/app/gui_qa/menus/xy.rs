//! I6d XY: internal Generator acquisition, retained f64 pairs, menus and every
//! dedicated hover. Synthetic histories explicitly cover unavailable/gap states.
use super::*;
use crate::xy::{self, CursorMode};

pub(super) struct Retained {
    settings: xy::Settings,
    capture: xy::Capture,
    frames: Option<Vec<Option<Vec<f64>>>>,
    points: [Option<[f64; 2]>; 2],
    samples: [Option<u64>; 2],
    input: Option<export::Input>,
    dropped: u64,
    sample_rate: u32,
    mode: CursorMode,
}

impl Retained {
    pub(super) fn new(app: &ScopeApp) -> Self {
        Self {
            settings: app.xy_settings,
            capture: app.xy_capture.clone(),
            frames: (!app.running()).then(|| {
                app.history
                    .samples(app.xy_capture.range.clone())
                    .map(|frame| frame.map(<[f64]>::to_vec))
                    .collect()
            }),
            points: app.cursors.xy_points,
            samples: app.cursor_samples(),
            input: app.held_input.clone(),
            dropped: app.dropped,
            sample_rate: app.sample_rate,
            mode: app.xy_cursor_mode,
        }
    }
}

fn prepare(app: &mut ScopeApp, target: &str) -> Result<(), String> {
    assert!(app.core.is_none() && !app.running() && app.generator.stopped());
    app.presentation = Presentation::default();
    app.presentation.apply(Action::OpenSingle(Instrument::Xy));
    app.shell = shell::Shell::default();
    app.source = Source::Generator;
    app.demo_enabled = false;
    app.core = Some(measurement::Worker::new(app.stft.take_feeder()));
    app.acquisition_mode = acquisition::Mode::Auto;
    app.spectrum_mode = SpectrumMode::Continuous;
    app.xy_settings = xy::Settings {
        x_fs_per_div: 0.05,
        y_fs_per_div: 0.05,
        ..Default::default()
    };
    app.xy_cursor_mode = if matches!(
        target,
        "trace"
            | "auto"
            | "free-run"
            | "trace-outside"
            | "details-trace"
            | "details-trigger"
            | "tooltip-plot-trace"
    ) || target.starts_with("menu-trigger")
        || target == "menu-edge"
        || target.starts_with("tooltip-trigger")
    {
        CursorMode::TraceSnap
    } else {
        CursorMode::Free
    };
    app.trigger = Trigger::default();
    if target == "auto" {
        app.trigger.level = 0.9;
    }
    if target == "free-run" {
        app.trigger.edge = Edge::Free;
    }
    let mut signals = generator::Settings::default();
    for (index, signal) in signals.signals.iter_mut().enumerate() {
        signal.enabled = true;
        signal.frequency_hz = 1000.0;
        signal.amplitude_dbfs = -18.0;
        signal.phase_degrees = index as f64 * 90.0;
    }
    app.generator.configure(signals);
    scope::wait(app, |app| !app.generator.pending)?;
    app.generator.start();
    scope::wait(app, |app| {
        app.generator.status.state == generator::State::Running && !app.generator.starting
    })?;
    let mut driver = Driver::new();
    let locale = i18n::locale();
    i18n::initialize(&driver.ctx, None);
    i18n::set_locale(&driver.ctx, locale.id());
    driver.frame(app, vec![]);
    driver.frame(app, vec![]);
    if !matches!(target, "empty" | "error-empty") {
        driver.click(app, i18n::text("io.start_input"))?;
        scope::wait(app, |app| {
            app.analyzer.is_ready() && app.history.len() >= 4800
        })?;
        if target == "error" {
            app.fail_input("I6d simulated XY input error (internal Generator)".into());
            scope::wait(app, |app| app.pending_stop.is_none())?;
        } else if target != "live" {
            driver.frame(app, vec![]);
            driver.click(app, i18n::text("io.stop_input"))?;
            scope::wait(app, |app| app.pending_stop.is_none())?;
        }
    } else if target == "error-empty" {
        app.fail_input("I6d simulated XY input error (internal Generator)".into());
        scope::wait(app, |app| app.pending_stop.is_none())?;
    }
    if matches!(target, "stopped" | "empty") {
        driver.frame(app, vec![]);
        driver.click(app, i18n::text("generator.stop_output_2"))?;
        scope::wait(app, |app| app.generator.stopped())?;
    }
    // Explicit display fixtures after finite input Stop; no physical I/O.
    if matches!(target, "mono" | "gap" | "invalid" | "limit" | "waiting") {
        // Scope replies must not replace the stopped synthetic display history.
        app.pending_scope = None;
        app.core = None;
        let channels = if target == "mono" { 1 } else { 2 };
        let count = if target == "limit" { 40000 } else { 2400 };
        app.history = History::with_channels(count, channels);
        app.channels = channels as u16;
        if target == "limit" {
            app.sample_rate = 192000;
            app.xy_settings.milliseconds = 200.0;
        }
        if let Some(input) = &mut app.held_input {
            input.channels = channels;
            input.nominal_sample_rate_hz = app.sample_rate;
            input.source = export::Source::InternalQa {
                description: format!("Synthetic XY {target} history"),
            };
        }
        if target == "gap" {
            app.dropped = 200;
        }
        if target != "waiting" {
            for i in 0..count {
                if target == "gap" && (1000..1200).contains(&i) {
                    continue;
                }
                let phase = std::f64::consts::TAU * (i % 48) as f64 / 48.0;
                let pair = if target == "invalid" {
                    [f64::NAN, 0.0]
                } else {
                    [0.1 * phase.sin(), 0.1 * phase.cos()]
                };
                app.history.push_at(i as u64, &pair[..channels]);
            }
        }
        println!(
            "XY review synthetic history: {target}; channels={channels}; Fs={}; no physical stream",
            app.sample_rate
        );
    }
    if target == "missing" {
        app.xy_channels = channel::Pair([0, 2]);
        app.xy_settings.channels = app.xy_channels;
    }
    if target == "source-pending" {
        app.xy_settings.channels = channel::Pair([1, 0]);
    }
    app.xy_dirty = true;
    app.rebuild_xy();
    if app.xy_cursor_mode == CursorMode::TraceSnap && !app.xy_capture.range.is_empty() {
        let reference = cursor::trigger_sample(app.xy_capture.range.clone()).unwrap();
        app.cursors
            .set_trace_time(0, reference + 3, app.xy_capture.range.clone());
        app.cursors
            .set_trace_time(1, reference + 9, app.xy_capture.range.clone());
        if target == "trace-outside" {
            app.cursors
                .set_trace_time(0, reference + 200, app.xy_capture.range.clone());
            app.cursors
                .set_trace_time(1, reference + 900, app.xy_capture.range.clone());
            app.xy_settings.milliseconds = 0.5;
            app.xy_dirty = true;
            app.rebuild_xy();
        }
    } else if !matches!(
        target,
        "empty" | "error-empty" | "mono" | "missing" | "waiting" | "invalid"
    ) {
        app.cursors.set_xy_point(0, [0.0625, -0.03125]);
        app.cursors.set_xy_point(
            1,
            if target == "free-outside" {
                [10.0, -10.0]
            } else {
                [-0.03125, 0.0625]
            },
        );
    }
    if !matches!(
        target,
        "empty" | "error-empty" | "mono" | "missing" | "gap" | "invalid" | "limit" | "waiting"
    ) {
        let amplitude = 10.0_f64.powf(-18.0 / 20.0);
        let (sin, cos) = (std::f64::consts::TAU * 1000.0 / app.sample_rate as f64).sin_cos();
        let mut previous: Option<[f64; 2]> = None;
        for frame in app.history.samples(app.xy_capture.range.clone()) {
            let Some(frame) = frame else {
                previous = None;
                continue;
            };
            let pair = [frame[0], frame[1]];
            assert!(
                (pair[0].hypot(pair[1]) - amplitude).abs() < 1e-12,
                "Internal XY pair differs from known sine amplitude/90 degree phase"
            );
            if let Some([x, y]) = previous {
                assert!((pair[0] - (x * cos + y * sin)).abs() < 1e-12);
                assert!((pair[1] - (y * cos - x * sin)).abs() < 1e-12);
            }
            previous = Some(pair);
        }
    }
    app.dirty = true;
    Ok(())
}

pub(super) fn case(app: &mut ScopeApp, target: &str) -> Result<Case, String> {
    prepare(app, target)?;
    let mut case = Case {
        steps: vec![],
        labels: vec![],
        popup: false,
        navigation: false,
        search: None,
    };
    let plot_help = match app.xy_cursor_mode {
        CursorMode::Free => i18n::text("xy.free_click_or_drag_to_fix_x_y_amplitudes"),
        CursorMode::TraceSnap => {
            i18n::text("xy.trace_snap_selects_the_nearest_actual_pair_from_the")
        }
    };
    match target {
        "empty" | "live" | "held" | "stopped" | "error" | "error-empty" | "trace" | "auto"
        | "free-run" | "free-outside" | "trace-outside" | "mono" | "missing" | "gap"
        | "invalid" | "limit" | "waiting" => {}
        "tooltip-plot-free" | "tooltip-plot-trace" | "tooltip-coordinate" => {
            // Hover the square's center, away from the readout annotations.
            case.steps
                .push(Step::HoverControl(egui::Id::unique("qa_xy_plot")));
            case.labels.push(plot_help.into());
            if target == "tooltip-coordinate" {
                case.labels.push(
                    i18n::format(
                        "xy.x_fs_y_fs",
                        &[("x_fs_per_div", "+0.0000"), ("y_fs_per_div", "+0.0000")],
                    )
                    .to_string(),
                );
            }
        }
        "tooltip-cursor-a" | "tooltip-cursor-b" | "tooltip-clear" | "tooltip-placed" => {
            let (label, help) = match target {
                "tooltip-cursor-a" => (
                    "A",
                    i18n::text("common.choose_which_cursor_the_next_plot_click_or_drag"),
                ),
                "tooltip-cursor-b" => (
                    "B",
                    i18n::text("common.choose_which_cursor_the_next_plot_click_or_drag"),
                ),
                "tooltip-clear" => (
                    i18n::text("common.clear_cursors"),
                    i18n::text("common.clear_both_a_b_time_cursors_spectrum_spectrogram_frequency"),
                ),
                _ => (
                    i18n::text("common.placed_a_b"),
                    i18n::text("common.stored_cursor_positions_for_this_view_readings_can_be"),
                ),
            };
            case.steps.push(Step::HoverText(label.into()));
            case.labels.push(help.into());
        }
        "details"
        | "details-trace"
        | "details-trigger"
        | "details-footer"
        | "source-pending"
        | "menu-x"
        | "menu-y"
        | "menu-edge"
        | "menu-trigger-source"
        | "tooltip-free"
        | "tooltip-trace"
        | "tooltip-window"
        | "tooltip-x-scale"
        | "tooltip-y-scale"
        | "tooltip-trigger-level" => {
            app.presentation.details_visible = true;
            app.shell.narrow_details = true;
            let label = match target {
                "details-footer" => "",
                "source-pending" | "tooltip-free" | "tooltip-trace" => i18n::text("xy.free"),
                "menu-y" | "tooltip-y-scale" => i18n::text("xy.y_axis"),
                "menu-edge" | "menu-trigger-source" => i18n::text("oscilloscope.edge"),
                "tooltip-trigger-level" => i18n::text("oscilloscope.level"),
                "details-trigger" => i18n::text("oscilloscope.zero_level"),
                _ => i18n::text("xy.observation"),
            };
            case.steps
                .push(Step::ScrollTo(if target == "details-footer" {
                    i18n::format(
                        "xy.up_to_real_sample_pairs_longer_windows_show_the",
                        &[("xy", &xy::MAX_POINTS.to_string())],
                    )
                    .to_string()
                } else {
                    label.into()
                }));
            match target {
                "menu-x" | "menu-y" | "menu-trigger-source" => {
                    let id = match target {
                        "menu-x" => "xy_x_source",
                        "menu-y" => "xy_y_source",
                        _ => "trigger_channel",
                    };
                    case.steps.push(Step::ClickControl(egui::Id::unique((
                        "qa_channel_select",
                        id,
                    ))));
                    case.popup = true;
                    case.labels = vec![channel::name(0), channel::name(1)];
                }
                "menu-edge" => {
                    case.steps.push(Step::Click(
                        i18n::text("oscilloscope.rising_edge").to_string(),
                    ));
                    case.popup = true;
                    case.labels = [
                        i18n::text("oscilloscope.free_run"),
                        i18n::text("oscilloscope.rising_edge"),
                        i18n::text("oscilloscope.falling_edge"),
                    ]
                    .map(str::to_owned)
                    .to_vec();
                }
                "tooltip-free" | "tooltip-trace" => {
                    let (label, help) = if target == "tooltip-free" {
                        (
                            i18n::text("xy.free"),
                            i18n::text("xy.fix_x_y_amplitudes_independently_of_the_moving_trace"),
                        )
                    } else {
                        (
                            i18n::text("xy.trace_snap"),
                            i18n::text("xy.follow_a_real_sample_at_a_fixed_time_offset"),
                        )
                    };
                    case.steps.push(Step::HoverText(label.into()));
                    case.labels.push(help.into());
                }
                "tooltip-window"
                | "tooltip-x-scale"
                | "tooltip-y-scale"
                | "tooltip-trigger-level" => {
                    case.steps
                        .push(Step::HoverControl(egui::Id::unique(match target {
                            "tooltip-window" => "qa_xy_window",
                            "tooltip-x-scale" => "qa_xy_x_scale",
                            "tooltip-y-scale" => "qa_xy_y_scale",
                            _ => "qa_trigger_level",
                        })));
                    case.labels.push(
                        i18n::text("oscilloscope.drag_the_slider_or_value_to_adjust_double_click")
                            .to_string(),
                    );
                }
                "details-trigger" => {
                    case.labels
                        .push(i18n::text("oscilloscope.zero_level").into());
                }
                "details-footer" => case.labels.push(
                    i18n::format(
                        "xy.up_to_real_sample_pairs_longer_windows_show_the",
                        &[("xy", &xy::MAX_POINTS.to_string())],
                    )
                    .to_string(),
                ),
                "source-pending" => case.labels.push(
                    i18n::text("xy.source_changes_apply_on_start_held_xy_keeps_its").to_string(),
                ),
                _ => {}
            }
        }
        _ => return Err(format!("Unknown XY review: {target}")),
    }
    Ok(case)
}

pub(super) fn verify(
    app: &ScopeApp,
    ctx: &egui::Context,
    target: &str,
    before: (u64, u64, u64),
    retained: &Retained,
) -> bool {
    let after = scope::progress(app);
    if app.running() && (after.0 <= before.0 || after.1 <= before.1) {
        return false;
    }
    if !app.generator.stopped() && after.2 <= before.2 {
        return false;
    }
    assert_eq!(app.xy_settings, retained.settings);
    assert_eq!(app.xy_cursor_mode, retained.mode);
    assert_eq!(app.sample_rate, retained.sample_rate);
    assert_eq!(app.cursors.xy_points, retained.points);
    if let Some(frames) = &retained.frames {
        assert_eq!(app.held_input, retained.input);
        assert_eq!(app.dropped, retained.dropped);
        assert_eq!(app.xy_capture.range, retained.capture.range);
        assert_eq!(app.xy_capture.channels, retained.capture.channels);
        assert_eq!(app.xy_capture.triggered, retained.capture.triggered);
        assert_eq!(app.xy_capture.limited, retained.capture.limited);
        assert_eq!(app.cursor_samples(), retained.samples);
        let current: Vec<_> = app
            .history
            .samples(app.xy_capture.range.clone())
            .map(|frame| frame.map(<[f64]>::to_vec))
            .collect();
        assert_eq!(
            &current, frames,
            "Retained f64 pairs or gap validity changed"
        );
    }
    if target == "details-trigger" {
        assert!(
            painted_text(ctx, i18n::text("oscilloscope.t_markers_top_ms_right_level")).is_empty(),
            "Scope marker explanation leaked into XY details"
        );
    }
    if target.starts_with("tooltip-")
        || target.starts_with("menu-")
        || target.starts_with("details")
        || target == "source-pending"
    {
        return true;
    }
    assert_visible(ctx, i18n::text("generator.stop_output_2"));
    assert_visible(
        ctx,
        if app.running() {
            i18n::text("io.stop_input")
        } else {
            i18n::text("io.start_input")
        },
    );
    assert_visible(
        ctx,
        if app.running() {
            i18n::text("common.live")
        } else if app.xy_capture.range.is_empty() {
            i18n::text("common.not_acquired")
        } else {
            i18n::text("common.held")
        },
    );
    if target.starts_with("error") {
        assert_visible(ctx, "I6d simulated XY input error (internal Generator)");
    }
    let reason = match target {
        "empty" | "error-empty" => Some(i18n::text("xy.xy_requires_two_input_channels")),
        "mono" => Some(i18n::text("xy.xy_unavailable_mono_input")),
        "missing" => Some(i18n::text("xy.xy_unavailable_assigned_channel_missing")),
        "waiting" | "invalid" => Some(i18n::text("xy.waiting_for_sample_pairs")),
        _ => None,
    };
    if let Some(reason) = reason {
        assert_visible(ctx, reason);
    }
    match target {
        "trace" => assert!(app.xy_capture.triggered),
        "auto" | "free-run" => assert!(!app.xy_capture.triggered),
        "trace-outside" => {
            // Shared time cursors still resolve in retained history; only XY's
            // shortened observation window makes their pair readouts unavailable.
            for sample in app.cursor_samples() {
                assert!(
                    !app.xy_capture
                        .range
                        .contains(&sample.expect("Retained shared cursor"))
                );
            }
        }
        "limit" => {
            assert!(app.xy_capture.limited);
            assert_eq!(
                app.xy_capture.range.end - app.xy_capture.range.start,
                xy::MAX_POINTS as u64
            );
        }
        "gap" => assert_eq!(
            app.history
                .samples(app.xy_capture.range.clone())
                .filter(Option::is_none)
                .count(),
            200
        ),
        _ => {}
    }
    // Read the actual painted annotations, including wrapped/outside reasons.
    // Assert complete bounds and no A/B/delta overlap.
    let layers: Vec<_> = ctx.memory(|memory| memory.layer_ids().collect());
    let notes = ctx.graphics(|graphics| {
        layers
            .into_iter()
            .filter_map(|layer| graphics.get(layer))
            .flat_map(|list| list.all_entries())
            .filter_map(|shape| {
                let egui::Shape::Text(text) = &shape.shape else {
                    return None;
                };
                let label = text.galley.text();
                (label.starts_with("A X ")
                    || label.starts_with("B X ")
                    || label.starts_with("B−A ΔX")
                    || label
                        == i18n::format("xy.outside_xy_window_or_unavailable", &[("index", "A")])
                            .as_ref()
                    || label
                        == i18n::format("xy.outside_xy_window_or_unavailable", &[("index", "B")])
                            .as_ref())
                .then(|| {
                    (
                        text.visual_bounding_rect(),
                        shape.clip_rect,
                        label.to_owned(),
                    )
                })
            })
            .collect::<Vec<_>>()
    });
    for (i, (bounds, clip, label)) in notes.iter().enumerate() {
        assert!(
            clip.contains_rect(*bounds) && ctx.content_rect().contains_rect(*bounds),
            "XY cursor note clipped: {label}"
        );
        for (other, _, _) in &notes[..i] {
            assert!(
                !bounds.intersects(*other),
                "XY cursor notes overlap: {label}"
            );
        }
    }
    if matches!(target, "held" | "trace" | "free-outside") {
        assert_eq!(notes.len(), 3);
    }
    true
}
