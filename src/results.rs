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
            let r = &l.result;
            r.settings.validate(self.input.nominal_sample_rate_hz)?;
            validate_calibration(
                l.reference_calibration.as_ref(),
                r.settings.reference_channel,
            )?;
            let has_values = r.state == crate::lockin::State::Valid
                || (r.state == crate::lockin::State::Settling && r.processed_windows > 0);
            if has_values != r.amplitude_peak.is_some()
                || has_values != r.phase_degrees.is_some()
                || has_values != r.x.is_some()
                || has_values != r.y.is_some()
                || has_values != r.gain.is_some()
                || (has_values && r.processed_windows == 0)
                || r.latest_window.end > s.diagnostics.input_end
            {
                return Err("Lock-in state disagrees with values/input endpoint".into());
            }
            validate_calibration(l.response_calibration.as_ref(), r.settings.response_channel)?;
            if r.sample_range.end < r.sample_range.start
                || r.latest_window.end < r.latest_window.start
                || [
                    r.reference_frequency_hz,
                    r.reference_ac_rms_fs,
                    r.reference_sinusoid_fraction,
                    r.reference_peak,
                    r.x,
                    r.y,
                    r.amplitude_peak,
                    r.phase_degrees,
                    r.gain,
                ]
                .iter()
                .flatten()
                .any(|v| !v.is_finite())
            {
                return Err("Invalid Lock-in result conditions".into());
            }
        }
        Ok(())
    }
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
        doc.lockin.as_mut().unwrap().result.x = Some(0.0);
        assert!(doc.validate().is_err());
    }
}
