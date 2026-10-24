//! Frequently used monitor controls stay beside the trace they affect.
use super::*;

pub(super) const SCOPE_CHANNEL_CARD_HEIGHT: f32 = 72.0;
const SCOPE_CHANNEL_GAP: f32 = 3.0;

fn scope_channel_columns(width: f32) -> usize {
    if width >= 4.0 * 140.0 + 3.0 * SCOPE_CHANNEL_GAP {
        SCOPE_CHANNELS
    } else {
        2
    }
}

pub(super) fn scope_channel_bar_height(width: f32) -> f32 {
    let rows = SCOPE_CHANNELS / scope_channel_columns(width);
    rows as f32 * SCOPE_CHANNEL_CARD_HEIGHT + (rows - 1) as f32 * SCOPE_CHANNEL_GAP
}

impl ScopeApp {
    pub(super) fn scope_axis_label(&self) -> Arc<str> {
        i18n::format(
            "oscilloscope.amplitude_axis_ch",
            &[("channel", &(self.scope_selected + 1).to_string())],
        )
    }

    pub(super) fn scope_display_vertical(&self, index: usize) -> Vertical {
        self.scope_common_vertical
            .unwrap_or(self.scope_vertical[index])
    }

    pub(super) fn scope_selected_vertical_mut(&mut self) -> &mut Vertical {
        self.scope_common_vertical
            .as_mut()
            .unwrap_or(&mut self.scope_vertical[self.scope_selected])
    }

    pub(super) fn scope_autoset_button(&mut self, ui: &mut egui::Ui) {
        if ui
            .add_enabled(
                self.autoset_pending.is_none() && self.core.is_some(),
                egui::Button::new(i18n::text("oscilloscope.autoset")),
            )
            .on_hover_text(i18n::text(
                "oscilloscope.automatically_set_time_scale_amplitude_and_trigger_for_a",
            ))
            .clicked()
        {
            self.autoset_pending = Some(self.core.as_ref().unwrap().autoset(self.trigger.channel));
        }
    }

    pub(super) fn scope_quick_controls(&mut self, ui: &mut egui::Ui) {
        ui.horizontal_wrapped(|ui| {
            let was_common = self.scope_common_vertical.is_some();
            let mut common = was_common;
            ui.selectable_value(
                &mut common,
                false,
                i18n::text("oscilloscope.per_channel_scale"),
            );
            ui.selectable_value(&mut common, true, i18n::text("oscilloscope.common_scale"));
            if common != was_common {
                self.scope_common_vertical =
                    common.then(|| self.scope_vertical[self.scope_selected]);
                self.dirty = true;
            }
            ui.label(i18n::text("oscilloscope.time_scale"));
            let timebase = ui.add(
                egui::DragValue::new(&mut self.ms_per_div)
                    .range(0.05..=100.0)
                    .speed(0.01)
                    .max_decimals(3)
                    .suffix(" ms/div"),
            );
            self.dirty |= timebase.changed();
            #[cfg(feature = "qa")]
            ui.ctx().data_mut(|data| {
                data.insert_temp(egui::Id::new("qa_scope_timebase"), timebase.rect)
            });
            ui.colored_label(
                scope_color(self.scope_selected),
                format!("CH{}", self.scope_selected + 1),
            );
            self.dirty |= ui
                .add(
                    egui::DragValue::new(&mut self.scope_selected_vertical_mut().fs_per_div)
                        .range(0.001..=0.5)
                        .speed(0.001)
                        .max_decimals(4)
                        .suffix(" FS/div"),
                )
                .changed();
            self.scope_autoset_button(ui);
        });
        if let Some(status) = &self.autoset_status {
            ui.label(RichText::new(status.render().as_ref()).small().color(MUTED));
        }
        if !self.running()
            && !self.scope_range.is_empty()
            && self.core_scope.mode != acquisition::Mode::Auto
        {
            ui.label(
                RichText::new(i18n::text(
                    "oscilloscope.time_trigger_edits_apply_on_next_start",
                ))
                .small()
                .color(YELLOW),
            );
        }
    }

    pub(super) fn scope_display_trigger(&self) -> Trigger {
        if self.core.is_some() && !self.running() {
            self.core_scope.trigger
        } else {
            self.trigger
        }
    }

    pub(super) fn scope_trigger_marker_status(&self) -> &'static str {
        if self.triggered && !self.scope_range.is_empty() {
            i18n::text("oscilloscope.t_markers_captured")
        } else {
            i18n::text("oscilloscope.t_markers_settings_only")
        }
    }

    pub(super) fn scope_trigger_marker_help(&self) -> String {
        let trigger = self.scope_display_trigger();
        i18n::format(
            "oscilloscope.source_level_raw_fs_the_level_follows_the_source",
            &[
                ("display", (display::trigger_help())),
                (
                    "scope_trigger_marker_status",
                    (self.scope_trigger_marker_status()),
                ),
                ("channel", &(channel::name(trigger.channel)).to_string()),
                ("level", &format!("{:+.3}", trigger.level)),
            ],
        )
        .to_string()
    }

    pub(super) fn scope_input_channels(&self) -> Option<u16> {
        if let Some(input) = self
            .held_input
            .as_ref()
            .filter(|input| input.generation == self.input_generation)
        {
            Some(input.channels as u16)
        } else if self.busy {
            None
        } else if self.source == Source::Live {
            self.devices
                .get(self.selected)
                .map(|d| d.channels)
                .filter(|count| *count > 0)
        } else {
            Some(2)
        }
    }

    pub(super) fn scope_channel_count(&self) -> u16 {
        self.scope_input_channels()
            .unwrap_or_else(|| self.lockin_channel_count())
    }

    pub(super) fn scope_channel_bar(&mut self, ui: &mut egui::Ui) {
        let sources = self.scope_view_channels();
        let columns = scope_channel_columns(ui.available_width());
        let width = ((ui.available_width() - SCOPE_CHANNEL_GAP * (columns - 1) as f32)
            / columns as f32)
            .max(1.0);
        ui.vertical(|ui| {
            ui.spacing_mut().item_spacing = vec2(SCOPE_CHANNEL_GAP, SCOPE_CHANNEL_GAP);
            for row in (0..SCOPE_CHANNELS).step_by(columns) {
                ui.horizontal(|ui| {
                    for index in row..row + columns {
                        let color = scope_color(index);
                        let channel = sources.0[index];
                        let out_of_range = self
                            .scope_input_channels()
                            .is_some_and(|count| !channel::available(channel, count as usize));
                        let selected = index == self.scope_selected;
                        let (rect, _) = ui.allocate_exact_size(
                            vec2(width, SCOPE_CHANNEL_CARD_HEIGHT),
                            egui::Sense::hover(),
                        );
                        ui.painter().rect(
                            rect,
                            3.0,
                            if selected {
                                color.gamma_multiply(0.12)
                            } else {
                                Color32::from_rgb(22, 34, 43)
                            },
                            Stroke::new(
                                if selected { 1.5 } else { 1.0 },
                                if selected { color } else { BORDER },
                            ),
                            egui::StrokeKind::Inside,
                        );
                        let selection =
                            egui::Rect::from_min_max(rect.min, rect.max - vec2(24.0, 0.0));
                        let response = ui.interact(
                            selection,
                            ui.id().with(("scope_select", index)),
                            egui::Sense::click(),
                        );
                        if response.clicked() {
                            self.scope_selected = index;
                            self.dirty = true;
                        }
                        ui.painter().text(
                            rect.min + vec2(6.0, 4.0),
                            egui::Align2::LEFT_TOP,
                            i18n::format(
                                "oscilloscope.ch_2",
                                &[("index", &(index + 1).to_string()), ("else", "")],
                            )
                            .to_string(),
                            egui::FontId::proportional(12.0),
                            color,
                        );
                        ui.painter().text(
                            rect.min + vec2(6.0, 23.0),
                            egui::Align2::LEFT_TOP,
                            i18n::format(
                                "oscilloscope.fs_div",
                                &[(
                                    "fs_per_div",
                                    &(display::number(Some(
                                        self.scope_display_vertical(index).fs_per_div as f64,
                                    )))
                                    .to_string(),
                                )],
                            )
                            .to_string(),
                            egui::FontId::monospace(10.0),
                            color,
                        );
                        self.scope_card_reading(ui, index, rect);
                        response.on_hover_text(
                            i18n::format(
                                "oscilloscope.ch_select_to_edit_this_channel_in_scope_settings",
                                &[
                                    ("index", &(index + 1).to_string()),
                                    ("channel", &(channel::name(channel)).to_string()),
                                    (
                                        "else",
                                        (if out_of_range {
                                            i18n::text("oscilloscope.outside_input_channel_range")
                                        } else {
                                            ""
                                        }),
                                    ),
                                    ("index_2", &(self.scope_readout_details(index)).to_string()),
                                    ("display", (display::div_help())),
                                ],
                            )
                            .as_ref(),
                        );
                        let toggle = egui::Rect::from_min_size(
                            rect.right_top() + vec2(-23.0, 3.0),
                            vec2(20.0, 20.0),
                        );
                        let toggle_help = i18n::format(
                            "oscilloscope.show_ch_waveform_keeps_selection_and_measurements",
                            &[("index", &(index + 1).to_string())],
                        );
                        self.dirty |= ui
                            .put(
                                toggle,
                                egui::Checkbox::without_text(&mut self.enabled[index]),
                            )
                            .on_hover_text(toggle_help.as_ref())
                            .changed();
                    }
                });
            }
        });
    }

    fn scope_card_reading(&self, ui: &egui::Ui, index: usize, rect: egui::Rect) {
        let painter = ui.painter().with_clip_rect(rect.shrink(4.0));
        let color = scope_color(index);
        let font = egui::FontId::monospace(10.0);
        if let Reading::Valid(m) = self.scope_readings[index] {
            // Each label, number and unit has its own fixed column. Changing
            // digits never changes another field, card or the plot's geometry.
            let unit_width = (rect.width() * 0.2).clamp(20.0, 72.0);
            let unit_x = rect.right() - 6.0 - unit_width;
            let value_right = unit_x - 4.0;
            let value_left = rect.left() + 30.0;
            let unit = self
                .calibration
                .captured
                .unit(self.scope_view_channels().0[index]);
            for (row, label, value) in [
                (0, i18n::text("oscilloscope.rms"), m.rms),
                (1, i18n::text("oscilloscope.p_p"), m.peak_to_peak),
            ] {
                let y = rect.top() + 39.0 + row as f32 * 15.0;
                painter.text(
                    pos2(rect.left() + 6.0, y),
                    egui::Align2::LEFT_TOP,
                    label,
                    font.clone(),
                    color,
                );
                let mut number = display::number(Some(value));
                let mut galley = painter.layout_no_wrap(number.clone(), font.clone(), color);
                if galley.size().x > value_right - value_left {
                    number = format!("{value:.3e}");
                    galley = painter.layout_no_wrap(number, font.clone(), color);
                }
                let value_rect =
                    egui::Rect::from_min_max(pos2(value_left, y), pos2(value_right, y + 14.0));
                painter.with_clip_rect(value_rect).galley(
                    pos2(value_right - galley.size().x, y),
                    galley,
                    color,
                );
                let mut job =
                    egui::text::LayoutJob::simple_singleline(unit.into(), font.clone(), color);
                job.wrap.max_width = unit_width;
                job.wrap.max_rows = 1;
                let galley = painter.layout_job(job);
                painter.galley(pos2(unit_x, y), galley, color);
            }
        } else {
            let mut job =
                egui::text::LayoutJob::simple_singleline(self.scope_readout(index), font, MUTED);
            job.wrap.max_width = (rect.width() - 12.0).max(1.0);
            job.wrap.max_rows = 2;
            let galley = painter.layout_job(job);
            painter.galley(rect.min + vec2(6.0, 39.0), galley, MUTED);
        }
    }

    pub(super) fn scope_readout(&self, index: usize) -> String {
        let unit = self
            .calibration
            .captured
            .unit(self.scope_view_channels().0[index]);
        match self.scope_readings[index] {
            Reading::Unavailable if self.scope_notice().is_some() => "—".into(),
            Reading::Unavailable
                if self.scope_input_channels().is_some_and(|count| {
                    !channel::available(self.scope_view_channels().0[index], count as usize)
                }) =>
            {
                i18n::text("oscilloscope.out_of_range").into()
            }
            Reading::Unavailable => i18n::text("oscilloscope.no_samples_in_this_interval").into(),
            Reading::NonFinite => i18n::text("oscilloscope.invalid_value").into(),
            Reading::Valid(m) => i18n::format(
                "oscilloscope.rms_p_p",
                &[
                    ("rms", &(display::number(Some(m.rms))).to_string()),
                    ("unit", (unit)),
                    (
                        "peak_to_peak",
                        &(display::number(Some(m.peak_to_peak))).to_string(),
                    ),
                ],
            )
            .to_string(),
        }
    }

    pub(super) fn scope_readout_details(&self, index: usize) -> String {
        let channel = self.scope_view_channels().0[index];
        if self.scope_range.is_empty() && self.held_input.is_none() {
            return i18n::format(
                "oscilloscope.no_acquired_samples_input_conditions_are_not_acquired_waveform",
                &[("channel", &(channel::name(channel)).to_string())],
            )
            .to_string();
        }
        let unit = self.calibration.captured.unit(channel);
        let reading = match self.scope_readings[index] {
            Reading::Valid(m) => i18n::format(
                "oscilloscope.rms_p_p_peak_acquired_samples",
                &[
                    ("rms", &format!("{:.15e}", m.rms)),
                    ("unit", (unit)),
                    ("peak_to_peak", &format!("{:.15e}", m.peak_to_peak)),
                    ("peak", &format!("{:.15e}", m.peak)),
                    ("samples", &(m.samples).to_string()),
                ],
            )
            .to_string(),
            Reading::Unavailable => {
                i18n::text("oscilloscope.no_acquired_samples_for_this_channel_and_interval").into()
            }
            Reading::NonFinite => {
                i18n::text("oscilloscope.an_acquired_or_calibrated_value_is_nonfinite_no_valid")
                    .into()
            }
        };
        i18n::format(
            "oscilloscope.interval_exclusive_end_generation_nominal_hz_waveform_and_trigger",
            &[
                ("channel", &(channel::name(channel)).to_string()),
                ("reading", &(reading).to_string()),
                ("start", &(self.scope_range.start).to_string()),
                ("end", &(self.scope_range.end).to_string()),
                ("input_generation", &(self.input_generation).to_string()),
                ("sample_rate", &(self.sample_rate).to_string()),
                (
                    "channel_2",
                    &(calibration_description(&self.calibration.captured, channel)).to_string(),
                ),
            ],
        )
        .to_string()
    }

    pub(super) fn spectrogram_primary(&mut self, ui: &mut egui::Ui) {
        let before = self.spectrogram_channel;
        let channels = self.lockin_channel_count();
        ui.horizontal_wrapped(|ui| {
            ui.label(i18n::text("spectrum.input_source"));
            channel_select(
                ui,
                "spectrogram_primary_source",
                &mut self.spectrogram_channel,
                channels,
            );
            if ui
                .selectable_label(
                    self.spectrogram_hold.is_none(),
                    i18n::text("spectrogram.live_action"),
                )
                .clicked()
            {
                self.live_spectrogram();
            }
            if ui
                .add_enabled(
                    self.spectrogram_snapshot.latest().is_some(),
                    egui::Button::selectable(
                        self.spectrogram_hold.is_some(),
                        i18n::text("spectrogram.hold_action"),
                    ),
                )
                .clicked()
            {
                self.hold_spectrogram();
            }
            ui.label(
                RichText::new(i18n::text("oscilloscope.spectrogram_time_hz_cursor"))
                    .small()
                    .color(MUTED),
            );
            self.cursor_controls(ui, Instrument::Spectrogram);
        });
        if self.spectrogram_channel != before && self.running() {
            self.reset_stft();
        }
    }
}

pub(super) fn scope_color(index: usize) -> Color32 {
    let [r, g, b, _] = COLORS[index];
    Color32::from_rgb(
        (r * 255.0).round() as u8,
        (g * 255.0).round() as u8,
        (b * 255.0).round() as u8,
    )
}

impl ScopeApp {
    pub(super) fn scope_trigger_overlay(&self, ui: &egui::Ui, rect: egui::Rect) {
        let painter = ui.painter();
        let trigger = self.scope_display_trigger();
        let guides = self.scope_trigger_display == settings::TriggerDisplay::Guides;
        let editing = self.scope_trigger_level_edit_frame == Some(ui.ctx().cumulative_frame_nr());
        let level_y = |trigger: Trigger| {
            let vertical = self
                .scope_view_channels()
                .0
                .iter()
                .position(|ch| *ch == trigger.channel)
                .map(|i| self.scope_display_vertical(i))
                .unwrap_or_else(|| self.scope_common_vertical.unwrap_or_default());
            rect.top() + vertical.y(trigger.level) * rect.height()
        };
        let guide_color = TRIGGER.gamma_multiply(0.65);
        if editing || (guides && trigger.edge != Edge::Free) {
            // Preview the edited setting even while a held capture retains its
            // original trigger. Only this preview follows next-Start edits.
            let ty = level_y(if editing { self.trigger } else { trigger });
            if rect.y_range().contains(ty) {
                painter
                    .with_clip_rect(rect)
                    .extend(egui::Shape::dotted_line(
                        &[pos2(rect.left(), ty), pos2(rect.right(), ty)],
                        guide_color,
                        6.0,
                        1.0,
                    ));
            }
        }
        if trigger.edge != Edge::Free && self.scope_trigger_display != settings::TriggerDisplay::Off
        {
            let tx = rect.left() + rect.width() * (0.2 + self.scope_horizontal_position / 10.0);
            if rect.x_range().contains(tx) {
                if guides {
                    painter
                        .with_clip_rect(rect)
                        .extend(egui::Shape::dotted_line(
                            &[pos2(tx, rect.top()), pos2(tx, rect.bottom())],
                            guide_color,
                            6.0,
                            1.0,
                        ));
                }
                painter.line_segment(
                    [pos2(tx, rect.top()), pos2(tx, rect.top() + 12.0)],
                    Stroke::new(2.0, TRIGGER),
                );
                painter.text(
                    pos2(tx, rect.top() + 17.0),
                    egui::Align2::CENTER_TOP,
                    "T",
                    egui::FontId::monospace(11.0),
                    TRIGGER,
                );
                ui.interact(
                    egui::Rect::from_min_max(
                        pos2(tx - 12.0, rect.top()),
                        pos2(tx + 12.0, rect.top() + 32.0),
                    ),
                    ui.id().with("trigger_time_marker"),
                    egui::Sense::hover(),
                )
                .on_hover_text(self.scope_trigger_marker_help());
            }
            let ty = level_y(trigger);
            if rect.y_range().contains(ty) {
                // Keep the trigger-level indicator outside the waveform area.
                painter.add(egui::Shape::convex_polygon(
                    vec![
                        pos2(rect.right() + 2.0, ty),
                        pos2(rect.right() + 9.0, ty - 4.0),
                        pos2(rect.right() + 9.0, ty + 4.0),
                    ],
                    TRIGGER,
                    Stroke::NONE,
                ));
                painter.text(
                    pos2(rect.right() + 12.0, ty),
                    egui::Align2::LEFT_CENTER,
                    "T",
                    egui::FontId::monospace(10.0),
                    TRIGGER,
                );
                ui.interact(
                    egui::Rect::from_min_max(
                        pos2(rect.right(), ty - 8.0),
                        pos2(rect.right() + 26.0, ty + 8.0),
                    ),
                    ui.id().with("trigger_level_marker"),
                    egui::Sense::hover(),
                )
                .on_hover_text(self.scope_trigger_marker_help());
            }
        }
    }
}
