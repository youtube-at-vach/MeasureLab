//! Regression checks for comparing unequal signals and adjusting beside the plot.
use super::*;

impl ScopeApp {
    pub(super) fn check_measurement_ux_interactions(
        &mut self,
        driver: &mut Driver,
    ) -> Result<(), String> {
        let saved = (
            self.presentation.clone(),
            self.shell.clone(),
            self.enabled,
            self.scope_selected,
            self.scope_vertical,
            self.scope_common_vertical,
            self.ms_per_div,
            self.measurements,
        );
        let generation = self.input_generation;
        let command = self.generator.command_marker();
        self.presentation.screen = Screen::Single(Instrument::Scope);
        self.presentation.details_visible = true;
        self.shell.narrow_details = false;
        self.enabled = [true, true, false, false];
        self.scope_selected = 0;
        self.scope_vertical[0] = Vertical {
            fs_per_div: 0.04,
            offset: 0.0,
        };
        self.scope_vertical[1] = Vertical {
            fs_per_div: 0.02,
            offset: 0.0,
        };
        self.scope_common_vertical = None;
        self.ms_per_div = 0.3;
        driver.resize(self, vec2(900.0, 660.0), 1.0, 2.0);
        driver.visible_text_rect(i18n::text("oscilloscope.per_channel_scale"))?;
        driver.scope_plot()?;
        let independent = self.scope_vertical;
        // These unequal inputs looked equally tall with independent scales.
        assert_eq!(
            self.scope_display_vertical(0).y(0.1),
            self.scope_display_vertical(1).y(0.05)
        );
        driver.click(self, i18n::text("oscilloscope.common_scale"))?;
        let shared = self.scope_display_vertical(0);
        assert_eq!(shared, self.scope_display_vertical(1));
        let zero = shared.y(0.0);
        let ratio = (zero - shared.y(0.05)) / (zero - shared.y(0.1));
        assert!((ratio - 0.5).abs() < 1e-6);
        // A trigger source outside the displayed traces still uses the shared axis.
        let trigger_state = (
            self.trigger,
            self.core_scope.trigger,
            self.scope_trigger_display,
        );
        self.trigger.channel = 15;
        self.trigger.level = 0.08;
        self.trigger.edge = Edge::Rising;
        self.core_scope.trigger = self.trigger;
        self.scope_trigger_display = settings::TriggerDisplay::Markers;
        driver.frame(self, vec![]);
        let plot = driver.scope_plot()?;
        let marker_y = driver
            .output
            .shapes
            .iter()
            .find_map(|s| {
                if let egui::Shape::Path(path) = &s.shape
                    && path.fill == TRIGGER
                    && path.points.len() == 3
                    && path.points[0].x > plot.right()
                {
                    Some(path.points[0].y)
                } else {
                    None
                }
            })
            .ok_or("Shared-axis trigger marker is missing")?;
        assert!(
            (marker_y - (plot.top() + shared.y(self.trigger.level) * plot.height())).abs() < 0.1
        );
        (
            self.trigger,
            self.core_scope.trigger,
            self.scope_trigger_display,
        ) = trigger_state;
        driver.frame(self, vec![]);
        driver.click(self, "CH2")?;
        assert_eq!(self.scope_display_vertical(0), shared);
        driver.visible_text_rect(self.scope_axis_label().as_ref())?;
        // Edit the quick timebase through its real DragValue, with the plot visible.
        let pos = driver
            .ctx
            .data(|data| data.get_temp::<egui::Rect>(egui::Id::new("qa_scope_timebase")))
            .ok_or("Quick timebase is missing")?
            .center();
        driver.click_at(self, pos);
        assert!(
            driver.ctx.text_edit_focused(),
            "Quick timebase did not enter text editing"
        );
        driver.key(self, egui::Key::A, egui::Modifiers::COMMAND);
        driver.frame(self, vec![egui::Event::Text("0.15".into())]);
        driver.key(self, egui::Key::Enter, egui::Modifiers::NONE);
        assert!(
            (self.ms_per_div - 0.15).abs() < 1e-6,
            "Quick timebase: {}",
            self.ms_per_div
        );
        assert!(!self.shell.narrow_details);
        driver.scope_plot()?;
        self.measurements[0].peak = 0.1;
        self.measurements[1].peak = 0.05;
        self.fit_scope_amplitude();
        assert!((self.scope_display_vertical(1).fs_per_div as f64 - 0.1 / 3.5).abs() < 1e-7);
        driver.frame(self, vec![]);
        driver.click(self, i18n::text("oscilloscope.per_channel_scale"))?;
        assert_eq!(self.scope_vertical, independent);
        assert_eq!(self.scope_display_vertical(1), independent[1]);
        // Navigation to the displayed connection's settings does not start I/O.
        self.presentation.screen = Screen::Single(Instrument::Generator);
        driver.frame(self, vec![]);
        driver.click(self, i18n::text("common.open_input_settings"))?;
        assert!(self.shell.io == Some(shell::IoTab::Connections));
        assert_eq!(self.input_generation, generation);
        assert_eq!(self.generator.command_marker(), command);
        (
            self.presentation,
            self.shell,
            self.enabled,
            self.scope_selected,
            self.scope_vertical,
            self.scope_common_vertical,
            self.ms_per_div,
            self.measurements,
        ) = saved;
        self.dirty = true;
        driver.resize(self, vec2(1440.0, 1000.0), 1.0, 1.0);
        println!(
            "Measurement UX UI OK: common scale preserves 2:1 amplitude and independent settings, CH selection preserves shared axis, quick timebase keeps plot visible, Generator input-settings navigation leaves I/O unchanged"
        );
        Ok(())
    }
}
