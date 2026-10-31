//! I6d Spectrum inventory: real internal input/FFT, retained f64 results,
//! dedicated menus and every Spectrum hover description. No physical streams.
use super::*;

pub(super) struct Retained {
    document: Option<export::Document>,
    traces: [crate::spectrum::Result; 4],
    history: [crate::spectrum::Result; 2],
}

impl Retained {
    pub(super) fn new(app: &ScopeApp) -> Result<Self, String> {
        Ok(Self {
            document: (!app.running() && app.held_input.is_some())
                .then(|| app.capture_held_results(true))
                .transpose()?,
            traces: std::array::from_fn(|i| app.spectrum_result(i).clone()),
            history: app.spectrum_history.results.clone(),
        })
    }
}

fn assert_result(actual: &crate::spectrum::Result, before: &crate::spectrum::Result) {
    assert_eq!(actual.settings(), before.settings());
    assert_eq!(actual.validity(), before.validity());
    assert_eq!(actual.window(), before.window());
    assert_eq!(actual.average(), before.average());
    assert_eq!(actual.hold_info(), before.hold_info());
    assert_eq!(actual.power(), before.power());
    assert_eq!(actual.hold_power(), before.hold_power());
}

fn prepare(app: &mut ScopeApp, target: &str) -> Result<(), String> {
    assert!(app.core.is_none() && !app.running() && app.generator.stopped());
    app.presentation = Presentation::default();
    app.presentation
        .apply(Action::OpenSingle(Instrument::Spectrum));
    app.shell = shell::Shell::default();
    app.source = Source::Generator;
    app.demo_enabled = false;
    app.core = Some(measurement::Worker::new(app.stft.take_feeder()));
    app.acquisition_mode = acquisition::Mode::Auto;
    app.spectrum_settings = Settings {
        size: if target == "filling" { 524288 } else { 2048 },
        averages: 4,
        ..Settings::default()
    };
    app.spectrum_display = settings::SpectrumDisplay {
        enabled: [true, !matches!(target, "invalid" | "filling"), false, false],
        ..Default::default()
    };
    app.spectrum_mode = SpectrumMode::Continuous;
    app.show_hold = true;
    if matches!(target, "psd" | "tooltip-band" | "details-band") {
        app.spectrum_settings.select_quantity(Quantity::Psd);
    } else if matches!(target, "esd" | "esd-window" | "tooltip-energy") {
        app.spectrum_settings.select_quantity(Quantity::Esd);
        if target == "esd-window" {
            app.spectrum_settings.window = Window::Hann;
        }
    }
    if matches!(target, "invalid" | "tooltip-calibration") {
        app.calibration.pending = app.calibration.pending.with(
            0,
            Some(Calibration::new(
                "i6d-synthetic".into(),
                1,
                if target == "invalid" { f64::MAX } else { 2.0 },
                0.0,
                "V".into(),
                "Synthetic GUI fixture".into(),
            )?),
        )?;
    }
    let mut signals = generator::Settings::default();
    for signal in &mut signals.signals {
        signal.enabled = true;
        signal.frequency_hz = 984.375; // Exact bin 42 at 48 kHz / 2048.
        signal.amplitude_dbfs = -18.0;
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
    if target != "error-empty" {
        driver.click(app, i18n::text("io.start_input"))?;
        scope::wait(app, |app| {
            if target == "invalid" {
                app.analyzer.validity() == crate::spectrum::Validity::NonFinite
            } else if target == "filling" {
                !app.history.is_empty()
            } else {
                app.analyzer.is_ready()
                    && app.spectrum_result(1).is_ready()
                    && (!(target.starts_with("history-") || target == "tooltip-history-cursor")
                        || app.stft_history.snapshot().frames().count() >= 3)
            }
        })?;
    }
    if matches!(target, "error" | "error-empty") {
        app.fail_input("I6d simulated input error (internal Generator)".into());
        scope::wait(app, |app| app.pending_stop.is_none())?;
        assert!(app.input_error.is_some());
    } else if !matches!(
        target,
        "live" | "filling" | "tooltip-reset" | "history-live"
    ) {
        driver.frame(app, vec![]);
        driver.click(app, i18n::text("io.stop_input"))?;
        scope::wait(app, |app| app.pending_stop.is_none())?;
    }
    if target == "stopped" {
        driver.frame(app, vec![]);
        driver.click(app, i18n::text("generator.stop_output_2"))?;
        scope::wait(app, |app| app.generator.stopped())?;
    }
    if target == "unavailable" || target == "tooltip-unavailable" {
        app.spectrum_display.selected = 2;
    }
    if target == "all-off" {
        app.spectrum_display.enabled.fill(false);
    }
    if target.starts_with("history-") || target == "tooltip-history-cursor" {
        app.presentation
            .apply(Action::PairWith(Instrument::Spectrogram));
        app.presentation
            .apply(Action::FocusPane(Instrument::Spectrum));
        app.presentation.console.layout = Layout::Tabs;
        app.spectrogram_snapshot = app.stft_history.snapshot();
        app.spectrogram_anchor = app
            .spectrogram_snapshot
            .latest()
            .ok_or("Missing STFT history")?
            .info
            .end;
        app.hold_spectrogram();
        if target != "history-empty" {
            let samples: Vec<_> = app
                .spectrogram_snapshot
                .frames()
                .take(2)
                .map(|frame| frame.info.end - 1)
                .collect();
            for (i, sample) in samples.into_iter().enumerate() {
                app.select_spectrogram_sample(i, sample);
            }
        }
        app.link_spectrum_history();
        assert!(!app.can_export() && (app.running() || app.can_export_scope()));
    }
    app.dirty = true;
    app.spectrum_dirty = true;
    app.spectrum_numeric_key = None;
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
    let hover_key = match target {
        "tooltip-amplitude" => Some((
            i18n::text("spectrum.amplitude"),
            i18n::text("spectrum.bin_amplitude_dbfs_fs_peak_sine_at_a_bin"),
        )),
        "tooltip-psd" => Some((
            i18n::text("spectrum.psd"),
            i18n::text("spectrum.power_spectral_density_power_per_hz_with_window_noise"),
        )),
        "tooltip-esd" => Some((
            i18n::text("spectrum.quantity.esd"),
            i18n::text("spectrum.energy_spectral_density_energy_per_hz_selecting_esd_presets"),
        )),
        "tooltip-average" => Some((
            i18n::text("spectrum.average"),
            i18n::text("spectrum.exponential_average_of_linear_power_off_uses_the_latest"),
        )),
        "tooltip-reset" => Some((
            i18n::text("spectrum.reset"),
            i18n::text("spectrum.reset_averaging_and_peak_hold_for_all_spectrum_traces"),
        )),
        "tooltip-reset-disabled" => Some((
            i18n::text("spectrum.reset"),
            i18n::text("spectrum.reset_requires_running_input"),
        )),
        "tooltip-live" => Some((
            i18n::text("spectrum.live_observe_newest_window"),
            i18n::text("spectrum.observe_the_newest_complete_window_with_a_processing_time"),
        )),
        "tooltip-latest" => Some((
            i18n::text("spectrum.latest_observe_at_a_limited_rate"),
            i18n::text("spectrum.newest_complete_window_only_intermediate_windows_can_be_skipped"),
        )),
        "tooltip-dc" => Some((
            i18n::text("spectrum.remove_dc_offset"),
            i18n::text("spectrum.subtracts_each_window_s_mean_before_windowing_in_esd"),
        )),
        "tooltip-clear" => Some((
            i18n::text("common.clear_cursors"),
            i18n::text("spectrum.clear_both_frequency_cursors_shared_by_spectrum_and_spectrogram"),
        )),
        _ => None,
    };
    let advanced = matches!(
        target,
        "tooltip-live"
            | "tooltip-latest"
            | "tooltip-dc"
            | "tooltip-precision"
            | "tooltip-interval"
            | "menu-precision"
            | "details-diagnostics"
    );
    let details = hover_key.is_some()
        || advanced
        || matches!(
            target,
            "tooltip-cursor-a" | "tooltip-cursor-b" | "tooltip-ema" | "esd-window"
        )
        || target.starts_with("menu-")
        || target.starts_with("details-");
    if details {
        app.presentation.details_visible = true;
        app.shell.narrow_details = true;
    }
    if advanced {
        case.steps.push(Step::ScrollTo(
            i18n::text("spectrum.advanced_analysis_diagnostics").into(),
        ));
        case.steps.push(Step::Click(
            i18n::text("spectrum.advanced_analysis_diagnostics").into(),
        ));
    }
    if let Some((label, help)) = hover_key {
        let scroll_label = if target == "tooltip-average" {
            i18n::text("spectrum.ema_settling")
        } else {
            label
        };
        case.steps.push(Step::ScrollTo(scroll_label.into()));
        case.steps.push(if target == "tooltip-average" {
            Step::HoverControl(egui::Id::unique("qa_spectrum_average"))
        } else {
            Step::HoverText(label.into())
        });
        case.labels.push(help.into());
        return Ok(case);
    }
    match target {
        "live" | "held" | "stopped" | "error" | "error-empty" | "filling" | "invalid"
        | "all-off" | "unavailable" | "psd" | "esd" | "history-live" | "history-held"
        | "history-empty" => {}
        "esd-window" => {
            let label = i18n::text(
                "spectrum.rectangular_recommended_other_windows_attenuate_energy_without_correction",
            );
            case.steps.push(Step::ScrollTo(label.into()));
            case.labels.push(label.into());
        }
        "tooltip-channel" | "tooltip-unavailable" => {
            let index = if target == "tooltip-unavailable" {
                2usize
            } else {
                0usize
            };
            case.steps.push(Step::HoverControl(egui::Id::unique((
                "qa_spectrum_channel",
                index,
            ))));
            case.labels.push(
                i18n::format(
                    "spectrum.ch_input_select_for_peak_cursor_and_export_display",
                    &[
                        ("index", &(index + 1).to_string()),
                        ("source", &(app.spectrum_source(index) + 1).to_string()),
                        ("db_unit", &app.spectrum_result(index).db_unit()),
                    ],
                )
                .to_string(),
            );
        }
        "tooltip-toggle" => {
            case.steps.push(Step::HoverControl(egui::Id::unique((
                "qa_spectrum_toggle",
                0usize,
            ))));
            case.labels
                .push(i18n::format("spectrum.show_ch_spectrum", &[("index", "1")]).to_string());
        }
        "tooltip-cursor-a" | "tooltip-cursor-b" => {
            let label = if target.ends_with('a') { "A" } else { "B" };
            case.steps
                .push(Step::ScrollTo(i18n::text("spectrum.place_cursor").into()));
            case.steps.push(Step::HoverText(label.into()));
            case.labels.push(
                i18n::text("spectrum.choose_which_cursor_the_next_spectrum_click_or_drag").into(),
            );
        }
        "tooltip-ema" => {
            case.steps
                .push(Step::ScrollTo(i18n::text("spectrum.ema_settling").into()));
            case.steps
                .push(Step::HoverText(i18n::text("spectrum.ema_settling").into()));
            case.labels.push(
                i18n::format(
                    "spectrum.exponential_power_average_approximately_settled_after_weight_windows",
                    &[("averages", "4")],
                )
                .to_string(),
            );
        }
        "tooltip-precision" => {
            let label = app.spectrum_settings.precision.display_name();
            case.steps.push(Step::ScrollTo(label.into()));
            case.steps.push(Step::HoverText(label.into()));
            case.labels.push(
                i18n::text("common.only_this_instrument_s_fft_changes_precision_input_history")
                    .into(),
            );
        }
        "tooltip-interval" => {
            let w = app.analyzer.window().ok_or("Missing FFT window")?;
            let label = i18n::format(
                "spectrum.fft_end_acquired_end",
                &[
                    ("end", &w.end.to_string()),
                    ("end_2", &app.history.range().end.to_string()),
                ],
            )
            .to_string();
            case.steps.push(Step::ScrollTo(label.clone()));
            case.steps.push(Step::HoverText(label));
            case.labels.push(
                i18n::text("spectrum.spectrum_and_scope_xy_have_independent_sample_intervals_fft")
                    .into(),
            );
        }
        "tooltip-energy" => {
            case.steps
                .push(Step::HoverControl(egui::Id::unique("qa_spectrum_energy")));
            case.labels
                .push(i18n::text("spectrum.sum_of_f64_esd_f_over_all_bins_including").into());
        }
        "tooltip-calibration" => {
            case.steps.push(Step::HoverControl(egui::Id::unique(
                "qa_spectrum_calibration",
            )));
            case.labels
                .push(spectrum_calibration_description(app.analyzer.calibration()));
        }
        "tooltip-band" => {
            app.refresh_spectrum_readouts(app.spectrum_view());
            let band = app.spectrum_band.as_ref().ok_or("Missing PSD band")?;
            case.steps
                .push(Step::HoverControl(egui::Id::unique("qa_spectrum_band")));
            case.labels.push(
                i18n::format(
                    "spectrum.requested_hz_inclusive_centres_of_bins_sum_of_f64",
                    &[
                        ("requested_hz", &band.requested_hz[0].to_string()),
                        ("requested_hz_2", &band.requested_hz[1].to_string()),
                        ("first_bin", &band.first_bin.to_string()),
                        ("last_bin", &band.last_bin.to_string()),
                        ("channel", &(band.window.channel + 1).to_string()),
                        ("input_generation", &app.input_generation.to_string()),
                        ("updates", &band.average.updates.to_string()),
                        ("start", &band.average.start.to_string()),
                        ("end", &band.average.end.to_string()),
                        ("dropped", &app.dropped.to_string()),
                        (
                            "missing_windows",
                            &app.spectrum_info.missing_windows.to_string(),
                        ),
                    ],
                )
                .to_string(),
            );
        }
        "history-details" => {
            app.presentation.details_visible = true;
            app.shell.narrow_details = true;
            let label = spectrum_history::export_reason();
            case.steps.push(Step::ScrollTo(label.into()));
            case.labels.push(label.into());
        }
        "tooltip-history-cursor" => {
            app.cursors.set_frequency(0, 984.375);
            let reading = app
                .shown_selected_spectrum()
                .cursor(984.375)
                .ok_or("Missing history reading")?;
            let w = &reading.window;
            case.steps
                .push(Step::HoverControl(egui::Id::unique("qa_spectrum_plot")));
            case.labels.push(
                i18n::format(
                    "spectrum.time_nearest_bin_acquired_samples_hz_points_no_average",
                    &[
                        ("selected", "A"),
                        ("value", &format!("{:.6e}", reading.value)),
                        ("linear_unit", &w.linear_unit()),
                        ("start", &w.start.to_string()),
                        ("end", &w.end.to_string()),
                        ("sample_rate", &w.sample_rate.to_string()),
                        ("size", &w.settings.size.to_string()),
                        ("name", w.settings.window.display_name()),
                        ("name_2", w.settings.precision.display_name()),
                    ],
                )
                .to_string(),
            );
        }
        "tooltip-cursor" | "tooltip-cursor-times" => {
            app.cursors.set_frequency(0, 984.375);
            app.cursors.set_frequency(1, 1968.75);
            let reading = app
                .analyzer
                .cursor(984.375)
                .ok_or("Missing cursor reading")?;
            let w = &reading.window;
            let times = if target == "tooltip-cursor-times" {
                app.cursors.set_time(0, w.start);
                app.cursors.set_time(1, w.end);
                format!(
                    "{}{}",
                    i18n::format("spectrum.time_cursor_inside_fft_window", &[("index", "A")]),
                    i18n::format("spectrum.time_cursor_outside_fft_window", &[("index", "B")])
                )
            } else {
                String::new()
            };
            case.steps
                .push(Step::HoverControl(egui::Id::unique("qa_spectrum_plot")));
            // Both descriptions are attached to the same plot response.
            case.labels.push(
                i18n::format(
                    "spectrum.cursor_nearest_bin_latest_window_samples_exclusive_end_ch",
                    &[
                        ("index", "A"),
                        ("value", &format!("{:.6e}", reading.value)),
                        ("linear_unit", &w.linear_unit()),
                        ("start", &w.start.to_string()),
                        ("end", &w.end.to_string()),
                        ("channel", &(w.channel + 1).to_string()),
                        ("sample_rate", &w.sample_rate.to_string()),
                        ("size", &w.settings.size.to_string()),
                        ("name", w.settings.window.display_name()),
                        ("name_2", w.settings.precision.display_name()),
                        ("averages", &w.settings.averages.to_string()),
                        ("updates", &reading.average.updates.to_string()),
                        ("start_2", &reading.average.start.to_string()),
                        ("end_2", &reading.average.end.to_string()),
                        ("input_generation", &app.input_generation.to_string()),
                        (
                            "missing_windows",
                            &app.spectrum_info.missing_windows.to_string(),
                        ),
                        ("times", &times),
                    ],
                )
                .to_string(),
            );
            case.labels.push(spectrum_calibration_description(None));
        }
        "menu-size" | "menu-size-large" | "menu-window" | "menu-span" | "menu-average"
        | "menu-precision" | "menu-source" => {
            let (label, labels) = match target {
                "menu-size" | "menu-size-large" => (
                    i18n::format(
                        "spectrum.points",
                        &[("size", &app.spectrum_settings.size.to_string())],
                    )
                    .to_string(),
                    FFT_SIZES
                        .into_iter()
                        .skip(if target == "menu-size-large" { 5 } else { 0 })
                        .take(5)
                        .map(|size| {
                            i18n::format("spectrum.points", &[("size", &size.to_string())])
                                .to_string()
                        })
                        .collect(),
                ),
                "menu-window" => (
                    app.spectrum_settings.window.display_name().into(),
                    [Window::Hann, Window::Rectangular, Window::BlackmanHarris]
                        .map(|w| w.display_name().into())
                        .to_vec(),
                ),
                "menu-span" => (
                    i18n::text("spectrum.full_nyquist").into(),
                    std::iter::once(i18n::text("spectrum.full_nyquist").to_owned())
                        .chain([1000.0, 2000.0, 5000.0, 10000.0, 20000.0].map(|hz| {
                            i18n::format("spectrum.span", &[("hz", &frequency_label(hz))])
                                .to_string()
                        }))
                        .collect(),
                ),
                "menu-average" => (
                    i18n::format("spectrum.weight_2", &[("average_weight", "4")]).to_string(),
                    [4, 16, 64]
                        .map(|count| {
                            i18n::format("spectrum.weight", &[("count", &count.to_string())])
                                .to_string()
                        })
                        .to_vec(),
                ),
                "menu-precision" => (
                    app.spectrum_settings.precision.display_name().into(),
                    [Precision::F64, Precision::F32]
                        .map(|p| p.display_name().into())
                        .to_vec(),
                ),
                _ => (channel::name(0), vec![channel::name(0), channel::name(1)]),
            };
            case.steps.push(Step::ScrollTo(label.clone()));
            case.steps.push(Step::Click(label));
            if target == "menu-size-large" {
                case.steps.push(Step::ScrollMenuTo(
                    i18n::format("spectrum.points", &[("size", "524288")]).to_string(),
                ));
            }
            case.labels = labels;
            case.popup = true;
        }
        "details-frequency" => {
            let label = i18n::text("spectrum.custom_frequency_range");
            case.steps.push(Step::ScrollTo(label.into()));
            case.steps.push(Step::Click(label.into()));
            case.labels.push(
                i18n::text("spectrum.to_uses_nyquist_narrow_ranges_show_individual_bins").into(),
            );
        }
        "details-band" => {
            let label = i18n::text("spectrum.power_in_band");
            case.steps.push(Step::ScrollTo(label.into()));
            case.steps.push(Step::Click(label.into()));
            case.steps.push(Step::ScrollTo(
                i18n::text("spectrum.to_uses_nyquist_inclusive_bin_centres_whole_bins_band").into(),
            ));
            case.labels.push(
                i18n::text("spectrum.to_uses_nyquist_inclusive_bin_centres_whole_bins_band").into(),
            );
        }
        "details-diagnostics" => {
            let label = i18n::text("spectrum.json_csv_png_use_the_selected_trace");
            case.steps.push(Step::ScrollTo(label.into()));
            case.labels.push(label.into());
        }
        _ => return Err(format!("Unknown Spectrum review: {target}")),
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
    if app.running() && (after.0 <= before.0 || (target != "filling" && after.1 <= before.1)) {
        return false;
    }
    if target != "stopped" && after.2 <= before.2 {
        return false;
    }
    if let Some(held) = &retained.document {
        let current = app
            .capture_held_results(true)
            .expect("Held Spectrum became unavailable");
        assert_eq!(current.input, held.input);
        assert_eq!(current.spectrum, held.spectrum);
        assert_eq!(current.scope, held.scope);
        assert_eq!(current.loss, held.loss);
        for (i, before) in retained.traces.iter().enumerate() {
            assert_result(app.spectrum_result(i), before);
        }
    }
    if app.spectrum_history.linked {
        assert!(!app.can_export() && (app.running() || app.can_export_scope()));
        for (actual, before) in app.spectrum_history.results.iter().zip(&retained.history) {
            assert_result(actual, before);
        }
    }
    if !target.starts_with("tooltip-")
        && !target.starts_with("menu-")
        && !target.starts_with("details-")
        && !matches!(target, "esd-window" | "history-details")
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
        assert_visible(
            ctx,
            display::activity(
                app.running() && !app.spectrum_history.linked,
                false,
                app.shown_selected_spectrum().window().is_some(),
            )
            .0,
        );
        match target {
            "error" | "error-empty" => {
                assert_visible(ctx, "I6d simulated input error (internal Generator)")
            }
            "invalid" => {
                assert_eq!(
                    app.analyzer.validity(),
                    crate::spectrum::Validity::NonFinite
                );
                assert_visible(ctx, i18n::text("common.invalid_fft_window_nonfinite_value"));
            }
            "filling" => {
                assert!(!app.analyzer.is_ready());
                assert_visible(ctx, i18n::text("common.collecting_a_complete_fft_window"));
            }
            "history-live" | "history-held" | "history-empty" => {
                assert_visible(ctx, i18n::text("spectrum.history_read_only"));
                assert_visible(ctx, i18n::text("spectrum.normal_spectrum"));
                if target == "history-empty" {
                    assert_visible(
                        ctx,
                        i18n::text("spectrum.select_a_time_frame_in_spectrogram"),
                    );
                }
            }
            "all-off" => assert_visible(ctx, i18n::text("common.all_channels_off")),
            "unavailable" => assert_visible(ctx, i18n::text("spectrum.no_input")),
            _ => {}
        }
    }
    true
}
