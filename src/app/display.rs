//! Display-only formatting and acquisition state; never modifies captured values.
use super::*;

pub(super) const AMPLITUDE_HELP: &str = "FS = digital full scale. Waveform and trigger levels use raw FS. RMS / P-P readouts use the captured channel calibration and show their own units.";
pub(super) const SAMPLE_RATE_HELP: &str = "Fs = nominal sample rate in samples/s (Sa/s). Captured time and frequency use this rate; the physical sample clock is not calibrated.";
pub(super) const DIV_HELP: &str = "div = one grid division. ms/div sets time per horizontal division; FS/div sets raw amplitude per vertical division for each Scope channel.";
pub(super) const TRIGGER_HELP: &str = "T at the top marks the time reference (0 ms); T on the right marks the trigger level in raw FS for its source channel. Without a confirmed trigger, both are settings only.";

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
            Self::Stopped => "Input stopped",
            Self::NoDevice => "Select an input source",
            Self::Opening => "Preparing input…",
            Self::Finishing => "Finishing acquisition…",
            Self::WaitingForSamples => "No samples acquired yet",
            Self::WaitingForTrigger => "Waiting for trigger",
            Self::PostTrigger => "Acquiring post-trigger samples…",
            Self::Incomplete => "No complete sweep captured",
            Self::ChannelRange => "Channels outside the input range",
            Self::TriggerRange => "Trigger source outside the input range",
            Self::ChannelsOff => "All Scope channels OFF",
            Self::Failed => "Input acquisition failed",
        }
    }

    fn instruction(self) -> &'static str {
        match self {
            Self::Stopped => {
                "Open input settings to choose the source, then press Start input in the top bar."
            }
            Self::NoDevice => {
                "Open input settings to select or refresh an audio device, or choose Software Loopback. Then press Start input."
            }
            Self::Opening => "Waiting for the input source and its channel count to be ready.",
            Self::Finishing => "Waiting for the final measurement. Acquired data will be retained.",
            Self::WaitingForSamples => {
                "Input is active. Waiting for enough samples to draw a complete sweep."
            }
            Self::WaitingForTrigger => {
                "Input is active. Check the trigger source, level and edge in Scope settings, or use Auto mode."
            }
            Self::PostTrigger => "Input is active. Waiting for the rest of the triggered sweep.",
            Self::Incomplete => {
                "Input stopped before a complete sweep was available. Check Scope settings, then press Start input to acquire again."
            }
            Self::ChannelRange => {
                "Select a channel below the plot and choose its Input source in Scope settings, or change the input source in Audio I/O."
            }
            Self::TriggerRange => {
                "Choose an available trigger source in Scope settings, or change the input source in Audio I/O."
            }
            Self::ChannelsOff => "Turn on a channel using the checkboxes below the plot.",
            Self::Failed => {
                "Check input settings and the acquisition error, then press Start input to try again."
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
        // A real child UI gives the button keyboard/pointer semantics and wraps
        // long source/error names. Its opaque frame masks the grid underneath.
        let size_id = ui.id().with("scope_notice_size");
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
                        egui::Button::new(RichText::new("Open input settings").size(14.0))
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
            return "Input conditions: —".into();
        };
        let captured = !self.history.is_empty() || !self.scope_range.is_empty();
        let (state, _) = activity(self.running(), self.pending_stop.is_some(), captured);
        format!(
            "{state} input · {:.1} kSa/s nominal · {} ch · {}",
            input.nominal_sample_rate_hz as f64 / 1000.0,
            input.channels,
            self.format
        )
    }
}

pub(super) fn activity(running: bool, finishing: bool, captured: bool) -> (&'static str, Color32) {
    if finishing {
        ("FINISHING", YELLOW)
    } else if running {
        if captured {
            ("LIVE", GREEN)
        } else {
            ("WAITING", YELLOW)
        }
    } else if captured {
        ("HELD", HOLD)
    } else {
        ("NOT ACQUIRED", MUTED)
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
        .on_hover_text(
            value
                .filter(|v| v.is_finite())
                .map_or("No valid captured value".into(), |v| {
                    format!("Captured f64: {v:.15e} {unit}")
                }),
        );
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
