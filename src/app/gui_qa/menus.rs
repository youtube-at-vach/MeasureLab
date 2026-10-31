//! I6: open menus and hover real controls, then retain the GPU image.
use super::*;
use std::collections::VecDeque;

mod instruments;
mod scope;
mod spectrum;

enum Step {
    Click(String),
    TypeText(String),
    HoverText(String),
    HoverControl(egui::Id),
    ScrollTo(String),
    ScrollMenuTo(String),
}

struct Case {
    steps: Vec<Step>,
    labels: Vec<String>,
    popup: bool,
    navigation: bool,
    search: Option<String>,
}

pub(in crate::app) struct Review {
    target: String,
    header: bool,
    scope: bool,
    spectrum: bool,
    running: bool,
    output_running: bool,
    held: Option<export::Document>,
    retained_spectrum: Option<spectrum::Retained>,
    progress: (u64, u64, u64),
    case: Case,
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
    command: (u64, u64),
    cursor_times: [Option<cursor::TimeCursor>; 2],
    active_cursor: usize,
    frequencies: [Option<f64>; 2],
}

impl Review {
    pub(in crate::app) fn from_env(app: &mut ScopeApp) -> Result<Option<Self>, String> {
        let header_target = std::env::var("MEASURELAB_UI_SMOKE_HEADER_MENU").ok();
        let instrument_target = std::env::var("MEASURELAB_UI_SMOKE_INSTRUMENT_REVIEW").ok();
        let scope_target = std::env::var("MEASURELAB_UI_SMOKE_SCOPE_REVIEW").ok();
        let spectrum_target = std::env::var("MEASURELAB_UI_SMOKE_SPECTRUM_REVIEW").ok();
        if [
            &header_target,
            &instrument_target,
            &scope_target,
            &spectrum_target,
        ]
        .iter()
        .filter(|target| target.is_some())
        .count()
            > 1
        {
            return Err("Choose only one visual review".into());
        }
        let header = header_target.is_some();
        let scope = scope_target.is_some();
        let spectrum = spectrum_target.is_some();
        let Some(target) = header_target
            .or(instrument_target)
            .or(scope_target)
            .or(spectrum_target)
        else {
            return Ok(None);
        };
        let case = if header {
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
            Case {
                steps: path
                    .into_iter()
                    .map(|text| Step::Click(text.into()))
                    .collect(),
                labels: vec![],
                popup: true,
                navigation: false,
                search: None,
            }
        } else if scope {
            scope::case(app, &target)?
        } else if spectrum {
            spectrum::case(app, &target)?
        } else {
            instruments::case(app, &target)?
        };
        Ok(Some(Self {
            target,
            header,
            scope,
            spectrum,
            running: app.running(),
            output_running: !app.generator.stopped(),
            retained_spectrum: spectrum.then(|| spectrum::Retained::new(app)).transpose()?,
            held: if scope && !app.running() && !app.scope_range.is_empty() {
                Some(app.capture_scope_results()?)
            } else {
                None
            },
            progress: scope::progress(app),
            case,
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
            command: app.generator.command_marker(),
            cursor_times: app.cursors.times,
            active_cursor: app.active_cursor,
            frequencies: app.cursors.spectrum_frequencies_hz,
        }))
    }

    pub(in crate::app) fn input(&mut self, input: &mut egui::RawInput) {
        // An actual desktop pointer must not close or activate a review popup.
        input.events.clear();
        if let Some(events) = self.events.pop_front() {
            input.events = events;
        } else if self.pointer.is_none() {
            input.events.push(egui::Event::PointerGone);
        }
        // Keep the last pointer position without synthesizing more movement:
        // egui restarts its hover delay on every PointerMoved, even at the
        // same coordinate. Native events remain isolated above.
        input
            .events
            .insert(0, egui::Event::ModifiersChanged(egui::Modifiers::NONE));
    }

    pub(in crate::app) fn ready(&self) -> bool {
        self.ready
    }

    pub(in crate::app) fn observe(&mut self, app: &ScopeApp, ctx: &egui::Context) {
        self.frames += 1;
        if self.frames == 1 {
            ctx.send_viewport_cmd(egui::ViewportCommand::Focus);
        }
        if self.frames == 300 && !self.ready {
            eprintln!(
                "Menu review waiting: {}; search={:?}; expected={:?}",
                self.target, app.shell.search, self.case.labels
            );
        }
        assert!(
            self.ready || self.frames < 360,
            "Menu review did not settle: {}; step {}/{}",
            self.target,
            self.step,
            self.case.steps.len()
        );
        // Opening/hovering must not issue transport or measurement commands.
        assert_eq!(app.running(), self.running);
        assert_eq!(!app.generator.stopped(), self.output_running);
        assert!(!app.workspace_pending && app.settings_task.is_none());
        assert_eq!(app.generator.settings, self.generator);
        assert_eq!(app.generator.target, self.generator_target);
        assert_eq!(app.generator.rate, self.generator_rate);
        assert_eq!(i18n::locale(), self.locale);
        assert_eq!(app.input_generation, self.generation);
        assert_eq!(app.generator.command_marker(), self.command);
        assert_eq!(app.cursors.times, self.cursor_times);
        assert_eq!(app.active_cursor, self.active_cursor);
        assert_eq!(app.cursors.spectrum_frequencies_hz, self.frequencies);
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
                if self.header {
                    self.case
                        .steps
                        .insert(0, Step::Click(i18n::text("shell.menu").into()));
                } else if self.case.navigation {
                    let title = app.presentation.selected().map_or_else(
                        || i18n::text("shell.multi_instrument_view").to_owned(),
                        |i| {
                            i18n::format("shell.instrument", &[("name", i.display_name())])
                                .to_string()
                        },
                    );
                    self.case.steps.insert(0, Step::Click(title));
                    self.case
                        .steps
                        .insert(0, Step::Click(i18n::text("shell.menu").into()));
                    self.case.popup = true;
                }
                if !self.header && !self.scope && !self.spectrum {
                    instruments::compact(&mut self.case, &self.target, app);
                }
            } else if !painted_text(ctx, i18n::text("common.file")).is_empty() {
                assert!(
                    !self.header || self.target != "root",
                    "Root menu requires compact layout"
                );
            } else {
                return;
            }
            self.conditions = Some(config);
            self.workspace = Some(app.capture_workspace());
        }
        if !self.events.is_empty() {
            return;
        }
        if let Some(step) = self.case.steps.get(self.step) {
            if let Step::ScrollTo(label) | Step::ScrollMenuTo(label) = step {
                if text_visible(ctx, label) {
                    self.step += 1;
                } else {
                    // Scroll the actual inspector, including the narrow Details page.
                    let pos = if matches!(step, Step::ScrollMenuTo(_)) {
                        self.pointer.expect("Open the popup before scrolling") + vec2(0.0, 40.0)
                    } else {
                        pos2(
                            ctx.content_rect().right() - 80.0,
                            ctx.content_rect().center().y,
                        )
                    };
                    self.events.push_back(vec![
                        egui::Event::PointerMoved(pos),
                        egui::Event::MouseWheel {
                            unit: egui::MouseWheelUnit::Point,
                            phase: egui::TouchPhase::Move,
                            source: egui::MouseWheelSource::Unknown,
                            delta: vec2(0.0, -160.0),
                            modifiers: egui::Modifiers::NONE,
                        },
                    ]);
                    self.events.extend((0..8).map(|_| vec![]));
                }
                return;
            }
            if let Step::TypeText(text) = step {
                self.events.push_back(vec![egui::Event::Text(text.clone())]);
                self.pointer = None;
                self.events.push_back(vec![egui::Event::PointerGone]);
                self.events.extend((0..8).map(|_| vec![]));
                self.step += 1;
                return;
            }
            // View and the inspector's Display label share a translation in
            // Japanese. The header/popup entry is above the inspector label.
            let pos = match step {
                Step::Click(key) | Step::HoverText(key) => {
                    let Some((pos, _, _)) = painted_text(ctx, key)
                        .into_iter()
                        .min_by(|a, b| a.0.y.total_cmp(&b.0.y).then(a.0.x.total_cmp(&b.0.x)))
                    else {
                        return;
                    };
                    pos
                }
                Step::HoverControl(id) => {
                    let Some(rect) = ctx.data(|data| data.get_temp::<egui::Rect>(*id)) else {
                        return;
                    };
                    assert!(ctx.content_rect().contains_rect(rect));
                    rect.center()
                }
                Step::TypeText(_) | Step::ScrollTo(_) | Step::ScrollMenuTo(_) => unreachable!(),
            };
            self.pointer = Some(pos);
            self.events.push_back(vec![egui::Event::PointerMoved(pos)]);
            for pressed in [true, false]
                .into_iter()
                .filter(|_| matches!(step, Step::Click(_)))
            {
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
        if !self.header {
            if let Some(query) = &self.case.search {
                assert_eq!(
                    &app.shell.search, query,
                    "Search editor did not receive text"
                );
            }
            // Hover delay and tooltip placement run in the desktop event loop.
            // Wait for the expected tooltip itself, never accept its source label.
            let hover = self
                .case
                .steps
                .last()
                .is_some_and(|step| matches!(step, Step::HoverText(_) | Step::HoverControl(_)));
            // Smooth scrolling can move a target after its text first becomes
            // visible. Follow that real movement, then leave the pointer still
            // so egui's normal tooltip delay can expire.
            if hover {
                let position = match self.case.steps.last().unwrap() {
                    Step::HoverText(label) => painted_text(ctx, label)
                        .into_iter()
                        .min_by(|a, b| a.0.y.total_cmp(&b.0.y).then(a.0.x.total_cmp(&b.0.x)))
                        .map(|text| text.0),
                    Step::HoverControl(id) => ctx
                        .data(|data| data.get_temp::<egui::Rect>(*id))
                        .map(|rect| rect.center()),
                    _ => unreachable!(),
                };
                if let Some(position) = position
                    && self.pointer.is_some_and(|old| old.distance(position) > 0.5)
                {
                    self.pointer = Some(position);
                    self.events
                        .push_back(vec![egui::Event::PointerMoved(position)]);
                    return;
                }
            }
            if self.case.labels.iter().enumerate().any(|(index, label)| {
                if hover && (self.spectrum || index + 1 == self.case.labels.len()) {
                    !painted_text_on(ctx, label, Some(egui::Order::Tooltip))
                        .into_iter()
                        .any(|(_, bounds, clip)| {
                            clip.contains_rect(bounds) && ctx.content_rect().contains_rect(bounds)
                        })
                } else {
                    !text_visible(ctx, label)
                }
            }) {
                return;
            }
            if self.case.popup {
                assert!(egui::Popup::is_any_open(ctx));
            }
            if self.scope
                && !scope::verify(
                    app,
                    ctx,
                    &self.target,
                    self.running,
                    self.output_running,
                    self.progress,
                    self.held.as_ref(),
                )
            {
                return;
            }
            if self.spectrum
                && !spectrum::verify(
                    app,
                    ctx,
                    &self.target,
                    self.progress,
                    self.retained_spectrum.as_ref().unwrap(),
                )
            {
                return;
            }
            if !self.ready {
                let bounds = self
                    .case
                    .labels
                    .iter()
                    .flat_map(|label| painted_text_on(ctx, label, Some(egui::Order::Tooltip)))
                    .map(|(_, bounds, _)| bounds)
                    .reduce(|a, b| a.union(b));
                if let Some(bounds) = bounds {
                    println!(
                        "Review tooltip bounds: {}",
                        serde_json::json!([
                            bounds.left(),
                            bounds.top(),
                            bounds.right(),
                            bounds.bottom(),
                            ctx.pixels_per_point()
                        ])
                    );
                }
                println!(
                    "{} review UI OK: {}; locale={}; text within clip and viewport; measurement, workspace and output unchanged",
                    if self.scope {
                        "Scope"
                    } else if self.spectrum {
                        "Spectrum"
                    } else {
                        "Instrument"
                    },
                    self.target,
                    i18n::locale().id()
                );
                self.ready = true;
            }
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
        text_visible(ctx, label),
        "Menu review text clipped or missing: {label}"
    );
}

fn text_visible(ctx: &egui::Context, label: &str) -> bool {
    painted_text(ctx, label)
        .into_iter()
        .any(|(_, bounds, clip)| {
            clip.contains_rect(bounds) && ctx.content_rect().contains_rect(bounds)
        })
}

fn painted_text(ctx: &egui::Context, label: &str) -> Vec<(egui::Pos2, egui::Rect, egui::Rect)> {
    painted_text_on(ctx, label, None)
}

fn painted_text_on(
    ctx: &egui::Context,
    label: &str,
    order: Option<egui::Order>,
) -> Vec<(egui::Pos2, egui::Rect, egui::Rect)> {
    let layers: Vec<_> = ctx.memory(|memory| memory.layer_ids().collect());
    ctx.graphics(|graphics| {
        layers
            .into_iter()
            .filter(|layer| order.is_none_or(|order| layer.order == order))
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
