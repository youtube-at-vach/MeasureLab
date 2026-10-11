//! Display-only formatting and sample reads. Never feed rounded values back
//! into measurement, calibration, or export.
use crate::{calibration, channel::ChannelId, signal::History};
use std::ops::Range;

/// Five significant digits, with engineering prefixes for unambiguous scalar
/// units. Compound/custom units keep their spelling and use scientific notation.
pub(crate) fn value(value: f64, unit: &str) -> String {
    if !value.is_finite() {
        return "invalid value".into();
    }
    if value == 0.0 {
        return format!("0 {unit}");
    }
    let magnitude = value.abs();
    let prefixable = matches!(unit, "FS" | "V" | "A" | "W" | "Pa" | "Ω" | "Hz" | "s");
    if prefixable && (1e-12..1e12).contains(&magnitude) {
        let mut exponent = ((magnitude.log10() / 3.0).floor() as i32 * 3).clamp(-12, 9);
        let mut scaled = value / 10.0_f64.powi(exponent);
        // Promote after rounding too, so 999.999 Hz becomes 1.0000 kHz.
        if scaled.abs() >= 999.995 {
            exponent += 3;
            scaled = value / 10.0_f64.powi(exponent);
        }
        if exponent <= 9 {
            let prefix = match exponent {
                -12 => "p",
                -9 => "n",
                -6 => "µ",
                -3 => "m",
                0 => "",
                3 => "k",
                6 => "M",
                9 => "G",
                _ => unreachable!(),
            };
            let decimals = (4 - scaled.abs().log10().floor() as i32).clamp(0, 4) as usize;
            return format!("{scaled:.decimals$} {prefix}{unit}");
        }
    }
    format!("{value:.4e} {unit}")
}

pub(crate) fn signed(value: f64, unit: &str) -> String {
    let text = self::value(value, unit);
    if value.is_finite() && value >= 0.0 {
        format!("+{text}")
    } else {
        text
    }
}

pub(crate) fn db(value: f64, unit: &str) -> String {
    if value == f64::NEG_INFINITY {
        format!("−∞ {unit} (zero)")
    } else if value.is_finite() {
        format!("{value:.2} {unit}")
    } else {
        "invalid value".into()
    }
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub(crate) enum Sample {
    Value(f64),
    Outside,
    Missing,
    Unavailable,
    NonFinite,
}

impl Sample {
    pub(crate) fn text(self, unit: &str) -> String {
        match self {
            Self::Value(value) => signed(value, unit),
            Self::Outside => "outside sweep".into(),
            Self::Missing => "missing sample".into(),
            Self::Unavailable => "CH unavailable".into(),
            Self::NonFinite => "invalid value".into(),
        }
    }

    pub(crate) fn difference(self, earlier: Self) -> Self {
        match (self, earlier) {
            (Self::Value(b), Self::Value(a)) if (b - a).is_finite() => Self::Value(b - a),
            (Self::Value(_), Self::Value(_)) => Self::NonFinite,
            (Self::Value(_), invalid) | (invalid, _) => invalid,
        }
    }
}

pub(crate) fn sample(
    history: &History,
    range: Range<u64>,
    sample: u64,
    channel: ChannelId,
    calibration: &calibration::Set,
) -> Sample {
    if !range.contains(&sample) {
        return Sample::Outside;
    }
    if channel >= history.channels() {
        return Sample::Unavailable;
    }
    let Some(frame) = history.get(sample) else {
        return Sample::Missing;
    };
    calibration
        .value(channel, frame[channel])
        .map_or(Sample::NonFinite, Sample::Value)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::calibration::{Calibration, Set};

    #[test]
    fn small_values_signs_and_prefix_boundaries_stay_readable() {
        assert_eq!(value(0.000_000_123_456, "V"), "123.46 nV");
        assert_eq!(value(0.000_012_345_6, "FS"), "12.346 µFS");
        assert_eq!(value(1.0 / 48_000.0, "s"), "20.833 µs");
        assert_eq!(signed(-1.25e-9, "A"), "-1.2500 nA");
        assert_eq!(signed(1.25e-9, "A"), "+1.2500 nA");
        assert_eq!(value(999.999, "Hz"), "1.0000 kHz");
        assert_eq!(value(0.999_999, "V"), "1.0000 V");
        assert_eq!(value(1e-12, "V"), "1.0000 pV");
        assert_eq!(value(0.0, "FS"), "0 FS");
        assert_eq!(value(-0.0, "V"), "0 V");
    }

    #[test]
    fn compound_units_and_f64_extremes_do_not_change_meaning() {
        for unit in ["mV", "V²", "FS²/Hz", "(V)²/Hz", "custom units"] {
            assert_eq!(value(1.25e-6, unit), format!("1.2500e-6 {unit}"));
        }
        assert_eq!(value(f64::from_bits(1), "V"), "4.9407e-324 V");
        assert_eq!(value(f64::MAX, "V"), "1.7977e308 V");
        assert_eq!(value(1e12, "Hz"), "1.0000e12 Hz");
        assert_eq!(value(999.999e9, "Hz"), "1.0000e12 Hz");
        assert_eq!(value(f64::NAN, "V"), "invalid value");
        assert_eq!(value(f64::INFINITY, "V"), "invalid value");
        assert_eq!(db(f64::NEG_INFINITY, "dBFS"), "−∞ dBFS (zero)");
        assert_eq!(db(-150.0, "dBFS"), "-150.00 dBFS");
        assert_eq!(db(f64::NAN, "dBFS"), "invalid value");
    }

    #[test]
    fn cursor_reads_use_captured_calibration_and_reject_invalid_samples() {
        let mut history = History::with_channels(4, 16);
        let mut frame = [0.0; 16];
        frame[15] = 0.25;
        history.push_at(0, frame);
        frame[15] = 0.5;
        history.push_at(2, frame);
        frame[15] = 0.75;
        history.push_at(3, frame);
        let captured = Set::default()
            .with(
                15,
                Some(
                    Calibration::new("id".into(), 1, -2.0, 1.0, "V".into(), "reference".into())
                        .unwrap(),
                ),
            )
            .unwrap();
        let a = sample(&history, 0..4, 0, 15, &captured);
        let b = sample(&history, 0..4, 2, 15, &captured);
        assert_eq!(a, Sample::Value(0.5));
        assert_eq!(b, Sample::Value(0.0));
        assert_eq!(b.difference(a), Sample::Value(-0.5));
        assert_eq!(sample(&history, 2..4, 0, 15, &captured), Sample::Outside);
        assert_eq!(sample(&history, 0..4, 1, 15, &captured), Sample::Missing);
        assert_eq!(
            sample(&history, 0..4, 2, 16, &captured),
            Sample::Unavailable
        );
        let overflow = Set::default()
            .with(
                15,
                Some(
                    Calibration::new(
                        "overflow".into(),
                        1,
                        f64::MAX,
                        f64::MAX,
                        "V".into(),
                        "reference".into(),
                    )
                    .unwrap(),
                ),
            )
            .unwrap();
        assert_eq!(sample(&history, 0..4, 3, 15, &overflow), Sample::NonFinite);
        assert_eq!(Sample::Missing.difference(a), Sample::Missing);
        assert_eq!(b.difference(Sample::Outside), Sample::Outside);
        assert_eq!(
            Sample::Value(f64::MAX).difference(Sample::Value(-f64::MAX)),
            Sample::NonFinite
        );
    }
}
