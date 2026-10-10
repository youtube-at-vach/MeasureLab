//! Versioned measurement settings. File I/O never runs on acquisition or DSP.
//! Restoring this document has no command to start input, output or recording.
use crate::{
    audio::{self, DeviceInfo},
    calibration::{self, Calibration},
    channel::{ChannelId, Pair},
    measurement::SpectrumMode,
    signal::{MAX_CHANNELS, Trigger},
    spectrum::{FFT_SIZES, FrequencyScale, Quantity, STFT_SIZES, Settings},
    xy::CursorMode,
};
use serde::{Deserialize, Serialize};
use std::{
    fs::{File, OpenOptions},
    io::{Read, Write},
    path::{Path, PathBuf},
    sync::mpsc,
    thread::{self, JoinHandle},
};

pub const VERSION: u32 = 1;
pub const MAX_BYTES: usize = 64 * 1024;

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Input {
    /// CPAL's backend-qualified device ID. Never an enumeration index or name.
    pub device_id: String,
    pub device_name: String,
    pub channels: u16,
    pub device_default_sample_rate: u32,
    /// None means device default, not the rate of a previously held result.
    pub sample_rate: Option<u32>,
}

impl Input {
    pub fn from_device(device: &DeviceInfo, sample_rate: Option<u32>) -> Result<Self, String> {
        Ok(Self {
            device_id: device.id.clone().ok_or("Input has no stable device ID")?,
            device_name: device.name.clone(),
            channels: device.channels,
            device_default_sample_rate: device.default_sample_rate,
            sample_rate,
        })
    }

    /// Resolve only an unambiguous stable ID and the original channel topology.
    /// A missing input or unsupported rate never selects another device/rate.
    pub fn resolve(&self, devices: &[DeviceInfo]) -> Result<usize, String> {
        let mut matches = devices
            .iter()
            .enumerate()
            .filter(|(_, device)| device.id.as_deref() == Some(&self.device_id));
        let (index, device) = matches
            .next()
            .ok_or_else(|| format!("Saved input is unavailable: {}", self.device_name))?;
        if matches.next().is_some() {
            return Err("Saved input ID is ambiguous; refresh devices".into());
        }
        if device.channels != self.channels {
            return Err(format!(
                "Saved input channel count changed: {} → {}",
                self.channels, device.channels
            ));
        }
        if let Some(rate) = self.sample_rate
            && !device.sample_rates.contains(&rate)
        {
            return Err(format!("Saved input does not support {rate} Hz"));
        }
        if self.sample_rate.is_none()
            && self.device_default_sample_rate != device.default_sample_rate
        {
            return Err("Saved device default sample rate changed; choose an explicit rate or save new settings".into());
        }
        Ok(index)
    }

    pub fn expected_sample_rate(&self) -> u32 {
        self.sample_rate.unwrap_or(self.device_default_sample_rate)
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Scope {
    pub channels: Pair,
    pub ms_per_div: f32,
    pub trigger: Trigger,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Spectrum {
    pub channel: ChannelId,
    pub analysis: Settings,
    pub mode: SpectrumMode,
    pub band_min_hz: f64,
    pub band_max_hz: f64,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Spectrogram {
    pub channel: ChannelId,
    pub analysis: Settings,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Xy {
    pub channels: Pair,
    pub milliseconds: f64,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ChannelCalibration {
    pub channel: ChannelId,
    pub id: String,
    pub revision: u64,
    pub gain: f64,
    pub offset: f64,
    pub unit: String,
    pub conditions: String,
}

impl ChannelCalibration {
    pub fn capture(set: &calibration::Set) -> Vec<Self> {
        (0..MAX_CHANNELS)
            .filter_map(|channel| {
                set.get(channel).map(|definition| Self {
                    channel,
                    id: definition.id().into(),
                    revision: definition.revision(),
                    gain: definition.gain(),
                    offset: definition.offset(),
                    unit: definition.unit().into(),
                    conditions: definition.conditions().into(),
                })
            })
            .collect()
    }

    fn definition(&self) -> Result<Calibration, String> {
        Calibration::new(
            self.id.clone(),
            self.revision,
            self.gain,
            self.offset,
            self.unit.clone(),
            self.conditions.clone(),
        )
        .map_err(str::to_owned)
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Measurement {
    pub input: Input,
    pub scope: Scope,
    pub spectrum: Spectrum,
    pub spectrogram: Spectrogram,
    pub xy: Xy,
    pub calibrations: Vec<ChannelCalibration>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PlotLayout {
    Auto,
    Columns,
    Rows,
}

/// Display preferences are separate from input and analysis conditions.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Workspace {
    pub visible: [bool; 4],
    pub layout: PlotLayout,
    pub sidebar_visible: bool,
    pub scope_enabled: [bool; 2],
    pub scope_fs_per_div: f32,
    pub spectrum_scale: FrequencyScale,
    pub spectrum_min_hz: f32,
    pub spectrum_max_hz: f32,
    pub spectrum_floor_db: f32,
    pub spectrum_ceiling_db: f32,
    pub spectrum_show_hold: bool,
    pub spectrogram_scale: FrequencyScale,
    pub spectrogram_min_hz: f32,
    pub spectrogram_max_hz: f32,
    pub spectrogram_floor_db: f32,
    pub spectrogram_ceiling_db: f32,
    pub spectrogram_seconds: f64,
    pub xy_x_fs_per_div: f64,
    pub xy_y_fs_per_div: f64,
    pub xy_cursor_mode: CursorMode,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Document {
    pub version: u32,
    pub measurement: Measurement,
    pub workspace: Workspace,
}

impl Document {
    /// Check the whole document before exposing any restored state to the app.
    pub fn validate(&self) -> Result<calibration::Set, String> {
        if self.version != VERSION {
            return Err(format!("Unsupported settings version: {}", self.version));
        }
        let m = &self.measurement;
        bounded_text(&m.input.device_id, 4096, "device ID")?;
        bounded_text(&m.input.device_name, 1024, "device name")?;
        if !(1..=MAX_CHANNELS as u16).contains(&m.input.channels) {
            return Err("Input channel count must be 1–16".into());
        }
        if let Some(rate) = m.input.sample_rate {
            audio::validate_sample_rate(rate)?;
        }
        audio::validate_sample_rate(m.input.device_default_sample_rate)?;
        for channel in m
            .scope
            .channels
            .0
            .into_iter()
            .chain(m.xy.channels.0)
            .chain([
                m.scope.trigger.channel,
                m.spectrum.channel,
                m.spectrogram.channel,
            ])
        {
            if channel >= MAX_CHANNELS {
                return Err("Channel ID is outside 0–15".into());
            }
        }
        // Scope/XY can intentionally keep unavailable assignments. The current
        // FFT/STFT setup requires an acquired channel; do not silently clamp it.
        if m.spectrum.channel >= m.input.channels as usize
            || m.spectrogram.channel >= m.input.channels as usize
        {
            return Err("Spectrum/Spectrogram source is unavailable on the saved input".into());
        }
        in_range(
            m.scope.ms_per_div as f64,
            0.05_f32 as f64,
            100.0,
            "Scope timebase",
        )?;
        in_range(m.scope.trigger.level, -1.0, 1.0, "trigger level")?;
        analysis(m.spectrum.analysis, &FFT_SIZES)?;
        analysis(m.spectrogram.analysis, &STFT_SIZES)?;
        if m.spectrogram.analysis.quantity != Quantity::Amplitude
            || m.spectrogram.analysis.averages != 1
        {
            return Err("Spectrogram requires amplitude without averaging".into());
        }
        frequency_range(m.spectrum.band_min_hz, m.spectrum.band_max_hz)?;
        in_range(m.xy.milliseconds, 0.5, 200.0, "XY observation window")?;
        let mut set = calibration::Set::default();
        let mut seen = [false; MAX_CHANNELS];
        if m.calibrations.len() > MAX_CHANNELS {
            return Err("Too many calibration definitions".into());
        }
        for definition in &m.calibrations {
            if definition.channel >= MAX_CHANNELS || seen[definition.channel] {
                return Err("Calibration channels must be unique IDs in 0–15".into());
            }
            seen[definition.channel] = true;
            set = set
                .with(definition.channel, Some(definition.definition()?))
                .map_err(str::to_owned)?;
        }
        let w = &self.workspace;
        if !w.visible.contains(&true) {
            return Err("At least one instrument must be visible".into());
        }
        for scale in [
            w.scope_fs_per_div as f64,
            w.xy_x_fs_per_div,
            w.xy_y_fs_per_div,
        ] {
            in_range(scale, 0.001, 0.5, "amplitude scale")?;
        }
        frequency_range(w.spectrum_min_hz as f64, w.spectrum_max_hz as f64)?;
        frequency_range(w.spectrogram_min_hz as f64, w.spectrogram_max_hz as f64)?;
        in_range(w.spectrum_floor_db as f64, -180.0, -60.0, "Spectrum floor")?;
        in_range(
            w.spectrum_ceiling_db as f64,
            w.spectrum_floor_db as f64 + 6.0,
            3200.0,
            "Spectrum ceiling",
        )?;
        in_range(
            w.spectrogram_floor_db as f64,
            -180.0,
            -20.0,
            "Spectrogram floor",
        )?;
        in_range(
            w.spectrogram_ceiling_db as f64,
            -20.0,
            6.0,
            "Spectrogram ceiling",
        )?;
        in_range(w.spectrogram_seconds, 0.5, 20.0, "Spectrogram time span")?;
        Ok(set)
    }

    pub fn decode(bytes: &[u8]) -> Result<Self, String> {
        if bytes.len() > MAX_BYTES {
            return Err("Settings file exceeds 64 KiB".into());
        }
        #[derive(Deserialize)]
        struct Header {
            version: u32,
        }
        let header: Header = serde_json::from_slice(bytes).map_err(|e| e.to_string())?;
        if header.version != VERSION {
            return Err(format!("Unsupported settings version: {}", header.version));
        }
        let document: Self = serde_json::from_slice(bytes).map_err(|e| e.to_string())?;
        document.validate()?;
        Ok(document)
    }

    pub fn encode(&self) -> Result<Vec<u8>, String> {
        self.validate()?;
        let mut bytes = serde_json::to_vec_pretty(self).map_err(|e| e.to_string())?;
        bytes.push(b'\n');
        if bytes.len() > MAX_BYTES {
            return Err("Settings file exceeds 64 KiB".into());
        }
        Ok(bytes)
    }
}

fn bounded_text(value: &str, max: usize, name: &str) -> Result<(), String> {
    if value.trim().is_empty() || value.len() > max || value.chars().any(char::is_control) {
        return Err(format!("Invalid {name}"));
    }
    Ok(())
}

fn in_range(value: f64, min: f64, max: f64, name: &str) -> Result<(), String> {
    if !value.is_finite() || !(min..=max).contains(&value) {
        return Err(format!("Invalid {name}: expected {min}–{max}"));
    }
    Ok(())
}

fn analysis(settings: Settings, sizes: &[usize]) -> Result<(), String> {
    if !sizes.contains(&settings.size) || ![1, 4, 16, 64].contains(&settings.averages) {
        return Err("Unsupported FFT size or EMA setting".into());
    }
    Ok(())
}

fn frequency_range(min: f64, max: f64) -> Result<(), String> {
    in_range(
        min,
        0.0,
        audio::MAX_SAMPLE_RATE as f64 / 2.0,
        "lower frequency",
    )?;
    in_range(
        max,
        0.0,
        audio::MAX_SAMPLE_RATE as f64 / 2.0,
        "upper frequency",
    )?;
    if max != 0.0 && min > max {
        return Err("Frequency range must increase; To = 0 selects Nyquist".into());
    }
    Ok(())
}

pub fn default_path() -> Result<PathBuf, String> {
    #[cfg(target_os = "windows")]
    let base = std::env::var_os("APPDATA").map(PathBuf::from);
    #[cfg(not(target_os = "windows"))]
    let base = std::env::var_os("HOME").map(|home| {
        let home = PathBuf::from(home);
        #[cfg(target_os = "macos")]
        {
            home.join("Library/Application Support")
        }
        #[cfg(not(target_os = "macos"))]
        {
            std::env::var_os("XDG_CONFIG_HOME").map_or_else(|| home.join(".config"), PathBuf::from)
        }
    });
    base.map(|base| base.join("MeasureLab/measurement-settings.json"))
        .ok_or_else(|| "User settings directory is unavailable; enter a file path".into())
}

pub fn load(path: &Path) -> Result<Document, String> {
    let file = File::open(path).map_err(|e| e.to_string())?;
    let mut bytes = Vec::new();
    file.take(MAX_BYTES as u64 + 1)
        .read_to_end(&mut bytes)
        .map_err(|e| e.to_string())?;
    Document::decode(&bytes)
}

/// Write beside the destination, then replace it only after a complete flush.
/// An invalid document or failed write leaves the previous file intact.
pub fn save(path: &Path, document: &Document) -> Result<(), String> {
    let bytes = document.encode()?;
    let parent = path
        .parent()
        .filter(|p| !p.as_os_str().is_empty())
        .unwrap_or(Path::new("."));
    let filename = path.file_name().ok_or("Enter a settings file path")?;
    std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    let suffix = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_err(|e| e.to_string())?
        .as_nanos();
    let temporary = parent.join(format!(
        ".{}.{}.{suffix}.tmp",
        filename.to_string_lossy(),
        std::process::id()
    ));
    let mut options = OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let mut file = options.open(&temporary).map_err(|e| e.to_string())?;
    let result = (|| {
        file.write_all(&bytes)?;
        file.sync_all()?;
        drop(file);
        std::fs::rename(&temporary, path)
    })();
    if result.is_err() {
        let _ = std::fs::remove_file(&temporary);
    }
    result.map_err(|e| e.to_string())
}

pub enum Operation {
    Save(Box<Document>),
    Restore,
}

pub enum Event {
    Saved(PathBuf),
    Restored(PathBuf, Box<Document>),
    Error(String),
}

/// The UI submits at most one outstanding operation. The bounded request queue
/// cannot accumulate file writes, and neither acquisition nor DSP uses it.
pub struct Worker {
    requests: Option<mpsc::SyncSender<(PathBuf, Operation)>>,
    pub events: mpsc::Receiver<Event>,
    handle: Option<JoinHandle<()>>,
}

impl Default for Worker {
    fn default() -> Self {
        let (requests, receiver) = mpsc::sync_channel::<(PathBuf, Operation)>(1);
        let (events, responses) = mpsc::channel();
        let handle = thread::spawn(move || {
            while let Ok((path, operation)) = receiver.recv() {
                let result = match operation {
                    Operation::Save(document) => {
                        save(&path, &document).map(|()| Event::Saved(path))
                    }
                    Operation::Restore => {
                        load(&path).map(|document| Event::Restored(path, Box::new(document)))
                    }
                };
                if events.send(result.unwrap_or_else(Event::Error)).is_err() {
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
    pub fn submit(&self, path: PathBuf, operation: Operation) -> Result<(), String> {
        self.requests
            .as_ref()
            .unwrap()
            .try_send((path, operation))
            .map_err(|e| format!("Settings worker unavailable: {e}"))
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
mod tests {
    use super::*;
    use crate::{
        calibration::Reading,
        signal::{Edge, History},
        spectrum::{Analyzer, Precision, Window},
    };

    fn fixture() -> Document {
        Document {
            version: VERSION,
            measurement: Measurement {
                input: Input {
                    device_id: "coreaudio:reference-device".into(),
                    device_name: "Reference 16ch".into(),
                    channels: 16,
                    device_default_sample_rate: 48_000,
                    sample_rate: Some(48_000),
                },
                scope: Scope {
                    channels: Pair([15, 7]),
                    ms_per_div: 10.0,
                    trigger: Trigger {
                        edge: Edge::Free,
                        level: 0.125,
                        channel: 15,
                    },
                },
                spectrum: Spectrum {
                    channel: 15,
                    analysis: Settings {
                        size: 1024,
                        averages: 1,
                        quantity: Quantity::Psd,
                        remove_dc: false,
                        ..Settings::default()
                    },
                    mode: SpectrumMode::Continuous,
                    band_min_hz: 0.0,
                    band_max_hz: 0.0,
                },
                spectrogram: Spectrogram {
                    channel: 7,
                    analysis: Settings {
                        averages: 1,
                        ..Settings::default()
                    },
                },
                xy: Xy {
                    channels: Pair([15, 7]),
                    milliseconds: 50.0,
                },
                calibrations: vec![ChannelCalibration {
                    channel: 15,
                    id: "dc-sine-reference".into(),
                    revision: 3,
                    gain: -4.000000000000001,
                    offset: 1.0000000000000002,
                    unit: "V".into(),
                    conditions: "Synthetic DC + sine at nominal 48 kHz; not an ADC calibration"
                        .into(),
                }],
            },
            workspace: Workspace {
                visible: [true; 4],
                layout: PlotLayout::Auto,
                sidebar_visible: true,
                scope_enabled: [true; 2],
                scope_fs_per_div: 0.25,
                spectrum_scale: FrequencyScale::Log,
                spectrum_min_hz: 0.0,
                spectrum_max_hz: 0.0,
                spectrum_floor_db: -120.0,
                spectrum_ceiling_db: 6.0,
                spectrum_show_hold: true,
                spectrogram_scale: FrequencyScale::Linear,
                spectrogram_min_hz: 20.0,
                spectrogram_max_hz: 0.0,
                spectrogram_floor_db: -120.0,
                spectrogram_ceiling_db: 0.0,
                spectrogram_seconds: 5.0,
                xy_x_fs_per_div: 0.25,
                xy_y_fs_per_div: 0.125,
                xy_cursor_mode: CursorMode::TraceSnap,
            },
        }
    }

    fn device(id: &str, name: &str) -> DeviceInfo {
        DeviceInfo {
            id: Some(id.into()),
            name: name.into(),
            channels: 16,
            default_sample_rate: 48_000,
            is_default: true,
            sample_rates: vec![48_000, 96_000],
        }
    }

    #[test]
    fn roundtrip_retains_f64_calibration_ids_and_all_analysis_choices() {
        for size in FFT_SIZES {
            for precision in [Precision::F32, Precision::F64] {
                for window in [Window::Rectangular, Window::Hann, Window::BlackmanHarris] {
                    for mode in [
                        SpectrumMode::Live,
                        SpectrumMode::Continuous,
                        SpectrumMode::Latest,
                    ] {
                        let mut original = fixture();
                        original.measurement.spectrum.analysis.size = size;
                        original.measurement.spectrum.analysis.precision = precision;
                        original.measurement.spectrum.analysis.window = window;
                        original.measurement.spectrum.mode = mode;
                        let restored = Document::decode(&original.encode().unwrap()).unwrap();
                        assert_eq!(restored, original);
                        assert_eq!(restored.validate().unwrap(), original.validate().unwrap());
                    }
                }
            }
        }
        let encoded = String::from_utf8(fixture().encode().unwrap()).unwrap();
        assert!(encoded.contains("\"mode\": \"continuous\""));
        assert!(!encoded.contains("running"));
        assert!(!encoded.contains("start"));
    }

    #[test]
    fn device_resolution_uses_unique_id_topology_and_rate_without_name_fallback() {
        let input = fixture().measurement.input;
        let other = device("coreaudio:other", &input.device_name);
        let target = device(&input.device_id, "Renamed reference input");
        assert_eq!(input.resolve(&[other.clone(), target.clone()]).unwrap(), 1);
        assert_eq!(input.resolve(&[target.clone(), other.clone()]).unwrap(), 0);
        assert!(input.resolve(&[other]).is_err());
        assert!(input.resolve(&[target.clone(), target.clone()]).is_err());
        let mut changed = target.clone();
        changed.channels = 2;
        assert!(input.resolve(&[changed]).is_err());
        let mut changed = target;
        changed.sample_rates = vec![96_000];
        assert!(input.resolve(&[changed]).is_err());
        let mut default_input = input;
        default_input.sample_rate = None;
        let mut changed = device(&default_input.device_id, "Reference");
        changed.default_sample_rate = 96_000;
        assert!(default_input.resolve(&[changed]).is_err());
    }

    #[test]
    fn invalid_legacy_unknown_and_oversized_documents_are_rejected() {
        assert!(
            Document::decode(br#"{"version":0}"#)
                .unwrap_err()
                .contains("version")
        );
        assert!(
            Document::decode(br#"{"version":2}"#)
                .unwrap_err()
                .contains("version")
        );
        assert!(Document::decode(br#"{"fft_size":8192,"running":true}"#).is_err());
        assert!(Document::decode(&vec![b' '; MAX_BYTES + 1]).is_err());
        let good = fixture();
        let mut value = serde_json::to_value(&good).unwrap();
        value["running"] = serde_json::json!(true);
        assert!(Document::decode(&serde_json::to_vec(&value).unwrap()).is_err());
        let mut value = serde_json::to_value(&good).unwrap();
        value["measurement"]["spectrum"]["analysis"]["precision"] = serde_json::json!("automatic");
        assert!(Document::decode(&serde_json::to_vec(&value).unwrap()).is_err());
        let mut value = serde_json::to_value(&good).unwrap();
        value["measurement"]["calibrations"][0]["gain"] = serde_json::json!(null);
        assert!(Document::decode(&serde_json::to_vec(&value).unwrap()).is_err());
        for mutate in [
            |d: &mut Document| d.measurement.scope.channels.0[0] = 16,
            |d: &mut Document| d.measurement.scope.ms_per_div = f32::NAN,
            |d: &mut Document| d.measurement.scope.trigger.level = f64::INFINITY,
            |d: &mut Document| d.measurement.spectrum.analysis.size = 1000,
            |d: &mut Document| d.measurement.spectrum.analysis.averages = 0,
            |d: &mut Document| d.measurement.spectrogram.analysis.size = 65536,
            |d: &mut Document| d.measurement.spectrogram.analysis.quantity = Quantity::Psd,
            |d: &mut Document| d.measurement.input.channels = 0,
            |d: &mut Document| d.measurement.input.sample_rate = Some(768001),
            |d: &mut Document| d.measurement.spectrum.band_min_hz = -1.0,
            |d: &mut Document| d.measurement.xy.milliseconds = 0.0,
            |d: &mut Document| d.measurement.calibrations[0].gain = 0.0,
            |d: &mut Document| d.measurement.calibrations[0].unit = "FS".into(),
            |d: &mut Document| d.measurement.calibrations[0].revision = 0,
            |d: &mut Document| d.workspace.visible = [false; 4],
            |d: &mut Document| d.workspace.spectrum_ceiling_db = -120.0,
        ] {
            let mut bad = good.clone();
            mutate(&mut bad);
            assert!(bad.validate().is_err());
            assert!(bad.encode().is_err());
        }
        let mut duplicate = good.clone();
        duplicate
            .measurement
            .calibrations
            .push(duplicate.measurement.calibrations[0].clone());
        assert!(duplicate.validate().is_err());
        let mut conflicting = good;
        let mut other = conflicting.measurement.calibrations[0].clone();
        other.channel = 7;
        other.gain = 2.0;
        conflicting.measurement.calibrations.push(other);
        assert!(conflicting.validate().is_err());
    }

    #[test]
    fn restored_conditions_reproduce_raw_scope_and_psd_from_the_same_known_input() {
        let original = fixture();
        let restored = Document::decode(&original.encode().unwrap()).unwrap();
        let sample_rate = 48_000;
        let mut history = History::with_channels(1024, 16);
        for index in 0..1024 {
            let angle = std::f64::consts::TAU * 16.0 * index as f64 / 1024.0;
            let mut frame = [0.0; 16];
            frame[15] = 0.125 + 0.25 * angle.sin();
            frame[7] = 0.25 * angle.cos();
            history.push(frame);
        }
        let measure = |document: &Document| {
            let set = document.validate().unwrap();
            let readings =
                calibration::measure(&history, 0..1024, document.measurement.scope.channels, &set);
            let mut analyzer = Analyzer::new(document.measurement.spectrum.analysis, sample_rate);
            analyzer.set_calibration(set.get(15).cloned().map(std::sync::Arc::new));
            assert!(analyzer.update(&history, document.measurement.spectrum.channel));
            (readings, analyzer)
        };
        let (before, analyzer_before) = measure(&original);
        let (after, analyzer_after) = measure(&restored);
        assert_eq!(before, after);
        let Reading::Valid(scope) = after[0] else {
            panic!("valid scope measurement")
        };
        // y ≈ 0.5 - sin(theta): RMS² = 0.25 + 0.5; P-P = 2 V.
        assert!((scope.rms - 0.75_f64.sqrt()).abs() < 1e-14);
        assert!((scope.peak_to_peak - 2.0).abs() < 1e-14);
        assert_eq!(analyzer_before.power(), analyzer_after.power());
        assert_eq!(analyzer_before.window(), analyzer_after.window());
        let band = analyzer_after.band(0.0, sample_rate as f64 / 2.0).unwrap();
        assert!((band.power - 0.75).abs() < 1e-14);
        assert_eq!(analyzer_after.unit(), "V");
        let definition = analyzer_after.calibration().unwrap();
        assert_eq!(definition.id(), "dc-sine-reference");
        assert_eq!(definition.revision(), 3);
    }

    #[test]
    fn atomic_save_worker_restore_and_failures_preserve_the_previous_file() {
        let directory =
            std::env::temp_dir().join(format!("measurelab-settings-test-{}", std::process::id()));
        std::fs::create_dir_all(&directory).unwrap();
        let path = directory.join("conditions.json");
        let worker = Worker::default();
        let original = fixture();
        worker
            .submit(path.clone(), Operation::Save(Box::new(original.clone())))
            .unwrap();
        assert!(
            matches!(worker.events.recv_timeout(std::time::Duration::from_secs(5)).unwrap(), Event::Saved(p) if p == path)
        );
        drop(worker); // New worker models reopening after an app restart.
        let before = std::fs::read(&path).unwrap();
        let worker = Worker::default();
        worker.submit(path.clone(), Operation::Restore).unwrap();
        let Event::Restored(_, restored) = worker
            .events
            .recv_timeout(std::time::Duration::from_secs(5))
            .unwrap()
        else {
            panic!("restore")
        };
        assert_eq!(*restored, original);
        let mut invalid = original.clone();
        invalid.measurement.calibrations[0].gain = f64::NAN;
        assert!(save(&path, &invalid).is_err());
        assert_eq!(std::fs::read(&path).unwrap(), before);
        assert!(save(&path.join("cannot-create.json"), &original).is_err());
        assert_eq!(std::fs::read(&path).unwrap(), before);
        worker
            .submit(directory.join("missing.json"), Operation::Restore)
            .unwrap();
        assert!(matches!(
            worker
                .events
                .recv_timeout(std::time::Duration::from_secs(5))
                .unwrap(),
            Event::Error(_)
        ));
        let mut changed = original;
        changed.measurement.calibrations[0].revision += 1;
        changed.measurement.calibrations[0].gain = 8.0;
        save(&path, &changed).unwrap();
        assert_eq!(load(&path).unwrap(), changed);
        assert_eq!(std::fs::read_dir(&directory).unwrap().count(), 1);
        drop(worker);
        std::fs::remove_dir_all(directory).unwrap();
    }
}
