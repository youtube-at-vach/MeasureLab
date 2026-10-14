//! Application chrome, navigation and console layout; measurement lives in ScopeApp.
use super::*;
use crate::presentation::PANE_CHROME;

#[derive(Clone, Copy, Default, PartialEq, Eq)]
pub(super) enum IoTab {
    #[default]
    Input,
    Output,
    Calibration,
}

#[derive(Clone, Default)]
pub(super) struct Shell {
    pub io: Option<IoTab>,
    pub help: bool,
    pub file_paths: bool,
    pub search: String,
    pub narrow_details: bool,
    pub previous_console: Option<Console>,
}

impl ScopeApp {
    fn navigate(&mut self, action: Action) {
        if matches!(action, Action::PairWith(_))
            && !self.presentation.console.instruments.is_empty()
        {
            self.shell.previous_console = Some(self.presentation.console.clone());
        }
        self.presentation.apply(action);
        self.shell.io = None;
        self.shell.narrow_details = false;
    }

    pub(super) fn shell_header(&mut self, ui: &mut egui::Ui) {
        let ctx = ui.ctx().clone();
        if !ctx.text_edit_focused() {
            for (index, key) in [
                egui::Key::Num1,
                egui::Key::Num2,
                egui::Key::Num3,
                egui::Key::Num4,
                egui::Key::Num5,
                egui::Key::Num6,
                egui::Key::Num7,
            ]
            .into_iter()
            .enumerate()
            {
                if ctx.input(|i| i.modifiers.ctrl && i.key_pressed(key)) {
                    self.navigate(Action::OpenSingle(Instrument::ALL[index]));
                }
            }
            if ctx.input(|i| i.key_pressed(egui::Key::Escape)) {
                self.shell.io = None;
                self.shell.narrow_details = false;
            }
            let step = ctx.input(|i| {
                if i.modifiers.ctrl && i.key_pressed(egui::Key::ArrowRight) {
                    1
                } else if i.modifiers.ctrl && i.key_pressed(egui::Key::ArrowLeft) {
                    -1
                } else {
                    0
                }
            });
            if step != 0 && self.presentation.screen == Screen::Console {
                let c = &self.presentation.console;
                if let Some(index) = c
                    .selected
                    .and_then(|s| c.instruments.iter().position(|i| *i == s))
                {
                    let index =
                        (index as isize + step).rem_euclid(c.instruments.len() as isize) as usize;
                    self.presentation
                        .apply(Action::FocusPane(c.instruments[index]));
                }
            }
        }
        egui::Panel::top("header").show(ui, |ui| {
            ui.horizontal_wrapped(|ui| {
                ui.label(RichText::new("MeasureLab").strong().color(GREEN));
                self.file_menu(ui);
                self.view_menu(ui);
                ui.menu_button("I/O", |ui| {
                    for (tab, name) in [
                        (IoTab::Input, "Input"),
                        (IoTab::Output, "Output"),
                        (IoTab::Calibration, "Calibration"),
                    ] {
                        if ui.button(name).clicked() {
                            self.shell.io = Some(tab);
                            ui.close();
                        }
                    }
                });
                if ui.button("Help").clicked() {
                    self.shell.help = true;
                }
                if ui.max_rect().width() < 1180.0 {
                    self.instrument_menu(ui);
                }
            });
            ui.horizontal_wrapped(|ui| {
                ui.label(
                    RichText::new(if self.pending_stop.is_some() {
                        "INPUT · FINISHING"
                    } else if self.busy {
                        "INPUT · OPENING"
                    } else if self.running() {
                        "INPUT · LIVE"
                    } else {
                        "INPUT · STOPPED"
                    })
                    .small()
                    .monospace()
                    .color(if self.running() { GREEN } else { MUTED }),
                );
                self.transport(ui);
                ui.separator();
                self.generator_transport(ui);
                ui.menu_button("Running…", |ui| {
                    ui.label(if self.running() {
                        "Scope / Spectrum / STFT / XY · input running"
                    } else {
                        "Shared input · stopped"
                    });
                    ui.label("Display selection does not start or stop measurement.");
                    ui.separator();
                    let before = self.lockin_settings;
                    ui.label(format!(
                        "Lock-in · {}",
                        self.analysis_state(self.lockin_settings.enabled)
                    ));
                    if ui
                        .add_enabled(
                            self.lockin_settings.enabled
                                && !self.busy
                                && self.pending_stop.is_none()
                                && !self.workspace_restoring
                                && self.settings_task != Some(SettingsTask::Restore),
                            egui::Button::new("Stop Lock-in analysis"),
                        )
                        .clicked()
                    {
                        self.lockin_settings.enabled = false;
                        self.apply_lockin_controls(before);
                    }
                    let before = self.comparison_settings;
                    ui.label(format!(
                        "Synchronous 2ch · {}",
                        self.analysis_state(self.comparison_settings.enabled)
                    ));
                    if ui
                        .add_enabled(
                            self.comparison_settings.enabled
                                && !self.busy
                                && self.pending_stop.is_none()
                                && !self.workspace_restoring
                                && self.settings_task != Some(SettingsTask::Restore),
                            egui::Button::new("Stop synchronous analysis"),
                        )
                        .clicked()
                    {
                        self.comparison_settings.enabled = false;
                        self.apply_comparison_controls(before);
                    }
                });
            });
        });
    }

    pub(super) fn analysis_state(&self, enabled: bool) -> &'static str {
        if !enabled {
            "STOPPED"
        } else if self.running() {
            "ANALYSIS ON"
        } else {
            "WAITING FOR INPUT"
        }
    }

    fn view_menu(&mut self, ui: &mut egui::Ui) {
        ui.menu_button("View", |ui| {
            ui.checkbox(
                &mut self.presentation.details_visible,
                "Selected instrument details",
            );
            ui.separator();
            ui.label("Console arrangement");
            for layout in Layout::ALL {
                if ui
                    .selectable_label(self.presentation.console.layout == layout, layout.name())
                    .clicked()
                {
                    self.presentation.apply(Action::SetLayout(layout));
                }
            }
            ui.add(
                egui::Slider::new(&mut self.presentation.console.split, 0.2..=0.8)
                    .text("First pane share"),
            );
            ui.separator();
            let mut zoom = ui.ctx().zoom_factor();
            if ui
                .add(egui::Slider::new(&mut zoom, 0.75..=1.75).text("Display scale"))
                .changed()
            {
                ui.ctx().set_zoom_factor(zoom);
            }
        });
    }

    fn instrument_menu(&mut self, ui: &mut egui::Ui) {
        let title = if self.shell.io.is_some() {
            "Instruments".into()
        } else {
            self.presentation
                .selected()
                .map_or("Console".into(), |i| format!("Instrument: {}", i.name()))
        };
        ui.menu_button(title, |ui| self.instrument_list(ui, true));
    }

    fn instrument_list(&mut self, ui: &mut egui::Ui, close_menu: bool) {
        ui.add(
            egui::TextEdit::singleline(&mut self.shell.search)
                .hint_text("Find an instrument")
                .desired_width(ui.available_width()),
        );
        let query = self.shell.search.trim().to_lowercase();
        let mut group = "";
        for instrument in Instrument::ALL {
            if !format!("{} {}", instrument.name(), instrument.purpose())
                .to_lowercase()
                .contains(&query)
            {
                continue;
            }
            if group != instrument.group() {
                group = instrument.group();
                ui.add_space(8.0);
                setting_label(ui, group);
            }
            if instrument_button(ui, &self.presentation, instrument, self.shell.io.is_none())
                .clicked()
            {
                self.navigate(Action::OpenSingle(instrument));
                if close_menu {
                    ui.close();
                }
            }
            let state = match instrument {
                Instrument::Generator => self.generator.label(),
                Instrument::Lockin => self.analysis_state(self.lockin_settings.enabled),
                Instrument::Comparison => self.analysis_state(self.comparison_settings.enabled),
                _ => {
                    if self.running() {
                        "INPUT LIVE"
                    } else {
                        "INPUT STOPPED"
                    }
                }
            };
            ui.label(RichText::new(state).small().color(MUTED));
        }
        ui.separator();
        if ui
            .selectable_label(
                self.presentation.screen == Screen::Console && self.shell.io.is_none(),
                "Measurement console",
            )
            .clicked()
        {
            self.navigate(Action::OpenConsole);
            if close_menu {
                ui.close();
            }
        }
    }

    pub(super) fn shell_sides(&mut self, ui: &mut egui::Ui) {
        if ui.max_rect().width() < 1180.0 {
            return;
        }
        egui::Panel::left("instrument_list")
            .default_size(164.0)
            .size_range(150.0..=220.0)
            .resizable(true)
            .show(ui, |ui| {
                setting_label(ui, "INSTRUMENTS");
                egui::ScrollArea::vertical()
                    .id_salt("instrument_list_scroll")
                    .show(ui, |ui| self.instrument_list(ui, false));
            });
        if self.presentation.details_visible && self.shell.io.is_none() {
            egui::Panel::right("instrument_details")
                .default_size(290.0)
                .size_range(270.0..=360.0)
                .resizable(true)
                .show(ui, |ui| {
                    egui::ScrollArea::vertical()
                        .id_salt(("selected_details", self.presentation.selected()))
                        .auto_shrink([false, false])
                        .show(ui, |ui| self.selected_details(ui));
                });
        }
    }

    fn selected_details(&mut self, ui: &mut egui::Ui) {
        let Some(instrument) = self.presentation.selected() else {
            ui.label("Add an instrument to edit its details.");
            return;
        };
        ui.heading(instrument.name());
        ui.label(
            RichText::new("SELECTED INSTRUMENT · DETAILS")
                .small()
                .color(MUTED),
        );
        ui.separator();
        if self.settings_task == Some(SettingsTask::Restore) || self.workspace_restoring {
            ui.label("Restoring settings…");
            return;
        }
        ui.spacing_mut().slider_width = (ui.available_width() - 140.0).max(75.0);
        match instrument {
            Instrument::Scope => self.scope_controls(ui),
            Instrument::Spectrum => self.spectrum_controls(ui),
            Instrument::Spectrogram => self.spectrogram_controls(ui),
            Instrument::Xy => {
                ui.label("X and Y use the same input frame. Trace Snap shares the Scope trigger; Free keeps amplitude coordinates.");
                ui.label("Source and display controls are in the XY instrument.");
            }
            Instrument::Lockin => self.lockin_controls(ui),
            Instrument::Comparison => self.comparison_controls(ui),
            Instrument::Generator => self.generator_controls(ui),
        }
    }

    pub(super) fn shell_central(&mut self, ui: &mut egui::Ui) {
        let narrow = ui.max_rect().width() < 1180.0;
        egui::CentralPanel::default().show(ui, |ui| {
            ui.spacing_mut().item_spacing = vec2(6.0, 5.0);
            if let Some(error) = &self.error { ui.colored_label(TRIGGER, error); }
            if let Some(tab) = self.shell.io {
                ui.horizontal_wrapped(|ui| {
                    ui.heading("Input / output");
                    if ui.button("Back to instruments").clicked() { self.shell.io = None; }
                    for (t, name) in [(IoTab::Input, "Input"), (IoTab::Output, "Output"), (IoTab::Calibration, "Calibration")] {
                        if ui.selectable_label(tab == t, name).clicked() { self.shell.io = Some(t); }
                    }
                });
                egui::ScrollArea::vertical().id_salt("common_io").show(ui, |ui| {
                    ui.set_max_width(720.0);
                    match self.shell.io.unwrap_or(tab) { IoTab::Input => self.input_controls(ui), IoTab::Output => self.output_controls(ui), IoTab::Calibration => self.calibration_controls(ui) }
                });
                return;
            }
            if narrow && self.presentation.details_visible {
                ui.horizontal(|ui| {
                    ui.selectable_value(&mut self.shell.narrow_details, false, "Measurement");
                    ui.selectable_value(&mut self.shell.narrow_details, true, "Details");
                    if let Some(i) = self.presentation.selected() { ui.label(i.name()); }
                });
                if self.shell.narrow_details {
                    egui::ScrollArea::vertical().id_salt("narrow_details").show(ui, |ui| self.selected_details(ui));
                    return;
                }
            }
            match self.presentation.screen {
                Screen::Single(i) => {
                    ui.horizontal_wrapped(|ui| {
                        ui.heading(i.name());
                        ui.menu_button("Pair with…", |ui| {
                            if !self.presentation.console.instruments.is_empty() {
                                ui.label("This replaces the saved console. Undo is available in the console."); ui.separator();
                            }
                            for other in Instrument::ALL {
                                if other != i && ui.button(other.name()).clicked() { self.navigate(Action::PairWith(other)); ui.close(); }
                            }
                        });
                    });
                    let available = ui.available_size();
                    egui::ScrollArea::vertical().id_salt(("single", i)).auto_shrink([false, false]).show(ui, |ui| {
                        ui.allocate_ui_with_layout(vec2(ui.available_width().min(available.x), available.y.max(i.minimum_size()[1])), egui::Layout::top_down(egui::Align::Min), |ui| self.draw_instrument(ui, i));
                    });
                }
                Screen::Console => self.console(ui),
            }
        });
        let ctx = ui.ctx().clone();
        let mut help = self.shell.help;
        egui::Window::new("Help").open(&mut help).resizable(true).show(&ctx, |ui| {
            ui.label("Space: start / stop shared input. Typing in an editor leaves input unchanged.");
            ui.label("Ctrl + 1…7: open an instrument. Ctrl + Left / Right: select a console pane.");
            ui.label("Tab / Shift + Tab: move keyboard focus. Enter / Space: activate a focused control.");
            ui.label("Escape: return from I/O or narrow details.");
            ui.separator();
            ui.label("FS: digital full scale; physical amplitude and clocks require calibration.");
            ui.label("LIVE / HELD / WAITING describe acquisition; validity and calibration are shown separately.");
            ui.label(format!("{} · UI {:.0} fps · CPU FFT {:.2} ms", self.adapter, self.fps, self.fft_ms));
        });
        self.shell.help = help;
        let mut paths = self.shell.file_paths;
        egui::Window::new("File paths & status")
            .open(&mut paths)
            .default_width(440.0)
            .show(&ctx, |ui| {
                egui::ScrollArea::vertical().show(ui, |ui| self.workspace_controls(ui));
            });
        self.shell.file_paths = paths;
    }

    fn console(&mut self, ui: &mut egui::Ui) {
        ui.horizontal_wrapped(|ui| {
            ui.heading("Measurement console");
            ui.menu_button("Add instrument…", |ui| {
                for i in Instrument::ALL {
                    if ui.button(i.name()).clicked() {
                        self.navigate(Action::AddToConsole(i));
                        ui.close();
                    }
                }
            });
            if ui
                .add_enabled(
                    self.shell.previous_console.is_some(),
                    egui::Button::new("Undo replacement"),
                )
                .clicked()
                && let Some(previous) = self.shell.previous_console.take()
            {
                self.presentation.console = previous;
            }
            for layout in Layout::ALL {
                if ui
                    .selectable_label(self.presentation.console.layout == layout, layout.name())
                    .clicked()
                {
                    self.presentation.apply(Action::SetLayout(layout));
                }
            }
        });
        if self.presentation.console.instruments.is_empty() {
            ui.label("Add instruments to observe and generate signals together. Removing a pane leaves its analysis and output running.");
            return;
        }
        ui.horizontal_wrapped(|ui| {
            for i in self.presentation.console.instruments.clone() {
                if ui
                    .selectable_label(
                        self.presentation.console.selected == Some(i),
                        pane_title(i, self.presentation.console.selected == Some(i)),
                    )
                    .clicked()
                {
                    self.presentation.apply(Action::FocusPane(i));
                }
            }
        });
        // The tab strip may wrap. Decide only after its actual height is known.
        let gap = ui.spacing().item_spacing.x;
        let layout = self.presentation.console.effective_layout(
            ui.available_width(),
            ui.available_height(),
            gap,
        );
        if layout == Layout::Tabs
            && self.presentation.console.layout != Layout::Tabs
            && self.presentation.console.instruments.len() > 1
        {
            ui.label(RichText::new("Tabs keep controls and readings visible at this size. The requested arrangement returns when space allows.").small().color(MUTED));
        }
        let instruments = self.presentation.console.displayed(layout).to_vec();
        let columns = if matches!(layout, Layout::Columns | Layout::Grid) {
            2
        } else {
            1
        };
        let available = ui.available_size();
        let sizes = self
            .presentation
            .console
            .pane_sizes(layout, available.x, available.y, gap);
        egui::ScrollArea::vertical()
            .id_salt("console_scroll")
            .auto_shrink([false, false])
            .show(ui, |ui| {
                ui.spacing_mut().item_spacing = vec2(gap, gap);
                for (row, panes) in instruments.chunks(columns).enumerate() {
                    ui.horizontal_top(|ui| {
                        ui.spacing_mut().item_spacing.x = gap;
                        for (column, &i) in panes.iter().enumerate() {
                            let [width, height] = sizes[row * columns + column];
                            ui.allocate_ui_with_layout(
                                vec2(width, height.max(i.minimum_size()[1] + PANE_CHROME[1])),
                                egui::Layout::top_down(egui::Align::Min),
                                |ui| {
                                    let frame = egui::Frame::new()
                                        .stroke(Stroke::new(
                                            2.0,
                                            if self.presentation.console.selected == Some(i) {
                                                BLUE
                                            } else {
                                                BORDER
                                            },
                                        ))
                                        .inner_margin(4.0)
                                        .show(ui, |ui| {
                                            ui.horizontal_wrapped(|ui| {
                                                if ui
                                                    .selectable_label(
                                                        self.presentation.console.selected
                                                            == Some(i),
                                                        pane_title(
                                                            i,
                                                            self.presentation.console.selected
                                                                == Some(i),
                                                        ),
                                                    )
                                                    .clicked()
                                                {
                                                    self.presentation.apply(Action::FocusPane(i));
                                                }
                                                if ui.small_button("Open single").clicked() {
                                                    self.navigate(Action::OpenSingle(i));
                                                }
                                                if ui
                                                    .small_button("Remove from view")
                                                    .on_hover_text("Analysis and output continue")
                                                    .clicked()
                                                {
                                                    self.presentation
                                                        .apply(Action::RemoveFromConsole(i));
                                                }
                                            });
                                            // Expanded details and wrapped readouts must
                                            // stay inside their pane, including a held
                                            // Lock-in with all four values visible.
                                            let available = ui.available_size();
                                            egui::ScrollArea::vertical()
                                                .id_salt(("console_contents", i))
                                                .max_height(available.y)
                                                .auto_shrink([false, true])
                                                .show(ui, |ui| {
                                                    ui.allocate_ui_with_layout(
                                                        vec2(ui.available_width(), available.y),
                                                        egui::Layout::top_down(egui::Align::Min),
                                                        |ui| self.draw_instrument(ui, i),
                                                    );
                                                });
                                        });
                                    if pane_clicked(ui, frame.response.rect) {
                                        self.presentation.apply(Action::FocusPane(i));
                                    }
                                    #[cfg(feature = "qa")]
                                    if self.smoke && layout != Layout::Tabs {
                                        assert!(
                                            frame.response.rect.width() <= width + 1.0,
                                            "{} exceeds console width",
                                            i.name()
                                        );
                                        assert!(
                                            frame.response.rect.height() <= height + 1.0,
                                            "{} exceeds console height: {} > {}",
                                            i.name(),
                                            frame.response.rect.height(),
                                            height
                                        );
                                    }
                                },
                            );
                        }
                    });
                }
            });
    }

    fn draw_instrument(&mut self, ui: &mut egui::Ui, instrument: Instrument) {
        #[cfg(feature = "qa")]
        let width = ui.available_width();
        let response = ui.push_id(instrument, |ui| match instrument {
            Instrument::Scope => self.scope_panel(ui),
            Instrument::Spectrum => self.spectrum_panel(ui),
            Instrument::Spectrogram => self.spectrogram_panel(ui),
            Instrument::Xy => self.xy_panel(ui),
            Instrument::Lockin => self.lockin_panel(ui),
            Instrument::Comparison => self.comparison_panel(ui),
            Instrument::Generator => self.generator_panel(ui),
        });
        #[cfg(feature = "qa")]
        if self.smoke {
            assert!(
                response.response.rect.is_finite(),
                "{} produced nonfinite display bounds",
                instrument.name()
            );
            assert!(
                response.response.rect.width() <= width + 1.0,
                "{} exceeds its pane: {} > {}",
                instrument.name(),
                response.response.rect.width(),
                width
            );
        }
        #[cfg(not(feature = "qa"))]
        let _ = response;
    }

    #[cfg(feature = "qa")]
    pub(super) fn check_redesign_navigation(&mut self) -> Result<(), String> {
        let saved = self.presentation.clone();
        let saved_shell = self.shell.clone();
        let running = self.running();
        let generation = self.input_generation;
        let range = self.history.range();
        let power = self.analyzer.power().to_vec();
        let settings = (
            self.scope_channels,
            self.spectrum_settings,
            self.spectrogram_settings,
            self.lockin_settings,
            self.comparison_settings,
            self.generator.settings,
        );
        let lockin = self.lockin_result.clone();
        let comparison = self.comparison_result.clone();
        let output_status = self.generator.status;
        let output_request = self.generator.command_marker();
        let held = self.capture_results().ok();
        for i in Instrument::ALL {
            self.navigate(Action::OpenSingle(i));
            self.navigate(Action::OpenSingle(i));
            assert_eq!(self.presentation.screen, Screen::Single(i));
        }
        self.navigate(Action::OpenSingle(Instrument::Scope));
        self.navigate(Action::PairWith(Instrument::Generator));
        let pair = self.presentation.console.clone();
        self.navigate(Action::OpenSingle(Instrument::Scope));
        self.navigate(Action::OpenConsole);
        assert_eq!(self.presentation.console, pair);
        for i in Instrument::ALL {
            self.navigate(Action::AddToConsole(i));
        }
        assert_eq!(self.presentation.console.instruments.len(), 7);
        for i in Instrument::ALL {
            self.navigate(Action::FocusPane(i));
        }
        let console = self.presentation.console.clone();
        self.navigate(Action::OpenSingle(Instrument::Scope));
        self.navigate(Action::PairWith(Instrument::Spectrum));
        assert_eq!(self.shell.previous_console.as_ref(), Some(&console));
        self.presentation.console = self.shell.previous_console.take().unwrap();
        self.navigate(Action::OpenConsole);
        for i in Instrument::ALL {
            self.navigate(Action::RemoveFromConsole(i));
        }
        assert_eq!(self.presentation.selected(), None);
        assert_eq!(self.running(), running);
        assert_eq!(self.input_generation, generation);
        assert_eq!(self.history.range(), range);
        assert_eq!(self.analyzer.power(), power);
        assert_eq!(
            (
                self.scope_channels,
                self.spectrum_settings,
                self.spectrogram_settings,
                self.lockin_settings,
                self.comparison_settings,
                self.generator.settings
            ),
            settings
        );
        assert_eq!(self.lockin_result, lockin);
        assert_eq!(self.comparison_result, comparison);
        assert_eq!(self.generator.status, output_status);
        assert_eq!(self.generator.command_marker(), output_request);
        if let Some(held) = held {
            assert_eq!(self.capture_results()?, held);
        }
        self.presentation = saved;
        self.shell = saved_shell;
        println!(
            "GUI navigation OK: seven instruments, pair/console return, deduplication, replacement undo, empty console; input, DSP conditions, held values and output commands unchanged"
        );
        Ok(())
    }

    #[cfg(feature = "qa")]
    pub(super) fn select_view(&mut self, visible: [bool; 4]) {
        self.qa_previous_presentation
            .get_or_insert_with(|| self.presentation.clone());
        let instruments: Vec<_> = Instrument::ALL[..4]
            .iter()
            .copied()
            .zip(visible)
            .filter_map(|(i, on)| on.then_some(i))
            .collect();
        self.presentation.screen = if instruments.len() == 1 {
            Screen::Single(instruments[0])
        } else {
            Screen::Console
        };
        self.presentation.console = Console {
            selected: instruments.first().copied(),
            instruments,
            layout: Layout::Grid,
            split: 0.5,
        };
    }
    #[cfg(feature = "qa")]
    pub(super) fn qa_show(&mut self, instrument: Instrument) {
        if let Screen::Single(i) = self.presentation.screen {
            self.presentation.apply(Action::AddToConsole(i));
        }
        self.presentation.apply(Action::AddToConsole(instrument));
        if self.presentation.console.instruments.len() == 1 {
            self.presentation.screen = Screen::Single(instrument);
        }
    }
    #[cfg(feature = "qa")]
    pub(super) fn restore_view(&mut self) {
        if let Some(previous) = self.qa_previous_presentation.take() {
            self.presentation = previous;
        }
    }
}

fn instrument_button(
    ui: &mut egui::Ui,
    presentation: &Presentation,
    instrument: Instrument,
    active: bool,
) -> egui::Response {
    ui.selectable_label(
        active && presentation.screen == Screen::Single(instrument),
        instrument.name(),
    )
    .on_hover_text(instrument.purpose())
}

fn pane_title(instrument: Instrument, selected: bool) -> String {
    if selected {
        format!("{} · Selected", instrument.name())
    } else {
        instrument.name().into()
    }
}

fn pane_clicked(ui: &egui::Ui, rect: egui::Rect) -> bool {
    let position = ui.input(|input| {
        input
            .pointer
            .any_pressed()
            .then(|| input.pointer.interact_pos())
            .flatten()
    });
    position.is_some_and(|p| rect.contains(p) && ui.ctx().layer_id_at(p) == Some(ui.layer_id()))
}

pub(super) fn input_shortcut(ctx: &egui::Context, enabled: bool) -> bool {
    if !enabled || ctx.egui_wants_keyboard_input() || ctx.any_popup_open() {
        return false;
    }
    let pressed = ctx.input(|input| {
        input.events.iter().any(|event| matches!(event,
        egui::Event::Key { key: egui::Key::Space, pressed: true, repeat: false, modifiers, .. }
            if *modifiers == egui::Modifiers::NONE
    ))
    });
    pressed && ctx.input_mut(|input| input.consume_key(egui::Modifiers::NONE, egui::Key::Space))
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn a_foreground_editor_does_not_select_the_console_pane_behind_it() {
        let ctx = egui::Context::default();
        let mut text = String::new();
        let mut editor = egui::Rect::NOTHING;
        let mut selected = false;
        for frame in 0..3 {
            let events = if frame == 2 {
                vec![
                    egui::Event::PointerMoved(editor.center()),
                    egui::Event::PointerButton {
                        pos: editor.center(),
                        button: egui::PointerButton::Primary,
                        pressed: true,
                        modifiers: egui::Modifiers::NONE,
                    },
                ]
            } else {
                vec![]
            };
            ctx.run_ui(
                egui::RawInput {
                    screen_rect: Some(egui::Rect::from_min_size(
                        pos2(0.0, 0.0),
                        vec2(900.0, 660.0),
                    )),
                    events,
                    ..Default::default()
                },
                |ui| {
                    let pane = egui::Rect::from_min_size(pos2(0.0, 0.0), vec2(600.0, 500.0));
                    ui.allocate_rect(pane, egui::Sense::hover());
                    selected |= pane_clicked(ui, pane);
                    egui::Window::new("File editor")
                        .fixed_pos(pos2(60.0, 60.0))
                        .show(ui.ctx(), |ui| {
                            editor = ui.text_edit_singleline(&mut text).rect;
                        });
                },
            )
            .drop_without_applying_deltas();
        }
        assert!(
            !selected,
            "the foreground edit must keep the selected instrument"
        );
    }

    #[test]
    fn real_pointer_events_select_without_toggling_and_hover_does_not_focus_a_pane() {
        let ctx = egui::Context::default();
        let mut presentation = Presentation::default();
        let mut rect = egui::Rect::NOTHING;
        let run = |events: Vec<egui::Event>,
                   presentation: &mut Presentation,
                   rect: &mut egui::Rect| {
            ctx.run_ui(
                egui::RawInput {
                    screen_rect: Some(egui::Rect::from_min_size(
                        pos2(0.0, 0.0),
                        vec2(900.0, 660.0),
                    )),
                    events,
                    ..Default::default()
                },
                |ui| {
                    let button = instrument_button(ui, presentation, Instrument::Spectrum, true);
                    *rect = button.rect;
                    if button.clicked() {
                        presentation.apply(Action::OpenSingle(Instrument::Spectrum));
                    }
                },
            )
            .drop_without_applying_deltas();
        };
        run(vec![], &mut presentation, &mut rect);
        run(vec![], &mut presentation, &mut rect);
        for _ in 0..2 {
            let pos = rect.center();
            run(
                vec![
                    egui::Event::PointerMoved(pos),
                    egui::Event::PointerButton {
                        pos,
                        button: egui::PointerButton::Primary,
                        pressed: true,
                        modifiers: egui::Modifiers::NONE,
                    },
                ],
                &mut presentation,
                &mut rect,
            );
            run(
                vec![egui::Event::PointerButton {
                    pos,
                    button: egui::PointerButton::Primary,
                    pressed: false,
                    modifiers: egui::Modifiers::NONE,
                }],
                &mut presentation,
                &mut rect,
            );
            assert_eq!(presentation.screen, Screen::Single(Instrument::Spectrum));
        }
        presentation.apply(Action::PairWith(Instrument::Generator));
        let selected = presentation.selected();
        ctx.run_ui(
            egui::RawInput {
                events: vec![egui::Event::PointerMoved(rect.center())],
                ..Default::default()
            },
            |ui| {
                if pane_clicked(ui, rect) {
                    presentation.apply(Action::FocusPane(Instrument::Spectrum));
                }
            },
        )
        .drop_without_applying_deltas();
        assert_eq!(presentation.selected(), selected);
        ctx.run_ui(
            egui::RawInput {
                events: vec![egui::Event::PointerButton {
                    pos: rect.center(),
                    button: egui::PointerButton::Primary,
                    pressed: true,
                    modifiers: egui::Modifiers::NONE,
                }],
                ..Default::default()
            },
            |ui| {
                if pane_clicked(ui, rect) {
                    presentation.apply(Action::FocusPane(Instrument::Spectrum));
                }
            },
        )
        .drop_without_applying_deltas();
        assert_eq!(presentation.selected(), Some(Instrument::Spectrum));
    }
    #[test]
    fn space_in_a_text_editor_does_not_start_shared_input() {
        let ctx = egui::Context::default();
        let mut text = String::new();
        ctx.run_ui(egui::RawInput::default(), |ui| {
            ui.text_edit_singleline(&mut text).request_focus();
        })
        .drop_without_applying_deltas();
        ctx.run_ui(
            egui::RawInput {
                events: vec![egui::Event::Key {
                    key: egui::Key::Space,
                    physical_key: None,
                    pressed: true,
                    repeat: false,
                    modifiers: egui::Modifiers::NONE,
                }],
                ..Default::default()
            },
            |ui| {
                assert!(!input_shortcut(ui.ctx(), true));
                ui.text_edit_singleline(&mut text);
            },
        )
        .drop_without_applying_deltas();
    }

    #[test]
    fn input_space_requires_enabled_transport_and_a_fresh_unmodified_press() {
        for (enabled, modifiers, repeat, expected) in [
            (true, egui::Modifiers::NONE, false, true),
            (false, egui::Modifiers::NONE, false, false),
            (true, egui::Modifiers::CTRL, false, false),
            (true, egui::Modifiers::SHIFT, false, false),
            (true, egui::Modifiers::NONE, true, false),
        ] {
            let ctx = egui::Context::default();
            if repeat {
                // egui derives repetition from the preceding key-down state.
                ctx.run_ui(
                    egui::RawInput {
                        events: vec![egui::Event::Key {
                            key: egui::Key::Space,
                            physical_key: None,
                            pressed: true,
                            repeat: false,
                            modifiers,
                        }],
                        ..Default::default()
                    },
                    |_| {},
                )
                .drop_without_applying_deltas();
            }
            ctx.run_ui(
                egui::RawInput {
                    events: vec![egui::Event::Key {
                        key: egui::Key::Space,
                        physical_key: None,
                        pressed: true,
                        repeat,
                        modifiers,
                    }],
                    ..Default::default()
                },
                |ui| {
                    assert_eq!(
                        input_shortcut(ui.ctx(), enabled),
                        expected,
                        "enabled={enabled}, modifiers={modifiers:?}, repeat={repeat}"
                    );
                    assert!(
                        !input_shortcut(ui.ctx(), enabled),
                        "one key event must not toggle twice"
                    );
                },
            )
            .drop_without_applying_deltas();
        }
    }
}
