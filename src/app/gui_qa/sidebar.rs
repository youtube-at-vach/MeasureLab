//! Click and hover the real rail, checking layout and measurement isolation.
use super::*;

impl Driver {
    fn sidebar_control(&self, id: egui::Id) -> Result<egui::Rect, String> {
        self.ctx
            .data(|data| data.get_temp(id))
            .ok_or("Sidebar control missing".into())
    }

    pub(super) fn sidebar_toggle(&self) -> Result<egui::Rect, String> {
        self.sidebar_control(egui::Id::unique("qa_sidebar_toggle"))
    }

    fn navigation_rect(&self, instrument: Option<Instrument>) -> Result<egui::Rect, String> {
        self.sidebar_control(egui::Id::unique(("qa_navigation", instrument)))
    }
}

impl ScopeApp {
    pub(super) fn check_sidebar_interactions(&mut self, driver: &mut Driver) -> Result<(), String> {
        let presentation = self.presentation.clone();
        let shell = self.shell.clone();
        let generation = self.input_generation;
        let running = self.running();
        let command = self.generator.command_marker();
        let conditions = (
            self.scope_channels,
            self.spectrum_settings,
            self.lockin_settings,
            self.comparison_settings,
            self.generator.settings,
        );
        let held = self.capture_results().ok();
        self.presentation = Presentation::default();
        self.shell = shell::Shell::default();
        self.presentation.details_visible = false;
        driver.frame(self, vec![]);
        driver.frame(self, vec![]);
        let full_plot = driver.scope_plot()?;
        let toggle = driver.sidebar_toggle()?.center();
        // Hover has no side effects.
        driver.frame(self, vec![egui::Event::PointerMoved(toggle)]);
        assert!(!self.shell.sidebar_compact);
        // Even a full-list filter must not remove or reorder compact icons.
        self.shell.search = "no matching instrument".into();
        driver.click_at(self, toggle);
        assert!(self.shell.sidebar_compact);
        driver.frame(self, vec![egui::Event::PointerGone]);
        let compact_plot = driver.scope_plot()?;
        assert!(compact_plot.width() > full_plot.width() + 150.0);
        assert!((compact_plot.right() - full_plot.right()).abs() < 1.0);
        let rows = Instrument::ALL.map(|i| driver.navigation_rect(Some(i)).unwrap());
        for pair in rows.windows(2) {
            assert!(pair[0].bottom() < pair[1].top());
            assert!((pair[0].left() - pair[1].left()).abs() < 0.1);
        }
        for (instrument, row) in Instrument::ALL.into_iter().zip(rows) {
            driver.click_at(self, row.center());
            assert_eq!(self.presentation.screen, Screen::Single(instrument));
            driver.click_at(self, row.center());
            assert_eq!(self.presentation.screen, Screen::Single(instrument));
            assert_eq!(driver.navigation_rect(Some(instrument))?, row);
        }
        // Tooltip includes the name and actual run state, without changing selection.
        driver.ctx.global_style_mut(|style| {
            style.interaction.tooltip_delay = 0.0;
            style.interaction.show_tooltips_only_when_still = false;
        });
        // egui intentionally suppresses tooltips after clicks. Let that
        // interval pass before moving to another icon, using simulated frames.
        for _ in 0..10 {
            driver.frame(self, vec![egui::Event::PointerGone]);
        }
        let pos = rows[1].center();
        for _ in 0..6 {
            driver.frame(self, vec![egui::Event::PointerMoved(pos)]);
        }
        let state = if self.pending_stop.is_some() {
            "Input · finishing analysis"
        } else if self.busy {
            "Input · opening device"
        } else if self.running() {
            "Shared input · live"
        } else {
            "Shared input · stopped"
        };
        driver.text_position(&format!("Spectrum\n{state}"))?;
        assert_eq!(
            self.presentation.screen,
            Screen::Single(Instrument::Generator)
        );
        driver.frame(self, vec![egui::Event::PointerGone]);
        // Every icon has a fixed cell even when I/O owns the central page.
        self.shell.io = Some(shell::IoTab::Connections);
        driver.frame(self, vec![]);
        driver.click_at(self, rows[0].center());
        assert!(self.shell.io.is_none());
        let console = self.presentation.console.clone();
        driver.click_at(self, driver.navigation_rect(None)?.center());
        assert_eq!(self.presentation.screen, Screen::Console);
        assert_eq!(self.presentation.console, console);
        driver.click_at(self, rows[0].center());
        let compact_plot = driver.scope_plot()?;
        // Narrow layout temporarily hides the rail; its preference survives resizing/scale.
        driver.size = vec2(1040.0, 780.0);
        driver.frame(self, vec![]);
        driver.text_position(i18n::text("shell.menu"))?;
        assert!(self.shell.sidebar_compact);
        for compact in [false, true] {
            driver.click(self, i18n::text("shell.menu"))?;
            driver.click(self, i18n::text("shell.view"))?;
            driver.click(self, i18n::text("shell.compact_sidebar"))?;
            assert_eq!(self.shell.sidebar_compact, compact);
            driver.key(self, egui::Key::Escape, egui::Modifiers::NONE);
            driver.key(self, egui::Key::Escape, egui::Modifiers::NONE);
        }
        driver.size = vec2(1440.0, 1000.0);
        driver.native_scale = 2.0;
        driver.frame(self, vec![]);
        driver.frame(self, vec![]);
        // Native scale can round a logical edge to a different physical pixel.
        let same_bounds = |a: egui::Rect, b: egui::Rect| {
            a.min.distance(b.min) < 2.0 && a.max.distance(b.max) < 2.0
        };
        assert!(same_bounds(
            driver.navigation_rect(Some(Instrument::Scope))?,
            rows[0]
        ));
        assert!(same_bounds(driver.scope_plot()?, compact_plot));
        driver.click_at(self, driver.sidebar_toggle()?.center());
        assert!(!self.shell.sidebar_compact);
        driver.frame(self, vec![]);
        assert!(same_bounds(driver.scope_plot()?, full_plot));
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
            let measurement = |doc: &export::Document| -> Result<serde_json::Value, String> {
                let mut value = serde_json::to_value(doc).map_err(|e| e.to_string())?;
                value
                    .as_object_mut()
                    .unwrap()
                    .remove("exported_unix_seconds");
                Ok(value)
            };
            assert_eq!(measurement(&self.capture_results()?)?, measurement(&held)?);
        }
        self.presentation = presentation;
        self.shell = shell;
        driver.native_scale = 1.0;
        driver.frame(self, vec![]);
        driver.frame(self, vec![]);
        println!(
            "Sidebar UI OK: toggle, seven fixed icons, selection/reselection, tooltip, I/O return, console, plot expansion, resize/scale, measurement isolation"
        );
        Ok(())
    }
}
