//! I6b's explicit inventory. Instrument-specific controls belong to I6c/I6d.
use super::*;

pub(super) fn case(app: &mut ScopeApp, target: &str) -> Result<Case, String> {
    let mut case = Case {
        steps: vec![],
        labels: vec![],
        popup: false,
        navigation: false,
        search: None,
    };
    let click = |label: &str| Step::Click(label.into());
    let hover = |label: &str| Step::HoverText(label.into());
    match target {
        "selection" | "selection-filter" | "selection-empty" => {
            case.navigation = true;
            if target == "selection" {
                case.labels
                    .extend(Instrument::ALL.map(|i| i.display_name().into()));
            } else {
                case.steps
                    .push(click(i18n::text("shell.find_an_instrument")));
                let query = if target == "selection-filter" {
                    case.labels.push(Instrument::Spectrum.display_name().into());
                    Instrument::Spectrum.display_name()
                } else {
                    case.labels
                        .push(i18n::text("shell.no_matching_instruments").to_owned());
                    "__i6b_no_match__"
                };
                case.steps.push(Step::TypeText(query.into()));
                case.search = Some(query.into());
            }
            case.labels
                .push(i18n::text("shell.multi_instrument_view").to_owned());
        }
        "split" | "split-replace" => {
            if target == "split-replace" {
                // Retain the paired fixture while showing one instrument.
                assert!(!app.presentation.console.instruments.is_empty());
                app.navigate(Action::OpenSingle(Instrument::Scope));
                case.labels.push(
                    i18n::text("shell.this_replaces_the_saved_multi_instrument_view_use_undo")
                        .to_owned(),
                );
            } else {
                app.presentation.console = Console::default();
                assert!(app.presentation.console.instruments.is_empty());
            }
            case.steps.push(click(i18n::text("shell.split_view_with")));
            case.labels.extend(
                Instrument::ALL
                    .into_iter()
                    .filter(|i| Some(*i) != app.presentation.selected())
                    .map(|i| i.display_name().into()),
            );
            case.popup = true;
        }
        "add" => {
            case.steps.push(click(i18n::text("shell.add_instrument")));
            case.labels
                .extend(Instrument::ALL.map(|i| i.display_name().into()));
            case.popup = true;
        }
        "arrange" | "arrange-undo" => {
            if target == "arrange-undo" {
                // The same retained state created by replacing a console;
                // functional replace/undo events are covered by navigation QA.
                app.shell.previous_console = Some(app.presentation.console.clone());
            }
            case.steps.push(click(i18n::text("shell.arrange_view")));
            case.labels
                .push(i18n::text("shell.undo_replacement").to_owned());
            case.labels
                .extend(Layout::ALL.map(|layout| layout.display_name().into()));
            case.popup = true;
        }
        "pane" | "tooltip-remove" => {
            case.steps.push(Step::Click("⋯".into()));
            case.labels.extend([
                i18n::text("shell.open_single").to_owned(),
                i18n::text("shell.remove_from_view").to_owned(),
            ]);
            if target == "tooltip-remove" {
                case.steps.push(hover(i18n::text("shell.remove_from_view")));
                case.labels
                    .push(i18n::text("shell.analysis_and_output_continue").to_owned());
            }
            case.popup = true;
        }
        "layout" => {
            // Unlike the navigation list, View always belongs to the header.
            case.steps.push(click(i18n::text("shell.view")));
            case.labels
                .extend(Layout::ALL.map(|layout| layout.display_name().into()));
            case.labels
                .push(i18n::text("shell.first_pane_share").to_owned());
            case.popup = true;
        }
        "empty" => {
            app.presentation.console = Console::default();
            assert!(app.presentation.console.instruments.is_empty());
            case.labels.extend([
                i18n::text("shell.add_instrument").to_owned(),
                i18n::text(
                    "shell.add_instruments_to_observe_and_generate_signals_together_removing",
                )
                .to_owned(),
            ]);
        }
        "tooltip-sidebar" => {
            case.steps
                .push(Step::HoverControl(egui::Id::unique("qa_sidebar_toggle")));
            case.labels.push(
                if app.shell.sidebar_compact {
                    i18n::text("shell.expand_sidebar")
                } else {
                    i18n::text("shell.compact_sidebar")
                }
                .into(),
            );
        }
        "tooltip-input-group" => {
            case.navigation = true;
            case.steps.push(hover(i18n::text("shell.input_stopped")));
            case.labels.push(
                i18n::text("shell.shared_input_for_scope_spectrum_spectrogram_and_xy_acquisition")
                    .to_owned(),
            );
        }
        "tooltip-input" => {
            let label = format!(
                "{} · {}",
                i18n::text("shell.input"),
                i18n::text("shell.stopped_2")
            );
            // Replaced with the compact IN prefix at the first native frame.
            case.steps.push(Step::HoverText(label));
            case.labels.push(
                i18n::format(
                    "shell.shared_input",
                    &[("state", i18n::text("shell.stopped_2"))],
                )
                .to_string(),
            );
        }
        "tooltip-start" => {
            case.steps.push(hover(i18n::text("io.start_input")));
            case.labels.push(
                i18n::text("io.start_or_stop_the_shared_input_for_all_instruments").to_owned(),
            );
        }
        "tooltip-output" => {
            case.steps.push(Step::HoverText(format!(
                "{} · {}",
                i18n::text("generator.output"),
                app.generator.label()
            )));
            case.labels.push(
                i18n::format(
                    "generator.hz_ch_input_stop_holds_the_measurement_output_continues",
                    &[
                        ("label", text::output_target(&app.generator.target)),
                        ("rate", &app.generator.rate.to_string()),
                        ("channels", &app.generator.target.channels().to_string()),
                    ],
                )
                .to_string(),
            );
        }
        _ if target.starts_with("tooltip-nav-") => {
            let name = target.trim_start_matches("tooltip-nav-");
            let instrument = match name {
                "scope" => Some(Instrument::Scope),
                "spectrum" => Some(Instrument::Spectrum),
                "spectrogram" => Some(Instrument::Spectrogram),
                "xy" => Some(Instrument::Xy),
                "lockin" => Some(Instrument::Lockin),
                "comparison" => Some(Instrument::Comparison),
                "generator" => Some(Instrument::Generator),
                "console" => None,
                _ => return Err(format!("Unknown navigation tooltip: {name}")),
            };
            case.navigation = true;
            case.steps.push(Step::HoverControl(egui::Id::unique((
                "qa_navigation",
                instrument,
            ))));
            let name = instrument.map_or(i18n::text("shell.multi_instrument_view"), |i| {
                i.display_name()
            });
            let status = match instrument {
                Some(Instrument::Generator) => Some(i18n::text("shell.output_stopped")),
                Some(Instrument::Lockin | Instrument::Comparison) => {
                    let enabled = if instrument == Some(Instrument::Lockin) {
                        app.lockin_settings.enabled
                    } else {
                        app.comparison_settings.enabled
                    };
                    Some(if enabled {
                        i18n::text("shell.analysis_enabled_waiting_for_input")
                    } else {
                        i18n::text("shell.analysis_stopped")
                    })
                }
                Some(_) if app.shell.sidebar_compact => {
                    Some(i18n::text("shell.shared_input_stopped"))
                }
                _ => None,
            };
            case.labels
                .push(status.map_or_else(|| name.into(), |status| format!("{name}\n{status}")));
        }
        _ => return Err(format!("Unknown instrument review: {target}")),
    }
    Ok(case)
}

pub(super) fn compact(case: &mut Case, target: &str, app: &ScopeApp) {
    match target {
        "layout" => case
            .steps
            .insert(0, Step::Click(i18n::text("shell.menu").into())),
        "tooltip-input" => {
            case.steps[0] = Step::HoverText(format!(
                "{} · {}",
                i18n::text("shell.in"),
                i18n::text("shell.stopped_2")
            ))
        }
        "tooltip-output" => {
            case.steps[0] = Step::HoverText(format!(
                "{} · {}",
                i18n::text("generator.out_3"),
                app.generator.label()
            ))
        }
        _ => {}
    }
}
