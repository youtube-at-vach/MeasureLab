//! Display-only formatting and acquisition state; never modifies captured values.
use super::*;

pub(super) fn amplitude_help() -> &'static str {
    i18n::text("common.amplitude_help")
}
pub(super) fn sample_rate_help() -> &'static str {
    i18n::text("common.sample_rate_help")
}
pub(super) fn div_help() -> &'static str {
    i18n::text("common.div_help")
}
pub(super) fn trigger_help() -> &'static str {
    i18n::text("common.trigger_help")
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(super) enum ScopeNotice {
    Stopped,
    NoDevice,
    Opening,
    Finishing,
    WaitingForSamples,
    WaitingForTrigger,
    PostTrigger,
    Incomplete,
    ChannelRange,
    TriggerRange,
    ChannelsOff,
    Failed,
}

impl ScopeNotice {
    pub(super) fn title(self) -> &'static str {
        match self {
            Self::Stopped => i18n::text("common.input_stopped"),
            Self::NoDevice => i18n::text("common.select_an_input_source"),
            Self::Opening => i18n::text("common.preparing_input"),
            Self::Finishing => i18n::text("common.finishing_acquisition"),
            Self::WaitingForSamples => i18n::text("common.no_samples_acquired_yet"),
            Self::WaitingForTrigger => i18n::text("common.waiting_for_trigger"),
            Self::PostTrigger => i18n::text("common.acquiring_post_trigger_samples"),
            Self::Incomplete => i18n::text("common.no_complete_sweep_captured"),
            Self::ChannelRange => i18n::text("common.channels_outside_the_input_range"),
            Self::TriggerRange => i18n::text("common.trigger_source_outside_the_input_range"),
            Self::ChannelsOff => i18n::text("common.all_scope_channels_off"),
            Self::Failed => i18n::text("common.input_acquisition_failed"),
        }
    }

    fn instruction(self) -> &'static str {
        match self {
            Self::Stopped => {
                i18n::text("common.open_input_settings_to_choose_the_source_then_press")
            }
            Self::NoDevice => {
                i18n::text("common.open_input_settings_to_select_or_refresh_an_audio")
            }
            Self::Opening => {
                i18n::text("common.waiting_for_the_input_source_and_its_channel_count")
            }
            Self::Finishing => {
                i18n::text("common.waiting_for_the_final_measurement_acquired_data_will_be")
            }
            Self::WaitingForSamples => {
                i18n::text("common.input_is_active_waiting_for_enough_samples_to_draw")
            }
            Self::WaitingForTrigger => {
                i18n::text("common.input_is_active_check_the_trigger_source_level_and")
            }
            Self::PostTrigger => i18n::text("common.input_is_active_waiting_for_the_rest_of_the"),
            Self::Incomplete => {
                i18n::text("common.input_stopped_before_a_complete_sweep_was_available_check")
            }
            Self::ChannelRange => {
                i18n::text("common.select_a_channel_below_the_plot_and_choose_its")
            }
            Self::TriggerRange => {
                i18n::text("common.choose_an_available_trigger_source_in_scope_settings_or")
            }
            Self::ChannelsOff => {
                i18n::text("common.turn_on_a_channel_using_the_checkboxes_below_the")
            }
            Self::Failed => {
                i18n::text("common.check_input_settings_and_the_acquisition_error_then_press")
            }
        }
    }
}

impl ScopeApp {
    pub(super) fn scope_notice(&self) -> Option<ScopeNotice> {
        use ScopeNotice::*;
        // A captured interval remains visible after Stop or failure, including
        // partial/gapped data. A notice must never cover acquired values.
        if !self.scope_range.is_empty() {
            if !self.enabled.iter().any(|enabled| *enabled) {
                return Some(ChannelsOff);
            }
            return self.scope_sources_out_of_range().then_some(ChannelRange);
        }
        if self.input_error.is_some() || self.input_failed {
            return Some(Failed);
        }
        if self.pending_stop.is_some() {
            return Some(Finishing);
        }
        if self.busy {
            return Some(Opening);
        }
        if !self.running() {
            return Some(if !self.history.is_empty() {
                Incomplete
            } else if self.source == Source::Live && self.devices.get(self.selected).is_none() {
                NoDevice
            } else {
                Stopped
            });
        }
        if !self.enabled.iter().any(|enabled| *enabled) {
            return Some(ChannelsOff);
        }
        if self.scope_sources_out_of_range() {
            return Some(ChannelRange);
        }
        let trigger = self.core_scope.trigger;
        if trigger.edge != Edge::Free
            && self
                .scope_input_channels()
                .is_some_and(|count| !channel::available(trigger.channel, count as usize))
        {
            return Some(TriggerRange);
        }
        Some(if self.history.is_empty() {
            WaitingForSamples
        } else if self.core_scope.mode != acquisition::Mode::Auto {
            if self.acquisition_state == acquisition::State::Acquiring {
                PostTrigger
            } else {
                WaitingForTrigger
            }
        } else {
            WaitingForSamples
        })
    }

    fn scope_sources_out_of_range(&self) -> bool {
        self.scope_input_channels().is_some_and(|channels| {
            self.scope_view_channels()
                .0
                .iter()
                .zip(self.enabled)
                .all(|(&source, enabled)| {
                    !enabled || !channel::available(source, channels as usize)
                })
        })
    }

    pub(super) fn scope_notice_ui(&mut self, ui: &mut egui::Ui, rect: egui::Rect) {
        let Some(notice) = self.scope_notice() else {
            return;
        };
        if matches!(
            notice,
            ScopeNotice::Stopped
                | ScopeNotice::Opening
                | ScopeNotice::Finishing
                | ScopeNotice::WaitingForSamples
                | ScopeNotice::WaitingForTrigger
                | ScopeNotice::PostTrigger
        ) {
            // Ordinary acquisition states need no panel or duplicate controls.
            // Paint within the plot without allocating space or intercepting input.
            ui.painter()
                .with_clip_rect(ui.clip_rect().intersect(rect))
                .text(
                    rect.center(),
                    egui::Align2::CENTER_CENTER,
                    notice.title(),
                    egui::FontId::proportional(14.0),
                    MUTED,
                );
            return;
        }
        // A real child UI gives the button keyboard/pointer semantics and wraps
        // long source/error names. Its opaque frame masks the grid underneath.
        let size_id = ui.scope_id().with("scope_notice_size");
        let width = rect.width().clamp(40.0, 466.0);
        let previous_height = ui
            .ctx()
            .data_mut(|data| data.get_temp::<f32>(size_id))
            .unwrap_or(180.0);
        let height = previous_height.min(rect.height());
        let card = egui::Rect::from_center_size(rect.center(), vec2(width, height));
        let mut notice_ui = ui.new_child(
            egui::UiBuilder::new()
                .id_salt("scope_notice")
                .max_rect(card)
                .layout(egui::Layout::top_down(egui::Align::Min)),
        );
        notice_ui.spacing_mut().interact_size.y = 26.0;
        notice_ui.set_clip_rect(ui.clip_rect().intersect(rect));
        let response = egui::Frame::new()
            .fill(Color32::from_rgb(20, 32, 42))
            .stroke(Stroke::new(1.0, BORDER))
            .corner_radius(6.0)
            .inner_margin(12.0)
            .show(&mut notice_ui, |ui| {
                ui.set_width((width - 26.0).max(14.0));
                let button_height = ui.spacing().interact_size.y + ui.spacing().item_spacing.y;
                egui::ScrollArea::vertical()
                    .id_salt("scope_notice_text")
                    .max_height((rect.height() - 26.0 - button_height).max(20.0))
                    .show(ui, |ui| {
                        ui.label(RichText::new(notice.title()).strong().size(18.0));
                        ui.add(
                            egui::Label::new(RichText::new(self.input_source_label()).size(13.0))
                                .wrap(),
                        );
                        ui.add(
                            egui::Label::new(RichText::new(notice.instruction()).size(14.0)).wrap(),
                        );
                        if notice == ScopeNotice::Failed
                            && self.presentation.screen == Screen::Single(Instrument::Scope)
                            && let Some(error) = &self.input_error
                        {
                            ui.add(
                                egui::Label::new(RichText::new(error).size(14.0).color(TRIGGER))
                                    .wrap(),
                            );
                        }
                    });
                if ui
                    .add(
                        egui::Button::new(
                            RichText::new(i18n::text("common.open_input_settings")).size(14.0),
                        )
                        .min_size(vec2(0.0, 26.0)),
                    )
                    .clicked()
                {
                    self.shell.io = Some(shell::IoTab::Connections);
                    self.shell.narrow_details = false;
                }
            })
            .response;
        ui.ctx()
            .data_mut(|data| data.insert_temp(size_id, response.rect.height()));
        if (previous_height - response.rect.height()).abs() > 0.5 {
            ui.ctx().request_repaint();
        }
    }

    pub(super) fn input_status_text(&self) -> String {
        let Some(input) = self
            .held_input
            .as_ref()
            .filter(|input| input.generation == self.input_generation)
        else {
            return i18n::text("common.input_conditions").into();
        };
        let captured = !self.history.is_empty() || !self.scope_range.is_empty();
        let (state, _) = activity(self.running(), self.pending_stop.is_some(), captured);
        i18n::format(
            "common.input_ksa_s_nominal_ch",
            &[
                ("state", (state)),
                (
                    "nominal_sample_rate_hz",
                    &format!("{:.1}", input.nominal_sample_rate_hz as f64 / 1000.0),
                ),
                ("channels", &(input.channels).to_string()),
                ("format", &(self.format).to_string()),
            ],
        )
        .to_string()
    }
}

pub(super) fn activity(running: bool, finishing: bool, captured: bool) -> (&'static str, Color32) {
    if finishing {
        (i18n::text("common.finishing"), YELLOW)
    } else if running {
        if captured {
            (i18n::text("common.live"), GREEN)
        } else {
            (i18n::text("common.waiting"), YELLOW)
        }
    } else if captured {
        (i18n::text("common.held"), HOLD)
    } else {
        (i18n::text("common.not_acquired"), MUTED)
    }
}

pub(super) fn activity_label(ui: &mut egui::Ui, running: bool, finishing: bool, captured: bool) {
    let (text, color) = activity(running, finishing, captured);
    ui.label(RichText::new(text).small().strong().color(color));
}

pub(super) fn number(value: Option<f64>) -> String {
    value.filter(|v| v.is_finite()).map_or("—".into(), |v| {
        if v != 0.0 && !(1e-3..1e6).contains(&v.abs()) {
            format!("{v:.3e}")
        } else {
            format!("{v:.4}")
                .trim_end_matches('0')
                .trim_end_matches('.')
                .to_owned()
        }
    })
}

pub(super) fn metric(
    ui: &mut egui::Ui,
    title: &str,
    value: Option<f64>,
    unit: &str,
    color: Color32,
) {
    ui.vertical(|ui| {
        ui.set_min_width(105.0);
        ui.label(RichText::new(title).small().color(MUTED));
        ui.add(
            egui::Label::new(
                RichText::new(format!("{} {unit}", number(value)))
                    .monospace()
                    .size(18.0)
                    .color(color),
            )
            .wrap(),
        )
        .on_hover_text(value.filter(|v| v.is_finite()).map_or(
            i18n::text("common.no_valid_captured_value").into(),
            |v| {
                i18n::format(
                    "common.captured_f64",
                    &[("v", &format!("{:.15e}", v)), ("unit", (unit))],
                )
                .to_string()
            },
        ));
    });
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn acquisition_state_does_not_claim_an_empty_result_is_held() {
        assert_eq!(activity(false, false, false).0, "NOT ACQUIRED");
        assert_eq!(activity(false, false, true).0, "HELD");
        assert_eq!(activity(true, false, false).0, "WAITING");
        assert_eq!(activity(true, false, true).0, "LIVE");
        assert_eq!(activity(false, true, true).0, "FINISHING");
    }

    #[test]
    fn formatting_distinguishes_weak_values_from_zero_and_invalid_values() {
        assert_eq!(number(Some(1e-12)), "1.000e-12");
        assert_eq!(number(Some(-1e-7)), "-1.000e-7");
        assert_eq!(number(Some(0.0)), "0");
        assert_eq!(number(Some(0.5)), "0.5");
        assert_eq!(number(None), "—");
        assert_eq!(number(Some(f64::NAN)), "—");
    }
}
