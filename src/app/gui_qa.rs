//! Drive the real shell widgets with egui events, without a second audio runtime.
//! Rendered text locates controls; assertions inspect the resulting app state.
use super::*;
use crate::generator;

mod scope;
mod sidebar;

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

    fn frame(&mut self, app: &mut ScopeApp, mut events: Vec<egui::Event>) {
        let modifiers = events
            .iter()
            .find_map(|event| match event {
                egui::Event::MouseWheel { modifiers, .. } => Some(*modifiers),
                _ => None,
            })
            .unwrap_or_default();
        events.insert(0, egui::Event::ModifiersChanged(modifiers));
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

    fn text_positions(&self, label: &str) -> Vec<egui::Pos2> {
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
            .collect()
    }

    fn position(&self, label: &str) -> Result<egui::Pos2, String> {
        self.text_positions(label)
            .into_iter()
            .find(|p| {
                self.ctx
                    .interactive_rects_last_pass()
                    .iter()
                    .any(|r| r.contains(*p) && r.height() < 80.0)
            })
            .ok_or_else(|| format!("GUI interaction control not visible: {label}"))
    }

    fn text_position(&self, label: &str) -> Result<egui::Pos2, String> {
        self.text_positions(label)
            .into_iter()
            .next()
            .ok_or_else(|| format!("GUI text not visible: {label}"))
    }

    fn visible_text_rect(&self, label: &str) -> Result<egui::Rect, String> {
        self.output
            .shapes
            .iter()
            .find_map(|s| {
                if let egui::Shape::Text(text) = &s.shape
                    && text.galley.text() == label
                    && s.clip_rect.contains_rect(text.visual_bounding_rect())
                    && self
                        .ctx
                        .content_rect()
                        .contains_rect(text.visual_bounding_rect())
                {
                    Some(text.visual_bounding_rect())
                } else {
                    None
                }
            })
            .ok_or_else(|| format!("GUI text clipped or missing: {label}"))
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

    fn check_header(&self) -> Result<(), String> {
        let menu = self
            .position(i18n::text("shell.menu"))
            .or_else(|_| self.position(i18n::text("common.file")))?;
        let output = self.text_position(i18n::text("generator.stop_output_2"))?;
        let input = ["▶  Start input", "▶  Start input (demo)", "■  Stop input"]
            .into_iter()
            .find_map(|label| self.text_positions(label).first().copied())
            .ok_or("Shared input control missing from header")?;
        assert!((menu.y - input.y).abs() < 2.0);
        assert!((output.y - input.y).abs() < 2.0);
        assert!(menu.x < output.x && output.x < input.x);
        assert!(input.x > self.size.x - 100.0);
        assert!(self.text_positions("MeasureLab").is_empty());
        let rect = self
            .ctx
            .interactive_rects_last_pass()
            .into_iter()
            .filter(|rect| rect.contains(menu) && rect.height() < 80.0)
            .min_by(|a, b| a.width().total_cmp(&b.width()))
            .ok_or("Header menu has no interactive bounds")?;
        assert!(rect.left() >= 0.0 && rect.right() <= self.size.x);
        let mut texts: Vec<_> = self
            .output
            .shapes
            .iter()
            .filter_map(|shape| {
                if let egui::Shape::Text(text) = &shape.shape
                    && text.visual_bounding_rect().top() < 20.0
                {
                    Some(text.visual_bounding_rect())
                } else {
                    None
                }
            })
            .collect();
        texts.sort_by(|a, b| a.left().total_cmp(&b.left()));
        for rect in &texts {
            assert!(rect.left() >= 0.0 && rect.right() <= self.size.x);
            assert!((rect.center().y - input.y).abs() < 2.0);
        }
        for pair in texts.windows(2) {
            assert!(pair[0].right() < pair[1].left(), "Header texts overlap");
        }
        Ok(())
    }
}

impl ScopeApp {
    pub(super) fn check_input_guidance(&mut self) -> Result<(), String> {
        use display::ScopeNotice;
        assert!(self.core.is_none() && !self.running() && self.pending_stop.is_none());
        let saved = (
            self.source,
            self.busy,
            self.input_error.take(),
            self.input_failed,
            self.channels,
            self.held_input.take(),
            std::mem::take(&mut self.devices),
            self.selected,
            self.enabled,
            self.scope_channels,
            self.core_scope,
            self.acquisition_mode,
            self.acquisition_state,
            self.scope_missing,
            self.dropped,
            self.scope_readings,
            self.measurements,
            self.trigger,
            self.triggered,
        );
        let history = std::mem::replace(&mut self.history, History::with_channels(96000, 2));
        let capture = self.scope_capture.take();
        let range = std::mem::replace(&mut self.scope_range, 0..0);
        let presentation = self.presentation.clone();
        let shell = self.shell.clone();
        let generation = self.input_generation;
        let command = self.generator.command_marker();
        self.presentation = Presentation::default();
        self.shell = shell::Shell::default();
        self.source = Source::Live;
        self.busy = false;
        self.input_failed = false;
        self.channels = 0;
        self.scope_channels = ScopeChannels::default();
        self.enabled = [true; SCOPE_CHANNELS];
        self.acquisition_mode = acquisition::Mode::Auto;
        self.scope_readings = [Reading::Unavailable; SCOPE_CHANNELS];
        self.dirty = true;
        let mut driver = Driver::new();
        let check = |app: &mut ScopeApp, driver: &mut Driver, reason: ScopeNotice| {
            driver.frame(app, vec![]);
            driver.frame(app, vec![]);
            assert_eq!(app.scope_notice(), Some(reason));
            assert_eq!(driver.text_positions(reason.title()).len(), 1);
            assert!(driver.text_positions("Oscilloscope").is_empty());
            driver
                .visible_text_rect(i18n::text("common.amplitude_fs"))
                .unwrap();
            driver
                .visible_text_rect(i18n::text("common.time_ms"))
                .unwrap();
            assert!(
                driver
                    .text_positions("Trigger source unavailable")
                    .is_empty()
            );
            assert!(driver.text_positions("No input").is_empty());
            assert!(
                driver
                    .text_positions("Fs not acquired · no input samples")
                    .is_empty()
            );
            let title = driver.text_positions(reason.title())[0];
            let button = driver
                .position(i18n::text("common.open_input_settings"))
                .unwrap();
            let plot = driver
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
                .unwrap();
            let card = driver
                .output
                .shapes
                .iter()
                .find_map(|s| {
                    if let egui::Shape::Rect(shape) = &s.shape
                        && shape.fill == Color32::from_rgb(20, 32, 42)
                        && shape.rect.contains(title)
                    {
                        Some(shape.rect)
                    } else {
                        None
                    }
                })
                .unwrap();
            assert!((card.center() - plot.center()).length() < 2.0);
            assert!(plot.contains_rect(card) && card.contains(button));
            assert!(card.contains_rect(driver.visible_text_rect(reason.title()).unwrap()));
            assert!(card.contains_rect(driver.visible_text_rect("Open input settings").unwrap()));
        };
        check(self, &mut driver, ScopeNotice::NoDevice);
        driver.visible_text_rect(i18n::text("shell.scope_settings"))?;
        for instrument in Instrument::ALL {
            assert!(
                driver
                    .text_positions(instrument.display_purpose())
                    .is_empty()
            );
        }
        assert_eq!(self.scope_input_channels(), None);
        driver.click(self, i18n::text("common.open_input_settings"))?;
        assert!(self.shell.io == Some(shell::IoTab::Connections));
        assert_eq!(self.presentation, Presentation::default());
        driver.click(self, i18n::text("shell.back_to_instruments"))?;
        self.devices.push(DeviceInfo {
            id: Some("guidance-qa".into()),
            name: "Guidance input (synthetic)".into(),
            channels: 0,
            default_sample_rate: 48000,
            sample_rates: vec![48000],
            is_default: true,
        });
        self.selected = 0;
        check(self, &mut driver, ScopeNotice::Stopped);
        assert_eq!(self.scope_input_channels(), None);
        self.devices[0].channels = 16;
        self.busy = true;
        check(self, &mut driver, ScopeNotice::Opening);
        assert_eq!(self.scope_input_channels(), None);
        assert_eq!(self.input_status_text(), "Input conditions: —");
        self.busy = false;
        self.source = Source::Software;
        self.software_running = true;
        check(self, &mut driver, ScopeNotice::WaitingForSamples);
        assert_eq!(self.scope_input_channels(), Some(2));
        self.scope_channels.0 = [15; SCOPE_CHANNELS];
        check(self, &mut driver, ScopeNotice::ChannelRange);
        self.scope_channels = ScopeChannels::default();
        self.trigger.channel = 15;
        self.trigger.edge = Edge::Rising;
        self.dirty = true;
        check(self, &mut driver, ScopeNotice::TriggerRange);
        driver.visible_text_rect(i18n::text("oscilloscope.t_markers_settings_only"))?;
        self.trigger.channel = 0;
        self.acquisition_mode = acquisition::Mode::Single;
        self.acquisition_state = acquisition::State::Waiting;
        self.history.push([0.25, -0.25]);
        self.dirty = true;
        check(self, &mut driver, ScopeNotice::WaitingForTrigger);
        self.acquisition_state = acquisition::State::Acquiring;
        check(self, &mut driver, ScopeNotice::PostTrigger);
        self.stop();
        check(self, &mut driver, ScopeNotice::Incomplete);
        self.history.clear_at(0);
        self.fail_input("Simulated input error · no device was opened".into());
        for (width, height, zoom) in [
            (1440.0, 860.0, 1.0),
            (720.0, 640.0, 1.25),
            (514.0, 528.0, 1.25),
        ] {
            driver.resize(self, vec2(width, height), zoom, 1.0);
            check(self, &mut driver, ScopeNotice::Failed);
            assert_eq!(
                driver
                    .text_positions(self.input_error.as_ref().unwrap())
                    .len(),
                1
            );
            driver.position(i18n::text("common.open_input_settings"))?;
        }
        // Exercise the same failure handler used by AudioWorker notifications,
        // with an acquired interval and loss information already present.
        self.input_error = None;
        self.acquisition_mode = acquisition::Mode::Auto;
        for _ in 0..1024 {
            self.history.push([0.25, -0.25]);
        }
        self.dirty = true;
        self.refresh_scope_range();
        self.scope_missing = 7;
        self.dropped = 11;
        let held = (
            self.scope_range.clone(),
            self.scope_readings,
            self.history.len(),
        );
        self.fail_input("Simulated failure after acquisition".into());
        driver.resize(self, vec2(1440.0, 1000.0), 1.0, 1.0);
        assert_eq!(self.scope_notice(), None);
        assert_eq!(
            driver
                .text_positions("Simulated failure after acquisition")
                .len(),
            1
        );
        assert_eq!(
            driver.text_positions("Partial · 7 missing samples").len(),
            1
        );
        assert_eq!(
            (
                self.scope_range.clone(),
                self.scope_readings,
                self.history.len()
            ),
            held
        );
        assert_eq!(self.dropped, 11);
        self.triggered = true;
        driver.frame(self, vec![]);
        driver.visible_text_rect(i18n::text("oscilloscope.t_markers_captured"))?;
        assert!(driver.text_positions("T markers: settings only").is_empty());
        self.presentation
            .apply(Action::PairWith(Instrument::Spectrum));
        self.presentation
            .apply(Action::FocusPane(Instrument::Scope));
        driver.frame(self, vec![]);
        driver.visible_text_rect("Scope · Selected")?;
        driver.visible_text_rect(i18n::text("common.amplitude_fs"))?;
        assert!(driver.text_positions("Oscilloscope").is_empty());
        assert_eq!(
            (
                self.scope_range.clone(),
                self.scope_readings,
                self.history.len()
            ),
            held
        );
        assert_eq!(self.input_generation, generation);
        assert_eq!(self.generator.command_marker(), command);
        self.history = history;
        self.scope_capture = capture;
        self.scope_range = range;
        self.presentation = presentation;
        self.shell = shell;
        (
            self.source,
            self.busy,
            self.input_error,
            self.input_failed,
            self.channels,
            self.held_input,
            self.devices,
            self.selected,
            self.enabled,
            self.scope_channels,
            self.core_scope,
            self.acquisition_mode,
            self.acquisition_state,
            self.scope_missing,
            self.dropped,
            self.scope_readings,
            self.measurements,
            self.trigger,
            self.triggered,
        ) = saved;
        self.dirty = true;
        self.xy_dirty = true;
        self.rebuild_xy();
        println!(
            "Input guidance UI OK: startup/unknown channels, opening, no samples, trigger wait, channel range, simulated failure, held data/loss, settings button; readable notices/axes, tooltip-only purposes, single/console headings and trigger settings/capture distinction; generation/output unchanged"
        );
        Ok(())
    }

    pub(super) fn check_common_io_interactions(&mut self) -> Result<(), String> {
        let saved = (
            self.source,
            self.devices.clone(),
            self.selected,
            self.requested_sample_rate,
            self.restored_input.clone(),
            self.busy,
            self.shell.clone(),
        );
        let output = self.generator.rate;
        let held = (self.input_generation, self.sample_rate, self.scope_readings);
        let settle = |app: &mut ScopeApp| {
            let deadline = Instant::now() + Duration::from_secs(2);
            while app.generator.pending {
                app.generator.poll();
                assert!(
                    Instant::now() < deadline,
                    "Common I/O rate acknowledgement timed out"
                );
                std::thread::sleep(Duration::from_millis(2));
            }
            assert!(app.generator.stopped());
            assert!(app.generator.error.is_none());
        };
        settle(self);
        assert!(!self.running() && self.pending_stop.is_none());
        self.source = Source::Live;
        self.busy = false;
        self.devices = vec![DeviceInfo {
            id: Some("coreaudio:common-io-qa".into()),
            name: "Common I/O QA (synthetic)".into(),
            channels: 2,
            default_sample_rate: 48_000,
            sample_rates: vec![48_000, 96_000],
            is_default: true,
        }];
        self.selected = 0;
        self.requested_sample_rate = Some(48_000);
        self.shell.io = Some(shell::IoTab::Connections);
        self.shell.separate_io_rates = false;
        let mut driver = Driver::new();
        driver.frame(self, vec![]);
        driver.frame(self, vec![]);

        driver.check_header()?;
        driver.click(self, "48000 Hz")?;
        driver.click(self, "96000 Hz")?;
        assert_eq!(self.requested_sample_rate, Some(96_000));
        assert_eq!(self.generator.rate, 96_000);
        settle(self);
        let command = self.generator.command_marker();
        assert!(self.apply_common_io_rate(44_100).is_err());
        self.busy = true;
        assert!(self.apply_common_io_rate(48_000).is_err());
        self.busy = false;
        let settings = self.generator.settings;
        self.generator.settings.signals[0].frequency_hz = 30_000.0;
        assert!(self.apply_common_io_rate(48_000).is_err());
        self.generator.settings = settings;
        assert_eq!(self.generator.command_marker(), command);
        assert_eq!(self.requested_sample_rate, Some(96_000));
        assert_eq!(self.generator.rate, 96_000);
        driver.frame(self, vec![]);
        driver.click(self, i18n::text("io.separate_sample_rates"))?;
        driver.click(self, "96 kHz")?;
        driver.click(self, i18n::text("io.device_default"))?;
        assert_eq!(self.requested_sample_rate, None);
        assert_eq!(self.generator.rate, 96_000);
        driver.click(self, i18n::text("io.separate_sample_rates"))?;
        assert!(!driver.text_positions("Select common rate").is_empty());
        assert_eq!(self.generator.command_marker(), command);
        driver.click(self, i18n::text("io.select_common_rate"))?;
        driver.click(self, "48000 Hz")?;
        settle(self);
        assert_eq!(self.requested_sample_rate, Some(48_000));
        assert_eq!(self.generator.rate, 48_000);
        assert!(!self.running());
        assert_eq!(
            (self.input_generation, self.sample_rate, self.scope_readings),
            held
        );
        self.check_output_format_interactions(&mut driver)?;
        if self.generator.rate != output {
            self.generator.select(
                self.generator.target.clone(),
                output,
                self.generator.settings,
            )?;
            settle(self);
        }
        (
            self.source,
            self.devices,
            self.selected,
            self.requested_sample_rate,
            self.restored_input,
            self.busy,
            self.shell,
        ) = saved;
        println!(
            "Shared I/O controls OK: common rate applies to both, unsupported/busy/invalid requests leave both unchanged, separate/default/mixed rates preserve held conditions and stay stopped"
        );
        Ok(())
    }

    fn check_output_format_interactions(&mut self, driver: &mut Driver) -> Result<(), String> {
        let saved = (
            self.generator.target.clone(),
            self.generator.rate,
            self.generator.settings,
            self.generator.devices.clone(),
        );
        let config = output::device::Config {
            rate: 48_000,
            channels: 16,
            pcm: output::device::Pcm::F32,
        };
        let target = output::Target::Audio {
            device_id: "common-io-output-qa".into(),
            device_name: "Output format QA (synthetic)".into(),
            channels: config.channels,
            pcm: config.pcm,
        };
        self.generator.devices = vec![output::device::DeviceInfo {
            id: "common-io-output-qa".into(),
            name: "Output format QA (synthetic)".into(),
            configs: vec![
                config,
                output::device::Config {
                    channels: 2,
                    ..config
                },
                output::device::Config {
                    channels: 1,
                    ..config
                },
            ],
            preferred: config,
        }];
        let mut settings = self.generator.settings;
        settings.signals[0].output_channel = Some(0);
        settings.signals[1].output_channel = Some(15);
        settings.signals[1].enabled = true;
        self.generator.select(target, config.rate, settings)?;
        let settle = |app: &mut ScopeApp| {
            let deadline = Instant::now() + Duration::from_secs(2);
            while app.generator.pending {
                app.generator.poll();
                assert!(
                    Instant::now() < deadline,
                    "Output format acknowledgement timed out"
                );
                std::thread::sleep(Duration::from_millis(2));
            }
            assert!(app.generator.stopped());
            assert!(app.generator.error.is_none());
        };
        settle(self);
        let held = (self.input_generation, self.sample_rate, self.scope_readings);
        for guard in 0..3 {
            self.busy = guard == 0;
            self.workspace_restoring = guard == 1;
            self.settings_task = (guard == 2).then_some(SettingsTask::Restore);
            driver.frame(self, vec![]);
            for label in ["16ch · f32", "Output format QA (synthetic)", "48000 Hz"] {
                driver.click_at(self, driver.text_positions(label)[0]);
                assert!(
                    !driver.ctx.any_popup_open(),
                    "I/O selector opened during pending operation: {label}"
                );
            }
            driver.click_at(
                self,
                driver.text_positions(i18n::text("io.software_loopback"))[0],
            );
            assert!(
                self.source == Source::Live,
                "Input source changed during pending operation"
            );
        }
        self.busy = false;
        self.workspace_restoring = false;
        self.settings_task = None;
        driver.frame(self, vec![]);
        driver.click(self, "16ch · f32")?;
        driver.click(self, "2ch · f32")?;
        assert_eq!(self.generator.target.channels(), 2);
        let mut expected = settings;
        expected.signals[1].output_channel = None;
        expected.signals[1].enabled = false;
        assert_eq!(self.generator.settings, expected);
        settle(self);
        // OFF cards also reserve an OUT and must be unassigned on mono output.
        let mut mono = expected;
        mono.signals[1].output_channel = Some(1);
        self.generator.configure(mono);
        settle(self);
        driver.frame(self, vec![]);
        driver.click(self, i18n::text("io.separate_sample_rates"))?;
        driver.click(self, "48000 Hz · 2ch · f32")?;
        driver.click(self, "48000 Hz · 1ch · f32")?;
        assert_eq!(self.generator.target.channels(), 1);
        assert_eq!(self.generator.settings, expected);
        settle(self);
        driver.click(self, i18n::text("io.separate_sample_rates"))?;
        assert_eq!(
            (self.input_generation, self.sample_rate, self.scope_readings),
            held
        );
        self.generator.select(saved.0, saved.1, saved.2)?;
        settle(self);
        self.generator.devices = saved.3;
        println!(
            "Output format controls OK: 16/2/1ch keeps GEN IDs, unassigns unavailable OUTs and stays OFF; refresh/restore guards preserve held input"
        );
        Ok(())
    }

    pub(super) fn check_spectrogram_display_interactions(&mut self) -> Result<(), String> {
        // The initial device enumeration reply is polled by the desktop update,
        // not by this widget-only driver. It is unrelated to held fixture data.
        let busy = self.busy;
        self.busy = false;
        let presentation = self.presentation.clone();
        let shell = self.shell.clone();
        let cursors = std::mem::take(&mut self.cursors);
        let active = self.active_cursor;
        let saved = (
            self.spectrogram_color_map,
            self.spectrogram_auto_color,
            self.spectrogram_scale,
            self.spectrogram_min_hz,
            self.spectrogram_max_hz,
            self.spectrogram_seconds,
        );
        let previous_history = self.spectrogram_history.clone();
        let previous_snapshot = self.spectrogram_snapshot.clone();
        let previous_hold = self.spectrogram_hold.take();
        let previous_anchor = self.spectrogram_anchor;
        let previous_hold_anchor = self.spectrogram_hold_anchor.take();
        let previous_last = self.last_stft;
        let previous_unavailable = self.spectrogram_unavailable_selection;
        self.spectrogram_unavailable_selection = [false; 2];
        let config = stft::Config {
            size: 1024,
            hop: 256,
            ..self.stft_config()
        };
        self.spectrogram_snapshot = spectrogram::history::fixture(
            self.input_generation,
            self.stft_generation,
            config,
            (0..12000).map(|i| {
                let end = 1024 + i * 256;
                let mut power = vec![1e-18; 513];
                power[32] = 0.25 + f64::EPSILON;
                power[64] = 0.0625 * (1.0 + (i % 200) as f64 / 200.0);
                (
                    RowInfo {
                        generation: self.stft_generation,
                        config,
                        start: end - 1024,
                        end,
                        gap: stft::Gap::default(),
                    },
                    power,
                )
            }),
        );
        let previous_collector = self
            .stft_history
            .replace_frozen_snapshot(self.spectrogram_snapshot.clone());
        self.spectrogram_anchor = self.spectrogram_snapshot.latest().unwrap().info.end;
        let conditions = (
            self.input_generation,
            self.stft_generation,
            self.spectrogram_settings,
            self.generator.command_marker(),
        );
        self.presentation
            .apply(Action::OpenSingle(Instrument::Spectrogram));
        self.presentation.details_visible = true;
        self.spectrogram_color_map = spectrogram::ColorMap::Blue;
        self.spectrogram_auto_color = false;
        self.spectrogram_seconds = 5.0;
        self.spectrogram_scale = FrequencyScale::Log;
        self.spectrogram_min_hz = 20.0;
        self.spectrogram_max_hz = 0.0;
        let mut driver = Driver::new();
        let settle = |driver: &mut Driver, app: &mut ScopeApp| {
            let deadline = Instant::now() + Duration::from_secs(10);
            loop {
                driver.frame(app, vec![]);
                if app.spectrogram_prepared_id == app.spectrogram_view_worker.current_id()
                    && app.spectrogram_prepared_id != 0
                {
                    break;
                }
                assert!(Instant::now() < deadline, "Spectrogram raster timed out");
                std::thread::sleep(Duration::from_millis(2));
            }
        };
        settle(&mut driver, self);
        for map in spectrogram::ColorMap::ALL {
            driver.click(self, self.spectrogram_color_map.display_name())?;
            driver.click(self, map.display_name())?;
            assert_eq!(self.spectrogram_color_map, map);
        }
        driver.click(self, i18n::text("spectrogram.auto_color_range"))?;
        assert!(self.spectrogram_auto_color);
        driver.click(self, "5 s")?;
        driver.click(self, "60 s")?;
        assert_eq!(self.spectrogram_seconds, 60.0);
        let plot = |driver: &Driver| -> Result<egui::Rect, String> {
            driver
                .output
                .shapes
                .iter()
                .find_map(|s| match &s.shape {
                    egui::Shape::Callback(callback) => Some(callback.rect),
                    _ => None,
                })
                .ok_or("Spectrogram plot missing".into())
        };
        settle(&mut driver, self);
        let rect = plot(&driver)?;
        let center = rect.center();
        let before = self.spectrogram_view();
        driver.frame(
            self,
            vec![
                egui::Event::PointerMoved(center),
                egui::Event::MouseWheel {
                    unit: egui::MouseWheelUnit::Point,
                    phase: egui::TouchPhase::Move,
                    delta: vec2(0.0, 60.0),
                    modifiers: egui::Modifiers::NONE,
                },
            ],
        );
        let after = self.spectrogram_view();
        assert!(after.max_hz / after.min_hz < before.max_hz / before.min_hz);
        assert!(self.cursors.times.iter().all(Option::is_none));
        // Settle the wheel before pointer gestures.
        for _ in 0..30 {
            driver.frame(self, vec![]);
        }
        settle(&mut driver, self);
        let rect = plot(&driver)?;
        let start = rect.center();
        let destination = start + vec2(30.0, 0.0);
        let drag = |driver: &mut Driver, app: &mut ScopeApp, start, destination| {
            driver.frame(
                app,
                vec![
                    egui::Event::PointerMoved(start),
                    egui::Event::PointerButton {
                        pos: start,
                        button: egui::PointerButton::Primary,
                        pressed: true,
                        modifiers: egui::Modifiers::NONE,
                    },
                ],
            );
            driver.frame(app, vec![egui::Event::PointerMoved(destination)]);
            driver.frame(
                app,
                vec![egui::Event::PointerButton {
                    pos: destination,
                    button: egui::PointerButton::Primary,
                    pressed: false,
                    modifiers: egui::Modifiers::NONE,
                }],
            );
            driver.frame(app, vec![]);
        };
        let before_pan = self.spectrogram_view();
        drag(&mut driver, self, start, destination);
        assert!(self.spectrogram_view().min_hz < before_pan.min_hz);
        assert!(
            self.cursors.times.iter().all(Option::is_none),
            "Background drag created a time cursor"
        );
        assert!(
            self.spectrogram_hold.is_none(),
            "Horizontal pan entered Hold"
        );
        settle(&mut driver, self);
        driver.click_at(self, center);
        for _ in 0..30 {
            driver.frame(self, vec![]);
        }
        settle(&mut driver, self);
        assert!(
            self.spectrogram_hold.is_some(),
            "Time selection did not enter Hold"
        );
        let a = self.cursors.times[self.active_cursor]
            .unwrap()
            .spectrogram_sample()
            .unwrap();
        let selected = self.spectrogram_selected[self.active_cursor]
            .as_ref()
            .unwrap()
            .clone();
        assert_eq!(
            selected.power()[32].to_bits(),
            (0.25 + f64::EPSILON).to_bits()
        );
        let before_drag = self.spectrogram_view();
        drag(&mut driver, self, center, center + vec2(30.0, 40.0));
        let b = self.cursors.times[self.active_cursor]
            .unwrap()
            .spectrogram_sample()
            .unwrap();
        assert!(b < a);
        assert_eq!(
            self.spectrogram_view(),
            before_drag,
            "Cursor drag panned frequency"
        );
        settle(&mut driver, self);
        let fixed_samples = self.cursor_samples();
        let hold = self.spectrogram_hold.clone().unwrap();
        let anchor = self.spectrogram_hold_anchor.unwrap();
        let background = pos2(
            rect.left() + rect.width() * 0.8,
            rect.top() + rect.height() * 0.9,
        );
        drag(&mut driver, self, background, background + vec2(0.0, 30.0));
        assert!(self.spectrogram_hold_anchor.unwrap() < anchor);
        assert_eq!(self.cursor_samples(), fixed_samples);
        assert!(Arc::ptr_eq(self.spectrogram_hold.as_ref().unwrap(), &hold));
        let anchor = self.spectrogram_hold_anchor.unwrap();
        let frequency = self.spectrogram_view();
        driver.frame(
            self,
            vec![
                egui::Event::PointerMoved(background),
                egui::Event::MouseWheel {
                    unit: egui::MouseWheelUnit::Point,
                    phase: egui::TouchPhase::Move,
                    delta: vec2(0.0, 60.0),
                    modifiers: egui::Modifiers::SHIFT,
                },
            ],
        );
        assert!(self.spectrogram_hold_anchor.unwrap() < anchor);
        assert_eq!(self.spectrogram_view(), frequency);
        assert_eq!(self.cursor_samples(), fixed_samples);
        for _ in 0..30 {
            driver.frame(self, vec![]);
        }
        settle(&mut driver, self);
        // Keep this double-click distinct from the earlier cursor click.
        // egui otherwise recognizes a rapid third click as a triple-click.
        for _ in 0..50 {
            driver.frame(self, vec![]);
        }
        let no_cursor = pos2(
            rect.left() + rect.width() * 0.2,
            rect.top() + rect.height() * 0.2,
        );
        driver.click_at(self, no_cursor);
        driver.click_at(self, no_cursor);
        assert_eq!(self.spectrogram_max_hz, 0.0);
        assert_eq!(self.spectrogram_min_hz, 20.0);
        assert_eq!(self.spectrogram_seconds, 60.0);
        assert!(
            self.spectrogram_hold.is_some(),
            "Double-click changed Hold mode"
        );
        driver.click(self, i18n::text("spectrogram.live_action"))?;
        assert!(self.spectrogram_hold.is_none());
        assert!(self.cursors.times.iter().all(Option::is_none));
        settle(&mut driver, self);
        // Double-click while Live must cancel its deferred single click.
        driver.click_at(self, no_cursor);
        driver.click_at(self, no_cursor);
        for _ in 0..30 {
            driver.frame(self, vec![]);
        }
        assert!(self.spectrogram_hold.is_none());
        driver.resize(self, vec2(900.0, 700.0), 1.25, 2.0);
        driver.click(self, i18n::text("shell.details"))?;
        driver.position(i18n::text("spectrogram.auto_color_range"))?;
        driver.click(self, i18n::text("shell.measurement"))?;
        settle(&mut driver, self);
        assert!(plot(&driver)?.width() > 100.0);
        assert_eq!(
            (
                self.input_generation,
                self.stft_generation,
                self.spectrogram_settings,
                self.generator.command_marker()
            ),
            conditions
        );
        // S4 uses the actual Pair/Undo and source-selection widgets. The
        // retained f64 frame is adapted once, never the reduced display raster.
        self.refresh_scope_range();
        driver.resize(self, vec2(1600.0, 1200.0), 1.0, 1.0);
        let ordinary = self.analyzer.clone();
        let ordinary_settings = self.spectrum_settings;
        let ordinary_display = self.spectrum_display;
        let ordinary_axes = (
            self.frequency_scale,
            self.floor_db,
            self.spectrum_ceiling_db,
            self.span_hz,
            self.spectrum_min_hz,
            self.show_hold,
        );
        let processed = self.stft.metrics.produced.load(Ordering::Relaxed);
        self.presentation.console = Console {
            instruments: vec![Instrument::Scope, Instrument::Generator],
            selected: Some(Instrument::Scope),
            layout: Layout::Rows,
            split: 0.4,
        };
        let original_console = self.presentation.console.clone();
        self.select_spectrogram_time(0, 0.1);
        self.select_spectrogram_time(1, 0.4);
        let frames: [_; 2] = std::array::from_fn(|i| self.spectrogram_selected[i].clone().unwrap());
        driver.frame(self, vec![]);
        driver.click(self, i18n::text("shell.split_view_with"))?;
        driver.click(self, i18n::text("shell.instrument_names.spectrum"))?;
        assert!(self.spectrum_history.linked);
        for (i, frame) in frames.iter().enumerate() {
            assert_eq!(self.shown_spectrum(i).power(), frame.power());
            assert_eq!(
                self.shown_spectrum(i).window().unwrap().start,
                frame.info.start
            );
            assert_eq!(
                self.shown_spectrum(i).cursor(1500.0).unwrap().value,
                frame.power()[32].sqrt()
            );
            assert!(self.shown_spectrum(i).calibration().is_none());
        }
        assert!(!self.can_export());
        assert!(
            self.capture_results()
                .unwrap_err()
                .contains("History Spectrum export")
        );
        let scope_export = self.capture_scope_results()?;
        scope_export.validate()?;
        assert_eq!(scope_export.spectrum.state, export::State::Unavailable);
        assert!(scope_export.spectrum.values.is_none());
        assert!(scope_export.spectrum.latest_window.is_none());
        assert!(scope_export.spectrum.peak_hold.is_none());
        let restored: export::Document =
            serde_json::from_slice(&serde_json::to_vec(&scope_export).unwrap()).unwrap();
        restored.validate()?;
        assert_eq!(restored.scope, scope_export.scope);
        crate::result_image::render(&scope_export)?;
        let fixed_times = self.cursors.times;
        let time_cursor = self.active_cursor;
        // Both panes have A/B controls. Locate the frequency target beside its
        // own label rather than clicking the shared time target in Spectrogram.
        let frequency_label =
            driver.text_position(i18n::text("spectrum.place_frequency_cursor"))?;
        let frequency_b = driver
            .text_positions("B")
            .into_iter()
            .min_by(|a, b| {
                a.distance_sq(frequency_label)
                    .total_cmp(&b.distance_sq(frequency_label))
            })
            .ok_or("Frequency cursor B missing")?;
        driver.click_at(self, frequency_b);
        assert_eq!(
            self.active_cursor, time_cursor,
            "Frequency cursor changed active time cursor"
        );
        let spectrum_rect = driver
            .output
            .shapes
            .iter()
            .rev()
            .find_map(|s| match &s.shape {
                egui::Shape::Callback(c) => Some(c.rect),
                _ => None,
            })
            .ok_or("Spectrum plot missing")?;
        driver.click_at(self, spectrum_rect.center());
        assert!(self.cursors.spectrum_frequencies_hz[1].is_some());
        assert_eq!(self.cursors.times, fixed_times);
        driver.click(self, i18n::text("spectrum.clear_frequency"))?;
        assert_eq!(
            self.cursors.times, fixed_times,
            "Frequency Clear discarded time selections"
        );
        assert!(
            self.cursors
                .spectrum_frequencies_hz
                .iter()
                .all(Option::is_none)
        );
        driver.click(self, "Time B")?;
        assert_eq!(self.spectrum_history.selected, 1);
        assert_eq!(
            self.shown_selected_spectrum().window().unwrap().end,
            frames[1].info.end
        );
        // Same frame for A/B is valid; unavailable selections never borrow A.
        self.select_spectrogram_sample(1, frames[0].info.end - 1);
        self.refresh_spectrum_history();
        assert_eq!(
            self.shown_spectrum(0).power(),
            self.shown_spectrum(1).power()
        );
        self.select_spectrogram_sample(1, 0);
        self.refresh_spectrum_history();
        assert!(self.shown_spectrum(1).window().is_none());
        assert!(self.shown_spectrum(1).cursor(1500.0).is_none());
        driver.frame(self, vec![]);
        driver.click(self, i18n::text("spectrum.normal_spectrum"))?;
        assert!(!self.spectrum_history.linked);
        assert_eq!(self.analyzer.power(), ordinary.power());
        assert_eq!(self.analyzer.hold_power(), ordinary.hold_power());
        assert_eq!(self.analyzer.average(), ordinary.average());
        assert_eq!(self.analyzer.window(), ordinary.window());
        assert_eq!(self.spectrum_settings, ordinary_settings);
        assert_eq!(self.spectrum_display, ordinary_display);
        assert_eq!(
            (
                self.frequency_scale,
                self.floor_db,
                self.spectrum_ceiling_db,
                self.span_hz,
                self.spectrum_min_hz,
                self.show_hold
            ),
            ordinary_axes
        );
        driver.click(self, i18n::text("spectrum.time_a_b_from_spectrogram"))?;
        assert!(self.spectrum_history.linked);
        driver.click(self, i18n::text("shell.undo_replacement"))?;
        assert!(!self.spectrum_history.linked);
        assert_eq!(self.presentation.console, original_console);
        self.navigate(Action::OpenSingle(Instrument::Spectrogram));
        driver.frame(self, vec![]);
        driver.click(self, i18n::text("shell.split_view_with"))?;
        driver.click(self, i18n::text("shell.instrument_names.spectrum"))?;
        self.live_spectrogram();
        assert!(!self.spectrum_history.linked);
        assert!(self.spectrogram_selected.iter().all(Option::is_none));
        // Opening an existing layout or another Pair never changes the source.
        self.navigate(Action::OpenSingle(Instrument::Scope));
        self.navigate(Action::PairWith(Instrument::Spectrum));
        assert!(!self.spectrum_history.linked);
        self.navigate(Action::OpenSingle(Instrument::Spectrogram));
        self.navigate(Action::PairWith(Instrument::Spectrum));
        assert!(self.spectrum_history.linked);
        self.clear_spectrogram_view();
        assert!(!self.spectrum_history.linked);
        assert_eq!(
            self.stft.metrics.produced.load(Ordering::Relaxed),
            processed
        );
        // S5 edits while stopped are next-run settings and leave held frames
        // and the active STFT generation untouched.
        self.navigate(Action::OpenSingle(Instrument::Spectrogram));
        let previous_overlap = self.spectrogram_overlap;
        driver.frame(self, vec![]);
        for overlap in [
            stft::Overlap::Half,
            stft::Overlap::SevenEighths,
            stft::Overlap::ThreeQuarters,
        ] {
            driver.click(self, self.spectrogram_overlap.display_name())?;
            driver.click(self, overlap.display_name())?;
            assert_eq!(
                self.stft_config().hop,
                overlap.hop(self.spectrogram_settings.size)
            );
            assert_eq!(self.stft_generation, conditions.1);
        }
        self.spectrogram_overlap = previous_overlap;
        self.spectrogram_view_worker.clear();
        self.stft_history
            .replace_frozen_snapshot(previous_collector);
        self.spectrogram_unavailable_selection = previous_unavailable;
        self.spectrogram_history = previous_history;
        self.spectrogram_snapshot = previous_snapshot;
        self.spectrogram_hold = previous_hold;
        self.spectrogram_anchor = previous_anchor;
        self.spectrogram_hold_anchor = previous_hold_anchor;
        self.spectrogram_selected = [None, None];
        self.last_stft = previous_last;
        (
            self.spectrogram_color_map,
            self.spectrogram_auto_color,
            self.spectrogram_scale,
            self.spectrogram_min_hz,
            self.spectrogram_max_hz,
            self.spectrogram_seconds,
        ) = saved;
        self.presentation = presentation;
        self.shell = shell;
        self.cursors = cursors;
        self.active_cursor = active;
        self.spectrogram_auto_result = spectrogram::ColorRange::default();
        self.busy = busy;
        if std::env::var("MEASURELAB_UI_SMOKE_SPECTROGRAM_DISPLAY").as_deref() == Ok("pair") {
            self.spectrogram_color_map = spectrogram::ColorMap::Turbo;
            self.spectrogram_snapshot = hold.clone();
            self.spectrogram_hold = Some(hold);
            self.spectrogram_anchor = self.spectrogram_snapshot.latest().unwrap().info.end;
            self.spectrogram_hold_anchor = Some(self.spectrogram_anchor);
            self.spectrogram_seconds = 5.0;
            self.select_spectrogram_time(0, 0.2);
            self.select_spectrogram_time(1, 0.6);
            self.navigate(Action::OpenSingle(Instrument::Spectrogram));
            self.navigate(Action::PairWith(Instrument::Spectrum));
            self.spectrum_history.view =
                View::full(config.sample_rate, FrequencyScale::Linear, -120.0);
            self.presentation.details_visible = true;
            self.cursors.set_frequency(0, 1500.0);
            self.cursors.set_frequency(1, 3000.0);
        }
        println!(
            "Spectrogram display UI OK: palette/Auto/time, pan/zoom, fixed f64 frames, Hold/Live, Pair Spectrum Time A/B, independent frequency cursors, normal result preservation, export guard, Undo/unlink, Overlap widgets, narrow/DPI; STFT/generation/output unchanged"
        );
        Ok(())
    }

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

        self.check_display_scale_interactions(&mut driver)?;
        self.check_language_interactions(&mut driver)?;
        self.check_sidebar_interactions(&mut driver)?;
        self.check_output_stop_interactions(&mut driver)?;
        self.check_cursor_placement_interactions(&mut driver)?;
        self.check_trigger_display_interactions(&mut driver)?;

        let shared_input_labels = driver
            .output
            .shapes
            .iter()
            .filter(|shape| {
                matches!(&shape.shape, egui::Shape::Text(text) if matches!(text.galley.text(),
                    "■ Input stopped" | "▶ Input live" | "… Opening" | "… Finishing"))
            })
            .count();
        assert_eq!(shared_input_labels, 1, "Monitor shares one input status");

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
        driver.click(self, i18n::text("oscilloscope.zero_level"))?;
        assert_eq!(self.trigger.level, 0.0);
        assert_eq!(self.scope_vertical, unedited.3);
        driver.click(self, i18n::text("oscilloscope.reset_time_position"))?;
        assert_eq!(self.scope_horizontal_position, 0.0);
        assert_eq!(self.ms_per_div, unedited.0);
        driver.click(self, i18n::text("oscilloscope.zero_offset"))?;
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
        driver.click(self, i18n::text("shell.instrument_names.spectrum"))?;
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
        driver.click(self, i18n::text("spectrum.auto"))?;
        assert!(self.spectrum_display.auto_level);
        let view = self.spectrum_view();
        assert!(view.max_hz <= self.sample_rate as f32 / 2.0);
        assert!(view.min_hz >= 0.0 && view.min_hz < view.max_hz);
        assert!(view.floor_db < view.ceiling_db);
        driver.click(self, i18n::text("spectrum.manual"))?;
        assert!(!self.spectrum_display.auto_level);
        self.spectrum_display = spectrum_display;
        self.spectrum_dirty = true;
        self.spectrum_numeric_key = None;
        self.check_spectrum_interactions(&mut driver)?;
        self.check_xy_controls_interactions(&mut driver)?;

        for instrument in Instrument::ALL {
            driver.click(self, instrument.display_name())?;
            assert_eq!(self.presentation.screen, Screen::Single(instrument));
            driver.click(self, instrument.display_name())?;
            assert_eq!(self.presentation.screen, Screen::Single(instrument));
            driver.text_position(i18n::text("generator.stop_output_2"))?;
        }
        driver.key(self, egui::Key::Num1, egui::Modifiers::CTRL);
        driver.click(self, i18n::text("shell.split_view_with"))?;
        driver.click(self, i18n::text("shell.instrument_names.generator"))?;
        assert_eq!(
            self.presentation.console.instruments,
            [Instrument::Scope, Instrument::Generator]
        );
        assert_eq!(self.presentation.selected(), Some(Instrument::Generator));
        let pair = self.presentation.console.clone();
        driver.key(self, egui::Key::Num1, egui::Modifiers::CTRL);
        driver.click(self, i18n::text("shell.multi_instrument_view"))?;
        assert_eq!(self.presentation.console, pair);
        driver.key(self, egui::Key::ArrowLeft, egui::Modifiers::CTRL);
        assert_eq!(self.presentation.selected(), Some(Instrument::Scope));
        driver.key(self, egui::Key::ArrowRight, egui::Modifiers::CTRL);
        assert_eq!(self.presentation.selected(), Some(Instrument::Generator));
        // Foreground menus/windows own keyboard input. Escape dismisses just
        // that layer, preserving both the console and an underlying I/O page.
        for menu in [
            "File",
            "View",
            "Audio I/O",
            "Analysis status…",
            "Add instrument…",
        ] {
            driver.click(self, menu)?;
            assert!(driver.ctx.any_popup_open());
            driver.key(self, egui::Key::Num2, egui::Modifiers::CTRL);
            driver.key(self, egui::Key::ArrowLeft, egui::Modifiers::CTRL);
            assert_eq!(self.presentation.screen, Screen::Console);
            assert_eq!(self.presentation.console, pair);
            driver.key(self, egui::Key::Escape, egui::Modifiers::NONE);
            assert!(!driver.ctx.any_popup_open());
        }
        driver.click(self, i18n::text("shell.audio_i_o"))?;
        driver.click(self, i18n::text("shell.input_output"))?;
        // Both connection directions are available on the same page.
        assert!(!driver.text_positions("Audio input").is_empty());
        assert!(
            !driver
                .text_positions("SAMPLE RATE · INPUT + OUTPUT")
                .is_empty()
        );
        assert!(!driver.text_positions("OUTPUT DEVICE").is_empty());
        driver.key(self, egui::Key::ArrowLeft, egui::Modifiers::CTRL);
        assert_eq!(self.presentation.console, pair);
        driver.click(self, i18n::text("shell.audio_i_o"))?;
        driver.key(self, egui::Key::Escape, egui::Modifiers::NONE);
        assert!(!driver.ctx.any_popup_open() && self.shell.io.is_some());
        driver.click(self, i18n::text("shell.help"))?;
        // Keep the floating window's resize corner clear of the header while
        // checking keyboard priority and opening another auxiliary window.
        let help_title = driver
            .text_positions(i18n::text("shell.help"))
            .into_iter()
            .find(|pos| pos.y > 20.0)
            .ok_or("Help window title missing")?;
        driver.frame(self, vec![egui::Event::PointerMoved(help_title)]);
        driver.frame(
            self,
            vec![egui::Event::PointerButton {
                pos: help_title,
                button: egui::PointerButton::Primary,
                pressed: true,
                modifiers: egui::Modifiers::NONE,
            }],
        );
        let moved = help_title + vec2(300.0, 100.0);
        driver.frame(self, vec![egui::Event::PointerMoved(moved)]);
        driver.frame(
            self,
            vec![egui::Event::PointerButton {
                pos: moved,
                button: egui::PointerButton::Primary,
                pressed: false,
                modifiers: egui::Modifiers::NONE,
            }],
        );
        driver.frame(self, vec![]);
        driver.key(self, egui::Key::Num2, egui::Modifiers::CTRL);
        driver.key(self, egui::Key::ArrowLeft, egui::Modifiers::CTRL);
        assert_eq!(self.presentation.screen, Screen::Console);
        assert_eq!(self.presentation.console, pair);
        assert!(matches!(self.shell.io, Some(shell::IoTab::Connections)));
        driver.click(self, i18n::text("common.file"))?;
        driver.click(self, i18n::text("common.file_paths_status"))?;
        assert!(self.shell.file_paths && self.shell.help);
        driver.key(self, egui::Key::Num2, egui::Modifiers::CTRL);
        assert_eq!(self.presentation.screen, Screen::Console);
        driver.key(self, egui::Key::Escape, egui::Modifiers::NONE);
        assert!(
            !self.shell.file_paths && self.shell.help,
            "Escape must close the front file window: paths={}, help={}, editor={}",
            self.shell.file_paths,
            self.shell.help,
            driver.ctx.text_edit_focused()
        );
        assert!(self.shell.io.is_some());
        driver.key(self, egui::Key::Escape, egui::Modifiers::NONE);
        assert!(!self.shell.help && self.shell.io.is_some());
        driver.key(self, egui::Key::Escape, egui::Modifiers::NONE);
        assert!(self.shell.io.is_none());
        assert_eq!(self.presentation.console, pair);
        // Let the closed auxiliary windows finish fading before clicking
        // controls underneath their former screen area.
        for _ in 0..10 {
            driver.frame(self, vec![]);
        }
        driver.key(self, egui::Key::Num1, egui::Modifiers::CTRL);
        driver.click(self, i18n::text("shell.split_view_with"))?;
        driver.click(self, i18n::text("shell.instrument_names.spectrum"))?;
        driver.click(self, i18n::text("shell.undo_replacement"))?;
        assert_eq!(self.presentation.console, pair);
        for instrument in Instrument::ALL {
            driver.click(self, i18n::text("shell.add_instrument"))?;
            driver.click(self, instrument.display_name())?;
            assert_eq!(self.presentation.selected(), Some(instrument));
        }
        assert_eq!(self.presentation.console.instruments.len(), 7);
        driver.click(self, i18n::text("shell.layout_names.tabs"))?;
        for _ in 0..7 {
            driver.click(self, i18n::text("shell.remove_from_view"))?;
        }
        assert!(self.presentation.console.instruments.is_empty());
        assert_eq!(self.presentation.selected(), None);

        // Requested layout and ratio survive a round trip through a small view,
        // app zoom, and simulated native scale events. Native monitor QA is separate.
        driver.key(self, egui::Key::Num1, egui::Modifiers::CTRL);
        driver.click(self, i18n::text("shell.split_view_with"))?;
        driver.click(self, i18n::text("shell.instrument_names.generator"))?;
        self.presentation.details_visible = false;
        self.presentation.console.split = 0.4;
        driver.frame(self, vec![]);
        let console = self.presentation.console.clone();
        for native_scale in [1.0, 2.0] {
            for width in [514.0, 720.0, 1040.0, 1180.0, 1200.0] {
                driver.resize(self, vec2(width, 528.0), 1.25, native_scale);
                driver.check_header()?;
                assert_eq!(self.presentation.console, console);
            }
            driver.resize(self, vec2(1440.0, 1000.0), 1.0, 1.0);
            driver.check_header()?;
            assert_eq!(self.presentation.console, console);
        }
        for tab in ["Input / output", "Calibration"] {
            driver.click(self, i18n::text("shell.audio_i_o"))?;
            driver.click(self, tab)?;
            assert!(self.shell.io.is_some());
            driver.text_position(i18n::text("generator.stop_output_2"))?;
            driver.click(self, i18n::text("shell.back_to_instruments"))?;
            assert!(self.shell.io.is_none());
            assert_eq!(self.presentation.console, console);
        }
        driver.resize(self, vec2(720.0, 528.0), 1.25, 1.0);
        self.presentation.details_visible = true;
        let menu_title = self
            .presentation
            .selected()
            .map_or("Multi-instrument view".into(), |i| {
                format!("Instrument: {}", i.display_name())
            });
        driver.click(self, i18n::text("shell.menu"))?;
        driver.click(self, &menu_title)?;
        for instrument in Instrument::ALL {
            driver.visible_text_rect(instrument.display_name())?;
            assert!(
                driver
                    .text_positions(instrument.display_purpose())
                    .is_empty()
            );
        }
        driver.click(self, i18n::text("shell.instrument_names.generator"))?;
        assert_eq!(
            self.presentation.screen,
            Screen::Single(Instrument::Generator)
        );
        driver.frame(self, vec![]);
        assert!(!driver.ctx.any_popup_open());
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
            driver.click(self, i18n::text("shell.details"))?;
            assert!(self.shell.narrow_details);
            driver.text_position(i18n::text("generator.stop_output_2"))?;
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

    fn check_language_interactions(&mut self, driver: &mut Driver) -> Result<(), String> {
        let selected = i18n::locale();
        let screen = self.presentation.screen;
        let generation = self.input_generation;
        let command = self.generator.command_marker();
        i18n::initialize(&driver.ctx, None);
        for (width, zoom, native) in [(1440.0, 1.0, 1.0), (900.0, 1.25, 2.0)] {
            driver.resize(self, vec2(width, 1000.0), zoom, native);
            for locale in i18n::Locale::ALL {
                if width < 1180.0 {
                    driver.click(self, i18n::text("shell.menu"))?;
                }
                driver.click(self, i18n::text("shell.view"))?;
                driver.click(self, i18n::text("shell.language"))?;
                driver.visible_text_rect(locale.native_name())?;
                driver.click(self, locale.native_name())?;
                assert_eq!(i18n::locale(), locale);
                assert_eq!(self.presentation.screen, screen);
                assert_eq!(self.input_generation, generation);
                assert_eq!(self.generator.command_marker(), command);
                assert!(!egui::Popup::is_any_open(&driver.ctx));
                driver.text_position(i18n::text("generator.stop_output_2"))?;
            }
        }
        i18n::set_locale(&driver.ctx, selected.id());
        driver.resize(self, vec2(1440.0, 1000.0), 1.0, 1.0);
        println!(
            "Language UI OK: nine locales, English fallback, wide/narrow/zoom/native scale; selection, input generation and output commands unchanged"
        );
        Ok(())
    }

    fn check_output_stop_interactions(&mut self, driver: &mut Driver) -> Result<(), String> {
        // Synthetic UI states only: never start an output stream. In particular,
        // a Start request can be pending while the last status still says Stopped.
        let saved = std::mem::take(&mut self.generator);
        let presentation = self.presentation.clone();
        let restoring = self.workspace_restoring;
        self.presentation
            .apply(Action::OpenSingle(Instrument::Generator));
        for (state, pending, starting, stopping) in [
            (generator::State::Stopped, false, false, false),
            (generator::State::Stopped, true, false, false),
            (generator::State::Stopped, false, true, false),
            (generator::State::Stopped, false, false, true),
            (generator::State::Starting, false, false, false),
            (generator::State::Running, false, false, false),
            (generator::State::Stopping, false, false, false),
            (
                generator::State::Error(generator::Error::OutputStream),
                false,
                false,
                false,
            ),
        ] {
            for restore in [false, true] {
                self.workspace_restoring = restore;
                self.generator.status.state = state;
                self.generator.pending = pending;
                self.generator.starting = starting;
                self.generator.stopping = stopping;
                let stopped = self.generator.stopped();
                driver.frame(self, vec![]);
                driver.frame(self, vec![]);
                driver.text_position(i18n::text("generator.stop_output_2"))?;
                assert_eq!(driver.position("Stop output").is_err(), stopped);
                let marker = self.generator.command_marker();
                // Click the disabled button too; it must not send a command.
                driver.click_at(
                    self,
                    driver.text_position(i18n::text("generator.stop_output_2"))?,
                );
                assert_eq!(self.generator.command_marker().0, marker.0);
                assert_eq!(self.generator.command_marker().1 > marker.1, !stopped);
                if !stopped {
                    driver.click(self, i18n::text("generator.stop_output"))?;
                    assert!(self.generator.command_marker().1 > marker.1 + 1);
                }
            }
        }
        self.generator = saved;
        self.presentation = presentation;
        self.workspace_restoring = restoring;
        driver.frame(self, vec![]);
        println!(
            "Output Stop UI OK: disabled only when fully stopped; pending Start/configuration, transitions, errors and restore remain stoppable; no output started"
        );
        Ok(())
    }

    fn check_cursor_placement_interactions(&mut self, driver: &mut Driver) -> Result<(), String> {
        let saved = std::mem::take(&mut self.cursors);
        let active = self.active_cursor;
        let selected = self.spectrogram_selected.clone();
        let unavailable = self.spectrogram_unavailable_selection;
        let pending = self.spectrogram_pending_click.take();
        driver.frame(self, vec![]);
        driver.text_position(i18n::text("common.place_cursor"))?;
        driver.text_position(i18n::text("common.placed_none"))?;
        driver.text_position(i18n::text("oscilloscope.start_single_capture"))?;
        assert_eq!(
            driver.position("Start single capture").is_ok(),
            !self.running() && self.input_transport_enabled()
        );
        driver.click(self, "B")?;
        assert_eq!(self.active_cursor, 1);
        assert!(self.cursors.times.iter().all(Option::is_none));
        self.cursors.set_scope_time(0, 0.25);
        self.cursors.set_frequency(1, 1500.0);
        self.cursors.set_xy_point(1, [0.125, -0.25]);
        self.spectrogram_unavailable_selection = [true; 2];
        driver.frame(self, vec![]);
        driver.text_position(i18n::text("common.placed_a"))?;
        driver.click(self, "A")?;
        assert_eq!(self.active_cursor, 0);
        assert!(self.cursors.times[0].is_some());
        assert!(self.cursors.times[1].is_none());
        driver.click(self, i18n::text("common.clear_cursors"))?;
        driver.text_position(i18n::text("common.placed_none"))?;
        assert!(self.cursors.times.iter().all(Option::is_none));
        assert_eq!(self.cursors.spectrum_frequencies_hz, [None; 2]);
        assert!(self.cursors.frequency_hz.is_none());
        assert_eq!(self.cursors.xy_points, [None; 2]);
        assert!(self.spectrogram_selected.iter().all(Option::is_none));
        assert_eq!(self.spectrogram_unavailable_selection, [false; 2]);
        assert!(self.spectrogram_pending_click.is_none());
        assert_eq!(self.active_cursor, 0);
        self.cursors = saved;
        self.active_cursor = active;
        self.spectrogram_selected = selected;
        self.spectrogram_unavailable_selection = unavailable;
        self.spectrogram_pending_click = pending;
        driver.frame(self, vec![]);
        println!(
            "Cursor placement UI OK: target selection does not place cursors; placed status and shared Clear cursors scope"
        );
        Ok(())
    }

    fn check_display_scale_interactions(&mut self, driver: &mut Driver) -> Result<(), String> {
        // Use the actual nested menus, including the compact header and a
        // simulated native DPI change. Opening/hovering must not apply zoom.
        for (width, native_scale) in [(1440.0, 1.0), (720.0, 2.0)] {
            driver.resize(self, vec2(width, 1000.0), 1.0, native_scale);
            for percent in [175, 75, 150, 90, 125, 110, 100] {
                let before = driver.ctx.zoom_factor();
                if width < 1180.0 {
                    driver.click(self, i18n::text("shell.menu"))?;
                }
                driver.click(self, i18n::text("shell.view"))?;
                driver.click(self, i18n::text("shell.display_scale"))?;
                for label in ["75%", "90%", "100%", "110%", "125%", "150%", "175%"] {
                    let pos = driver.position(label)?;
                    driver.frame(self, vec![egui::Event::PointerMoved(pos)]);
                    assert_eq!(driver.ctx.zoom_factor(), before);
                }
                driver.click(self, &format!("{percent}%"))?;
                assert_eq!(driver.ctx.zoom_factor(), percent as f32 / 100.0);
                assert!(
                    !egui::Popup::is_any_open(&driver.ctx),
                    "Scale selection left a menu open: {width}, {percent}%"
                );
                // Let the menu's closing animation finish after the zoom
                // changes its area coordinates.
                for _ in 0..10 {
                    driver.frame(self, vec![]);
                }
                assert!(!driver.ctx.any_popup_open());
                driver.check_header()?;
            }
            // Dismissing the scale choices keeps the applied value.
            if width < 1180.0 {
                driver.click(self, i18n::text("shell.menu"))?;
            }
            driver.click(self, i18n::text("shell.view"))?;
            driver.click(self, i18n::text("shell.display_scale"))?;
            driver.key(self, egui::Key::Escape, egui::Modifiers::NONE);
            assert_eq!(driver.ctx.zoom_factor(), 1.0);
            assert!(!driver.ctx.any_popup_open());
        }
        driver.resize(self, vec2(1440.0, 1000.0), 1.0, 1.0);
        println!(
            "Display scale UI OK: seven presets, hover/dismiss unchanged, selection commits and closes menus, wide/compact/native scale"
        );
        Ok(())
    }

    fn check_xy_controls_interactions(&mut self, driver: &mut Driver) -> Result<(), String> {
        let saved = (self.xy_settings, self.xy_cursor_mode, self.trigger);
        let presentation = self.presentation.clone();
        let shell = self.shell.clone();
        let cursors = std::mem::take(&mut self.cursors);
        let scope = (self.scope_channels, self.ms_per_div, self.scope_vertical);
        self.xy_settings.channels = Pair([1, 0]);
        self.xy_settings.milliseconds = 12.3456789;
        self.xy_settings.x_fs_per_div = 0.123456789;
        self.xy_settings.y_fs_per_div = 0.234567891;
        self.xy_cursor_mode = xy::CursorMode::Free;
        self.cursors.set_xy_point(0, [0.125, -0.25]);
        self.cursors.set_xy_point(1, [-0.5, 0.0625]);
        let points = self.cursors.xy_points;
        self.navigate(Action::OpenSingle(Instrument::Xy));
        self.presentation.details_visible = true;
        driver.resize(self, vec2(1440.0, 1000.0), 1.0, 1.0);
        let unedited = self.xy_settings;
        driver.frame(self, vec![]);
        assert_eq!(
            self.xy_settings, unedited,
            "Showing XY sliders rounded f64 settings"
        );

        let reset = driver.position(i18n::text("xy.reset_xy_scales"))?;
        let snap = driver.position(i18n::text("xy.trace_snap"))?;
        assert!(
            reset.x > 1100.0 && snap.x > 1100.0,
            "XY settings are not in the right sidebar"
        );
        driver.click(self, i18n::text("xy.trace_snap"))?;
        assert_eq!(self.xy_cursor_mode, xy::CursorMode::TraceSnap);
        assert_eq!(self.cursors.xy_points, points);
        self.trigger.level = 0.125;
        driver.frame(self, vec![]);
        driver.click(self, i18n::text("oscilloscope.zero_level"))?;
        assert_eq!(self.trigger.level, 0.0);
        assert_eq!(self.xy_settings, unedited);
        driver.click(self, i18n::text("xy.free"))?;
        assert_eq!(self.xy_cursor_mode, xy::CursorMode::Free);
        assert_eq!(self.cursors.xy_points, points);

        driver.click(self, i18n::text("xy.reset_xy_scales"))?;
        assert_eq!(
            self.xy_settings,
            xy::Settings {
                channels: unedited.channels,
                ..xy::Settings::default()
            }
        );
        assert_eq!(self.cursors.xy_points, points);
        assert_eq!(
            (self.scope_channels, self.ms_per_div, self.scope_vertical),
            scope
        );

        // The same controls remain reachable via Details at compact widths.
        driver.resize(self, vec2(980.0, 760.0), 1.25, 1.0);
        driver.click(self, i18n::text("shell.details"))?;
        driver.click(self, i18n::text("xy.trace_snap"))?;
        assert_eq!(self.xy_cursor_mode, xy::CursorMode::TraceSnap);
        driver.click(self, i18n::text("xy.free"))?;
        driver.key(self, egui::Key::Escape, egui::Modifiers::NONE);
        assert!(!self.shell.narrow_details);
        driver.position("A")?;
        (self.xy_settings, self.xy_cursor_mode, self.trigger) = saved;
        self.cursors = cursors;
        self.xy_dirty = true;
        self.dirty = true;
        self.presentation = presentation;
        self.shell = shell;
        driver.resize(self, vec2(1440.0, 1000.0), 1.0, 1.0);
        println!(
            "XY controls UI OK: right sidebar and narrow Details, f64 settings preserved, cursor modes, shared trigger, scale reset preserves sources/cursors/Scope axes"
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
        let quantity = driver.position(i18n::text("spectrum.amplitude"))?;
        let axis = driver.position(i18n::text("spectrogram.log_hz"))?;
        let cursor_a = driver.position("A")?;
        let average = driver.position(i18n::text("spectrum.average"))?;
        let advanced = driver.position(i18n::text("spectrum.advanced_analysis_diagnostics"))?;
        assert!(
            quantity.y < axis.y
                && axis.y < cursor_a.y
                && cursor_a.y < average.y
                && average.y < advanced.y
        );
        driver.click(self, i18n::text("spectrum.psd"))?;
        assert_eq!(self.spectrum_settings.quantity, Quantity::Psd);
        assert_eq!(self.analyzer.settings().quantity, Quantity::Amplitude);
        driver.click(self, i18n::text("spectrum.quantity.esd"))?;
        assert_eq!(self.spectrum_settings.quantity, Quantity::Esd);
        assert_eq!(self.spectrum_settings.window, spectrum::Window::Rectangular);
        assert_eq!(self.spectrum_settings.averages, 1);
        assert!(!self.spectrum_settings.remove_dc);
        assert_eq!(self.analyzer.settings().quantity, Quantity::Amplitude);
        // Restore the held fixture's next-run settings before cursor checks.
        driver.click(self, i18n::text("spectrum.amplitude"))?;
        self.spectrum_settings = settings;
        driver.click(self, i18n::text("spectrum.average"))?;
        assert_eq!(
            self.spectrum_settings.averages,
            self.spectrum_display.average_weight
        );
        driver.position(i18n::text("spectrum.advanced_analysis_diagnostics"))?;
        driver.click(self, i18n::text("spectrum.average"))?;
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
        driver.click(self, "A")?;
        driver.text_position(i18n::text("common.placed_none"))?;
        driver.click_at(self, at(frequency));
        let a = self.cursors.spectrum_frequencies_hz[0]
            .ok_or("Spectrum A did not respond to plot click")?;
        driver.text_position(i18n::text("common.placed_a"))?;
        driver.click(self, "B")?;
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
        self.cursors.set_scope_time(0, 0.25);
        self.cursors.set_xy_point(1, [0.125, -0.25]);
        let times = self.cursors.times;
        let points = self.cursors.xy_points;
        driver.text_position(i18n::text("common.placed_a_b"))?;
        driver.click(self, i18n::text("common.clear_cursors"))?;
        assert_eq!(self.cursors.spectrum_frequencies_hz, [None; 2]);
        assert!(self.cursors.frequency_hz.is_none());
        assert_eq!(self.cursors.times, times);
        assert_eq!(self.cursors.xy_points, points);
        driver.text_position(i18n::text("common.placed_none"))?;

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
