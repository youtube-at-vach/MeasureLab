//! Scope details follow the operating groups of a bench oscilloscope.
use super::*;

impl ScopeApp {
    pub(super) fn scope_controls(&mut self, ui: &mut egui::Ui) {
        control_group(ui, i18n::text("oscilloscope.acquisition"), MUTED, |ui| {
            let old_mode = self.acquisition_mode;
            ui.horizontal(|ui| {
                for (mode, label, help) in [
                    (
                        acquisition::Mode::Auto,
                        i18n::text("oscilloscope.auto"),
                        i18n::text("oscilloscope.update_even_without_a_trigger_crossing"),
                    ),
                    (
                        acquisition::Mode::Normal,
                        i18n::text("oscilloscope.normal"),
                        i18n::text(
                            "oscilloscope.update_on_trigger_crossings_hold_the_last_capture_while",
                        ),
                    ),
                    (
                        acquisition::Mode::Single,
                        i18n::text("oscilloscope.single"),
                        i18n::text("oscilloscope.capture_once_on_the_next_trigger_crossing"),
                    ),
                ] {
                    ui.selectable_value(&mut self.acquisition_mode, mode, label)
                        .on_hover_text(help);
                }
            });
            self.dirty |= old_mode != self.acquisition_mode;
            ui.horizontal(|ui| {
                if ui
                    .add_enabled(
                        !self.running() && self.input_transport_enabled(),
                        egui::Button::new(i18n::text("oscilloscope.start_single_capture")),
                    )
                    .on_hover_text(i18n::text(
                        "oscilloscope.start_input_and_wait_for_a_single_triggered_capture",
                    ))
                    .clicked()
                {
                    self.acquisition_mode = acquisition::Mode::Single;
                    self.start();
                }
                self.scope_autoset_button(ui);
            });
            if let Some(status) = &self.autoset_status {
                ui.label(RichText::new(status.render().as_ref()).small().color(MUTED));
            }
        });

        control_group(ui, i18n::text("oscilloscope.trigger"), TRIGGER, |ui| {
            self.trigger_controls(ui);
            ui.horizontal(|ui| {
                ui.label(i18n::text("oscilloscope.display"));
                egui::ComboBox::from_id_salt("scope_trigger_display")
                    .selected_text(match self.scope_trigger_display {
                        settings::TriggerDisplay::Markers => i18n::text("oscilloscope.markers"),
                        settings::TriggerDisplay::Guides => i18n::text("oscilloscope.guides"),
                        settings::TriggerDisplay::Off => i18n::text("oscilloscope.off"),
                    })
                    .show_ui(ui, |ui| {
                        for (mode, label) in [
                            (
                                settings::TriggerDisplay::Markers,
                                i18n::text("oscilloscope.markers"),
                            ),
                            (
                                settings::TriggerDisplay::Guides,
                                i18n::text("oscilloscope.guides"),
                            ),
                            (
                                settings::TriggerDisplay::Off,
                                i18n::text("oscilloscope.off"),
                            ),
                        ] {
                            ui.selectable_value(&mut self.scope_trigger_display, mode, label);
                        }
                    })
                    .response
                    .on_hover_text(i18n::text(
                        "oscilloscope.markers_t_markers_only_guides_t_markers_and_dotted",
                    ));
            });
        });

        control_group(ui, i18n::text("oscilloscope.horizontal"), BLUE, |ui| {
            self.dirty |= control_slider(
                ui,
                i18n::text("oscilloscope.time_scale"),
                egui::Slider::new(&mut self.ms_per_div, 0.05..=100.0)
                    .logarithmic(true)
                    .suffix(" ms/div")
                    .max_decimals(3)
                    .drag_value_speed(0.05),
                None,
            )
            .0;
            let (changed, centre) = control_slider(
                ui,
                i18n::text("oscilloscope.position"),
                egui::Slider::new(&mut self.scope_horizontal_position, -5.0..=5.0)
                    .suffix(" div")
                    .max_decimals(2)
                    .drag_value_speed(0.1)
                    .trailing_fill(false),
                Some(i18n::text("oscilloscope.reset_time_position")),
            );
            if centre {
                self.scope_horizontal_position = 0.0;
            }
            self.dirty |= changed || centre;
        });

        let index = self.scope_selected;
        let color = monitor_controls::scope_color(index);
        control_group(
            ui,
            i18n::format(
                "oscilloscope.vertical_ch",
                &[("index", &(index + 1).to_string())],
            )
            .as_ref(),
            color,
            |ui| {
                if self.scope_common_vertical.is_some() {
                    ui.label(i18n::text("oscilloscope.common_scale"));
                }
                ui.horizontal(|ui| {
                    ui.label(i18n::text("oscilloscope.input_source"));
                    let before = self.scope_channels;
                    let channels = self.lockin_channel_count().max(self.scope_channel_count());
                    channel_select(
                        ui,
                        "scope_channel_source",
                        &mut self.scope_channels.0[index],
                        channels,
                    );
                    self.dirty |= self.scope_channels != before;
                });
                let channel = self.scope_view_channels().0[index];
                if self
                    .scope_input_channels()
                    .is_some_and(|count| !channel::available(channel, count as usize))
                {
                    ui.label(
                        RichText::new(
                            i18n::format(
                                "oscilloscope.outside_input_channel_range_2",
                                &[("channel", &(channel::name(channel)).to_string())],
                            )
                            .as_ref(),
                        )
                        .small()
                        .color(MUTED),
                    );
                }
                self.dirty |= control_slider(
                    ui,
                    i18n::text("oscilloscope.vertical_range"),
                    egui::Slider::new(
                        &mut self.scope_selected_vertical_mut().fs_per_div,
                        0.001..=0.5,
                    )
                    .logarithmic(true)
                    .suffix(" FS/div")
                    .max_decimals(3)
                    .drag_value_speed(0.001),
                    None,
                )
                .0;
                let (changed, zero) = control_slider(
                    ui,
                    i18n::text("oscilloscope.centre_offset"),
                    egui::Slider::new(&mut self.scope_selected_vertical_mut().offset, -2.0..=2.0)
                        .suffix(" FS")
                        .max_decimals(3)
                        .drag_value_speed(0.001)
                        .trailing_fill(false),
                    Some(i18n::text("oscilloscope.zero_offset")),
                );
                if zero {
                    self.scope_selected_vertical_mut().offset = 0.0;
                }
                self.dirty |= changed || zero;
                if ui
                    .button(i18n::text("oscilloscope.fit_amplitude"))
                    .on_hover_text(if self.scope_common_vertical.is_some() {
                        i18n::text("oscilloscope.fit_visible_channels")
                    } else {
                        i18n::text("oscilloscope.fit_the_selected_channel_s_raw_peak_and_centre")
                    })
                    .clicked()
                {
                    self.fit_scope_amplitude();
                }
            },
        );

        if !self.running() && self.core_scope.mode != acquisition::Mode::Auto {
            ui.label(
                RichText::new(i18n::text(
                    "oscilloscope.time_trigger_edits_apply_on_next_start",
                ))
                .small()
                .color(YELLOW),
            );
        }
        ui.label(
            RichText::new(i18n::text(
                "oscilloscope.wheel_time_scale_shift_wheel_selected_channel_scale",
            ))
            .small()
            .color(MUTED),
        );
        ui.add(
            egui::Label::new(i18n::text(
                "oscilloscope.fs_full_scale_fs_sample_rate_div_grid_division",
            ))
            .wrap(),
        )
        .on_hover_text(format!(
            "{}\n{}\n{}",
            display::amplitude_help(),
            display::sample_rate_help(),
            display::div_help()
        ));
    }

    pub(super) fn trigger_controls(&mut self, ui: &mut egui::Ui) {
        let before = (self.trigger.edge, self.trigger.channel);
        ui.horizontal(|ui| {
            ui.label(i18n::text("oscilloscope.edge"));
            egui::ComboBox::from_id_salt("edge")
                .width(ui.available_width())
                .selected_text(match self.trigger.edge {
                    Edge::Free => i18n::text("oscilloscope.free_run"),
                    Edge::Rising => i18n::text("oscilloscope.rising_edge"),
                    Edge::Falling => i18n::text("oscilloscope.falling_edge"),
                })
                .show_ui(ui, |ui| {
                    ui.selectable_value(
                        &mut self.trigger.edge,
                        Edge::Free,
                        i18n::text("oscilloscope.free_run"),
                    );
                    ui.selectable_value(
                        &mut self.trigger.edge,
                        Edge::Rising,
                        i18n::text("oscilloscope.rising_edge"),
                    );
                    ui.selectable_value(
                        &mut self.trigger.edge,
                        Edge::Falling,
                        i18n::text("oscilloscope.falling_edge"),
                    );
                });
        });
        ui.horizontal(|ui| {
            ui.label(i18n::text("oscilloscope.source"));
            let channels = self.lockin_channel_count().max(self.scope_channel_count());
            channel_select(ui, "trigger_channel", &mut self.trigger.channel, channels);
        });
        self.dirty |= before != (self.trigger.edge, self.trigger.channel);
        let (response, zero) = control_slider_response(
            ui,
            i18n::text("oscilloscope.level"),
            egui::Slider::new(&mut self.trigger.level, -1.0..=1.0)
                .suffix(" FS")
                .max_decimals(3)
                .drag_value_speed(0.001)
                .trailing_fill(false),
            Some(i18n::text("oscilloscope.zero_level")),
        );
        if zero {
            self.trigger.level = 0.0;
        }
        #[cfg(feature = "qa")]
        if self.smoke {
            ui.ctx().data_mut(|data| {
                data.insert_temp(egui::Id::unique("qa_trigger_level"), response.rect);
            });
        }
        self.dirty |= response.changed() || zero;
        if response.is_pointer_button_down_on()
            || (response.has_focus() && ui.ctx().text_edit_focused())
            || response.changed()
            || zero
        {
            self.scope_trigger_level_edit_frame = Some(ui.ctx().cumulative_frame_nr());
            // A stopped input need not otherwise repaint after the edit ends.
            ui.ctx().request_repaint();
        }
        ui.add(egui::Label::new(i18n::text("oscilloscope.t_markers_top_ms_right_level")).wrap())
            .on_hover_text(self.scope_trigger_marker_help());
    }
}

pub(super) fn control_group(
    ui: &mut egui::Ui,
    title: &str,
    accent: Color32,
    contents: impl FnOnce(&mut egui::Ui),
) {
    egui::Frame::new()
        .fill(Color32::from_rgb(20, 29, 37))
        .stroke(Stroke::new(1.0, BORDER))
        .corner_radius(5)
        .inner_margin(10)
        .show(ui, |ui| {
            ui.set_width(ui.available_width());
            ui.spacing_mut().item_spacing = vec2(6.0, 5.0);
            ui.label(RichText::new(title).small().strong().color(accent));
            ui.add_space(2.0);
            contents(ui);
        });
    ui.add_space(4.0);
}

/// Keep units with the editable value and give every rail the same width.
/// The value retains egui's drag and keyboard entry, alongside the slider.
pub(super) fn control_slider(
    ui: &mut egui::Ui,
    label: &str,
    slider: egui::Slider<'_>,
    reset: Option<&str>,
) -> (bool, bool) {
    let (response, reset_clicked) = control_slider_response(ui, label, slider, reset);
    (response.changed(), reset_clicked)
}

fn control_slider_response(
    ui: &mut egui::Ui,
    label: &str,
    slider: egui::Slider<'_>,
    reset: Option<&str>,
) -> (egui::Response, bool) {
    let mut reset_clicked = false;
    let label = ui
        .horizontal(|ui| {
            let response = ui.label(label);
            if let Some(reset) = reset {
                ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                    reset_clicked = ui.small_button(reset).clicked();
                });
            }
            response
        })
        .inner;
    ui.spacing_mut().slider_width = (ui.available_width() - 100.0).max(80.0);
    // Always-clamping sliders round the stored value on every paint. Preserve
    // values from wheel edits, Autoset and restored settings until a user edits.
    let response = ui
        .add(slider.clamping(egui::SliderClamping::Edits))
        .labelled_by(label.id)
        .on_hover_text(i18n::text(
            "oscilloscope.drag_the_slider_or_value_to_adjust_double_click",
        ));
    (response, reset_clicked)
}
