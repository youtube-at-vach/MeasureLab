//! Application chrome, navigation and console layout; measurement lives in ScopeApp.
use super::*;
use crate::{generator, presentation::PANE_CHROME};

mod language;
mod sidebar;

const HELP_WINDOW: &str = "help_window";
const FILE_PATHS_WINDOW: &str = "file_paths_window";

#[derive(Clone, Copy, Default, PartialEq, Eq)]
pub(super) enum IoTab {
    #[default]
    Connections,
    Calibration,
}

#[derive(Clone, Default)]
pub(super) struct Shell {
    pub io: Option<IoTab>,
    pub help: bool,
    pub file_paths: bool,
    pub search: String,
    pub sidebar_compact: bool,
    pub narrow_details: bool,
    pub separate_io_rates: bool,
    pub previous_console: Option<Console>,
    editor_focused_last_frame: bool,
}

impl Shell {
    const SIDEBAR_KEY: &str = "measurelab.sidebar_compact";

    pub(super) fn from_storage(storage: Option<&dyn eframe::Storage>) -> Self {
        Self {
            sidebar_compact: storage
                .and_then(|storage| storage.get_string(Self::SIDEBAR_KEY))
                .is_some_and(|value| value == "true"),
            ..Self::default()
        }
    }

    pub(super) fn save_sidebar(&self, storage: &mut dyn eframe::Storage) {
        storage.set_string(Self::SIDEBAR_KEY, self.sidebar_compact.to_string());
    }

    pub(super) fn auxiliary_window_open(&self) -> bool {
        self.help || self.file_paths
    }

    fn finish_keyboard_frame(&mut self, ctx: &egui::Context) {
        if self.editor_focused_last_frame || ctx.any_popup_open() {
            // Editors and popups have now handled Escape. Consume it before
            // another layout pass could navigate after focus/menu dismissal.
            ctx.input_mut(|input| input.consume_key(egui::Modifiers::NONE, egui::Key::Escape));
        }
        self.editor_focused_last_frame = ctx.text_edit_focused();
    }

    fn navigation_shortcut(
        &mut self,
        ctx: &egui::Context,
        presentation: &Presentation,
    ) -> Option<Action> {
        if popup_open(ctx) || ctx.text_edit_focused() {
            return None;
        }
        // egui releases editor focus before widgets see Escape. Leave that
        // press to the editor so cancelling a draft cannot also leave its page.
        if self.editor_focused_last_frame && ctx.input(|i| i.key_pressed(egui::Key::Escape)) {
            return None;
        }
        if self.auxiliary_window_open() {
            if fresh_key(ctx, egui::Key::Escape, egui::Modifiers::NONE) {
                let help = egui::Id::new(HELP_WINDOW);
                let paths = egui::Id::new(FILE_PATHS_WINDOW);
                let top = ctx.memory(|memory| {
                    memory
                        .layer_ids()
                        .filter(|layer| {
                            (self.help && layer.id == help)
                                || (self.file_paths && layer.id == paths)
                        })
                        .last()
                });
                if self.file_paths && top.is_some_and(|layer| layer.id == paths) {
                    self.file_paths = false;
                } else if self.help {
                    self.help = false;
                } else {
                    self.file_paths = false;
                }
            }
            return None;
        }
        if fresh_key(ctx, egui::Key::Escape, egui::Modifiers::NONE) {
            self.io = None;
            self.narrow_details = false;
            return None;
        }
        for (instrument, key) in Instrument::ALL.into_iter().zip([
            egui::Key::Num1,
            egui::Key::Num2,
            egui::Key::Num3,
            egui::Key::Num4,
            egui::Key::Num5,
            egui::Key::Num6,
            egui::Key::Num7,
        ]) {
            if fresh_key(ctx, key, egui::Modifiers::CTRL) {
                return Some(Action::OpenSingle(instrument));
            }
        }
        if self.io.is_none() && presentation.screen == Screen::Console {
            let console = &presentation.console;
            let index = console
                .selected
                .and_then(|selected| console.instruments.iter().position(|i| *i == selected))?;
            let step = if fresh_key(ctx, egui::Key::ArrowRight, egui::Modifiers::CTRL) {
                1
            } else if fresh_key(ctx, egui::Key::ArrowLeft, egui::Modifiers::CTRL) {
                -1
            } else {
                return None;
            };
            let index =
                (index as isize + step).rem_euclid(console.instruments.len() as isize) as usize;
            return Some(Action::FocusPane(console.instruments[index]));
        }
        None
    }
}

impl ScopeApp {
    pub(super) fn navigate(&mut self, action: Action) {
        let link_history = self.presentation.screen == Screen::Single(Instrument::Spectrogram)
            && matches!(action, Action::PairWith(Instrument::Spectrum));
        if matches!(
            action,
            Action::OpenSingle(_)
                | Action::PairWith(_)
                | Action::RemoveFromConsole(Instrument::Spectrum | Instrument::Spectrogram)
        ) {
            self.unlink_spectrum_history();
        }
        if matches!(action, Action::PairWith(_))
            && !self.presentation.console.instruments.is_empty()
        {
            self.shell.previous_console = Some(self.presentation.console.clone());
        }
        self.presentation.apply(action);
        if link_history {
            self.link_spectrum_history();
        }
        self.shell.io = None;
        self.shell.narrow_details = false;
    }

    pub(super) fn shell_header(&mut self, ui: &mut egui::Ui) {
        let ctx = ui.ctx().clone();
        if let Some(action) = self.shell.navigation_shortcut(&ctx, &self.presentation) {
            if matches!(action, Action::FocusPane(_)) {
                self.presentation.apply(action);
            } else {
                self.navigate(action);
            }
        }
        egui::Panel::top("header").show(ui, |ui| {
            let compact = ui.available_width() < 1180.0;
            ui.horizontal(|ui| {
                if compact {
                    ui.menu_button(i18n::text("shell.menu"), |ui| self.shell_menus(ui, true));
                } else {
                    self.shell_menus(ui, false);
                }
                ui.allocate_ui_with_layout(
                    vec2(ui.available_width(), ui.spacing().interact_size.y),
                    egui::Layout::right_to_left(egui::Align::Center).with_main_wrap(true),
                    |ui| {
                        self.transport(ui);
                        let state = if self.pending_stop.is_some() {
                            i18n::text("shell.finishing_2")
                        } else if self.busy {
                            i18n::text("shell.opening_2")
                        } else if self.running() {
                            i18n::text("shell.live")
                        } else {
                            i18n::text("shell.stopped_2")
                        };
                        ui.label(
                            RichText::new(format!(
                                "{} · {state}",
                                if compact {
                                    i18n::text("shell.in")
                                } else {
                                    i18n::text("shell.input")
                                }
                            ))
                            .small()
                            .monospace()
                            .color(if self.running() {
                                GREEN
                            } else {
                                MUTED
                            }),
                        )
                        .on_hover_text(
                            i18n::format("shell.shared_input", &[("state", (state))]).as_ref(),
                        );
                        ui.separator();
                        self.generator_transport(ui, compact);
                    },
                );
            });
        });
    }

    fn shell_menus(&mut self, ui: &mut egui::Ui, instruments: bool) {
        self.file_menu(ui);
        self.view_menu(ui);
        ui.menu_button(i18n::text("shell.audio_i_o"), |ui| {
            for (tab, name) in [
                (IoTab::Connections, i18n::text("shell.input_output")),
                (IoTab::Calibration, i18n::text("shell.calibration")),
            ] {
                if ui.button(name).clicked() {
                    self.shell.io = Some(tab);
                    ui.close();
                }
            }
        });
        if ui.button(i18n::text("shell.help")).clicked() {
            self.shell.help = true;
            if ui.layout().is_vertical() {
                ui.close();
            }
        }
        if instruments {
            self.instrument_menu(ui);
        }
        ui.menu_button(i18n::text("shell.analysis_status"), |ui| {
            ui.label(if self.running() {
                i18n::text("shell.scope_spectrum_stft_xy_input_running")
            } else {
                i18n::text("shell.shared_input_stopped")
            });
            ui.label(i18n::text(
                "shell.display_selection_does_not_start_or_stop_measurement",
            ));
            ui.separator();
            let before = self.lockin_settings;
            ui.label(
                i18n::format(
                    "shell.lock_in",
                    &[(
                        "enabled",
                        (self.analysis_state(self.lockin_settings.enabled)),
                    )],
                )
                .as_ref(),
            );
            if ui
                .add_enabled(
                    self.lockin_settings.enabled
                        && !self.busy
                        && self.pending_stop.is_none()
                        && !self.workspace_restoring
                        && self.settings_task != Some(SettingsTask::Restore),
                    egui::Button::new(i18n::text("shell.stop_lock_in_analysis")),
                )
                .clicked()
            {
                self.lockin_settings.enabled = false;
                self.apply_lockin_controls(before);
            }
            let before = self.comparison_settings;
            ui.label(
                i18n::format(
                    "shell.synchronous_ch",
                    &[(
                        "enabled",
                        (self.analysis_state(self.comparison_settings.enabled)),
                    )],
                )
                .as_ref(),
            );
            if ui
                .add_enabled(
                    self.comparison_settings.enabled
                        && !self.busy
                        && self.pending_stop.is_none()
                        && !self.workspace_restoring
                        && self.settings_task != Some(SettingsTask::Restore),
                    egui::Button::new(i18n::text("shell.stop_synchronous_analysis")),
                )
                .clicked()
            {
                self.comparison_settings.enabled = false;
                self.apply_comparison_controls(before);
            }
        });
    }

    pub(super) fn analysis_state(&self, enabled: bool) -> &'static str {
        if !enabled {
            i18n::text("shell.stopped_2")
        } else if self.running() {
            i18n::text("shell.analysis_on")
        } else {
            i18n::text("shell.waiting_for_input")
        }
    }

    fn view_menu(&mut self, ui: &mut egui::Ui) {
        ui.menu_button(i18n::text("shell.view"), |ui| {
            ui.checkbox(
                &mut self.shell.sidebar_compact,
                i18n::text("shell.compact_sidebar"),
            );
            ui.checkbox(
                &mut self.presentation.details_visible,
                i18n::text("shell.selected_instrument_details"),
            );
            ui.separator();
            ui.label(i18n::text("shell.multi_instrument_arrangement"));
            for layout in Layout::ALL {
                if ui
                    .selectable_label(
                        self.presentation.console.layout == layout,
                        layout.display_name(),
                    )
                    .clicked()
                {
                    self.presentation.apply(Action::SetLayout(layout));
                    ui.close();
                }
            }
            ui.add(
                egui::Slider::new(&mut self.presentation.console.split, 0.2..=0.8)
                    .text(i18n::text("shell.first_pane_share")),
            );
            ui.separator();
            ui.menu_button(i18n::text("shell.display_scale"), |ui| {
                let current = ui.ctx().zoom_factor();
                for percent in [75, 90, 100, 110, 125, 150, 175] {
                    let scale = percent as f32 / 100.0;
                    if ui
                        .selectable_label((current - scale).abs() < 0.001, format!("{percent}%"))
                        .clicked()
                    {
                        // Commit after selection, so scaling cannot move an
                        // active control underneath the pointer.
                        ui.ctx().set_zoom_factor(scale);
                        ui.close();
                        egui::Popup::close_all(ui.ctx());
                    }
                }
            });
            language::menu(ui);
        });
    }

    fn instrument_menu(&mut self, ui: &mut egui::Ui) {
        let title = if self.shell.io.is_some() {
            i18n::text("shell.instruments").into()
        } else {
            self.presentation
                .selected()
                .map_or(i18n::text("shell.multi_instrument_view").into(), |i| {
                    i18n::format("shell.instrument", &[("name", (i.display_name()))]).to_string()
                })
        };
        ui.menu_button(title, |ui| self.instrument_list(ui, true));
    }

    fn instrument_list(&mut self, ui: &mut egui::Ui, close_menu: bool) {
        ui.set_min_width(212.0);
        ui.add(
            egui::TextEdit::singleline(&mut self.shell.search)
                .hint_text(i18n::text("shell.find_an_instrument"))
                .desired_width(ui.available_width()),
        );
        let query = self.shell.search.trim().to_lowercase();
        let mut group = "";
        let mut matches = 0;
        for instrument in Instrument::ALL {
            if !format!(
                "{} {}",
                instrument.display_name(),
                instrument.display_purpose()
            )
            .to_lowercase()
            .contains(&query)
            {
                continue;
            }
            matches += 1;
            if group != instrument.group() {
                group = instrument.group();
                ui.add_space(12.0);
                ui.horizontal(|ui| {
                    setting_label(ui, instrument.display_group());
                    if group == Instrument::Scope.group() {
                        ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                            ui.label(self.input_navigation_status().text())
                                .on_hover_text(i18n::text("shell.shared_input_for_scope_spectrum_spectrogram_and_xy_acquisition"));
                        });
                    }
                });
            }
            let status = self.instrument_navigation_status(instrument, false);
            if instrument_button(
                ui,
                &self.presentation,
                instrument,
                self.shell.io.is_none(),
                status,
            )
            .clicked()
            {
                self.navigate(Action::OpenSingle(instrument));
                if close_menu {
                    ui.close();
                }
            }
        }
        if matches == 0 {
            ui.add_space(8.0);
            ui.label(
                RichText::new(i18n::text("shell.no_matching_instruments"))
                    .small()
                    .color(MUTED),
            );
        }
        ui.add_space(12.0);
        ui.separator();
        if sidebar::navigation_button(
            ui,
            &self.presentation,
            None,
            self.shell.io.is_none(),
            None,
            false,
        )
        .clicked()
        {
            self.navigate(Action::OpenConsole);
            if close_menu {
                ui.close();
            }
        }
    }

    fn instrument_navigation_status(
        &self,
        instrument: Instrument,
        compact: bool,
    ) -> Option<NavigationStatus> {
        match instrument {
            Instrument::Generator => Some(self.output_navigation_status()),
            Instrument::Lockin => {
                Some(self.analysis_navigation_status(self.lockin_settings.enabled))
            }
            Instrument::Comparison => {
                Some(self.analysis_navigation_status(self.comparison_settings.enabled))
            }
            _ => compact.then(|| self.input_navigation_status()),
        }
    }

    fn input_navigation_status(&self) -> NavigationStatus {
        if self.pending_stop.is_some() {
            NavigationStatus(
                i18n::text("shell.finishing"),
                YELLOW,
                i18n::text("shell.input_finishing_analysis"),
            )
        } else if self.busy {
            NavigationStatus(
                i18n::text("shell.opening"),
                YELLOW,
                i18n::text("shell.input_opening_device"),
            )
        } else if self.running() {
            NavigationStatus(
                i18n::text("shell.input_live"),
                GREEN,
                i18n::text("shell.shared_input_live"),
            )
        } else {
            NavigationStatus(
                i18n::text("shell.input_stopped"),
                MUTED,
                i18n::text("shell.shared_input_stopped"),
            )
        }
    }

    fn analysis_navigation_status(&self, enabled: bool) -> NavigationStatus {
        if !enabled {
            NavigationStatus(
                i18n::text("shell.off"),
                MUTED,
                i18n::text("shell.analysis_stopped"),
            )
        } else if self.running() {
            NavigationStatus(
                i18n::text("shell.on"),
                GREEN,
                i18n::text("shell.analysis_enabled_input_live"),
            )
        } else {
            NavigationStatus(
                i18n::text("shell.wait"),
                YELLOW,
                i18n::text("shell.analysis_enabled_waiting_for_input"),
            )
        }
    }

    fn output_navigation_status(&self) -> NavigationStatus {
        let g = &self.generator;
        if g.stopping {
            return NavigationStatus(
                i18n::text("shell.stopping"),
                YELLOW,
                i18n::text("shell.output_stopping"),
            );
        }
        if g.starting {
            return NavigationStatus(
                i18n::text("shell.starting"),
                YELLOW,
                i18n::text("shell.output_start_pending"),
            );
        }
        match g.status.state {
            generator::State::Stopped => NavigationStatus(
                i18n::text("shell.stopped"),
                MUTED,
                i18n::text("shell.output_stopped"),
            ),
            generator::State::Starting => NavigationStatus(
                i18n::text("shell.starting"),
                YELLOW,
                i18n::text("shell.output_starting"),
            ),
            generator::State::Running => NavigationStatus(
                i18n::text("shell.running"),
                GREEN,
                i18n::text("shell.output_running"),
            ),
            generator::State::Stopping => NavigationStatus(
                i18n::text("shell.stopping"),
                YELLOW,
                i18n::text("shell.output_stopping"),
            ),
            generator::State::Error(_) => NavigationStatus(
                i18n::text("shell.error"),
                TRIGGER,
                i18n::text("shell.output_error"),
            ),
        }
    }

    pub(super) fn shell_sides(&mut self, ui: &mut egui::Ui) {
        if ui.max_rect().width() < 1180.0 {
            return;
        }
        self.sidebar(ui);
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
            ui.label(i18n::text("shell.add_an_instrument_to_edit_its_details"));
            return;
        };
        ui.heading(if instrument == Instrument::Scope {
            i18n::text("shell.scope_settings")
        } else {
            instrument.display_name()
        });
        ui.separator();
        if self.preferences.loading
            || self.settings_task == Some(SettingsTask::Restore)
            || self.workspace_restoring
        {
            ui.label(i18n::text("shell.restoring_settings"));
            return;
        }
        ui.spacing_mut().slider_width = (ui.available_width() - 140.0).max(75.0);
        match instrument {
            Instrument::Scope => self.scope_controls(ui),
            Instrument::Spectrum => self.spectrum_controls(ui),
            Instrument::Spectrogram => self.spectrogram_controls(ui),
            Instrument::Xy => self.xy_controls(ui),
            Instrument::Lockin => self.lockin_controls(ui),
            Instrument::Comparison => self.comparison_controls(ui),
            Instrument::Generator => self.generator_controls(ui),
        }
    }

    pub(super) fn shell_central(&mut self, ui: &mut egui::Ui) {
        let narrow = ui.max_rect().width() < 1180.0;
        egui::CentralPanel::default().show(ui, |ui| {
            ui.spacing_mut().item_spacing = vec2(6.0, 5.0);
            if let Some(error) = &self.error {
                ui.colored_label(TRIGGER, error);
            }
            if let Some(error) = &self.input_error {
                let notice_shown = self.shell.io.is_none()
                    && !(narrow && self.presentation.details_visible && self.shell.narrow_details)
                    && self.presentation.screen == Screen::Single(Instrument::Scope)
                    && self.scope_notice() == Some(display::ScopeNotice::Failed);
                if !notice_shown {
                    ui.colored_label(TRIGGER, error);
                }
            }
            if let Some(tab) = self.shell.io {
                ui.horizontal_wrapped(|ui| {
                    ui.heading(i18n::text("shell.audio_i_o_settings"));
                    if ui.button(i18n::text("shell.back_to_instruments")).clicked() {
                        self.shell.io = None;
                    }
                    for (t, name) in [
                        (IoTab::Connections, i18n::text("shell.input_output")),
                        (IoTab::Calibration, i18n::text("shell.calibration")),
                    ] {
                        if ui.selectable_label(tab == t, name).clicked() {
                            self.shell.io = Some(t);
                        }
                    }
                });
                egui::ScrollArea::vertical()
                    .id_salt("common_io")
                    .show(ui, |ui| match self.shell.io.unwrap_or(tab) {
                        IoTab::Connections => self.io_controls(ui),
                        IoTab::Calibration => {
                            ui.set_max_width(ui.available_width().min(720.0));
                            self.calibration_controls(ui);
                        }
                    });
                return;
            }
            if narrow && self.presentation.details_visible {
                ui.horizontal(|ui| {
                    ui.selectable_value(
                        &mut self.shell.narrow_details,
                        false,
                        i18n::text("shell.measurement"),
                    );
                    ui.selectable_value(
                        &mut self.shell.narrow_details,
                        true,
                        i18n::text("shell.details"),
                    );
                    if self.shell.narrow_details
                        && let Some(i) = self.presentation.selected()
                    {
                        ui.label(i.display_name());
                    }
                });
                if self.shell.narrow_details {
                    egui::ScrollArea::vertical()
                        .id_salt("narrow_details")
                        .show(ui, |ui| self.selected_details(ui));
                    return;
                }
            }
            match self.presentation.screen {
                Screen::Single(i) => {
                    ui.horizontal_wrapped(|ui| {
                        ui.heading(i.display_name());
                        ui.menu_button(i18n::text("shell.split_view_with"), |ui| {
                            if !self.presentation.console.instruments.is_empty() {
                                ui.label(i18n::text(
                                    "shell.this_replaces_the_saved_multi_instrument_view_use_undo",
                                ));
                                ui.separator();
                            }
                            for other in Instrument::ALL {
                                if other != i && ui.button(other.display_name()).clicked() {
                                    self.navigate(Action::PairWith(other));
                                    ui.close();
                                }
                            }
                        });
                    });
                    let available = ui.available_size();
                    egui::ScrollArea::vertical()
                        .id_salt(("single", i))
                        .auto_shrink([false, false])
                        .show(ui, |ui| {
                            ui.allocate_ui_with_layout(
                                vec2(
                                    ui.available_width().min(available.x),
                                    available.y.max(i.minimum_size()[1]),
                                ),
                                egui::Layout::top_down(egui::Align::Min),
                                |ui| self.draw_instrument(ui, i),
                            );
                        });
                }
                Screen::Console => self.console(ui),
            }
        });
        let ctx = ui.ctx().clone();
        let mut help = self.shell.help;
        egui::Window::new(i18n::text("shell.help"))
            .id(egui::Id::new(HELP_WINDOW))
            .open(&mut help)
            .resizable(true)
            .show(&ctx, |ui| {
                ui.label(i18n::text(
                    "shell.space_start_stop_shared_input_typing_in_an_editor",
                ));
                ui.label(i18n::text(
                    "shell.ctrl_open_an_instrument_ctrl_left_right_select_a",
                ));
                ui.label(i18n::text(
                    "shell.tab_shift_tab_move_keyboard_focus_enter_space_activate",
                ));
                ui.label(i18n::text(
                    "shell.escape_cancel_editing_close_the_front_menu_window_then",
                ));
                ui.label(spectrogram_controls::gestures());
                ui.separator();
                ui.label(display::amplitude_help());
                ui.label(display::sample_rate_help());
                ui.label(display::div_help());
                ui.label(display::trigger_help());
                ui.label(i18n::text(
                    "shell.live_held_waiting_describe_acquisition_validity_and_calibration_are",
                ));
                ui.label(
                    i18n::format(
                        "shell.ui_fps_cpu_fft_ms",
                        &[
                            ("adapter", &(self.adapter).to_string()),
                            ("fps", &format!("{:.0}", self.fps)),
                            ("fft_ms", &format!("{:.2}", self.fft_ms)),
                        ],
                    )
                    .as_ref(),
                );
                egui::CollapsingHeader::new(i18n::text("shell.font_license"))
                    .id_salt("font_license")
                    .show(ui, |ui| {
                        egui::ScrollArea::vertical()
                            .max_height(200.0)
                            .show(ui, |ui| {
                                ui.label(include_str!("../../assets/fonts/OFL.txt"));
                            });
                    });
            });
        self.shell.help = help;
        let mut paths = self.shell.file_paths;
        egui::Window::new(i18n::text("shell.file_paths_status"))
            .id(egui::Id::new(FILE_PATHS_WINDOW))
            .open(&mut paths)
            .default_width(440.0)
            .show(&ctx, |ui| {
                egui::ScrollArea::vertical().show(ui, |ui| self.workspace_controls(ui));
            });
        self.shell.file_paths = paths;
        self.shell.finish_keyboard_frame(&ctx);
    }

    fn console(&mut self, ui: &mut egui::Ui) {
        ui.horizontal_wrapped(|ui| {
            ui.heading(i18n::text("shell.multi_instrument_view"));
            ui.menu_button(i18n::text("shell.add_instrument"), |ui| {
                for i in Instrument::ALL {
                    if ui.button(i.display_name()).clicked() {
                        self.navigate(Action::AddToConsole(i));
                        ui.close();
                    }
                }
            });
            ui.menu_button(i18n::text("shell.arrange_view"), |ui| {
                if ui
                    .add_enabled(
                        self.shell.previous_console.is_some(),
                        egui::Button::new(i18n::text("shell.undo_replacement")),
                    )
                    .clicked()
                    && let Some(previous) = self.shell.previous_console.take()
                {
                    self.presentation.console = previous;
                    self.unlink_spectrum_history();
                    ui.close();
                }
                for layout in Layout::ALL {
                    if ui
                        .selectable_label(
                            self.presentation.console.layout == layout,
                            layout.display_name(),
                        )
                        .clicked()
                    {
                        self.presentation.apply(Action::SetLayout(layout));
                        ui.close();
                    }
                }
            });
        });
        if self.presentation.console.instruments.is_empty() {
            ui.label(i18n::text(
                "shell.add_instruments_to_observe_and_generate_signals_together_removing",
            ));
            return;
        }
        let gap = ui.spacing().item_spacing.x;
        let mut layout = self.presentation.console.effective_layout(
            ui.available_width(),
            ui.available_height(),
            gap,
        );
        // Pane headers select visible instruments; tabs are only needed to
        // reach instruments that cannot be shown together.
        if layout == Layout::Tabs || self.presentation.console.instruments.len() > layout.capacity()
        {
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
            layout = self.presentation.console.effective_layout(
                ui.available_width(),
                ui.available_height(),
                gap,
            );
        }
        if layout == Layout::Tabs
            && self.presentation.console.layout != Layout::Tabs
            && self.presentation.console.instruments.len() > 1
        {
            ui.label(
                RichText::new(i18n::text(
                    "shell.tabs_keep_controls_and_readings_visible_at_this_size",
                ))
                .small()
                .color(MUTED),
            );
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
                                                ui.menu_button("⋯", |ui| {
                                                    if ui
                                                        .button(i18n::text("shell.open_single"))
                                                        .clicked()
                                                    {
                                                        self.navigate(Action::OpenSingle(i));
                                                        ui.close();
                                                    }
                                                    if ui
                                                        .button(i18n::text(
                                                            "shell.remove_from_view",
                                                        ))
                                                        .on_hover_text(i18n::text(
                                                            "shell.analysis_and_output_continue",
                                                        ))
                                                        .clicked()
                                                    {
                                                        self.presentation
                                                            .apply(Action::RemoveFromConsole(i));
                                                        ui.close();
                                                        if matches!(
                                                            i,
                                                            Instrument::Spectrum
                                                                | Instrument::Spectrogram
                                                        ) {
                                                            self.unlink_spectrum_history();
                                                        }
                                                    }
                                                });
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
                                            i.display_name()
                                        );
                                        assert!(
                                            frame.response.rect.height() <= height + 1.0,
                                            "{} exceeds console height: {} > {}",
                                            i.display_name(),
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
                instrument.display_name()
            );
            assert!(
                response.response.rect.width() <= width + 1.0,
                "{} exceeds its pane: {} > {}",
                instrument.display_name(),
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

#[derive(Clone, Copy)]
struct NavigationStatus(&'static str, Color32, &'static str);

impl NavigationStatus {
    fn text(self) -> RichText {
        RichText::new(self.0).small().color(self.1)
    }
}

fn instrument_button(
    ui: &mut egui::Ui,
    presentation: &Presentation,
    instrument: Instrument,
    active: bool,
    status: Option<NavigationStatus>,
) -> egui::Response {
    sidebar::navigation_button(ui, presentation, Some(instrument), active, status, false)
}

fn pane_title(instrument: Instrument, selected: bool) -> String {
    if selected {
        i18n::format("shell.selected", &[("name", (instrument.display_name()))]).to_string()
    } else {
        instrument.display_name().into()
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
    if !enabled || ctx.egui_wants_keyboard_input() || popup_open(ctx) {
        return false;
    }
    fresh_key(ctx, egui::Key::Space, egui::Modifiers::NONE)
}

fn popup_open(ctx: &egui::Context) -> bool {
    // Shortcuts run before menus are drawn. Context reports only popups shown
    // in this pass; Popup also reports the persisted state of shell menus.
    egui::Popup::is_any_open(ctx) || ctx.any_popup_open()
}

fn fresh_key(ctx: &egui::Context, key: egui::Key, modifiers: egui::Modifiers) -> bool {
    let pressed = ctx.input(|input| {
        input.events.iter().any(|event| matches!(event,
            egui::Event::Key { key: event_key, pressed: true, repeat: false, modifiers: event_modifiers, .. }
                if *event_key == key && *event_modifiers == modifiers
        ))
    });
    pressed && ctx.input_mut(|input| input.consume_key(modifiers, key))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn key_event(key: egui::Key, modifiers: egui::Modifiers) -> egui::Event {
        egui::Event::Key {
            key,
            physical_key: None,
            pressed: true,
            repeat: false,
            modifiers,
        }
    }

    #[test]
    fn navigation_requires_a_fresh_press_with_exact_modifiers_and_consumes_it() {
        for (modifiers, repeat, expected) in [
            (egui::Modifiers::CTRL, false, true),
            (egui::Modifiers::CTRL, true, false),
            (egui::Modifiers::CTRL | egui::Modifiers::SHIFT, false, false),
            (egui::Modifiers::CTRL | egui::Modifiers::ALT, false, false),
            (egui::Modifiers::NONE, false, false),
        ] {
            let ctx = egui::Context::default();
            let mut shell = Shell::default();
            let presentation = Presentation::default();
            if repeat {
                ctx.run_ui(
                    egui::RawInput {
                        events: vec![key_event(egui::Key::Num2, modifiers)],
                        ..Default::default()
                    },
                    |_| {},
                )
                .drop_without_applying_deltas();
            }
            ctx.run_ui(
                egui::RawInput {
                    events: vec![key_event(egui::Key::Num2, modifiers)],
                    ..Default::default()
                },
                |ui| {
                    let action = shell.navigation_shortcut(ui.ctx(), &presentation);
                    assert_eq!(
                        matches!(action, Some(Action::OpenSingle(Instrument::Spectrum))),
                        expected
                    );
                    assert!(shell.navigation_shortcut(ui.ctx(), &presentation).is_none());
                },
            )
            .drop_without_applying_deltas();
        }
    }

    #[test]
    fn an_open_menu_blocks_input_and_navigation_before_it_is_drawn() {
        for key in [egui::Key::Space, egui::Key::Num2, egui::Key::Escape] {
            let ctx = egui::Context::default();
            let popup = egui::Id::new("menu");
            egui::Popup::open_id(&ctx, popup);
            let mut shell = Shell {
                io: Some(IoTab::Connections),
                ..Default::default()
            };
            ctx.run_ui(
                egui::RawInput {
                    events: vec![key_event(
                        key,
                        if key == egui::Key::Num2 {
                            egui::Modifiers::CTRL
                        } else {
                            egui::Modifiers::NONE
                        },
                    )],
                    ..Default::default()
                },
                |ui| {
                    assert!(!ui.ctx().any_popup_open(), "menu has not been drawn yet");
                    assert!(!input_shortcut(ui.ctx(), true));
                    assert!(
                        shell
                            .navigation_shortcut(ui.ctx(), &Presentation::default())
                            .is_none()
                    );
                    assert!(matches!(shell.io, Some(IoTab::Connections)));
                    assert!(egui::Popup::is_id_open(ui.ctx(), popup));
                },
            )
            .drop_without_applying_deltas();
        }
    }

    #[test]
    fn escape_leaves_an_editor_before_leaving_its_details_page() {
        let ctx = egui::Context::default();
        let mut shell = Shell {
            narrow_details: true,
            ..Default::default()
        };
        let presentation = Presentation::default();
        let mut text = "draft".to_owned();
        ctx.run_ui(egui::RawInput::default(), |ui| {
            ui.text_edit_singleline(&mut text).request_focus();
            shell.finish_keyboard_frame(ui.ctx());
        })
        .drop_without_applying_deltas();
        assert!(shell.editor_focused_last_frame);
        for (events, expected_details) in [
            (
                vec![key_event(egui::Key::Num2, egui::Modifiers::CTRL)],
                true,
            ),
            (
                vec![key_event(egui::Key::Escape, egui::Modifiers::NONE)],
                true,
            ),
            (
                vec![egui::Event::Key {
                    key: egui::Key::Escape,
                    physical_key: None,
                    pressed: false,
                    repeat: false,
                    modifiers: egui::Modifiers::NONE,
                }],
                true,
            ),
            (
                vec![key_event(egui::Key::Escape, egui::Modifiers::NONE)],
                false,
            ),
        ] {
            ctx.run_ui(
                egui::RawInput {
                    events,
                    ..Default::default()
                },
                |ui| {
                    assert!(shell.navigation_shortcut(ui.ctx(), &presentation).is_none());
                    ui.text_edit_singleline(&mut text);
                    shell.finish_keyboard_frame(ui.ctx());
                    assert_eq!(shell.narrow_details, expected_details);
                },
            )
            .drop_without_applying_deltas();
        }
    }

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
        let run =
            |events: Vec<egui::Event>, presentation: &mut Presentation, rect: &mut egui::Rect| {
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
                        let button =
                            instrument_button(ui, presentation, Instrument::Spectrum, true, None);
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
            // The entire row, including the space to the right of the name,
            // selects the instrument without toggling it off on a second click.
            let pos = pos2(rect.right() - 4.0, rect.center().y);
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
    fn navigation_names_and_status_fit_on_one_line_at_minimum_sidebar_width() {
        let ctx = egui::Context::default();
        ctx.global_style_mut(|style| {
            style.spacing.button_padding = vec2(8.0, 4.0);
        });
        let cases = [
            (
                Instrument::Comparison,
                NavigationStatus("… Wait", YELLOW, ""),
            ),
            (
                Instrument::Generator,
                NavigationStatus("… Starting", YELLOW, ""),
            ),
            (
                Instrument::Generator,
                NavigationStatus("… Stopping", YELLOW, ""),
            ),
            (
                Instrument::Generator,
                NavigationStatus("▶ Running", GREEN, ""),
            ),
        ];
        for width in [212.0, 264.0] {
            let mut rows = Vec::new();
            let mut output = ctx.run_ui(egui::RawInput::default(), |ui| {
                ui.set_width(width);
                for (instrument, status) in cases {
                    let row = instrument_button(
                        ui,
                        &Presentation::default(),
                        instrument,
                        true,
                        Some(status),
                    );
                    rows.push(row.rect);
                }
            });
            output.textures_delta.clear();
            for ((instrument, status), row) in cases.into_iter().zip(rows) {
                assert!((row.width() - width).abs() < 1.0);
                let text_rect = |label: &str| {
                    output
                        .shapes
                        .iter()
                        .find_map(|shape| {
                            if let egui::Shape::Text(text) = &shape.shape
                                && text.galley.text() == label
                                && row.contains(text.pos)
                            {
                                Some(text.visual_bounding_rect())
                            } else {
                                None
                            }
                        })
                        .unwrap_or_else(|| panic!("Missing navigation text: {label}"))
                };
                let name = text_rect(instrument.display_name());
                let state = text_rect(status.0);
                assert!(row.contains_rect(name) && row.contains_rect(state));
                assert!(name.right() + 4.0 <= state.left());
                assert!((name.center().y - state.center().y).abs() < 2.0);
            }
        }
    }

    #[derive(Default)]
    struct MemoryStorage(std::collections::BTreeMap<String, String>);

    impl eframe::Storage for MemoryStorage {
        fn get_string(&self, key: &str) -> Option<String> {
            self.0.get(key).cloned()
        }
        fn set_string(&mut self, key: &str, value: String) {
            self.0.insert(key.into(), value);
        }
        fn remove_string(&mut self, key: &str) {
            self.0.remove(key);
        }
        fn flush(&mut self) {}
    }

    #[test]
    fn sidebar_preference_restores_independently_of_measurement_settings() {
        assert!(!Shell::from_storage(None).sidebar_compact);
        let mut storage = MemoryStorage::default();
        assert!(!Shell::from_storage(Some(&storage)).sidebar_compact);
        for compact in [true, false] {
            let shell = Shell {
                sidebar_compact: compact,
                search: "Spectrum".into(),
                ..Shell::default()
            };
            shell.save_sidebar(&mut storage);
            let restored = Shell::from_storage(Some(&storage));
            assert_eq!(restored.sidebar_compact, compact);
            assert!(restored.search.is_empty() && restored.io.is_none());
            assert_eq!(
                storage.0.len(),
                1,
                "Only the display preference is persisted"
            );
        }
        eframe::Storage::set_string(&mut storage, Shell::SIDEBAR_KEY, "invalid".into());
        assert!(!Shell::from_storage(Some(&storage)).sidebar_compact);
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
