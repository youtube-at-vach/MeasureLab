//! XY settings share the selected-instrument sidebar with Scope.
use super::scope_controls::{control_group, control_slider};
use super::*;

impl ScopeApp {
    pub(super) fn xy_controls(&mut self, ui: &mut egui::Ui) {
        let before = self.xy_settings;
        control_group(ui, "OBSERVATION", BLUE, |ui| {
            control_slider(
                ui,
                "Observation window",
                egui::Slider::new(&mut self.xy_settings.milliseconds, 0.5..=200.0)
                    .logarithmic(true)
                    .suffix(" ms")
                    .max_decimals(3)
                    .drag_value_speed(0.5),
                None,
            );
            if ui.button("Reset XY scales").clicked() {
                self.xy_settings = xy::Settings {
                    channels: self.xy_settings.channels,
                    ..xy::Settings::default()
                };
            }
        });

        let channels = self.lockin_channel_count().max(self.scope_channel_count());
        for (index, title, color) in [(0, "X AXIS", BLUE), (1, "Y AXIS", PURPLE)] {
            control_group(ui, title, color, |ui| {
                ui.horizontal(|ui| {
                    ui.label("Input source");
                    channel_select(
                        ui,
                        if index == 0 {
                            "xy_x_source"
                        } else {
                            "xy_y_source"
                        },
                        &mut self.xy_settings.channels.0[index],
                        channels,
                    );
                });
                control_slider(
                    ui,
                    "Amplitude range",
                    egui::Slider::new(
                        if index == 0 {
                            &mut self.xy_settings.x_fs_per_div
                        } else {
                            &mut self.xy_settings.y_fs_per_div
                        },
                        0.001..=0.5,
                    )
                    .logarithmic(true)
                    .suffix(" FS/div")
                    .max_decimals(3)
                    .drag_value_speed(0.001),
                    None,
                );
            });
        }
        if self.xy_settings.channels != before.channels
            && self.running()
            && let Some(core) = &self.core
        {
            core.configure_xy(self.xy_settings.channels);
        }
        self.xy_dirty |= self.xy_settings != before;
        if !self.running() && self.xy_settings.channels != self.xy_view_settings().channels {
            ui.label(
                RichText::new("Source changes apply on Start. Held XY keeps its channels.")
                    .small()
                    .color(YELLOW),
            );
        }
        if channels < 2 {
            ui.label(
                RichText::new("XY requires at least two input channels.")
                    .small()
                    .color(YELLOW),
            );
        }

        control_group(ui, "CURSORS", PURPLE, |ui| {
            let before = self.xy_cursor_mode;
            ui.horizontal_wrapped(|ui| {
                ui.selectable_value(&mut self.xy_cursor_mode, xy::CursorMode::Free, "Free")
                    .on_hover_text("Fix X/Y amplitudes independently of the moving trace. Measure ΔX and ΔY.");
                ui.selectable_value(&mut self.xy_cursor_mode, xy::CursorMode::TraceSnap, "Trace Snap")
                    .on_hover_text("Follow a real sample at a fixed time offset from the XY trigger. Uses Scope trigger settings.");
            });
            self.xy_dirty |= self.xy_cursor_mode != before;
            ui.label(RichText::new(match self.xy_cursor_mode {
                xy::CursorMode::Free => "Free keeps X/Y amplitudes fixed and reads ΔX/ΔY. Cursor positions are retained when switching modes.",
                xy::CursorMode::TraceSnap => "Trace Snap follows a trigger-relative sample. Auto/free run may move the marker; Stop freezes it.",
            }).small().color(MUTED));
        });
        if self.xy_cursor_mode == xy::CursorMode::TraceSnap {
            control_group(ui, "TRIGGER", TRIGGER, |ui| {
                ui.label(RichText::new("Shared with Scope").small().color(MUTED));
                self.trigger_controls(ui);
            });
        }
        ui.label(RichText::new("X/Y use the same input frame. Equal axis scales preserve circles on the square plot.").small().color(MUTED));
        ui.label(
            RichText::new(format!(
                "Up to {} real sample pairs; longer windows show the latest portion.",
                xy::MAX_POINTS
            ))
            .small()
            .color(MUTED),
        );
    }
}
