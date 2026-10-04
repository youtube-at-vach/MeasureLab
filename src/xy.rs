//! Synchronous CH 1 / CH 2 trajectories, independent of the desktop UI.
use crate::signal::{History, Line};
use std::ops::Range;

/// Bound geometry and GPU transfers without decimating into false trajectories.
/// At longer windows, show the latest contiguous samples and report the limit.
pub const MAX_POINTS: usize = 32_768;

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Settings {
    pub milliseconds: f64,
    pub x_fs_per_div: f64,
    pub y_fs_per_div: f64,
}

impl Default for Settings {
    fn default() -> Self {
        Self {
            milliseconds: 50.0,
            x_fs_per_div: 0.25,
            y_fs_per_div: 0.25,
        }
    }
}

#[derive(Clone, Debug, Default)]
pub struct Capture {
    pub range: Range<u64>,
    pub limited: bool,
}

/// Select an actual synchronized pair. Resolve overlapping trajectory points
/// to the latest sample, consistently with the latest-window display.
pub fn nearest_sample(
    history: &History,
    range: Range<u64>,
    settings: Settings,
    point: [f64; 2],
) -> Option<u64> {
    if history.channels() < 2
        || range.start < history.range().start
        || range.end > history.range().end
        || range.is_empty()
        || !point.iter().all(|v| v.is_finite())
    {
        return None;
    }
    history
        .samples(range.clone())
        .enumerate()
        .map(|(i, frame)| {
            let x = 0.5 + frame[0] / (settings.x_fs_per_div.max(0.00001) * 8.0);
            let y = 0.5 - frame[1] / (settings.y_fs_per_div.max(0.00001) * 8.0);
            (
                range.start + i as u64,
                (x - point[0]).powi(2) + (y - point[1]).powi(2),
            )
        })
        .min_by(|a, b| a.1.total_cmp(&b.1).then_with(|| b.0.cmp(&a.0)))
        .map(|(sample, _)| sample)
}

/// Each vertex uses both channels of the same frame. History retains only the
/// latest continuous interval, so no connector can cross an acquisition gap.
/// Coordinates are calculated in f64 and converted only at the display boundary.
pub fn build_lines(
    history: &History,
    sample_rate: u32,
    settings: Settings,
    output: &mut Vec<Line>,
) -> Capture {
    output.clear();
    if history.channels() < 2 || history.len() < 2 || sample_rate == 0 {
        return Capture::default();
    }
    let requested = (settings.milliseconds.max(0.0) * sample_rate as f64 / 1000.0)
        .round()
        .max(2.0) as usize;
    let available = requested.min(history.len());
    let count = available.min(MAX_POINTS);
    let end = history.range().end;
    let range = end - count as u64..end;
    let x_scale = settings.x_fs_per_div.max(0.00001) * 8.0;
    let y_scale = settings.y_fs_per_div.max(0.00001) * 8.0;
    let mut previous = None;
    for frame in history.samples(range.clone()) {
        let point = [
            (0.5 + frame[0] / x_scale) as f32,
            (0.5 - frame[1] / y_scale) as f32,
        ];
        if let Some(a) = previous {
            output.push(Line {
                a,
                b: point,
                channel: 0,
            });
        }
        previous = Some(point);
    }
    Capture {
        range,
        limited: available > MAX_POINTS,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::f64::consts::{FRAC_PI_2, PI, TAU};

    #[test]
    fn cursor_selects_actual_pair_and_latest_overlapping_point_with_no_gap_fallback() {
        let mut history = History::new(8);
        for (sequence, pair) in [(100, [0.25, -0.5]), (101, [0.0, 0.0]), (102, [0.25, -0.5])] {
            history.push_at(sequence, pair);
        }
        let settings = Settings::default();
        assert_eq!(
            nearest_sample(&history, 100..103, settings, [0.625, 0.75]),
            Some(102)
        );
        assert_eq!(history.get(102).unwrap(), &[0.25, -0.5]);
        assert_eq!(
            nearest_sample(&history, 100..103, settings, [0.5, 0.5]),
            Some(101)
        );
        history.push_at(200, [0.0, 0.0]);
        assert_eq!(
            nearest_sample(&history, 100..103, settings, [0.5, 0.5]),
            None
        );
        let mut mono = History::with_channels(8, 1);
        mono.push([0.0]);
        assert_eq!(nearest_sample(&mono, 0..1, settings, [0.5, 0.5]), None);
    }

    #[test]
    fn synchronous_phase_signals_form_lines_circles_and_ellipses() {
        for (phase, gain) in [(0.0, 1.0), (PI, 1.0), (FRAC_PI_2, 1.0), (FRAC_PI_2, 0.5)] {
            let mut history = History::with_channels(1024, 16);
            for i in 0..1024 {
                let angle = TAU * i as f64 / 1024.0;
                let mut frame = [9.0; 16];
                frame[0] = angle.sin();
                frame[1] = (angle + phase).sin() * gain;
                history.push(frame);
            }
            let mut lines = Vec::new();
            let capture = build_lines(
                &history,
                1024,
                Settings {
                    milliseconds: 1000.0,
                    ..Settings::default()
                },
                &mut lines,
            );
            assert_eq!(capture.range, 0..1024);
            for point in lines.iter().flat_map(|line| [line.a, line.b]) {
                let x = (point[0] as f64 - 0.5) * 2.0;
                let y = (0.5 - point[1] as f64) * 2.0;
                if phase == 0.0 {
                    assert!((y - x).abs() < 2e-7);
                } else if phase == PI {
                    assert!((y + x).abs() < 2e-7);
                } else {
                    assert!((x * x + (y / gain).powi(2) - 1.0).abs() < 5e-7);
                }
            }
        }
    }

    #[test]
    fn wrap_gaps_and_restart_never_connect_old_frames() {
        let mut history = History::new(4);
        for i in 100..107 {
            history.push_at(i, [i as f64, -(i as f64)]);
        }
        let mut lines = Vec::new();
        let settings = Settings {
            milliseconds: 1000.0,
            ..Settings::default()
        };
        assert_eq!(
            build_lines(&history, 1000, settings, &mut lines).range,
            103..107
        );
        assert_eq!(lines.len(), 3);
        history.push_at(200, [0.1, 0.2]);
        build_lines(&history, 1000, settings, &mut lines);
        assert!(lines.is_empty());
        history.push_at(201, [0.3, 0.4]);
        assert_eq!(
            build_lines(&history, 1000, settings, &mut lines).range,
            200..202
        );
        assert_eq!(lines.len(), 1);
        assert_eq!(lines[0].a, [0.55, 0.4]);
        assert_eq!(lines[0].b, [0.65, 0.3]);
        history.clear_at(0);
        build_lines(&history, 1000, settings, &mut lines);
        assert!(lines.is_empty());
    }

    #[test]
    fn mono_is_unavailable_and_geometry_is_bounded_without_decimation() {
        let mut mono = History::with_channels(4, 1);
        mono.push([1.0]);
        mono.push([2.0]);
        let mut lines = Vec::new();
        build_lines(&mono, 48000, Settings::default(), &mut lines);
        assert!(lines.is_empty());
        let mut history = History::new(MAX_POINTS * 2);
        for i in 0..MAX_POINTS * 2 {
            history.push([i as f64 / MAX_POINTS as f64, 0.0]);
        }
        let settings = Settings {
            milliseconds: 1000.0,
            ..Settings::default()
        };
        let capture = build_lines(&history, 192000, settings, &mut lines);
        assert!(capture.limited);
        assert_eq!(capture.range, MAX_POINTS as u64..(MAX_POINTS * 2) as u64);
        assert_eq!(lines.len(), MAX_POINTS - 1);
        assert!(lines.windows(2).all(|pair| pair[0].b == pair[1].a));
    }

    #[test]
    fn display_changes_reuse_held_samples_with_independent_axes() {
        let mut history = History::new(8);
        history.push([0.25, 0.5]);
        history.push([-0.25, -0.5]);
        let mut lines = Vec::new();
        let range = history.range();
        let settings = Settings {
            x_fs_per_div: 0.125,
            ..Settings::default()
        };
        assert_eq!(
            build_lines(&history, 48000, settings, &mut lines).range,
            range
        );
        assert_eq!(lines[0].a, [0.75, 0.25]);
        assert_eq!(lines[0].b, [0.25, 0.75]);
        assert_eq!(history.range(), range);
    }
}
