//! Fixed instrument order and vector icons, independent of measurement state.
use super::*;

impl ScopeApp {
    pub(super) fn sidebar(&mut self, ui: &mut egui::Ui) {
        let compact = self.shell.sidebar_compact;
        let panel = if compact {
            egui::Panel::left("compact_instrument_list")
                .exact_size(56.0)
                .resizable(false)
        } else {
            egui::Panel::left("instrument_list")
                .default_size(232.0)
                .size_range(228.0..=280.0)
                .resizable(true)
        };
        panel.show(ui, |ui| {
            ui.horizontal(|ui| {
                if !compact {
                    setting_label(ui, i18n::text("shell.instruments_2"));
                }
                ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                    let id = egui::IdSalt::new("sidebar_toggle_icon");
                    let button = egui::Button::new(egui::Atom::custom(id, vec2(18.0, 18.0)))
                        .min_size(vec2(36.0, 30.0))
                        .atom_ui(ui);
                    if let Some(rect) = button.rect(id) {
                        paint_toggle(ui.painter(), rect, compact, ui.visuals().text_color());
                    }
                    let label = if compact {
                        i18n::text("shell.expand_sidebar")
                    } else {
                        i18n::text("shell.compact_sidebar")
                    };
                    button
                        .response
                        .widget_info(|| egui::WidgetInfo::labeled(egui::Role::Button, true, label));
                    #[cfg(feature = "qa")]
                    ui.ctx().data_mut(|data| {
                        data.insert_temp(
                            egui::Id::unique("qa_sidebar_toggle"),
                            button.response.rect,
                        )
                    });
                    if button.response.on_hover_text(label).clicked() {
                        self.shell.sidebar_compact = !compact;
                    }
                });
            });
            egui::ScrollArea::vertical()
                // A filtered/scrolled full list must never hide compact icons.
                .id_salt(if compact {
                    "compact_instrument_scroll"
                } else {
                    "instrument_list_scroll"
                })
                .auto_shrink([false, false])
                .show(ui, |ui| {
                    if !compact {
                        self.instrument_list(ui, false);
                        return;
                    }
                    ui.add_space(6.0);
                    for instrument in Instrument::ALL {
                        if navigation_button(
                            ui,
                            &self.presentation,
                            Some(instrument),
                            self.shell.io.is_none(),
                            self.instrument_navigation_status(instrument, true),
                            true,
                        )
                        .clicked()
                        {
                            self.navigate(Action::OpenSingle(instrument));
                        }
                    }
                    ui.separator();
                    if navigation_button(
                        ui,
                        &self.presentation,
                        None,
                        self.shell.io.is_none(),
                        None,
                        true,
                    )
                    .clicked()
                    {
                        self.navigate(Action::OpenConsole);
                    }
                });
        });
    }
}

pub(super) fn navigation_button(
    ui: &mut egui::Ui,
    presentation: &Presentation,
    instrument: Option<Instrument>,
    active: bool,
    status: Option<NavigationStatus>,
    compact: bool,
) -> egui::Response {
    let screen = instrument.map_or(Screen::Console, Screen::Single);
    let selected = active && presentation.screen == screen;
    let name = instrument.map_or(i18n::text("shell.multi_instrument_view"), |i| {
        i.display_name()
    });
    let color = if selected {
        GREEN
    } else {
        ui.visuals().text_color()
    };
    let icon = egui::IdSalt::new("navigation_icon");
    let atoms = if compact {
        egui::Atoms::new(egui::Atom::custom(icon, vec2(20.0, 20.0)))
    } else {
        egui::Atoms::new((
            egui::Atom::custom(icon, vec2(18.0, 18.0)),
            RichText::new(name).color(color),
        ))
    };
    let mut button = egui::Button::selectable(selected, atoms)
        .min_size(vec2(
            ui.available_width(),
            if compact { 38.0 } else { 30.0 },
        ))
        .corner_radius(5);
    if !compact {
        button =
            button.right_text(status.map_or_else(|| RichText::new(""), NavigationStatus::text));
    }
    let button = button.atom_ui(ui);
    if let Some(rect) = button.rect(icon) {
        paint_instrument(ui.painter(), rect, instrument, color);
    }
    if compact && let Some(status) = status {
        let center = button.response.rect.right_bottom() - vec2(5.0, 5.0);
        ui.painter().circle_filled(center, 3.0, status.1);
    }
    button
        .response
        .widget_info(|| egui::WidgetInfo::selected(egui::Role::Button, true, selected, name));
    #[cfg(feature = "qa")]
    ui.ctx().data_mut(|data| {
        data.insert_temp(
            egui::Id::unique(("qa_navigation", instrument)),
            button.response.rect,
        )
    });
    button.response.on_hover_text(
        status.map_or_else(|| name.to_owned(), |status| format!("{name}\n{}", status.2)),
    )
}

fn paint_toggle(painter: &egui::Painter, rect: egui::Rect, compact: bool, color: Color32) {
    let stroke = Stroke::new(1.5, color);
    painter.rect_stroke(rect.shrink(1.0), 2, stroke, egui::StrokeKind::Inside);
    let p = |x, y| rect.lerp_inside(vec2(x, y));
    painter.line_segment([p(0.3, 0.1), p(0.3, 0.9)], stroke);
    let (tip, tail) = if compact { (0.78, 0.55) } else { (0.5, 0.73) };
    painter.add(egui::Shape::line(
        vec![p(tail, 0.3), p(tip, 0.5), p(tail, 0.7)],
        stroke,
    ));
}

fn paint_instrument(
    painter: &egui::Painter,
    rect: egui::Rect,
    instrument: Option<Instrument>,
    color: Color32,
) {
    let rect = rect.shrink(1.0);
    let stroke = Stroke::new(1.5, color);
    let p = |x, y| rect.lerp_inside(vec2(x, y));
    let line = |points: &[[f32; 2]]| {
        painter.add(egui::Shape::line(
            points.iter().map(|[x, y]| p(*x, *y)).collect(),
            stroke,
        ));
    };
    match instrument {
        Some(Instrument::Scope) => {
            line(&[[0.0, 0.9], [0.0, 0.1]]);
            line(&[
                [0.0, 0.65],
                [0.2, 0.65],
                [0.2, 0.25],
                [0.55, 0.25],
                [0.55, 0.75],
                [0.85, 0.75],
                [0.85, 0.4],
                [1.0, 0.4],
            ]);
        }
        Some(Instrument::Spectrum) => {
            line(&[[0.0, 0.9], [1.0, 0.9]]);
            for (x, h) in [(0.15, 0.65), (0.38, 0.1), (0.62, 0.45), (0.85, 0.65)] {
                line(&[[x, 0.9], [x, h]]);
            }
        }
        Some(Instrument::Spectrogram) => {
            for (x, ys) in [(0.05, [0.1, 0.4]), (0.4, [0.4, 0.7]), (0.75, [0.1, 0.7])] {
                for y in ys {
                    painter.rect_filled(
                        egui::Rect::from_min_max(p(x, y), p(x + 0.2, y + 0.2)),
                        0,
                        color,
                    );
                }
            }
        }
        Some(Instrument::Xy) => {
            painter.add(egui::epaint::EllipseShape::stroke(
                p(0.5, 0.5),
                rect.size() * vec2(0.3, 0.45),
                stroke,
            ));
            line(&[[0.0, 0.5], [1.0, 0.5]]);
            line(&[[0.5, 0.0], [0.5, 1.0]]);
        }
        Some(Instrument::Lockin) => {
            painter.circle_stroke(p(0.5, 0.5), rect.width() * 0.4, stroke);
            line(&[[0.5, 0.85], [0.5, 0.5], [0.8, 0.2]]);
            painter.circle_filled(p(0.5, 0.5), 1.5, color);
        }
        Some(Instrument::Comparison) => {
            line(&[[0.0, 0.3], [0.9, 0.3], [0.65, 0.05]]);
            line(&[[1.0, 0.7], [0.1, 0.7], [0.35, 0.95]]);
        }
        Some(Instrument::Generator) => {
            let points: Vec<_> = (0..=24)
                .map(|n| {
                    let x = n as f32 / 24.0;
                    [x, 0.5 - 0.35 * (x * std::f32::consts::TAU).sin()]
                })
                .collect();
            line(&points);
        }
        None => {
            for x in [0.05, 0.6] {
                for y in [0.05, 0.6] {
                    painter.rect_stroke(
                        egui::Rect::from_min_max(p(x, y), p(x + 0.35, y + 0.35)),
                        1,
                        stroke,
                        egui::StrokeKind::Inside,
                    );
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn compact_status_dots_and_selection_do_not_move_the_icons() {
        let ctx = egui::Context::default();
        let mut positions = None;
        for color in [MUTED, GREEN, YELLOW, TRIGGER] {
            for selected in [Instrument::Scope, Instrument::Generator] {
                let mut rows = Vec::new();
                let presentation = Presentation {
                    screen: Screen::Single(selected),
                    ..Default::default()
                };
                let output = ctx.run_ui(egui::RawInput::default(), |ui| {
                    ui.set_width(40.0);
                    for instrument in Instrument::ALL {
                        rows.push(
                            navigation_button(
                                ui,
                                &presentation,
                                Some(instrument),
                                true,
                                Some(NavigationStatus("", color, "")),
                                true,
                            )
                            .rect,
                        );
                    }
                });
                for rect in &rows {
                    assert!(output.shapes.iter().any(|shape| matches!(&shape.shape,
                        egui::Shape::Circle(circle) if circle.radius == 3.0 && circle.fill == color
                            && circle.center == rect.right_bottom() - vec2(5.0, 5.0))));
                }
                assert!(
                    !output
                        .shapes
                        .iter()
                        .any(|shape| matches!(shape.shape, egui::Shape::Text(_)))
                );
                if let Some(positions) = &positions {
                    assert_eq!(&rows, positions);
                } else {
                    positions = Some(rows);
                }
                output.drop_without_applying_deltas();
            }
        }
    }
}
