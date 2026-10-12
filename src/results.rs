//! Bounded, validated reference results; never a command to start acquisition.
use crate::{audio, calibration::Calibration, export::*, spectrum::FFT_SIZES};
use std::{
    fs::File,
    io::{BufWriter, Read, Write},
    path::Path,
};

pub const MAX_BYTES: u64 = 128 * 1024 * 1024;

impl Document {
    pub fn validate(&self) -> Result<(), String> {
        self.validate_header()?;
        audio::validate_sample_rate(self.input.nominal_sample_rate_hz)?;
        match (&self.input.source, &self.generator_output) {
            (Source::Generator, Some(timeline)) if self.input.channels == 2 => {
                timeline.validate(
                    self.input.nominal_sample_rate_hz,
                    self.spectrum
                        .diagnostics
                        .input_end
                        .max(self.retained_history.end),
                )?;
            }
            (Source::Generator, _) | (_, Some(_)) => {
                return Err("Missing or mismatched Generator output conditions".into());
            }
            _ => {}
        }
        if let Source::SoftwareLoopback { settings } = &self.input.source {
            settings.validate(self.input.nominal_sample_rate_hz)?;
        }
        if !(1..=16).contains(&self.input.channels) {
            return Err("Result input requires 1–16 channels".into());
        }
        let range = &self.scope.sample_range;
        if range.end < range.start
            || range.end - range.start > audio::MAX_SAMPLE_RATE as u64 * 2
            || self.scope.observation_samples > audio::MAX_SAMPLE_RATE as usize * 2
            || self.retained_history.end < self.retained_history.start
            || (!range.is_empty()
                && (range.start < self.retained_history.start
                    || range.end > self.retained_history.end))
            || !self.scope.horizontal_sample_offset.is_finite()
            || !self.scope.trigger.level.is_finite()
            || self.scope.trigger.channel >= 16
        {
            return Err("Invalid Scope conditions or interval".into());
        }
        for t in &self.scope.traces {
            if t.channel >= 16 {
                return Err("Invalid Scope channel".into());
            }
            if let Some(samples) = &t.raw_samples_fs {
                if t.channel >= self.input.channels
                    || samples.len() as u64 != range.end - range.start
                    || samples.iter().flatten().any(|v| !v.is_finite())
                    || samples.iter().filter(|v| v.is_none()).count() as u64 != t.missing_samples
                {
                    return Err("Invalid Scope samples or missing count".into());
                }
            } else if t.channel < self.input.channels
                && !range.is_empty()
                && t.state == State::Valid
            {
                return Err("Valid Scope trace has no samples".into());
            }
            validate_calibration(t.calibration.as_ref(), t.channel)?;
            if t.raw_statistics.unit != "FS"
                || t.calibrated_statistics.unit
                    != t.calibration.as_ref().map_or("FS", |c| c.unit.as_str())
            {
                return Err("Scope unit disagrees with calibration".into());
            }
            for stats in [&t.raw_statistics, &t.calibrated_statistics] {
                if stats.unit.len() > 256
                    || stats.acquired_samples > range.end - range.start
                    || stats.values.as_ref().is_some_and(|v| {
                        [v.rms, v.peak, v.peak_to_peak]
                            .iter()
                            .any(|x| !x.is_finite() || *x < 0.0)
                    })
                    || matches!(stats.state, State::Valid | State::Partial)
                        != stats.values.is_some()
                {
                    return Err("Invalid Scope statistics".into());
                }
            }
        }
        let s = &self.spectrum;
        if !FFT_SIZES.contains(&s.settings.size)
            || !(1..=256).contains(&s.settings.averages)
            || s.channel.is_some_and(|ch| ch >= self.input.channels)
            || s.unit.len() > 256
            || !s.bin_width_hz.is_finite()
            || !s.rbw_hz.is_finite()
            || s.bin_width_hz != self.input.nominal_sample_rate_hz as f64 / s.settings.size as f64
            || s.rbw_hz <= 0.0
            || s.requested_band_hz.iter().any(|x| !x.is_finite())
        {
            return Err("Invalid Spectrum conditions".into());
        }
        validate_calibration(s.calibration.as_ref(), s.channel.unwrap_or(0))?;
        let calibration = s.calibration.as_ref().map(|c| {
            Calibration::new(
                c.id.clone(),
                c.revision,
                c.gain,
                c.offset,
                c.unit.clone(),
                c.conditions.clone(),
            )
            .unwrap()
        });
        if s.unit
            != s.settings
                .quantity
                .calibrated_linear_unit(calibration.as_ref())
        {
            return Err("Spectrum unit disagrees with calibration/quantity".into());
        }
        let valid = s.state == State::Valid;
        if valid != s.values.is_some()
            || valid != s.latest_window.is_some()
            || valid != s.average.is_some()
        {
            return Err("Spectrum validity disagrees with data".into());
        }
        if let Some(w) = &s.latest_window
            && (w.end < w.start
                || w.end - w.start != s.settings.size as u64
                || w.end > s.diagnostics.input_end)
        {
            return Err("Invalid Spectrum window".into());
        }
        let bins = s.settings.size / 2 + 1;
        for values in s.values.iter().chain(s.peak_hold.iter().map(|h| &h.values)) {
            if values.len() != bins || values.iter().any(|x| !x.is_finite() || *x < 0.0) {
                return Err("Invalid Spectrum bins".into());
            }
        }
        if let Some(a) = &s.average
            && (a.alpha != 1.0 / s.settings.averages as f64
                || a.processed_windows == 0
                || a.contributing_envelope.end < a.contributing_envelope.start)
        {
            return Err("Invalid Spectrum average".into());
        }
        if let Some(b) = &s.band {
            if s.settings.quantity != crate::spectrum::Quantity::Psd
                || b.inclusive_bins[0] > b.inclusive_bins[1]
                || b.inclusive_bins[1] >= bins
                || [b.power, b.rms].iter().any(|x| !x.is_finite() || *x < 0.0)
                || b.requested_hz
                    .iter()
                    .chain(&b.bin_centres_hz)
                    .any(|x| !x.is_finite())
            {
                return Err("Invalid PSD band".into());
            }
            let values = s.values.as_ref().ok_or("Band without spectrum")?;
            let expected = values[b.inclusive_bins[0]..=b.inclusive_bins[1]]
                .iter()
                .sum::<f64>()
                * s.bin_width_hz;
            if (expected - b.power).abs() > expected.abs() * 1e-12 + 1e-300
                || (b.rms * b.rms - b.power).abs() > b.power.abs() * 1e-12 + 1e-300
            {
                return Err("PSD band disagrees with bins".into());
            }
        }
        if let Some(l) = &self.lockin {
            l.validate(
                self.input.nominal_sample_rate_hz,
                self.input.channels,
                s.diagnostics.input_end,
            )?;
        }
        Ok(())
    }
}

impl Lockin {
    pub(crate) fn validate(
        &self,
        rate: u32,
        channels: usize,
        input_end: u64,
    ) -> Result<(), String> {
        use crate::lockin::State;
        let r = &self.result;
        r.settings.validate(rate)?;
        validate_calibration(
            self.reference_calibration.as_ref(),
            r.settings.reference_channel,
        )?;
        validate_calibration(
            self.response_calibration.as_ref(),
            r.settings.response_channel,
        )?;
        let reference_unit = self
            .reference_calibration
            .as_ref()
            .map_or("FS", |c| c.unit.as_str());
        let response_unit = self
            .response_calibration
            .as_ref()
            .map_or("FS", |c| c.unit.as_str());
        let gain_unit = if reference_unit == response_unit {
            "ratio".into()
        } else {
            format!("{response_unit}/{reference_unit}")
        };
        if self.response_unit_peak != format!("{response_unit} peak")
            || self.gain_unit != gain_unit
            || (r.settings.reference_channel == r.settings.response_channel
                && self.reference_calibration != self.response_calibration)
        {
            return Err("Lock-in units disagree with calibration".into());
        }
        let has_values =
            r.state == State::Valid || (r.state == State::Settling && r.processed_windows > 0);
        let values = [
            r.reference_frequency_hz,
            r.reference_ac_rms_fs,
            r.reference_sinusoid_fraction,
            r.reference_peak,
            r.x,
            r.y,
            r.amplitude_peak,
            r.phase_degrees,
            r.gain,
        ];
        let available =
            r.settings.reference_channel < channels && r.settings.response_channel < channels;
        if r.settings.enabled == (r.state == State::Disabled)
            || (r.settings.enabled && !available && r.state != State::Unavailable)
            || values.iter().any(|v| v.is_some() != has_values)
            || values.iter().flatten().any(|v| !v.is_finite())
            || r.sample_range.end < r.sample_range.start
            || r.latest_window.end < r.latest_window.start
            || r.latest_window.end > input_end
            || (!r.latest_window.is_empty()
                && r.latest_window.end - r.latest_window.start
                    != r.settings.integration_samples as u64)
        {
            return Err("Lock-in state disagrees with values/interval/input endpoint".into());
        }
        if !has_values {
            if r.processed_windows != 0 || r.sample_range != (0..0) {
                return Err("Invalid Lock-in result retains an average".into());
            }
            return Ok(());
        }
        let samples = r.sample_range.end - r.sample_range.start;
        if !available
            || r.processed_windows == 0
            || r.processed_windows
                .checked_mul(r.settings.integration_samples as u64)
                != Some(samples)
            || r.latest_window.is_empty()
            || r.latest_window.end != r.sample_range.end
            || r.latest_window.start < r.sample_range.start
            || (r.state == State::Valid)
                != (samples as f64 >= 10.0 * r.settings.time_constant_seconds * rate as f64)
        {
            return Err("Lock-in average/settling disagrees with complete windows".into());
        }
        let frequency = r.reference_frequency_hz.unwrap();
        let fraction = r.reference_sinusoid_fraction.unwrap();
        let amplitude = r.amplitude_peak.unwrap();
        let x = r.x.unwrap();
        let y = r.y.unwrap();
        let expected_amplitude = x.hypot(y);
        let phase = r.phase_degrees.unwrap();
        if frequency <= 0.0
            || frequency >= rate as f64 / 2.0
            || frequency * r.settings.integration_samples as f64 / (rate as f64) < 3.0
            || (r.settings.track_reference
                && !(r.settings.frequency_hz * 0.9..=r.settings.frequency_hz * 1.1)
                    .contains(&frequency))
            || (!r.settings.track_reference && frequency != r.settings.frequency_hz)
            || r.reference_ac_rms_fs.unwrap() < r.settings.reference_min_rms_fs
            || !(0.98..=1.0).contains(&fraction)
            || r.reference_peak.unwrap() <= 0.0
            || amplitude < 0.0
            || !expected_amplitude.is_finite()
            || r.gain.unwrap() < 0.0
            || !(-180.0..=180.0).contains(&phase)
            || (amplitude - expected_amplitude).abs() > expected_amplitude * 8.0 * f64::EPSILON
            || phase_difference(phase, y.atan2(x).to_degrees()).abs() > 1e-10
        {
            return Err("Lock-in numeric values disagree with REF/peak/phase definitions".into());
        }
        Ok(())
    }
}

/// Differences between settled measurements with matching definitions and calibrations.
/// Independent sample-clock origins are intentionally not aligned.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct LockinDifference {
    pub x: f64,
    pub y: f64,
    pub amplitude_peak: f64,
    pub phase_degrees: f64,
    pub gain: f64,
}

/// Generator comparisons require a known, stationary excitation over each
/// result's entire contributing interval. Other sources retain their own rules.
pub fn matching_excitation(
    reference: &Document,
    reference_range: std::ops::Range<u64>,
    current: &Document,
    current_range: std::ops::Range<u64>,
) -> bool {
    if matches!(reference.input.source, Source::Generator)
        || matches!(current.input.source, Source::Generator)
    {
        let a_condition = reference
            .generator_output
            .as_ref()
            .and_then(|t| t.stationary(reference_range));
        let b_condition = current
            .generator_output
            .as_ref()
            .and_then(|t| t.stationary(current_range));
        return matches!((a_condition, b_condition), (Some(a), Some(b)) if a.same_excitation(b));
    }
    true
}

pub fn lockin_difference(reference: &Document, current: &Document) -> Option<LockinDifference> {
    let a = reference.lockin.as_ref()?;
    let b = current.lockin.as_ref()?;
    if !matching_excitation(
        reference,
        a.result.sample_range.clone(),
        current,
        b.result.sample_range.clone(),
    ) {
        return None;
    }
    if reference.loss.input_failed
        || current.loss.input_failed
        || reference.input.nominal_sample_rate_hz != current.input.nominal_sample_rate_hz
        || a.result.state != crate::lockin::State::Valid
        || b.result.state != crate::lockin::State::Valid
        || a.result.settings != b.result.settings
        || a.reference_calibration != b.reference_calibration
        || a.response_calibration != b.response_calibration
        || a.response_unit_peak != b.response_unit_peak
        || a.gain_unit != b.gain_unit
    {
        return None;
    }
    Some(LockinDifference {
        x: b.result.x? - a.result.x?,
        y: b.result.y? - a.result.y?,
        amplitude_peak: b.result.amplitude_peak? - a.result.amplitude_peak?,
        phase_degrees: phase_difference(b.result.phase_degrees?, a.result.phase_degrees?),
        gain: b.result.gain? - a.result.gain?,
    })
}

fn phase_difference(current: f64, reference: f64) -> f64 {
    (current - reference + 180.0).rem_euclid(360.0) - 180.0
}

fn validate_calibration(
    c: Option<&crate::settings::ChannelCalibration>,
    channel: usize,
) -> Result<(), String> {
    if let Some(c) = c {
        if c.channel != channel {
            return Err("Calibration channel disagrees with result".into());
        }
        Calibration::new(
            c.id.clone(),
            c.revision,
            c.gain,
            c.offset,
            c.unit.clone(),
            c.conditions.clone(),
        )
        .map_err(str::to_owned)?;
    }
    Ok(())
}

pub fn load(path: &Path) -> Result<Document, String> {
    let file = File::open(path).map_err(|e| e.to_string())?;
    if file.metadata().map_err(|e| e.to_string())?.len() > MAX_BYTES {
        return Err("Result file exceeds 128 MiB".into());
    }
    let mut bytes = Vec::new();
    file.take(MAX_BYTES + 1)
        .read_to_end(&mut bytes)
        .map_err(|e| e.to_string())?;
    if bytes.len() as u64 > MAX_BYTES {
        return Err("Result file exceeds 128 MiB".into());
    }
    let doc: Document =
        serde_json::from_slice(&bytes).map_err(|e| format!("Invalid result JSON: {e}"))?;
    doc.validate()?;
    Ok(doc)
}

/// Metadata JSON is quoted in a CSV record before the typed data sections.
/// Empty sample cells mean missing; raw and calibrated values stay f64.
pub fn save_csv(path: &Path, doc: &Document) -> Result<(), String> {
    doc.validate()?;
    crate::file_io::atomic_write(path, |file| {
        let mut w = BufWriter::new(file);
        let mut metadata = doc.clone();
        for t in &mut metadata.scope.traces {
            t.raw_samples_fs = None;
        }
        metadata.spectrum.values = None;
        metadata.spectrum.peak_hold = None;
        let json = serde_json::to_string(&metadata).map_err(std::io::Error::other)?;
        writeln!(w, "metadata_json,\"{}\"", json.replace('"', "\"\""))?;
        writeln!(
            w,
            "section,trace,channel,sample_index,seconds_from_input_start,raw_fs,calibrated_value,unit,state"
        )?;
        for (i, t) in doc.scope.traces.iter().enumerate() {
            if let Some(samples) = &t.raw_samples_fs {
                for (n, x) in samples.iter().enumerate() {
                    let index = doc.scope.sample_range.start + n as u64;
                    let y = x.map(|x| {
                        t.calibration
                            .as_ref()
                            .map_or(x, |c| c.gain.mul_add(x, c.offset))
                    });
                    writeln!(
                        w,
                        "scope,{i},{},{index},{},{},{},\"{}\",{}",
                        t.channel,
                        index as f64 / doc.input.nominal_sample_rate_hz as f64,
                        x.map_or(String::new(), |x| x.to_string()),
                        y.filter(|y| y.is_finite())
                            .map_or(String::new(), |x| x.to_string()),
                        t.calibrated_statistics.unit.replace('"', "\"\""),
                        if x.is_none() {
                            "missing"
                        } else if y.is_some_and(|y| !y.is_finite()) {
                            "non_finite"
                        } else {
                            "valid"
                        }
                    )?;
                }
            }
        }
        writeln!(
            w,
            "section,channel,bin,frequency_hz,linear_value,unit,peak_hold,state"
        )?;
        if let Some(values) = &doc.spectrum.values {
            for (k, v) in values.iter().enumerate() {
                writeln!(
                    w,
                    "spectrum,{},{k},{},{v},\"{}\",{},valid",
                    doc.spectrum.channel.unwrap(),
                    k as f64 * doc.spectrum.bin_width_hz,
                    doc.spectrum.unit.replace('"', "\"\""),
                    doc.spectrum
                        .peak_hold
                        .as_ref()
                        .map_or(String::new(), |h| h.values[k].to_string())
                )?;
            }
        }
        if let Some(l) = &doc.lockin {
            let r = &l.result;
            writeln!(
                w,
                "section,reference_channel,response_channel,contributing_start,contributing_end,latest_start,latest_end,processed_windows,missing_samples,x_peak,y_peak,amplitude_peak,phase_lead_degrees,response_unit_peak,gain,gain_unit,reference_frequency_hz,reference_ac_rms_fs,reference_peak,reference_unit_peak,reference_sinusoid_fraction,state"
            )?;
            write!(
                w,
                "lockin,{},{},{},{},{},{},{},{}",
                r.settings.reference_channel,
                r.settings.response_channel,
                r.sample_range.start,
                r.sample_range.end,
                r.latest_window.start,
                r.latest_window.end,
                r.processed_windows,
                r.missing_samples
            )?;
            for v in [r.x, r.y, r.amplitude_peak, r.phase_degrees] {
                write!(w, ",{}", v.map_or(String::new(), |v| v.to_string()))?;
            }
            write!(
                w,
                ",\"{}\",{},\"{}\"",
                l.response_unit_peak.replace('"', "\"\""),
                r.gain.map_or(String::new(), |v| v.to_string()),
                l.gain_unit.replace('"', "\"\"")
            )?;
            for v in [
                r.reference_frequency_hz,
                r.reference_ac_rms_fs,
                r.reference_peak,
            ] {
                write!(w, ",{}", v.map_or(String::new(), |v| v.to_string()))?;
            }
            let reference_unit = l
                .reference_calibration
                .as_ref()
                .map_or("FS", |c| c.unit.as_str());
            writeln!(
                w,
                ",\"{} peak\",{},{}",
                reference_unit.replace('"', "\"\""),
                r.reference_sinusoid_fraction
                    .map_or(String::new(), |v| v.to_string()),
                serde_json::to_string(&r.state).map_err(std::io::Error::other)?
            )?;
        }
        w.flush()
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{
        calibration::Set,
        channel::Pair,
        signal::History,
        spectrum::{Analyzer, Result as SpectrumResult, Settings, Window},
    };
    fn fixture() -> Document {
        let mut h = History::new(1024);
        for n in 0..1024 {
            h.push([
                0.123456789012345 + n as f64 * 1e-13,
                0.25 * (std::f64::consts::TAU * n as f64 * 16.0 / 1024.0).sin(),
            ]);
        }
        let s = Settings {
            size: 1024,
            window: Window::Rectangular,
            averages: 1,
            ..Default::default()
        };
        let mut a = Analyzer::new(s, 48000);
        a.update_window(&h, 0..1024, 1);
        let mut r = SpectrumResult::empty(s, 48000);
        a.copy_result(&mut r);
        crate::export::tests::document(&h, &r, &Set::default(), Pair([0, 1]))
    }

    #[test]
    fn generator_conditions_roundtrip_and_differences_require_known_stationary_excitation() {
        let mut doc = lockin_fixture(0.0625, 30.0, &Set::default(), crate::lockin::State::Valid);
        doc.input.source = Source::Generator;
        let range = doc.lockin.as_ref().unwrap().result.sample_range.clone();
        let mut signals = crate::generator::Settings::default();
        for s in &mut signals.signals {
            s.enabled = true;
            s.frequency_hz = 750.0;
        }
        let mut engine = crate::generator::Engine::new(48_000, 2, signals, 0).unwrap();
        engine.start(signals, 1).unwrap();
        for _ in 0..480 {
            engine.next_frame().unwrap();
        }
        let condition = crate::output::Condition::from_status(engine.status());
        doc.generator_output = Some(crate::output::Timeline {
            spans: vec![crate::output::Span {
                sample_range: range,
                condition,
            }],
        });
        doc.validate().unwrap();
        let path = std::env::temp_dir().join(format!(
            "measurelab-generator-reference-{}.json",
            std::process::id()
        ));
        crate::export::save(&path, &doc).unwrap();
        assert_eq!(load(&path).unwrap(), doc);
        std::fs::remove_file(path).unwrap();
        let mut next = doc.clone();
        next.input.generation += 1;
        assert!(lockin_difference(&doc, &next).is_some());
        next.generator_output.as_mut().unwrap().spans[0]
            .condition
            .carrier_phase_cycles[1] = 0.25;
        assert!(lockin_difference(&doc, &next).is_none());
        next = doc.clone();
        next.generator_output.as_mut().unwrap().spans[0]
            .condition
            .transitioning = true;
        assert!(lockin_difference(&doc, &next).is_none());
        next = doc.clone();
        next.generator_output.as_mut().unwrap().spans.clear();
        assert!(lockin_difference(&doc, &next).is_none());
        let range = doc.lockin.as_ref().unwrap().result.sample_range.clone();
        assert!(matching_excitation(
            &doc,
            range.clone(),
            &doc,
            range.clone()
        ));
        assert!(!matching_excitation(&doc, 0..480, &doc, range.clone()));
        assert!(!matching_excitation(&doc, range, &fixture(), 0..1024));
        next = doc.clone();
        next.generator_output = None;
        assert!(next.validate().is_err());
        let mut old = serde_json::to_value(fixture()).unwrap();
        old["version"] = 1.into();
        old.as_object_mut().unwrap().remove("generator_output");
        let old: Document = serde_json::from_value(old).unwrap();
        old.validate().unwrap();
    }

    fn lockin_fixture(
        peak: f64,
        phase: f64,
        calibrations: &Set,
        state: crate::lockin::State,
    ) -> Document {
        use crate::lockin;
        let settings = lockin::Settings {
            enabled: true,
            frequency_hz: 750.0,
            integration_samples: 1024,
            track_reference: false,
            time_constant_seconds: if state == lockin::State::Settling {
                10.0
            } else {
                0.02
            },
            ..Default::default()
        };
        let mut detector = lockin::Analyzer::new(settings, 48000);
        detector.set_calibrations(calibrations.clone());
        let mut history = History::new(1024);
        // Preserve exact integer clocks beyond f64's consecutive-integer range.
        let first = (1u64 << 54) + 7;
        for i in 0..65536 {
            let angle = std::f64::consts::TAU * 750.0 * i as f64 / 48000.0;
            let pair = [
                if state == lockin::State::ReferenceLost {
                    0.2
                } else {
                    0.125 * angle.sin()
                },
                0.1 + peak * (angle + phase.to_radians()).sin(),
            ];
            detector.push_pair(first + i, pair);
            history.push_at(first + i, pair);
        }
        assert_eq!(detector.result().state, state);
        let fft_settings = Settings {
            size: 1024,
            averages: 1,
            ..Default::default()
        };
        let mut fft = Analyzer::new(fft_settings, 48000);
        fft.update_window(&history, history.range(), 1);
        let mut fft_result = SpectrumResult::empty(fft_settings, 48000);
        fft.copy_result(&mut fft_result);
        let mut doc =
            crate::export::tests::document(&history, &fft_result, calibrations, Pair([0, 1]));
        doc.lockin = Some(Lockin::capture(detector.result().clone(), calibrations));
        doc.validate().unwrap();
        doc
    }

    #[test]
    fn lockin_json_csv_roundtrip_preserves_micro_signal_calibrations_and_invalid_states() {
        use crate::lockin::State;
        let calibrations = Set::default()
            .with(
                0,
                Some(
                    Calibration::new("ref".into(), 3, -2.0, 0.4, "A".into(), "Known REF".into())
                        .unwrap(),
                ),
            )
            .unwrap()
            .with(
                1,
                Some(
                    Calibration::new(
                        "response".into(),
                        7,
                        4.0,
                        0.8,
                        "V".into(),
                        "Known DUT".into(),
                    )
                    .unwrap(),
                ),
            )
            .unwrap();
        let path = std::env::temp_dir().join(format!(
            "measurelab-lockin-roundtrip-{}.json",
            std::process::id()
        ));
        let csv_path = path.with_extension("csv");
        for state in [State::Valid, State::Settling, State::ReferenceLost] {
            let doc = lockin_fixture(1.25e-8, 30.0, &calibrations, state);
            crate::export::save(&path, &doc).unwrap();
            let loaded = load(&path).unwrap();
            assert_eq!(doc, loaded);
            let l = loaded.lockin.as_ref().unwrap();
            assert_eq!(l.response_unit_peak, "V peak");
            assert_eq!(l.gain_unit, "V/A");
            assert_eq!(l.reference_calibration.as_ref().unwrap().revision, 3);
            assert_eq!(l.response_calibration.as_ref().unwrap().revision, 7);
            if state == State::Valid {
                // DC/calibration offsets are excluded; negative REF gain rotates 180°.
                assert!((l.result.amplitude_peak.unwrap() - 5e-8).abs() < 1e-15);
                assert!((l.result.phase_degrees.unwrap() + 150.0).abs() < 1e-6);
                assert!((l.result.gain.unwrap() - 2e-7).abs() < 1e-14);
            }
            save_csv(&csv_path, &loaded).unwrap();
            let csv = std::fs::read_to_string(&csv_path).unwrap();
            let row: Vec<_> = csv
                .lines()
                .find(|line| line.starts_with("lockin,"))
                .unwrap()
                .split(',')
                .collect();
            assert_eq!(row.len(), 22);
            assert_eq!(row[3].parse::<u64>().unwrap(), l.result.sample_range.start);
            assert_eq!(row[6].parse::<u64>().unwrap(), l.result.latest_window.end);
            assert_eq!(row[13], "\"V peak\"");
            assert_eq!(row[15], "\"V/A\"");
            for (column, value) in [
                (9, l.result.x),
                (10, l.result.y),
                (11, l.result.amplitude_peak),
                (12, l.result.phase_degrees),
                (14, l.result.gain),
                (16, l.result.reference_frequency_hz),
                (17, l.result.reference_ac_rms_fs),
                (18, l.result.reference_peak),
                (20, l.result.reference_sinusoid_fraction),
            ] {
                if let Some(v) = value {
                    assert_eq!(row[column].parse::<f64>().unwrap().to_bits(), v.to_bits());
                } else {
                    assert_eq!(row[column], "");
                }
            }
            assert_eq!(row[21], serde_json::to_string(&state).unwrap());
        }
        std::fs::remove_file(path).unwrap();
        std::fs::remove_file(csv_path).unwrap();
    }

    #[test]
    fn lockin_rejects_corrupt_definitions_and_save_preserves_previous_file() {
        let doc = lockin_fixture(0.0625, 30.0, &Set::default(), crate::lockin::State::Valid);
        let path = std::env::temp_dir().join(format!(
            "measurelab-lockin-corrupt-{}.json",
            std::process::id()
        ));
        for corrupt in [
            "unit",
            "gain_unit",
            "range",
            "latest",
            "windows",
            "overflow",
            "settling",
            "state",
            "channel",
            "r",
            "phase",
            "gain",
            "frequency",
            "rms",
            "fraction",
            "peak",
            "diagnostic",
        ] {
            let mut json = serde_json::to_value(&doc).unwrap();
            let l = &mut json["lockin"];
            match corrupt {
                "unit" => l["response_unit_peak"] = "V RMS".into(),
                "gain_unit" => l["gain_unit"] = "V/A".into(),
                "range" => l["result"]["sample_range"]["start"] = 0.into(),
                "latest" => l["result"]["latest_window"]["start"] = 0.into(),
                "windows" => l["result"]["processed_windows"] = 1.into(),
                "overflow" => l["result"]["processed_windows"] = u64::MAX.into(),
                "settling" => l["result"]["settings"]["time_constant_seconds"] = 10.0.into(),
                "state" => l["result"]["state"] = "reference_lost".into(),
                "channel" => l["result"]["settings"]["response_channel"] = 15.into(),
                "r" => l["result"]["amplitude_peak"] = 0.5.into(),
                "phase" => l["result"]["phase_degrees"] = (-30.0).into(),
                "gain" => l["result"]["gain"] = (-0.5).into(),
                "frequency" => l["result"]["reference_frequency_hz"] = 751.0.into(),
                "rms" => l["result"]["reference_ac_rms_fs"] = 0.0.into(),
                "fraction" => l["result"]["reference_sinusoid_fraction"] = 0.97.into(),
                "peak" => l["result"]["reference_peak"] = 0.0.into(),
                _ => l["result"]["reference_frequency_hz"] = serde_json::Value::Null,
            }
            std::fs::write(&path, serde_json::to_vec(&json).unwrap()).unwrap();
            assert!(load(&path).is_err(), "accepted {corrupt}");
            crate::export::save(&path, &doc).unwrap();
            let previous = std::fs::read(&path).unwrap();
            let bad: Document = serde_json::from_value(json).unwrap();
            assert!(crate::export::save(&path, &bad).is_err(), "saved {corrupt}");
            assert_eq!(std::fs::read(&path).unwrap(), previous);
        }
        let mut bad = doc.clone();
        bad.lockin.as_mut().unwrap().result.x = Some(f64::NAN);
        assert!(crate::export::save(&path, &bad).is_err());
        assert_eq!(load(&path).unwrap(), doc);
        let mut old = serde_json::to_value(&doc).unwrap();
        old.as_object_mut().unwrap().remove("lockin");
        let old: Document = serde_json::from_value(old).unwrap();
        old.validate().unwrap();
        assert!(old.lockin.is_none());
        std::fs::remove_file(path).unwrap();
    }

    #[test]
    fn lockin_comparison_wraps_phase_and_requires_matching_settled_conditions() {
        let a = lockin_fixture(0.0625, 179.0, &Set::default(), crate::lockin::State::Valid);
        let mut b = lockin_fixture(0.125, -179.0, &Set::default(), crate::lockin::State::Valid);
        b.input.generation += 1;
        let d = lockin_difference(&a, &b).unwrap();
        assert!((d.phase_degrees - 2.0).abs() < 1e-10);
        assert!((d.amplitude_peak - 0.0625).abs() < 1e-12);
        assert!((d.gain - 0.5).abs() < 1e-12);
        for mismatch in [
            "rate",
            "channel",
            "tau",
            "window",
            "tracking",
            "calibration",
            "reference_calibration",
            "state",
            "input_failed",
            "absent",
        ] {
            let mut b = b.clone();
            let l = b.lockin.as_mut().unwrap();
            match mismatch {
                "rate" => b.input.nominal_sample_rate_hz = 96000,
                "channel" => l.result.settings.reference_channel = 1,
                "tau" => l.result.settings.time_constant_seconds = 0.03,
                "window" => l.result.settings.integration_samples = 4096,
                "tracking" => l.result.settings.track_reference = true,
                "calibration" | "reference_calibration" => {
                    let c = crate::settings::ChannelCalibration {
                        channel: 1,
                        id: "new".into(),
                        revision: 2,
                        gain: 2.0,
                        offset: 0.0,
                        unit: "FS".into(),
                        conditions: "Different revision".into(),
                    };
                    if mismatch == "calibration" {
                        l.response_calibration = Some(c);
                    } else {
                        l.reference_calibration =
                            Some(crate::settings::ChannelCalibration { channel: 0, ..c });
                    }
                }
                "state" => l.result.state = crate::lockin::State::Settling,
                "input_failed" => b.loss.input_failed = true,
                _ => b.lockin = None,
            }
            assert!(lockin_difference(&a, &b).is_none(), "compared {mismatch}");
        }
    }
    #[test]
    fn result_roundtrip_is_bit_exact_and_rejects_corrupt_metadata_arrays_and_versions() {
        let doc = fixture();
        doc.validate().unwrap();
        let path =
            std::env::temp_dir().join(format!("measurelab-reference-{}.json", std::process::id()));
        crate::export::save(&path, &doc).unwrap();
        let loaded = load(&path).unwrap();
        assert_eq!(doc, loaded);
        let mut old = serde_json::to_value(&doc).unwrap();
        old["scope"]
            .as_object_mut()
            .unwrap()
            .remove("acquisition_mode");
        let old: Document = serde_json::from_value(old).unwrap();
        assert_eq!(old.scope.acquisition_mode, crate::acquisition::Mode::Auto);
        old.validate().unwrap();
        for corrupt in ["version", "samples", "interval", "unit", "unknown"] {
            let mut json = serde_json::to_value(&doc).unwrap();
            match corrupt {
                "version" => json["version"] = 99.into(),
                "samples" => {
                    json["scope"]["traces"][0]["raw_samples_fs"] = serde_json::json!([1.0])
                }
                "interval" => json["spectrum"]["latest_window"]["end"] = 0.into(),
                "unit" => json["spectrum"]["unit"] = "V peak".into(),
                _ => json["unexpected"] = true.into(),
            }
            std::fs::write(&path, serde_json::to_vec(&json).unwrap()).unwrap();
            assert!(load(&path).is_err(), "accepted {corrupt}");
        }
        std::fs::File::create(&path)
            .unwrap()
            .set_len(MAX_BYTES + 1)
            .unwrap();
        assert!(load(&path).unwrap_err().contains("128 MiB"));
        std::fs::remove_file(path).unwrap();
    }
    #[test]
    fn csv_preserves_raw_f64_and_conditions_and_missing_cells() {
        let mut doc = fixture();
        let t = &mut doc.scope.traces[0];
        t.raw_samples_fs.as_mut().unwrap()[10] = None;
        t.missing_samples = 1;
        t.state = State::Partial;
        let path =
            std::env::temp_dir().join(format!("measurelab-reference-{}.csv", std::process::id()));
        save_csv(&path, &doc).unwrap();
        let csv = std::fs::read_to_string(&path).unwrap();
        assert!(csv.contains("0.123456789012345"));
        assert!(csv.contains("scope,0,0,10,"));
        assert!(csv.contains(",,,\"FS\",missing"));
        assert!(csv.contains("nominal_sample_rate_hz"));
        assert!(csv.contains("frequency_hz,linear_value,unit"));
        std::fs::remove_file(path).unwrap();
    }

    #[test]
    fn unfilled_lockin_window_can_be_saved_without_fabricated_values() {
        let mut doc = fixture();
        let analyzer = crate::lockin::Analyzer::new(
            crate::lockin::Settings {
                enabled: true,
                ..Default::default()
            },
            doc.input.nominal_sample_rate_hz,
        );
        doc.lockin = Some(Lockin {
            result: analyzer.result().clone(),
            reference_calibration: None,
            response_calibration: None,
            response_unit_peak: "FS peak".into(),
            gain_unit: "ratio".into(),
        });
        doc.validate().unwrap();
        assert!(doc.lockin.as_ref().unwrap().result.x.is_none());
        let path = std::env::temp_dir().join(format!(
            "measurelab-lockin-unfilled-{}.json",
            std::process::id()
        ));
        crate::export::save(&path, &doc).unwrap();
        assert_eq!(load(&path).unwrap(), doc);
        let csv_path = path.with_extension("csv");
        save_csv(&csv_path, &doc).unwrap();
        let csv = std::fs::read_to_string(&csv_path).unwrap();
        let row: Vec<_> = csv
            .lines()
            .find(|line| line.starts_with("lockin,"))
            .unwrap()
            .split(',')
            .collect();
        assert_eq!(row[9], "");
        assert_eq!(row[14], "");
        assert_eq!(row[21], "\"settling\"");
        std::fs::remove_file(path).unwrap();
        std::fs::remove_file(csv_path).unwrap();
        doc.lockin.as_mut().unwrap().result.x = Some(0.0);
        assert!(doc.validate().is_err());
    }

    #[test]
    fn lockin_gap_nonfinite_unavailable_and_disabled_results_roundtrip_without_old_values() {
        use crate::lockin::{self, State};
        let path = std::env::temp_dir().join(format!(
            "measurelab-lockin-invalid-{}.json",
            std::process::id()
        ));
        for state in [
            State::Missing,
            State::NonFinite,
            State::Unavailable,
            State::Disabled,
        ] {
            let mut doc = fixture();
            let settings = lockin::Settings {
                enabled: state != State::Disabled,
                integration_samples: 1024,
                track_reference: false,
                ..Default::default()
            };
            let mut detector = lockin::Analyzer::new(settings, 48000);
            for n in 0..1024 {
                let tone = 0.125 * (std::f64::consts::TAU * 1000.0 * n as f64 / 48000.0).sin();
                detector.push_pair(n, [tone, tone]);
            }
            match state {
                State::Missing => detector.gap_to(1030),
                State::NonFinite => detector.push_pair(1024, [f64::NAN, 0.0]),
                State::Unavailable => detector.push(1024, &[]),
                _ => {}
            }
            assert_eq!(detector.result().state, state);
            assert_eq!(
                detector.result().missing_samples,
                if state == State::Missing { 6 } else { 0 }
            );
            doc.spectrum.diagnostics.input_end = 1030;
            doc.lockin = Some(Lockin::capture(detector.result().clone(), &Set::default()));
            crate::export::save(&path, &doc).unwrap();
            assert_eq!(load(&path).unwrap(), doc);
            let r = &doc.lockin.as_ref().unwrap().result;
            assert!(r.x.is_none() && r.reference_peak.is_none());
            assert_eq!(r.processed_windows, 0);
            let mut bad = doc.clone();
            bad.lockin.as_mut().unwrap().result.processed_windows = 1;
            assert!(bad.validate().is_err());
        }
        std::fs::remove_file(path).unwrap();
    }
}
