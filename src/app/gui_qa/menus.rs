//! I6: open common header menus using painted labels, then retain the real GPU image.
use super::*;
use std::collections::VecDeque;

pub(in crate::app) struct Review {
    target: String,
    path: Vec<&'static str>,
    step: usize,
    events: VecDeque<Vec<egui::Event>>,
    pointer: Option<egui::Pos2>,
    frames: usize,
    ready: bool,
    conditions: Option<measurement::Config>,
    workspace: Option<settings::Workspace>,
    generator: generator::Settings,
    generator_target: output::Target,
    generator_rate: u32,
    locale: i18n::Locale,
    generation: u64,
}

impl Review {
    pub(in crate::app) fn from_env(app: &ScopeApp) -> Result<Option<Self>, String> {
        let Ok(target) = std::env::var("MEASURELAB_UI_SMOKE_HEADER_MENU") else {
            return Ok(None);
        };
        let path = match target.as_str() {
            "root" => vec![],
            "file" => vec![i18n::text("common.file")],
            "view" => vec![i18n::text("shell.view")],
            "audio" => vec![i18n::text("shell.audio_i_o")],
            "analysis" => vec![i18n::text("shell.analysis_status")],
            "scale" => vec![i18n::text("shell.view"), i18n::text("shell.display_scale")],
            "language" => vec![i18n::text("shell.view"), i18n::text("shell.language")],
            _ => return Err(format!("Unknown header menu review: {target}")),
        };
        Ok(Some(Self {
            target,
            path,
            step: 0,
            events: VecDeque::new(),
            pointer: None,
            frames: 0,
            ready: false,
            conditions: None,
            workspace: None,
            generator: app.generator.settings,
            generator_target: app.generator.target.clone(),
            generator_rate: app.generator.rate,
            locale: i18n::locale(),
            generation: app.input_generation,
        }))
    }

    pub(in crate::app) fn input(&mut self, input: &mut egui::RawInput) {
        // An actual desktop pointer must not close or activate a review popup.
        input.events.clear();
        if let Some(events) = self.events.pop_front() {
            input.events = events;
        } else if let Some(pos) = self.pointer {
            input.events.push(egui::Event::PointerMoved(pos));
        } else {
            input.events.push(egui::Event::PointerGone);
        }
        input
            .events
            .insert(0, egui::Event::ModifiersChanged(egui::Modifiers::NONE));
    }

    pub(in crate::app) fn ready(&self) -> bool {
        self.ready
    }

    pub(in crate::app) fn observe(&mut self, app: &ScopeApp, ctx: &egui::Context) {
        self.frames += 1;
        assert!(
            self.ready || self.frames < 180,
            "Header menu did not settle: {}; step {}/{}",
            self.target,
            self.step,
            self.path.len()
        );
        // These cases only inspect stopped input. Opening menus must not issue
        // transport, settings, file-dialog or navigation actions.
        assert!(!app.running() && app.generator.stopped());
        assert!(!app.workspace_pending && app.settings_task.is_none());
        assert_eq!(app.generator.settings, self.generator);
        assert_eq!(app.generator.target, self.generator_target);
        assert_eq!(app.generator.rate, self.generator_rate);
        assert_eq!(i18n::locale(), self.locale);
        assert_eq!(app.input_generation, self.generation);
        let config = app.core_config();
        if let Some(before) = &self.conditions {
            assert_eq!(config.scope, before.scope);
            assert_eq!(config.spectrum, before.spectrum);
            assert_eq!(config.spectrum_channel, before.spectrum_channel);
            assert_eq!(config.spectrum_mode, before.spectrum_mode);
            assert_eq!(config.lockin, before.lockin);
            assert_eq!(config.comparison, before.comparison);
            assert_eq!(config.calibrations, before.calibrations);
            assert_eq!(config.xy_channels, before.xy_channels);
            assert_eq!(config.stft, before.stft);
            assert_eq!(config.stft_generation, before.stft_generation);
            assert_eq!(
                Some(app.capture_workspace()).as_ref(),
                self.workspace.as_ref()
            );
        } else {
            // The compact root is determined from the actual header layout,
            // after native size, zoom and the first layer order have settled.
            if self.frames < 4 {
                return;
            }
            if !painted_text(ctx, i18n::text("shell.menu")).is_empty() {
                self.path.insert(0, i18n::text("shell.menu"));
            } else if !painted_text(ctx, i18n::text("common.file")).is_empty() {
                assert_ne!(self.target, "root", "Root menu requires compact layout");
            } else {
                return;
            }
            self.conditions = Some(config);
            self.workspace = Some(app.capture_workspace());
        }
        if !self.events.is_empty() {
            return;
        }
        if let Some(key) = self.path.get(self.step) {
            // View and the inspector's Display label share a translation in
            // Japanese. The header/popup entry is above the inspector label.
            let Some((pos, _, _)) = painted_text(ctx, key)
                .into_iter()
                .min_by(|a, b| a.0.y.total_cmp(&b.0.y))
            else {
                return;
            };
            self.pointer = Some(pos);
            self.events.push_back(vec![egui::Event::PointerMoved(pos)]);
            for pressed in [true, false] {
                self.events.push_back(vec![
                    egui::Event::PointerMoved(pos),
                    egui::Event::PointerButton {
                        pos,
                        button: egui::PointerButton::Primary,
                        pressed,
                        modifiers: egui::Modifiers::NONE,
                    },
                ]);
            }
            // Allow popup placement, text layout and animation to settle.
            self.events
                .extend((0..8).map(|_| vec![egui::Event::PointerMoved(pos)]));
            self.step += 1;
            return;
        }
        assert!(egui::Popup::is_any_open(ctx));
        let labels: Vec<&str> = match self.target.as_str() {
            "root" => vec![
                i18n::text("common.file"),
                i18n::text("shell.view"),
                i18n::text("shell.audio_i_o"),
                i18n::text("shell.analysis_status"),
            ],
            "file" => vec![
                i18n::text("common.file_paths_status"),
                i18n::text("common.save_settings_2"),
                i18n::text("common.restore_settings_2"),
                i18n::text("common.load_reference_result"),
                i18n::text("common.keep_held_result_as_reference"),
                i18n::text("common.save_held_result_json"),
                i18n::text("common.export_held_result_csv"),
                i18n::text("common.export_annotated_png"),
                i18n::text("common.compare_saved_reference"),
                i18n::text("common.clear_reference"),
            ],
            "view" => vec![
                i18n::text("shell.compact_sidebar"),
                i18n::text("shell.selected_instrument_details"),
                i18n::text("shell.multi_instrument_arrangement"),
                i18n::text("shell.first_pane_share"),
                i18n::text("shell.display_scale"),
                i18n::text("shell.language"),
            ],
            "audio" => vec![
                i18n::text("shell.input_output"),
                i18n::text("shell.calibration"),
            ],
            "analysis" => vec![
                i18n::text("shell.shared_input_stopped"),
                i18n::text("shell.display_selection_does_not_start_or_stop_measurement"),
                i18n::text("shell.stop_lock_in_analysis"),
                i18n::text("shell.stop_synchronous_analysis"),
            ],
            "scale" => vec![],
            "language" => vec![i18n::text("common.language_fallback")],
            _ => unreachable!(),
        };
        for key in labels {
            assert_visible(ctx, key);
        }
        if self.target == "scale" {
            for label in ["75%", "90%", "100%", "110%", "125%", "150%", "175%"] {
                assert_visible(ctx, label);
            }
        }
        if self.target == "language" {
            for locale in i18n::Locale::ALL {
                assert_visible(ctx, locale.native_name());
            }
        }
        if !self.ready {
            println!(
                "Header menu UI OK: {}; locale={}; menu text within clip and viewport; measurement, workspace and output unchanged",
                self.target,
                i18n::locale().id()
            );
            self.ready = true;
        }
    }
}

fn assert_visible(ctx: &egui::Context, label: &str) {
    assert!(
        painted_text(ctx, label)
            .into_iter()
            .any(|(_, bounds, clip)| {
                clip.contains_rect(bounds) && ctx.content_rect().contains_rect(bounds)
            }),
        "Header menu text clipped or missing: {label}"
    );
}

fn painted_text(ctx: &egui::Context, label: &str) -> Vec<(egui::Pos2, egui::Rect, egui::Rect)> {
    let layers: Vec<_> = ctx.memory(|memory| memory.layer_ids().collect());
    ctx.graphics(|graphics| {
        layers
            .into_iter()
            .filter_map(|layer| graphics.get(layer))
            .flat_map(|list| list.all_entries())
            .filter_map(|shape| {
                if let egui::Shape::Text(text) = &shape.shape
                    && text.galley.text() == label
                {
                    let bounds = text.visual_bounding_rect();
                    shape.clip_rect.contains(bounds.center()).then_some((
                        bounds.center(),
                        bounds,
                        shape.clip_rect,
                    ))
                } else {
                    None
                }
            })
            .collect()
    })
}
