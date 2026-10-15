//! Drive the real shell widgets with egui events, without a second audio runtime.
//! Rendered text locates controls; assertions inspect the resulting app state.
use super::*;

struct Driver {
    ctx: egui::Context,
    size: egui::Vec2,
    native_scale: f32,
    output: egui::FullOutput,
}

impl Driver {
    fn new() -> Self {
        Self {
            ctx: egui::Context::default(),
            size: vec2(1440.0, 1000.0),
            native_scale: 1.0,
            output: egui::FullOutput::default(),
        }
    }

    fn frame(&mut self, app: &mut ScopeApp, events: Vec<egui::Event>) {
        let mut input = egui::RawInput {
            screen_rect: Some(egui::Rect::from_min_size(pos2(0.0, 0.0), self.size)),
            events,
            ..Default::default()
        };
        input
            .viewports
            .get_mut(&egui::ViewportId::ROOT)
            .unwrap()
            .native_pixels_per_point = Some(self.native_scale);
        self.output = self.ctx.run_ui(input, |ui| {
            app.shell_header(ui);
            app.shell_sides(ui);
            app.shell_central(ui);
        });
        self.output.textures_delta.clear();
    }

    fn position(&self, label: &str) -> Result<egui::Pos2, String> {
        fn locate(shape: &egui::Shape, clip: egui::Rect, label: &str) -> Option<egui::Pos2> {
            match shape {
                egui::Shape::Text(text) if text.galley.text() == label => {
                    let center = text.visual_bounding_rect().center();
                    clip.contains(center).then_some(center)
                }
                egui::Shape::Vec(shapes) => {
                    shapes.iter().rev().find_map(|s| locate(s, clip, label))
                }
                _ => None,
            }
        }
        self.output
            .shapes
            .iter()
            .rev()
            .filter_map(|s| locate(&s.shape, s.clip_rect, label))
            .find(|p| {
                self.ctx
                    .interactive_rects_last_pass()
                    .iter()
                    .any(|r| r.contains(*p) && r.height() < 80.0)
            })
            .ok_or_else(|| format!("GUI interaction control not visible: {label}"))
    }

    fn click(&mut self, app: &mut ScopeApp, label: &str) -> Result<(), String> {
        let pos = self.position(label)?;
        self.click_at(app, pos);
        Ok(())
    }

    fn click_at(&mut self, app: &mut ScopeApp, pos: egui::Pos2) {
        for pressed in [true, false] {
            self.frame(
                app,
                vec![
                    egui::Event::PointerMoved(pos),
                    egui::Event::PointerButton {
                        pos,
                        button: egui::PointerButton::Primary,
                        pressed,
                        modifiers: egui::Modifiers::NONE,
                    },
                ],
            );
        }
        // Panels and menus settle on the following frame, as in the desktop UI.
        self.frame(app, vec![]);
    }

    fn key(&mut self, app: &mut ScopeApp, key: egui::Key, modifiers: egui::Modifiers) {
        for pressed in [true, false] {
            self.frame(
                app,
                vec![
                    egui::Event::ModifiersChanged(modifiers),
                    egui::Event::Key {
                        key,
                        physical_key: None,
                        pressed,
                        repeat: false,
                        modifiers,
                    },
                ],
            );
        }
        self.frame(
            app,
            vec![egui::Event::ModifiersChanged(egui::Modifiers::NONE)],
        );
    }

    fn resize(&mut self, app: &mut ScopeApp, size: egui::Vec2, zoom: f32, native_scale: f32) {
        self.size = size;
        self.native_scale = native_scale;
        self.ctx.set_zoom_factor(zoom);
        for _ in 0..3 {
            self.frame(app, vec![]);
        }
    }
}

impl ScopeApp {
    pub(super) fn check_esd_ui(&mut self) -> Result<(), String> {
        self.spectrum_settings.select_quantity(Quantity::Esd);
        self.spectrum_channel = 0;
        self.spectrum_display = settings::SpectrumDisplay::default();
        self.spectrum_display.auto_level = true;
        self.frequency_scale = FrequencyScale::Linear;
        self.span_hz = 5000.0;
        self.spectrum_min_hz = 0.0;
        self.calibration.channel = 0;
        self.calibration.gain = 4.0;
        self.calibration.offset = 0.0;
        self.calibration.unit = "V".into();
        self.calibration.conditions = "Synthetic decaying impact; no physical ADC reference".into();
        self.calibration.apply()?;
        self.calibration.captured = self.calibration.pending.clone();
        self.history.clear_at(0);
        let mut time_energy = 0.0;
        for n in 0..self.spectrum_settings.size {
            let time = n as f64 / self.sample_rate as f64;
            let sample =
                0.25 * (-time * 100.0).exp() * (std::f64::consts::TAU * 1000.0 * time).sin();
            self.history.push([sample, 0.0]);
            time_energy += (4.0 * sample).powi(2) / self.sample_rate as f64;
        }
        self.update_spectrum(true);
        self.refresh_spectrum_readouts(self.spectrum_view());
        assert!((self.spectrum_energy.unwrap() / time_energy - 1.0).abs() < 1e-12);
        assert_eq!(self.analyzer.db_unit(), "dB re 1 V²·s/Hz");
        assert_eq!(self.analyzer.settings().quantity, Quantity::Esd);
        self.cursors.set_frequency(0, 1000.0);
        self.cursors.set_frequency(1, 1500.0);
        println!(
            "ESD UI OK: calibrated decaying impact, shared spectrum plot/cursors, V²·s/Hz, Parseval energy, rectangular/no-average/no-DC preset"
        );
        Ok(())
    }

    pub(super) fn check_redesign_interactions(&mut self) -> Result<(), String> {
        let saved = self.presentation.clone();
        let saved_shell = self.shell.clone();
        let generation = self.input_generation;
        let running = self.running();
        let command = self.generator.command_marker();
        let held = self.capture_results().ok();
        let conditions = (
            self.scope_channels,
            self.spectrum_settings,
            self.lockin_settings,
            self.comparison_settings,
            self.generator.settings,
        );
        self.presentation = Presentation::default();
        self.shell = shell::Shell::default();
        let mut driver = Driver::new();
        driver.frame(self, vec![]);
        driver.frame(self, vec![]);

        let scope_display = (self.enabled, self.scope_selected, self.scope_vertical);
        let readings = self.scope_readings;
        for index in 0..SCOPE_CHANNELS {
            driver.click(self, &format!("CH{}", index + 1))?;
            assert_eq!(self.scope_selected, index);
            assert_eq!(self.enabled, scope_display.0);
            let pos = driver.position(&format!("CH{}", index + 1))?;
            let selection = driver
                .ctx
                .interactive_rects_last_pass()
                .into_iter()
                .find(|r| r.contains(pos) && (r.height() - 40.0).abs() < 1.0)
                .ok_or("Scope channel selection area missing")?;
            driver.click_at(self, pos2(selection.right() + 10.0, selection.top() + 13.0));
            assert_ne!(self.enabled[index], scope_display.0[index]);
            assert_eq!(self.scope_selected, index);
            assert_eq!(self.scope_readings, readings);
            driver.click_at(self, pos2(selection.right() + 10.0, selection.top() + 13.0));
            assert_eq!(self.enabled, scope_display.0);
        }
        // Drag the actual right-side range control after selecting CH4.
        let pos = driver
            .output
            .shapes
            .iter()
            .filter_map(|s| {
                if let egui::Shape::Text(t) = &s.shape
                    && t.galley.text().ends_with(" FS/div")
                {
                    Some(t.visual_bounding_rect().center())
                } else {
                    None
                }
            })
            .max_by(|a, b| a.x.total_cmp(&b.x))
            .ok_or("Scope vertical range control missing")?;
        driver.frame(
            self,
            vec![
                egui::Event::PointerMoved(pos),
                egui::Event::PointerButton {
                    pos,
                    button: egui::PointerButton::Primary,
                    pressed: true,
                    modifiers: egui::Modifiers::NONE,
                },
            ],
        );
        driver.frame(self, vec![egui::Event::PointerMoved(pos + vec2(30.0, 0.0))]);
        driver.frame(
            self,
            vec![egui::Event::PointerButton {
                pos: pos + vec2(30.0, 0.0),
                button: egui::PointerButton::Primary,
                pressed: false,
                modifiers: egui::Modifiers::NONE,
            }],
        );
        assert_ne!(
            self.scope_vertical[3].fs_per_div,
            scope_display.2[3].fs_per_div
        );
        assert_eq!(self.scope_vertical[..3], scope_display.2[..3]);
        assert_eq!(self.scope_readings, readings);
        if held.is_none() && self.history.is_empty() {
            let timebase = self.ms_per_div;
            let vertical = self.scope_vertical;
            let wave = pos2(driver.position("CH2")?.x, driver.position("CH2")?.y - 100.0);
            driver.frame(
                self,
                vec![
                    egui::Event::PointerMoved(wave),
                    egui::Event::MouseWheel {
                        unit: egui::MouseWheelUnit::Point,
                        phase: egui::TouchPhase::Move,
                        delta: vec2(0.0, 30.0),
                        modifiers: egui::Modifiers::NONE,
                    },
                ],
            );
            assert_ne!(self.ms_per_div, timebase);
            assert_eq!(self.scope_vertical, vertical);
            let horizontal = self.ms_per_div;
            driver.frame(
                self,
                vec![
                    egui::Event::ModifiersChanged(egui::Modifiers::SHIFT),
                    egui::Event::MouseWheel {
                        unit: egui::MouseWheelUnit::Point,
                        phase: egui::TouchPhase::Move,
                        delta: vec2(0.0, 30.0),
                        modifiers: egui::Modifiers::SHIFT,
                    },
                ],
            );
            assert_eq!(self.ms_per_div, horizontal);
            assert_ne!(self.scope_vertical[3], vertical[3]);
            assert_eq!(self.scope_vertical[..3], vertical[..3]);
            driver.frame(
                self,
                vec![
                    egui::Event::PointerMoved(pos2(0.0, 0.0)),
                    egui::Event::ModifiersChanged(egui::Modifiers::NONE),
                ],
            );
            self.ms_per_div = timebase;
        }
        // Merely showing the new sliders must preserve values produced by
        // Autoset, wheel zoom and settings, beyond their displayed precision.
        let saved_axes = (
            self.ms_per_div,
            self.scope_horizontal_position,
            self.trigger,
        );
        self.ms_per_div = 1.234567;
        self.scope_horizontal_position = -1.234567;
        self.trigger.level = 0.123456789;
        self.scope_vertical[3].fs_per_div = 0.1234567;
        self.scope_vertical[3].offset = -0.123456789;
        let unedited = (
            self.ms_per_div,
            self.scope_horizontal_position,
            self.trigger,
            self.scope_vertical,
        );
        driver.frame(self, vec![]);
        assert_eq!(
            (
                self.ms_per_div,
                self.scope_horizontal_position,
                self.trigger,
                self.scope_vertical
            ),
            unedited
        );
        driver.click(self, "Zero level")?;
        assert_eq!(self.trigger.level, 0.0);
        assert_eq!(self.scope_vertical, unedited.3);
        driver.click(self, "Centre horizontal")?;
        assert_eq!(self.scope_horizontal_position, 0.0);
        assert_eq!(self.ms_per_div, unedited.0);
        driver.click(self, "Zero offset")?;
        assert_eq!(self.scope_vertical[3].offset, 0.0);
        assert_eq!(self.scope_vertical[3].fs_per_div, unedited.3[3].fs_per_div);
        assert_eq!(self.scope_vertical[..3], unedited.3[..3]);
        assert_eq!(self.scope_readings, readings);
        (
            self.ms_per_div,
            self.scope_horizontal_position,
            self.trigger,
        ) = saved_axes;
        (self.enabled, self.scope_selected, self.scope_vertical) = scope_display;
        self.dirty = true;
        driver.frame(self, vec![]);

        let spectrum_display = self.spectrum_display;
        self.spectrum_display.overlay_channels = [0, 0, 0];
        driver.click(self, "Spectrum")?;
        let average = self.analyzer.average();
        for index in 0..4 {
            driver.click(self, &format!("CH{}", index + 1))?;
            assert_eq!(self.spectrum_display.selected, index);
            assert_eq!(self.spectrum_display.enabled, spectrum_display.enabled);
            let pos = driver.position(&format!("CH{}", index + 1))?;
            let selection = driver
                .ctx
                .interactive_rects_last_pass()
                .into_iter()
                .find(|r| r.contains(pos) && (r.height() - 40.0).abs() < 1.0)
                .ok_or("Spectrum channel selection area missing")?;
            let toggle = pos2(selection.right() + 10.0, selection.top() + 13.0);
            driver.click_at(self, toggle);
            assert_ne!(
                self.spectrum_display.enabled[index],
                spectrum_display.enabled[index]
            );
            assert_eq!(self.spectrum_display.selected, index);
            assert_eq!(self.analyzer.average(), average);
            driver.click_at(self, toggle);
            assert_eq!(self.spectrum_display.enabled, spectrum_display.enabled);
        }
        driver.click(self, "Auto")?;
        assert!(self.spectrum_display.auto_level);
        let view = self.spectrum_view();
        assert!(view.max_hz <= self.sample_rate as f32 / 2.0);
        assert!(view.min_hz >= 0.0 && view.min_hz < view.max_hz);
        assert!(view.floor_db < view.ceiling_db);
        driver.click(self, "Manual")?;
        assert!(!self.spectrum_display.auto_level);
        self.spectrum_display = spectrum_display;
        self.spectrum_dirty = true;
        self.spectrum_numeric_key = None;
        self.check_spectrum_interactions(&mut driver)?;

        for instrument in Instrument::ALL {
            driver.click(self, instrument.name())?;
            assert_eq!(self.presentation.screen, Screen::Single(instrument));
            driver.click(self, instrument.name())?;
            assert_eq!(self.presentation.screen, Screen::Single(instrument));
            driver.position("Stop output")?;
        }
        driver.key(self, egui::Key::Num1, egui::Modifiers::CTRL);
        driver.click(self, "Pair with…")?;
        driver.click(self, "Generator")?;
        assert_eq!(
            self.presentation.console.instruments,
            [Instrument::Scope, Instrument::Generator]
        );
        assert_eq!(self.presentation.selected(), Some(Instrument::Generator));
        let pair = self.presentation.console.clone();
        driver.key(self, egui::Key::Num1, egui::Modifiers::CTRL);
        driver.click(self, "Measurement console")?;
        assert_eq!(self.presentation.console, pair);
        driver.key(self, egui::Key::ArrowLeft, egui::Modifiers::CTRL);
        assert_eq!(self.presentation.selected(), Some(Instrument::Scope));
        driver.key(self, egui::Key::ArrowRight, egui::Modifiers::CTRL);
        assert_eq!(self.presentation.selected(), Some(Instrument::Generator));
        driver.key(self, egui::Key::Num1, egui::Modifiers::CTRL);
        driver.click(self, "Pair with…")?;
        driver.click(self, "Spectrum")?;
        driver.click(self, "Undo replacement")?;
        assert_eq!(self.presentation.console, pair);
        for instrument in Instrument::ALL {
            driver.click(self, "Add instrument…")?;
            driver.click(self, instrument.name())?;
            assert_eq!(self.presentation.selected(), Some(instrument));
        }
        assert_eq!(self.presentation.console.instruments.len(), 7);
        driver.click(self, "Tabs")?;
        for _ in 0..7 {
            driver.click(self, "Remove from view")?;
        }
        assert!(self.presentation.console.instruments.is_empty());
        assert_eq!(self.presentation.selected(), None);

        // Requested layout and ratio survive a round trip through a small view,
        // app zoom, and simulated native scale events. Native monitor QA is separate.
        driver.key(self, egui::Key::Num1, egui::Modifiers::CTRL);
        driver.click(self, "Pair with…")?;
        driver.click(self, "Generator")?;
        self.presentation.details_visible = false;
        self.presentation.console.split = 0.4;
        driver.frame(self, vec![]);
        let console = self.presentation.console.clone();
        for native_scale in [1.0, 2.0] {
            driver.resize(self, vec2(720.0, 528.0), 1.25, native_scale);
            driver.position("Stop output")?;
            assert_eq!(self.presentation.console, console);
            driver.resize(self, vec2(1440.0, 1000.0), 1.0, 1.0);
            assert_eq!(self.presentation.console, console);
        }
        for tab in ["Input", "Output", "Calibration"] {
            driver.click(self, "I/O")?;
            driver.click(self, tab)?;
            assert!(self.shell.io.is_some());
            driver.position("Stop output")?;
            driver.click(self, "Back to instruments")?;
            assert!(self.shell.io.is_none());
            assert_eq!(self.presentation.console, console);
        }
        driver.resize(self, vec2(720.0, 528.0), 1.25, 1.0);
        self.presentation.details_visible = true;
        for (instrument, key) in Instrument::ALL.into_iter().zip([
            egui::Key::Num1,
            egui::Key::Num2,
            egui::Key::Num3,
            egui::Key::Num4,
            egui::Key::Num5,
            egui::Key::Num6,
            egui::Key::Num7,
        ]) {
            driver.key(self, key, egui::Modifiers::CTRL);
            assert_eq!(self.presentation.screen, Screen::Single(instrument));
            if instrument == Instrument::Scope {
                driver.position("CH4")?;
            }
            driver.click(self, "Details")?;
            assert!(self.shell.narrow_details);
            driver.position("Stop output")?;
            driver.key(self, egui::Key::Escape, egui::Modifiers::NONE);
            assert!(!self.shell.narrow_details);
        }
        assert_eq!(self.input_generation, generation);
        assert_eq!(self.running(), running);
        assert_eq!(self.generator.command_marker(), command);
        assert_eq!(
            (
                self.scope_channels,
                self.spectrum_settings,
                self.lockin_settings,
                self.comparison_settings,
                self.generator.settings
            ),
            conditions
        );
        if let Some(held) = held {
            let measurement = |document: &export::Document| -> Result<serde_json::Value, String> {
                let mut value = serde_json::to_value(document).map_err(|e| e.to_string())?;
                value
                    .as_object_mut()
                    .unwrap()
                    .remove("exported_unix_seconds");
                Ok(value)
            };
            // Export time identifies this serialization, not the captured
            // measurement. A widget sequence can cross a wall-clock second.
            assert!(
                measurement(&self.capture_results()?)? == measurement(&held)?,
                "GUI interaction changed the held measurement"
            );
        }
        self.presentation = saved;
        self.shell = saved_shell;
        println!(
            "GUI interactions OK: widget clicks, keyboard navigation, details, I/O return, resize/scale; measurement and output commands unchanged"
        );
        Ok(())
    }

    fn check_spectrum_interactions(&mut self, driver: &mut Driver) -> Result<(), String> {
        let saved_settings = self.spectrum_settings;
        let saved_display = self.spectrum_display;
        let saved_axes = (self.frequency_scale, self.span_hz, self.spectrum_min_hz);
        let saved_cursors = std::mem::take(&mut self.cursors);
        let saved_active = self.active_cursor;
        let settings = Settings {
            averages: 1,
            quantity: Quantity::Amplitude,
            ..Settings::default()
        };
        let mut history = History::with_channels(settings.size, 2);
        for n in 0..settings.size {
            let phase = std::f64::consts::TAU * 128.0 * n as f64 / settings.size as f64;
            history.push([
                0.125 * phase.sin() + 0.0625 * (2.0 * phase).sin(),
                0.25 * phase.sin(),
            ]);
        }
        let mut analyzer = Analyzer::new(settings, self.sample_rate);
        assert!(analyzer.update(&history, 0));
        let mut result = spectrum::Result::empty(settings, self.sample_rate);
        analyzer.copy_result(&mut result);
        let saved_result = std::mem::replace(&mut self.analyzer, result);
        self.spectrum_settings = settings;
        self.spectrum_display = settings::SpectrumDisplay::default();
        self.frequency_scale = FrequencyScale::Linear;
        self.span_hz = 0.0;
        self.spectrum_min_hz = 0.0;
        self.active_cursor = 0;
        self.spectrum_dirty = true;
        self.spectrum_numeric_key = None;
        driver.resize(self, vec2(1440.0, 860.0), 1.0, 1.0);

        // All default groups fit the actual startup height without scrolling.
        let quantity = driver.position("Amplitude")?;
        let axis = driver.position("Log Hz")?;
        let cursor_a = driver.position("Cursor A")?;
        let average = driver.position("Average")?;
        let advanced = driver.position("Advanced analysis / diagnostics")?;
        assert!(
            quantity.y < axis.y
                && axis.y < cursor_a.y
                && cursor_a.y < average.y
                && average.y < advanced.y
        );
        driver.click(self, "PSD")?;
        assert_eq!(self.spectrum_settings.quantity, Quantity::Psd);
        assert_eq!(self.analyzer.settings().quantity, Quantity::Amplitude);
        driver.click(self, "Transient (ESD)")?;
        assert_eq!(self.spectrum_settings.quantity, Quantity::Esd);
        assert_eq!(self.spectrum_settings.window, spectrum::Window::Rectangular);
        assert_eq!(self.spectrum_settings.averages, 1);
        assert!(!self.spectrum_settings.remove_dc);
        assert_eq!(self.analyzer.settings().quantity, Quantity::Amplitude);
        // Restore the held fixture's next-run settings before cursor checks.
        driver.click(self, "Amplitude")?;
        self.spectrum_settings = settings;
        driver.click(self, "Average")?;
        assert_eq!(
            self.spectrum_settings.averages,
            self.spectrum_display.average_weight
        );
        driver.position("Advanced analysis / diagnostics")?;
        driver.click(self, "Average")?;
        assert_eq!(self.spectrum_settings.averages, 1);

        let rect = driver
            .output
            .shapes
            .iter()
            .find_map(|s| {
                if let egui::Shape::Callback(callback) = &s.shape {
                    Some(callback.rect)
                } else {
                    None
                }
            })
            .ok_or("Spectrum plot rectangle missing")?;
        let view = self.spectrum_view();
        let frequency = self.sample_rate as f64 * 128.0 / settings.size as f64;
        let at = |hz: f64| {
            pos2(
                rect.left() + view.x(hz as f32) * rect.width(),
                rect.center().y,
            )
        };
        driver.click(self, "Cursor A")?;
        driver.click_at(self, at(frequency));
        let a = self.cursors.spectrum_frequencies_hz[0]
            .ok_or("Spectrum A did not respond to plot click")?;
        driver.click(self, "Cursor B")?;
        driver.click_at(self, at(2.0 * frequency));
        let b = self.cursors.spectrum_frequencies_hz[1]
            .ok_or("Spectrum B did not respond to plot click")?;
        assert_eq!(self.cursors.spectrum_frequencies_hz[0], Some(a));
        let reading_a = self.analyzer.cursor(a).unwrap();
        let reading_b = self.analyzer.cursor(b).unwrap();
        assert_eq!(reading_a.frequency_hz, frequency);
        assert_eq!(reading_b.frequency_hz, 2.0 * frequency);
        assert!((reading_a.value - 0.125).abs() < 1e-10);
        assert!((reading_b.value - 0.0625).abs() < 1e-10);
        assert!(driver.output.shapes.iter().any(|s| matches!(&s.shape,
            egui::Shape::Text(t) if t.galley.text().starts_with("Δf "))));

        let destination = at(3.0 * frequency);
        driver.frame(
            self,
            vec![
                egui::Event::PointerMoved(at(b)),
                egui::Event::PointerButton {
                    pos: at(b),
                    button: egui::PointerButton::Primary,
                    pressed: true,
                    modifiers: egui::Modifiers::NONE,
                },
            ],
        );
        driver.frame(self, vec![egui::Event::PointerMoved(destination)]);
        driver.frame(
            self,
            vec![egui::Event::PointerButton {
                pos: destination,
                button: egui::PointerButton::Primary,
                pressed: false,
                modifiers: egui::Modifiers::NONE,
            }],
        );
        assert_eq!(self.cursors.spectrum_frequencies_hz[0], Some(a));
        assert_ne!(self.cursors.spectrum_frequencies_hz[1], Some(b));
        driver.click(self, "Clear")?;
        assert_eq!(self.cursors.spectrum_frequencies_hz, [None; 2]);
        assert!(self.cursors.frequency_hz.is_none());

        self.analyzer = saved_result;
        self.spectrum_settings = saved_settings;
        self.spectrum_display = saved_display;
        (self.frequency_scale, self.span_hz, self.spectrum_min_hz) = saved_axes;
        self.cursors = saved_cursors;
        self.active_cursor = saved_active;
        self.spectrum_dirty = true;
        self.spectrum_numeric_key = None;
        driver.resize(self, vec2(1440.0, 1000.0), 1.0, 1.0);
        println!(
            "Spectrum controls OK: default-height groups, PSD/ESD/Amplitude, transient preset, averaging, independent A/B clicks and drag, known-bin readings, delta and Clear"
        );
        Ok(())
    }
}
