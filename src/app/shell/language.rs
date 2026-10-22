//! Language is a display preference; this widget has no access to ScopeApp.
use crate::i18n;
use eframe::egui;

pub(super) fn menu(ui: &mut egui::Ui) {
    ui.push_id("language_menu", |ui| {
        ui.menu_button(i18n::text("shell.language"), |ui| {
            ui.set_max_width(320.0);
            for locale in i18n::Locale::ALL {
                ui.push_id(locale.id(), |ui| {
                    let response =
                        ui.selectable_label(i18n::locale() == locale, locale.native_name());
                    if response.clicked() {
                        i18n::set_locale(ui.ctx(), locale.id());
                        ui.close();
                        egui::Popup::close_all(ui.ctx());
                    }
                });
            }
            ui.separator();
            ui.add(egui::Label::new(i18n::text("common.language_fallback")).wrap());
        });
    });
}

#[cfg(test)]
mod tests {
    use super::*;

    fn frame(ctx: &egui::Context, events: Vec<egui::Event>) -> egui::FullOutput {
        let mut output = ctx.run_ui(
            egui::RawInput {
                screen_rect: Some(egui::Rect::from_min_size(
                    egui::Pos2::ZERO,
                    egui::vec2(900.0, 660.0),
                )),
                events,
                ..Default::default()
            },
            menu,
        );
        output.textures_delta.clear();
        output
    }

    fn label(ctx: &egui::Context, output: &egui::FullOutput, value: &str) -> egui::Pos2 {
        output
            .shapes
            .iter()
            .rev()
            .find_map(|shape| {
                if let egui::Shape::Text(text) = &shape.shape
                    && text.galley.text() == value
                {
                    let center = text.visual_bounding_rect().center();
                    (shape.clip_rect.contains(center)
                        && ctx
                            .interactive_rects_last_pass()
                            .iter()
                            .any(|rect| rect.contains(center)))
                    .then_some(center)
                } else {
                    None
                }
            })
            .unwrap_or_else(|| panic!("Missing language label: {value}"))
    }

    fn click(ctx: &egui::Context, pos: egui::Pos2) -> egui::FullOutput {
        let event = |pressed| egui::Event::PointerButton {
            pos,
            button: egui::PointerButton::Primary,
            pressed,
            modifiers: egui::Modifiers::NONE,
        };
        frame(ctx, vec![egui::Event::PointerMoved(pos), event(true)]);
        frame(ctx, vec![event(false)])
    }

    #[test]
    fn actual_menu_selects_nine_locales_at_narrow_width_and_zoom() {
        for zoom in [0.75, 1.0, 1.75] {
            let ctx = egui::Context::default();
            i18n::initialize(&ctx, None);
            ctx.set_zoom_factor(zoom);
            for _ in 0..3 {
                frame(&ctx, vec![]);
            }
            for locale in i18n::Locale::ALL {
                let output = frame(&ctx, vec![]);
                let pos = label(&ctx, &output, "Language");
                click(&ctx, pos);
                let output = frame(&ctx, vec![]);
                let pos = label(&ctx, &output, locale.native_name());
                click(&ctx, pos);
                assert_eq!(i18n::locale(), locale);
                frame(&ctx, vec![]);
                assert!(
                    !egui::Popup::is_any_open(&ctx),
                    "zoom={zoom}, locale={locale:?}"
                );
            }
        }
    }
}
