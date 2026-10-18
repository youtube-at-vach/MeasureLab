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
        if let Some(output) = &self.external_output {
            if !matches!(self.input.source, Source::Audio { .. }) || self.generator_output.is_some()
            {
                return Err("External output observations require audio input".into());
            }
            output.validate(self.input.generation)?;
        }
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
        if ![2, crate::channel::SCOPE_CHANNELS].contains(&self.scope.traces.len()) {
            return Err("Invalid Scope trace count".into());
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
        if let Some(c) = &self.comparison {
            c.validate(
                &self.input,
                s.diagnostics.input_end.max(self.retained_history.end),
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
    // External output observations never establish the excitation at an ADC
    // sample. Do not use identical latest settings as a stationary match.
    if reference.external_output.is_some() || current.external_output.is_some() {
        return false;
    }
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

impl Comparison {
    fn validate(&self, input: &Input, end: u64) -> Result<(), String> {
        use crate::comparison::{self, State};
        let r = &self.result;
        r.settings.validate(input.nominal_sample_rate_hz)?;
        let s = r.settings;
        validate_calibration(self.reference_calibration.as_ref(), s.reference_channel)?;
        validate_calibration(self.response_calibration.as_ref(), s.response_channel)?;
        let mut set = crate::calibration::Set::default();
        for c in [&self.reference_calibration, &self.response_calibration]
            .into_iter()
            .flatten()
        {
            set = set
                .with(
                    c.channel,
                    Some(
                        Calibration::new(
                            c.id.clone(),
                            c.revision,
                            c.gain,
                            c.offset,
                            c.unit.clone(),
                            c.conditions.clone(),
                        )
                        .map_err(str::to_owned)?,
                    ),
                )
                .map_err(str::to_owned)?;
        }
        let expected = Comparison::capture(r.clone(), &set);
        if self.reference_psd_unit != expected.reference_psd_unit
            || self.response_psd_unit != expected.response_psd_unit
            || self.cross_psd_unit != expected.cross_psd_unit
            || self.gain_unit != expected.gain_unit
            || self.limitations != COMPARISON_LIMITATIONS
            || r.generation != input.generation
            || r.nominal_sample_rate_hz != input.nominal_sample_rate_hz
            || r.input_end > end
            || (!s.enabled && r.state != State::Disabled)
        {
            return Err("Comparison input, units or limitations disagree".into());
        }
        if r.state != State::Valid {
            if !r.bins.is_empty()
                || r.delay.is_some()
                || r.averaged_windows != 0
                || r.sample_range != (0..0)
                || r.latest_window != (0..0)
                || (r.state != State::Averaging && r.processed_windows != 0)
                || (r.state == State::Averaging
                    && (r.processed_windows == 0 || r.processed_windows >= s.averages as u64))
            {
                return Err("Invalid comparison state carries stale values".into());
            }
            return Ok(());
        }
        if !s.enabled
            || s.reference_channel >= input.channels
            || s.response_channel >= input.channels
            || r.sample_range.end < r.sample_range.start
            || r.sample_range.end - r.sample_range.start != (s.size * s.averages) as u64
            || r.sample_range.end > r.input_end
            || r.latest_window.end != r.sample_range.end
            || r.latest_window.end < r.latest_window.start
            || r.latest_window.end - r.latest_window.start != s.size as u64
            || r.averaged_windows != s.averages
            || r.processed_windows < s.averages as u64
            || r.bins.len() != s.size / 2 + 1
        {
            return Err("Invalid comparison window, channels or average".into());
        }
        let ref_gain = set.get(s.reference_channel).map_or(1.0, |c| c.gain());
        let close = |a: f64, b: f64| {
            a.is_finite() && b.is_finite() && (a - b).abs() <= b.abs() * 1e-10 + 1e-300
        };
        let option_close = |a: Option<f64>, b: Option<f64>| match (a, b) {
            (Some(a), Some(b)) => close(a, b),
            (None, None) => true,
            _ => false,
        };
        for (k, b) in r.bins.iter().enumerate() {
            if [b.reference_psd, b.response_psd, b.cross_re, b.cross_im]
                .iter()
                .any(|v| !v.is_finite())
                || b.reference_psd < 0.0
                || b.response_psd < 0.0
                || ((b.reference_psd == 0.0 || b.response_psd == 0.0)
                    && (b.cross_re != 0.0 || b.cross_im != 0.0))
            {
                return Err("Nonfinite or impossible comparison spectra".into());
            }
            if b.reference_psd > 0.0 && b.response_psd > 0.0 {
                let magnitude = ((b.cross_re / b.reference_psd.sqrt()) / b.response_psd.sqrt())
                    .hypot((b.cross_im / b.reference_psd.sqrt()) / b.response_psd.sqrt());
                if !magnitude.is_finite() || magnitude > 1.0 + 1e-10 {
                    return Err("Cross spectrum violates coherence bound".into());
                }
            }
            let expected = comparison::make_bin(
                [b.reference_psd, b.response_psd, b.cross_re, b.cross_im],
                k,
                s,
                r.nominal_sample_rate_hz,
                ref_gain,
            );
            if b.state != expected.state
                || !option_close(b.coherence, expected.coherence)
                || !option_close(b.transfer_re, expected.transfer_re)
                || !option_close(b.transfer_im, expected.transfer_im)
                || !option_close(b.gain, expected.gain)
                || !option_close(b.phase_lead_degrees, expected.phase_lead_degrees)
                || !option_close(b.phase_delay_seconds, expected.phase_delay_seconds)
            {
                return Err("Comparison derived values disagree with spectra".into());
            }
        }
        let expected_delay = comparison::fit_delay(&r.bins, s, r.bin_width_hz());
        match (&r.delay, expected_delay) {
            (None, None) => {}
            (Some(a), Some(b))
                if a.inclusive_bins == b.inclusive_bins
                    && close(a.seconds, b.seconds)
                    && close(a.phase_residual_rms_degrees, b.phase_residual_rms_degrees) => {}
            _ => return Err("Comparison delay disagrees with phase slope".into()),
        }
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct ComparisonDifference {
    pub gain: f64,
    pub phase_degrees: f64,
    pub phase_delay_seconds: Option<f64>,
}
pub fn comparison_difference(
    reference: &Document,
    current: &Document,
    bin: usize,
) -> Option<ComparisonDifference> {
    use crate::comparison::{BinState, State};
    let a = reference.comparison.as_ref()?;
    let b = current.comparison.as_ref()?;
    if reference.loss.input_failed
        || current.loss.input_failed
        || a.result.state != State::Valid
        || b.result.state != State::Valid
        || a.result.settings != b.result.settings
        || reference.input.source != current.input.source
        || reference.input.channels != current.input.channels
        || a.result.nominal_sample_rate_hz != b.result.nominal_sample_rate_hz
        || a.reference_calibration != b.reference_calibration
        || a.response_calibration != b.response_calibration
        || a.gain_unit != b.gain_unit
        || a.result.missing_samples != 0
        || b.result.missing_samples != 0
        || a.result.invalid_samples != 0
        || b.result.invalid_samples != 0
        || !matching_excitation(
            reference,
            a.result.sample_range.clone(),
            current,
            b.result.sample_range.clone(),
        )
    {
        return None;
    }
    let a = a.result.bins.get(bin)?;
    let b = b.result.bins.get(bin)?;
    if a.state != BinState::Valid || b.state != BinState::Valid {
        return None;
    }
    Some(ComparisonDifference {
        gain: b.gain? - a.gain?,
        phase_degrees: phase_difference(b.phase_lead_degrees?, a.phase_lead_degrees?),
        phase_delay_seconds: b
            .phase_delay_seconds
            .zip(a.phase_delay_seconds)
            .map(|(b, a)| b - a),
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
        if let Some(c) = &mut metadata.comparison {
            c.result.bins.clear();
        }
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
        if let Some(c) = &doc.comparison {
            writeln!(
                w,
                "section,bin,frequency_hz,reference_psd,response_psd,cross_re,cross_im,coherence,transfer_re,transfer_im,gain,phase_lead_degrees,phase_delay_seconds,state"
            )?;
            for (k, b) in c.result.bins.iter().enumerate() {
                write!(
                    w,
                    "comparison,{k},{},{},{},{},{}",
                    k as f64 * c.result.bin_width_hz(),
                    b.reference_psd,
                    b.response_psd,
                    b.cross_re,
                    b.cross_im
                )?;
                for v in [
                    b.coherence,
                    b.transfer_re,
                    b.transfer_im,
                    b.gain,
                    b.phase_lead_degrees,
                    b.phase_delay_seconds,
                ] {
                    write!(w, ",{}", v.map_or(String::new(), |v| v.to_string()))?;
                }
                writeln!(
                    w,
                    ",{}",
                    serde_json::to_string(&b.state).map_err(std::io::Error::other)?
                )?;
            }
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
    fn comparison_fixture() -> Document {
        let mut doc = fixture();
        let s = crate::comparison::Settings {
            enabled: true,
            size: 1024,
            averages: 4,
            window: Window::Rectangular,
            ..Default::default()
        };
        let mut a =
            crate::comparison::Analyzer::new(s, 48000, doc.input.generation, 1, 2, Set::default());
        for n in 0..4096 {
            let p = std::f64::consts::TAU * 16.0 * n as f64 / 1024.0;
            a.push_pair(n, [0.125 * p.sin(), 0.0625 * (p + 0.5).sin()]);
        }
        doc.spectrum.diagnostics.input_end = 4096;
        doc.comparison = Some(Comparison::capture(a.result().clone(), &Set::default()));
        doc
    }
    #[test]
    fn comparison_roundtrip_csv_corruption_and_matching_conditions() {
        let doc = comparison_fixture();
        doc.validate().unwrap();
        let path =
            std::env::temp_dir().join(format!("measurelab-comparison-{}.json", std::process::id()));
        crate::export::save(&path, &doc).unwrap();
        let loaded = load(&path).unwrap();
        assert_eq!(doc.comparison, loaded.comparison);
        let csv = path.with_extension("csv");
        save_csv(&csv, &doc).unwrap();
        let text = std::fs::read_to_string(&csv).unwrap();
        assert!(text.contains("comparison,16,750,"));
        let difference = comparison_difference(&loaded, &doc, 16).unwrap();
        assert_eq!(difference.gain, 0.0);
        assert_eq!(difference.phase_degrees, 0.0);
        for corruption in [
            "generation",
            "size",
            "window",
            "coherence",
            "gain",
            "phase",
            "delay",
            "unit",
            "calibration",
            "version",
            "range",
            "cross",
        ] {
            let mut value = serde_json::to_value(&doc).unwrap();
            let c = &mut value["comparison"];
            match corruption {
                "generation" => c["result"]["generation"] = 999.into(),
                "size" => c["result"]["settings"]["size"] = 2048.into(),
                "window" => c["result"]["averaged_windows"] = 1.into(),
                "coherence" => c["result"]["bins"][16]["coherence"] = 0.0.into(),
                "gain" => c["result"]["bins"][16]["gain"] = 100.0.into(),
                "phase" => c["result"]["bins"][16]["phase_lead_degrees"] = 90.0.into(),
                "delay" => c["result"]["bins"][16]["phase_delay_seconds"] = 1.0.into(),
                "unit" => c["gain_unit"] = "V/A".into(),
                "calibration" => c["limitations"] = "calibrated".into(),
                "version" => value["version"] = 3.into(),
                "range" => c["result"]["sample_range"]["end"] = 4095.into(),
                _ => c["result"]["bins"][16]["cross_re"] = 1e100.into(),
            }
            let bad: Document = serde_json::from_value(value).unwrap();
            assert!(bad.validate().is_err(), "accepted {corruption}");
        }
        let mut bad = doc.clone();
        bad.comparison.as_mut().unwrap().result.bins[16].gain = Some(f64::NAN);
        assert!(crate::export::save(&path, &bad).is_err());
        assert_eq!(load(&path).unwrap().comparison, doc.comparison);
        for mismatch in [
            "window",
            "calibration",
            "missing",
            "failure",
            "source",
            "state",
            "external",
        ] {
            let mut next = doc.clone();
            let c = next.comparison.as_mut().unwrap();
            match mismatch {
                "window" => c.result.settings.window = Window::Hann,
                "calibration" => c.gain_unit = "A/V".into(),
                "missing" => c.result.missing_samples = 1,
                "failure" => next.loss.input_failed = true,
                "source" => {
                    next.input.source = Source::InternalQa {
                        description: "different".into(),
                    }
                }
                "state" => c.result.state = crate::comparison::State::Missing,
                _ => {
                    next.external_output = Some(crate::output::history::ExternalOutput {
                        input_generation: doc.input.generation,
                        clock_relationship:
                            crate::output::history::ClockRelationship::IndependentUncalibrated,
                        observation_start_host_micros: 0,
                        observation_end_host_micros: 0,
                        initial: None,
                        changes: Vec::new(),
                        latest: None,
                        evicted_changes: 0,
                        lost_reports_since_output_worker_start: 0,
                        notifications_since_output_worker_start: 0,
                    })
                }
            }
            assert!(
                comparison_difference(&doc, &next, 16).is_none(),
                "compared {mismatch}"
            );
        }
        let mut old = serde_json::to_value(&doc).unwrap();
        old["version"] = 3.into();
        old.as_object_mut().unwrap().remove("comparison");
        let old: Document = serde_json::from_value(old).unwrap();
        old.validate().unwrap();
        assert!(old.comparison.is_none());
        std::fs::remove_file(path).unwrap();
        std::fs::remove_file(csv).unwrap();
    }
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
    fn four_scope_traces_roundtrip_all_raw_channels_and_legacy_stereo_stays_readable() {
        let mut history = History::with_channels(1024, 4);
        for n in 0..1024 {
            history.push_at(n, [0.125, -0.25, 0.375, -0.5]);
        }
        let settings = Settings {
            size: 1024,
            window: Window::Rectangular,
            averages: 1,
            remove_dc: false,
            ..Default::default()
        };
        let mut analyzer = Analyzer::new(settings, 48000);
        analyzer.update_window(&history, history.range(), 3);
        let mut result = SpectrumResult::empty(settings, 48000);
        analyzer.copy_result(&mut result);
        let doc = crate::export::tests::document(&history, &result, &Set::default(), Pair([0, 1]));
        doc.validate().unwrap();
        let loaded: Document = serde_json::from_slice(&serde_json::to_vec(&doc).unwrap()).unwrap();
        loaded.validate().unwrap();
        assert_eq!(loaded.scope.traces.len(), 4);
        for (index, value) in [0.125_f64, -0.25, 0.375, -0.5].into_iter().enumerate() {
            let trace = &loaded.scope.traces[index];
            assert_eq!(trace.channel, index);
            assert_eq!(
                trace.raw_samples_fs.as_ref().unwrap(),
                &vec![Some(value); 1024]
            );
            assert_eq!(
                trace.raw_statistics.values.as_ref().unwrap().rms,
                value.abs()
            );
        }
        let mut legacy = serde_json::to_value(fixture()).unwrap();
        legacy["version"] = 4.into();
        legacy["scope"]["traces"]
            .as_array_mut()
            .unwrap()
            .truncate(2);
        let loaded: Document = serde_json::from_value(legacy).unwrap();
        loaded.validate().unwrap();
        assert_eq!(loaded.scope.traces.len(), 2);
        let mut invalid = doc.clone();
        invalid.scope.traces.pop();
        assert!(invalid.validate().is_err());
    }

    #[test]
    fn external_output_json_csv_preserve_independent_clock_without_numeric_matching() {
        let mut doc = lockin_fixture(0.0625, 30.0, &Set::default(), crate::lockin::State::Valid);
        doc.external_output = Some(crate::output::history::tests::fixture(doc.input.generation));
        // Output is 96 kHz with a different integer origin; input remains 48 kHz.
        doc.validate().unwrap();
        let path = std::env::temp_dir().join(format!(
            "measurelab-external-reference-{}.json",
            std::process::id()
        ));
        crate::export::save(&path, &doc).unwrap();
        assert_eq!(load(&path).unwrap(), doc);
        std::fs::remove_file(&path).unwrap();
        let csv = path.with_extension("csv");
        save_csv(&csv, &doc).unwrap();
        let contents = std::fs::read_to_string(&csv).unwrap();
        let metadata = contents
            .lines()
            .next()
            .unwrap()
            .strip_prefix("metadata_json,\"")
            .unwrap()
            .strip_suffix('"')
            .unwrap()
            .replace("\"\"", "\"");
        let metadata: Document = serde_json::from_str(&metadata).unwrap();
        assert_eq!(metadata.external_output, doc.external_output);
        std::fs::remove_file(csv).unwrap();
        assert!(!matching_excitation(&doc, 0..1024, &doc, 0..1024));
        assert!(lockin_difference(&doc, &doc).is_none());
        let plain = fixture();
        assert!(!matching_excitation(&doc, 0..1024, &plain, 0..1024));
        assert!(!matching_excitation(&plain, 0..1024, &doc, 0..1024));
    }

    #[test]
    fn external_output_rejects_bad_provenance_and_old_result_versions_still_load() {
        let mut doc = fixture();
        doc.external_output = Some(crate::output::history::tests::fixture(doc.input.generation));
        for mutation in [
            "generation",
            "source",
            "order",
            "rate",
            "channels",
            "phase",
            "version",
        ] {
            let mut invalid = serde_json::to_value(&doc).unwrap();
            match mutation {
                "generation" => invalid["external_output"]["input_generation"] = 0.into(),
                "source" => {
                    invalid["input"]["source"] =
                        serde_json::json!({"kind":"internal_qa", "description":"test"})
                }
                "order" => invalid["external_output"]["observation_end_host_micros"] = 0.into(),
                "rate" => {
                    invalid["external_output"]["latest"]["status"]["nominal_sample_rate"] = 0.into()
                }
                "channels" => {
                    invalid["external_output"]["latest"]["status"]["output_channels"] = 16.into()
                }
                "phase" => {
                    invalid["external_output"]["latest"]["status"]["carrier_phase_cycles"][0] =
                        1.0.into()
                }
                "version" => invalid["version"] = 2.into(),
                _ => unreachable!(),
            }
            let invalid: Document = serde_json::from_value(invalid).unwrap();
            assert!(invalid.validate().is_err(), "accepted {mutation}");
        }
        for version in [1, 2] {
            let mut old = serde_json::to_value(fixture()).unwrap();
            old["version"] = version.into();
            old.as_object_mut().unwrap().remove("external_output");
            let old: Document = serde_json::from_value(old).unwrap();
            old.validate().unwrap();
            assert!(old.external_output.is_none());
        }
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
        let mut legacy = serde_json::to_value(&doc).unwrap();
        legacy["version"] = 5.into();
        for span in legacy["generator_output"]["spans"].as_array_mut().unwrap() {
            let condition = &mut span["condition"];
            for key in ["carrier_phase_cycles", "transition_end"] {
                condition[key].as_array_mut().unwrap().truncate(2);
            }
            condition["settings"]
                .as_object_mut()
                .unwrap()
                .remove("next_id");
            for signal in condition["settings"]["signals"].as_array_mut().unwrap() {
                for key in ["id", "waveform", "noise_seed"] {
                    signal.as_object_mut().unwrap().remove(key);
                }
            }
        }
        let legacy: Document = serde_json::from_value(legacy).unwrap();
        legacy.validate().unwrap();
        assert_eq!(legacy.generator_output, doc.generator_output);
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
