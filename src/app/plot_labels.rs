//! Keep axis labels legible as console panes and display scales change.
use super::*;

/// Keep the endpoint labels when they fit, then fill available space with
/// intermediate ticks. Grid and data coordinates remain independent of labels.
pub(super) fn horizontal(
    painter: &egui::Painter,
    bounds: egui::Rect,
    ticks: impl IntoIterator<Item = (f32, String)>,
) {
    let mut labels: Vec<_> = ticks
        .into_iter()
        .filter_map(|(x, text)| {
            let galley = painter.layout_no_wrap(text, egui::FontId::monospace(10.0), MUTED);
            let size = galley.size();
            if !x.is_finite() || size.x > bounds.width() || size.y > bounds.height() {
                return None;
            }
            let left = (x - size.x * 0.5).clamp(bounds.left(), bounds.right() - size.x);
            Some((
                egui::Rect::from_min_size(pos2(left, bounds.top()), size),
                galley,
            ))
        })
        .collect();
    if labels.is_empty() {
        return;
    }
    let mut placed = vec![labels.remove(0)];
    // Reserve the far endpoint before placing intermediate labels near it.
    if labels.len() > 1 {
        let last = labels.pop().unwrap();
        if last.0.left() >= placed[0].0.right() + 6.0 {
            placed.push(last);
        }
    }
    for label in labels {
        if placed.iter().all(|(rect, _)| {
            label.0.left() >= rect.right() + 6.0 || label.0.right() + 6.0 <= rect.left()
        }) {
            placed.push(label);
        }
    }
    let painter = painter.with_clip_rect(bounds.intersect(painter.clip_rect()));
    for (rect, galley) in placed {
        painter.galley(rect.min, galley, MUTED);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn actual_text_fits_narrow_axes_without_overlaps_at_different_scales() {
        for scale in [1.0, 1.25, 2.0] {
            for width in [24.0, 90.0, 180.0, 800.0] {
                let ctx = egui::Context::default();
                ctx.set_pixels_per_point(scale);
                let bounds = egui::Rect::from_min_size(pos2(10.0, 10.0), vec2(width, 20.0));
                let output = ctx.run_ui(egui::RawInput::default(), |ui| {
                    horizontal(
                        ui.painter(),
                        bounds,
                        (0..=10).map(|i| {
                            (
                                bounds.left() + width * i as f32 / 10.0,
                                format!("{:.1}", (i as f32 - 2.0) * 100.0),
                            )
                        }),
                    );
                });
                let mut labels: Vec<_> = output
                    .shapes
                    .iter()
                    .filter_map(|s| {
                        if let egui::Shape::Text(text) = &s.shape {
                            Some((text.visual_bounding_rect(), text.galley.text()))
                        } else {
                            None
                        }
                    })
                    .collect();
                labels.sort_by(|a, b| a.0.left().total_cmp(&b.0.left()));
                for (rect, _) in &labels {
                    assert!(
                        bounds.expand(0.5).contains_rect(*rect),
                        "{scale} {width}: {rect:?}"
                    );
                }
                for pair in labels.windows(2) {
                    assert!(pair[0].0.right() + 5.0 <= pair[1].0.left());
                }
                if width >= 90.0 {
                    assert_eq!(labels.first().unwrap().1, "-200.0");
                    assert_eq!(labels.last().unwrap().1, "800.0");
                }
                output.drop_without_applying_deltas();
            }
        }
    }
}
