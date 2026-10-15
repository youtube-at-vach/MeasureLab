//! Frequently used monitor controls stay beside the trace they affect.
use super::*;

impl ScopeApp {
    pub(super) fn scope_channel_count(&self) -> u16 {
        if self.core.is_some() || !self.history.is_empty() {
            self.channels
        } else {
            self.lockin_channel_count()
        }
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
                let available = channel::available(channel, self.scope_channel_count() as usize);
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
                    format!("CH{}{}", index + 1, if !available && width <= 125.0 { " —" } else { "" }), egui::FontId::proportional(12.0), color);
                ui.painter().text(rect.min + vec2(6.0, 23.0), egui::Align2::LEFT_TOP,
                    format!("{} FS/div", display::number(Some(self.scope_vertical[index].fs_per_div as f64))),
                    egui::FontId::monospace(10.0), color);
                if !available && width > 125.0 {
                    ui.painter().text(rect.min + vec2(44.0, 5.0), egui::Align2::LEFT_TOP,
                        "No input", egui::FontId::proportional(10.0), MUTED);
                }
                response.on_hover_text(format!("CH{} · {}{}\n{}\nSelect to edit this channel in Channel settings. Display on/off is independent.", index + 1,
                    channel::name(channel), if available { "" } else { " · No input (unavailable)" }, self.scope_readout_details(index)));
                let toggle = egui::Rect::from_min_size(rect.right_top() + vec2(-23.0, 3.0), vec2(20.0, 20.0));
                self.dirty |= ui.put(toggle, egui::Checkbox::without_text(&mut self.enabled[index]))
                    .on_hover_text(format!("Show CH{} waveform (keeps selection and measurements)", index + 1)).changed();
                if !available {
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
            Reading::Unavailable => "— · unavailable".into(),
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
            self.cursor_controls(ui);
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
