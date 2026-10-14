//! Frequently used monitor controls stay beside the trace they affect.
use super::*;

impl ScopeApp {
    pub(super) fn scope_sources(&mut self, ui: &mut egui::Ui) {
        let before = self.scope_channels;
        let channels = self.lockin_channel_count();
        ui.horizontal_wrapped(|ui| {
            for (index, color) in [GREEN, BLUE].into_iter().enumerate() {
                self.dirty |= ui
                    .checkbox(
                        &mut self.enabled[index],
                        RichText::new(format!("T{}", index + 1)).color(color),
                    )
                    .changed();
                channel_select(
                    ui,
                    if index == 0 {
                        "scope_primary_1"
                    } else {
                        "scope_primary_2"
                    },
                    &mut self.scope_channels.0[index],
                    channels,
                );
            }
        });
        self.dirty |= self.scope_channels != before;
    }

    pub(super) fn spectrum_primary(&mut self, ui: &mut egui::Ui) {
        let before = self.spectrum_channel;
        let channels = self.lockin_channel_count();
        ui.horizontal_wrapped(|ui| {
            ui.label("Source");
            channel_select(
                ui,
                "spectrum_primary_source",
                &mut self.spectrum_channel,
                channels,
            );
            ui.menu_button("Display range…", |ui| self.spectrum_display_controls(ui));
            ui.label(
                RichText::new("Spectrum · frequency cursor")
                    .small()
                    .color(MUTED),
            );
            self.cursor_controls(ui);
        });
        if self.spectrum_channel != before && self.running() {
            self.reset_analysis();
        }
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
            ui.menu_button("Display…", |ui| self.spectrogram_display_controls(ui));
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
