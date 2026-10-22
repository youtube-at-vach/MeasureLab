//! Shared input/output connection settings. Signal edits remain in the
//! Generator panel; this page handles input sources and output devices/formats.
use super::generator_panel::GeneratorUi;
use super::*;
use crate::generator;

fn output_config(g: &GeneratorUi) -> output::device::Config {
    output::device::Config {
        rate: g.rate,
        channels: g.target.channels() as u16,
        pcm: match g.target {
            output::Target::Audio { pcm, .. } => pcm,
            output::Target::Internal => output::device::Pcm::F64,
        },
    }
}

fn output_configs(g: &GeneratorUi) -> Vec<output::device::Config> {
    match &g.target {
        output::Target::Internal => output::RATES
            .into_iter()
            .map(|rate| output::device::Config {
                rate,
                ..output_config(g)
            })
            .collect(),
        output::Target::Audio { device_id, .. } => g
            .devices
            .iter()
            .find(|d| &d.id == device_id)
            .map(|d| d.configs.clone())
            .unwrap_or_default(),
    }
}

fn common_rates(
    input: &[u32],
    configs: &[output::device::Config],
    current: output::device::Config,
) -> Vec<u32> {
    let mut rates: Vec<_> = configs
        .iter()
        .filter(|c| {
            c.channels == current.channels && c.pcm == current.pcm && input.contains(&c.rate)
        })
        .map(|c| c.rate)
        .collect();
    rates.sort_unstable();
    rates.dedup();
    rates
}

fn config_label(config: output::device::Config, include_rate: bool) -> String {
    let format = i18n::format(
        "io.ch",
        &[
            ("channels", &(config.channels).to_string()),
            ("label", (config.pcm.label())),
        ],
    )
    .to_string();
    if include_rate {
        i18n::format(
            "io.hz_4",
            &[
                ("rate", &(config.rate).to_string()),
                ("format", &(format).to_string()),
            ],
        )
        .to_string()
    } else {
        format
    }
}

fn settings_for_output_channels(
    mut settings: generator::Settings,
    channels: usize,
) -> generator::Settings {
    for signal in &mut settings.signals {
        if signal.output_channel.is_some_and(|ch| ch >= channels) {
            signal.output_channel = None;
            signal.enabled = false;
        }
    }
    settings
}

impl ScopeApp {
    pub(super) fn input_source_label(&self) -> String {
        let source = match self.source {
            Source::Live => self
                .devices
                .get(self.selected)
                .map_or(i18n::text("io.audio_input_no_device_selected"), |d| {
                    d.name.as_str()
                }),
            Source::Software => i18n::text("io.software_loopback"),
            Source::Generator => i18n::text("io.generator_loopback_out"),
            #[cfg(feature = "qa")]
            Source::Demo => i18n::text("io.demo_signal_qa"),
        };
        i18n::format("io.input_source", &[("source", (source))]).to_string()
    }

    pub(super) fn io_controls(&mut self, ui: &mut egui::Ui) {
        ui.set_max_width(ui.available_width().min(1200.0));
        self.common_io_controls(ui);
        ui.add_space(8.0);
        if ui.available_width() >= 900.0 {
            ui.columns(2, |columns| {
                self.io_section(&mut columns[0], false);
                self.io_section(&mut columns[1], true);
            });
        } else {
            self.io_section(ui, false);
            ui.add_space(8.0);
            self.io_section(ui, true);
        }
    }

    fn io_editable(&self) -> bool {
        self.io_input_editable() && !self.running() && self.generator.stopped()
    }

    fn io_input_editable(&self) -> bool {
        self.pending_stop.is_none()
            && !self.busy
            && !self.workspace_restoring
            && self.settings_task != Some(SettingsTask::Restore)
    }

    fn io_input_rates(&self) -> Vec<u32> {
        match self.source {
            Source::Live => self
                .devices
                .get(self.selected)
                .map(|d| d.sample_rates.clone())
                .unwrap_or_default(),
            Source::Software | Source::Generator => output::RATES.to_vec(),
            #[cfg(feature = "qa")]
            Source::Demo => vec![48_000],
        }
    }

    fn io_input_rate(&self) -> Option<u32> {
        match self.source {
            Source::Live => self.requested_sample_rate.or_else(|| {
                self.devices
                    .get(self.selected)
                    .map(|d| d.default_sample_rate)
                    .filter(|&r| r != 0)
            }),
            Source::Software => Some(self.requested_sample_rate.unwrap_or(48_000)),
            Source::Generator => Some(self.generator.rate),
            #[cfg(feature = "qa")]
            Source::Demo => Some(48_000),
        }
    }

    fn common_io_rates(&self) -> Vec<u32> {
        common_rates(
            &self.io_input_rates(),
            &output_configs(&self.generator),
            output_config(&self.generator),
        )
    }

    pub(super) fn apply_common_io_rate(&mut self, rate: u32) -> Result<(), String> {
        if !self.io_editable() || !self.common_io_rates().contains(&rate) {
            return Err(
                i18n::text("io.stop_input_and_output_and_select_a_supported_common").into(),
            );
        }
        if self.source == Source::Software {
            self.loopback_settings.validate(rate)?;
        }
        let g = &mut self.generator;
        // Reject incompatible signal conditions before changing either side.
        g.settings
            .validate(rate, g.target.channels())
            .map_err(text::generator_error)?;
        if g.rate != rate {
            g.select(g.target.clone(), rate, g.settings)?;
        }
        g.error = None;
        if matches!(self.source, Source::Live | Source::Software) {
            self.requested_sample_rate = Some(rate);
            if let Some(input) = &mut self.restored_input {
                input.sample_rate = Some(rate);
            }
        }
        Ok(())
    }

    fn common_io_controls(&mut self, ui: &mut egui::Ui) {
        egui::Frame::group(ui.style()).show(ui, |ui| {
            ui.set_min_width(ui.available_width());
            ui.horizontal_wrapped(|ui| {
                ui.checkbox(
                    &mut self.shell.separate_io_rates,
                    i18n::text("io.separate_sample_rates"),
                );
                if ui
                    .add_enabled(
                        self.io_editable(),
                        egui::Button::new(i18n::text("io.refresh_devices")),
                    )
                    .clicked()
                {
                    match self.generator.worker.refresh() {
                        Ok(_) => {
                            self.busy = true;
                            self.error = None;
                            self.audio.send(Command::Refresh);
                        }
                        Err(e) => self.generator.error = Some(e),
                    }
                }
            });
            if !self.shell.separate_io_rates {
                setting_label(ui, i18n::text("io.sample_rate_input_output"));
                let rates = self.common_io_rates();
                let current = self
                    .io_input_rate()
                    .filter(|&rate| rate == self.generator.rate);
                let mut chosen = None;
                ui.add_enabled_ui(self.io_editable() && !rates.is_empty(), |ui| {
                    egui::ComboBox::from_id_salt("common_io_rate")
                        .width(ui.available_width())
                        .selected_text(current.map_or_else(
                            || i18n::text("io.select_common_rate").into(),
                            |r| i18n::format("io.hz_2", &[("r", &(r).to_string())]).to_string(),
                        ))
                        .show_ui(ui, |ui| {
                            for rate in rates.iter().copied() {
                                if ui
                                    .selectable_label(
                                        current == Some(rate),
                                        i18n::format("io.hz_3", &[("rate", &(rate).to_string())])
                                            .as_ref(),
                                    )
                                    .clicked()
                                {
                                    chosen = Some(rate);
                                }
                            }
                        });
                });
                if let Some(rate) = chosen
                    && let Err(e) = self.apply_common_io_rate(rate)
                {
                    self.generator.error = Some(e);
                }
                if current.is_none() {
                    ui.label(
                        i18n::format(
                            "io.input_output_hz",
                            &[
                                (
                                    "r",
                                    &(self.io_input_rate().map_or(
                                        i18n::text("io.unavailable").into(),
                                        |r| {
                                            i18n::format("io.hz_2", &[("r", &(r).to_string())])
                                                .to_string()
                                        },
                                    ))
                                    .to_string(),
                                ),
                                ("rate", &(self.generator.rate).to_string()),
                            ],
                        )
                        .as_ref(),
                    );
                }
                ui.label(
                    RichText::new(if rates.is_empty() {
                        i18n::text("io.no_common_rate_for_these_devices_and_output_format")
                    } else {
                        i18n::text("io.applies_to_both_while_stopped_held_results_keep_their")
                    })
                    .small()
                    .color(MUTED),
                );
            }
        });
    }

    fn io_section(&mut self, ui: &mut egui::Ui, output: bool) {
        egui::Frame::group(ui.style()).show(ui, |ui| {
            ui.set_min_width(ui.available_width());
            ui.heading(if output {
                i18n::text("io.output")
            } else {
                i18n::text("io.input")
            });
            ui.separator();
            if output {
                self.output_controls(ui);
            } else {
                self.input_controls(ui);
            }
        });
    }

    pub(super) fn input_controls(&mut self, ui: &mut egui::Ui) {
        ui.add_enabled_ui(self.io_input_editable(), |ui| self.input_settings(ui));
    }

    fn input_settings(&mut self, ui: &mut egui::Ui) {
        let old_source = self.source;
        ui.add_enabled_ui(!self.busy && self.pending_stop.is_none(), |ui| {
            ui.horizontal_wrapped(|ui| {
                ui.selectable_value(&mut self.source, Source::Live, i18n::text("io.audio_input"));
                ui.selectable_value(
                    &mut self.source,
                    Source::Software,
                    i18n::text("io.software_loopback"),
                );
                ui.add_enabled_ui(self.generator.target == output::Target::Internal, |ui| {
                    ui.selectable_value(
                        &mut self.source,
                        Source::Generator,
                        i18n::text("io.generator_loopback"),
                    );
                })
                .response
                .on_hover_text(i18n::text(
                    "io.available_with_the_internal_loopback_output_device",
                ));
            });
        });
        if old_source != self.source {
            self.switch_source();
            self.requested_sample_rate = None;
        }
        if self.source == Source::Software {
            self.software_controls(ui);
        }
        if self.source == Source::Generator {
            ui.label(
                RichText::new(i18n::text(
                    "io.out_ch_out_ch_start_input_and_output_separately",
                ))
                .small()
                .color(MUTED),
            );
        }
        #[cfg(feature = "qa")]
        if self.demo_enabled {
            setting_label(ui, i18n::text("io.source"));
            let previous_source = self.source;
            ui.add_enabled_ui(!self.busy, |ui| {
                ui.horizontal(|ui| {
                    ui.selectable_value(
                        &mut self.source,
                        Source::Live,
                        i18n::text("io.audio_input"),
                    );
                    ui.selectable_value(
                        &mut self.source,
                        Source::Demo,
                        i18n::text("io.demo_signal_qa"),
                    );
                });
            });
            if previous_source != self.source {
                self.switch_source();
            }
        }
        if self.source == Source::Live {
            setting_label(ui, i18n::text("io.device"));
            let selected_name = self
                .devices
                .get(self.selected)
                .map(|d| d.name.as_str())
                .unwrap_or(i18n::text("io.no_input_device"));
            let previous = self.selected;
            ui.add_enabled_ui(!self.busy, |ui| {
                egui::ComboBox::from_id_salt("input")
                    .width(ui.available_width())
                    .truncate()
                    .selected_text(selected_name)
                    .show_ui(ui, |ui| {
                        for (index, device) in self.devices.iter().enumerate() {
                            let name = if device.is_default {
                                i18n::format("io.default", &[("name", &(device.name).to_string())])
                                    .to_string()
                            } else {
                                device.name.clone()
                            };
                            ui.selectable_value(&mut self.selected, index, name);
                        }
                    });
            });
            if previous != self.selected {
                self.restored_input = None;
                self.calibration.clear_input();
                self.requested_sample_rate = None;
            }
            let previous_rate = self.requested_sample_rate;
            if self.shell.separate_io_rates {
                setting_label(ui, i18n::text("io.sample_rate"));
                ui.add_enabled_ui(!self.busy && !self.devices.is_empty(), |ui| {
                    egui::ComboBox::from_id_salt("input_sample_rate")
                        .width(ui.available_width())
                        .selected_text(self.input_rate_label())
                        .show_ui(ui, |ui| {
                            ui.selectable_value(
                                &mut self.requested_sample_rate,
                                None,
                                i18n::text("io.device_default"),
                            );
                            if let Some(device) = self.devices.get(self.selected) {
                                for &rate in &device.sample_rates {
                                    ui.selectable_value(
                                        &mut self.requested_sample_rate,
                                        Some(rate),
                                        i18n::format(
                                            "io.khz",
                                            &[("rate", &(rate as f64 / 1000.0).to_string())],
                                        )
                                        .as_ref(),
                                    );
                                }
                            }
                        });
                });
                ui.label(
                    RichText::new(i18n::text("io.supported_device_rates_up_to_khz"))
                        .small()
                        .color(MUTED),
                );
                if !self.running() {
                    ui.label(
                        RichText::new(i18n::text(
                            "io.rate_changes_apply_on_start_held_results_keep_their",
                        ))
                        .small()
                        .color(MUTED),
                    );
                }
            }
            if previous_rate != self.requested_sample_rate
                && let Some(input) = &mut self.restored_input
            {
                input.sample_rate = self.requested_sample_rate;
            }
            if (previous != self.selected || previous_rate != self.requested_sample_rate)
                && self.capture.is_some()
            {
                self.start();
            }
        }
        #[cfg(feature = "qa")]
        if self.source.is_demo() {
            let before = (
                self.demo.waveform,
                self.demo.frequency,
                self.demo.amplitude,
                self.demo.noise,
                self.demo.phase_degrees,
                self.demo.channel_2_gain,
            );
            setting_label(ui, i18n::text("io.waveform"));
            egui::ComboBox::from_id_salt("demo_waveform")
                .width(ui.available_width())
                .selected_text(self.demo.waveform.display_name())
                .show_ui(ui, |ui| {
                    for shape in [Waveform::Sine, Waveform::Harmonics, Waveform::Square] {
                        ui.selectable_value(&mut self.demo.waveform, shape, shape.display_name());
                    }
                });
            setting_label(ui, i18n::text("io.frequency"));
            ui.add(
                egui::Slider::new(&mut self.demo.frequency, 20.0..=10000.0)
                    .logarithmic(true)
                    .text("Hz"),
            );
            setting_label(ui, i18n::text("io.amplitude"));
            ui.add(
                egui::Slider::new(&mut self.demo.amplitude, 0.01..=0.8)
                    .text(i18n::text("io.fs_peak")),
            );
            setting_label(ui, i18n::text("io.noise_2"));
            ui.add(
                egui::Slider::new(&mut self.demo.noise, 0.0..=0.05)
                    .logarithmic(true)
                    .smallest_positive(0.000001)
                    .fixed_decimals(4)
                    .text(i18n::text("io.noise")),
            )
            .on_hover_text(i18n::text("io.noise_amplitude_in_digital_full_scale_fs"));
            setting_label(ui, i18n::text("io.ch_phase_gain"));
            ui.add(
                egui::Slider::new(&mut self.demo.phase_degrees, -180.0..=180.0)
                    .text(i18n::text("io.degrees")),
            );
            ui.add(
                egui::Slider::new(&mut self.demo.channel_2_gain, 0.0..=1.0)
                    .text(i18n::text("io.ch_gain")),
            );
            ui.horizontal(|ui| {
                for phase in [0.0, 90.0, 180.0] {
                    if ui.small_button(format!("{phase:.0}°")).clicked() {
                        self.demo.waveform = Waveform::Sine;
                        self.demo.noise = 0.0;
                        self.demo.phase_degrees = phase;
                        self.demo.channel_2_gain = 1.0;
                    }
                }
            })
            .response
            .on_hover_text(i18n::text(
                "io.equal_amplitude_noise_free_sine_signals_for_xy_in",
            ));
            if before
                != (
                    self.demo.waveform,
                    self.demo.frequency,
                    self.demo.amplitude,
                    self.demo.noise,
                    self.demo.phase_degrees,
                    self.demo.channel_2_gain,
                )
            {
                self.apply_demo_settings();
            }
            if !self.running() {
                ui.label(
                    RichText::new(i18n::text(
                        "io.signal_changes_apply_when_input_restarts_captured_samples_stay",
                    ))
                    .small()
                    .color(MUTED),
                );
            }
            ui.label(
                RichText::new(i18n::text("io.internal_source_no_audio_output"))
                    .small()
                    .color(MUTED),
            );
        }
        ui.label(
            RichText::new(i18n::text("io.start_stop_is_always_in_the_top_bar"))
                .small()
                .color(MUTED),
        );
    }

    pub(super) fn output_controls(&mut self, ui: &mut egui::Ui) {
        let selectable = self.io_editable();
        let g = &mut self.generator;
        let separate_rates = self.shell.separate_io_rates;
        ui.add_enabled_ui(selectable, |ui| {
            setting_label(ui, i18n::text("io.output_device"));
            let mut selected = g.target.clone();
            let mut rate = g.rate;
            egui::ComboBox::from_id_salt("generator_destination")
                .width(ui.available_width()).truncate()
                .selected_text(text::output_target(&g.target)).show_ui(ui, |ui| {
                    ui.selectable_value(&mut selected, output::Target::Internal, i18n::text("io.internal_loopback"));
                    for device in &g.devices {
                        let config = device.preferred;
                        let candidate = output::Target::Audio {
                            device_id: device.id.clone(), device_name: device.name.clone(),
                            channels: config.channels, pcm: config.pcm,
                        };
                        let active = matches!(&g.target, output::Target::Audio { device_id, .. } if device_id == &device.id);
                        if ui.selectable_label(active, &device.name).clicked() && !active {
                            selected = candidate;
                            rate = config.rate;
                        }
                    }
                });
            if selected != g.target {
                if selected == output::Target::Internal { rate = 48000; }
                let settings = settings_for_output_channels(g.settings, selected.channels());
                if let Err(e) = g.select(selected, rate, settings) { g.error = Some(e); }
            }
            setting_label(ui, if separate_rates { i18n::text("io.sample_rate_channels_pcm") } else { i18n::text("io.channels_pcm") });
            let mut config = output_config(g);
            let before = config;
            egui::ComboBox::from_id_salt("generator_rate")
                .width(ui.available_width()).truncate()
                .selected_text(config_label(config, separate_rates))
                .show_ui(ui, |ui| {
                    for value in output_configs(g).into_iter().filter(|c| separate_rates || c.rate == g.rate) {
                        ui.selectable_value(&mut config, value, config_label(value, separate_rates));
                    }
                });
            if config != before {
                let mut target = g.target.clone();
                if let output::Target::Audio { channels, pcm, .. } = &mut target {
                    *channels = config.channels; *pcm = config.pcm;
                }
                let settings = settings_for_output_channels(g.settings, target.channels());
                if let Err(e) = g.select(target, config.rate, settings) { g.error = Some(e); }
            }
        });
        if !selectable {
            ui.label(
                RichText::new(i18n::text(
                    "io.stop_input_and_output_to_change_the_device_or",
                ))
                .small()
                .color(MUTED),
            );
        }
        if self.source == Source::Generator && self.generator.target != output::Target::Internal {
            self.source = Source::Live;
            self.switch_source();
        }
        self.generator_reset(ui);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn common_rates_require_both_devices_and_preserve_output_channels_and_pcm() {
        let current = output::device::Config {
            rate: 48_000,
            channels: 2,
            pcm: output::device::Pcm::F64,
        };
        let configs = [
            current,
            output::device::Config {
                rate: 96_000,
                ..current
            },
            output::device::Config {
                rate: 96_000,
                ..current
            },
            output::device::Config {
                rate: 192_000,
                channels: 16,
                ..current
            },
            output::device::Config {
                rate: 192_000,
                pcm: output::device::Pcm::F32,
                ..current
            },
        ];
        assert_eq!(
            common_rates(&[44_100, 48_000, 96_000, 192_000], &configs, current),
            [48_000, 96_000]
        );
        assert!(common_rates(&[44_100], &configs, current).is_empty());
        assert!(common_rates(&[], &configs, current).is_empty());
        assert!(common_rates(&[48_000], &[], current).is_empty());
    }
}
