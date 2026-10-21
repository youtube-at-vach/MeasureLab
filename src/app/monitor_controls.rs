//! Frequently used monitor controls stay beside the trace they affect.
use super::*;

impl ScopeApp {
    pub(super) fn scope_display_trigger(&self) -> Trigger {
        if self.core.is_some() && !self.running() {
            self.core_scope.trigger
        } else {
            self.trigger
        }
    }

    pub(super) fn scope_trigger_marker_status(&self) -> &'static str {
        if self.triggered && !self.scope_range.is_empty() {
            "T markers: captured"
        } else {
            "T markers: settings only"
        }
    }

    pub(super) fn scope_trigger_marker_help(&self) -> String {
        let trigger = self.scope_display_trigger();
        format!(
            "{}\n{} · source {} · level {:+.3} raw FS. The level follows the source channel's vertical range, which may differ from the selected channel's axis.",
            display::TRIGGER_HELP,
            self.scope_trigger_marker_status(),
            channel::name(trigger.channel),
            trigger.level,
        )
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
        let width = ((ui.available_width() - 3.0 * (SCOPE_CHANNELS - 1) as f32)
            / SCOPE_CHANNELS as f32)
            .max(1.0);
        ui.horizontal(|ui| {
            ui.spacing_mut().item_spacing.x = 3.0;
            for index in 0..SCOPE_CHANNELS {
                let color = scope_color(index);
                let channel = sources.0[index];
                let out_of_range = self.scope_input_channels().is_some_and(|count| !channel::available(channel, count as usize));
                let show_range = out_of_range && self.scope_notice().is_none();
                let selected = index == self.scope_selected;
                let (rect, _) = ui.allocate_exact_size(vec2(width, 40.0), egui::Sense::hover());
                ui.painter().rect(rect, 3.0,
                    if selected { color.gamma_multiply(0.12) } else { Color32::from_rgb(22, 34, 43) },
                    Stroke::new(if selected { 1.5 } else { 1.0 }, if selected { color } else { BORDER }),
                    egui::StrokeKind::Inside);
                let selection = egui::Rect::from_min_max(rect.min, rect.max - vec2(24.0, 0.0));
                let response = ui.interact(selection, ui.id().with(("scope_select", index)), egui::Sense::click());
                if response.clicked() {
                    self.scope_selected = index;
                    self.dirty = true;
                }
                ui.painter().text(rect.min + vec2(6.0, 4.0), egui::Align2::LEFT_TOP,
                    format!("CH{}{}", index + 1, if show_range && width <= 150.0 { " —" } else { "" }), egui::FontId::proportional(12.0), color);
                ui.painter().text(rect.min + vec2(6.0, 23.0), egui::Align2::LEFT_TOP,
                    format!("{} FS/div", display::number(Some(self.scope_vertical[index].fs_per_div as f64))),
                    egui::FontId::monospace(10.0), color);
                if show_range && width > 150.0 {
                    ui.painter().text(rect.min + vec2(44.0, 5.0), egui::Align2::LEFT_TOP,
                        "Out of range", egui::FontId::proportional(10.0), MUTED);
                }
                response.on_hover_text(format!("CH{} · {}{}\n{}\nSelect to edit this channel in Scope settings. Display on/off is independent.\n{}", index + 1,
                    channel::name(channel), if out_of_range { " · outside input channel range" } else { "" }, self.scope_readout_details(index), display::DIV_HELP));
                let toggle = egui::Rect::from_min_size(rect.right_top() + vec2(-23.0, 3.0), vec2(20.0, 20.0));
                self.dirty |= ui.put(toggle, egui::Checkbox::without_text(&mut self.enabled[index]))
                    .on_hover_text(format!("Show CH{} waveform (keeps selection and measurements)", index + 1)).changed();
                if show_range {
                    ui.painter().line_segment([rect.right_bottom() - vec2(18.0, 7.0), rect.right_bottom() - vec2(6.0, 7.0)], Stroke::new(1.5, MUTED));
                }
            }
        });
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
                "— · channel out of range".into()
            }
            Reading::Unavailable => "— · no samples in this interval".into(),
            Reading::NonFinite => "— · invalid value".into(),
            Reading::Valid(m) => format!(
                "RMS {} {unit} · P-P {} {unit}",
                display::number(Some(m.rms)),
                display::number(Some(m.peak_to_peak))
            ),
        }
    }

    pub(super) fn scope_readout_details(&self, index: usize) -> String {
        let channel = self.scope_view_channels().0[index];
        if self.scope_range.is_empty() && self.held_input.is_none() {
            return format!(
                "{} · No acquired samples\nInput conditions are not acquired. Waveform and trigger settings use raw FS.",
                channel::name(channel)
            );
        }
        let unit = self.calibration.captured.unit(channel);
        let reading = match self.scope_readings[index] {
            Reading::Valid(m) => format!(
                "RMS {:.15e} {unit} · P-P {:.15e} {unit} · Peak {:.15e} {unit} · {} acquired samples",
                m.rms, m.peak_to_peak, m.peak, m.samples
            ),
            Reading::Unavailable => "No acquired samples for this channel and interval".into(),
            Reading::NonFinite => {
                "An acquired or calibrated value is nonfinite; no valid numeric readout".into()
            }
        };
        format!(
            "{} · {reading}\nInterval {}..{} (exclusive end) · generation {} · nominal {} Hz. {}. Waveform and trigger are raw FS.",
            channel::name(channel),
            self.scope_range.start,
            self.scope_range.end,
            self.input_generation,
            self.sample_rate,
            calibration_description(&self.calibration.captured, channel)
        )
    }

    pub(super) fn spectrogram_primary(&mut self, ui: &mut egui::Ui) {
        let before = self.spectrogram_channel;
        let channels = self.lockin_channel_count();
        ui.horizontal_wrapped(|ui| {
            ui.label("Source");
            channel_select(
                ui,
                "spectrogram_primary_source",
                &mut self.spectrogram_channel,
                channels,
            );
            if ui
                .selectable_label(self.spectrogram_hold.is_none(), "Live")
                .clicked()
            {
                self.live_spectrogram();
            }
            if ui
                .add_enabled(
                    self.spectrogram_snapshot.latest().is_some(),
                    egui::Button::selectable(self.spectrogram_hold.is_some(), "Hold"),
                )
                .clicked()
            {
                self.hold_spectrogram();
            }
            ui.label(
                RichText::new("Spectrogram · time / Hz cursor")
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
                .map(|i| self.scope_vertical[i])
                .unwrap_or_default();
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
