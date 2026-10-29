//! Cepstral coordinates and readouts never enter frequency or amplitude APIs.
use super::*;

impl ScopeApp {
    pub(super) fn spectrogram_applied_config(&self) -> stft::Config {
        self.spectrogram_hold
            .as_ref()
            .and_then(|s| s.config)
            .or(self.spectrogram_snapshot.config)
            .or_else(|| {
                self.stft_applied
                    .then(|| self.stft_history.snapshot().config)
                    .flatten()
            })
            .unwrap_or_else(|| self.stft_config())
    }

    pub(super) fn cepstrogram_applied(&self) -> bool {
        self.spectrogram_applied_config().analysis == stft::Analysis::Cepstrogram
    }

    pub(super) fn instrument_title(&self, instrument: Instrument) -> &'static str {
        if instrument == Instrument::Spectrogram {
            self.spectrogram_title()
        } else {
            instrument.display_name()
        }
    }

    pub(super) fn spectrogram_title(&self) -> &'static str {
        if self.cepstrogram_applied() {
            i18n::text("spectrogram.cepstrogram")
        } else {
            i18n::text("spectrogram.spectrogram")
        }
    }

    pub(super) fn quefrency_range(&self) -> spectrogram::QuefrencyRange {
        let c = self.spectrogram_applied_config();
        self.cepstrogram_display
            .quefrency
            .effective(c.sample_rate, c.size)
    }

    pub(super) fn spectrogram_active_colors(
        &self,
    ) -> (spectrogram::ColorRange, bool, spectrogram::ColorMap) {
        if self.cepstrogram_applied() {
            let d = self.cepstrogram_display;
            (
                spectrogram::ColorRange::new(d.floor_db, d.ceiling_db).unwrap(),
                d.auto_color,
                d.color_map,
            )
        } else {
            (
                spectrogram::ColorRange::new(self.spectrogram_floor, self.spectrogram_ceiling)
                    .unwrap(),
                self.spectrogram_auto_color,
                self.spectrogram_color_map,
            )
        }
    }

    pub(super) fn pan_history_horizontal(&mut self, fraction: f64) {
        if self.cepstrogram_applied() {
            let c = self.spectrogram_applied_config();
            self.cepstrogram_display.quefrency =
                self.quefrency_range().pan(fraction, c.sample_rate, c.size);
        } else {
            let r = self.spectrogram_frequency_range().pan(fraction);
            self.spectrogram_min_hz = r.min as f32;
            self.spectrogram_max_hz = r.max as f32;
        }
    }

    pub(super) fn zoom_history_horizontal(&mut self, fraction: f64, factor: f64) {
        if self.cepstrogram_applied() {
            let c = self.spectrogram_applied_config();
            self.cepstrogram_display.quefrency =
                self.quefrency_range()
                    .zoom(fraction, factor, c.sample_rate, c.size);
        } else {
            let r = self.spectrogram_frequency_range().zoom(fraction, factor);
            self.spectrogram_min_hz = r.min as f32;
            self.spectrogram_max_hz = r.max as f32;
        }
    }

    pub(super) fn cepstrogram_display_controls(&mut self, ui: &mut egui::Ui) {
        let before = self.cepstrogram_display;
        setting_label(ui, i18n::text("spectrogram.color_map"));
        egui::ComboBox::from_id_salt("cepstrogram_color_map")
            .width(ui.available_width())
            .selected_text(self.cepstrogram_display.color_map.display_name())
            .show_ui(ui, |ui| {
                for map in spectrogram::ColorMap::ALL {
                    ui.selectable_value(
                        &mut self.cepstrogram_display.color_map,
                        map,
                        map.display_name(),
                    );
                }
            });
        setting_label(ui, i18n::text("spectrogram.cepstral_power"));
        ui.checkbox(
            &mut self.cepstrogram_display.auto_color,
            i18n::text("spectrogram.auto_color_range"),
        );
        let mut manual_changed = false;
        ui.horizontal_wrapped(|ui| {
            ui.label(i18n::text("spectrogram.min"));
            manual_changed |= ui
                .add(egui::DragValue::new(&mut self.cepstrogram_display.floor_db).speed(0.5))
                .changed();
            ui.label(i18n::text("spectrogram.max"));
            manual_changed |= ui
                .add(egui::DragValue::new(&mut self.cepstrogram_display.ceiling_db).speed(0.5))
                .changed();
        });
        if manual_changed {
            self.cepstrogram_display.auto_color = false;
        }
        if self.cepstrogram_display.validate().is_err() {
            self.cepstrogram_display = before;
            ui.colored_label(
                YELLOW,
                i18n::text("spectrogram.min_and_max_must_be_finite_with_min_max"),
            );
        }
        setting_label(ui, i18n::text("spectrogram.quefrency_ms"));
        let before_range = self.cepstrogram_display.quefrency;
        let mut min_ms = before_range.min_seconds * 1000.0;
        let mut max_ms = before_range.max_seconds * 1000.0;
        let mut changed = false;
        ui.horizontal_wrapped(|ui| {
            ui.label(i18n::text("spectrogram.from"));
            changed |= ui
                .add(egui::DragValue::new(&mut min_ms).speed(0.01).suffix(" ms"))
                .changed();
        });
        ui.horizontal_wrapped(|ui| {
            ui.label(i18n::text("spectrogram.to"));
            changed |= ui
                .add(egui::DragValue::new(&mut max_ms).speed(0.01).suffix(" ms"))
                .changed();
        });
        if changed {
            let requested = spectrogram::QuefrencyRange {
                min_seconds: min_ms / 1000.0,
                max_seconds: max_ms / 1000.0,
            };
            if requested.validate().is_ok() {
                self.cepstrogram_display.quefrency = requested;
            } else {
                ui.colored_label(YELLOW, i18n::text("spectrogram.quefrency_invalid"));
            }
        }
        let c = self.spectrogram_applied_config();
        let r = self.quefrency_range();
        ui.label(
            i18n::format(
                "spectrogram.quefrency_effective",
                &[
                    ("min", &format!("{:.6}", r.min_seconds * 1000.0)),
                    ("max", &format!("{:.6}", r.max_seconds * 1000.0)),
                    ("step", &format!("{:.6}", 1000.0 / c.sample_rate as f64)),
                ],
            )
            .as_ref(),
        );
        setting_label(ui, i18n::text("spectrogram.time_range"));
        egui::ComboBox::from_id_salt("spectrogram_time")
            .width(ui.available_width())
            .selected_text(format!("{} s", self.spectrogram_seconds))
            .show_ui(ui, |ui| {
                for seconds in [5.0, 10.0, 30.0, 60.0] {
                    ui.selectable_value(
                        &mut self.spectrogram_seconds,
                        seconds,
                        format!("{seconds} s"),
                    );
                }
            });
        ui.label(i18n::text("spectrogram.cepstral_gestures"));
    }

    pub(super) fn cepstral_status(&self, frame: &spectrogram::history::Frame) -> String {
        let Some(info) = frame.info.cepstrum else {
            return String::new();
        };
        let status = match info.status {
            crate::cepstrum::Status::Valid => i18n::text("spectrogram.cepstral_valid"),
            crate::cepstrum::Status::NoSignal => i18n::text("spectrogram.no_signal"),
            crate::cepstrum::Status::NonFinite => i18n::text("spectrogram.non_finite"),
        };
        i18n::format(
            "spectrogram.cepstral_status",
            &[
                ("status", status),
                ("floor", &frame.info.config.log_floor_db.to_string()),
                ("count", &info.floored_bins.to_string()),
            ],
        )
        .to_string()
    }

    pub(super) fn cepstral_readout(
        &self,
        frame: &spectrogram::history::Frame,
        seconds: f64,
    ) -> String {
        let row = frame.info;
        let q =
            crate::cepstrum::nearest_quefrency(seconds, row.config.size, row.config.sample_rate)
                .unwrap();
        if let (Some(c), Some(db)) = (frame.coefficient(q), frame.cepstral_level_db(q)) {
            i18n::format(
                "spectrogram.cepstral_readout",
                &[
                    ("q", &q.to_string()),
                    (
                        "ms",
                        &format!("{:.6}", q as f64 / row.config.sample_rate as f64 * 1000.0),
                    ),
                    ("c", &format!("{c:.9}")),
                    ("db", &format!("{db:.6}")),
                    ("channel", &(row.config.channel + 1).to_string()),
                    ("start", &row.start.to_string()),
                    ("end", &row.end.to_string()),
                ],
            )
            .to_string()
        } else {
            self.cepstral_status(frame)
        }
    }
}
