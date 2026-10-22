//! Captured synchronous results; display selection never schedules an FFT.
use super::*;

impl ScopeApp {
    #[cfg(feature = "qa")]
    pub(super) fn check_comparison_ui(&mut self, mode: &str) -> Result<(), String> {
        self.poll_audio();
        self.core = Some(measurement::Worker::new(self.stft.take_feeder()));
        self.source = Source::Software;
        self.demo_enabled = false;
        self.loopback_settings = loopback::Settings {
            frequency_hz: 750.0,
            ..Default::default()
        };
        self.comparison_settings = comparison::Settings {
            enabled: true,
            size: 4096,
            averages: 4,
            ..Default::default()
        };
        self.lockin_settings = lockin::Settings {
            enabled: true,
            frequency_hz: 750.0,
            ..Default::default()
        };
        self.spectrum_settings.size = 4096;
        self.spectrum_settings.window = Window::Rectangular;
        self.comparison_frequency_hz = 750.0;
        self.acquisition_mode = acquisition::Mode::Auto;
        self.start();
        let deadline = Instant::now() + Duration::from_secs(10);
        while self.comparison_result.state != comparison::State::Valid {
            self.poll_measurement();
            if Instant::now() > deadline {
                return Err("Comparison UI input timed out".into());
            }
            std::thread::sleep(Duration::from_millis(5));
        }
        // A live pair change must clear the old average and invert the transfer.
        let before = self.comparison_settings;
        self.comparison_settings.reference_channel = 1;
        self.comparison_settings.response_channel = 0;
        self.apply_comparison_controls(before);
        let deadline = Instant::now() + Duration::from_secs(10);
        while self.comparison_result.settings != self.comparison_settings
            || self.comparison_result.state != comparison::State::Valid
        {
            self.poll_measurement();
            if Instant::now() > deadline {
                return Err("Live comparison routing timed out".into());
            }
            std::thread::sleep(Duration::from_millis(5));
        }
        assert!((self.comparison_result.bins[64].gain.unwrap() - 2.0).abs() < 1e-9);
        assert!((self.comparison_result.bins[64].phase_lead_degrees.unwrap() + 30.0).abs() < 1e-7);
        self.comparison_settings = before;
        self.core.as_ref().unwrap().configure_comparison(before);
        let deadline = Instant::now() + Duration::from_secs(10);
        while self.comparison_result.settings != before
            || self.comparison_result.state != comparison::State::Valid
        {
            self.poll_measurement();
            if Instant::now() > deadline {
                return Err("Comparison original routing timed out".into());
            }
            std::thread::sleep(Duration::from_millis(5));
        }
        self.stop();
        let mut snapshot = self
            .pending_stop
            .take()
            .ok_or("Missing comparison stop")?
            .wait();
        self.accept_snapshot(&mut snapshot);
        let held = self.comparison_result.clone();
        let b = &held.bins[64];
        assert!((b.gain.unwrap() - 0.5).abs() < 1e-9);
        assert!((b.phase_lead_degrees.unwrap() - 30.0).abs() < 1e-7);
        assert!(held.delay.is_none());
        self.select_view([mode == "pair", false, false, false]);
        self.qa_show(Instrument::Comparison);
        self.presentation.details_visible = mode == "narrow";
        let settings = self.capture_settings()?;
        let doc = self.capture_results()?;
        doc.validate()?;
        std::fs::create_dir_all("dist/comparison-qa").map_err(|e| e.to_string())?;
        export::save(
            std::path::Path::new("dist/comparison-qa/ui-results.json"),
            &doc,
        )?;
        crate::results::save_csv(
            std::path::Path::new("dist/comparison-qa/ui-results.csv"),
            &doc,
        )?;
        let loaded =
            crate::results::load(std::path::Path::new("dist/comparison-qa/ui-results.json"))?;
        assert_eq!(loaded.comparison, doc.comparison);
        let before = self.comparison_settings;
        self.comparison_settings.response_channel = 0;
        self.comparison_settings.reference_channel = 1;
        self.apply_comparison_controls(before);
        assert_eq!(self.comparison_result, held);
        self.restore_settings(settings::Document::decode(&settings.encode()?)?)?;
        assert!(!self.running());
        self.start();
        let deadline = Instant::now() + Duration::from_secs(10);
        while self.comparison_result.state != comparison::State::Valid {
            self.poll_measurement();
            if Instant::now() > deadline {
                return Err("Comparison remeasurement timed out".into());
            }
            std::thread::sleep(Duration::from_millis(5));
        }
        self.stop();
        let mut snapshot = self
            .pending_stop
            .take()
            .ok_or("Missing remeasurement stop")?
            .wait();
        self.accept_snapshot(&mut snapshot);
        let current = self.capture_results()?;
        let difference = crate::results::comparison_difference(&loaded, &current, 64)
            .ok_or("Comparison conditions differ after restore")?;
        assert!(difference.gain.abs() < 1e-9 && difference.phase_degrees.abs() < 1e-7);
        match std::env::var("MEASURELAB_UI_SMOKE_COMPARISON_AXIS").as_deref() {
            Ok("log") => self.comparison_display.log = true,
            Ok("full") => self.comparison_display.span = Span::Full,
            Ok("custom") => {
                self.comparison_display.span = Span::Custom;
                self.comparison_display.from_hz = 700.0;
                self.comparison_display.to_hz = 800.0;
            }
            _ => {}
        }
        self.created = Instant::now();
        println!(
            "Comparison UI QA OK: {mode}; normal software input; finite stop; JSON/CSV; stopped edit; OFF restore and new-generation remeasurement; gain/phase match"
        );
        Ok(())
    }
    pub(super) fn comparison_controls(&mut self, ui: &mut egui::Ui) {
        let before = self.comparison_settings;
        let channels = self.lockin_channel_count();
        ui.add_enabled_ui(
            !self.busy && self.pending_stop.is_none() && !self.workspace_restoring,
            |ui| {
                comparison_controls(ui, &mut self.comparison_settings, channels);
            },
        );
        self.apply_comparison_controls(before);
        ui.label(
            RichText::new(i18n::text(
                "comparison.ac_comparison_positive_phase_leads_ref_positive_delay_lags",
            ))
            .small()
            .color(MUTED),
        );
    }
    pub(super) fn apply_comparison_controls(&mut self, before: comparison::Settings) {
        if before == self.comparison_settings {
            return;
        }
        if let Err(error) = self.comparison_settings.validate(self.sample_rate) {
            self.comparison_settings = before;
            self.error = Some(error);
        } else if self.running()
            && let Some(core) = &self.core
        {
            core.configure_comparison(self.comparison_settings);
        }
    }
    fn comparison_primary_controls(&mut self, ui: &mut egui::Ui) {
        let before = self.comparison_settings;
        let channels = self.lockin_channel_count();
        ui.horizontal_wrapped(|ui| {
            ui.add_enabled_ui(
                !self.busy && self.pending_stop.is_none() && !self.workspace_restoring,
                |ui| {
                    ui.label(i18n::text("comparison.ref"));
                    channel_select(
                        ui,
                        "comparison_ref_primary",
                        &mut self.comparison_settings.reference_channel,
                        channels,
                    );
                    ui.label(i18n::text("comparison.sig"));
                    channel_select(
                        ui,
                        "comparison_signal_primary",
                        &mut self.comparison_settings.response_channel,
                        channels,
                    );
                    if ui
                        .button(if self.comparison_settings.enabled {
                            i18n::text("comparison.stop_analysis")
                        } else {
                            i18n::text("comparison.start_analysis")
                        })
                        .clicked()
                    {
                        self.comparison_settings.enabled = !self.comparison_settings.enabled;
                    }
                },
            );
            ui.label(
                RichText::new(self.analysis_state(self.comparison_settings.enabled))
                    .small()
                    .color(MUTED),
            );
        });
        self.apply_comparison_controls(before);
    }

    pub(super) fn comparison_panel(&mut self, ui: &mut egui::Ui) {
        egui::Frame::new().fill(Color32::from_rgb(17,27,35)).stroke(Stroke::new(1.0,BORDER))
            .inner_margin(8.0).show(ui, |ui| {
                ui.horizontal_wrapped(|ui| {
                    ui.label(RichText::new(i18n::text("comparison.synchronous_comparison")).strong().color(BLUE));
                    display::activity_label(ui, self.running(), self.pending_stop.is_some(), !self.comparison_result.sample_range.is_empty());

                });
                self.comparison_primary_controls(ui);
                let r = Arc::clone(&self.comparison_result);
                let s = r.settings;
                let state_color = match r.state {
                    comparison::State::Valid => GREEN,
                    comparison::State::Filling | comparison::State::Averaging => YELLOW,
                    comparison::State::Disabled => MUTED,
                    _ => TRIGGER,
                };
                ui.label(RichText::new(i18n::format("comparison.ref_ch_sig_ch_n_f_hz", &[("state", r.state.display_name()), ("reference_channel", &(s.reference_channel+1).to_string()), ("response_channel", &(s.response_channel+1).to_string()), ("size", &(s.size).to_string()), ("averages", &(s.averages).to_string()), ("bin_width_hz", &format!("{:.3}", r.bin_width_hz()))]).as_ref()).small().color(state_color));
                if !self.running() && s != self.comparison_settings {
                    ui.label(RichText::new(i18n::text("comparison.held_conditions_retained_queued_analysis_settings_apply_on_next")).small().color(YELLOW));
                }
                ui.horizontal_wrapped(|ui| {
                    ui.label(i18n::text("comparison.read_at"));
                    ui.add(egui::DragValue::new(&mut self.comparison_frequency_hz).range(0.0..=r.nominal_sample_rate_hz as f64*0.5).speed(r.bin_width_hz()).max_decimals(3).suffix(" Hz"));
                    if let Some((k,b)) = r.bin_at(self.comparison_frequency_hz) {
                        ui.label(RichText::new(i18n::format("comparison.bin_hz", &[("k", &(k).to_string()), ("bin_width_hz", &format!("{:.3}", k as f64*r.bin_width_hz())), ("state", b.state.display_name())]).as_ref()).small().color(if b.state == comparison::BinState::Valid { MUTED } else { YELLOW }));
                    } else { ui.label(RichText::new(self.comparison_wait_help(&r)).small().color(MUTED)); }
                });
                let reading = r.bin_at(self.comparison_frequency_hz).map(|(_,b)| b);
                let ref_unit = self.calibration.captured.unit(s.reference_channel);
                let sig_unit = self.calibration.captured.unit(s.response_channel);
                let unit = if ref_unit==sig_unit {"ratio".into()} else {format!("{sig_unit}/{ref_unit}")};
                ui.horizontal_wrapped(|ui| {
                    display::metric(ui, i18n::text("comparison.gain"), reading.and_then(|b| b.gain), &unit, GREEN);
                    display::metric(ui, i18n::text("comparison.phase_lead"), reading.and_then(|b| b.phase_lead_degrees), "°", BLUE);
                    display::metric(ui, i18n::text("comparison.coherence"), reading.and_then(|b| b.coherence), "", YELLOW);
                    display::metric(ui, i18n::text("comparison.wrapped_delay"), reading.and_then(|b| b.phase_delay_seconds).map(|v| v*1e6), "µs", BLUE);
                });
                if let Some(d) = &r.delay {
                    ui.label(i18n::format("comparison.phase_slope_s_hz_residual_rms", &[("e6", &(display::number(Some(d.seconds*1e6))).to_string()), ("bin_width_hz", &format!("{:.1}", d.inclusive_bins[0] as f64*r.bin_width_hz())), ("bin_width_hz_2", &format!("{:.1}", d.inclusive_bins[1] as f64*r.bin_width_hz())), ("phase_residual_rms_degrees", &(display::number(Some(d.phase_residual_rms_degrees))).to_string())]).as_ref());
                } else { ui.label(RichText::new(i18n::text("comparison.phase_slope_needs_contiguous_excited_coherent_bins")).small().color(MUTED)); }
                ui.label(RichText::new(i18n::text("comparison.nominal_fs_ch_phase_timing_calibration_unverified_delay_wraps")).small().color(YELLOW));
                self.comparison_display.controls(ui, r.nominal_sample_rate_hz as f64*0.5);
                let view = self.comparison_display.range(&r, self.comparison_frequency_hz);
                let valid = r.bins.iter().filter(|b| b.state == comparison::BinState::Valid).count();
                ui.label(RichText::new(i18n::format("comparison.valid_transfer_bins_gaps_are_not_interpolated", &[("valid", &(valid).to_string())]).as_ref()).small().color(MUTED));
                let h = ((ui.available_height()-32.0)/3.0).clamp(100.0,180.0);
                for plot in 0..3 { if let Some(hz) = comparison_plot(ui,&r,plot,h,self.comparison_frequency_hz,view) { self.comparison_frequency_hz=hz; } }
                egui::CollapsingHeader::new(i18n::text("comparison.captured_conditions")).id_salt("Captured conditions").show(ui, |ui| {
                    ui.label(i18n::format("comparison.input_generation_analysis_revision_hz_nominal_f64", &[("generation", &(r.generation).to_string()), ("analysis_revision", &(r.analysis_revision).to_string()), ("nominal_sample_rate_hz", &(r.nominal_sample_rate_hz).to_string())]).as_ref());
                    ui.label(i18n::format("comparison.samples_latest_input_end", &[("start", &(r.sample_range.start).to_string()), ("end", &(r.sample_range.end).to_string()), ("start_2", &(r.latest_window.start).to_string()), ("end_2", &(r.latest_window.end).to_string()), ("input_end", &(r.input_end).to_string())]).as_ref());
                    ui.label(i18n::format("comparison.averaged_windows_processed_missing_invalid_samples", &[("averaged_windows", &(r.averaged_windows).to_string()), ("processed_windows", &(r.processed_windows).to_string()), ("missing_samples", &(r.missing_samples).to_string()), ("invalid_samples", &(r.invalid_samples).to_string())]).as_ref());
                    ui.label(i18n::format("comparison.ac_mean_removed_disjoint_arithmetic_batches_ref_floor_fs", &[("name", (s.window.display_name())), ("reference_min_psd_fs2_hz", &(s.reference_min_psd_fs2_hz).to_string()), ("minimum_coherence", &(s.minimum_coherence).to_string())]).as_ref());
                    ui.label(i18n::text("comparison.h1_pxy_pxx_scope_spectrum_and_comparison_each_retain"));
                    for ch in [s.reference_channel,s.response_channel] { if let Some(c)=self.calibration.captured.get(ch) {ui.label(i18n::format("comparison.ch_revision_fs", &[("ch", &(ch+1).to_string()), ("id", (c.id())), ("revision", &(c.revision()).to_string()), ("gain", &(c.gain()).to_string()), ("unit", (c.unit()))]).as_ref());} }
                });
            });
    }

    fn comparison_wait_help(&self, result: &comparison::Result) -> &'static str {
        match result.state {
            comparison::State::Disabled => {
                i18n::text("comparison.select_ref_sig_channels_then_press_start_analysis")
            }
            comparison::State::Unavailable => {
                i18n::text("comparison.check_ref_sig_channels_fft_and_nominal_fs_settings")
            }
            comparison::State::Missing if self.running() => {
                i18n::text("comparison.input_gap_waiting_for_a_new_complete_average")
            }
            comparison::State::Missing => {
                i18n::text("comparison.input_gap_press_start_input_to_acquire_again")
            }
            comparison::State::NonFinite => {
                i18n::text("comparison.invalid_input_no_valid_comparison_is_available")
            }
            comparison::State::Valid => {
                i18n::text("comparison.selected_frequency_is_outside_the_captured_result")
            }
            comparison::State::Filling | comparison::State::Averaging => {
                if self.pending_stop.is_some() {
                    i18n::text("comparison.finishing_analysis_before_holding_the_result")
                } else if !self.running() {
                    i18n::text("comparison.press_start_input_to_acquire_a_complete_average")
                } else {
                    i18n::text("comparison.waiting_for_a_complete_average")
                }
            }
        }
    }
}
fn comparison_controls(ui: &mut egui::Ui, s: &mut comparison::Settings, _channels: u16) {
    setting_label(ui, i18n::text("comparison.window_averaging"));
    egui::ComboBox::from_id_salt("comparison_size")
        .selected_text(
            i18n::format("comparison.samples", &[("size", &(s.size).to_string())]).as_ref(),
        )
        .show_ui(ui, |ui| {
            for n in comparison::SIZES {
                ui.selectable_value(&mut s.size, n, n.to_string());
            }
        });
    egui::ComboBox::from_id_salt("comparison_window")
        .selected_text(s.window.display_name())
        .show_ui(ui, |ui| {
            for w in [Window::Rectangular, Window::Hann, Window::BlackmanHarris] {
                ui.selectable_value(&mut s.window, w, w.display_name());
            }
        });
    ui.add(
        egui::DragValue::new(&mut s.averages)
            .range(2..=256)
            .prefix(i18n::text("comparison.average_windows")),
    );
    ui.add(
        egui::DragValue::new(&mut s.minimum_coherence)
            .range(0.0..=1.0)
            .speed(0.01)
            .prefix(i18n::text("comparison.min_coherence")),
    );
    ui.add(
        egui::DragValue::new(&mut s.reference_min_psd_fs2_hz)
            .range(1e-30..=1.0)
            .speed(1e-13)
            .max_decimals(20)
            .prefix(i18n::text("comparison.min_ref"))
            .suffix(i18n::text("comparison.fs_hz")),
    );
    ui.add(
        egui::DragValue::new(&mut s.delay_band_hz[0])
            .range(0.0..=383999.0)
            .speed(10.0)
            .prefix(i18n::text("comparison.slope_from"))
            .suffix(" Hz"),
    );
    ui.add(
        egui::DragValue::new(&mut s.delay_band_hz[1])
            .range(1.0..=384000.0)
            .speed(10.0)
            .prefix(i18n::text("comparison.slope_to"))
            .suffix(" Hz"),
    );
}
#[derive(Clone, Copy, PartialEq, Eq)]
enum Span {
    Reading,
    Valid,
    Full,
    Custom,
}

pub(super) struct ComparisonDisplay {
    span: Span,
    log: bool,
    from_hz: f64,
    to_hz: f64,
}
impl Default for ComparisonDisplay {
    fn default() -> Self {
        Self {
            span: Span::Reading,
            log: false,
            from_hz: 0.0,
            to_hz: 2000.0,
        }
    }
}
impl ComparisonDisplay {
    fn controls(&mut self, ui: &mut egui::Ui, nyquist: f64) {
        ui.horizontal_wrapped(|ui| {
            ui.label(
                RichText::new(i18n::text("comparison.display_range"))
                    .small()
                    .color(MUTED),
            );
            egui::ComboBox::from_id_salt("comparison_span")
                .selected_text(match self.span {
                    Span::Reading => i18n::text("comparison.around_reading"),
                    Span::Valid => i18n::text("comparison.valid_band"),
                    Span::Full => i18n::text("comparison.full_nyquist"),
                    Span::Custom => i18n::text("comparison.custom"),
                })
                .show_ui(ui, |ui| {
                    for (span, label) in [
                        (Span::Reading, i18n::text("comparison.around_reading")),
                        (Span::Valid, i18n::text("comparison.valid_band")),
                        (Span::Full, i18n::text("comparison.full_nyquist")),
                        (Span::Custom, i18n::text("comparison.custom")),
                    ] {
                        ui.selectable_value(&mut self.span, span, label);
                    }
                });
            ui.selectable_value(&mut self.log, false, i18n::text("comparison.linear_hz"));
            ui.selectable_value(&mut self.log, true, i18n::text("comparison.log_hz"));
            if self.span == Span::Custom {
                ui.add(
                    egui::DragValue::new(&mut self.from_hz)
                        .range(0.0..=nyquist)
                        .speed(1.0)
                        .prefix(i18n::text("comparison.from"))
                        .suffix(" Hz"),
                );
                ui.add(
                    egui::DragValue::new(&mut self.to_hz)
                        .range(0.0..=nyquist)
                        .speed(1.0)
                        .prefix(i18n::text("comparison.to"))
                        .suffix(" Hz"),
                );
            }
        })
        .response
        .on_hover_text(i18n::text(
            "comparison.display_only_captured_analysis_validity_thresholds_and_the_phase",
        ));
    }
    fn range(&self, result: &comparison::Result, selected: f64) -> FrequencyRange {
        let nyquist = result.nominal_sample_rate_hz as f64 * 0.5;
        let bin = result.bin_width_hz();
        let focus = |low: f64, high: f64| {
            let padding = ((high - low) * 0.15)
                .max(bin * 8.0)
                .max((low + high) * 0.25);
            [(low - padding).max(0.0), (high + padding).min(nyquist)]
        };
        let [from, to] = match self.span {
            Span::Reading => {
                let selected = selected.clamp(0.0, nyquist);
                focus(selected, selected)
            }
            Span::Valid => {
                let mut bins = result
                    .bins
                    .iter()
                    .enumerate()
                    .filter(|(_, b)| b.state == comparison::BinState::Valid)
                    .map(|(k, _)| k as f64 * bin);
                if let Some(first) = bins.next() {
                    focus(first, bins.next_back().unwrap_or(first))
                } else {
                    [0.0, nyquist]
                }
            }
            Span::Full => [0.0, nyquist],
            Span::Custom => [self.from_hz, self.to_hz],
        };
        FrequencyRange::new(from, to, nyquist, bin, self.log)
    }
}

#[derive(Clone, Copy)]
struct FrequencyRange {
    from: f64,
    to: f64,
    log: bool,
}
impl FrequencyRange {
    fn new(from: f64, to: f64, nyquist: f64, bin: f64, log: bool) -> Self {
        let minimum = if log {
            bin.min(nyquist * 0.5).max(f64::MIN_POSITIVE)
        } else {
            0.0
        };
        let from = if from.is_finite() { from } else { 0.0 };
        let to = if to.is_finite() { to } else { nyquist };
        let low = from.min(to);
        let high = from.max(to);
        let from = low.clamp(minimum, nyquist - bin.min(nyquist * 0.5));
        let to = high.max(from + bin.min(nyquist * 0.5)).min(nyquist);
        Self { from, to, log }
    }
    fn fraction(self, hz: f64) -> f64 {
        if self.log {
            (hz / self.from).ln() / (self.to / self.from).ln()
        } else {
            (hz - self.from) / (self.to - self.from)
        }
    }
    fn hz(self, fraction: f64) -> f64 {
        let fraction = fraction.clamp(0.0, 1.0);
        if self.log {
            self.from * (self.to / self.from).powf(fraction)
        } else {
            self.from + fraction * (self.to - self.from)
        }
    }
    fn contains(self, hz: f64) -> bool {
        (self.from..=self.to).contains(&hz)
    }
}

fn comparison_axis(plot: usize) -> (&'static str, f64, f64, Color32) {
    match plot {
        0 => (i18n::text("comparison.gain_db"), -60.0, 20.0, GREEN),
        1 => (i18n::text("comparison.phase"), -180.0, 180.0, BLUE),
        _ => ("γ²", 0.0, 1.0, YELLOW),
    }
}

fn comparison_value(b: &comparison::Bin, plot: usize) -> Option<f64> {
    match plot {
        0 => b.gain.filter(|v| *v > 0.0).map(|v| 20.0 * v.log10()),
        1 => b.phase_lead_degrees,
        _ => b.coherence,
    }
    .filter(|v| v.is_finite())
}

fn comparison_point(
    graph: egui::Rect,
    view: FrequencyRange,
    hz: f64,
    value: f64,
    plot: usize,
) -> egui::Pos2 {
    let (_, min, max, _) = comparison_axis(plot);
    // Clip the actual segment at the graph boundary. Clamping vertices would
    // turn an off-scale response into a false horizontal plateau on the frame.
    pos2(
        graph.left() + graph.width() * view.fraction(hz) as f32,
        graph.bottom() - graph.height() * ((value - min) / (max - min)) as f32,
    )
}

fn comparison_trace(
    r: &comparison::Result,
    plot: usize,
    view: FrequencyRange,
    graph: egui::Rect,
) -> Vec<egui::Shape> {
    let (_, _, _, color) = comparison_axis(plot);
    let bin = r.bin_width_hz();
    // Retain the neighboring bins so a custom range cuts through the curve
    // instead of leaving a blank strip between the frame and the first bin.
    let first = ((view.from / bin).floor() as usize).max(usize::from(view.log));
    let end = ((view.to / bin).ceil() as usize + 1).min(r.bins.len());
    let joins = |a: f64, b: f64| plot != 1 || (b - a).abs() <= 180.0;
    let mut previous: Option<(egui::Pos2, f64)> = None;
    let mut shapes = Vec::new();
    for k in first..end {
        let Some(value) = comparison_value(&r.bins[k], plot) else {
            previous = None;
            continue;
        };
        let point = comparison_point(graph, view, k as f64 * bin, value, plot);
        let connected = previous.filter(|(_, old)| joins(*old, value));
        if let Some((old, _)) = connected {
            shapes.push(egui::Shape::line_segment(
                [old, point],
                Stroke::new(1.5, color),
            ));
        }
        let close_before = connected.is_some_and(|(old, _)| (point.x - old.x).abs() < 8.0);
        let close_after = k + 1 < end
            && comparison_value(&r.bins[k + 1], plot).is_some_and(|next| {
                joins(value, next)
                    && (comparison_point(graph, view, (k + 1) as f64 * bin, next, plot).x - point.x)
                        .abs()
                        < 8.0
            });
        // Sparse and isolated bins remain identifiable; dense curves retain
        // the line's stroke width instead of becoming a band of round markers.
        if !close_before && !close_after && graph.contains(point) {
            shapes.push(egui::Shape::circle_filled(point, 2.0, color));
        }
        previous = Some((point, value));
    }
    shapes
}

fn comparison_plot(
    ui: &mut egui::Ui,
    r: &comparison::Result,
    plot: usize,
    height: f32,
    selected: f64,
    view: FrequencyRange,
) -> Option<f64> {
    let (rect, response) = ui.allocate_exact_size(
        vec2(ui.available_width(), height),
        egui::Sense::click_and_drag(),
    );
    let graph = egui::Rect::from_min_max(
        rect.left_top() + vec2(58.0, 20.0),
        rect.right_bottom() - vec2(8.0, 20.0),
    );
    if graph.width() <= 0.0 || graph.height() <= 0.0 {
        return None;
    }
    let painter = ui.painter().with_clip_rect(rect.intersect(ui.clip_rect()));
    let (title, min, max, color) = comparison_axis(plot);
    painter.text(
        rect.left_top(),
        egui::Align2::LEFT_TOP,
        title,
        egui::FontId::monospace(11.0),
        color,
    );
    let font = egui::FontId::monospace(10.0);
    for i in 0..=4 {
        if graph.height() < 60.0 && matches!(i, 1 | 3) {
            continue;
        }
        let y = graph.top() + graph.height() * i as f32 / 4.0;
        painter.line_segment(
            [pos2(graph.left(), y), pos2(graph.right(), y)],
            Stroke::new(1.0, BORDER),
        );
        painter.text(
            pos2(graph.left() - 3.0, y),
            egui::Align2::RIGHT_CENTER,
            if plot == 2 {
                format!("{:.2}", max - (max - min) * i as f64 / 4.0)
            } else {
                format!("{:.0}", max - (max - min) * i as f64 / 4.0)
            },
            font.clone(),
            MUTED,
        );
    }
    let divisions = if graph.width() >= 400.0 { 4 } else { 2 };
    let mut labels = Vec::new();
    for i in 0..=divisions {
        let fraction = i as f64 / divisions as f64;
        let x = graph.left() + graph.width() * fraction as f32;
        painter.line_segment(
            [pos2(x, graph.top()), pos2(x, graph.bottom())],
            Stroke::new(1.0, BORDER),
        );
        labels.push((
            x,
            i18n::format(
                "comparison.hz_2",
                &[(
                    "fraction",
                    &(frequency_label(view.hz(fraction) as f32)).to_string(),
                )],
            )
            .to_string(),
        ));
    }
    plot_labels::horizontal(
        &painter,
        egui::Rect::from_min_max(
            pos2(graph.left(), graph.bottom() + 4.0),
            pos2(graph.right(), rect.bottom()),
        ),
        labels,
    );
    let project = |hz, v| comparison_point(graph, view, hz, v, plot);
    let data_painter = painter.with_clip_rect(graph.intersect(ui.clip_rect()));
    data_painter.extend(comparison_trace(r, plot, view, graph));
    // Mark the actual FFT bin used by the readout, not an unsnapped requested frequency.
    let selected_hz = r
        .bin_at(selected)
        .map_or(selected, |(k, _)| k as f64 * r.bin_width_hz());
    if view.contains(selected_hz) {
        let x = project(selected_hz, min).x;
        data_painter.line_segment(
            [pos2(x, graph.top()), pos2(x, graph.bottom())],
            Stroke::new(1.0, MUTED),
        );
        plot_labels::horizontal(
            &painter,
            egui::Rect::from_min_max(pos2(graph.left(), rect.top()), graph.right_top()),
            [(
                x,
                i18n::format(
                    "comparison.hz",
                    &[(
                        "selected_hz",
                        &(display::number(Some(selected_hz))).to_string(),
                    )],
                )
                .to_string(),
            )],
        );
        if let Some((_, b)) = r.bin_at(selected)
            && let Some(v) = comparison_value(b, plot)
            && graph.contains(project(selected_hz, v))
        {
            data_painter.circle_filled(project(selected_hz, v), 4.0, color);
        }
    }
    if (response.clicked() || response.dragged())
        && let Some(pos) = response
            .interact_pointer_pos()
            .filter(|pos| graph.contains(*pos))
    {
        return Some(view.hz(((pos.x - graph.left()) / graph.width()) as f64));
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;

    fn fixture(values: &[Option<f64>]) -> comparison::Result {
        let mut r = comparison::Result::empty(
            comparison::Settings {
                size: 1024,
                ..Default::default()
            },
            1024,
            1,
            1,
            2,
        );
        r.bins = values
            .iter()
            .map(|&value| comparison::Bin {
                reference_psd: 1.0,
                response_psd: 1.0,
                cross_re: 1.0,
                cross_im: 0.0,
                coherence: value.map(|_| 1.0),
                transfer_re: None,
                transfer_im: None,
                gain: value.map(|db| 10.0_f64.powf(db / 20.0)),
                phase_lead_degrees: value,
                phase_delay_seconds: None,
                state: if value.is_some() {
                    comparison::BinState::Valid
                } else {
                    comparison::BinState::ReferenceLost
                },
            })
            .collect();
        r
    }

    #[test]
    fn off_scale_gain_keeps_its_slope_and_custom_ranges_reach_the_frame() {
        let r = fixture(&[None, Some(-100.0), Some(-20.0), Some(-100.0)]);
        let original = r.clone();
        let graph = egui::Rect::from_min_size(pos2(0.0, 0.0), vec2(100.0, 100.0));
        for log in [false, true] {
            let view = FrequencyRange::new(1.25, 2.75, 512.0, 1.0, log);
            let shapes = comparison_trace(&r, 0, view, graph);
            let lines: Vec<_> = shapes
                .iter()
                .filter_map(|s| match s {
                    egui::Shape::LineSegment { points, .. } => Some(points),
                    _ => None,
                })
                .collect();
            assert_eq!(lines.len(), 2);
            assert!(lines[0][0].x < graph.left());
            assert!(lines[1][1].x > graph.right());
            // -100 dB is 40 dB below the frame, rather than stuck at -60 dB.
            assert_eq!(lines[0][0].y, 150.0);
            assert_eq!(lines[0][1].y, 50.0);
            assert_eq!(lines[1][1].y, 150.0);
        }
        let below = fixture(&[Some(-100.0), Some(-80.0)]);
        let shapes = comparison_trace(
            &below,
            0,
            FrequencyRange::new(0.0, 1.0, 512.0, 1.0, false),
            graph,
        );
        assert_eq!(shapes.len(), 1);
        assert!(!shapes[0].visual_bounding_rect().intersects(graph));
        assert_eq!(r, original);
    }

    #[test]
    fn dense_curves_omit_bin_discs_but_keep_isolated_bins_and_gaps() {
        let graph = egui::Rect::from_min_size(pos2(0.0, 0.0), vec2(100.0, 100.0));
        let view = FrequencyRange::new(0.0, 511.0, 512.0, 1.0, false);
        let mut values = vec![Some(0.0); 512];
        values[256] = None;
        let shapes = comparison_trace(&fixture(&values), 0, view, graph);
        assert_eq!(shapes.len(), 509);
        assert!(
            shapes
                .iter()
                .all(|s| matches!(s, egui::Shape::LineSegment { .. }))
        );
        values.fill(None);
        values[256] = Some(0.0);
        let isolated = comparison_trace(&fixture(&values), 0, view, graph);
        assert_eq!(isolated.len(), 1);
        assert!(matches!(isolated[0], egui::Shape::Circle(_)));
    }

    #[test]
    fn phase_wraps_and_missing_bins_do_not_gain_connectors() {
        let r = fixture(&[Some(170.0), Some(-170.0), None, Some(15.0)]);
        let graph = egui::Rect::from_min_size(pos2(0.0, 0.0), vec2(300.0, 100.0));
        let view = FrequencyRange::new(0.0, 3.0, 512.0, 1.0, false);
        let shapes = comparison_trace(&r, 1, view, graph);
        assert_eq!(shapes.len(), 3);
        assert!(shapes.iter().all(|s| matches!(s, egui::Shape::Circle(_))));
    }

    #[test]
    fn selected_frequency_in_a_very_narrow_graph_does_not_panic() {
        let ctx = egui::Context::default();
        let r = fixture(&[Some(0.0), Some(0.0)]);
        let view = FrequencyRange::new(0.0, 1.0, 512.0, 1.0, false);
        ctx.run_ui(
            egui::RawInput {
                screen_rect: Some(egui::Rect::from_min_size(
                    pos2(0.0, 0.0),
                    vec2(100.0, 400.0),
                )),
                ..Default::default()
            },
            |ui| {
                for plot in 0..3 {
                    comparison_plot(ui, &r, plot, 100.0, 1.0, view);
                }
            },
        )
        .drop_without_applying_deltas();
    }

    #[test]
    fn logarithmic_selection_roundtrips_and_excludes_dc() {
        let view = FrequencyRange::new(0.0, 24000.0, 24000.0, 11.71875, true);
        assert!(!view.contains(0.0));
        for hz in [view.from, 750.0, 10000.0, view.to] {
            assert!((view.hz(view.fraction(hz)) - hz).abs() < 1e-8);
        }
    }

    #[test]
    fn equal_reversed_and_out_of_range_spans_stay_finite() {
        for (from, to) in [
            (750.0, 750.0),
            (5000.0, 100.0),
            (48000.0, 48000.0),
            (0.0, 0.0),
        ] {
            for log in [false, true] {
                let view = FrequencyRange::new(from, to, 24000.0, 11.71875, log);
                assert!(view.from < view.to && view.to <= 24000.0);
                assert_eq!(view.hz(-1.0), view.from);
                assert!((view.hz(2.0) - view.to).abs() < 1e-8);
                assert!(view.fraction(view.hz(0.5)).is_finite());
            }
        }
    }

    #[test]
    fn reading_zoom_keeps_the_tone_visible_without_changing_results() {
        let r = comparison::Result::empty(
            comparison::Settings {
                size: 4096,
                ..Default::default()
            },
            48000,
            1,
            1,
            2,
        );
        let original = r.clone();
        let view = ComparisonDisplay::default().range(&r, 750.0);
        assert!((0.3..=0.7).contains(&view.fraction(750.0)));
        assert!(view.to - view.from < 24000.0 * 0.1);
        assert_eq!(r, original);
        let reversed = FrequencyRange::new(5000.0, 100.0, 24000.0, 11.71875, false);
        assert_eq!([reversed.from, reversed.to], [100.0, 5000.0]);
    }
}
