//! XY settings share the selected-instrument sidebar with Scope.
use super::scope_controls::{control_group, control_slider_response};
use super::*;

impl ScopeApp {
    pub(super) fn xy_controls(&mut self, ui: &mut egui::Ui) {
        let before = self.xy_settings;
        control_group(ui, i18n::text("xy.observation"), BLUE, |ui| {
            let (response, _) = control_slider_response(
                ui,
                i18n::text("xy.observation_window"),
                egui::Slider::new(&mut self.xy_settings.milliseconds, 0.5..=200.0)
                    .logarithmic(true)
                    .suffix(" ms")
                    .max_decimals(3)
                    .drag_value_speed(0.5),
                None,
            );
            #[cfg(feature = "qa")]
            ui.ctx().data_mut(|data| {
                data.insert_temp(egui::Id::unique("qa_xy_window"), response.rect);
            });
            #[cfg(not(feature = "qa"))]
            let _ = response;
            if ui.button(i18n::text("xy.reset_xy_scales")).clicked() {
                self.xy_settings = xy::Settings {
                    channels: self.xy_settings.channels,
                    ..xy::Settings::default()
                };
            }
        });

        let channels = self.lockin_channel_count().max(self.scope_channel_count());
        for (index, title, color) in [
            (0, i18n::text("xy.x_axis"), BLUE),
            (1, i18n::text("xy.y_axis"), PURPLE),
        ] {
            control_group(ui, title, color, |ui| {
                ui.horizontal(|ui| {
                    ui.label(i18n::text("xy.input_source"));
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
                let (response, _) = control_slider_response(
                    ui,
                    i18n::text("xy.amplitude_range"),
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
                #[cfg(feature = "qa")]
                ui.ctx().data_mut(|data| {
                    data.insert_temp(
                        egui::Id::unique(if index == 0 {
                            "qa_xy_x_scale"
                        } else {
                            "qa_xy_y_scale"
                        }),
                        response.rect,
                    );
                });
                #[cfg(not(feature = "qa"))]
                let _ = response;
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
                RichText::new(i18n::text(
                    "xy.source_changes_apply_on_start_held_xy_keeps_its",
                ))
                .small()
                .color(YELLOW),
            );
        }
        if channels < 2 {
            ui.label(
                RichText::new(i18n::text("xy.xy_requires_at_least_two_input_channels"))
                    .small()
                    .color(YELLOW),
            );
        }

        control_group(ui, i18n::text("xy.cursors"), PURPLE, |ui| {
            let before = self.xy_cursor_mode;
            ui.horizontal_wrapped(|ui| {
                ui.selectable_value(
                    &mut self.xy_cursor_mode,
                    xy::CursorMode::Free,
                    i18n::text("xy.free"),
                )
                .on_hover_text(i18n::text(
                    "xy.fix_x_y_amplitudes_independently_of_the_moving_trace",
                ));
                ui.selectable_value(
                    &mut self.xy_cursor_mode,
                    xy::CursorMode::TraceSnap,
                    i18n::text("xy.trace_snap"),
                )
                .on_hover_text(i18n::text("xy.follow_a_real_sample_at_a_fixed_time_offset"));
            });
            self.xy_dirty |= self.xy_cursor_mode != before;
            ui.label(
                RichText::new(match self.xy_cursor_mode {
                    xy::CursorMode::Free => {
                        i18n::text("xy.free_keeps_x_y_amplitudes_fixed_and_reads_x")
                    }
                    xy::CursorMode::TraceSnap => {
                        i18n::text("xy.trace_snap_follows_a_trigger_relative_sample_auto_free")
                    }
                })
                .small()
                .color(MUTED),
            );
        });
        if self.xy_cursor_mode == xy::CursorMode::TraceSnap {
            control_group(ui, i18n::text("xy.trigger"), TRIGGER, |ui| {
                ui.label(
                    RichText::new(i18n::text("xy.shared_with_scope"))
                        .small()
                        .color(MUTED),
                );
                self.trigger_controls(ui);
            });
        }
        ui.label(
            RichText::new(i18n::text("xy.x_y_use_the_same_input_frame_equal_axis"))
                .small()
                .color(MUTED),
        );
        ui.label(
            RichText::new(
                i18n::format(
                    "xy.up_to_real_sample_pairs_longer_windows_show_the",
                    &[("xy", &(xy::MAX_POINTS).to_string())],
                )
                .as_ref(),
            )
            .small()
            .color(MUTED),
        );
    }
}
