//! User-supplied affine channel calibration for Scope numeric readouts.
//! Raw history, trace coordinates, triggers and FFT inputs remain in FS.
use crate::{
    channel::{self, ChannelId, Pair},
    signal::{History, MAX_CHANNELS, Measurement},
};
use std::{ops::Range, sync::Arc};

/// Immutable definition: y [unit] = gain [unit/FS] × x [FS] + offset [unit].
/// An ID/revision identifies these coefficients and their reference conditions;
/// it does not certify the accuracy of the reference or ADC.
#[derive(Clone, Debug, PartialEq)]
pub struct Calibration {
    id: String,
    revision: u64,
    gain: f64,
    offset: f64,
    unit: String,
    conditions: String,
}

impl Calibration {
    pub fn new(
        id: String,
        revision: u64,
        gain: f64,
        offset: f64,
        unit: String,
        conditions: String,
    ) -> Result<Self, &'static str> {
        if !gain.is_finite() || gain == 0.0 || !offset.is_finite() {
            return Err("Gain must be finite and nonzero; offset must be finite");
        }
        if revision == 0 {
            return Err("Calibration revision must be nonzero");
        }
        let id = id.trim().to_owned();
        let unit = unit.trim().to_owned();
        let conditions = conditions.trim().to_owned();
        for (text, limit) in [(&id, 128), (&unit, 24), (&conditions, 1024)] {
            if text.is_empty() || text.len() > limit || text.chars().any(char::is_control) {
                return Err(
                    "ID, unit and reference conditions must be bounded, nonempty single-line text",
                );
            }
        }
        if matches!(unit.as_str(), "FS" | "dBFS") {
            return Err("Use a physical unit for calibration; uncalibrated values use FS");
        }
        Ok(Self {
            id,
            revision,
            gain,
            offset,
            unit,
            conditions,
        })
    }

    pub fn id(&self) -> &str {
        &self.id
    }
    pub fn revision(&self) -> u64 {
        self.revision
    }
    pub fn gain(&self) -> f64 {
        self.gain
    }
    pub fn offset(&self) -> f64 {
        self.offset
    }
    pub fn unit(&self) -> &str {
        &self.unit
    }
    pub fn conditions(&self) -> &str {
        &self.conditions
    }
    pub fn value(&self, raw_fs: f64) -> Option<f64> {
        if !raw_fs.is_finite() {
            return None;
        }
        let value = self.gain.mul_add(raw_fs, self.offset);
        value.is_finite().then_some(value)
    }
}

/// A bounded immutable set keyed by zero-based input channel ID. Cloning into
/// a snapshot only increments an Arc; editing allocates outside acquisition.
#[derive(Clone, Debug, PartialEq)]
pub struct Set(Arc<[Option<Calibration>; MAX_CHANNELS]>);

impl Default for Set {
    fn default() -> Self {
        Self(Arc::new(std::array::from_fn(|_| None)))
    }
}

impl Set {
    pub fn get(&self, channel: ChannelId) -> Option<&Calibration> {
        self.0.get(channel).and_then(Option::as_ref)
    }

    pub fn with(
        &self,
        channel: ChannelId,
        calibration: Option<Calibration>,
    ) -> Result<Self, &'static str> {
        if channel >= MAX_CHANNELS {
            return Err("Calibration channel is outside 1–16");
        }
        if let Some(new) = &calibration
            && self
                .0
                .iter()
                .flatten()
                .any(|old| old.id == new.id && old.revision == new.revision && old != new)
        {
            return Err("An ID/revision must identify a single calibration definition");
        }
        if let (Some(old), Some(new)) = (self.get(channel), &calibration)
            && old.id == new.id
            && old != new
            && new.revision <= old.revision
        {
            return Err("Changed calibration requires a newer revision");
        }
        let mut next = self.0.as_ref().clone();
        next[channel] = calibration;
        Ok(Self(Arc::new(next)))
    }

    pub fn unit(&self, channel: ChannelId) -> &str {
        self.get(channel).map_or("FS", Calibration::unit)
    }

    pub fn value(&self, channel: ChannelId, raw_fs: f64) -> Option<f64> {
        if channel >= MAX_CHANNELS {
            return None;
        }
        match self.get(channel) {
            Some(calibration) => calibration.value(raw_fs),
            None => raw_fs.is_finite().then_some(raw_fs),
        }
    }
}

#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub enum Reading {
    #[default]
    Unavailable,
    /// At least one read value, its calibration, or its P-P is nonfinite.
    /// Do not omit the bad value and report the remaining samples as valid.
    NonFinite,
    Valid(Measurement),
}

/// Apply calibration to each retained f64 sample, before computing statistics.
/// In particular, RMS with an offset cannot be obtained by scaling raw RMS.
/// Missing frames are excluded; the caller retains the interval/loss metadata.
pub fn measure(
    history: &History,
    range: Range<u64>,
    channels: Pair,
    calibrations: &Set,
) -> [Reading; 2] {
    channels.0.map(|channel| {
        if !channel::available(channel, history.channels()) {
            return Reading::Unavailable;
        }
        let mut min = f64::INFINITY;
        let mut max = f64::NEG_INFINITY;
        let mut count = 0;
        // Scaled sum of squares avoids overflow for finite calibrated values
        // whose squares exceed f64, and underflow for very small units.
        let mut scale = 0.0_f64;
        let mut squares = 0.0;
        let range = range.start.max(history.range().start)..range.end.min(history.range().end);
        if range.end <= range.start {
            return Reading::Unavailable;
        }
        for frame in history.samples(range).flatten() {
            let Some(value) = calibrations.value(channel, frame[channel]) else {
                return Reading::NonFinite;
            };
            min = min.min(value);
            max = max.max(value);
            let magnitude = value.abs();
            if magnitude > scale {
                squares = 1.0 + squares * (scale / magnitude).powi(2);
                scale = magnitude;
            } else if magnitude != 0.0 {
                squares += (magnitude / scale).powi(2);
            }
            count += 1;
        }
        if count == 0 {
            Reading::Unavailable
        } else if !(max - min).is_finite() {
            Reading::NonFinite
        } else {
            Reading::Valid(Measurement {
                peak: min.abs().max(max.abs()),
                rms: scale * (squares / count as f64).sqrt(),
                peak_to_peak: max - min,
                samples: count,
            })
        }
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn definition(revision: u64, gain: f64, offset: f64) -> Calibration {
        Calibration::new(
            "reference-ch16".into(),
            revision,
            gain,
            offset,
            "V".into(),
            "Known DC/sine source, ±10 V range, nominal 48 kHz".into(),
        )
        .unwrap()
    }

    #[test]
    fn affine_statistics_use_real_samples_offset_and_signed_gain() {
        let mut history = History::with_channels(4, 16);
        // The retained interval wraps and contains a missing frame.
        for (index, value) in [(0, 7.0), (1, 8.0), (2, -0.5), (3, 0.0), (5, 0.5)] {
            let mut frame = [0.0; 16];
            frame[15] = value;
            history.push_at(index, frame);
        }
        let set = Set::default()
            .with(15, Some(definition(1, -2.0, 1.0)))
            .unwrap();
        // y = [2, 1, missing, 0], not gain × raw RMS + offset.
        let readings = measure(&history, 2..6, Pair([15, 0]), &set);
        let Reading::Valid(m) = readings[0] else {
            panic!("valid calibrated samples")
        };
        assert_eq!(m.samples, 3);
        assert_eq!(m.peak, 2.0);
        assert_eq!(m.peak_to_peak, 2.0);
        assert!((m.rms - (5.0_f64 / 3.0).sqrt()).abs() < 1e-15);
        assert_eq!(set.value(15, -0.5), Some(2.0));
        assert_eq!(set.unit(0), "FS");
        assert_eq!(
            readings[1],
            Reading::Valid(Measurement {
                samples: 3,
                ..Measurement::default()
            })
        );
        assert_eq!(
            measure(&history, 4..5, Pair([15, 16]), &set),
            [Reading::Unavailable; 2]
        );
        let swapped = measure(&history, 2..6, Pair([0, 15]), &set);
        assert_eq!(swapped, [readings[1], readings[0]]);
    }

    #[test]
    fn offset_sine_rms_and_sub_f32_values_keep_f64_precision() {
        let mut history = History::new(1024);
        for index in 0..1024 {
            let sine = 0.25 * (std::f64::consts::TAU * 16.0 * index as f64 / 1024.0).sin();
            history.push([sine, 1.0 + if index % 2 == 0 { 1e-9 } else { -1e-9 }]);
        }
        let set = Set::default()
            .with(0, Some(definition(1, 4.0, 2.0)))
            .unwrap();
        let [Reading::Valid(sine), Reading::Valid(tiny)] =
            measure(&history, 0..1024, Pair::default(), &set)
        else {
            panic!("valid measurements")
        };
        assert!((sine.rms - 4.5_f64.sqrt()).abs() < 1e-14);
        assert!((sine.peak - 3.0).abs() < 1e-14);
        assert!((sine.peak_to_peak - 2.0).abs() < 1e-14);
        assert!((tiny.peak_to_peak - 2e-9).abs() < 2e-16);
        let mut dc = History::new(2);
        dc.push([0.0, 0.0]);
        dc.push([0.0, 0.0]);
        assert_eq!(
            measure(&dc, 0..2, Pair([0, 0]), &set),
            [Reading::Valid(Measurement {
                rms: 2.0,
                peak: 2.0,
                peak_to_peak: 0.0,
                samples: 2
            }); 2]
        );
    }

    #[test]
    fn invalid_definitions_and_revisions_are_rejected_without_mutation() {
        for gain in [0.0, f64::NAN, f64::INFINITY] {
            assert!(
                Calibration::new("id".into(), 1, gain, 0.0, "V".into(), "reference".into())
                    .is_err()
            );
        }
        assert!(
            Calibration::new(
                "id".into(),
                1,
                1.0,
                f64::INFINITY,
                "V".into(),
                "reference".into()
            )
            .is_err()
        );
        assert!(
            Calibration::new("id".into(), 0, 1.0, 0.0, "V".into(), "reference".into()).is_err()
        );
        for unit in ["", "FS", "dBFS", "V\nA", "abcdefghijklmnopqrstuvwxyz"] {
            assert!(
                Calibration::new("id".into(), 1, 1.0, 0.0, unit.into(), "reference".into())
                    .is_err()
            );
        }
        assert!(Calibration::new("id".into(), 1, 1.0, 0.0, "V".into(), "".into()).is_err());
        let original = Set::default()
            .with(15, Some(definition(1, 2.0, 0.0)))
            .unwrap();
        assert!(original.with(16, Some(definition(2, 4.0, 0.0))).is_err());
        assert!(original.with(15, Some(definition(1, 4.0, 0.0))).is_err());
        assert!(original.with(0, Some(definition(1, 4.0, 0.0))).is_err());
        let edited = original.with(15, Some(definition(2, 4.0, 0.0))).unwrap();
        assert_eq!(original.get(15).unwrap().gain(), 2.0);
        assert_eq!(edited.get(15).unwrap().revision(), 2);
        assert_eq!(original.value(16, 0.5), None);
    }

    #[test]
    fn unavailable_and_overflow_are_not_normal_values() {
        let mut history = History::with_channels(4, 1);
        history.push([0.5]);
        history.push([0.5]);
        let extreme = Set::default()
            .with(0, Some(definition(1, 1e200, 0.0)))
            .unwrap();
        let [Reading::Valid(m), Reading::Unavailable] =
            measure(&history, 0..2, Pair::default(), &extreme)
        else {
            panic!("finite RMS despite overflowing squares")
        };
        assert!((m.rms / 5e199 - 1.0).abs() < 1e-15);
        let overflow = Set::default()
            .with(0, Some(definition(1, f64::MAX, f64::MAX)))
            .unwrap();
        assert_eq!(
            measure(&history, 0..2, Pair([0, 0]), &overflow),
            [Reading::NonFinite; 2]
        );
        assert_eq!(overflow.value(0, f64::NAN), None);
        assert_eq!(Set::default().value(0, f64::NAN), None);
        history.push([-0.75]);
        history.push([0.75]);
        let span_overflow = Set::default()
            .with(0, Some(definition(1, f64::MAX, 0.0)))
            .unwrap();
        assert_eq!(
            measure(&history, 2..4, Pair([0, 0]), &span_overflow),
            [Reading::NonFinite; 2]
        );
    }
}
