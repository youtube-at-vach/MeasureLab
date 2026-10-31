//! I6d: real internal STFT, pinned f64 history and selections, every dedicated
//! menu/hover description. Finite synthetic STFT fixtures cover invalid/gap data.
use super::*;

pub(super) struct Retained {
    hold: Option<Arc<crate::spectrogram::history::Snapshot>>,
    selected: [Option<Arc<crate::spectrogram::history::Frame>>; 2],
    anchor: Option<u64>,
    unavailable: [bool; 2],
    stft_rows: u64,
    frequency: Option<f64>,
    quefrencies: [Option<f64>; 2],
}

impl Retained {
    pub(super) fn new(app: &ScopeApp) -> Self {
        Self {
            hold: app.spectrogram_hold.clone(),
            selected: app.spectrogram_selected.clone(),
            anchor: app.spectrogram_hold_anchor,
            unavailable: app.spectrogram_unavailable_selection,
            stft_rows: app.stft_history.metrics.collected.load(Ordering::Relaxed),
            frequency: app.cursors.frequency_hz,
            quefrencies: app.cursors.quefrency_seconds,
        }
    }
}

fn prepare(app: &mut ScopeApp, target: &str) -> Result<(), String> {
    assert!(app.core.is_none() && !app.running() && app.generator.stopped());
    app.presentation = Presentation::default();
    app.presentation
        .apply(Action::OpenSingle(Instrument::Spectrogram));
    app.shell = shell::Shell::default();
    app.source = Source::Generator;
    app.demo_enabled = false;
    app.core = Some(measurement::Worker::new(app.stft.take_feeder()));
    app.clear_spectrogram_view();
    app.stft_history.clear();
    app.last_stft = None;
    app.acquisition_mode = acquisition::Mode::Auto;
    app.spectrogram_settings = Settings {
        size: 2048,
        ..Default::default()
    };
    app.spectrum_settings.size = 2048;
    app.spectrum_mode = SpectrumMode::Continuous;
    if target.contains("cepstral") {
        app.spectrogram_mode = stft::Analysis::Cepstrogram;
    }
    if target == "filling" {
        app.spectrogram_settings.size = 32768;
    }
    let mut signals = generator::Settings::default();
    for signal in &mut signals.signals {
        signal.enabled = true;
        signal.frequency_hz = 984.375;
        signal.amplitude_dbfs = -18.0;
    }
    app.generator.configure(signals);
    scope::wait(app, |app| !app.generator.pending)?;
    app.generator.start();
    scope::wait(app, |app| {
        !app.generator.starting && app.generator.status.state == generator::State::Running
    })?;
    let mut driver = Driver::new();
    let locale = i18n::locale();
    i18n::initialize(&driver.ctx, None);
    i18n::set_locale(&driver.ctx, locale.id());
    driver.frame(app, vec![]);
    driver.frame(app, vec![]);
    if target == "filling" {
        partial_input(app)?;
    } else if !matches!(target, "idle" | "error-empty") {
        driver.click(app, i18n::text("io.start_input"))?;
        scope::wait(app, |app| {
            // Let complete rows pass the delayed Live edge before pressing
            // Hold; startup can legitimately still be blank.
            app.analyzer.is_ready()
                && app.stft_history.snapshot().retained_seconds()
                    >= if target == "hold-live" { 0.75 } else { 0.25 }
        })?;
    }
    if matches!(target, "error" | "error-empty") {
        app.fail_input("I6d simulated input error (internal Generator)".into());
        scope::wait(app, |app| app.pending_stop.is_none())?;
    } else if app.running() && !matches!(target, "live" | "hold-live" | "cepstral-live" | "filling")
    {
        driver.frame(app, vec![]);
        driver.click(app, i18n::text("io.stop_input"))?;
        scope::wait(app, |app| app.pending_stop.is_none())?;
    }
    if target == "stopped" {
        driver.frame(app, vec![]);
        driver.click(app, i18n::text("generator.stop_output_2"))?;
        scope::wait(app, |app| app.generator.stopped())?;
    }
    app.spectrogram_snapshot = app.stft_history.snapshot();
    if matches!(
        target,
        "invalid"
            | "gap"
            | "cepstral-silence"
            | "tooltip-invalid"
            | "tooltip-cepstral-silence"
            | "cepstral-invalid"
            | "tooltip-cepstral-invalid"
    ) {
        synthetic(app, target)?;
    }
    app.spectrogram_anchor = app.spectrogram_snapshot.latest().map_or(0, |f| f.info.end);
    if !matches!(
        target,
        "live"
            | "cepstral-live"
            | "held"
            | "stopped"
            | "error"
            | "error-empty"
            | "idle"
            | "filling"
    ) {
        // Exercise the actual Hold button, without freezing acquisition/analysis.
        driver.frame(app, vec![]);
        driver.frame(app, vec![]);
        driver.click(app, i18n::text("spectrogram.hold_action"))?;
        assert!(app.spectrogram_hold.is_some());
    }
    if target == "capacity" {
        let mut snapshot = (*app.spectrogram_hold.take().unwrap()).clone();
        snapshot.capacity_limited = true; // Explicit display-only synthetic flag.
        app.spectrogram_snapshot = Arc::new(snapshot);
        app.spectrogram_hold = Some(app.spectrogram_snapshot.clone());
        app.spectrogram_view_worker.clear();
    }
    if matches!(
        target,
        "cursors"
            | "time-only"
            | "outside"
            | "invalid"
            | "gap"
            | "cepstral-held"
            | "cepstral-silence"
            | "cepstral-invalid"
    ) {
        let frames: Vec<_> = app
            .spectrogram_hold
            .as_ref()
            .unwrap()
            .frames()
            .map(|f| f.info)
            .collect();
        for (i, frame) in frames.iter().rev().take(2).enumerate() {
            app.select_spectrogram_sample(i, frame.end - 1);
        }
        if target == "gap" {
            let first = frames.first().unwrap();
            app.select_spectrogram_sample(0, first.end);
            assert!(app.spectrogram_selected[0].is_none());
        } else if target == "outside" {
            app.spectrogram_seconds = 0.01;
            app.select_spectrogram_sample(0, frames.first().unwrap().end - 1);
        }
        if target != "time-only" {
            if app.cepstrogram_applied() {
                app.cursors.quefrency_seconds = [Some(0.001), Some(0.002)];
            } else {
                app.cursors.set_frequency(0, 984.375);
            }
        }
    }
    if target == "before-input" {
        app.select_spectrogram_time(0, 1.0);
        assert!(app.spectrogram_unavailable_selection[0]);
    }
    if target == "tooltip-placed" {
        let end = app
            .spectrogram_hold
            .as_ref()
            .unwrap()
            .latest()
            .unwrap()
            .info
            .end;
        app.select_spectrogram_sample(0, end - 1);
        app.select_spectrogram_sample(1, end - 1);
    }
    if target == "source-pending" {
        app.spectrogram_channel = 15; // Next-Start reservation; captured CH stays 1.
    }
    if target == "color-error" {
        app.spectrogram_color_error = true;
    }
    if target == "tooltip-cepstral-link" {
        app.presentation
            .apply(Action::PairWith(Instrument::Spectrum));
        app.presentation
            .apply(Action::FocusPane(Instrument::Spectrum));
        app.presentation.console.layout = Layout::Tabs;
    }
    app.dirty = true;
    Ok(())
}

/// A finite synthetic capture supplies fewer samples than one STFT window.
/// Keep its worker awaiting input; independent real Generator output continues.
fn partial_input(app: &mut ScopeApp) -> Result<(), String> {
    app.begin_observation();
    app.source = Source::Software;
    app.sample_rate = 48000;
    app.channels = 2;
    app.format = "Synthetic partial STFT input · f64".into();
    app.software_running = true;
    app.held_input = Some(export::Input {
        generation: app.input_generation,
        source: export::Source::InternalQa {
            description: app.format.clone(),
        },
        nominal_sample_rate_hz: 48000,
        channels: 2,
    });
    app.reset_analysis();
    app.reset_stft();
    let (mut producer, consumer) = rtrb::RingBuffer::new(4096);
    for sequence in 0..4096 {
        let mut samples = [0.0; crate::signal::MAX_CHANNELS];
        samples[..2]
            .fill(0.1 * (std::f64::consts::TAU * 984.375 * sequence as f64 / 48000.0).cos());
        producer
            .push(crate::audio::AudioFrame {
                sequence,
                samples,
                available_at: None,
            })
            .unwrap();
    }
    let metrics = Arc::new(crate::audio::Metrics::default());
    metrics.input_end.store(4096, Ordering::Release);
    app.core.as_ref().unwrap().start_capture(
        app.input_generation,
        crate::audio::Capture {
            consumer,
            sample_rate: 48000,
            channels: 2,
            format: app.format.clone(),
            metrics,
        },
        app.core_config(),
    );
    scope::wait(app, |app| {
        app.history.len() == 4096 && app.analyzer.is_ready()
    })?;
    println!("Spectrogram synthetic fixture: filling; 4096 finite samples / 32768-point STFT");
    Ok(())
}

/// Run finite samples through a separate real f64 STFT + collector, with
/// explicit NaN, sequence discontinuity or silence. Never alter live input.
fn synthetic(app: &mut ScopeApp, target: &str) -> Result<(), String> {
    assert!(!app.running());
    let config = app.stft_config();
    let mut worker = stft::Worker::new();
    let collector = crate::spectrogram::history::Collector::new(worker.take_results());
    let generation = worker.configure(config)?;
    collector.configure(app.input_generation, generation, config);
    for block in 0..2 {
        let start = block * config.size as u64 * 2;
        for n in start..start + config.size as u64 {
            let value = if target.contains("invalid") {
                f64::NAN
            } else if target.contains("silence") {
                0.0
            } else {
                0.1 * (std::f64::consts::TAU * 42.0 * n as f64 / config.size as f64).cos()
            };
            worker.submit(n, &[value, value]);
        }
        worker.flush();
        let deadline = Instant::now() + Duration::from_secs(5);
        while collector
            .snapshot()
            .latest()
            .is_none_or(|f| f.info.end < start + config.size as u64)
        {
            if Instant::now() > deadline {
                return Err("Synthetic STFT timed out".into());
            }
            std::thread::sleep(Duration::from_millis(5));
        }
    }
    app.spectrogram_snapshot = collector.snapshot();
    app.stft_history.freeze();
    app.stft_history
        .replace_frozen_snapshot(app.spectrogram_snapshot.clone());
    app.stft_generation = generation;
    app.last_stft = app.spectrogram_snapshot.latest().map(|f| f.info);
    let frame = app.spectrogram_snapshot.latest().unwrap();
    if target.contains("invalid") {
        assert!(!frame.valid());
    } else if target.contains("silence") {
        assert_eq!(
            frame.info.cepstrum.unwrap().status,
            crate::cepstrum::Status::NoSignal
        );
    } else {
        assert!(frame.valid() && frame.info.gap.input_frames > 0);
    }
    println!("Spectrogram synthetic fixture: {target}; finite STFT, no physical input");
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
    let details = target.starts_with("menu-") && target != "menu-source"
        || matches!(
            target,
            "details-display"
                | "details-analysis"
                | "color-error"
                | "cepstral-details"
                | "cepstral-display"
                | "tooltip-precision"
        );
    if details {
        app.presentation.details_visible = true;
        app.shell.narrow_details = true;
    }
    let menu = match target {
        "menu-source" => Some((channel::name(0), vec![channel::name(0), channel::name(1)])),
        "menu-color" => Some((
            app.spectrogram_color_map.display_name().into(),
            crate::spectrogram::ColorMap::ALL
                .iter()
                .take(6)
                .map(|m| m.display_name().into())
                .collect(),
        )),
        "menu-color-last" => Some((
            app.spectrogram_color_map.display_name().into(),
            crate::spectrogram::ColorMap::ALL
                .iter()
                .skip(6)
                .map(|m| m.display_name().into())
                .collect(),
        )),
        "menu-time" => Some((
            "5 s".into(),
            ["5 s", "10 s", "30 s", "60 s"].map(str::to_owned).to_vec(),
        )),
        "menu-mode" => Some((
            i18n::text("spectrogram.spectrogram").into(),
            vec![
                i18n::text("spectrogram.spectrogram").into(),
                i18n::text("spectrogram.cepstrogram").into(),
            ],
        )),
        "menu-precision" => Some((
            app.spectrogram_settings.precision.display_name().into(),
            [Precision::F64, Precision::F32]
                .map(|p| p.display_name().into())
                .to_vec(),
        )),
        "menu-size" | "menu-size-large" => Some((
            i18n::format("spectrogram.points", &[("size", "2048")]).to_string(),
            STFT_SIZES
                .into_iter()
                .skip(if target == "menu-size-large" { 4 } else { 0 })
                .take(4)
                .map(|size| {
                    i18n::format("spectrogram.points", &[("size", &size.to_string())]).to_string()
                })
                .collect(),
        )),
        "menu-overlap" => Some((
            app.spectrogram_overlap.display_name().into(),
            stft::Overlap::ALL.map(|o| o.display_name().into()).to_vec(),
        )),
        "menu-window" => Some((
            app.spectrogram_settings.window.display_name().into(),
            [Window::Hann, Window::Rectangular, Window::BlackmanHarris]
                .map(|w| w.display_name().into())
                .to_vec(),
        )),
        _ => None,
    };
    if let Some((label, labels)) = menu {
        if details {
            case.steps.push(Step::ScrollTo(label.clone()));
        }
        if target == "menu-mode" {
            case.steps
                .push(Step::ClickControl(egui::Id::unique("qa_stft_mode")));
        } else {
            case.steps.push(Step::Click(label));
        }
        if matches!(target, "menu-color-last" | "menu-size-large") {
            case.steps
                .push(Step::ScrollMenuTo(labels.last().unwrap().clone()));
        }
        case.labels = labels;
        case.popup = true;
        return Ok(case);
    }
    let hover = match target {
        "tooltip-cursor-a" | "tooltip-cursor-b" => Some((
            if target.ends_with('a') { "A" } else { "B" },
            i18n::text("common.choose_which_cursor_the_next_plot_click_or_drag"),
        )),
        "tooltip-clear" => Some((
            i18n::text("common.clear_cursors"),
            i18n::text("common.clear_both_a_b_time_cursors_spectrum_spectrogram_frequency"),
        )),
        "tooltip-placed" => Some((
            i18n::text("common.placed_a_b"),
            i18n::text("common.stored_cursor_positions_for_this_view_readings_can_be"),
        )),
        "tooltip-precision" => Some((
            app.spectrogram_settings.precision.display_name(),
            i18n::text("common.only_this_instrument_s_fft_changes_precision_input_history"),
        )),
        "tooltip-cepstral-link" => Some((
            i18n::text("spectrum.time_a_b_from_spectrogram"),
            i18n::text("spectrogram.cepstral_link_disabled"),
        )),
        _ => None,
    };
    if let Some((label, help)) = hover {
        if details {
            case.steps.push(Step::ScrollTo(label.into()));
        }
        case.steps.push(Step::HoverText(label.into()));
        case.labels.push(help.into());
        return Ok(case);
    }
    match target {
        "idle" | "live" | "hold-live" | "held" | "stopped" | "error" | "error-empty"
        | "filling" | "cursors" | "time-only" | "before-input" | "outside" | "invalid" | "gap"
        | "capacity" | "source-pending" | "cepstral-live" | "cepstral-held"
        | "cepstral-silence" | "cepstral-invalid" => {}
        "details-display" | "details-analysis" | "color-error" | "cepstral-details"
        | "cepstral-display" => {
            let label = match target {
                "details-display" => i18n::text("spectrogram.gestures"),
                "cepstral-display" => i18n::text("spectrogram.cepstral_gestures"),
                "color-error" => i18n::text("spectrogram.min_and_max_must_be_finite_with_min_max"),
                "cepstral-details" => i18n::text("spectrogram.cepstral_definition"),
                _ => i18n::text(
                    "spectrogram.per_window_bin_amplitude_uncalibrated_fs_orange_stripes_missing",
                ),
            };
            case.steps.push(Step::ScrollTo(label.into()));
            case.labels.push(label.into());
        }
        "tooltip-plot"
        | "tooltip-gap"
        | "tooltip-invalid"
        | "tooltip-cepstral"
        | "tooltip-cepstral-silence"
        | "tooltip-cepstral-invalid" => {
            let fraction = vec2(
                0.5,
                if target == "tooltip-gap" {
                    0.9
                } else if target.contains("invalid") || target == "tooltip-cepstral-silence" {
                    0.001
                } else {
                    0.03
                },
            );
            case.steps.push(Step::HoverAt(
                egui::Id::unique("qa_spectrogram_plot"),
                fraction,
            ));
            let sample = cursor::sample_at_age(
                app.spectrogram_anchor,
                fraction.y as f64 * app.spectrogram_seconds,
                app.sample_rate,
            );
            let frame = sample.and_then(|s| app.spectrogram_hold.as_ref().unwrap().at_sample(s));
            let view = app.spectrogram_view();
            let help = if let Some(frame) = frame {
                let row = frame.info;
                if app.cepstrogram_applied() {
                    app.cepstral_readout(frame, app.quefrency_range().at(fraction.x as f64))
                } else if !frame.valid() {
                    i18n::format(
                        "spectrogram.invalid_stft_window_non_finite_input_samples",
                        &[
                            ("start", &row.start.to_string()),
                            ("end", &row.end.to_string()),
                        ],
                    )
                    .to_string()
                } else {
                    let bin = cursor::nearest_bin(
                        view.frequency(fraction.x) as f64,
                        row.config.size,
                        row.config.sample_rate,
                    )
                    .unwrap();
                    i18n::format(
                        "spectrogram.hz_dbfs_samples",
                        &[
                            (
                                "size",
                                &format!(
                                    "{:.1}",
                                    bin as f64 * row.config.sample_rate as f64
                                        / row.config.size as f64
                                ),
                            ),
                            ("bin", &format!("{:.6}", frame.level_db(bin).unwrap())),
                            ("start", &row.start.to_string()),
                            ("end", &row.end.to_string()),
                        ],
                    )
                    .to_string()
                }
            } else {
                i18n::text("spectrogram.no_stft_data_at_this_time_gap_or_unavailable").into()
            };
            let gestures = if app.cepstrogram_applied() {
                i18n::text("spectrogram.cepstral_gestures")
            } else {
                spectrogram_controls::gestures()
            };
            case.labels.push(format!("{help}\n{gestures}"));
        }
        _ => return Err(format!("Unknown Spectrogram review: {target}")),
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
    let plot_visible = target != "tooltip-cepstral-link"
        && !(ctx.content_rect().width() < 1180.0
            && app.presentation.details_visible
            && app.shell.narrow_details);
    if app.running()
        && target != "filling"
        && (after.0 <= before.0
            || after.1 <= before.1
            || app.stft_history.metrics.collected.load(Ordering::Relaxed) <= retained.stft_rows)
    {
        return false;
    }
    if target == "filling" {
        assert_eq!(after.0, 4096);
        assert!(app.analyzer.is_ready());
        assert!(app.stft_history.snapshot().latest().is_none());
    }
    if target != "stopped" && after.2 <= before.2 {
        return false;
    }
    assert_eq!(app.spectrogram_hold_anchor, retained.anchor);
    assert_eq!(app.spectrogram_unavailable_selection, retained.unavailable);
    assert_eq!(app.cursors.frequency_hz, retained.frequency);
    assert_eq!(app.cursors.quefrency_seconds, retained.quefrencies);
    verify_notes(app, ctx, target);
    if let Some(hold) = &retained.hold {
        let actual = app.spectrogram_hold.as_ref().expect("Hold was released");
        assert!(Arc::ptr_eq(actual, hold)); // Immutable original f64 frames/conditions/losses.
        if plot_visible && !Arc::ptr_eq(&app.spectrogram_snapshot, hold) {
            return false;
        }
        for (actual, before) in app.spectrogram_selected.iter().zip(&retained.selected) {
            assert!(match (actual, before) {
                (Some(a), Some(b)) => Arc::ptr_eq(a, b),
                (None, None) => true,
                _ => false,
            });
        }
    }
    // Numerical history can arrive before the desktop raster. A blank
    // "collecting" placeholder must never satisfy a retained-image review.
    if plot_visible
        && app.spectrogram_snapshot.latest().is_some()
        && (app.spectrogram_history.lock().unwrap().is_empty()
            || app.spectrogram_prepared_id != app.spectrogram_view_worker.current_id())
    {
        return false;
    }
    if !target.starts_with("menu-")
        && !target.starts_with("tooltip-")
        && !target.contains("details")
        && target != "cepstral-display"
        && target != "color-error"
    {
        assert_visible(
            ctx,
            if app.running() {
                i18n::text("io.stop_input")
            } else {
                i18n::text("io.start_input")
            },
        );
        assert_visible(ctx, i18n::text("generator.stop_output_2"));
        if let Some(row) = app.spectrogram_snapshot.latest() {
            let snapshot = &app.spectrogram_snapshot;
            let state = if !app.running() {
                i18n::text("spectrogram.hold_input_stopped")
            } else if app.spectrogram_hold.is_some() {
                i18n::text("spectrogram.hold_input_running")
            } else {
                i18n::text("spectrogram.live")
            };
            let label = i18n::format(
                "spectrogram.end_s_s_retained_n_hop",
                &[
                    ("live", state),
                    (
                        "sample_rate",
                        &format!(
                            "{:.3}",
                            app.spectrogram_anchor as f64 / row.info.config.sample_rate as f64
                        ),
                    ),
                    (
                        "retained_seconds",
                        &format!("{:.2}", snapshot.retained_seconds()),
                    ),
                    ("size", &row.info.config.size.to_string()),
                    ("hop", &row.info.config.hop.to_string()),
                    (
                        "else",
                        if snapshot.capacity_limited {
                            i18n::text("spectrogram.history_limited_by_capacity")
                        } else {
                            ""
                        },
                    ),
                ],
            );
            if app.running() && app.spectrogram_hold.is_none() {
                assert_status(ctx, state);
            } else {
                assert_visible(ctx, label.as_ref());
            }
            if !target.contains("cepstral") && !matches!(target, "invalid" | "gap") {
                assert!(row.valid());
                assert!((row.power()[42] - 10.0_f64.powf(-1.8)).abs() < 1e-9);
            }
        } else {
            assert_visible(
                ctx,
                if app.running() {
                    i18n::text("spectrogram.collecting_a_complete_stft_window")
                } else {
                    i18n::text("spectrogram.start_input_to_begin_acquisition")
                },
            );
        }
        if matches!(target, "error" | "error-empty") {
            assert_visible(ctx, "I6d simulated input error (internal Generator)");
        }
        if target == "source-pending" {
            assert_visible(
                ctx,
                i18n::format("common.unavailable", &[("selected", &channel::name(15))]).as_ref(),
            );
            assert_eq!(app.spectrogram_snapshot.config.unwrap().channel, 0);
        }
        if target == "before-input" {
            assert_visible(
                ctx,
                i18n::format(
                    "spectrogram.no_stft_row_before_input_began",
                    &[("index", "A")],
                )
                .as_ref(),
            );
        }
        if target == "outside" {
            assert!(app.spectrogram_selected[0].is_some());
        }
    }
    true
}

// The panel requests a newer raster after painting its status. Live snapshot
// counters can advance in that same frame; verify the actual painted status
// and its full bounds without demanding newer counters retroactively.
fn assert_status(ctx: &egui::Context, state: &str) {
    let layers: Vec<_> = ctx.memory(|m| m.layer_ids().collect());
    let viewport = ctx.content_rect();
    let prefix = format!("{state} ·");
    assert!(
        ctx.graphics(|graphics| layers
            .into_iter()
            .filter_map(|layer| graphics.get(layer))
            .flat_map(|list| list.all_entries())
            .any(|shape| {
                if let egui::Shape::Text(text) = &shape.shape {
                    let bounds = text.visual_bounding_rect();
                    text.galley.text().starts_with(&prefix)
                        && shape.clip_rect.contains_rect(bounds)
                        && viewport.contains_rect(bounds)
                } else {
                    false
                }
            })),
        "Spectrogram state missing or clipped: {state}"
    );
}

fn verify_notes(app: &ScopeApp, ctx: &egui::Context, target: &str) {
    let notes: Vec<_> = (0..3usize)
        .filter_map(|index| {
            ctx.data(|data| {
                data.get_temp::<(egui::Rect, String)>(egui::Id::unique((
                    "qa_spectrogram_note",
                    index,
                )))
            })
        })
        .collect();
    let expected = match target {
        "before-input" => 1,
        "cursors" | "time-only" | "outside" | "invalid" | "gap" | "tooltip-placed" => 2,
        "cepstral-held" | "cepstral-silence" | "cepstral-invalid" => 3,
        _ => 0,
    };
    assert_eq!(notes.len(), expected, "Missing cursor readout: {target}");
    for (index, (bounds, text)) in notes.iter().enumerate() {
        assert_visible(ctx, text);
        for (other, _) in &notes[..index] {
            assert!(
                !bounds.expand(1.0).intersects(other.expand(1.0)),
                "History cursor readouts overlap: {target}"
            );
        }
    }
    match target {
        "invalid" => {
            let row = app.spectrogram_selected[0].as_ref().unwrap().info;
            assert_eq!(
                notes[0].1,
                i18n::format(
                    "spectrogram.invalid_stft_window_non_finite_input",
                    &[
                        ("index", "A"),
                        ("start", &row.start.to_string()),
                        ("end", &row.end.to_string())
                    ]
                )
                .as_ref()
            );
        }
        "gap" => {
            let sample = app.cursors.times[0].unwrap().spectrogram_sample().unwrap();
            let age = cursor::signed_distance(app.spectrogram_anchor - 1, sample)
                / app.sample_rate as f64;
            assert_eq!(
                notes[0].1,
                i18n::format(
                    "spectrogram.s_no_stft_row_gap_or_unavailable",
                    &[("index", "A"), ("age", &format!("{age:.3}"))]
                )
                .as_ref()
            );
        }
        "outside" => assert!(
            notes[0]
                .1
                .ends_with(i18n::text("spectrogram.outside_visible_time_range"))
        ),
        "cepstral-silence" => assert!(notes[0].1.contains(i18n::text("spectrogram.no_signal"))),
        "cepstral-invalid" => assert!(notes[0].1.contains(i18n::text("spectrogram.non_finite"))),
        _ => {}
    }
}
