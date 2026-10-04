//! Shared observation coordinates, independent of plotting and acquisition.
use std::ops::Range;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct TimeCursor {
    pub epoch: u64,
    pub sample: u64,
}

/// A/B remain at absolute source samples as views move. A new input epoch
/// invalidates both times and frequency, even when sample numbers are reused.
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
            sample,
        });
    }

    pub fn sample(&self, cursor: TimeCursor) -> Option<u64> {
        (cursor.epoch == self.epoch).then_some(cursor.sample)
    }

    pub fn delta_seconds(&self, sample_rate: u32) -> Option<f64> {
        let a = self.sample(self.times[0]?)?;
        let b = self.sample(self.times[1]?)?;
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
        assert_eq!(cursors.delta_seconds(48000), Some(-1.0 / 48000.0));
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
        assert_eq!(cursors.sample(previous), None);
        assert_eq!(cursors.sample(cursors.times[0].unwrap()), Some(123));
        assert!(cursors.frequency_hz.is_none());
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
