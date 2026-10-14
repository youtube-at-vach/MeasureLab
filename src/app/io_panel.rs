//! Shared input/output connection settings. Signal edits remain in the
//! Generator panel; device, format and channel routing live together here.
use super::generator_panel::output_channel_label;
use super::*;

impl ScopeApp {
    pub(super) fn input_controls(&mut self, ui: &mut egui::Ui) {
        let old_source = self.source;
        ui.add_enabled_ui(!self.busy && self.pending_stop.is_none(), |ui| {
            ui.horizontal_wrapped(|ui| {
                ui.selectable_value(&mut self.source, Source::Live, "Audio input");
                ui.selectable_value(&mut self.source, Source::Software, "Software Loopback");
                ui.selectable_value(&mut self.source, Source::Generator, "Generator loopback");
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
                RichText::new("2ch internal connection · Start input and output separately.")
                    .small()
                    .color(MUTED),
            );
            if ui.button("Open Generator").clicked() {
                self.presentation
                    .apply(Action::OpenSingle(Instrument::Generator));
                self.shell.io = None;
            }
        }
        #[cfg(feature = "qa")]
        if self.demo_enabled {
            setting_label(ui, "SOURCE");
            let previous_source = self.source;
            ui.add_enabled_ui(!self.busy, |ui| {
                ui.horizontal(|ui| {
                    ui.selectable_value(&mut self.source, Source::Live, "Audio input");
                    ui.selectable_value(&mut self.source, Source::Demo, "Demo signal (QA)");
                });
            });
            if previous_source != self.source {
                self.switch_source();
            }
        }
        if self.source == Source::Live {
            setting_label(ui, "DEVICE");
            let selected_name = self
                .devices
                .get(self.selected)
                .map(|d| d.name.as_str())
                .unwrap_or("No input device");
            let previous = self.selected;
            ui.add_enabled_ui(!self.busy, |ui| {
                egui::ComboBox::from_id_salt("input")
                    .width(ui.available_width())
                    .truncate()
                    .selected_text(selected_name)
                    .show_ui(ui, |ui| {
                        for (index, device) in self.devices.iter().enumerate() {
                            let name = if device.is_default {
                                format!("{} (default)", device.name)
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
            setting_label(ui, "SAMPLE RATE");
            let previous_rate = self.requested_sample_rate;
            ui.add_enabled_ui(!self.busy && !self.devices.is_empty(), |ui| {
                egui::ComboBox::from_id_salt("input_sample_rate")
                    .width(ui.available_width())
                    .selected_text(self.input_rate_label())
                    .show_ui(ui, |ui| {
                        ui.selectable_value(
                            &mut self.requested_sample_rate,
                            None,
                            "Device default",
                        );
                        if let Some(device) = self.devices.get(self.selected) {
                            for &rate in &device.sample_rates {
                                ui.selectable_value(
                                    &mut self.requested_sample_rate,
                                    Some(rate),
                                    format!("{} kHz", rate as f64 / 1000.0),
                                );
                            }
                        }
                    });
            });
            ui.label(
                RichText::new("Supported device rates · up to 768 kHz")
                    .small()
                    .color(MUTED),
            );
            if !self.running() {
                ui.label(
                    RichText::new("Rate changes apply on Start. Held results keep their rate.")
                        .small()
                        .color(MUTED),
                );
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
        if self.source == Source::Live
            && ui
                .add_enabled(
                    !self.busy && self.capture.is_none(),
                    egui::Button::new("Refresh devices"),
                )
                .clicked()
        {
            self.busy = true;
            self.error = None;
            self.audio.send(Command::Refresh);
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
            setting_label(ui, "WAVEFORM");
            egui::ComboBox::from_id_salt("demo_waveform")
                .width(ui.available_width())
                .selected_text(self.demo.waveform.name())
                .show_ui(ui, |ui| {
                    for shape in [Waveform::Sine, Waveform::Harmonics, Waveform::Square] {
                        ui.selectable_value(&mut self.demo.waveform, shape, shape.name());
                    }
                });
            setting_label(ui, "FREQUENCY");
            ui.add(
                egui::Slider::new(&mut self.demo.frequency, 20.0..=10000.0)
                    .logarithmic(true)
                    .text("Hz"),
            );
            setting_label(ui, "AMPLITUDE");
            ui.add(egui::Slider::new(&mut self.demo.amplitude, 0.01..=0.8).text("FS peak"));
            setting_label(ui, "NOISE");
            ui.add(
                egui::Slider::new(&mut self.demo.noise, 0.0..=0.05)
                    .logarithmic(true)
                    .smallest_positive(0.000001)
                    .fixed_decimals(4)
                    .text("Noise"),
            )
            .on_hover_text("Noise amplitude in digital full scale (FS).");
            setting_label(ui, "CH 2 PHASE / GAIN");
            ui.add(egui::Slider::new(&mut self.demo.phase_degrees, -180.0..=180.0).text("degrees"));
            ui.add(egui::Slider::new(&mut self.demo.channel_2_gain, 0.0..=1.0).text("CH 2 gain"));
            ui.horizontal(|ui| {
                for phase in [0.0, 90.0, 180.0] {
                    if ui.small_button(format!("{phase:.0}°")).clicked() {
                        self.demo.waveform = Waveform::Sine;
                        self.demo.noise = 0.0;
                        self.demo.phase_degrees = phase;
                        self.demo.channel_2_gain = 1.0;
                    }
                }
            }).response.on_hover_text("Equal-amplitude, noise-free sine signals for XY: in-phase, quadrature or opposite phase.");
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
                    RichText::new(
                        "Signal changes apply when input restarts. Captured samples stay held.",
                    )
                    .small()
                    .color(MUTED),
                );
            }
            ui.label(
                RichText::new("Internal source · no audio output")
                    .small()
                    .color(MUTED),
            );
        }
        ui.label(
            RichText::new("Start / stop is always in the top bar.")
                .small()
                .color(MUTED),
        );
    }

    pub(super) fn output_controls(&mut self, ui: &mut egui::Ui) {
        let input_running = self.running() || self.pending_stop.is_some();
        let restoring =
            self.workspace_restoring || self.settings_task == Some(SettingsTask::Restore);
        let g = &mut self.generator;
        let selectable = g.stopped() && !input_running && !restoring;
        ui.add_enabled_ui(selectable, |ui| {
            setting_label(ui, "OUTPUT DEVICE");
            let mut selected = g.target.clone();
            let mut rate = g.rate;
            egui::ComboBox::from_id_salt("generator_destination")
                .width(ui.available_width()).truncate()
                .selected_text(g.target.label()).show_ui(ui, |ui| {
                    ui.selectable_value(&mut selected, output::Target::Internal, "Internal loopback");
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
                let mut settings = g.settings;
                for signal in &mut settings.signals {
                    if signal.output_channel.is_some_and(|ch| ch >= selected.channels()) {
                        signal.output_channel = None;
                        signal.enabled = false;
                    }
                }
                if let Err(e) = g.select(selected, rate, settings) { g.error = Some(e); }
            }
            setting_label(ui, "SAMPLE RATE / CHANNELS / PCM");
            let mut config = output::device::Config {
                rate: g.rate, channels: g.target.channels() as u16,
                pcm: match &g.target { output::Target::Audio { pcm, .. } => *pcm, _ => output::device::Pcm::F64 },
            };
            let before = config;
            egui::ComboBox::from_id_salt("generator_rate")
                .width(ui.available_width()).truncate()
                .selected_text(format!("{} Hz · {}ch · {}", config.rate, config.channels, config.pcm.label()))
                .show_ui(ui, |ui| {
                    let configs: Vec<_> = match &g.target {
                        output::Target::Internal => output::RATES.into_iter()
                            .map(|rate| output::device::Config { rate, ..config }).collect(),
                        output::Target::Audio { device_id, .. } => g.devices.iter()
                            .find(|d| &d.id == device_id).map(|d| d.configs.clone()).unwrap_or_default(),
                    };
                    for value in configs {
                        ui.selectable_value(&mut config, value, format!("{} Hz · {}ch · {}", value.rate, value.channels, value.pcm.label()));
                    }
                });
            if config != before {
                let mut target = g.target.clone();
                if let output::Target::Audio { channels, pcm, .. } = &mut target {
                    *channels = config.channels; *pcm = config.pcm;
                }
                if let Err(e) = g.select(target, config.rate, g.settings) { g.error = Some(e); }
            }
            if ui.button("Refresh outputs").clicked()
                && let Err(e) = g.worker.refresh() { g.error = Some(e); }
        });
        if !selectable {
            ui.label(
                RichText::new("Stop input and output to change the device or format.")
                    .small()
                    .color(MUTED),
            );
        }
        setting_label(ui, "OUTPUT ROUTING");
        let mut settings = g.settings;
        ui.add_enabled_ui(g.stopped() && !restoring, |ui| {
            for (i, signal) in settings.signals.iter_mut().enumerate() {
                ui.horizontal(|ui| {
                    ui.colored_label(if i == 0 { GREEN } else { BLUE }, format!("GEN {}", i + 1));
                    egui::ComboBox::from_id_salt(("generator_channel", i))
                        .width(140.0)
                        .selected_text(output_channel_label(*signal))
                        .show_ui(ui, |ui| {
                            ui.selectable_value(&mut signal.output_channel, None, "Unassigned");
                            for c in 0..g.target.channels() {
                                ui.selectable_value(
                                    &mut signal.output_channel,
                                    Some(c),
                                    format!("OUT {}", c + 1),
                                );
                            }
                        });
                });
            }
        });
        if settings != g.settings {
            g.configure(settings);
        }
        ui.separator();
        if ui.add_enabled(!input_running && !self.busy && !restoring && g.target == output::Target::Internal,
            egui::Button::new("Observe Generator").selected(self.source == Source::Generator))
            .on_hover_text("Select the generated f64 samples as the shared 2ch input. Start input and output separately.").clicked()
            && self.source != Source::Generator {
                self.source = Source::Generator;
                self.switch_source();
        }
        if self.source == Source::Generator && self.generator.target != output::Target::Internal {
            self.source = Source::Live;
            self.switch_source();
        }
        if ui.button("Open Generator").clicked() {
            self.presentation
                .apply(Action::OpenSingle(Instrument::Generator));
            self.shell.io = None;
        }
        self.generator_reset(ui);
    }
}
