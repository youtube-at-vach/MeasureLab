//! Temporary, read-only Spectrum source. Ordinary results/workers stay owned
//! by the normal measurement path, including while this source is displayed.
use super::*;

pub(super) const EXPORT_REASON: &str = "History Spectrum export is unavailable. Scope-only JSON / CSV / PNG remain available after input stops; Normal Spectrum restores combined export.";

pub(super) struct HistorySpectrum {
    pub linked: bool,
    pub selected: usize,
    pub frequency_cursor: usize,
    keys: [Option<(u64, RowInfo)>; 2],
    pub results: [spectrum::Result; 2],
    pub view: View,
}

impl Default for HistorySpectrum {
    fn default() -> Self {
        Self {
            linked: false,
            selected: 0,
            frequency_cursor: 0,
            keys: [None; 2],
            results: std::array::from_fn(|_| {
                spectrum::Result::empty(
                    Settings {
                        size: 1024,
                        averages: 1,
                        ..Settings::default()
                    },
                    48000,
                )
            }),
            view: View::full(48000, FrequencyScale::Log, -120.0),
        }
    }
}

impl ScopeApp {
    pub(super) fn link_spectrum_history(&mut self) {
        self.hold_spectrogram();
        self.spectrum_history.view = self.spectrum_view();
        self.spectrum_history.linked = true;
        self.spectrum_dirty = true;
        self.spectrum_numeric_key = None;
        self.refresh_spectrum_history();
    }

    pub(super) fn unlink_spectrum_history(&mut self) {
        if self.spectrum_history.linked {
            self.spectrum_history = HistorySpectrum::default();
            self.spectrum_dirty = true;
            self.spectrum_numeric_key = None;
        }
    }

    pub(super) fn refresh_spectrum_history(&mut self) {
        if !self.spectrum_history.linked {
            return;
        }
        for i in 0..2 {
            let frame = self.spectrogram_selected[i].as_ref().filter(|frame| {
                frame.input_generation == self.input_generation
                    && frame.info.generation == self.stft_generation
                    && self.cursors.times[i].and_then(|t| t.spectrogram_sample())
                        == Some(frame.info.end - 1)
            });
            let key = frame.map(|f| (f.input_generation, f.info));
            if self.spectrum_history.keys[i] != key {
                self.spectrum_history.results[i] = frame
                    .and_then(|f| spectrum::Result::from_stft(f.info, f.power()))
                    .unwrap_or_else(|| {
                        spectrum::Result::empty(
                            Settings {
                                size: 1024,
                                averages: 1,
                                ..Settings::default()
                            },
                            self.sample_rate,
                        )
                    });
                self.spectrum_history.keys[i] = key;
                self.spectrum_dirty = true;
                self.spectrum_numeric_key = None;
            }
        }
    }

    pub(super) fn shown_spectrum(&self, index: usize) -> &spectrum::Result {
        if self.spectrum_history.linked {
            &self.spectrum_history.results[index.min(1)]
        } else {
            self.spectrum_result(index)
        }
    }

    pub(super) fn shown_spectrum_index(&self) -> usize {
        if self.spectrum_history.linked {
            self.spectrum_history.selected
        } else {
            self.spectrum_display.selected
        }
    }

    pub(super) fn shown_spectrum_color(&self, index: usize) -> Color32 {
        if self.spectrum_history.linked {
            cursor_color(index)
        } else {
            monitor_controls::scope_color(index)
        }
    }

    pub(super) fn shown_selected_spectrum(&self) -> &spectrum::Result {
        self.shown_spectrum(self.shown_spectrum_index())
    }

    pub(super) fn shown_spectrum_enabled(&self, index: usize) -> bool {
        if self.spectrum_history.linked {
            index < 2
        } else {
            self.spectrum_display.enabled[index]
        }
    }

    pub(super) fn history_spectrum_view(&self) -> View {
        let mut view = self.spectrum_history.view;
        let result = (0..2)
            .map(|i| self.shown_spectrum(i))
            .find(|r| r.window().is_some());
        if let Some(result) = result {
            let minimum_span = (result.bin_hz() * 0.01).max(0.001);
            view.max_hz = view.max_hz.min(result.nyquist()).max(minimum_span * 2.0);
            view.min_hz = view
                .min_hz
                .max(if view.scale == FrequencyScale::Log {
                    0.001
                } else {
                    0.0
                })
                .min(view.max_hz - minimum_span);
        }
        view
    }

    pub(super) fn history_spectrum_reason(&self, index: usize) -> &'static str {
        if self.shown_spectrum(index).validity() == spectrum::Validity::NonFinite {
            "Invalid STFT window · nonfinite input"
        } else if self.spectrogram_unavailable_selection[index] {
            "Before input began · no STFT frame"
        } else if self.cursors.times[index].is_some() {
            "No STFT frame · gap, unavailable or different generation"
        } else {
            "Select a time frame in Spectrogram"
        }
    }

    pub(super) fn history_spectrum_summary(&self, ui: &mut egui::Ui) {
        ui.label(
            RichText::new(
                "Spectrogram history · Bin amplitude · FS / dBFS · AVG OFF · uncalibrated",
            )
            .small()
            .color(MUTED),
        );
        for i in 0..2 {
            let result = self.shown_spectrum(i);
            let text = if let Some(w) = result.window() {
                format!(
                    "Time {} · end {:.6} s · CH {} · samples {}..{} · {} Hz · {} pt · {} · {} · DC {}",
                    cursor_name(i),
                    w.end as f64 / w.sample_rate as f64,
                    w.channel + 1,
                    w.start,
                    w.end,
                    w.sample_rate,
                    w.settings.size,
                    w.settings.window.name(),
                    w.settings.precision.name(),
                    if w.settings.remove_dc {
                        "removed"
                    } else {
                        "retained"
                    }
                )
            } else {
                format!(
                    "Time {} · {}",
                    cursor_name(i),
                    self.history_spectrum_reason(i)
                )
            };
            let text = if result.window().is_some() && !result.is_ready() {
                format!("{text} · {}", self.history_spectrum_reason(i))
            } else {
                text
            };
            ui.label(RichText::new(text).small().color(cursor_color(i)));
        }
        if let [Some(a), Some(b)] = std::array::from_fn(|i| self.shown_spectrum(i).window()) {
            ui.label(
                RichText::new(format!(
                    "Δt B − A {:+.6} s",
                    cursor::signed_distance(b.end, a.end) / a.sample_rate as f64
                ))
                .small()
                .color(YELLOW),
            );
        }
    }

    pub(super) fn history_spectrum_bar(&mut self, ui: &mut egui::Ui) {
        ui.horizontal_wrapped(|ui| {
            for i in 0..2 {
                if ui
                    .selectable_value(
                        &mut self.spectrum_history.selected,
                        i,
                        RichText::new(format!("Time {}", cursor_name(i))).color(cursor_color(i)),
                    )
                    .changed()
                {
                    self.spectrum_numeric_key = None;
                }
            }
            if ui.button("Normal Spectrum").clicked() {
                self.unlink_spectrum_history();
            }
        });
    }

    pub(super) fn history_spectrum_controls(&mut self, ui: &mut egui::Ui) {
        self.history_spectrum_summary(ui);
        ui.label(RichText::new("Captured FFT, Source, units and averaging are read-only. Normal Spectrum continues independently.").small().color(MUTED));
        self.history_spectrum_bar(ui);
        let before = self.spectrum_history.view;
        self.spectrum_history.view = self.history_spectrum_view();
        let nyquist = (0..2)
            .map(|i| self.shown_spectrum(i))
            .find(|r| r.window().is_some())
            .map_or(self.sample_rate as f32 * 0.5, |r| r.nyquist());
        let view = &mut self.spectrum_history.view;
        ui.horizontal_wrapped(|ui| {
            ui.selectable_value(&mut view.scale, FrequencyScale::Log, "Log Hz");
            ui.selectable_value(&mut view.scale, FrequencyScale::Linear, "Linear Hz");
        });
        ui.horizontal_wrapped(|ui| {
            ui.label("From");
            ui.add(
                egui::DragValue::new(&mut view.min_hz)
                    .range(0.0..=view.max_hz)
                    .suffix(" Hz"),
            );
            ui.label("To");
            ui.add(
                egui::DragValue::new(&mut view.max_hz)
                    .range(view.min_hz + 0.001..=nyquist)
                    .suffix(" Hz"),
            );
        });
        ui.horizontal_wrapped(|ui| {
            ui.label("Bottom");
            ui.add(
                egui::DragValue::new(&mut view.floor_db)
                    .range(-180.0..=-6.0)
                    .suffix(" dBFS"),
            );
            ui.label("Top");
            ui.add(
                egui::DragValue::new(&mut view.ceiling_db)
                    .range(view.floor_db + 6.0..=60.0)
                    .suffix(" dBFS"),
            );
        });
        self.spectrum_dirty |= before != self.spectrum_history.view;
        self.spectrum_cursor_controls(ui);
        ui.label(RichText::new(EXPORT_REASON).small().color(MUTED));
    }
}
