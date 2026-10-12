//! Generator controls and a static settings preview. Measured samples are
//! supplied separately by output::Worker through the shared measurement path.
use super::*;
use crate::{generator, output};

pub(super) struct GeneratorUi {
    pub worker: output::Worker,
    pub settings: generator::Settings,
    pub rate: u32,
    pub status: generator::Status,
    pub visible: bool,
    pub pending: bool,
    pub starting: bool,
    pub stopping: bool,
    pub error: Option<String>,
    requested_id: u64,
    stop_epoch: u64,
    texts: [[String; 3]; 2],
    edited: [[bool; 3]; 2],
    selected: usize,
    step: f64,
}
impl Default for GeneratorUi {
    fn default() -> Self {
        let settings = generator::Settings::default();
        Self {
            worker: output::Worker::new(),
            settings,
            rate: 48_000,
            status: generator::Engine::new(48_000, 2, settings, 0)
                .unwrap()
                .status(),
            visible: false,
            pending: false,
            starting: false,
            stopping: false,
            error: None,
            requested_id: 0,
            stop_epoch: 0,
            texts: std::array::from_fn(|_| std::array::from_fn(|_| String::new())),
            edited: [[false; 3]; 2],
            selected: 0,
            step: 1.0,
        }
    }
}
impl GeneratorUi {
    pub fn stopped(&self) -> bool {
        self.status.state == generator::State::Stopped
            && !self.starting
            && !self.stopping
            && !self.pending
    }
    pub fn poll(&mut self) {
        if let Some(update) = self.worker.poll() {
            self.status = update.status;
            let acknowledged = update.acknowledged_request >= self.requested_id;
            if acknowledged && update.error.is_none() && (self.pending || self.starting) {
                self.error = None;
            }
            if let Some(error) = update.error
                && acknowledged
            {
                self.error = Some(error.to_string());
                self.pending = false;
                self.starting = false;
            }
            if acknowledged {
                self.pending = false;
                self.starting = false;
            }
            if update.stop_epoch >= self.stop_epoch
                && matches!(
                    self.status.state,
                    generator::State::Stopped | generator::State::Error(_)
                )
            {
                self.stopping = false;
            }
        }
    }
    fn configure(&mut self, settings: generator::Settings) {
        match settings
            .validate(self.rate, 2)
            .map_err(|e| e.to_string())
            .and_then(|()| self.worker.configure(settings))
        {
            Ok(id) => {
                self.requested_id = id;
                self.settings = settings;
                self.pending = true;
                self.error = None;
            }
            Err(e) => self.error = Some(e),
        }
    }
    pub fn start(&mut self) {
        match self
            .settings
            .validate(self.rate, 2)
            .map_err(|e| e.to_string())
            .and_then(|()| self.worker.start(self.settings))
        {
            Ok(id) => {
                self.requested_id = id;
                self.starting = true;
                self.error = None;
            }
            Err(e) => self.error = Some(e),
        }
    }
    pub fn stop(&mut self) {
        self.stop_epoch = self.worker.stop();
        self.pending = false;
        self.stopping = true;
        self.starting = false;
    }
    fn label(&self) -> &'static str {
        if self.stopping {
            return "STOPPING";
        }
        if self.starting {
            return "STARTING · pending";
        }
        match self.status.state {
            generator::State::Stopped => "STOPPED",
            generator::State::Starting => "STARTING",
            generator::State::Running => "RUNNING",
            generator::State::Stopping => "STOPPING",
            generator::State::Error(_) => "ERROR",
        }
    }
    pub fn restore(&mut self, saved: output::Saved) -> Result<(), String> {
        saved.validate()?;
        self.requested_id = self
            .worker
            .set_rate(saved.nominal_sample_rate, saved.signals)?;
        self.rate = saved.nominal_sample_rate;
        self.settings = saved.signals;
        self.pending = true;
        self.error = None;
        Ok(())
    }
}

impl ScopeApp {
    #[cfg(feature = "qa")]
    pub(super) fn check_generator_ui(&mut self, mode: &str) -> Result<(), String> {
        self.poll_audio();
        self.core = Some(measurement::Worker::new(self.stft.take_feeder()));
        self.source = Source::Generator;
        self.demo_enabled = false;
        self.generator.visible = true;
        self.sidebar.visible = mode == "narrow";
        if mode == "narrow" {
            self.generator.selected = 1;
        }
        self.visible = [
            mode == "scope" || mode == "narrow",
            mode == "spectrum",
            false,
            false,
        ];
        self.lockin_visible = mode == "lockin";
        self.lockin_settings = lockin::Settings {
            enabled: true,
            frequency_hz: 750.0,
            time_constant_seconds: 0.005,
            ..Default::default()
        };
        self.spectrum_channel = 1;
        self.spectrum_settings.size = 8192;
        self.spectrum_settings.averages = 1;
        self.spectrum_settings.window = Window::Rectangular;
        self.spectrum_mode = SpectrumMode::Continuous;
        self.ms_per_div = 512.0 / 480.0;
        self.fs_per_div = 0.05;
        self.acquisition_mode = acquisition::Mode::Auto;
        let mut settings = crate::generator::Settings::default();
        for (i, s) in settings.signals.iter_mut().enumerate() {
            s.enabled = true;
            s.frequency_hz = 750.0;
            s.amplitude_dbfs = 20.0 * (0.125 / (i + 1) as f64).log10();
        }
        settings.signals[1].phase_degrees = 30.0;
        self.generator.configure(settings);
        let deadline = Instant::now() + Duration::from_secs(5);
        while self.generator.pending {
            self.generator.poll();
            if Instant::now() > deadline {
                return Err("Generator configuration timed out".into());
            }
            std::thread::sleep(Duration::from_millis(2));
        }
        assert!(self.generator.stopped());
        self.generator.start();
        self.start();
        let deadline = Instant::now() + Duration::from_secs(5);
        while self
            .core
            .as_ref()
            .unwrap()
            .metrics
            .input_frames
            .load(Ordering::Relaxed)
            < 48_000
        {
            self.generator.poll();
            self.poll_measurement();
            if Instant::now() > deadline {
                return Err("Generator measurement timed out".into());
            }
            if let Some(e) = &self.error {
                return Err(e.clone());
            }
            std::thread::sleep(Duration::from_millis(5));
        }
        // No UI result/feedback consumption for a full second. Both execution
        // and the common input/analysis workers must continue independently.
        let count = self
            .core
            .as_ref()
            .unwrap()
            .metrics
            .input_frames
            .load(Ordering::Relaxed);
        std::thread::sleep(Duration::from_secs(1));
        assert!(
            self.core
                .as_ref()
                .unwrap()
                .metrics
                .input_frames
                .load(Ordering::Relaxed)
                > count + 24_000
        );
        self.stop();
        let mut snapshot = self.pending_stop.take().unwrap().wait();
        self.accept_snapshot(&mut snapshot);
        self.generator.poll();
        assert_eq!(
            self.generator.status.state,
            crate::generator::State::Running
        );
        let document = self.capture_results()?;
        document.validate()?;
        assert_eq!(document.loss.capture_dropped_samples, 0);
        assert!(!document.loss.input_failed);
        assert!((self.lockin_result.amplitude_peak.unwrap() - 0.0625).abs() < 1e-8);
        assert!((self.lockin_result.phase_degrees.unwrap() - 30.0).abs() < 1e-6);
        assert!((self.lockin_result.reference_frequency_hz.unwrap() - 750.0).abs() < 1e-7);
        assert!((self.analyzer.power()[128].sqrt() - 0.0625).abs() < 1e-8);
        assert!((self.measurements[1].rms - 0.0625 / 2.0_f64.sqrt()).abs() < 1e-8);
        assert!(
            document
                .generator_output
                .as_ref()
                .unwrap()
                .stationary(self.lockin_result.sample_range.clone())
                .is_some()
        );
        std::fs::create_dir_all("dist/generator-qa").map_err(|e| e.to_string())?;
        let saved = self.capture_settings()?;
        settings::save(
            std::path::Path::new("dist/generator-qa/settings.json"),
            &saved,
        )?;
        export::save(
            std::path::Path::new("dist/generator-qa/results.json"),
            &document,
        )?;
        crate::results::save_csv(
            std::path::Path::new("dist/generator-qa/results.csv"),
            &document,
        )?;
        let loaded = crate::results::load(std::path::Path::new("dist/generator-qa/results.json"))?;
        assert_eq!(loaded, document);
        self.generator.stop();
        let deadline = Instant::now() + Duration::from_secs(5);
        while !self.generator.stopped() {
            self.generator.poll();
            if Instant::now() > deadline {
                return Err("Generator Stop timed out".into());
            }
            std::thread::sleep(Duration::from_millis(2));
        }
        self.restore_settings(settings::load(std::path::Path::new(
            "dist/generator-qa/settings.json",
        ))?)?;
        while self.generator.pending {
            self.generator.poll();
            if Instant::now() > deadline {
                return Err("Generator restore timed out".into());
            }
            std::thread::sleep(Duration::from_millis(2));
        }
        assert!(self.generator.stopped());
        assert!(!self.running());
        assert_eq!(
            self.capture_results()?.generator_output,
            document.generator_output
        );
        // Leave a live Generator alongside held measurements for the screenshot.
        self.generator.start();
        println!(
            "Generator UI OK: actual 2ch f64 frames, Scope/Spectrum/Lock-in, 1 s UI stall, independent input/output Stop, JSON/CSV roundtrip, OFF restore"
        );
        Ok(())
    }
    pub(super) fn generator_transport(&mut self, ui: &mut egui::Ui) {
        let g = &mut self.generator;
        ui.horizontal_wrapped(|ui| {
            ui.label(
                RichText::new(format!("OUTPUT · {} · Internal loopback", g.label()))
                    .monospace()
                    .color(if g.stopped() { MUTED } else { GREEN }),
            );
            if ui.small_button("Stop all outputs").clicked() {
                g.stop();
            }
            ui.label(
                RichText::new("Input Stop holds the measurement; output continues.")
                    .small()
                    .color(MUTED),
            );
        });
    }

    pub(super) fn generator_panel(&mut self, ui: &mut egui::Ui) {
        let input_running = self.running() || self.pending_stop.is_some();
        let restoring =
            self.workspace_restoring || self.settings_task == Some(SettingsTask::Restore);
        egui::Frame::new()
            .fill(Color32::from_rgb(15, 22, 29))
            .stroke(Stroke::new(1.0, BORDER))
            .corner_radius(5.0)
            .inner_margin(10.0)
            .show(ui, |ui| {
                ui.horizontal_wrapped(|ui| {
                    ui.label(RichText::new("Generator").strong().color(GREEN));
                    ui.label("Internal loopback · 2ch · f64 · nominal Fs");
                    let g = &mut self.generator;
                    let mut rate = g.rate;
                    ui.add_enabled_ui(g.stopped() && !input_running && !restoring, |ui| {
                        egui::ComboBox::from_id_salt("generator_rate")
                            .selected_text(format!("{} Hz", rate))
                            .show_ui(ui, |ui| {
                                for value in output::RATES {
                                    ui.selectable_value(&mut rate, value, format!("{value} Hz"));
                                }
                            });
                    });
                    if rate != g.rate {
                        match g.worker.set_rate(rate, g.settings) {
                            Ok(id) => {
                                g.requested_id = id;
                                g.rate = rate;
                                g.pending = true;
                                g.error = None;
                            }
                            Err(e) => g.error = Some(e),
                        }
                    }
                    ui.add_enabled_ui(!g.stopping && !restoring, |ui| {
                        if ui
                            .button(if g.stopped() {
                                "Start output"
                            } else {
                                "Stop output"
                            })
                            .clicked()
                        {
                            if g.stopped() {
                                g.start();
                            } else {
                                g.stop();
                            }
                        }
                        if ui
                            .add_enabled(
                                !g.stopped() && !g.starting,
                                egui::Button::new("Align phases"),
                            )
                            .clicked()
                        {
                            match g.worker.align() {
                                Ok(id) => {
                                    g.pending = true;
                                    g.requested_id = id;
                                }
                                Err(e) => g.error = Some(e),
                            }
                        }
                    });
                });
                ui.horizontal_wrapped(|ui| {
                    if ui
                        .add_enabled(
                            !input_running && !self.busy && !restoring,
                            egui::Button::new("Observe Generator")
                                .selected(self.source == Source::Generator),
                        )
                        .clicked()
                        && self.source != Source::Generator
                    {
                        self.source = Source::Generator;
                        self.switch_source();
                    }
                    ui.label(
                        RichText::new("Select ON channels, then Start output and Start input.")
                            .small()
                            .color(MUTED),
                    );
                });
                let g = &mut self.generator;
                ui.horizontal_wrapped(|ui| {
                    ui.label(
                        RichText::new(if g.pending {
                            "PENDING"
                        } else if g.status.transitioning() {
                            "TRANSITION"
                        } else {
                            "APPLIED"
                        })
                        .monospace()
                        .color(YELLOW),
                    );
                    ui.label(
                        RichText::new(format!(
                            "Applied Fs: {} Hz · sine amplitude uses FS peak",
                            g.status.nominal_sample_rate,
                        ))
                        .small()
                        .color(MUTED),
                    );
                });
                if let Some(error) = &g.error {
                    ui.colored_label(TRIGGER, error);
                }
                if matches!(g.status.state, generator::State::Error(_))
                    && !input_running
                    && ui.button("Reset output (stays OFF)").clicked()
                {
                    match g.worker.set_rate(g.rate, g.settings) {
                        Ok(id) => {
                            g.pending = true;
                            g.requested_id = id;
                        }
                        Err(e) => g.error = Some(e),
                    }
                }
                ui.collapsing("Output details", |ui| {
                    ui.label(format!(
                        "generation {} · revision {} · applied sample {} · transition ends {}, {}",
                        g.status.output_generation,
                        g.status.revision,
                        g.status.applied_sample,
                        g.status.transition_end[0],
                        g.status.transition_end[1]
                    ));
                    for (i, s) in g.status.settings.signals.iter().enumerate() {
                        ui.label(format!(
                            "Applied GEN {}: {} Hz · {} dBFS peak · {}° · {}",
                            i + 1,
                            s.frequency_hz,
                            s.amplitude_dbfs,
                            s.phase_degrees,
                            if s.enabled { "ON" } else { "OFF" }
                        ));
                    }
                });
                let mut settings = g.settings;
                let editable = !g.stopping
                    && !restoring
                    && !matches!(
                        g.status.state,
                        generator::State::Stopping | generator::State::Error(_)
                    );
                let routing = g.stopped();
                ui.add_enabled_ui(editable, |ui| {
                    if ui.available_width() >= 680.0 {
                        ui.columns(2, |cols| {
                            for (i, col) in cols.iter_mut().enumerate() {
                                generator_card(col, g, &mut settings, i, routing);
                            }
                        });
                    } else if ui.available_height() >= 620.0 {
                        for i in 0..2 {
                            generator_card(ui, g, &mut settings, i, routing);
                        }
                    } else {
                        // One compact card with a fixed summary for both outputs.
                        ui.horizontal(|ui| {
                            for (i, s) in settings.signals.iter().enumerate() {
                                ui.selectable_value(
                                    &mut g.selected,
                                    i,
                                    format!(
                                        "GEN {} · OUT {} · {}",
                                        i + 1,
                                        s.output_channel
                                            .map_or("—".into(), |c| (c + 1).to_string()),
                                        if s.enabled { "ON" } else { "OFF" }
                                    ),
                                );
                            }
                        });
                        generator_card(ui, g, &mut settings, g.selected, routing);
                    }
                });
                if settings != g.settings {
                    g.configure(settings);
                }
            });
    }
}

fn generator_card(
    ui: &mut egui::Ui,
    g: &mut GeneratorUi,
    settings: &mut generator::Settings,
    index: usize,
    routing: bool,
) {
    let color = if index == 0 { GREEN } else { BLUE };
    let s = &mut settings.signals[index];
    egui::Frame::new()
        .fill(Color32::from_rgb(7, 14, 19))
        .stroke(Stroke::new(1.0, color.gamma_multiply(0.45)))
        .corner_radius(4.0)
        .inner_margin(8.0)
        .show(ui, |ui| {
            ui.horizontal(|ui| {
                ui.label(
                    RichText::new(format!("GEN {} · Sine", index + 1))
                        .strong()
                        .color(color),
                );
                ui.checkbox(&mut s.enabled, "ON");
                ui.add_enabled_ui(routing, |ui| {
                    egui::ComboBox::from_id_salt(("generator_channel", index))
                        .selected_text(
                            s.output_channel
                                .map_or("Unassigned".into(), |c| format!("OUT {}", c + 1)),
                        )
                        .show_ui(ui, |ui| {
                            ui.selectable_value(&mut s.output_channel, None, "Unassigned");
                            for c in 0..2 {
                                ui.selectable_value(
                                    &mut s.output_channel,
                                    Some(c),
                                    format!("OUT {}", c + 1),
                                );
                            }
                        });
                });
            });
            ui.horizontal(|ui| {
                ui.label(RichText::new("Step").small().color(MUTED));
                egui::ComboBox::from_id_salt(("generator_step", index))
                    .selected_text(format!("{}", g.step))
                    .show_ui(ui, |ui| {
                        for value in [0.01, 0.1, 1.0, 10.0, 100.0] {
                            ui.selectable_value(&mut g.step, value, format!("{value}"));
                        }
                    });
                ui.label(
                    RichText::new("Enter / focus to apply · Esc to cancel")
                        .small()
                        .color(MUTED),
                );
            });
            for (field, (title, unit, value)) in [
                ("FREQUENCY", "Hz", &mut s.frequency_hz),
                ("AMPLITUDE · PEAK", "dBFS", &mut s.amplitude_dbfs),
                ("PHASE · LEAD", "°", &mut s.phase_degrees),
            ]
            .into_iter()
            .enumerate()
            {
                ui.label(RichText::new(title).small().color(MUTED));
                match numeric_field(
                    ui,
                    (index, field),
                    &mut g.texts[index][field],
                    &mut g.edited[index][field],
                    *value,
                    g.step,
                    unit,
                ) {
                    Ok(Some(next)) => *value = next,
                    Ok(None) => {}
                    Err(e) => g.error = Some(e),
                }
            }
            preview(ui, *s, color);
        });
}

fn numeric_field(
    ui: &mut egui::Ui,
    id: (usize, usize),
    text: &mut String,
    edited: &mut bool,
    value: f64,
    step: f64,
    unit: &str,
) -> Result<Option<f64>, String> {
    let widget_id = ui.make_persistent_id(("generator_number", id));
    if !ui.memory(|m| m.has_focus(widget_id)) && !*edited {
        *text = format!("{value:.3}");
        *edited = false;
    }
    let mut next = None;
    let mut invalid = false;
    ui.horizontal(|ui| {
        let width = (ui.available_width() - 120.0).max(100.0);
        let response = ui.add(
            egui::TextEdit::singleline(text)
                .id(widget_id)
                .font(egui::FontId::monospace(27.0))
                .desired_width(width),
        );
        *edited |= response.changed();
        // egui releases focus at the start of an Escape frame, before TextEdit
        // returns. That loss must cancel rather than commit a dirty value.
        let escape = (response.has_focus() || response.lost_focus())
            && ui.input(|i| i.key_pressed(egui::Key::Escape));
        let enter = response.has_focus() && ui.input(|i| i.key_pressed(egui::Key::Enter));
        if escape {
            *text = format!("{value:.3}");
            *edited = false;
            response.surrender_focus();
        } else if *edited && (response.lost_focus() || enter) {
            match text.trim().parse::<f64>() {
                Ok(v) if v.is_finite() => next = Some(v),
                _ => invalid = true,
            }
            if enter {
                response.surrender_focus();
            }
            *edited = false;
        }
        ui.label(RichText::new(unit).color(MUTED));
        if ui.small_button("−").clicked() {
            next = Some(next.unwrap_or(value) - step);
        }
        if ui.small_button("+").clicked() {
            next = Some(next.unwrap_or(value) + step);
        }
        if response.has_focus() {
            let delta = ui.input(|i| {
                if i.key_pressed(egui::Key::ArrowUp) {
                    Some(step)
                } else if i.key_pressed(egui::Key::ArrowDown) {
                    Some(-step)
                } else {
                    None
                }
            });
            if let Some(delta) = delta {
                let base = if *edited {
                    text.trim().parse::<f64>().ok()
                } else {
                    Some(value)
                };
                if let Some(base) = base.filter(|v| v.is_finite()) {
                    next = Some(base + delta);
                    *text = format!("{:.3}", base + delta);
                    *edited = false;
                } else {
                    invalid = true;
                }
            }
        }
    });
    if invalid {
        Err("Enter a finite number; settings were not applied".into())
    } else {
        Ok(next)
    }
}

fn preview(ui: &mut egui::Ui, s: generator::Signal, color: Color32) {
    ui.label(
        RichText::new(format!(
            "Settings preview · ±{:.6} FS peak · {:.3} ms / 2 cycles",
            s.amplitude_peak(),
            2000.0 / s.frequency_hz
        ))
        .small()
        .color(MUTED),
    );
    let (rect, _) = ui.allocate_exact_size(vec2(ui.available_width(), 52.0), egui::Sense::hover());
    if !ui.is_rect_visible(rect) {
        return;
    }
    let p = ui.painter();
    p.line_segment(
        [
            pos2(rect.left(), rect.center().y),
            pos2(rect.right(), rect.center().y),
        ],
        Stroke::new(1.0, BORDER),
    );
    let points: Vec<_> = (0..=128)
        .map(|n| {
            let x = n as f64 / 128.0;
            let y = (std::f64::consts::TAU * 2.0 * x + s.phase_degrees.to_radians()).sin();
            pos2(
                rect.left() + x as f32 * rect.width(),
                rect.center().y - y as f32 * rect.height() * 0.45,
            )
        })
        .collect();
    p.add(egui::Shape::line(points, Stroke::new(1.5, color)));
}

#[cfg(test)]
mod tests {
    use super::*;
    fn key(key: egui::Key, modifiers: egui::Modifiers) -> egui::Event {
        egui::Event::Key {
            key,
            physical_key: None,
            pressed: true,
            repeat: false,
            modifiers,
        }
    }
    fn edit_frame(
        ctx: &egui::Context,
        text: &mut String,
        edited: &mut bool,
        events: Vec<egui::Event>,
        focus: bool,
    ) -> Result<Option<f64>, String> {
        let mut result = Ok(None);
        let output = ctx.run_ui(
            egui::RawInput {
                screen_rect: Some(egui::Rect::from_min_size(
                    pos2(0.0, 0.0),
                    vec2(600.0, 200.0),
                )),
                events,
                ..Default::default()
            },
            |ui| {
                if focus {
                    let id = ui.make_persistent_id(("generator_number", (0usize, 0usize)));
                    ui.memory_mut(|m| m.request_focus(id));
                }
                result = numeric_field(ui, (0, 0), text, edited, 750.123456789, 1.0, "Hz");
            },
        );
        output.drop_without_applying_deltas();
        result
    }
    #[test]
    fn numeric_input_cancels_escape_commits_enter_and_steps_drafts_without_rounding_applied_values()
    {
        for (finish, expected) in [
            (egui::Key::Escape, None),
            (egui::Key::Enter, Some(750.987654321)),
            (egui::Key::Tab, Some(750.987654321)),
            (egui::Key::ArrowUp, Some(751.987654321)),
            (egui::Key::ArrowDown, Some(749.987654321)),
        ] {
            let ctx = egui::Context::default();
            let mut text = String::new();
            let mut edited = false;
            edit_frame(&ctx, &mut text, &mut edited, vec![], true).unwrap();
            let result = edit_frame(
                &ctx,
                &mut text,
                &mut edited,
                vec![
                    key(egui::Key::A, egui::Modifiers::COMMAND),
                    egui::Event::Text("750.987654321".into()),
                ],
                false,
            )
            .unwrap();
            assert_eq!(result, None);
            assert_eq!(text, "750.987654321");
            assert!(edited);
            let first = edit_frame(
                &ctx,
                &mut text,
                &mut edited,
                vec![key(finish, egui::Modifiers::NONE)],
                false,
            )
            .unwrap();
            let second = edit_frame(&ctx, &mut text, &mut edited, vec![], false).unwrap();
            assert_eq!(first.or(second), expected, "{finish:?}");
            assert!(!edited);
        }
        let ctx = egui::Context::default();
        let mut text = String::new();
        let mut edited = false;
        edit_frame(&ctx, &mut text, &mut edited, vec![], true).unwrap();
        assert_eq!(
            edit_frame(
                &ctx,
                &mut text,
                &mut edited,
                vec![key(egui::Key::Enter, egui::Modifiers::NONE)],
                false
            )
            .unwrap(),
            None
        );
    }
}
