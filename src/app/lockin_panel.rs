//! Instrument display only: captured conditions and f64 results remain in the worker.
use super::*;
use crate::settings::LockinDisplay;

// Reuse scalar formatting; the file also contains future monitor cursor helpers.
#[expect(dead_code, reason = "Lock-in uses scalar formatting only")]
#[path = "../readout.rs"]
mod readout;

impl ScopeApp {
    #[cfg(feature = "qa")]
    pub(super) fn check_lockin_ui(&mut self, mode: &str) -> Result<(), String> {
        self.poll_audio();
        self.source = Source::Software;
        self.core = Some(measurement::Worker::new(self.stft.take_feeder()));
        self.loopback_settings = loopback::Settings {
            frequency_hz: 750.0,
            reference_enabled: mode != "ref-loss",
            ..Default::default()
        };
        self.lockin_settings = lockin::Settings {
            enabled: true,
            frequency_hz: 750.0,
            time_constant_seconds: if mode == "settling" { 1.0 } else { 0.02 },
            ..Default::default()
        };
        self.acquisition_mode = acquisition::Mode::Auto;
        self.start();
        let deadline = Instant::now() + Duration::from_secs(5);
        loop {
            self.poll_measurement();
            if self.lockin_result.state == lockin::State::ReferenceLost
                || self.lockin_result.processed_windows >= 8
            {
                break;
            }
            if Instant::now() > deadline {
                return Err("Lock-in UI software measurement timed out".into());
            }
            std::thread::sleep(Duration::from_millis(5));
        }
        if mode == "live-edit" {
            let before = self.lockin_settings;
            self.lockin_settings.time_constant_seconds = 0.03;
            self.apply_lockin_controls(before);
            let deadline = Instant::now() + Duration::from_secs(5);
            loop {
                self.poll_measurement();
                if self.lockin_result.settings == self.lockin_settings
                    && self.lockin_result.state == lockin::State::Valid
                    && self.lockin_result.processed_windows >= 8
                {
                    break;
                }
                if Instant::now() > deadline {
                    return Err("Live Lock-in filter change timed out".into());
                }
                std::thread::sleep(Duration::from_millis(5));
            }
        }
        self.stop();
        let mut snapshot = self
            .pending_stop
            .take()
            .ok_or("Missing Lock-in stop barrier")?
            .wait();
        self.accept_snapshot(&mut snapshot);
        let expected_state = match mode {
            "ref-loss" => lockin::State::ReferenceLost,
            "settling" => lockin::State::Settling,
            _ => lockin::State::Valid,
        };
        assert_eq!(self.lockin_result.state, expected_state);
        if expected_state == lockin::State::Valid {
            assert!((self.lockin_result.amplitude_peak.unwrap() - 0.0625).abs() < 1e-8);
            assert!((self.lockin_result.phase_degrees.unwrap() - 30.0).abs() < 1e-6);
        } else if expected_state == lockin::State::ReferenceLost {
            assert!(self.lockin_result.x.is_none());
            assert!(self.lockin_result.phase_degrees.is_none());
        }
        let held = self.lockin_result.clone();
        let original_view = (self.visible, self.lockin_visible, self.plot_layout);
        self.previous_view = None;
        self.select_lockin_view(false);
        self.lockin_display = LockinDisplay::All;
        self.select_view([true; 4]);
        self.restore_view();
        assert_eq!(
            (self.visible, self.lockin_visible, self.plot_layout),
            original_view
        );
        assert_eq!(self.lockin_result, held);
        self.select_lockin_view(mode == "pair");
        self.lockin_display = match mode {
            "all" | "pair" => LockinDisplay::All,
            "cartesian" => LockinDisplay::Cartesian,
            _ => LockinDisplay::Polar,
        };
        if mode == "held-edit" {
            let before = self.lockin_settings;
            self.lockin_settings.frequency_hz = 1000.0;
            self.lockin_settings.time_constant_seconds = 0.1;
            self.apply_lockin_controls(before);
            assert_eq!(self.lockin_result, held);
        }
        let settings = self.capture_settings()?;
        assert!(settings.workspace.lockin_visible);
        let decoded = settings::Document::decode(&settings.encode()?)?;
        assert_eq!(decoded.workspace.lockin_display, self.lockin_display);
        if mode == "source-change" {
            self.source = Source::Live;
            self.switch_source();
            assert!(self.lockin_result.x.is_none());
            assert!(self.lockin_result.phase_degrees.is_none());
            assert_eq!(self.lockin_result.processed_windows, 0);
        }
        self.sidebar.reveal(SettingsSection::Lockin);
        self.created = Instant::now();
        println!(
            "Lock-in UI QA OK: {mode}; common software input and finite stop; display switching preserves captured values/conditions; workspace roundtrip"
        );
        Ok(())
    }

    pub(super) fn select_lockin_view(&mut self, scope: bool) {
        self.select_view([scope, false, false, false]);
        self.lockin_visible = true;
    }

    pub(super) fn lockin_controls(&mut self, ui: &mut egui::Ui) {
        if ui.button("Open Lock-in display").clicked() {
            self.select_lockin_view(false);
        }
        ui.label(
            RichText::new("EXPERIMENTAL · INPUT REFERENCE")
                .small()
                .color(YELLOW),
        );
        let before = self.lockin_settings;
        ui.add_enabled_ui(
            !self.busy && self.pending_stop.is_none() && !self.workspace_restoring,
            |ui| {
                let channels = self.lockin_channel_count();
                let s = &mut self.lockin_settings;
                ui.checkbox(&mut s.enabled, "Enable demodulator");
                setting_label(ui, "SIGNAL INPUT");
                channel_select(ui, "lockin_response", &mut s.response_channel, channels);
                setting_label(ui, "REFERENCE INPUT");
                channel_select(ui, "lockin_reference", &mut s.reference_channel, channels);
                ui.label(
                    RichText::new("REF and signal use the same input sample clock.")
                        .small()
                        .color(MUTED),
                );
                setting_label(ui, "REFERENCE & FILTER");
                lockin_filter_controls(ui, s);
                setting_label(ui, "REFERENCE VALIDITY");
                ui.add(
                    egui::DragValue::new(&mut s.reference_min_rms_fs)
                        .range(1e-12..=1.0)
                        .speed(0.0001)
                        .max_decimals(12)
                        .prefix("Min REF ")
                        .suffix(" FS RMS"),
                );
            },
        );
        self.apply_lockin_controls(before);
        ui.separator();
        ui.label(RichText::new("R, X and Y are peak amplitudes. Positive phase leads REF. The filter has two fixed EMA poles and settles after 10τ of valid samples. Settings changed while stopped apply on the next Start.").small().color(MUTED));
        ui.label(RichText::new("Physical REF and timing remain unverified. No physical oscillator output or selectable hardware sensitivity.").small().color(MUTED));
    }

    pub(super) fn lockin_channel_count(&self) -> u16 {
        if self.running() || self.pending_stop.is_some() {
            self.channels
        } else if self.source == Source::Software
            || self.source == Source::Generator
            || self.source.is_demo()
        {
            2
        } else {
            self.devices
                .get(self.selected)
                .map_or(self.channels, |d| d.channels)
        }
        .max(1)
    }

    fn apply_lockin_controls(&mut self, before: lockin::Settings) {
        if before == self.lockin_settings {
            return;
        }
        let rate = if self.running() {
            self.sample_rate
        } else if self.source == Source::Generator {
            self.generator.rate
        } else if self.source == Source::Software {
            self.requested_sample_rate.unwrap_or(48000)
        } else {
            self.requested_sample_rate.unwrap_or_else(|| {
                self.devices
                    .get(self.selected)
                    .map_or(self.sample_rate, |d| d.default_sample_rate)
            })
        };
        if let Err(error) = self.lockin_settings.validate(rate) {
            self.lockin_settings = before;
            self.error = Some(format!(
                "{error}: frequency must be below 0.45 × nominal Fs ({rate} Hz)"
            ));
        } else if self.running()
            && let Some(core) = &self.core
        {
            core.configure_lockin(self.lockin_settings);
        }
    }

    pub(super) fn lockin_panel(&mut self, ui: &mut egui::Ui) {
        let height = ui.available_height();
        egui::Frame::new()
            .fill(Color32::from_rgb(17, 27, 35))
            .stroke(Stroke::new(1.0, BORDER))
            .inner_margin(8.0)
            .show(ui, |ui| {
                ui.set_min_width((ui.available_width() - 1.0).max(0.0));
                ui.horizontal_wrapped(|ui| {
                    ui.label(RichText::new("Lock-in amplifier").strong());
                    ui.label(RichText::new("EXPERIMENTAL").small().color(MUTED));
                    if ui.small_button("Settings").clicked() {
                        self.sidebar.reveal(SettingsSection::Lockin);
                    }
                });
                ui.horizontal_wrapped(|ui| {
                    for (mode, label) in [(LockinDisplay::Polar, "R / θ"), (LockinDisplay::Cartesian, "X / Y"), (LockinDisplay::All, "All four")] {
                        ui.selectable_value(&mut self.lockin_display, mode, label);
                    }
                    ui.separator();
                    let no_capture = self.lockin_result.state == lockin::State::Settling
                        && self.lockin_result.latest_window.is_empty()
                        && !self.running();
                    let (label, color) = if self.input_failed {
                        ("INPUT FAILED", TRIGGER)
                    } else if no_capture {
                        ("NO CAPTURE", MUTED)
                    } else {
                        state_label(self.lockin_result.state)
                    };
                    ui.label(RichText::new(label).strong().color(color));
                    display::activity_label(ui, self.running(), self.pending_stop.is_some(), !self.lockin_result.latest_window.is_empty());
                });
                let r = &self.lockin_result;
                let unit = self.calibration.captured.unit(r.settings.response_channel);
                let usable = !self.input_failed && matches!(r.state, lockin::State::Valid | lockin::State::Settling);
                let read = |value| valid_reading(r, value).filter(|_| usable);
                let cells = match self.lockin_display {
                    LockinDisplay::Polar => vec![("R", "Amplitude · peak", read(r.amplitude_peak), false), ("θ", "Phase · leads REF", read(r.phase_degrees), true)],
                    LockinDisplay::Cartesian => vec![("X", "In-phase · peak", read(r.x), false), ("Y", "Quadrature · peak", read(r.y), false)],
                    LockinDisplay::All => vec![("R", "Amplitude · peak", read(r.amplitude_peak), false), ("θ", "Phase · leads REF", read(r.phase_degrees), true), ("X", "In-phase · peak", read(r.x), false), ("Y", "Quadrature · peak", read(r.y), false)],
                };
                let columns = if cells.len() == 4 && ui.available_width() >= 560.0 { 2 } else { 1 };
                let rows = cells.len().div_ceil(columns);
                let cell_height = ((height - 230.0) / rows as f32).clamp(92.0, 180.0);
                let amplitude_range = display_range(read(r.amplitude_peak).unwrap_or(1.0));
                egui::Frame::new().fill(Color32::from_rgb(16, 32, 75))
                    .stroke(Stroke::new(1.0, Color32::from_rgb(79, 108, 148)))
                    .inner_margin(8.0).corner_radius(4.0)
                    .show(ui, |ui| {
                        ui.horizontal_wrapped(|ui| {
                            ui.label(RichText::new(format!("SIG CH {}   /   REF CH {}", r.settings.response_channel + 1, r.settings.reference_channel + 1)).small().color(Color32::LIGHT_GRAY));
                            ui.label(RichText::new(if self.calibration.captured.get(r.settings.response_channel).is_some() { "CALIBRATED" } else { "UNCALIBRATED · FS" }).small().color(MUTED));
                        });
                        for row in cells.chunks(columns) {
                            ui.horizontal(|ui| {
                                let width = (ui.available_width() - ui.spacing().item_spacing.x * (row.len() - 1) as f32) / row.len() as f32;
                                for &(symbol, description, value, phase) in row {
                                    numeric_cell(ui, vec2(width, cell_height), NumericCell {
                                        symbol, description, value, unit: if phase { "°" } else { unit },
                                        range: if phase { 180.0 } else { amplitude_range },
                                        bipolar: symbol != "R", phase,
                                    });
                                }
                            });
                        }
                        ui.separator();
                        ui.horizontal_wrapped(|ui| {
                            ui.label(RichText::new(format!("f REF  {}", option_value(read(r.reference_frequency_hz), "Hz"))).monospace().color(Color32::WHITE));
                            let gain_unit = format!("{}/{}", unit, self.calibration.captured.unit(r.settings.reference_channel));
                            let gain = read(r.gain).map_or_else(|| format!("— {gain_unit}"), |v| format!("{v:.5} {gain_unit}"));
                            ui.label(RichText::new(format!("Gain  {gain}")).monospace().color(Color32::WHITE));
                        });
                        ui.horizontal_wrapped(|ui| {
                            ui.label(RichText::new(format!("τ {}   ·   2 poles   ·   N {}   ·   {}", readout::value(r.settings.time_constant_seconds, "s"), r.settings.integration_samples, if r.settings.track_reference { "TRACK REF" } else { "FIXED FREQUENCY" })).small().color(Color32::LIGHT_GRAY));
                        });
                    });
                if r.settings != self.lockin_settings {
                    ui.label(RichText::new(if self.running() { "Applying settings · display retains its captured conditions" } else { "Next Start settings changed · display retains captured conditions" }).small().color(YELLOW));
                }
                if !self.running() && r.latest_window.is_empty() && r.state == lockin::State::Settling {
                    ui.label(RichText::new("Start input to acquire a synchronous SIG / REF window.").small().color(MUTED));
                } else if r.state == lockin::State::Settling {
                    let progress = settling_fraction(r, self.sample_rate);
                    ui.add(egui::ProgressBar::new(progress as f32).text(format!("Settling · {:.0}% of 10τ", progress * 100.0)));
                } else if !usable {
                    ui.label(RichText::new(state_help(r.state)).small().color(MUTED));
                }
                ui.horizontal_wrapped(|ui| {
                    let before = self.lockin_settings;
                    ui.add_enabled_ui(!self.busy && self.pending_stop.is_none() && !self.workspace_restoring, |ui| {
                        ui.checkbox(&mut self.lockin_settings.enabled, "Demodulate");
                        ui.menu_button("REF / Filter…", |ui| {
                            ui.push_id("lockin_front_panel", |ui| lockin_filter_controls(ui, &mut self.lockin_settings));
                        });
                    });
                    self.apply_lockin_controls(before);
                    if ui.small_button("Input…").clicked() {
                        self.sidebar.io_output = false;
                        self.sidebar.reveal(SettingsSection::Io);
                    }
                });
                ui.collapsing("Measurement details", |ui| {
                    let r = &self.lockin_result;
                    ui.label(format!("Nominal Fs {} Hz · input generation {}", self.sample_rate, self.input_generation));
                    ui.label(format!("Captured hint {} · τ {} · REF threshold {}", readout::value(r.settings.frequency_hz, "Hz"), readout::value(r.settings.time_constant_seconds, "s"), readout::value(r.settings.reference_min_rms_fs, "FS")));
                    ui.label(format!("REF AC RMS {} · sinusoid fit {}", option_value(r.reference_ac_rms_fs, "FS"), r.reference_sinusoid_fraction.map_or_else(|| "—".into(), |v| format!("{:.3}%", v * 100.0))));
                    ui.label(format!("Averaged samples {}..{} · latest window {}..{}", r.sample_range.start, r.sample_range.end, r.latest_window.start, r.latest_window.end));
                    ui.label(format!("{} complete windows · {} missing samples", r.processed_windows, r.missing_samples));
                    for ch in [r.settings.response_channel, r.settings.reference_channel] {
                        if let Some(c) = self.calibration.captured.get(ch) {
                            ui.label(format!("CH {} calibration {} / revision {} · gain {} {} / FS", ch + 1, c.id(), c.revision(), c.gain(), c.unit()));
                        }
                    }
                    ui.label("Display bars auto-scale; they do not change input sensitivity. Periodic Hann fit + two EMA poles. Physical REF / timing unverified.");
                });
            });
    }
}

fn lockin_filter_controls(ui: &mut egui::Ui, s: &mut lockin::Settings) {
    ui.add(
        egui::DragValue::new(&mut s.frequency_hz)
            .range(10.0..=345599.0)
            .speed(1.0)
            .prefix("REF hint ")
            .suffix(" Hz"),
    );
    ui.checkbox(&mut s.track_reference, "Track input REF (hint ±10%)");
    ui.add(
        egui::DragValue::new(&mut s.time_constant_seconds)
            .range(0.001..=10.0)
            .speed(0.001)
            .max_decimals(3)
            .prefix("τ ")
            .suffix(" s"),
    );
    egui::ComboBox::from_id_salt("lockin_tau_presets")
        .selected_text("Time constant presets")
        .show_ui(ui, |ui| {
            for tau in [0.001, 0.003, 0.01, 0.02, 0.03, 0.1, 0.3, 1.0, 3.0, 10.0] {
                ui.selectable_value(&mut s.time_constant_seconds, tau, readout::value(tau, "s"));
            }
        });
    egui::ComboBox::from_id_salt("lockin_window")
        .selected_text(format!("Integration: {} samples", s.integration_samples))
        .show_ui(ui, |ui| {
            for n in [1024, 4096, 16384, 65536] {
                ui.selectable_value(&mut s.integration_samples, n, format!("{n} samples"));
            }
        });
    ui.label(
        RichText::new("2 EMA poles · 10τ settling · fundamental only")
            .small()
            .color(MUTED),
    );
}

fn valid_reading(result: &lockin::Result, value: Option<f64>) -> Option<f64> {
    value.filter(|value| {
        result.settings.enabled
            && matches!(result.state, lockin::State::Valid | lockin::State::Settling)
            && value.is_finite()
    })
}

fn option_value(value: Option<f64>, unit: &str) -> String {
    value
        .filter(|v| v.is_finite())
        .map_or_else(|| format!("— {unit}"), |v| readout::value(v, unit))
}

fn state_label(state: lockin::State) -> (&'static str, Color32) {
    match state {
        lockin::State::Valid => ("REF VALID", GREEN),
        lockin::State::Settling => ("SETTLING", YELLOW),
        lockin::State::Disabled => ("DISABLED", MUTED),
        lockin::State::Unavailable => ("CH / SETTINGS UNAVAILABLE", TRIGGER),
        lockin::State::ReferenceLost => ("REF LOST", TRIGGER),
        lockin::State::ReferenceUnstable => ("REF UNSTABLE", TRIGGER),
        lockin::State::Missing => ("INPUT GAP", TRIGGER),
        lockin::State::NonFinite => ("INVALID INPUT", TRIGGER),
    }
}

fn state_help(state: lockin::State) -> &'static str {
    match state {
        lockin::State::Disabled => {
            "Enable Demodulate, select SIG / REF channels, then Start input."
        }
        lockin::State::Unavailable => {
            "Check SIG / REF channel availability and frequency against nominal Fs."
        }
        lockin::State::ReferenceLost => {
            "REF is below its AC RMS threshold. Values clear until REF recovers."
        }
        lockin::State::ReferenceUnstable => {
            "REF needs ≥3 cycles/window, ≥98% sinusoid fit and frequency within the hint range."
        }
        lockin::State::Missing => {
            "Input samples are missing. The filter clears and settles again after recovery."
        }
        lockin::State::NonFinite => {
            "Input or calculation is nonfinite. No valid measurement is available."
        }
        lockin::State::Settling => "Waiting for a complete synchronous input window.",
        lockin::State::Valid => "",
    }
}

fn settling_fraction(result: &lockin::Result, rate: u32) -> f64 {
    (result
        .sample_range
        .end
        .saturating_sub(result.sample_range.start) as f64
        / (10.0 * result.settings.time_constant_seconds * rate as f64))
        .clamp(0.0, 1.0)
}

// A display range in 1/2/5 steps, never a detector sensitivity or input gain.
fn display_range(value: f64) -> f64 {
    if !value.is_finite() || value <= 0.0 {
        return 1.0;
    }
    let exponent = value.log10().floor().clamp(-300.0, 300.0);
    let decade = 10.0_f64.powf(exponent);
    let scaled = value / decade;
    let step = if scaled <= 1.0 {
        1.0
    } else if scaled <= 2.0 {
        2.0
    } else if scaled <= 5.0 {
        5.0
    } else {
        10.0
    };
    (step * decade).max(value)
}

struct NumericCell<'a> {
    symbol: &'a str,
    description: &'a str,
    value: Option<f64>,
    unit: &'a str,
    range: f64,
    bipolar: bool,
    phase: bool,
}

fn numeric_cell(ui: &mut egui::Ui, size: egui::Vec2, cell: NumericCell<'_>) {
    let (rect, response) = ui.allocate_exact_size(size, egui::Sense::hover());
    let p = ui.painter().with_clip_rect(rect.intersect(ui.clip_rect()));
    let white = Color32::from_rgb(222, 233, 255);
    p.text(
        rect.left_top() + vec2(4.0, 2.0),
        egui::Align2::LEFT_TOP,
        cell.description,
        egui::FontId::proportional(11.0),
        Color32::from_rgb(149, 175, 216),
    );
    let symbol_size = (size.y * 0.3).clamp(25.0, 44.0);
    let center_y = rect.top() + size.y * 0.44;
    p.text(
        pos2(rect.left() + 4.0, center_y),
        egui::Align2::LEFT_CENTER,
        cell.symbol,
        egui::FontId::proportional(symbol_size),
        white,
    );
    let text = cell.value.map_or_else(
        || format!("— {}", cell.unit),
        |v| {
            if cell.phase {
                format!("{v:+.3}°")
            } else {
                readout::signed(v, cell.unit)
            }
        },
    );
    let max_size = (size.y * 0.34).clamp(24.0, 58.0);
    let color = if cell.value.is_some() { YELLOW } else { MUTED };
    let mut galley = p.layout_no_wrap(text.clone(), egui::FontId::monospace(max_size), color);
    let numeric_width = (rect.width() - symbol_size - 30.0).max(1.0);
    if galley.size().x > numeric_width {
        let font_size = max_size * numeric_width / galley.size().x;
        galley = p.layout_no_wrap(text, egui::FontId::monospace(font_size), color);
    }
    p.galley(
        pos2(
            rect.right() - 6.0 - galley.size().x,
            center_y - galley.size().y * 0.5,
        ),
        galley,
        color,
    );
    let bar = egui::Rect::from_min_max(
        pos2(rect.left() + 6.0, rect.bottom() - 28.0),
        pos2(rect.right() - 6.0, rect.bottom() - 24.0),
    );
    p.rect_filled(bar, 0.0, Color32::from_rgb(68, 92, 134));
    for i in 0..=20 {
        let x = bar.left() + bar.width() * i as f32 / 20.0;
        p.line_segment(
            [
                pos2(x, bar.top() - if i % 5 == 0 { 6.0 } else { 3.0 }),
                pos2(x, bar.top()),
            ],
            Stroke::new(1.0, white),
        );
    }
    if let Some(value) = cell.value {
        let normalized = (value / cell.range).clamp(-1.0, 1.0) as f32;
        let origin = if cell.bipolar {
            bar.center().x
        } else {
            bar.left()
        };
        let x = if cell.bipolar {
            bar.center().x + normalized * bar.width() * 0.5
        } else {
            bar.left() + normalized * bar.width()
        };
        p.rect_filled(
            egui::Rect::from_min_max(
                pos2(origin.min(x), bar.top()),
                pos2(origin.max(x), bar.bottom()),
            ),
            0.0,
            YELLOW,
        );
        p.line_segment(
            [pos2(x, bar.top() - 8.0), pos2(x, bar.bottom() + 2.0)],
            Stroke::new(2.0, YELLOW),
        );
    }
    let font = egui::FontId::monospace(10.0);
    let bound = if cell.phase {
        "180°".into()
    } else {
        readout::value(cell.range, cell.unit)
    };
    p.text(
        pos2(bar.left(), rect.bottom() - 2.0),
        egui::Align2::LEFT_BOTTOM,
        if cell.bipolar {
            format!("−{bound}")
        } else {
            "0".into()
        },
        font.clone(),
        white,
    );
    if cell.bipolar {
        p.text(
            pos2(bar.center().x, rect.bottom() - 2.0),
            egui::Align2::CENTER_BOTTOM,
            "0",
            font.clone(),
            white,
        );
    }
    p.text(
        pos2(bar.right(), rect.bottom() - 2.0),
        egui::Align2::RIGHT_BOTTOM,
        bound,
        font,
        white,
    );
    response.on_hover_text(cell.value.map_or_else(
        || "No valid reading; no bar marker is shown".into(),
        |v| format!("{v:+.12e} {} · display scale only", cell.unit),
    ));
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn invalid_states_never_display_stale_values_or_replace_them_with_zero() {
        let mut result = lockin::Analyzer::new(
            lockin::Settings {
                enabled: true,
                ..Default::default()
            },
            48000,
        )
        .result()
        .clone();
        for state in [
            lockin::State::Disabled,
            lockin::State::Unavailable,
            lockin::State::ReferenceLost,
            lockin::State::ReferenceUnstable,
            lockin::State::Missing,
            lockin::State::NonFinite,
        ] {
            result.state = state;
            assert_eq!(valid_reading(&result, Some(0.125)), None);
        }
        for state in [lockin::State::Settling, lockin::State::Valid] {
            result.state = state;
            assert_eq!(valid_reading(&result, Some(0.0)), Some(0.0));
            assert_eq!(valid_reading(&result, None), None);
            assert_eq!(valid_reading(&result, Some(f64::NAN)), None);
        }
        assert_eq!(option_value(None, "FS"), "— FS");
    }
}
