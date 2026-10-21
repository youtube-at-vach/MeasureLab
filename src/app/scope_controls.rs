//! Scope details follow the operating groups of a bench oscilloscope.
use super::*;

impl ScopeApp {
    pub(super) fn scope_controls(&mut self, ui: &mut egui::Ui) {
        control_group(ui, "ACQUISITION", MUTED, |ui| {
            let old_mode = self.acquisition_mode;
            ui.horizontal(|ui| {
                for (mode, label, help) in [
                    (
                        acquisition::Mode::Auto,
                        "Auto",
                        "Update even without a trigger crossing",
                    ),
                    (
                        acquisition::Mode::Normal,
                        "Normal",
                        "Update on trigger crossings; hold the last capture while waiting",
                    ),
                    (
                        acquisition::Mode::Single,
                        "Single",
                        "Capture once on the next trigger crossing",
                    ),
                ] {
                    ui.selectable_value(&mut self.acquisition_mode, mode, label)
                        .on_hover_text(help);
                }
            });
            self.dirty |= old_mode != self.acquisition_mode;
            ui.horizontal(|ui| {
                if ui
                    .add_enabled(
                        !self.running() && self.input_transport_enabled(),
                        egui::Button::new("Start single capture"),
                    )
                    .on_hover_text("Start input and wait for a single triggered capture")
                    .clicked()
                {
                    self.acquisition_mode = acquisition::Mode::Single;
                    self.start();
                }
                if ui
                    .add_enabled(
                        self.autoset_pending.is_none() && self.core.is_some(),
                        egui::Button::new("Autoset"),
                    )
                    .on_hover_text(
                        "Automatically set time scale, amplitude and trigger for a periodic signal",
                    )
                    .clicked()
                {
                    self.autoset_pending =
                        Some(self.core.as_ref().unwrap().autoset(self.trigger.channel));
                }
            });
            if let Some(status) = &self.autoset_status {
                ui.label(RichText::new(status).small().color(MUTED));
            }
        });

        control_group(ui, "TRIGGER", TRIGGER, |ui| self.trigger_controls(ui));

        control_group(ui, "HORIZONTAL", BLUE, |ui| {
            self.dirty |= control_slider(
                ui,
                "Time scale",
                egui::Slider::new(&mut self.ms_per_div, 0.05..=100.0)
                    .logarithmic(true)
                    .suffix(" ms/div")
                    .max_decimals(3)
                    .drag_value_speed(0.05),
                None,
            )
            .0;
            let (changed, centre) = control_slider(
                ui,
                "Position",
                egui::Slider::new(&mut self.scope_horizontal_position, -5.0..=5.0)
                    .suffix(" div")
                    .max_decimals(2)
                    .drag_value_speed(0.1)
                    .trailing_fill(false),
                Some("Reset time position"),
            );
            if centre {
                self.scope_horizontal_position = 0.0;
            }
            self.dirty |= changed || centre;
        });

        let index = self.scope_selected;
        let color = monitor_controls::scope_color(index);
        control_group(ui, &format!("VERTICAL · CH{}", index + 1), color, |ui| {
            ui.horizontal(|ui| {
                ui.label("Input source");
                let before = self.scope_channels;
                let channels = self.lockin_channel_count().max(self.scope_channel_count());
                channel_select(
                    ui,
                    "scope_channel_source",
                    &mut self.scope_channels.0[index],
                    channels,
                );
                self.dirty |= self.scope_channels != before;
            });
            let channel = self.scope_view_channels().0[index];
            if self
                .scope_input_channels()
                .is_some_and(|count| !channel::available(channel, count as usize))
            {
                ui.label(
                    RichText::new(format!(
                        "{} · outside input channel range",
                        channel::name(channel)
                    ))
                    .small()
                    .color(MUTED),
                );
            }
            self.dirty |= control_slider(
                ui,
                "Vertical range",
                egui::Slider::new(&mut self.scope_vertical[index].fs_per_div, 0.001..=0.5)
                    .logarithmic(true)
                    .suffix(" FS/div")
                    .max_decimals(3)
                    .drag_value_speed(0.001),
                None,
            )
            .0;
            let (changed, zero) = control_slider(
                ui,
                "Centre offset",
                egui::Slider::new(&mut self.scope_vertical[index].offset, -2.0..=2.0)
                    .suffix(" FS")
                    .max_decimals(3)
                    .drag_value_speed(0.001)
                    .trailing_fill(false),
                Some("Zero offset"),
            );
            if zero {
                self.scope_vertical[index].offset = 0.0;
            }
            self.dirty |= changed || zero;
            if ui
                .button("Fit amplitude")
                .on_hover_text("Fit the selected channel's raw peak and centre its offset")
                .clicked()
            {
                self.fit_scope_amplitude();
            }
            ui.label(
                RichText::new(self.scope_readout(index))
                    .small()
                    .color(color),
            )
            .on_hover_text(self.scope_readout_details(index));
        });

        if !self.running() && self.core_scope.mode != acquisition::Mode::Auto {
            ui.label(
                RichText::new("Time / trigger edits apply on next Start")
                    .small()
                    .color(YELLOW),
            );
        }
        ui.label(
            RichText::new("Wheel: time scale · Shift+wheel: selected channel scale")
                .small()
                .color(MUTED),
        );
        ui.add(egui::Label::new("FS = full scale · Fs = sample rate · div = grid division").wrap())
            .on_hover_text(format!(
                "{}\n{}\n{}",
                display::AMPLITUDE_HELP,
                display::SAMPLE_RATE_HELP,
                display::DIV_HELP
            ));
    }

    pub(super) fn trigger_controls(&mut self, ui: &mut egui::Ui) {
        let before = (self.trigger.edge, self.trigger.channel);
        ui.horizontal(|ui| {
            ui.label("Edge");
            egui::ComboBox::from_id_salt("edge")
                .width(ui.available_width())
                .selected_text(match self.trigger.edge {
                    Edge::Free => "Free run",
                    Edge::Rising => "Rising edge",
                    Edge::Falling => "Falling edge",
                })
                .show_ui(ui, |ui| {
                    ui.selectable_value(&mut self.trigger.edge, Edge::Free, "Free run");
                    ui.selectable_value(&mut self.trigger.edge, Edge::Rising, "Rising edge");
                    ui.selectable_value(&mut self.trigger.edge, Edge::Falling, "Falling edge");
                });
        });
        ui.horizontal(|ui| {
            ui.label("Source");
            let channels = self.lockin_channel_count().max(self.scope_channel_count());
            channel_select(ui, "trigger_channel", &mut self.trigger.channel, channels);
        });
        self.dirty |= before != (self.trigger.edge, self.trigger.channel);
        let (changed, zero) = control_slider(
            ui,
            "Level",
            egui::Slider::new(&mut self.trigger.level, -1.0..=1.0)
                .suffix(" FS")
                .max_decimals(3)
                .drag_value_speed(0.001)
                .trailing_fill(false),
            Some("Zero level"),
        );
        if zero {
            self.trigger.level = 0.0;
        }
        self.dirty |= changed || zero;
        ui.add(egui::Label::new("T markers: top = 0 ms · right = level").wrap())
            .on_hover_text(self.scope_trigger_marker_help());
    }
}

pub(super) fn control_group(
    ui: &mut egui::Ui,
    title: &str,
    accent: Color32,
    contents: impl FnOnce(&mut egui::Ui),
) {
    egui::Frame::new()
        .fill(Color32::from_rgb(20, 29, 37))
        .stroke(Stroke::new(1.0, BORDER))
        .corner_radius(5)
        .inner_margin(10)
        .show(ui, |ui| {
            ui.set_width(ui.available_width());
            ui.spacing_mut().item_spacing = vec2(6.0, 5.0);
            ui.label(RichText::new(title).small().strong().color(accent));
            ui.add_space(2.0);
            contents(ui);
        });
    ui.add_space(4.0);
}

/// Keep units with the editable value and give every rail the same width.
/// The value retains egui's drag and keyboard entry, alongside the slider.
pub(super) fn control_slider(
    ui: &mut egui::Ui,
    label: &str,
    slider: egui::Slider<'_>,
    reset: Option<&str>,
) -> (bool, bool) {
    let mut reset_clicked = false;
    let label = ui
        .horizontal(|ui| {
            let response = ui.label(label);
            if let Some(reset) = reset {
                ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                    reset_clicked = ui.small_button(reset).clicked();
                });
            }
            response
        })
        .inner;
    ui.spacing_mut().slider_width = (ui.available_width() - 100.0).max(80.0);
    // Always-clamping sliders round the stored value on every paint. Preserve
    // values from wheel edits, Autoset and restored settings until a user edits.
    let response = ui
        .add(slider.clamping(egui::SliderClamping::Edits))
        .labelled_by(label.id)
        .on_hover_text(
            "Drag the slider or value to adjust. Double-click the value to type a number.",
        );
    (response.changed(), reset_clicked)
}
