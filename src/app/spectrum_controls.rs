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
            i18n::text("spectrum.avg_off").into()
        } else {
            i18n::format(
                "spectrum.ema",
                &[("averages", &(settings.averages).to_string())],
            )
            .to_string()
        };
        ui.label(
            RichText::new(
                i18n::format(
                    "spectrum.pt_fs_hz_f_hz",
                    &[
                        ("size", &(settings.size).to_string()),
                        ("name", (settings.window.display_name())),
                        ("sample_rate", &(result.sample_rate()).to_string()),
                        ("bin_hz", &format!("{:.3}", result.bin_hz())),
                        ("averaging", &(averaging).to_string()),
                    ],
                )
                .as_ref(),
            )
            .small()
            .color(MUTED),
        );
        let units: Vec<_> = (0..4)
            .filter(|&i| self.spectrum_display.enabled[i])
            .map(|i| self.spectrum_result(i).db_unit())
            .collect();
        if units.windows(2).any(|pair| pair[0] != pair[1]) {
            ui.label(
                RichText::new(i18n::text(
                    "spectrum.mixed_level_references_units_shown_per_channel",
                ))
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
                let source = self
                    .spectrum_result(index)
                    .window()
                    .map_or(self.spectrum_source(index), |w| w.channel);
                let available = source < self.scope_channel_count() as usize;
                let selected = self.spectrum_display.selected == index;
                let (rect, _) = ui.allocate_exact_size(vec2(width, 40.0), egui::Sense::hover());
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
                let selection = egui::Rect::from_min_max(rect.min, rect.max - vec2(24.0, 0.0));
                let response = ui.interact(
                    selection,
                    ui.scope_id().with(("spectrum_select", index)),
                    egui::Sense::click(),
                );
                #[cfg(feature = "qa")]
                ui.ctx().data_mut(|data| {
                    data.insert_temp(egui::Id::unique(("qa_spectrum_channel", index)), selection);
                });
                if response.clicked() {
                    self.spectrum_display.selected = index;
                    self.spectrum_numeric_key = None;
                    self.comparison_current = None;
                }
                ui.painter().text(
                    rect.min + vec2(6.0, 4.0),
                    egui::Align2::LEFT_TOP,
                    i18n::format("spectrum.ch", &[("index", &(index + 1).to_string())]).to_string(),
                    egui::FontId::proportional(12.0),
                    color,
                );
                let label = if !available {
                    i18n::text("spectrum.no_input").into()
                } else if !self.spectrum_display.enabled[index] {
                    i18n::text("spectrum.off").into()
                } else {
                    self.spectrum_result(index).db_unit()
                };
                ui.painter().text(
                    rect.min + vec2(6.0, 23.0),
                    egui::Align2::LEFT_TOP,
                    label,
                    egui::FontId::monospace(10.0),
                    if available { color } else { MUTED },
                );
                response.on_hover_text(
                    i18n::format(
                        "spectrum.ch_input_select_for_peak_cursor_and_export_display",
                        &[
                            ("index", &(index + 1).to_string()),
                            ("source", &(source + 1).to_string()),
                            (
                                "db_unit",
                                &(self.spectrum_result(index).db_unit()).to_string(),
                            ),
                        ],
                    )
                    .as_ref(),
                );
                let toggle = egui::Rect::from_min_size(
                    rect.right_top() + vec2(-23.0, 3.0),
                    vec2(20.0, 20.0),
                );
                #[cfg(feature = "qa")]
                ui.ctx().data_mut(|data| {
                    data.insert_temp(egui::Id::unique(("qa_spectrum_toggle", index)), toggle);
                });
                ui.put(toggle, |ui: &mut egui::Ui| {
                    ui.add_enabled(
                        available && self.pending_stop.is_none(),
                        egui::Checkbox::without_text(&mut self.spectrum_display.enabled[index]),
                    )
                })
                .on_hover_text(
                    i18n::format(
                        "spectrum.show_ch_spectrum",
                        &[("index", &(index + 1).to_string())],
                    )
                    .as_ref(),
                );
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
        control_group(ui, i18n::text("spectrum.fft"), BLUE, |ui| {
            let mut quantity = self.spectrum_settings.quantity;
            ui.horizontal_wrapped(|ui| {
                ui.selectable_value(
                    &mut quantity,
                    Quantity::Amplitude,
                    i18n::text("spectrum.amplitude"),
                )
                .on_hover_text(i18n::text(
                    "spectrum.bin_amplitude_dbfs_fs_peak_sine_at_a_bin",
                ));
                ui.selectable_value(&mut quantity, Quantity::Psd, i18n::text("spectrum.psd"))
                    .on_hover_text(i18n::text(
                        "spectrum.power_spectral_density_power_per_hz_with_window_noise",
                    ));
                ui.selectable_value(
                    &mut quantity,
                    Quantity::Esd,
                    i18n::text("spectrum.quantity.esd"),
                )
                .on_hover_text(i18n::text(
                    "spectrum.energy_spectral_density_energy_per_hz_selecting_esd_presets",
                ));
            });
            self.spectrum_settings.select_quantity(quantity);
            egui::ComboBox::from_id_salt("fft_size")
                .width(ui.available_width())
                .selected_text(
                    i18n::format(
                        "spectrum.points",
                        &[("size", &(self.spectrum_settings.size).to_string())],
                    )
                    .as_ref(),
                )
                .show_ui(ui, |ui| {
                    for size in FFT_SIZES {
                        ui.selectable_value(
                            &mut self.spectrum_settings.size,
                            size,
                            i18n::format("spectrum.points", &[("size", &(size).to_string())])
                                .as_ref(),
                        );
                    }
                });
            if self.spectrum_settings.quantity == Quantity::Esd {
                ui.label(
                    RichText::new(i18n::text(
                        "spectrum.fit_the_entire_transient_inside_one_fft_window_trigger",
                    ))
                    .small()
                    .color(MUTED),
                );
                if self.spectrum_settings.window != Window::Rectangular {
                    ui.label(RichText::new(i18n::text("spectrum.rectangular_recommended_other_windows_attenuate_energy_without_correction")).small().color(YELLOW));
                }
            }
            egui::ComboBox::from_id_salt("fft_window")
                .width(ui.available_width())
                .selected_text(self.spectrum_settings.window.display_name())
                .show_ui(ui, |ui| {
                    for window in [Window::Hann, Window::Rectangular, Window::BlackmanHarris] {
                        ui.selectable_value(
                            &mut self.spectrum_settings.window,
                            window,
                            window.display_name(),
                        );
                    }
                });
        });
        control_group(ui, i18n::text("spectrum.frequency_scale"), BLUE, |ui| {
            self.spectrum_display_controls(ui)
        });
        let index = self.spectrum_display.selected;
        control_group(
            ui,
            i18n::format(
                "spectrum.measurement_ch",
                &[("index", &(index + 1).to_string())],
            )
            .as_ref(),
            monitor_controls::scope_color(index),
            |ui| {
                let old_source = self.spectrum_source(index);
                let channels = self.lockin_channel_count().max(self.scope_channel_count());
                ui.horizontal(|ui| {
                    ui.label(i18n::text("spectrum.input_source"));
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
                    .checkbox(
                        &mut self.spectrum_display.peak_marker,
                        i18n::text("spectrum.peak_markers"),
                    )
                    .changed();
                self.spectrum_cursor_controls(ui);
                if self.selected_spectrum().settings().quantity == Quantity::Psd {
                    egui::CollapsingHeader::new(i18n::text("spectrum.power_in_band"))
                        .id_salt("Power in band")
                        .show(ui, |ui| self.spectrum_band_controls(ui));
                }
            },
        );
        control_group(ui, i18n::text("spectrum.averaging"), GREEN, |ui| {
            self.spectrum_average_controls(ui)
        });
        if before != self.spectrum_settings && self.running() {
            self.reset_analysis();
        }
        egui::CollapsingHeader::new(i18n::text("spectrum.advanced_analysis_diagnostics"))
            .id_salt("Advanced analysis / diagnostics")
            .show(ui, |ui| {
                self.spectrum_analysis_controls(ui);
                self.spectrum_diagnostics(ui);
                ui.label(
                    RichText::new(i18n::text("spectrum.json_csv_png_use_the_selected_trace"))
                        .small()
                        .color(MUTED),
                );
            });
        if !self.running() {
            ui.label(
                RichText::new(i18n::text(
                    "spectrum.fft_edits_apply_on_next_start_captured_results_retain",
                ))
                .small()
                .color(MUTED),
            );
        }
    }

    fn spectrum_average_controls(&mut self, ui: &mut egui::Ui) {
        let mut enabled = self.spectrum_settings.averages > 1;
        ui.horizontal(|ui| {
            let response = ui
                .checkbox(&mut enabled, i18n::text("spectrum.average"))
                .on_hover_text(i18n::text(
                    "spectrum.exponential_average_of_linear_power_off_uses_the_latest",
                ));
            #[cfg(feature = "qa")]
            ui.ctx().data_mut(|data| {
                data.insert_temp(egui::Id::unique("qa_spectrum_average"), response.rect);
            });
            if response.changed() {
                self.spectrum_settings.averages = if enabled {
                    self.spectrum_display.average_weight
                } else {
                    1
                };
            }
            ui.add_enabled_ui(enabled, |ui| {
                egui::ComboBox::from_id_salt("fft_average")
                    .width(100.0)
                    .selected_text(
                        i18n::format(
                            "spectrum.weight_2",
                            &[(
                                "average_weight",
                                &(self.spectrum_display.average_weight).to_string(),
                            )],
                        )
                        .as_ref(),
                    )
                    .show_ui(ui, |ui| {
                        for count in [4, 16, 64] {
                            if ui
                                .selectable_value(
                                    &mut self.spectrum_display.average_weight,
                                    count,
                                    i18n::format(
                                        "spectrum.weight",
                                        &[("count", &(count).to_string())],
                                    )
                                    .as_ref(),
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
                    egui::Button::new(i18n::text("spectrum.reset")).small(),
                )
                .on_hover_text(i18n::text(
                    "spectrum.reset_averaging_and_peak_hold_for_all_spectrum_traces",
                ))
                .on_disabled_hover_text(i18n::text("spectrum.reset_requires_running_input"))
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
            ui.add(
                egui::ProgressBar::new(if updates == 0 { 0.0 } else { weight as f32 })
                    .text(i18n::text("spectrum.ema_settling")),
            )
            .on_hover_text(
                i18n::format(
                    "spectrum.exponential_power_average_approximately_settled_after_weight_windows",
                    &[("averages", &(self.spectrum_settings.averages).to_string())],
                )
                .as_ref(),
            );
        }
    }

    pub(super) fn spectrum_cursor_controls(&mut self, ui: &mut egui::Ui) {
        ui.horizontal_wrapped(|ui| {
            ui.label(if self.spectrum_history.linked {
                i18n::text("spectrum.place_frequency_cursor")
            } else {
                i18n::text("spectrum.place_cursor")
            });
            for (index, title) in ["A", "B"].into_iter().enumerate() {
                let active = if self.spectrum_history.linked {
                    &mut self.spectrum_history.frequency_cursor
                } else {
                    &mut self.active_cursor
                };
                ui.selectable_value(active, index, title)
                    .on_hover_text(i18n::text(
                        "spectrum.choose_which_cursor_the_next_spectrum_click_or_drag",
                    ));
            }
            if ui
                .small_button(if self.spectrum_history.linked {
                    i18n::text("spectrum.clear_frequency")
                } else {
                    i18n::text("common.clear_cursors")
                })
                .on_hover_text(i18n::text(
                    "spectrum.clear_both_frequency_cursors_shared_by_spectrum_and_spectrogram",
                ))
                .clicked()
            {
                self.cursors.clear_frequencies();
                ui.ctx().request_repaint();
            }
            ui.label(
                RichText::new(cursor_placement_label(
                    self.cursors
                        .spectrum_frequencies_hz
                        .map(|frequency| frequency.is_some()),
                ))
                .small()
                .color(MUTED),
            );
        });
        ui.label(
            RichText::new(i18n::text("spectrum.click_drag_the_plot_to_place_a_cursor"))
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
        setting_label(ui, i18n::text("spectrum.update_mode"));
        ui.selectable_value(
            &mut self.spectrum_mode,
            SpectrumMode::Live,
            i18n::text("spectrum.live_observe_newest_window"),
        )
        .on_hover_text(i18n::text(
            "spectrum.observe_the_newest_complete_window_with_a_processing_time",
        ));
        ui.selectable_value(
            &mut self.spectrum_mode,
            SpectrumMode::Continuous,
            i18n::text("spectrum.continuous_process_every_window"),
        );
        ui.selectable_value(
            &mut self.spectrum_mode,
            SpectrumMode::Latest,
            i18n::text("spectrum.latest_observe_at_a_limited_rate"),
        )
        .on_hover_text(i18n::text(
            "spectrum.newest_complete_window_only_intermediate_windows_can_be_skipped",
        ));
        if self.channels > 0 {
            ui.label(
                RichText::new(
                    i18n::format(
                        "spectrum.one_complete_window_s_continuous_step_s_n",
                        &[
                            (
                                "sample_rate",
                                &format!(
                                    "{:.3}",
                                    self.spectrum_settings.size as f64 / self.sample_rate as f64
                                ),
                            ),
                            (
                                "sample_rate_2",
                                &format!(
                                    "{:.3}",
                                    self.spectrum_settings.size as f64
                                        / (4.0 * self.sample_rate as f64)
                                ),
                            ),
                        ],
                    )
                    .as_ref(),
                )
                .small()
                .color(MUTED),
            );
        } else {
            ui.label(
                RichText::new(i18n::text(
                    "spectrum.window_duration_available_after_input_starts",
                ))
                .small()
                .color(MUTED),
            );
        }
        ui.checkbox(
            &mut self.spectrum_settings.remove_dc,
            i18n::text("spectrum.remove_dc_offset"),
        )
        .on_hover_text(i18n::text(
            "spectrum.subtracts_each_window_s_mean_before_windowing_in_esd",
        ));
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
                RichText::new(i18n::text(
                    "spectrum.analysis_changes_apply_when_input_restarts_the_captured_spectrum",
                ))
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
            ui.selectable_value(
                &mut self.frequency_scale,
                FrequencyScale::Log,
                i18n::text("spectrum.log_hz"),
            );
            ui.selectable_value(
                &mut self.frequency_scale,
                FrequencyScale::Linear,
                i18n::text("spectrum.linear_hz"),
            );
        });
        egui::ComboBox::from_id_salt("spectrum_span")
            .width(ui.available_width())
            .selected_text(if self.span_hz == 0.0 {
                i18n::text("spectrum.full_nyquist").into()
            } else {
                i18n::format(
                    "spectrum.span_2",
                    &[("span_hz", &(frequency_label(self.span_hz)).to_string())],
                )
                .to_string()
            })
            .show_ui(ui, |ui| {
                ui.selectable_value(&mut self.span_hz, 0.0, i18n::text("spectrum.full_nyquist"));
                for hz in [1000.0, 2000.0, 5000.0, 10000.0, 20000.0] {
                    ui.selectable_value(
                        &mut self.span_hz,
                        hz,
                        i18n::format(
                            "spectrum.span",
                            &[("hz", &(frequency_label(hz)).to_string())],
                        )
                        .as_ref(),
                    );
                }
            });
        egui::CollapsingHeader::new(i18n::text("spectrum.custom_frequency_range"))
            .id_salt("Custom frequency range")
            .show(ui, |ui| {
                for (label, value) in [
                    (i18n::text("spectrum.from"), &mut self.spectrum_min_hz),
                    (i18n::text("spectrum.to"), &mut self.span_hz),
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
                    RichText::new(i18n::text(
                        "spectrum.to_uses_nyquist_narrow_ranges_show_individual_bins",
                    ))
                    .small()
                    .color(MUTED),
                );
            });
        ui.horizontal(|ui| {
            ui.label(i18n::text("spectrum.level_axis"));
            ui.selectable_value(
                &mut self.spectrum_display.auto_level,
                true,
                i18n::text("spectrum.auto"),
            );
            ui.selectable_value(
                &mut self.spectrum_display.auto_level,
                false,
                i18n::text("spectrum.manual"),
            );
        });
        if !self.spectrum_display.auto_level {
            ui.horizontal(|ui| {
                ui.label(i18n::text("spectrum.bottom"));
                ui.add(
                    egui::DragValue::new(&mut self.floor_db)
                        .range(-180.0..=3194.0)
                        .speed(1.0)
                        .suffix(" dB"),
                );
            });
            ui.horizontal(|ui| {
                ui.label(i18n::text("spectrum.top"));
                ui.add(
                    egui::DragValue::new(&mut self.spectrum_ceiling_db)
                        .range(self.floor_db + 6.0..=3200.0)
                        .speed(1.0)
                        .suffix(" dB"),
                );
            });
        }
        ui.horizontal(|ui| {
            if ui
                .checkbox(&mut self.show_hold, i18n::text("spectrum.peak_hold"))
                .changed()
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
                    egui::Button::new(i18n::text("spectrum.clear_hold")).small(),
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
            RichText::new(
                i18n::format(
                    "spectrum.f_hz_rbw_hz_window_ms_processed_windows",
                    &[
                        (
                            "bin_hz",
                            &format!("{:.6}", self.selected_spectrum().bin_hz()),
                        ),
                        (
                            "rbw_hz",
                            &format!("{:.6}", self.selected_spectrum().rbw_hz()),
                        ),
                        (
                            "sample_rate",
                            &format!(
                                "{:.1}",
                                self.selected_spectrum().settings().size as f32
                                    / self.sample_rate as f32
                                    * 1000.0
                            ),
                        ),
                        (
                            "updates",
                            &(self.selected_spectrum_info().updates).to_string(),
                        ),
                    ],
                )
                .as_ref(),
            )
            .small()
            .color(MUTED),
        );
        if self.pending_stop.is_some() {
            ui.label(
                RichText::new(i18n::text("spectrum.stopping_finishing_spectrum_windows"))
                    .small()
                    .color(YELLOW),
            );
        } else if self.selected_spectrum().validity() == spectrum::Validity::NonFinite {
            ui.label(
                RichText::new(i18n::text(
                    "spectrum.invalid_fft_window_nonfinite_sample_or_calibrated_power",
                ))
                .small()
                .color(YELLOW),
            );
        } else if self.running() && !self.selected_spectrum().is_ready() {
            ui.label(
                RichText::new(
                    i18n::format(
                        "spectrum.filling_window_samples",
                        &[
                            (
                                "filled_samples",
                                &(self.selected_spectrum_info().filled_samples).to_string(),
                            ),
                            ("size", &(self.spectrum_settings.size).to_string()),
                        ],
                    )
                    .as_ref(),
                )
                .small()
                .color(MUTED),
            );
        }
        let cadence = match self.selected_spectrum_info().mode {
            SpectrumMode::Continuous => i18n::format(
                "spectrum.continuous_hop_ms",
                &[(
                    "sample_rate",
                    &format!(
                        "{:.1}",
                        self.selected_spectrum().settings().size as f64
                            / 4.0
                            / self.sample_rate as f64
                            * 1000.0
                    ),
                )],
            )
            .to_string(),
            SpectrumMode::Live if self.selected_spectrum_info().observation_ms == 0 => {
                i18n::text("spectrum.live_up_to_updates_s").into()
            }
            SpectrumMode::Live => i18n::format(
                "spectrum.live_target_ms",
                &[(
                    "observation_ms",
                    &(self.selected_spectrum_info().observation_ms).to_string(),
                )],
            )
            .to_string(),
            SpectrumMode::Latest => i18n::format(
                "spectrum.latest_target_ms",
                &[(
                    "observation_ms",
                    &(self.selected_spectrum_info().observation_ms).to_string(),
                )],
            )
            .to_string(),
        };
        ui.label(
            RichText::new(
                i18n::format(
                    "spectrum.missing_input_invalid_windows_missed_observations",
                    &[
                        ("cadence", &(cadence).to_string()),
                        (
                            "input_missing",
                            &(self.selected_spectrum_info().input_missing).to_string(),
                        ),
                        (
                            "invalid_windows",
                            &(self.selected_spectrum_info().invalid_windows).to_string(),
                        ),
                        (
                            "missed_observations",
                            &(self.selected_spectrum_info().missed_observations).to_string(),
                        ),
                    ],
                )
                .as_ref(),
            )
            .small()
            .color(MUTED),
        );
        if let Some(window) = self.selected_spectrum().window() {
            ui.label(
                RichText::new(
                    i18n::format(
                        "spectrum.fft_end_acquired_end",
                        &[
                            ("end", &(window.end).to_string()),
                            ("end_2", &(self.history.range().end).to_string()),
                        ],
                    )
                    .as_ref(),
                )
                .small()
                .color(MUTED),
            )
            .on_hover_text(i18n::text(
                "spectrum.spectrum_and_scope_xy_have_independent_sample_intervals_fft",
            ));
        }
    }

    fn spectrum_band_controls(&mut self, ui: &mut egui::Ui) {
        if self.selected_spectrum().settings().quantity == Quantity::Psd {
            let nyquist = self.selected_spectrum().nyquist() as f64;
            ui.horizontal(|ui| {
                ui.label(i18n::text("spectrum.from"));
                ui.add(
                    egui::DragValue::new(&mut self.band_min_hz)
                        .range(0.0..=nyquist)
                        .speed(10.0)
                        .suffix(" Hz"),
                );
            });
            ui.horizontal(|ui| {
                ui.label(i18n::text("spectrum.to"));
                ui.add(
                    egui::DragValue::new(&mut self.band_max_hz)
                        .range(0.0..=nyquist)
                        .speed(10.0)
                        .suffix(" Hz"),
                );
            });
            ui.label(
                RichText::new(i18n::text(
                    "spectrum.to_uses_nyquist_inclusive_bin_centres_whole_bins_band",
                ))
                .small()
                .color(MUTED),
            );
        }
    }
}
