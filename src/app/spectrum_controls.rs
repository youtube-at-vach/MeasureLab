//! Spectrum controls and independent four-trace display state.
use super::scope_controls::control_group;
use super::*;

impl ScopeApp {
    pub(super) fn spectrum_summary(&self, ui: &mut egui::Ui) {
        if self.spectrum_history.linked {
            self.history_spectrum_summary(ui);
            return;
        }
        let result = self.selected_spectrum();
        let settings = result.settings();
        let averaging = if settings.averages == 1 {
            "AVG OFF".into()
        } else {
            format!("EMA 1/{}", settings.averages)
        };
        ui.label(
            RichText::new(format!(
                "{} pt · {} · Fs {} Hz · Δf {:.3} Hz · {averaging}",
                settings.size,
                settings.window.name(),
                result.sample_rate(),
                result.bin_hz()
            ))
            .small()
            .color(MUTED),
        );
        let units: Vec<_> = (0..4)
            .filter(|&i| self.spectrum_display.enabled[i])
            .map(|i| self.spectrum_result(i).db_unit())
            .collect();
        if units.windows(2).any(|pair| pair[0] != pair[1]) {
            ui.label(
                RichText::new("Mixed level references · units shown per channel")
                    .small()
                    .color(YELLOW),
            );
        }
    }

    pub(super) fn spectrum_channel_bar(&mut self, ui: &mut egui::Ui) {
        let width = ((ui.available_width() - 9.0) / 4.0).max(60.0);
        let before = self.spectrum_display.enabled;
        ui.horizontal(|ui| {
            ui.spacing_mut().item_spacing.x = 3.0;
            for index in 0..4 {
                let color = monitor_controls::scope_color(index);
                let source = self.spectrum_result(index).window().map_or(self.spectrum_source(index), |w| w.channel);
                let available = source < self.scope_channel_count() as usize;
                let selected = self.spectrum_display.selected == index;
                let (rect, _) = ui.allocate_exact_size(vec2(width, 40.0), egui::Sense::hover());
                ui.painter().rect(rect, 3.0, if selected { color.gamma_multiply(0.12) } else { Color32::from_rgb(22, 34, 43) },
                    Stroke::new(if selected { 1.5 } else { 1.0 }, if selected { color } else { BORDER }), egui::StrokeKind::Inside);
                let selection = egui::Rect::from_min_max(rect.min, rect.max - vec2(24.0, 0.0));
                let response = ui.interact(selection, ui.id().with(("spectrum_select", index)), egui::Sense::click());
                if response.clicked() {
                    self.spectrum_display.selected = index;
                    self.spectrum_numeric_key = None;
                    self.comparison_current = None;
                }
                ui.painter().text(rect.min + vec2(6.0, 4.0), egui::Align2::LEFT_TOP, format!("CH{}", index + 1), egui::FontId::proportional(12.0), color);
                let label = if !available { "No input".into() }
                    else if !self.spectrum_display.enabled[index] { "OFF".into() }
                    else { self.spectrum_result(index).db_unit() };
                ui.painter().text(rect.min + vec2(6.0, 23.0), egui::Align2::LEFT_TOP, label, egui::FontId::monospace(10.0), if available { color } else { MUTED });
                response.on_hover_text(format!("CH{} · input {} · {}\nSelect for peak/cursor and export. Display ON/OFF is independent. Re-enabling starts a fresh average.", index + 1, source + 1, self.spectrum_result(index).db_unit()));
                let toggle = egui::Rect::from_min_size(rect.right_top() + vec2(-23.0, 3.0), vec2(20.0, 20.0));
                ui.put(toggle, |ui: &mut egui::Ui| {
                    ui.add_enabled(available && self.pending_stop.is_none(), egui::Checkbox::without_text(&mut self.spectrum_display.enabled[index]))
                }).on_hover_text(format!("Show CH{} spectrum", index + 1));
            }
        });
        if before != self.spectrum_display.enabled {
            for (index, was_enabled) in before.into_iter().enumerate() {
                if !was_enabled && self.spectrum_display.enabled[index] && self.running() {
                    if index == 0 {
                        self.analyzer =
                            spectrum::Result::empty(self.spectrum_settings, self.sample_rate);
                        self.spectrum_info = measurement::SpectrumInfo::default();
                    } else {
                        self.spectrum_overlays[index - 1] =
                            spectrum::Result::empty(self.spectrum_settings, self.sample_rate);
                        self.spectrum_overlay_info[index - 1] =
                            measurement::SpectrumInfo::default();
                    }
                }
            }
            if self.running() {
                self.configure_spectrum_display();
            }
            self.spectrum_dirty = true;
            self.spectrum_numeric_key = None;
        }
    }
    pub(super) fn spectrum_result(&self, index: usize) -> &spectrum::Result {
        if index == 0 {
            &self.analyzer
        } else {
            &self.spectrum_overlays[index - 1]
        }
    }

    pub(super) fn selected_spectrum(&self) -> &spectrum::Result {
        self.spectrum_result(self.spectrum_display.selected)
    }

    pub(super) fn selected_spectrum_info(&self) -> &measurement::SpectrumInfo {
        if self.spectrum_display.selected == 0 {
            &self.spectrum_info
        } else {
            &self.spectrum_overlay_info[self.spectrum_display.selected - 1]
        }
    }

    pub(super) fn spectrum_source(&self, index: usize) -> usize {
        if index == 0 {
            self.spectrum_channel
        } else {
            self.spectrum_display.overlay_channels[index - 1]
        }
    }

    pub(super) fn configure_spectrum_display(&self) {
        if let Some(core) = &self.core {
            let channels = std::array::from_fn(|i| {
                self.spectrum_display.enabled[i + 1]
                    .then_some(self.spectrum_display.overlay_channels[i])
            });
            core.configure_spectrum_display(self.spectrum_display.enabled[0], channels);
        }
    }

    pub(super) fn clear_spectrum_overlays(&mut self) {
        self.spectrum_overlays = std::array::from_fn(|_| {
            spectrum::Result::empty(self.spectrum_settings, self.sample_rate)
        });
        self.spectrum_overlay_info = std::array::from_fn(|_| measurement::SpectrumInfo::default());
    }

    pub(super) fn receive_spectrum_overlays(&mut self) {
        let Some(core) = &mut self.core else {
            return;
        };
        for (index, worker) in core.spectrum_overlays.iter_mut().enumerate() {
            if let Some(mut p) = worker.take_latest() {
                if self.spectrum_display.enabled[index + 1]
                    && p.generation == self.input_generation
                    && p.channel == self.spectrum_display.overlay_channels[index]
                    && p.result.settings() == self.spectrum_settings
                    && p.info.mode == self.spectrum_mode
                    && (p.epoch, p.revision) > self.spectrum_overlay_publication[index]
                {
                    self.spectrum_overlay_publication[index] = (p.epoch, p.revision);
                    std::mem::swap(&mut self.spectrum_overlays[index], &mut p.result);
                    self.spectrum_overlay_info[index].clone_from(&p.info);
                    self.spectrum_dirty = true;
                    self.spectrum_numeric_key = None;
                }
                worker.recycle(p);
            }
        }
    }

    pub(super) fn spectrum_controls(&mut self, ui: &mut egui::Ui) {
        self.refresh_spectrum_history();
        if self.spectrum_history.linked {
            self.history_spectrum_controls(ui);
            return;
        }
        let before = self.spectrum_settings;
        control_group(ui, "FFT", BLUE, |ui| {
            let mut quantity = self.spectrum_settings.quantity;
            ui.horizontal_wrapped(|ui| {
                ui.selectable_value(
                    &mut quantity,
                    Quantity::Amplitude,
                    "Amplitude",
                ).on_hover_text("Bin amplitude · 0 dBFS = 1 FS peak sine at a bin centre. Window coherent gain corrected; off-bin tones have scalloping loss.");
                ui.selectable_value(&mut quantity, Quantity::Psd, "PSD")
                    .on_hover_text("Power spectral density · power per Hz, with window noise-bandwidth correction");
                ui.selectable_value(&mut quantity, Quantity::Esd, "Transient (ESD)")
                    .on_hover_text("Energy spectral density · energy per Hz. Selecting ESD presets Rectangular, Average OFF and Remove DC OFF for a single transient.");
            });
            self.spectrum_settings.select_quantity(quantity);
            egui::ComboBox::from_id_salt("fft_size")
                .width(ui.available_width())
                .selected_text(format!("{} points", self.spectrum_settings.size))
                .show_ui(ui, |ui| {
                    for size in FFT_SIZES {
                        ui.selectable_value(
                            &mut self.spectrum_settings.size,
                            size,
                            format!("{size} points"),
                        );
                    }
                });
            if self.spectrum_settings.quantity == Quantity::Esd {
                ui.label(RichText::new("Fit the entire transient inside one FFT window. Trigger capture is not linked.").small().color(MUTED));
                if self.spectrum_settings.window != Window::Rectangular {
                    ui.label(RichText::new("Rectangular recommended: other windows attenuate energy without correction.").small().color(YELLOW));
                }
            }
            egui::ComboBox::from_id_salt("fft_window")
                .width(ui.available_width())
                .selected_text(self.spectrum_settings.window.name())
                .show_ui(ui, |ui| {
                    for window in [Window::Hann, Window::Rectangular, Window::BlackmanHarris] {
                        ui.selectable_value(
                            &mut self.spectrum_settings.window,
                            window,
                            window.name(),
                        );
                    }
                });
        });
        control_group(ui, "FREQUENCY / SCALE", BLUE, |ui| {
            self.spectrum_display_controls(ui)
        });
        let index = self.spectrum_display.selected;
        control_group(
            ui,
            &format!("MEASUREMENT · CH{}", index + 1),
            monitor_controls::scope_color(index),
            |ui| {
                let old_source = self.spectrum_source(index);
                let channels = self.lockin_channel_count().max(self.scope_channel_count());
                ui.horizontal(|ui| {
                    ui.label("Input source");
                    let source = if index == 0 {
                        &mut self.spectrum_channel
                    } else {
                        &mut self.spectrum_display.overlay_channels[index - 1]
                    };
                    channel_select(ui, "spectrum_source", source, channels);
                });
                if old_source != self.spectrum_source(index) && self.running() {
                    if index == 0 {
                        self.analyzer =
                            spectrum::Result::empty(self.spectrum_settings, self.sample_rate);
                        self.spectrum_info = measurement::SpectrumInfo::default();
                        if let Some(core) = &self.core {
                            core.configure_spectrum(
                                self.spectrum_settings,
                                self.spectrum_channel,
                                self.spectrum_mode,
                            );
                        }
                        // The shared settings command restarts all traces.
                        self.clear_spectrum_overlays();
                    } else {
                        self.spectrum_overlays[index - 1] =
                            spectrum::Result::empty(self.spectrum_settings, self.sample_rate);
                        self.spectrum_overlay_info[index - 1] =
                            measurement::SpectrumInfo::default();
                    }
                    self.configure_spectrum_display();
                    self.spectrum_numeric_key = None;
                    self.spectrum_dirty = true;
                }
                self.spectrum_dirty |= ui
                    .checkbox(&mut self.spectrum_display.peak_marker, "Peak markers")
                    .changed();
                self.spectrum_cursor_controls(ui);
                if self.selected_spectrum().settings().quantity == Quantity::Psd {
                    ui.collapsing("Power in band", |ui| self.spectrum_band_controls(ui));
                }
            },
        );
        control_group(ui, "AVERAGING", GREEN, |ui| {
            self.spectrum_average_controls(ui)
        });
        if before != self.spectrum_settings && self.running() {
            self.reset_analysis();
        }
        ui.collapsing("Advanced analysis / diagnostics", |ui| {
            self.spectrum_analysis_controls(ui);
            self.spectrum_diagnostics(ui);
            ui.label(
                RichText::new("JSON / CSV / PNG use the selected trace.")
                    .small()
                    .color(MUTED),
            );
        });
        if !self.running() {
            ui.label(
                RichText::new(
                    "FFT edits apply on next Start; captured results retain their conditions.",
                )
                .small()
                .color(MUTED),
            );
        }
    }

    fn spectrum_average_controls(&mut self, ui: &mut egui::Ui) {
        let mut enabled = self.spectrum_settings.averages > 1;
        ui.horizontal(|ui| {
            if ui
                .checkbox(&mut enabled, "Average")
                .on_hover_text(
                    "Exponential average of linear power. OFF uses the latest processed window.",
                )
                .changed()
            {
                self.spectrum_settings.averages = if enabled {
                    self.spectrum_display.average_weight
                } else {
                    1
                };
            }
            ui.add_enabled_ui(enabled, |ui| {
                egui::ComboBox::from_id_salt("fft_average")
                    .width(100.0)
                    .selected_text(format!("Weight {}", self.spectrum_display.average_weight))
                    .show_ui(ui, |ui| {
                        for count in [4, 16, 64] {
                            if ui
                                .selectable_value(
                                    &mut self.spectrum_display.average_weight,
                                    count,
                                    format!("Weight {count}"),
                                )
                                .changed()
                            {
                                self.spectrum_settings.averages = count;
                            }
                        }
                    });
            });
            if ui
                .add_enabled(
                    self.running() && self.pending_stop.is_none(),
                    egui::Button::new("Reset").small(),
                )
                .on_hover_text("Reset averaging and peak hold for all Spectrum traces")
                .clicked()
            {
                self.reset_analysis();
            }
        });
        if enabled {
            let updates = self.selected_spectrum_info().updates;
            // EMA has no finite completion count: label progress as settling.
            let weight = 1.0
                - (1.0 - 1.0 / self.spectrum_settings.averages as f64)
                    .powf(updates.saturating_sub(1) as f64);
            ui.add(egui::ProgressBar::new(if updates == 0 { 0.0 } else { weight as f32 })
                .text("EMA settling"))
                .on_hover_text(format!("Exponential power average · α = 1/{}. Approximately 95% settled after 3 × weight windows.", self.spectrum_settings.averages));
        }
    }

    pub(super) fn spectrum_cursor_controls(&mut self, ui: &mut egui::Ui) {
        ui.horizontal_wrapped(|ui| {
            ui.label(if self.spectrum_history.linked { "Place frequency cursor:" } else { "Place cursor:" });
            for (index, title) in ["A", "B"].into_iter().enumerate() {
                let active = if self.spectrum_history.linked { &mut self.spectrum_history.frequency_cursor } else { &mut self.active_cursor };
                ui.selectable_value(active, index, title)
                    .on_hover_text("Choose which cursor the next spectrum click or drag places; selecting A or B does not place it. Both cursors read the selected channel's nearest FFT bin.");
            }
            if ui.small_button(if self.spectrum_history.linked { "Clear frequency" } else { "Clear cursors" })
                .on_hover_text("Clear both frequency cursors shared by Spectrum and Spectrogram. Time cursors, Spectrogram frame selections, XY Free points and acquired data are kept.")
                .clicked()
            {
                self.cursors.clear_frequencies();
                ui.ctx().request_repaint();
            }
            ui.label(RichText::new(cursor_placement_label(self.cursors.spectrum_frequencies_hz.map(|frequency| frequency.is_some()))).small().color(MUTED));
        });
        ui.label(
            RichText::new("Click / drag the plot to place a cursor")
                .small()
                .color(MUTED),
        );
    }

    fn spectrum_analysis_controls(&mut self, ui: &mut egui::Ui) {
        let before = (
            self.spectrum_settings,
            self.spectrum_channel,
            self.spectrum_mode,
        );
        fft_precision(
            ui,
            "spectrum_precision",
            &mut self.spectrum_settings.precision,
        );
        setting_label(ui, "UPDATE MODE");
        ui.selectable_value(
            &mut self.spectrum_mode,
            SpectrumMode::Live,
            "Live · observe newest window",
        ).on_hover_text("Observe the newest complete window with a processing-time budget. Average and hold update per observed window, independently of drawing. Use Continuous to process every N/4 window.");
        ui.selectable_value(
            &mut self.spectrum_mode,
            SpectrumMode::Continuous,
            "Continuous · process every window",
        );
        ui.selectable_value(
            &mut self.spectrum_mode,
            SpectrumMode::Latest,
            "Latest · observe at a limited rate",
        ).on_hover_text("Newest complete window only; intermediate windows can be skipped. At least 33 ms / N/4 for small FFTs, 100 ms for large FFTs. Does not guarantee transient capture.");
        if self.channels > 0 {
            ui.label(
                RichText::new(format!(
                    "One complete window: {:.3} s · continuous step: {:.3} s (N/4)",
                    self.spectrum_settings.size as f64 / self.sample_rate as f64,
                    self.spectrum_settings.size as f64 / (4.0 * self.sample_rate as f64)
                ))
                .small()
                .color(MUTED),
            );
        } else {
            ui.label(
                RichText::new("Window duration available after input starts")
                    .small()
                    .color(MUTED),
            );
        }
        ui.checkbox(&mut self.spectrum_settings.remove_dc, "Remove DC offset")
            .on_hover_text("Subtracts each window's mean before windowing. In ESD this changes transient energy and its dependence on window length.");
        if before
            != (
                self.spectrum_settings,
                self.spectrum_channel,
                self.spectrum_mode,
            )
            && self.running()
        {
            self.reset_analysis();
        }
        if !self.running() {
            ui.label(
                RichText::new(
                    "Analysis changes apply when input restarts. The captured spectrum stays held.",
                )
                .small()
                .color(MUTED),
            );
        }
    }

    fn spectrum_display_controls(&mut self, ui: &mut egui::Ui) {
        let view_before = (
            self.spectrum_display.auto_level,
            self.frequency_scale,
            self.floor_db,
            self.spectrum_ceiling_db,
            self.show_hold,
            self.span_hz,
            self.spectrum_min_hz,
        );
        ui.horizontal(|ui| {
            ui.selectable_value(&mut self.frequency_scale, FrequencyScale::Log, "Log Hz");
            ui.selectable_value(
                &mut self.frequency_scale,
                FrequencyScale::Linear,
                "Linear Hz",
            );
        });
        egui::ComboBox::from_id_salt("spectrum_span")
            .width(ui.available_width())
            .selected_text(if self.span_hz == 0.0 {
                "Full / Nyquist".into()
            } else {
                format!("Span {}", frequency_label(self.span_hz))
            })
            .show_ui(ui, |ui| {
                ui.selectable_value(&mut self.span_hz, 0.0, "Full / Nyquist");
                for hz in [1000.0, 2000.0, 5000.0, 10000.0, 20000.0] {
                    ui.selectable_value(
                        &mut self.span_hz,
                        hz,
                        format!("Span {}", frequency_label(hz)),
                    );
                }
            });
        ui.collapsing("Custom frequency range", |ui| {
            for (label, value) in [
                ("From", &mut self.spectrum_min_hz),
                ("To", &mut self.span_hz),
            ] {
                ui.horizontal(|ui| {
                    ui.label(label);
                    ui.add(
                        egui::DragValue::new(value)
                            .range(0.0..=self.sample_rate as f32 / 2.0)
                            .speed(0.1)
                            .suffix(" Hz"),
                    );
                });
            }
            ui.label(
                RichText::new("To = 0 uses Nyquist. Narrow ranges show individual bins.")
                    .small()
                    .color(MUTED),
            );
        });
        ui.horizontal(|ui| {
            ui.label("Level axis");
            ui.selectable_value(&mut self.spectrum_display.auto_level, true, "Auto");
            ui.selectable_value(&mut self.spectrum_display.auto_level, false, "Manual");
        });
        if !self.spectrum_display.auto_level {
            ui.horizontal(|ui| {
                ui.label("Bottom");
                ui.add(
                    egui::DragValue::new(&mut self.floor_db)
                        .range(-180.0..=3194.0)
                        .speed(1.0)
                        .suffix(" dB"),
                );
            });
            ui.horizontal(|ui| {
                ui.label("Top");
                ui.add(
                    egui::DragValue::new(&mut self.spectrum_ceiling_db)
                        .range(self.floor_db + 6.0..=3200.0)
                        .speed(1.0)
                        .suffix(" dB"),
                );
            });
        }
        ui.horizontal(|ui| {
            if ui.checkbox(&mut self.show_hold, "Peak hold").changed()
                && self.show_hold
                && self.pending_stop.is_none()
            {
                self.analyzer.clear_hold();
                for result in &mut self.spectrum_overlays {
                    result.clear_hold();
                }
                if let Some(core) = &self.core {
                    core.clear_hold();
                }
            }
            if ui
                .add_enabled(
                    self.pending_stop.is_none(),
                    egui::Button::new("Clear hold").small(),
                )
                .clicked()
            {
                self.analyzer.clear_hold();
                for result in &mut self.spectrum_overlays {
                    result.clear_hold();
                }
                if let Some(core) = &self.core {
                    core.clear_hold();
                }
                self.spectrum_dirty = true;
            }
        });
        self.spectrum_dirty |= view_before
            != (
                self.spectrum_display.auto_level,
                self.frequency_scale,
                self.floor_db,
                self.spectrum_ceiling_db,
                self.show_hold,
                self.span_hz,
                self.spectrum_min_hz,
            );
    }

    fn spectrum_diagnostics(&mut self, ui: &mut egui::Ui) {
        ui.label(
            RichText::new(format!(
                "Δf {:.6} Hz · RBW {:.6} Hz\nWindow {:.1} ms · {} processed windows",
                self.selected_spectrum().bin_hz(),
                self.selected_spectrum().rbw_hz(),
                self.selected_spectrum().settings().size as f32 / self.sample_rate as f32 * 1000.0,
                self.selected_spectrum_info().updates
            ))
            .small()
            .color(MUTED),
        );
        if self.pending_stop.is_some() {
            ui.label(
                RichText::new("Stopping · finishing Spectrum windows")
                    .small()
                    .color(YELLOW),
            );
        } else if self.selected_spectrum().validity() == spectrum::Validity::NonFinite {
            ui.label(
                RichText::new("Invalid FFT window · nonfinite sample or calibrated power")
                    .small()
                    .color(YELLOW),
            );
        } else if self.running() && !self.selected_spectrum().is_ready() {
            ui.label(
                RichText::new(format!(
                    "Filling window · {} / {} samples",
                    self.selected_spectrum_info().filled_samples,
                    self.spectrum_settings.size
                ))
                .small()
                .color(MUTED),
            );
        }
        let cadence = match self.selected_spectrum_info().mode {
            SpectrumMode::Continuous => format!(
                "Continuous · hop {:.1} ms",
                self.selected_spectrum().settings().size as f64 / 4.0 / self.sample_rate as f64
                    * 1000.0
            ),
            SpectrumMode::Live if self.selected_spectrum_info().observation_ms == 0 => {
                "Live · up to 60 updates/s".into()
            }
            SpectrumMode::Live => format!(
                "Live · target {} ms",
                self.selected_spectrum_info().observation_ms
            ),
            SpectrumMode::Latest => {
                format!(
                    "Latest · target {} ms",
                    self.selected_spectrum_info().observation_ms
                )
            }
        };
        ui.label(
            RichText::new(format!(
                "{cadence} · missing input {} · invalid windows {} · missed observations {}",
                self.selected_spectrum_info().input_missing,
                self.selected_spectrum_info().invalid_windows,
                self.selected_spectrum_info().missed_observations
            ))
            .small()
            .color(MUTED),
        );
        if let Some(window) = self.selected_spectrum().window() {
            ui.label(RichText::new(format!("FFT end #{} · acquired end #{}", window.end, self.history.range().end)).small().color(MUTED))
                .on_hover_text("Spectrum and Scope/XY have independent sample intervals. FFT processing time and the age of this window are separate conditions.");
        }
    }

    fn spectrum_band_controls(&mut self, ui: &mut egui::Ui) {
        if self.selected_spectrum().settings().quantity == Quantity::Psd {
            let nyquist = self.selected_spectrum().nyquist() as f64;
            ui.horizontal(|ui| {
                ui.label("From");
                ui.add(
                    egui::DragValue::new(&mut self.band_min_hz)
                        .range(0.0..=nyquist)
                        .speed(10.0)
                        .suffix(" Hz"),
                );
            });
            ui.horizontal(|ui| {
                ui.label("To");
                ui.add(
                    egui::DragValue::new(&mut self.band_max_hz)
                        .range(0.0..=nyquist)
                        .speed(10.0)
                        .suffix(" Hz"),
                );
            });
            ui.label(RichText::new("To = 0 uses Nyquist. Inclusive bin centres; whole bins. Band changes read the held PSD without resetting the average.").small().color(MUTED));
        }
    }
}
