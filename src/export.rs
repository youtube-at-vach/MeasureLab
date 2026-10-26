//! Finite, held Scope/Spectrum/Lock-in results with their acquisition conditions.
//! Only owned f64 results cross into the bounded file-I/O worker.
use crate::{
    audio, calibration,
    channel::{ChannelId, SCOPE_CHANNELS},
    measurement::{ScopeSettings, SpectrumInfo, SpectrumMode},
    settings::ChannelCalibration,
    signal::{History, Measurement, Sweep},
    spectrum::{self, Quantity, Settings},
};
use serde::{Deserialize, Serialize};
use std::{
    io::{BufWriter, Write},
    ops::Range,
    path::{Path, PathBuf},
    sync::mpsc,
    thread::{self, JoinHandle},
};

pub const FORMAT: &str = "measurelab-results";
pub const VERSION: u32 = 7;

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum Source {
    Generator,
    SoftwareLoopback {
        settings: crate::loopback::Settings,
    },
    Audio {
        device_id: Option<String>,
        device_name: String,
        sample_format: String,
        requested_sample_rate_hz: Option<u32>,
    },
    InternalQa {
        description: String,
    },
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Input {
    pub generation: u64,
    pub source: Source,
    pub nominal_sample_rate_hz: u32,
    pub channels: usize,
}

pub struct ScopeView<'a> {
    pub history: &'a History,
    pub settings: ScopeSettings,
    pub sweep: Sweep,
    pub calibrations: &'a calibration::Set,
    /// Already computed for this interval by the measurement worker.
    pub measurements: [Measurement; SCOPE_CHANNELS],
    pub readings: [calibration::Reading; SCOPE_CHANNELS],
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum State {
    Waiting,
    Unavailable,
    NonFinite,
    Partial,
    Valid,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Statistics {
    pub state: State,
    pub unit: String,
    pub acquired_samples: u64,
    pub values: Option<Values>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Values {
    pub rms: f64,
    pub peak: f64,
    pub peak_to_peak: f64,
}

impl Statistics {
    fn capture(reading: calibration::Reading, unit: &str, missing: u64) -> Self {
        let mut result = Self {
            state: State::Unavailable,
            unit: unit.into(),
            acquired_samples: 0,
            values: None,
        };
        match reading {
            calibration::Reading::Unavailable => {}
            calibration::Reading::NonFinite => result.state = State::NonFinite,
            calibration::Reading::Valid(Measurement {
                rms,
                peak,
                peak_to_peak,
                samples,
            }) => {
                result.acquired_samples = samples;
                if [rms, peak, peak_to_peak].iter().all(|v| v.is_finite()) {
                    result.state = if missing == 0 {
                        State::Valid
                    } else {
                        State::Partial
                    };
                    result.values = Some(Values {
                        rms,
                        peak,
                        peak_to_peak,
                    });
                } else {
                    result.state = State::NonFinite;
                }
            }
        }
        result
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Trace {
    pub channel: ChannelId,
    pub state: State,
    pub missing_samples: u64,
    pub calibration: Option<ChannelCalibration>,
    /// Position i belongs to sample_range.start + i; null is a missing frame.
    /// The whole array is null for an unavailable input channel.
    pub raw_samples_fs: Option<Vec<Option<f64>>>,
    pub raw_statistics: Statistics,
    pub calibrated_statistics: Statistics,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Scope {
    #[serde(default)]
    pub acquisition_mode: crate::acquisition::Mode,
    pub sample_range: Range<u64>,
    pub observation_samples: usize,
    pub trigger: crate::signal::Trigger,
    pub triggered: bool,
    /// For horizontal display only, never applied to acquired sample indices.
    pub horizontal_sample_offset: f64,
    pub traces: Vec<Trace>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Average {
    pub alpha: f64,
    pub processed_windows: u64,
    pub contributing_envelope: Range<u64>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PeakHold {
    pub considered_spectra: u64,
    pub contributing_envelope: Range<u64>,
    pub values: Vec<f64>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Diagnostics {
    pub processed_windows_since_reset: u64,
    pub missing_windows: u64,
    pub nonfinite_windows: u64,
    pub missing_input_samples: u64,
    pub missed_observations: u64,
    pub input_end: u64,
    pub filled_samples: usize,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Band {
    pub requested_hz: [f64; 2],
    pub inclusive_bins: [usize; 2],
    pub bin_centres_hz: [f64; 2],
    pub power: f64,
    pub power_unit: String,
    pub rms: f64,
    pub rms_unit: String,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Spectrum {
    pub state: State,
    pub channel: Option<ChannelId>,
    pub latest_window: Option<Range<u64>>,
    pub settings: Settings,
    pub mode: SpectrumMode,
    pub observation_interval_ms: u32,
    pub bin_width_hz: f64,
    pub rbw_hz: f64,
    pub calibration: Option<ChannelCalibration>,
    pub unit: String,
    pub average: Option<Average>,
    /// Entry k is at k * bin_width_hz, including DC and Nyquist.
    /// Amplitude is sqrt(averaged peak-bin power); PSD/ESD are averaged densities.
    pub values: Option<Vec<f64>>,
    pub peak_hold: Option<PeakHold>,
    pub requested_band_hz: [f64; 2],
    pub band: Option<Band>,
    pub diagnostics: Diagnostics,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Loss {
    pub capture_dropped_samples: u64,
    pub scope_missing_samples: u64,
    pub display_snapshots_skipped_since_worker_start: u64,
    pub input_failed: bool,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Document {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub external_output: Option<crate::output::history::ExternalOutput>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub generator_output: Option<crate::output::Timeline>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub lockin: Option<Lockin>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub comparison: Option<Comparison>,
    format: String,
    version: u32,
    app_version: String,
    exported_unix_seconds: u64,
    channel_index_base: u8,
    sample_range_convention: String,
    sample_clock: String,
    pub input: Input,
    pub retained_history: Range<u64>,
    pub scope: Scope,
    pub spectrum: Spectrum,
    pub loss: Loss,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Lockin {
    pub result: crate::lockin::Result,
    pub reference_calibration: Option<ChannelCalibration>,
    pub response_calibration: Option<ChannelCalibration>,
    pub response_unit_peak: String,
    pub gain_unit: String,
}

pub const COMPARISON_LIMITATIONS: &str = "nominal input clock; channel phase and timing calibration unverified; H1 estimate; wrapped phase delay is ambiguous by 1/f; slope fit requires 8 contiguous coherent bins at least 10% of peak reference PSD and adjacent phase steps below pi";

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Comparison {
    pub result: crate::comparison::Result,
    pub reference_calibration: Option<ChannelCalibration>,
    pub response_calibration: Option<ChannelCalibration>,
    pub reference_psd_unit: String,
    pub response_psd_unit: String,
    pub cross_psd_unit: String,
    pub gain_unit: String,
    pub limitations: String,
}
impl Comparison {
    pub fn capture(result: crate::comparison::Result, calibrations: &calibration::Set) -> Self {
        let s = result.settings;
        let definitions = ChannelCalibration::capture(calibrations);
        let unit = |ch| calibrations.unit(ch);
        let reference = unit(s.reference_channel);
        let response = unit(s.response_channel);
        Self {
            result,
            reference_calibration: definitions
                .iter()
                .find(|c| c.channel == s.reference_channel)
                .cloned(),
            response_calibration: definitions
                .iter()
                .find(|c| c.channel == s.response_channel)
                .cloned(),
            reference_psd_unit: format!("({reference})²/Hz"),
            response_psd_unit: format!("({response})²/Hz"),
            cross_psd_unit: format!("({reference})({response})/Hz"),
            gain_unit: if reference == response {
                "ratio".into()
            } else {
                format!("{response}/{reference}")
            },
            limitations: COMPARISON_LIMITATIONS.into(),
        }
    }
}

impl Lockin {
    pub fn capture(result: crate::lockin::Result, calibrations: &calibration::Set) -> Self {
        let definitions = ChannelCalibration::capture(calibrations);
        let reference_channel = result.settings.reference_channel;
        let response_channel = result.settings.response_channel;
        let reference_unit = calibrations.unit(reference_channel);
        let response_unit = calibrations.unit(response_channel);
        Self {
            result,
            reference_calibration: definitions
                .iter()
                .find(|c| c.channel == reference_channel)
                .cloned(),
            response_calibration: definitions
                .iter()
                .find(|c| c.channel == response_channel)
                .cloned(),
            response_unit_peak: format!("{response_unit} peak"),
            gain_unit: if reference_unit == response_unit {
                "ratio".into()
            } else {
                format!("{response_unit}/{reference_unit}")
            },
        }
    }
}

impl Document {
    pub(crate) fn validate_header(&self) -> Result<(), String> {
        if self.format != FORMAT
            || !(1..=VERSION).contains(&self.version)
            || (self.version >= 5 && self.scope.traces.len() != SCOPE_CHANNELS)
            || (self.version < 4 && self.comparison.is_some())
            || (self.version < 3 && self.external_output.is_some())
            || (self.version == 1
                && (self.generator_output.is_some()
                    || matches!(self.input.source, Source::Generator)))
            || self.channel_index_base != 0
            || self.sample_range_convention != "start inclusive, end exclusive"
            || self.sample_clock != "nominal input sample rate; no clock calibration"
        {
            return Err("Unsupported result format, version or sample convention".into());
        }
        Ok(())
    }
    pub fn capture(
        input: Input,
        scope: ScopeView<'_>,
        result: &spectrum::Result,
        info: &SpectrumInfo,
        requested_band_hz: [f64; 2],
        loss: Loss,
    ) -> Result<Self, String> {
        audio::validate_sample_rate(input.nominal_sample_rate_hz)?;
        let range = scope.sweep.range.clone();
        let retained = scope.history.range();
        if input.channels != scope.history.channels()
            || result.sample_rate() != input.nominal_sample_rate_hz
            || range.end < range.start
            || range.end - range.start > audio::MAX_SAMPLE_RATE as u64 * 2
            || (!range.is_empty() && (range.start < retained.start || range.end > retained.end))
            || !scope.sweep.sample_offset.is_finite()
            || !scope.settings.trigger.level.is_finite()
        {
            return Err("Held result conditions do not match retained samples".into());
        }
        if requested_band_hz.iter().any(|v| !v.is_finite()) {
            return Err("Band bounds must be finite".into());
        }
        let definitions = ChannelCalibration::capture(scope.calibrations);
        let raw = scope.measurements;
        let calibrated = scope.readings;
        let traces = (0..SCOPE_CHANNELS)
            .map(|i| {
                let channel = scope.settings.channels.0[i];
                let available = channel < input.channels;
                let samples: Option<Vec<_>> = available.then(|| {
                    range
                        .clone()
                        .map(|n| scope.history.get(n).map(|f| f[channel]))
                        .collect()
                });
                let missing = samples
                    .as_ref()
                    .map_or(0, |s| s.iter().filter(|v| v.is_none()).count() as u64);
                let state = if !available {
                    State::Unavailable
                } else if range.is_empty() {
                    State::Waiting
                } else if missing != 0 {
                    State::Partial
                } else {
                    State::Valid
                };
                let raw_reading = if raw[i].samples == 0 {
                    calibration::Reading::Unavailable
                } else {
                    calibration::Reading::Valid(raw[i])
                };
                Trace {
                    channel,
                    state,
                    missing_samples: missing,
                    calibration: definitions.iter().find(|d| d.channel == channel).cloned(),
                    raw_samples_fs: samples,
                    raw_statistics: Statistics::capture(raw_reading, "FS", missing),
                    calibrated_statistics: Statistics::capture(
                        calibrated[i],
                        scope.calibrations.unit(channel),
                        missing,
                    ),
                }
            })
            .collect();
        let window = result.window();
        let state = match result.validity() {
            spectrum::Validity::Waiting => State::Waiting,
            spectrum::Validity::NonFinite => State::NonFinite,
            spectrum::Validity::Valid => State::Valid,
        };
        if result.is_ready()
            && (result.power().len() != result.settings().size / 2 + 1
                || result
                    .power()
                    .iter()
                    .chain(result.hold_power())
                    .any(|v| !v.is_finite() || *v < 0.0))
        {
            return Err("Spectrum contains invalid linear values".into());
        }
        let value = |power: f64| match result.settings().quantity {
            Quantity::Amplitude => power.sqrt(),
            Quantity::Psd | Quantity::Esd => power,
        };
        let band = result
            .band(requested_band_hz[0], requested_band_hz[1])
            .map(|b| Band {
                requested_hz: b.requested_hz,
                inclusive_bins: [b.first_bin, b.last_bin],
                bin_centres_hz: [b.first_hz, b.last_hz],
                power: b.power,
                power_unit: result.power_unit(),
                rms: b.rms,
                rms_unit: result.unit().into(),
            });
        let spectrum = Spectrum {
            state,
            channel: window.as_ref().map(|w| w.channel),
            latest_window: window.as_ref().map(|w| w.start..w.end),
            settings: result.settings(),
            mode: info.mode,
            observation_interval_ms: info.observation_ms,
            bin_width_hz: result.sample_rate() as f64 / result.settings().size as f64,
            rbw_hz: result.rbw_hz(),
            calibration: window.as_ref().and_then(|w| {
                w.calibration.as_ref().map(|c| ChannelCalibration {
                    channel: w.channel,
                    id: c.id().into(),
                    revision: c.revision(),
                    gain: c.gain(),
                    offset: c.offset(),
                    unit: c.unit().into(),
                    conditions: c.conditions().into(),
                })
            }),
            unit: result
                .settings()
                .quantity
                .calibrated_linear_unit(result.calibration()),
            average: result
                .is_ready()
                .then(|| result.average())
                .flatten()
                .map(|a| Average {
                    alpha: 1.0 / result.settings().averages as f64,
                    processed_windows: a.updates,
                    contributing_envelope: a.start..a.end,
                }),
            values: result
                .is_ready()
                .then(|| result.power().iter().copied().map(value).collect()),
            peak_hold: result.hold_info().map(|h| PeakHold {
                considered_spectra: h.spectra,
                contributing_envelope: h.start..h.end,
                values: result.hold_power().iter().copied().map(value).collect(),
            }),
            requested_band_hz,
            band,
            diagnostics: Diagnostics {
                processed_windows_since_reset: info.updates,
                missing_windows: info.missing_windows,
                nonfinite_windows: info.invalid_windows,
                missing_input_samples: info.input_missing,
                missed_observations: info.missed_observations,
                input_end: info.input_end,
                filled_samples: info.filled_samples,
            },
        };
        Ok(Self {
            lockin: None,
            comparison: None,
            generator_output: None,
            external_output: None,
            format: FORMAT.into(),
            version: VERSION,
            app_version: env!("CARGO_PKG_VERSION").into(),
            exported_unix_seconds: std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map_err(|e| e.to_string())?
                .as_secs(),
            channel_index_base: 0,
            sample_range_convention: "start inclusive, end exclusive".into(),
            sample_clock: "nominal input sample rate; no clock calibration".into(),
            input,
            retained_history: retained,
            scope: Scope {
                acquisition_mode: scope.settings.mode,
                sample_range: range,
                observation_samples: scope.settings.samples,
                trigger: scope.settings.trigger,
                triggered: scope.sweep.triggered,
                horizontal_sample_offset: scope.sweep.sample_offset,
                traces,
            },
            spectrum,
            loss,
        })
    }
}

pub fn save(path: &Path, document: &Document) -> Result<(), String> {
    // serde_json otherwise silently represents a nonfinite float as null.
    // Null is reserved for deliberately missing/unavailable measurements.
    let spectrum = &document.spectrum;
    let valid_statistics = document.scope.traces.iter().all(|trace| {
        trace
            .raw_samples_fs
            .as_ref()
            .is_none_or(|samples| samples.iter().flatten().all(|v| v.is_finite()))
            && [&trace.raw_statistics, &trace.calibrated_statistics]
                .iter()
                .all(|s| {
                    s.values.as_ref().is_none_or(|v| {
                        [v.rms, v.peak, v.peak_to_peak]
                            .iter()
                            .all(|v| v.is_finite())
                    })
                })
    });
    let valid_spectrum = spectrum
        .values
        .as_ref()
        .is_none_or(|v| v.iter().all(|v| v.is_finite() && *v >= 0.0))
        && spectrum
            .peak_hold
            .as_ref()
            .is_none_or(|h| h.values.iter().all(|v| v.is_finite() && *v >= 0.0))
        && spectrum.band.as_ref().is_none_or(|b| {
            b.requested_hz
                .iter()
                .chain(&b.bin_centres_hz)
                .chain([&b.power, &b.rms])
                .all(|v| v.is_finite())
        })
        && spectrum.requested_band_hz.iter().all(|v| v.is_finite())
        && [spectrum.bin_width_hz, spectrum.rbw_hz]
            .iter()
            .all(|v| v.is_finite())
        && spectrum
            .average
            .as_ref()
            .is_none_or(|a| a.alpha.is_finite());
    let valid_calibration = document
        .scope
        .traces
        .iter()
        .filter_map(|t| t.calibration.as_ref())
        .chain(spectrum.calibration.as_ref())
        .all(|c| c.gain.is_finite() && c.offset.is_finite());
    if !valid_statistics
        || !valid_spectrum
        || !valid_calibration
        || !document.scope.horizontal_sample_offset.is_finite()
        || !document.scope.trigger.level.is_finite()
    {
        return Err("Cannot export nonfinite numbers; invalidate the measurement first".into());
    }
    if let Some(lockin) = &document.lockin {
        lockin.validate(
            document.input.nominal_sample_rate_hz,
            document.input.channels,
            spectrum.diagnostics.input_end,
        )?;
    }
    document.validate()?;
    crate::file_io::atomic_write(path, |file| {
        let mut writer = BufWriter::new(file);
        serde_json::to_writer_pretty(&mut writer, document).map_err(std::io::Error::other)?;
        writer.write_all(b"\n")?;
        writer.flush()
    })
}

pub enum Event {
    Saved(PathBuf),
    Error(String),
}

/// One outstanding export per UI, independent of acquisition and settings I/O.
pub struct Worker {
    requests: Option<mpsc::SyncSender<(PathBuf, Document)>>,
    pub events: mpsc::Receiver<Event>,
    handle: Option<JoinHandle<()>>,
}

impl Default for Worker {
    fn default() -> Self {
        let (requests, receiver) = mpsc::sync_channel::<(PathBuf, Document)>(1);
        let (events, responses) = mpsc::channel();
        let handle = thread::spawn(move || {
            while let Ok((path, document)) = receiver.recv() {
                let event = save(&path, &document)
                    .map(|()| Event::Saved(path))
                    .unwrap_or_else(Event::Error);
                if events.send(event).is_err() {
                    break;
                }
            }
        });
        Self {
            requests: Some(requests),
            events: responses,
            handle: Some(handle),
        }
    }
}

impl Worker {
    pub fn submit(&self, path: PathBuf, document: Document) -> Result<(), String> {
        self.requests
            .as_ref()
            .unwrap()
            .try_send((path, document))
            .map_err(|e| format!("Export worker unavailable: {e}"))
    }
}

impl Drop for Worker {
    fn drop(&mut self) {
        self.requests.take();
        if let Some(handle) = self.handle.take() {
            let _ = handle.join();
        }
    }
}

#[cfg(test)]
pub(crate) mod tests {
    use super::*;
    use crate::{
        calibration::{Calibration, Set},
        channel::Pair,
        signal::Trigger,
        spectrum::{Analyzer, Window},
    };
    use std::{f64::consts::TAU, time::Duration};

    pub(crate) fn input(channels: usize) -> Input {
        Input {
            generation: 42,
            source: Source::Audio {
                device_id: Some("reference:16ch".into()),
                device_name: "Known input".into(),
                sample_format: "f64".into(),
                requested_sample_rate_hz: Some(48_000),
            },
            nominal_sample_rate_hz: 48_000,
            channels,
        }
    }

    pub(crate) fn document(
        history: &History,
        result: &spectrum::Result,
        set: &Set,
        channels: Pair,
    ) -> Document {
        let channels = channels.scope();
        Document::capture(
            input(history.channels()),
            ScopeView {
                history,
                settings: ScopeSettings {
                    mode: crate::acquisition::Mode::Auto,
                    channels,
                    samples: history.len(),
                    trigger: Trigger::default(),
                },
                sweep: Sweep {
                    range: history.range(),
                    triggered: true,
                    sample_offset: 0.125,
                },
                calibrations: set,
                measurements: crate::signal::measure(history, history.range(), channels),
                readings: calibration::measure(history, history.range(), channels, set),
            },
            result,
            &SpectrumInfo {
                mode: SpectrumMode::Continuous,
                updates: result.average().map_or(0, |a| a.updates),
                filled_samples: history.len(),
                input_end: history.range().end,
                ..Default::default()
            },
            [0.0, 24_000.0],
            Loss {
                capture_dropped_samples: 3,
                scope_missing_samples: 2,
                display_snapshots_skipped_since_worker_start: 7,
                input_failed: false,
            },
        )
        .unwrap()
    }

    #[test]
    fn esd_calibrated_pulse_roundtrips_json_csv_and_keeps_density_values() {
        let mut history = History::new(1024);
        for n in 0..1024 {
            history.push([if n == 17 { 0.25 } else { 0.0 }, 0.0]);
        }
        let set = Set::default()
            .with(
                0,
                Some(
                    Calibration::new(
                        "voltage-pulse".into(),
                        1,
                        -4.0,
                        0.0,
                        "V".into(),
                        "Known pulse".into(),
                    )
                    .unwrap(),
                ),
            )
            .unwrap();
        let mut settings = Settings {
            size: 1024,
            ..Settings::default()
        };
        settings.select_quantity(Quantity::Esd);
        let mut analyzer = Analyzer::new(settings, 48000);
        analyzer.set_calibration(set.get(0).cloned().map(std::sync::Arc::new));
        analyzer.update_window(&history, 0..1024, 0);
        let mut result = spectrum::Result::empty(settings, 48000);
        analyzer.copy_result(&mut result);
        let doc = document(&history, &result, &set, Pair([0, 1]));
        doc.validate().unwrap();
        let path = std::env::temp_dir().join(format!("measurelab-esd-{}.json", std::process::id()));
        save(&path, &doc).unwrap();
        let restored = crate::results::load(&path).unwrap();
        assert_eq!(restored, doc);
        assert_eq!(restored.spectrum.unit, "V²·s/Hz");
        assert!(restored.spectrum.band.is_none());
        assert_eq!(result.db_unit(), "dB re 1 V²·s/Hz");
        let values = restored.spectrum.values.as_ref().unwrap();
        assert_eq!(values, result.power());
        assert_eq!(
            restored.spectrum.peak_hold.as_ref().unwrap().values,
            values.as_slice()
        );
        assert!(
            (values.iter().sum::<f64>() * restored.spectrum.bin_width_hz - 1.0 / 48000.0).abs()
                < 1e-17
        );
        let csv = path.with_extension("csv");
        crate::results::save_csv(&csv, &restored).unwrap();
        let text = std::fs::read_to_string(&csv).unwrap();
        let row: Vec<_> = text
            .lines()
            .find(|line| line.starts_with("spectrum,0,1,"))
            .unwrap()
            .split(',')
            .collect();
        assert_eq!(row[4].parse::<f64>().unwrap(), values[1]);
        assert_eq!(row[5], "\"V²·s/Hz\"");
        std::fs::remove_file(path).unwrap();
        std::fs::remove_file(csv).unwrap();
    }

    #[test]
    fn exported_calibrated_samples_psd_and_metadata_reproduce_known_values() {
        let mut history = History::with_channels(1024, 16);
        for n in 0..1024 {
            let mut frame = [0.0; 16];
            frame[15] = 0.125 + 0.25 * (TAU * 16.0 * n as f64 / 1024.0).sin();
            frame[7] = 0.123456789012345 + 1e-12 * n as f64;
            history.push(frame);
        }
        let set = Set::default()
            .with(
                15,
                Some(
                    Calibration::new(
                        "voltage-ref".into(),
                        3,
                        -4.0,
                        1.0,
                        "V".into(),
                        "Known affine test, no ADC".into(),
                    )
                    .unwrap(),
                ),
            )
            .unwrap();
        let settings = Settings {
            size: 1024,
            quantity: Quantity::Psd,
            window: Window::Rectangular,
            remove_dc: false,
            averages: 1,
            ..Default::default()
        };
        let mut analyzer = Analyzer::new(settings, 48_000);
        analyzer.set_calibration(set.get(15).cloned().map(std::sync::Arc::new));
        assert!(analyzer.update_window(&history, 0..1024, 15));
        let mut result = spectrum::Result::empty(settings, 48_000);
        analyzer.copy_result(&mut result);
        let doc = document(&history, &result, &set, Pair([15, 7]));
        let json: serde_json::Value =
            serde_json::from_slice(&serde_json::to_vec(&doc).unwrap()).unwrap();
        assert_eq!(json["format"], FORMAT);
        assert_eq!(json["version"], VERSION);
        assert_eq!(json["channel_index_base"], 0);
        assert_eq!(json["input"]["generation"], 42);
        assert_eq!(json["input"]["source"]["device_id"], "reference:16ch");
        assert_eq!(json["scope"]["traces"][0]["calibration"]["revision"], 3);
        assert_eq!(json["spectrum"]["channel"], 15);
        assert_eq!(json["spectrum"]["unit"], "V²/Hz");
        assert_eq!(json["spectrum"]["latest_window"]["end"], 1024);
        assert_eq!(json["spectrum"]["average"]["alpha"], 1.0);
        assert_eq!(
            json["loss"]["display_snapshots_skipped_since_worker_start"],
            7
        );
        let samples = json["scope"]["traces"][1]["raw_samples_fs"]
            .as_array()
            .unwrap();
        for (n, value) in samples.iter().enumerate() {
            assert_eq!(
                value.as_f64().unwrap().to_bits(),
                history.get(n as u64).unwrap()[7].to_bits()
            );
        }
        let calibrated: Vec<_> = doc.scope.traces[0]
            .raw_samples_fs
            .as_ref()
            .unwrap()
            .iter()
            .map(|v| set.value(15, v.unwrap()).unwrap())
            .collect();
        let power: f64 = calibrated.iter().map(|v| v * v).sum::<f64>() / 1024.0;
        assert!((power - 0.75).abs() < 1e-14);
        assert!(
            (doc.scope.traces[0]
                .calibrated_statistics
                .values
                .as_ref()
                .unwrap()
                .rms
                - power.sqrt())
            .abs()
                < 1e-14
        );
        let bins = json["spectrum"]["values"].as_array().unwrap();
        for (saved, original) in bins.iter().zip(result.power()) {
            assert_eq!(saved.as_f64().unwrap().to_bits(), original.to_bits());
        }
        let integrated: f64 =
            bins.iter().map(|v| v.as_f64().unwrap()).sum::<f64>() * doc.spectrum.bin_width_hz;
        assert!((integrated - power).abs() < 1e-14);
        assert!((doc.spectrum.band.as_ref().unwrap().power - integrated).abs() < 1e-14);
        history.clear_at(100_000);
        result.clear_hold();
        assert_eq!(doc.scope.sample_range, 0..1024);
        assert_eq!(doc.input.generation, 42);
        assert_eq!(doc.scope.traces[0].calibration.as_ref().unwrap().gain, -4.0);
    }

    #[test]
    fn gaps_unavailable_channels_and_invalid_results_never_export_zero_substitutes() {
        let mut history = History::with_channels(16, 1);
        history.push_at(7, [0.25]);
        history.push_at(10, [-0.25]);
        let settings = Settings {
            size: 1024,
            ..Default::default()
        };
        let mut result = spectrum::Result::empty(settings, 48_000);
        let set = Set::default()
            .with(
                0,
                Some(
                    Calibration::new(
                        "overflow".into(),
                        1,
                        1e308,
                        1.7e308,
                        "V".into(),
                        "Overflow test".into(),
                    )
                    .unwrap(),
                ),
            )
            .unwrap();
        let doc = document(&history, &result, &set, Pair([0, 15]));
        assert_eq!(doc.scope.sample_range, 7..11);
        assert_eq!(
            doc.scope.traces[0].raw_samples_fs,
            Some(vec![Some(0.25), None, None, Some(-0.25)])
        );
        assert_eq!(doc.scope.traces[0].missing_samples, 2);
        assert_eq!(doc.scope.traces[0].raw_statistics.state, State::Partial);
        assert_eq!(doc.scope.traces[0].raw_statistics.acquired_samples, 2);
        assert_eq!(
            doc.scope.traces[0].calibrated_statistics.state,
            State::NonFinite
        );
        assert!(doc.scope.traces[0].calibrated_statistics.values.is_none());
        assert_eq!(doc.scope.traces[1].state, State::Unavailable);
        assert!(doc.scope.traces[1].raw_samples_fs.is_none());
        assert_eq!(doc.spectrum.state, State::Waiting);
        assert!(doc.spectrum.values.is_none());
        let mut analyzer = Analyzer::new(settings, 48_000);
        analyzer.invalidate(1024, 0);
        analyzer.copy_result(&mut result);
        let invalid = document(&history, &result, &set, Pair([0, 15]));
        assert_eq!(invalid.spectrum.state, State::NonFinite);
        assert_eq!(invalid.spectrum.latest_window, Some(0..1024));
        assert!(invalid.spectrum.values.is_none());
        assert!(invalid.spectrum.average.is_none());
        assert!(invalid.spectrum.peak_hold.is_none());
        assert!(invalid.spectrum.band.is_none());
        let json = serde_json::to_value(&invalid).unwrap();
        assert!(json["spectrum"]["values"].is_null());
    }

    #[test]
    fn amplitude_zero_and_weak_bins_hold_and_ema_keep_f64_units_and_intervals() {
        for averages in [1, 4] {
            let settings = Settings {
                size: 1024,
                window: Window::Rectangular,
                averages,
                remove_dc: false,
                ..Settings::default()
            };
            let mut analyzer = Analyzer::new(settings, 48_000);
            let samples: Vec<_> = (0..1024)
                .map(|n| 1e-12 * (TAU * 32.0 * n as f64 / 1024.0).cos())
                .collect();
            assert!(analyzer.update_samples(&samples, 1024));
            assert!(analyzer.update_samples(&samples, 1280));
            let hold = analyzer.hold_info().unwrap();
            assert_eq!((hold.start, hold.end, hold.spectra), (0, 1280, 2));
            analyzer.clear_hold();
            let start = if averages == 1 { 256 } else { 0 };
            assert_eq!(
                analyzer.hold_info().unwrap(),
                spectrum::HoldInfo {
                    start,
                    end: 1280,
                    spectra: 1
                }
            );
            assert!(analyzer.update_samples(&vec![0.0; 1024], 1536));
            let mut result = spectrum::Result::empty(settings, 48_000);
            analyzer.copy_result(&mut result);
            assert_eq!(result.hold_info(), analyzer.hold_info());
            let mut history = History::with_channels(16, 1);
            history.push_at(1535, [0.0]);
            let doc = document(&history, &result, &Set::default(), Pair([0, 0]));
            assert_eq!(doc.spectrum.unit, "FS peak");
            let peak = doc.spectrum.peak_hold.as_ref().unwrap();
            assert_eq!(peak.contributing_envelope, start..1536);
            assert_eq!(peak.considered_spectra, 2);
            assert!((peak.values[32] / 1e-12 - 1.0).abs() < 1e-14);
            assert!(
                doc.spectrum
                    .values
                    .as_ref()
                    .unwrap()
                    .iter()
                    .all(|v| v.is_finite())
            );
            if averages == 1 {
                assert!(
                    doc.spectrum
                        .values
                        .as_ref()
                        .unwrap()
                        .iter()
                        .all(|v| *v == 0.0)
                );
            }
            result.clear_hold();
            assert_eq!(result.hold_info().unwrap().spectra, 1);
            analyzer.reset();
            assert!(analyzer.hold_info().is_none());
        }
    }

    #[test]
    fn result_worker_writes_a_complete_file_and_reports_failure_without_losing_previous_results() {
        let root = std::env::temp_dir().join(format!(
            "measurelab-export-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        let path = root.join("results.json");
        let mut history = History::with_channels(16, 1);
        history.push([0.123456789012345]);
        let result = spectrum::Result::empty(Settings::default(), 48_000);
        let doc = document(&history, &result, &Set::default(), Pair([0, 15]));
        let worker = Worker::default();
        worker.submit(path.clone(), doc.clone()).unwrap();
        assert!(
            matches!(worker.events.recv_timeout(Duration::from_secs(5)).unwrap(), Event::Saved(p) if p == path)
        );
        let bytes = std::fs::read(&path).unwrap();
        let json: serde_json::Value = serde_json::from_slice(&bytes).unwrap();
        assert_eq!(
            json["scope"]["traces"][0]["raw_samples_fs"][0]
                .as_f64()
                .unwrap()
                .to_bits(),
            0.123456789012345_f64.to_bits()
        );
        assert!(
            crate::file_io::atomic_write(&path, |file| {
                file.write_all(b"partial JSON")?;
                Err(std::io::Error::other("injected write failure"))
            })
            .is_err()
        );
        assert_eq!(std::fs::read(&path).unwrap(), bytes);
        let mut invalid = doc.clone();
        invalid.spectrum.values = Some(vec![f64::NAN]);
        assert!(save(&path, &invalid).is_err());
        assert_eq!(std::fs::read(&path).unwrap(), bytes);
        worker
            .submit(path.join("blocked.json"), doc.clone())
            .unwrap();
        assert!(matches!(
            worker.events.recv_timeout(Duration::from_secs(5)).unwrap(),
            Event::Error(_)
        ));
        assert_eq!(std::fs::read(&path).unwrap(), bytes);
        worker.submit(path.clone(), doc).unwrap();
        assert!(matches!(
            worker.events.recv_timeout(Duration::from_secs(5)).unwrap(),
            Event::Saved(_)
        ));
        assert_eq!(std::fs::read_dir(&root).unwrap().count(), 1);
        drop(worker);
        std::fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn largest_fft_exports_every_f64_bin_including_dc_and_nyquist() {
        let settings = Settings {
            size: 524_288,
            quantity: Quantity::Psd,
            averages: 1,
            window: Window::Rectangular,
            remove_dc: false,
            ..Settings::default()
        };
        let samples: Vec<_> = (0..settings.size)
            .map(|n| 0.125 + 0.25 * if n % 2 == 0 { 1.0 } else { -1.0 })
            .collect();
        let mut analyzer = Analyzer::new(settings, 48_000);
        assert!(analyzer.update_samples(&samples, settings.size as u64));
        let mut result = spectrum::Result::empty(settings, 48_000);
        analyzer.copy_result(&mut result);
        let mut history = History::with_channels(16, 1);
        history.push_at(settings.size as u64 - 1, [-0.125]);
        let doc = document(&history, &result, &Set::default(), Pair([0, 0]));
        let json: serde_json::Value =
            serde_json::from_slice(&serde_json::to_vec(&doc).unwrap()).unwrap();
        let bins = json["spectrum"]["values"].as_array().unwrap();
        assert_eq!(bins.len(), 262_145);
        assert_eq!(
            json["spectrum"]["peak_hold"]["values"]
                .as_array()
                .unwrap()
                .len(),
            bins.len()
        );
        for (saved, original) in bins.iter().zip(result.power()) {
            assert_eq!(saved.as_f64().unwrap().to_bits(), original.to_bits());
        }
        assert!(
            (bins[0].as_f64().unwrap() * doc.spectrum.bin_width_hz - 0.125_f64.powi(2)).abs()
                < 1e-14
        );
        assert!(
            (bins[262_144].as_f64().unwrap() * doc.spectrum.bin_width_hz - 0.25_f64.powi(2)).abs()
                < 1e-14
        );
    }
}
