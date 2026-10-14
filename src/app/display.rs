//! Display-only formatting and acquisition state; never modifies captured values.
use super::*;

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
