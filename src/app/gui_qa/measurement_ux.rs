//! Regression checks for comparing unequal signals and adjusting beside the plot.
use super::*;

impl ScopeApp {
    fn check_scope_readout_layout(&mut self, driver: &mut Driver) -> Result<(), String> {
        let saved = (
            self.scope_readings,
            self.scope_range.clone(),
            self.presentation.clone(),
            self.shell.clone(),
            self.enabled,
            self.scope_selected,
            self.source,
            self.scope_channels,
            self.core_scope.channels,
            self.held_input.take(),
            self.busy,
        );
        self.presentation.screen = Screen::Single(Instrument::Scope);
        self.presentation.details_visible = false;
        self.shell.narrow_details = false;
        self.scope_selected = 0;
        self.source = Source::Software;
        self.busy = false;
        self.scope_channels = ScopeChannels::default();
        self.core_scope.channels = self.scope_channels;
        self.enabled = [true; SCOPE_CHANNELS];
        let cards = |driver: &Driver| -> Vec<egui::Rect> {
            driver
                .output
                .shapes
                .iter()
                .filter_map(|s| {
                    if let egui::Shape::Rect(shape) = &s.shape
                        && (shape.rect.height() - monitor_controls::SCOPE_CHANNEL_CARD_HEIGHT).abs()
                            < 0.1
                        && shape.stroke.color != Color32::TRANSPARENT
                    {
                        assert!(
                            s.clip_rect.contains_rect(shape.rect),
                            "Channel card is clipped"
                        );
                        Some(shape.rect)
                    } else {
                        None
                    }
                })
                .collect()
        };
        for (size, zoom) in [
            (vec2(1440.0, 1000.0), 1.0),
            (vec2(900.0, 660.0), 1.25),
            (vec2(720.0, 660.0), 1.25),
        ] {
            driver.resize(self, size, zoom, 2.0);
            // Warm the real layout before supplying display-only readings.
            // Driver frames do not poll the measurement worker.
            self.scope_range = 0..32;
            self.dirty = false;
            let mut geometry = None;
            for value in [0.0, 0.1, 0.0625, 0.9999, 1.0, 999999.9999, 1e-12, 1e120] {
                let reading = Reading::Valid(Measurement {
                    rms: value,
                    peak_to_peak: value * 2.0,
                    peak: value,
                    samples: 32,
                });
                self.scope_readings =
                    [reading, reading, Reading::Unavailable, Reading::Unavailable];
                driver.frame(self, vec![egui::Event::PointerGone]);
                let plot = driver.scope_plot()?;
                let card_rects = cards(driver);
                assert_eq!(card_rects.len(), SCOPE_CHANNELS);
                assert!(card_rects.iter().all(|r| r.top() > plot.bottom()));
                let mut fields = Vec::new();
                for shape in &driver.output.shapes {
                    if let egui::Shape::Text(text) = &shape.shape
                        && let Some(card) = card_rects.iter().find(|r| r.contains(text.pos))
                        && text.pos.y >= card.top() + 38.0
                        && text.fallback_color != MUTED
                    {
                        assert!(
                            shape.clip_rect.contains_rect(text.visual_bounding_rect()),
                            "Readout clipped: {}",
                            text.galley.text()
                        );
                        let label = text.galley.text();
                        if label == "FS" || label == "RMS" || label == "P-P" {
                            fields.push((label.to_owned(), text.pos));
                        } else {
                            fields.push((
                                "number-right".into(),
                                text.pos + vec2(text.galley.size().x, 0.0),
                            ));
                        }
                    }
                }
                assert_eq!(fields.len(), 12, "Missing RMS/P-P labels, values or units");
                let current = (plot, card_rects, fields);
                if let Some(expected) = &geometry {
                    assert_eq!(
                        &current, expected,
                        "Reading digits moved another field or the plot"
                    );
                } else {
                    geometry = Some(current);
                }
                assert_eq!(
                    driver
                        .text_positions(i18n::text("oscilloscope.out_of_range"))
                        .len(),
                    2,
                    "Range status: input={:?}, notice={:?}, sources={:?}, readout={:?}",
                    self.scope_input_channels(),
                    self.scope_notice(),
                    self.scope_view_channels(),
                    self.scope_readout(2)
                );
                assert!(
                    driver
                        .text_positions(i18n::text("oscilloscope.channel_out_of_range"))
                        .is_empty()
                );
            }
            // Invalid and missing data occupy the same reserved geometry.
            self.scope_readings[0] = Reading::NonFinite;
            self.scope_readings[1] = Reading::Unavailable;
            driver.frame(self, vec![]);
            let (plot, card_rects, _) = geometry.unwrap();
            assert_eq!(driver.scope_plot()?, plot);
            assert_eq!(cards(driver), card_rects);
            driver.visible_text_rect(i18n::text("oscilloscope.invalid_value"))?;
            driver.visible_text_rect(i18n::text("oscilloscope.no_samples_in_this_interval"))?;
        }
        (
            self.scope_readings,
            self.scope_range,
            self.presentation,
            self.shell,
            self.enabled,
            self.scope_selected,
            self.source,
            self.scope_channels,
            self.core_scope.channels,
            self.held_input,
            self.busy,
        ) = saved;
        self.dirty = true;
        driver.resize(self, vec2(1440.0, 1000.0), 1.0, 1.0);
        println!(
            "Scope readout layout OK: digit/notation changes preserve labels, numeric right edges, units, channel cards and plot; range status appears once per unavailable channel"
        );
        Ok(())
    }

    pub(super) fn check_measurement_ux_interactions(
        &mut self,
        driver: &mut Driver,
    ) -> Result<(), String> {
        self.check_scope_readout_layout(driver)?;
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
