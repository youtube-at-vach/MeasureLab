//! Shared observation coordinates, independent of plotting and acquisition.
use std::ops::Range;

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct TimeCursor {
    pub epoch: u64,
    position: TimePosition,
}

#[derive(Clone, Copy, Debug, PartialEq)]
enum TimePosition {
    Sample(u64),
    ScopeX(f64),
}

impl TimeCursor {
    pub fn scope_x(self) -> Option<f64> {
        match self.position {
            TimePosition::ScopeX(x) => Some(x),
            TimePosition::Sample(_) => None,
        }
    }
}

/// Scope cursors keep their X position as acquisition advances; historical
/// Spectrogram/XY selections keep their source sample. A new input epoch
/// invalidates both types and frequency, even when sample numbers are reused.
#[derive(Default)]
pub struct Cursors {
    epoch: u64,
    pub times: [Option<TimeCursor>; 2],
    pub frequency_hz: Option<f64>,
}

impl Cursors {
    pub fn new_epoch(&mut self) {
        self.epoch = self.epoch.wrapping_add(1);
        self.clear();
    }

    pub fn clear(&mut self) {
        self.times = [None; 2];
        self.frequency_hz = None;
    }

    pub fn set_time(&mut self, index: usize, sample: u64) {
        self.times[index] = Some(TimeCursor {
            epoch: self.epoch,
            position: TimePosition::Sample(sample),
        });
    }

    pub fn set_scope_time(&mut self, index: usize, fraction: f64) {
        if fraction.is_finite() {
            self.times[index] = Some(TimeCursor {
                epoch: self.epoch,
                position: TimePosition::ScopeX(fraction.clamp(0.0, 1.0)),
            });
        }
    }

    pub fn sample(&self, cursor: TimeCursor, scope: Range<u64>) -> Option<u64> {
        if cursor.epoch != self.epoch {
            return None;
        }
        match cursor.position {
            TimePosition::Sample(sample) => Some(sample),
            TimePosition::ScopeX(x) => sample_at_fraction(scope, x),
        }
    }

    pub fn fraction(&self, cursor: TimeCursor, scope: Range<u64>) -> Option<f64> {
        if cursor.epoch != self.epoch {
            return None;
        }
        match cursor.position {
            TimePosition::Sample(sample) => fraction_at_sample(scope, sample),
            TimePosition::ScopeX(x) => Some(x),
        }
    }

    /// Time of the nearest real sample, relative to the sweep's trigger column.
    pub fn scope_seconds(
        &self,
        cursor: TimeCursor,
        scope: Range<u64>,
        sample_rate: u32,
    ) -> Option<f64> {
        let count = scope.end.checked_sub(scope.start)?;
        if count < 2 || sample_rate == 0 {
            return None;
        }
        let sample = self.sample(cursor, scope.clone())?;
        Some(signed_distance(sample, scope.start + count / 5) / sample_rate as f64)
    }

    pub fn delta_seconds(&self, sample_rate: u32, scope: Range<u64>) -> Option<f64> {
        let a = self.sample(self.times[0]?, scope.clone())?;
        let b = self.sample(self.times[1]?, scope)?;
        (sample_rate > 0).then(|| signed_distance(b, a) / sample_rate as f64)
    }
}

/// Subtract integers before converting: adjacent samples beyond 2^53 still
/// have distinct positions, and a cursor before the reference stays negative.
pub fn signed_distance(sample: u64, reference: u64) -> f64 {
    if sample >= reference {
        (sample - reference) as f64
    } else {
        -((reference - sample) as f64)
    }
}

pub fn sample_at_fraction(range: Range<u64>, fraction: f64) -> Option<u64> {
    let count = range.end.checked_sub(range.start)?;
    if count == 0 || !fraction.is_finite() {
        return None;
    }
    let offset = (((count - 1) as f64 * fraction.clamp(0.0, 1.0)).round() as u64).min(count - 1);
    Some(range.start + offset)
}

pub fn fraction_at_sample(range: Range<u64>, sample: u64) -> Option<f64> {
    if !range.contains(&sample) || range.end - range.start < 2 {
        return None;
    }
    Some((sample - range.start) as f64 / (range.end - range.start - 1) as f64)
}

/// Spectrogram rows occupy half-open sample intervals. Age zero selects the
/// last actual sample, never the exclusive window end.
pub fn sample_at_age(end: u64, age_seconds: f64, sample_rate: u32) -> Option<u64> {
    if !age_seconds.is_finite() || age_seconds < 0.0 || sample_rate == 0 {
        return None;
    }
    let offset = age_seconds * sample_rate as f64;
    if offset >= end as f64 {
        return None;
    }
    end.checked_sub(1)?.checked_sub(offset.floor() as u64)
}

pub fn nearest_bin(hz: f64, size: usize, sample_rate: u32) -> Option<usize> {
    if !hz.is_finite() || hz < 0.0 || sample_rate == 0 || size == 0 || hz > sample_rate as f64 * 0.5
    {
        return None;
    }
    Some((hz * size as f64 / sample_rate as f64).round() as usize)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn shared_coordinates_keep_adjacent_large_samples_and_signed_deltas() {
        let start = (1_u64 << 54) + 5;
        let range = start..start + 11;
        assert_eq!(sample_at_fraction(range.clone(), 0.3), Some(start + 3));
        assert_eq!(fraction_at_sample(range.clone(), start + 3), Some(0.3));
        assert_eq!(sample_at_fraction(range.clone(), 1.0), Some(range.end - 1));
        assert_eq!(fraction_at_sample(range.clone(), range.end), None);
        let mut cursors = Cursors::default();
        cursors.set_time(0, start + 4);
        cursors.set_time(1, start + 3);
        assert_eq!(
            cursors.delta_seconds(48000, range.clone()),
            Some(-1.0 / 48000.0)
        );
        assert_eq!(sample_at_age(range.end, 0.0, 48000), Some(range.end - 1));
        assert_eq!(
            sample_at_age(range.end, 1.0 / 48000.0, 48000),
            Some(range.end - 2)
        );
    }

    #[test]
    fn restart_and_source_switch_invalidate_reused_sample_numbers() {
        let mut cursors = Cursors::default();
        cursors.set_time(0, 123);
        let previous = cursors.times[0].unwrap();
        cursors.frequency_hz = Some(1000.0);
        cursors.new_epoch();
        cursors.set_time(0, 123);
        assert_eq!(cursors.sample(previous, 100..200), None);
        assert_eq!(
            cursors.sample(cursors.times[0].unwrap(), 100..200),
            Some(123)
        );
        assert!(cursors.frequency_hz.is_none());
    }

    #[test]
    fn scope_cursors_keep_x_and_read_each_new_sweep_after_history_wraps() {
        use crate::{
            demo::Demo,
            signal::{Edge, History, Trigger},
        };
        let mut demo = Demo::default();
        let mut history = History::new(1024);
        demo.append(&mut history, 1024, 48000);
        let mut cursors = Cursors::default();
        cursors.set_scope_time(0, 0.3);
        cursors.set_scope_time(1, 0.7);
        // Historical selections retain their sample; Scope selections follow
        // the current sweep even after that original sample has been evicted.
        let initial = history.sweep(480, Trigger::default()).range;
        let original = cursors
            .sample(cursors.times[0].unwrap(), initial.clone())
            .unwrap();
        let mut historical = Cursors::default();
        historical.set_time(0, original);
        let expected_delta = cursors.delta_seconds(48000, initial);
        for edge in [Edge::Rising, Edge::Falling, Edge::Free] {
            demo.amplitude = 0.2;
            demo.append(&mut history, 2048, 48000);
            let sweep = history
                .sweep(
                    480,
                    Trigger {
                        edge,
                        ..Trigger::default()
                    },
                )
                .range;
            assert_eq!(cursors.delta_seconds(48000, sweep.clone()), expected_delta);
            for (index, x) in [0.3, 0.7].into_iter().enumerate() {
                let time = cursors.times[index].unwrap();
                assert_eq!(cursors.fraction(time, sweep.clone()), Some(x));
                let sample = cursors.sample(time, sweep.clone()).unwrap();
                assert!(sweep.contains(&sample));
                assert!(sample > original);
                assert!(history.get(sample).unwrap()[0].abs() < 0.3);
            }
            let time = historical.times[0].unwrap();
            assert_eq!(historical.sample(time, sweep.clone()), Some(original));
            assert_eq!(historical.fraction(time, sweep), None);
            assert!(history.get(original).is_none());
        }
    }

    #[test]
    fn scope_coordinates_survive_empty_sweeps_zoom_and_large_sample_ids() {
        let mut cursors = Cursors::default();
        cursors.set_scope_time(0, 0.2);
        cursors.set_scope_time(1, 1.0);
        let a = cursors.times[0].unwrap();
        let b = cursors.times[1].unwrap();
        assert_eq!(cursors.fraction(a, 0..0), Some(0.2));
        assert_eq!(cursors.sample(a, 0..0), None);
        assert_eq!(cursors.scope_seconds(a, 0..0, 48000), None);
        assert_eq!(cursors.delta_seconds(48000, 0..0), None);
        let start = (1_u64 << 54) + 5;
        let scope = start..start + 480;
        assert_eq!(cursors.sample(a, scope.clone()), Some(start + 96));
        assert_eq!(cursors.sample(b, scope.clone()), Some(scope.end - 1));
        assert_eq!(cursors.scope_seconds(a, scope.clone(), 48000), Some(0.0));
        assert_eq!(
            cursors.delta_seconds(48000, scope.clone()),
            Some(383.0 / 48000.0)
        );
        let zoom = start..start + 240;
        assert_eq!(cursors.fraction(a, zoom.clone()), Some(0.2));
        assert_eq!(cursors.sample(a, zoom.clone()), Some(start + 48));
        assert_eq!(cursors.delta_seconds(48000, zoom), Some(191.0 / 48000.0));
        cursors.set_scope_time(0, f64::NAN);
        assert_eq!(cursors.times[0], Some(a));
        cursors.new_epoch();
        assert_eq!(cursors.fraction(a, scope.clone()), None);
        assert_eq!(cursors.sample(a, scope), None);
        assert_eq!(cursors.times, [None; 2]);
    }

    #[test]
    fn invalid_coordinates_and_frequencies_have_no_measurement() {
        assert_eq!(sample_at_fraction(0..0, 0.0), None);
        assert_eq!(sample_at_fraction(0..10, f64::NAN), None);
        assert_eq!(sample_at_age(0, 0.0, 48000), None);
        assert_eq!(sample_at_age(100, 1.0, 48000), None);
        assert_eq!(nearest_bin(24000.0, 1024, 48000), Some(512));
        assert_eq!(nearest_bin(24001.0, 1024, 48000), None);
        assert_eq!(nearest_bin(f64::NAN, 1024, 48000), None);
    }
}
