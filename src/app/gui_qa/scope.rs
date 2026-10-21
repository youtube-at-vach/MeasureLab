//! Scope acceptance through the real controls and software measurement worker.
use super::*;

impl Driver {
    pub(super) fn scope_plot(&self) -> Result<egui::Rect, String> {
        self.output
            .shapes
            .iter()
            .find_map(|shape| match &shape.shape {
                egui::Shape::Callback(callback) => Some(callback.rect),
                _ => None,
            })
            .ok_or("Scope plot is not visible".into())
    }

    fn check_scope_guides(&mut self, app: &mut ScopeApp) -> Result<(), String> {
        let cursors = std::mem::take(&mut app.cursors);
        self.frame(app, vec![egui::Event::PointerGone]);
        let rect = self.scope_plot()?;
        let point = rect.lerp_inside(vec2(0.65, 0.6));
        for (event, expected) in [
            (egui::Event::PointerMoved(point), 1),
            (
                egui::Event::PointerMoved(pos2(rect.left() - 8.0, point.y)),
                0,
            ),
            (egui::Event::PointerGone, 0),
        ] {
            self.frame(app, vec![event]);
            let guides = self
                .output
                .shapes
                .iter()
                .filter(|shape| {
                    matches!(&shape.shape, egui::Shape::LineSegment { points, stroke }
                    if *stroke == Stroke::new(1.0, Color32::from_white_alpha(65))
                        && points[0].x == points[1].x
                        && (points[0].y - rect.top()).abs() < 0.1
                        && (points[1].y - rect.bottom()).abs() < 0.1)
                })
                .count();
            assert_eq!(
                guides, expected,
                "Scope hover guide did not follow the pointer"
            );
            // Trigger markers remain short; they must not look like a cursor.
            assert!(!self.output.shapes.iter().any(|shape| {
                matches!(&shape.shape, egui::Shape::LineSegment { points, stroke }
                    if stroke.color == TRIGGER && (points[0].y - points[1].y).abs() > 13.0)
            }));
        }
        app.cursors.set_scope_time(0, 0.3);
        app.cursors.set_scope_time(1, 0.7);
        let placed = app.cursors.times;
        self.frame(app, vec![egui::Event::PointerMoved(point)]);
        self.frame(app, vec![egui::Event::PointerGone]);
        assert_eq!(
            app.cursors.times, placed,
            "Pointer exit changed placed cursors"
        );
        self.visible_text_rect("Placed: A, B")?;
        app.cursors = cursors;
        Ok(())
    }
}

impl ScopeApp {
    pub(in crate::app) fn check_analysis_guidance(&mut self) -> Result<(), String> {
        let saved = (
            self.presentation.clone(),
            self.shell.clone(),
            self.lockin_settings,
            self.lockin_result.clone(),
            self.comparison_settings,
            Arc::clone(&self.comparison_result),
            self.software_running,
            self.busy,
        );
        self.shell = shell::Shell::default();
        self.busy = false;
        self.lockin_settings.enabled = false;
        self.lockin_result = lockin::Analyzer::new(self.lockin_settings, self.sample_rate)
            .result()
            .clone();
        self.presentation
            .apply(Action::OpenSingle(Instrument::Lockin));
        let mut driver = Driver::new();
        driver.resize(self, vec2(1440.0, 1200.0), 1.0, 1.0);
        driver.text_position("Select SIG / REF channels, press Start analysis, then Start input if input is stopped.")?;
        assert!(
            driver
                .text_positions("Enable Demodulate, select SIG / REF channels, then Start input.")
                .is_empty()
        );
        self.presentation
            .apply(Action::OpenSingle(Instrument::Comparison));
        for (state, running, expected) in [
            (
                comparison::State::Disabled,
                false,
                "Select REF / SIG channels, then press Start analysis.",
            ),
            (
                comparison::State::Filling,
                false,
                "Press Start input to acquire a complete average.",
            ),
            (
                comparison::State::Averaging,
                false,
                "Press Start input to acquire a complete average.",
            ),
            (
                comparison::State::Filling,
                true,
                "Waiting for a complete average.",
            ),
            (
                comparison::State::Missing,
                true,
                "Input gap · waiting for a new complete average.",
            ),
            (
                comparison::State::Missing,
                false,
                "Input gap · press Start input to acquire again.",
            ),
            (
                comparison::State::NonFinite,
                true,
                "Invalid input · no valid comparison is available.",
            ),
        ] {
            self.comparison_settings.enabled = state != comparison::State::Disabled;
            let mut result = comparison::Result::empty(
                self.comparison_settings,
                self.sample_rate,
                self.input_generation,
                0,
                2,
            );
            result.state = state;
            self.comparison_result = Arc::new(result);
            self.software_running = running;
            driver.frame(self, vec![]);
            driver.frame(self, vec![]);
            driver.text_position(expected)?;
            if state == comparison::State::Disabled {
                assert!(
                    driver
                        .text_positions("Waiting for a complete average.")
                        .is_empty()
                );
            }
        }
        (
            self.presentation,
            self.shell,
            self.lockin_settings,
            self.lockin_result,
            self.comparison_settings,
            self.comparison_result,
            self.software_running,
            self.busy,
        ) = saved;
        println!(
            "Analysis guidance UI OK: current Start analysis label, disabled/input-stopped/waiting/gap/invalid reasons; synthetic states, no streams opened"
        );
        Ok(())
    }

    pub(in crate::app) fn check_generator_scope_views(&mut self) -> Result<(), String> {
        let presentation = self.presentation.clone();
        let shell = self.shell.clone();
        self.presentation = Presentation::default();
        self.shell = shell::Shell::default();
        self.poll_measurement();
        self.generator.poll();
        let output = self.generator.status;
        let core = self.core.as_ref().unwrap();
        let frames = core.metrics.input_frames.load(Ordering::Relaxed);
        let windows = core.spectrum.metrics.windows.load(Ordering::Relaxed);
        self.check_scope_views(&mut Driver::new())?;
        self.wait_scope(|app| {
            let core = app.core.as_ref().unwrap();
            core.metrics.input_frames.load(Ordering::Relaxed) > frames
                && core.spectrum.metrics.windows.load(Ordering::Relaxed) > windows
        })?;
        self.generator.poll();
        assert_eq!(self.generator.status.state, generator::State::Running);
        assert_eq!(
            self.generator.status.output_generation,
            output.output_generation
        );
        assert_eq!(self.generator.status.settings, output.settings);
        assert!(self.generator.status.next_sample > output.next_sample);
        self.presentation = presentation;
        self.shell = shell;
        println!(
            "Generator view UI OK: live Scope/split/narrow/scale/pointer changes preserve input/analysis/output execution, conditions and output generation"
        );
        Ok(())
    }

    fn wait_scope(&mut self, ready: impl Fn(&Self) -> bool) -> Result<(), String> {
        let deadline = Instant::now() + Duration::from_secs(5);
        loop {
            self.poll_measurement();
            if ready(self) {
                return Ok(());
            }
            if Instant::now() >= deadline {
                return Err(format!(
                    "Scope workflow timed out: running {}, state {:?}, notice {:?}, error {:?}",
                    self.running(),
                    self.acquisition_state,
                    self.scope_notice(),
                    self.input_error
                ));
            }
            std::thread::sleep(Duration::from_millis(5));
        }
    }

    fn check_scope_views(&mut self, driver: &mut Driver) -> Result<(), String> {
        let generation = self.input_generation;
        let command = self.generator.command_marker();
        let conditions = self.core_config();
        let running = self.running();
        let held = (!running)
            .then(|| self.capture_scope_results())
            .transpose()?;
        for (width, height, zoom, native_scale) in [
            (1440.0, 860.0, 1.0, 1.0),
            (1040.0, 780.0, 1.25, 2.0),
            (720.0, 640.0, 1.25, 1.0),
        ] {
            driver.resize(self, vec2(width, height), zoom, native_scale);
            driver.check_header()?;
            driver.visible_text_rect("Amplitude [FS]")?;
            driver.visible_text_rect("Time [ms]")?;
            driver.position("CH1")?;
            driver.position("CH4")?;
            driver.text_position("Stop output")?;
            driver.check_scope_guides(self)?;
        }
        driver.resize(self, vec2(1440.0, 860.0), 1.0, 1.0);
        driver.click(self, "Split view with…")?;
        driver.click(self, "Spectrum")?;
        assert_eq!(self.presentation.screen, Screen::Console);
        if self.presentation.selected() != Some(Instrument::Scope) {
            driver.key(self, egui::Key::ArrowLeft, egui::Modifiers::CTRL);
        }
        assert_eq!(self.presentation.selected(), Some(Instrument::Scope));
        for width in [1440.0, 720.0] {
            driver.resize(self, vec2(width, 860.0), 1.0, 2.0);
            driver.visible_text_rect("Scope · Selected")?;
            driver.text_position("Stop output")?;
        }
        driver.key(self, egui::Key::Num1, egui::Modifiers::CTRL);
        assert_eq!(self.presentation.screen, Screen::Single(Instrument::Scope));
        driver.resize(self, vec2(1440.0, 1000.0), 1.0, 1.0);
        for compact in [true, false] {
            driver.click_at(self, driver.sidebar_toggle()?.center());
            assert_eq!(self.shell.sidebar_compact, compact);
            driver.visible_text_rect("Amplitude [FS]")?;
            driver.visible_text_rect("Time [ms]")?;
            driver.text_position("Stop output")?;
        }
        assert_eq!(self.input_generation, generation);
        assert_eq!(self.running(), running);
        assert_eq!(self.generator.command_marker(), command);
        let after = self.core_config();
        assert_eq!(after.scope, conditions.scope);
        assert_eq!(after.spectrum, conditions.spectrum);
        assert_eq!(after.lockin, conditions.lockin);
        assert_eq!(after.comparison, conditions.comparison);
        assert_eq!(after.calibrations, conditions.calibrations);
        if let Some(held) = held {
            let after = self.capture_scope_results()?;
            assert_eq!(after.input, held.input);
            assert_eq!(after.scope, held.scope);
            assert_eq!(after.loss, held.loss);
        }
        Ok(())
    }

    pub(in crate::app) fn check_scope_workflow(&mut self, mode: &str) -> Result<(), String> {
        if !matches!(
            mode,
            "held" | "waiting" | "single" | "error" | "error-empty"
        ) {
            return Err(format!("Unknown Scope workflow mode: {mode}"));
        }
        assert!(self.core.is_none() && !self.running());
        self.poll_audio();
        self.presentation = Presentation::default();
        self.shell = shell::Shell::default();
        self.acquisition_mode = acquisition::Mode::Auto;
        self.trigger = Trigger::default();
        self.dirty = true;
        let mut driver = Driver::new();
        driver.frame(self, vec![]);
        driver.frame(self, vec![]);
        assert!(self.scope_notice().is_some());
        driver.click(self, "Open input settings")?;
        driver.click(self, "Software Loopback")?;
        assert!(self.source == Source::Software);
        driver.click(self, "Back to instruments")?;
        self.core = Some(measurement::Worker::new(self.stft.take_feeder()));
        self.loopback_settings = loopback::Settings::default();
        let command = self.generator.command_marker();
        driver.click(self, "▶  Start input")?;
        self.wait_scope(|app| !app.scope_range.is_empty() && app.analyzer.is_ready())?;
        assert!(self.scope_notice().is_none());
        assert!(matches!(self.scope_readings[0], Reading::Valid(_)));
        let core = self.core.as_ref().unwrap();
        let frames = core.metrics.input_frames.load(Ordering::Relaxed);
        let windows = core.spectrum.metrics.windows.load(Ordering::Relaxed);
        self.check_scope_views(&mut driver)?;
        self.wait_scope(|app| {
            let core = app.core.as_ref().unwrap();
            core.metrics.input_frames.load(Ordering::Relaxed) > frames
                && core.spectrum.metrics.windows.load(Ordering::Relaxed) > windows
        })?;
        driver.click(self, "■  Stop input")?;
        self.wait_scope(|app| app.pending_stop.is_none())?;
        driver.frame(self, vec![]);
        driver.visible_text_rect("HELD")?;
        self.check_scope_views(&mut driver)?;
        if mode != "held" {
            // An unreachable trigger makes Single's waiting state deterministic.
            self.trigger.level = 0.9;
            self.dirty = true;
            driver.frame(self, vec![]);
            let generation = self.input_generation;
            driver.click(self, "Start single capture")?;
            assert_eq!(self.input_generation, generation + 1);
            self.wait_scope(|app| !app.history.is_empty())?;
            driver.frame(self, vec![]);
            assert_eq!(
                self.scope_notice(),
                Some(display::ScopeNotice::WaitingForTrigger)
            );
            driver.visible_text_rect(display::ScopeNotice::WaitingForTrigger.title())?;
            if mode != "waiting" {
                driver.click(self, "■  Stop input")?;
                self.wait_scope(|app| app.pending_stop.is_none())?;
                driver.frame(self, vec![]);
                assert_eq!(self.scope_notice(), Some(display::ScopeNotice::Incomplete));
                self.trigger.level = 0.0;
                self.dirty = true;
                driver.click(self, "Start single capture")?;
                self.wait_scope(|app| !app.running() && app.pending_stop.is_none())?;
                assert_eq!(self.acquisition_state, acquisition::State::Complete);
                assert!(self.triggered && !self.scope_range.is_empty());
                self.check_scope_views(&mut driver)?;
                if mode != "single" {
                    driver.click(self, "Auto")?;
                    driver.click(self, "▶  Start input")?;
                    self.wait_scope(|app| !app.scope_range.is_empty())?;
                    self.fail_input("Simulated input error · Software Loopback QA".into());
                    self.wait_scope(|app| app.pending_stop.is_none())?;
                    assert!(self.scope_notice().is_none());
                    assert!(!self.scope_range.is_empty());
                    self.check_scope_views(&mut driver)?;
                    if mode == "error-empty" {
                        self.trigger.level = 0.9;
                        self.dirty = true;
                        driver.frame(self, vec![]);
                        driver.click(self, "Start single capture")?;
                        assert!(self.input_error.is_none());
                        self.wait_scope(|app| !app.history.is_empty())?;
                        self.fail_input(
                            "Simulated input error before capture · Software Loopback QA".into(),
                        );
                        self.wait_scope(|app| app.pending_stop.is_none())?;
                        assert_eq!(self.scope_notice(), Some(display::ScopeNotice::Failed));
                    } else if mode != "error" {
                        return Err(format!("Unknown Scope workflow mode: {mode}"));
                    }
                }
            }
        }
        assert_eq!(self.generator.command_marker(), command);
        assert!(self.generator.stopped());
        self.presentation = Presentation::default();
        self.shell = shell::Shell::default();
        self.dirty = true;
        println!(
            "Scope workflow UI OK: {mode}; input settings/real Software Loopback, live/held view and scale invariants, analysis continues, pointer guides, Single wait/stop/completion, simulated failure/restart as reached; output commands unchanged"
        );
        Ok(())
    }
}
