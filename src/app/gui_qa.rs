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
        Ok(())
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
}
