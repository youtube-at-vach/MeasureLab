//! Explicit opt-in physical stereo QA, separate from virtual-only fixtures.
//! Analog transfer is measured first; only controlled changes have known ratios.
use crate::{audio, export, lockin, measurement, results, signal::History, spectrum, stft};
use cpal::traits::{DeviceTrait, HostTrait, StreamTrait};
use serde::Serialize;
use std::{
    f64::consts::TAU,
    path::Path,
    sync::{
        Arc,
        atomic::{AtomicBool, AtomicU64, AtomicUsize, Ordering},
    },
    thread,
    time::{Duration, Instant},
};

const DEVICE: &str = "ZOOM UAC-232";
const OUTPUT_PEAK: f64 = 0.1;
// Defined before the physical run, independent of the observed cable transfer.
const R_REL_TOL: f64 = 0.002;
const R_ABS_TOL: f64 = 2e-6;
const PHASE_TOL: f64 = 0.05;
const CHANGE_REL_TOL: f64 = 0.01;
const CHANGE_PHASE_TOL: f64 = 0.1;

#[derive(Clone, Copy)]
enum Tone {
    Base,
    Inverted,
    Lead,
    Delayed,
    Half,
    Small,
    Offset,
    Lost,
    Unstable,
}
impl Tone {
    fn frequency(self) -> f64 {
        if matches!(self, Self::Offset) {
            1003.0
        } else {
            1000.0
        }
    }
    fn gain(self) -> f64 {
        match self {
            Self::Half => 0.5,
            Self::Small => 0.01,
            _ => 1.0,
        }
    }
    fn phase(self, rate: u32) -> f64 {
        match self {
            Self::Inverted => 180.0,
            Self::Lead => 30.0,
            Self::Delayed => -360.0 * self.frequency() * 3.0 / rate as f64,
            _ => 0.0,
        }
    }
}

struct Fixture {
    _stream: cpal::Stream,
    mode: Arc<AtomicUsize>,
    failed: Arc<AtomicBool>,
    notifications: Arc<AtomicU64>,
}
impl Fixture {
    fn new(name: &str, rate: u32) -> Result<Self, String> {
        require(
            name == DEVICE,
            "Physical output QA is restricted to ZOOM UAC-232",
        )?;
        let device = cpal::default_host()
            .output_devices()
            .map_err(|e| e.to_string())?
            .find(|d| d.to_string() == name)
            .ok_or("Requested physical output is unavailable")?;
        let config = device
            .supported_output_configs()
            .map_err(|e| e.to_string())?
            .filter(|c| c.channels() == 2 && c.sample_format() == cpal::SampleFormat::F32)
            .find_map(|c| c.try_with_sample_rate(rate))
            .ok_or("Requested stereo f32 output rate is unsupported")?;
        let cycles: Vec<Vec<f32>> = [
            Tone::Base,
            Tone::Inverted,
            Tone::Lead,
            Tone::Delayed,
            Tone::Half,
            Tone::Small,
            Tone::Offset,
            Tone::Lost,
            Tone::Unstable,
        ]
        .into_iter()
        .map(|tone| {
            (0..rate)
                .flat_map(|n| {
                    let angle = TAU * tone.frequency() * n as f64 / rate as f64;
                    let response =
                        OUTPUT_PEAK * tone.gain() * (angle + tone.phase(rate).to_radians()).sin();
                    let reference = match tone {
                        Tone::Lost => 0.0,
                        // Keep the combined peak below OUTPUT_PEAK. Never output DC.
                        Tone::Unstable => {
                            OUTPUT_PEAK * (0.6 * angle.sin() + 0.3 * (2.0 * angle).sin())
                        }
                        _ => OUTPUT_PEAK * angle.sin(),
                    };
                    // L=signal, R=REF, matching the user's screenshots and wiring.
                    [response as f32, reference as f32]
                })
                .collect()
        })
        .collect();
        let mode = Arc::new(AtomicUsize::new(0));
        let selected = mode.clone();
        let failed = Arc::new(AtomicBool::new(false));
        let failure = failed.clone();
        let notifications = Arc::new(AtomicU64::new(0));
        let errors = notifications.clone();
        let mut head = 0;
        let stream = device
            .build_output_stream(
                config.into(),
                move |data: &mut [f32], _| {
                    let cycle = &cycles[selected.load(Ordering::Acquire)];
                    let mut offset = 0;
                    while offset < data.len() {
                        let count = (cycle.len() - head).min(data.len() - offset);
                        data[offset..offset + count].copy_from_slice(&cycle[head..head + count]);
                        offset += count;
                        head = (head + count) % cycle.len();
                    }
                },
                move |error| {
                    eprintln!("Physical QA output error: {error}");
                    failure.store(true, Ordering::Relaxed);
                    errors.fetch_add(1, Ordering::Relaxed);
                },
                Some(Duration::from_secs(2)),
            )
            .map_err(|e| e.to_string())?;
        stream.play().map_err(|e| e.to_string())?;
        Ok(Self {
            _stream: stream,
            mode,
            failed,
            notifications,
        })
    }
    fn select(&self, tone: Tone) {
        self.mode.store(tone as usize, Ordering::Release);
    }
    fn warmup(&self) {
        println!(
            "Physical attachment warm-up: {} output notifications; excluded interval",
            self.notifications.swap(0, Ordering::Relaxed)
        );
        self.failed.store(false, Ordering::Relaxed);
    }
    fn check(&self) -> Result<(), String> {
        require(
            !self.failed.load(Ordering::Relaxed),
            "Physical output failed during measurement",
        )
    }
}

fn require(condition: bool, message: &str) -> Result<(), String> {
    if condition {
        Ok(())
    } else {
        Err(message.into())
    }
}
fn wrap(value: f64) -> f64 {
    (value + 180.0).rem_euclid(360.0) - 180.0
}

/// Independent unweighted DC/sin/cos least squares, using pivoted elimination.
/// Does not call the production detector's Hann fit, frequency search or EMA.
#[derive(Debug, Serialize)]
struct Fit {
    dc: f64,
    peak: f64,
    phase: f64,
    residual_rms: f64,
}
fn fit(
    history: &History,
    range: std::ops::Range<u64>,
    channel: usize,
    rate: u32,
    frequency: f64,
) -> Result<Fit, String> {
    let mut matrix = [[0.0; 4]; 3];
    for (i, sequence) in range.clone().enumerate() {
        let sample = history
            .get(sequence)
            .and_then(|s| s.get(channel))
            .copied()
            .ok_or("Independent fit lacks the complete Lock-in window")?;
        let angle = TAU * frequency * i as f64 / rate as f64;
        let basis = [1.0, angle.sin(), angle.cos()];
        for row in 0..3 {
            for column in 0..3 {
                matrix[row][column] += basis[row] * basis[column];
            }
            matrix[row][3] += basis[row] * sample;
        }
    }
    for column in 0..3 {
        let pivot = (column..3)
            .max_by(|&a, &b| matrix[a][column].abs().total_cmp(&matrix[b][column].abs()))
            .unwrap();
        matrix.swap(column, pivot);
        require(
            matrix[column][column].abs() > 1e-12,
            "Singular independent fit",
        )?;
        let scale = matrix[column][column];
        for cell in &mut matrix[column][column..] {
            *cell /= scale;
        }
        for row in 0..3 {
            if row == column {
                continue;
            }
            let factor = matrix[row][column];
            let pivot_values = matrix[column];
            for (cell, pivot) in matrix[row][column..]
                .iter_mut()
                .zip(&pivot_values[column..])
            {
                *cell -= factor * pivot;
            }
        }
    }
    let [dc, sine, cosine] = [matrix[0][3], matrix[1][3], matrix[2][3]];
    let mut residual = 0.0;
    for (i, sequence) in range.clone().enumerate() {
        let angle = TAU * frequency * i as f64 / rate as f64;
        let sample = history.get(sequence).unwrap()[channel];
        residual += (sample - dc - sine * angle.sin() - cosine * angle.cos()).powi(2);
    }
    Ok(Fit {
        dc,
        peak: sine.hypot(cosine),
        phase: cosine.atan2(sine).to_degrees(),
        residual_rms: (residual / (range.end - range.start) as f64).sqrt(),
    })
}

fn clean(snapshot: &measurement::Snapshot, fixture: &Fixture) -> Result<(), String> {
    fixture.check()?;
    require(
        !snapshot.failed && snapshot.input_dropped == 0 && snapshot.lockin.missing_samples == 0,
        "Unexpected input/Lock-in loss or stream failure",
    )
}
fn wait(
    worker: &mut measurement::Worker,
    fixture: &Fixture,
    settings: lockin::Settings,
    predicate: impl Fn(&lockin::Result) -> bool,
) -> Result<Box<measurement::Snapshot>, String> {
    let clock = Instant::now();
    let mut last = None;
    while clock.elapsed() < Duration::from_secs(12) {
        if let Some(snapshot) = worker.take_latest() {
            fixture.check()?;
            require(!snapshot.failed, "Physical input stream failed")?;
            if snapshot.lockin.settings == settings && predicate(&snapshot.lockin) {
                return Ok(snapshot);
            }
            last = Some(snapshot.lockin.clone());
            worker.recycle(snapshot);
        }
        thread::sleep(Duration::from_millis(5));
    }
    Err(format!("Physical Lock-in timed out: {last:?}"))
}
fn settled(
    worker: &mut measurement::Worker,
    fixture: &Fixture,
    settings: lockin::Settings,
    rate: u32,
) -> Result<Box<measurement::Snapshot>, String> {
    let snapshot = wait(worker, fixture, settings, |r| {
        r.state == lockin::State::Valid
            && (r.sample_range.end - r.sample_range.start) as f64
                >= 30.0 * settings.time_constant_seconds * rate as f64
    })?;
    clean(&snapshot, fixture)?;
    Ok(snapshot)
}
fn attach(device: &cpal::Device, rate: u32) -> Result<(cpal::Stream, audio::Capture), String> {
    let (stream, capture) = audio::start_device(device, Some(rate))?;
    thread::sleep(Duration::from_millis(300));
    require(
        capture.metrics.dropped.load(Ordering::Relaxed) == 0,
        "Input overflow during attachment",
    )?;
    println!(
        "Physical pre-worker warm-up: input notification {}; retained numbered frames, dropped 0",
        capture.metrics.failed.swap(false, Ordering::Relaxed)
    );
    Ok((stream, capture))
}

#[derive(Serialize)]
struct Observation {
    label: String,
    detector: lockin::Result,
    response_fit: Fit,
    reference_fit: Fit,
    amplitude_error_fs: f64,
    phase_error_degrees: f64,
    dbfs_peak: f64,
}
fn observe(label: &str, snapshot: &measurement::Snapshot) -> Result<Observation, String> {
    let result = &snapshot.lockin;
    require(
        result.state == lockin::State::Valid,
        "Independent comparison needs a settled detector",
    )?;
    let frequency = result
        .reference_frequency_hz
        .ok_or("Missing REF frequency")?;
    let reference = fit(
        &snapshot.history,
        result.latest_window.clone(),
        result.settings.reference_channel,
        snapshot.sample_rate,
        frequency,
    )?;
    let response = fit(
        &snapshot.history,
        result.latest_window.clone(),
        result.settings.response_channel,
        snapshot.sample_rate,
        frequency,
    )?;
    let amplitude = result.amplitude_peak.ok_or("Missing R")?;
    let amplitude_error = amplitude - response.peak;
    let phase_error =
        wrap(result.phase_degrees.ok_or("Missing phase")? - wrap(response.phase - reference.phase));
    require(
        amplitude_error.abs() < response.peak * R_REL_TOL + R_ABS_TOL,
        &format!("Independent R mismatch: {amplitude_error} FS"),
    )?;
    require(
        phase_error.abs() < PHASE_TOL,
        &format!("Independent phase mismatch: {phase_error} deg"),
    )?;
    println!(
        "Physical {label}: R={amplitude:.10} FS peak ({:.6} dBFS), phase={:.7}°, gain={:.9}, independent errors R={amplitude_error:.3e} FS, phase={phase_error:.3e}°, DC SIG/REF={:.3e}/{:.3e} FS",
        20.0 * amplitude.log10(),
        result.phase_degrees.unwrap(),
        result.gain.unwrap(),
        response.dc,
        reference.dc
    );
    Ok(Observation {
        label: label.into(),
        detector: result.clone(),
        response_fit: response,
        reference_fit: reference,
        amplitude_error_fs: amplitude_error,
        phase_error_degrees: phase_error,
        dbfs_peak: 20.0 * amplitude.log10(),
    })
}

/// GUI profiling uses the same raw-window independent oracle as physical QA.
pub fn validate_gui(snapshot: &measurement::Snapshot) -> Result<(), String> {
    validate_generator(
        snapshot,
        Path::new("dist/stage4-macos-qa/physical-gui-oracle.json"),
    )
}

/// Independent raw-input oracle, also for the normal Generator output path.
pub fn validate_generator(snapshot: &measurement::Snapshot, path: &Path) -> Result<(), String> {
    require(
        !snapshot.failed && snapshot.input_dropped == 0,
        "GUI physical input failed",
    )?;
    require(
        snapshot.spectrum_info.input_missing == 0,
        "GUI physical Spectrum lost input",
    )?;
    require(
        snapshot.lockin.missing_samples == 0,
        "GUI physical Lock-in lost input",
    )?;
    let observation = observe("GUI finite Stop", snapshot).inspect_err(|error| {
        // Retain bounded input evidence on a failed physical oracle as well;
        // a noise-only SIG or an unsettled REF must not become a passing run.
        let result = &snapshot.lockin;
        let samples: Vec<_> = result
            .latest_window
            .clone()
            .map(|n| {
                snapshot.history.get(n).map(|frame| {
                    [
                        frame.get(result.settings.reference_channel).copied(),
                        frame.get(result.settings.response_channel).copied(),
                    ]
                })
            })
            .collect();
        let diagnostic = serde_json::json!({
            "error": error,
            "nominal_sample_rate_hz": snapshot.sample_rate,
            "detector": result,
            "raw_ref_sig": samples,
        });
        if let Some(parent) = path.parent() {
            let _ = std::fs::create_dir_all(parent);
        }
        let failure_path = path.with_extension("failure.json");
        if let Ok(bytes) = serde_json::to_vec_pretty(&diagnostic)
            && std::fs::write(&failure_path, bytes).is_ok()
        {
            eprintln!(
                "Physical oracle failure evidence: {}",
                failure_path.display()
            );
        }
    })?;
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    }
    std::fs::write(
        path,
        serde_json::to_vec_pretty(&observation).map_err(|e| e.to_string())?,
    )
    .map_err(|e| e.to_string())
}

pub fn validate_single(
    snapshot: &measurement::Snapshot,
    baseline: &export::Document,
) -> Result<(), String> {
    require(
        !snapshot.failed && snapshot.input_dropped == 0 && snapshot.scope_missing == 0,
        "External Single failed or lost input",
    )?;
    let old = &baseline
        .lockin
        .as_ref()
        .ok_or("Single needs a baseline")?
        .result;
    let history = snapshot.scope_capture.as_ref().unwrap_or(&snapshot.history);
    let frequency = old
        .reference_frequency_hz
        .ok_or("Missing baseline frequency")?;
    let response = fit(
        history,
        snapshot.sweep.range.clone(),
        old.settings.response_channel,
        snapshot.sample_rate,
        frequency,
    )?;
    let reference = fit(
        history,
        snapshot.sweep.range.clone(),
        old.settings.reference_channel,
        snapshot.sample_rate,
        frequency,
    )?;
    require(reference.peak > 0.001, "Single REF is absent")?;
    require(
        (response.peak - old.amplitude_peak.unwrap()).abs()
            < old.amplitude_peak.unwrap() * 0.01 + R_ABS_TOL
            && wrap(response.phase - reference.phase - old.phase_degrees.unwrap()).abs() < 0.1,
        &format!(
            "Single raw input disagrees with baseline: R={}, expected {}; phase={}, expected {}; REF peak={}, SIG residual={}",
            response.peak,
            old.amplitude_peak.unwrap(),
            wrap(response.phase - reference.phase),
            old.phase_degrees.unwrap(),
            reference.peak,
            response.residual_rms
        ),
    )?;
    println!(
        "External Single raw oracle OK: {} samples, R={} FS peak, phase={} deg; detector remains settling, 512k unfilled",
        snapshot.sweep.range.end - snapshot.sweep.range.start,
        response.peak,
        wrap(response.phase - reference.phase)
    );
    Ok(())
}
fn change(
    result: &lockin::Result,
    baseline: &lockin::Result,
    ratio: f64,
    phase: f64,
) -> Result<(), String> {
    let expected = baseline.amplitude_peak.unwrap() * ratio;
    require(
        (result.amplitude_peak.unwrap() - expected).abs() < expected * CHANGE_REL_TOL + R_ABS_TOL,
        "Known physical amplitude ratio mismatch",
    )?;
    require(
        wrap(result.phase_degrees.unwrap() - baseline.phase_degrees.unwrap() - phase).abs()
            < CHANGE_PHASE_TOL,
        "Known physical phase change mismatch",
    )
}
fn save(
    snapshot: &measurement::Snapshot,
    source: export::Input,
    worker: &measurement::Worker,
    stem: &str,
) -> Result<export::Document, String> {
    let doc = super::lockin::document(snapshot, source, worker)?;
    export::save(Path::new(&format!("{stem}.json")), &doc)?;
    results::save_csv(Path::new(&format!("{stem}.csv")), &doc)?;
    require(
        results::load(Path::new(&format!("{stem}.json")))? == doc,
        "Physical JSON round trip mismatch",
    )?;
    Ok(doc)
}

pub fn smoke_test(name: &str, rate: u32) -> Result<(), Box<dyn std::error::Error>> {
    require(
        name == DEVICE,
        "Physical output QA is restricted to ZOOM UAC-232",
    )?;
    let seconds = std::env::var("MEASURELAB_LOCKIN_SECONDS")
        .unwrap_or_else(|_| "10".into())
        .parse::<u64>()
        .ok()
        .filter(|s| (1..=3600).contains(s))
        .ok_or("MEASURELAB_LOCKIN_SECONDS must be 1–3600")?;
    let device = audio::input_device(Some(name))?;
    let default = device.default_input_config()?;
    require(default.channels() == 2, "Physical QA requires stereo input")?;
    let original_rate = default.sample_rate();
    println!(
        "Explicit physical QA: {name}, nominal Fs {rate} Hz, L signal / R REF, output <= {OUTPUT_PEAK} FS peak (-20 dBFS), no generated DC; knobs unchanged"
    );
    let outcome = run(name, rate, seconds, &device).and_then(|()| {
        if std::env::var_os("MEASURELAB_PHYSICAL_TRANSITIONS").is_some() {
            transitions()
        } else {
            Ok(())
        }
    });
    // All output/input RAII streams have been dropped, including on failure.
    let restore = audio::start_device(&device, Some(original_rate));
    match restore {
        Ok((stream, _)) => {
            drop(stream);
            println!("Physical nominal rate restored to {original_rate} Hz");
        }
        Err(error) => {
            return Err(format!("QA outcome {outcome:?}; rate restoration failed: {error}").into());
        }
    }
    outcome.map_err(Into::into)
}

/// Keep one measurement worker across physical Fs and physical/virtual changes.
fn transitions() -> Result<(), String> {
    let mut stft = stft::Worker::new();
    let mut worker = measurement::Worker::new(stft.take_feeder());
    for (index, (name, rate)) in [
        (DEVICE, 48000),
        (DEVICE, 96000),
        (DEVICE, 44100),
        (DEVICE, 192000),
        ("BlackHole 2ch", 48000),
        (DEVICE, 48000),
    ]
    .into_iter()
    .enumerate()
    {
        use cpal::traits::DeviceTrait;
        let device = audio::input_device(Some(name))?;
        let original = device
            .default_input_config()
            .map_err(|e| e.to_string())?
            .sample_rate();
        let outcome: Result<(), String> = (|| {
            let physical = (name == DEVICE)
                .then(|| Fixture::new(name, rate))
                .transpose()?;
            let virtual_output = (name != DEVICE)
                .then(|| super::lockin::Fixture::new(name, rate))
                .transpose()?;
            let (stream, capture) = attach(&device, rate)?;
            let mut config = super::lockin::config(rate, 2);
            if physical.is_some() {
                config.lockin.frequency_hz = 1000.0;
                config.lockin.reference_channel = 1;
                config.lockin.response_channel = 0;
            }
            let generation = 100 + index as u64;
            worker.start_capture(generation, capture, config.clone());
            thread::sleep(Duration::from_millis(200));
            if let Some(f) = &physical {
                f.warmup();
            }
            if let Some(f) = &virtual_output {
                f.end_warmup("physical/device transition");
            }
            worker.configure_lockin(config.lockin);
            let deadline = Instant::now() + Duration::from_secs(5);
            loop {
                if Instant::now() > deadline {
                    return Err("Physical/device transition timed out".into());
                }
                if let Some(snapshot) = worker.take_latest() {
                    let ready = snapshot.generation == generation
                        && snapshot.lockin.state == lockin::State::Valid
                        && (snapshot.lockin.sample_range.end - snapshot.lockin.sample_range.start)
                            as f64
                            >= 0.6 * rate as f64;
                    worker.recycle(snapshot);
                    if ready {
                        break;
                    }
                }
                thread::sleep(Duration::from_millis(5));
            }
            let snapshot = super::lockin::finish(&worker)?;
            require(
                snapshot.generation == generation
                    && snapshot.sample_rate == rate
                    && snapshot.history.channels() == 2
                    && snapshot.lockin.settings == config.lockin
                    && !snapshot.failed
                    && snapshot.input_dropped == 0
                    && snapshot.lockin.missing_samples == 0,
                "Physical/device transition mixed conditions or lost input",
            )?;
            if let Some(f) = &physical {
                f.check()?;
                observe("Fs/device transition", &snapshot)?;
            }
            if let Some(f) = &virtual_output {
                require(
                    !f.failed.load(Ordering::Relaxed),
                    "Virtual transition output failed",
                )?;
                require(
                    (snapshot.lockin.amplitude_peak.unwrap() - 0.0625).abs() < 1e-8
                        && wrap(snapshot.lockin.phase_degrees.unwrap() - 13.125).abs() < 1e-4,
                    "Virtual transition disagrees with theory",
                )?;
            }
            println!("Physical/device transition OK: generation {generation}, {name}, {rate} Hz");
            drop(stream);
            Ok(())
        })();
        let _ = worker.stop();
        let (stream, _) = audio::start_device(&device, Some(original))?;
        drop(stream);
        outcome?;
    }
    Ok(())
}

fn run(name: &str, rate: u32, seconds: u64, device: &cpal::Device) -> Result<(), String> {
    std::fs::create_dir_all("dist/lockin-physical-qa").map_err(|e| e.to_string())?;
    let stem = format!("dist/lockin-physical-qa/uac232-{rate}");
    let fixture = Fixture::new(name, rate)?;
    thread::sleep(Duration::from_millis(300));
    let (stream, capture) = attach(device, rate)?;
    let format = capture.format.clone();
    let mut config = super::lockin::config(rate, 2);
    config.lockin.frequency_hz = 1000.0;
    config.lockin.reference_channel = 1;
    config.lockin.response_channel = 0;
    config.spectrum_channel = 0;
    config.spectrum.quantity = spectrum::Quantity::Psd;
    let mut stft = stft::Worker::new();
    let mut worker = measurement::Worker::new(stft.take_feeder());
    worker.start_capture(1, capture, config.clone());
    thread::sleep(Duration::from_millis(200));
    fixture.warmup();
    worker.configure_lockin(config.lockin);
    let baseline = settled(&mut worker, &fixture, config.lockin, rate)?;
    let mut observations = vec![observe("baseline", &baseline)?];
    let initial = baseline.lockin.clone();
    worker.recycle(baseline);
    let first = super::lockin::finish(&worker)?;
    clean(&first, &fixture)?;
    observe("finite Stop", &first)?;
    let frequency = first.lockin.reference_frequency_hz.unwrap();
    let half_band = 5.0 * rate as f64 / config.spectrum.size as f64;
    let spectrum_peak = first
        .spectrum
        .band(frequency - half_band, frequency + half_band)
        .ok_or("Missing physical PSD band")?
        .rms
        * 2.0_f64.sqrt();
    require(
        (spectrum_peak - first.lockin.amplitude_peak.unwrap()).abs()
            < first.lockin.amplitude_peak.unwrap() * R_REL_TOL + R_ABS_TOL,
        "Physical PSD/Lock-in peak mismatch",
    )?;
    println!(
        "Physical PSD band R={spectrum_peak:.10} FS peak; independent Spectrum window {:?}",
        first.spectrum.window()
    );
    let source = export::Input {
        generation: 1,
        nominal_sample_rate_hz: rate,
        channels: 2,
        source: export::Source::Audio {
            device_id: device.id().ok().map(|id| id.to_string()),
            device_name: name.into(),
            sample_format: format,
            requested_sample_rate_hz: Some(rate),
        },
    };
    let doc = save(&first, source.clone(), &worker, &format!("{stem}-baseline"))?;
    let held = first.lockin.clone();
    worker.configure_lockin(lockin::Settings {
        frequency_hz: 2000.0,
        ..config.lockin
    });
    require(
        super::lockin::finish(&worker)?.lockin == held,
        "Held physical result changed with edits/repeated Stop",
    )?;
    drop(stream);
    let (stream, capture) = attach(device, rate)?;
    worker.start_capture(2, capture, config.clone());
    thread::sleep(Duration::from_millis(200));
    fixture.warmup();
    worker.configure_lockin(config.lockin);
    let recapture = settled(&mut worker, &fixture, config.lockin, rate)?;
    observations.push(observe("restart", &recapture)?);
    change(&recapture.lockin, &initial, 1.0, 0.0)?;
    worker.recycle(recapture);
    let second = super::lockin::finish(&worker)?;
    clean(&second, &fixture)?;
    let mut second_source = source.clone();
    second_source.generation = 2;
    let second_doc = save(&second, second_source, &worker, &format!("{stem}-restart"))?;
    let difference = results::lockin_difference(&doc, &second_doc)
        .ok_or("Physical recapture conditions are incomparable")?;
    require(
        difference.amplitude_peak.abs()
            < initial.amplitude_peak.unwrap() * CHANGE_REL_TOL + R_ABS_TOL
            && difference.phase_degrees.abs() < CHANGE_PHASE_TOL,
        "Saved physical recapture differs",
    )?;
    drop(stream);
    let (stream, capture) = attach(device, rate)?;
    let metrics = capture.metrics.clone();
    worker.start_capture(3, capture, config.clone());
    thread::sleep(Duration::from_millis(200));
    fixture.warmup();
    worker.configure_lockin(config.lockin);
    let ready = settled(&mut worker, &fixture, config.lockin, rate)?;
    worker.recycle(ready);
    for (label, tone) in [
        ("polarity", Tone::Inverted),
        ("lead +30deg", Tone::Lead),
        ("delay 3 samples", Tone::Delayed),
        ("half amplitude", Tone::Half),
        ("small response -40dB", Tone::Small),
        ("tracking 1003Hz", Tone::Offset),
    ] {
        fixture.select(tone);
        worker.configure_lockin(config.lockin);
        let snapshot = settled(&mut worker, &fixture, config.lockin, rate)?;
        observations.push(observe(label, &snapshot)?);
        if matches!(tone, Tone::Small) {
            // The ADC/DAC/cables are not calibrated for level-dependent phase
            // or crosstalk. Check the detector against the actual raw input,
            // and the amplitude ratio; retain the measured phase excursion.
            let expected = initial.amplitude_peak.unwrap() * tone.gain();
            require(
                (snapshot.lockin.amplitude_peak.unwrap() - expected).abs()
                    < expected * CHANGE_REL_TOL + R_ABS_TOL,
                "Small physical amplitude ratio mismatch",
            )?;
            println!(
                "Small-response physical phase excursion {:.7} deg: recorded, level-independent analog phase is unverified",
                wrap(snapshot.lockin.phase_degrees.unwrap() - initial.phase_degrees.unwrap())
            );
        } else {
            change(&snapshot.lockin, &initial, tone.gain(), tone.phase(rate))?;
        }
        require(
            (snapshot.lockin.reference_frequency_hz.unwrap() - tone.frequency()).abs() < 0.1,
            "Physical REF tracking differs from nominal output by >=0.1Hz",
        )?;
        worker.recycle(snapshot);
    }
    for (label, tone, state) in [
        ("REF off", Tone::Lost, lockin::State::ReferenceLost),
        (
            "REF harmonics",
            Tone::Unstable,
            lockin::State::ReferenceUnstable,
        ),
    ] {
        fixture.select(tone);
        let invalid = wait(&mut worker, &fixture, config.lockin, |r| r.state == state)?;
        clean(&invalid, &fixture)?;
        require(
            invalid.lockin.amplitude_peak.is_none()
                && invalid.lockin.x.is_none()
                && invalid.lockin.gain.is_none()
                && invalid.lockin.processed_windows == 0,
            "Invalid physical REF retained old values",
        )?;
        worker.recycle(invalid);
        fixture.select(Tone::Base);
        let recovering = wait(&mut worker, &fixture, config.lockin, |r| {
            r.state == lockin::State::Settling
        })?;
        worker.recycle(recovering);
        let recovered = settled(&mut worker, &fixture, config.lockin, rate)?;
        observations.push(observe(&format!("{label} recovery"), &recovered)?);
        change(&recovered.lockin, &initial, 1.0, 0.0)?;
        worker.recycle(recovered);
        println!("Physical {label}: values invalidated, Settling then Valid");
    }
    for (label, settings) in [
        (
            "swapped CH",
            lockin::Settings {
                reference_channel: 0,
                response_channel: 1,
                ..config.lockin
            },
        ),
        (
            "same CH",
            lockin::Settings {
                response_channel: 1,
                ..config.lockin
            },
        ),
    ] {
        worker.configure_lockin(settings);
        let snapshot = settled(&mut worker, &fixture, settings, rate)?;
        observations.push(observe(label, &snapshot)?);
        let result = &snapshot.lockin;
        if settings.reference_channel == settings.response_channel {
            require(
                result.phase_degrees.unwrap().abs() < 1e-10
                    && (result.gain.unwrap() - 1.0).abs() < 1e-10,
                "Physical same-CH self-check failed",
            )?;
        } else {
            require(
                wrap(result.phase_degrees.unwrap() + initial.phase_degrees.unwrap()).abs()
                    < CHANGE_PHASE_TOL
                    && (result.gain.unwrap() * initial.gain.unwrap() - 1.0).abs() < CHANGE_REL_TOL,
                "Swapped physical CH phase/gain failed",
            )?;
        }
        worker.recycle(snapshot);
    }
    step(&mut worker, &fixture, config.lockin, rate, &initial)?;
    fixture.select(Tone::Base);
    worker.configure_lockin(config.lockin);
    let stable = settled(&mut worker, &fixture, config.lockin, rate)?;
    let stable_baseline = stable.lockin.clone();
    worker.recycle(stable);
    let mut r_bounds = [f64::INFINITY, f64::NEG_INFINITY];
    let mut phase_bounds = [f64::INFINITY, f64::NEG_INFINITY];
    let mut count = 0_u64;
    let mut previous_window = None;
    let mut independent_checks = 0;
    let mut max_independent_r: f64 = 0.0;
    let mut max_independent_phase: f64 = 0.0;
    let clock = Instant::now();
    let mut next_independent = 0;
    let mut next_report = 30;
    println!("Physical stability interval starts: {seconds} s");
    while clock.elapsed() < Duration::from_secs(seconds) {
        if let Some(snapshot) = worker.take_latest() {
            clean(&snapshot, &fixture)?;
            let result = &snapshot.lockin;
            require(
                result.state == lockin::State::Valid,
                "Physical steady REF became invalid",
            )?;
            change(result, &stable_baseline, 1.0, 0.0)?;
            if previous_window != Some(result.latest_window.end) {
                let r = result.amplitude_peak.unwrap();
                let phase =
                    wrap(result.phase_degrees.unwrap() - stable_baseline.phase_degrees.unwrap());
                r_bounds[0] = r_bounds[0].min(r);
                r_bounds[1] = r_bounds[1].max(r);
                phase_bounds[0] = phase_bounds[0].min(phase);
                phase_bounds[1] = phase_bounds[1].max(phase);
                previous_window = Some(result.latest_window.end);
                count += 1;
                if clock.elapsed().as_secs() >= next_independent {
                    let observation = observe("steady independent", &snapshot)?;
                    max_independent_r = max_independent_r.max(observation.amplitude_error_fs.abs());
                    max_independent_phase =
                        max_independent_phase.max(observation.phase_error_degrees.abs());
                    independent_checks += 1;
                    next_independent += 10;
                }
            }
            worker.recycle(snapshot);
        }
        if clock.elapsed().as_secs() >= next_report {
            println!(
                "Physical stability {next_report} s: {count} distinct complete windows, R {r_bounds:?} FS, relative phase {phase_bounds:?} deg, no gaps/errors"
            );
            next_report += 30;
        }
        thread::sleep(Duration::from_millis(5));
    }
    let final_snapshot = super::lockin::finish(&worker)?;
    clean(&final_snapshot, &fixture)?;
    observations.push(observe("final Stop", &final_snapshot)?);
    let result = &final_snapshot.lockin;
    require(
        count > 0
            && result.sample_range.end - result.sample_range.start
                == result.processed_windows * config.lockin.integration_samples as u64
            && result.latest_window.end == result.sample_range.end
            && final_snapshot.history.range().end - result.latest_window.end
                < config.lockin.integration_samples as u64,
        "Physical finite endpoint/window accounting failed",
    )?;
    let mut final_source = source.clone();
    final_source.generation = 3;
    save(
        &final_snapshot,
        final_source,
        &worker,
        &format!("{stem}-final"),
    )?;
    println!(
        "Physical stability OK: {seconds} s, {count} distinct windows, R span {:.3e} FS, phase span {:.3e}°, callbacks {}..{} frames",
        r_bounds[1] - r_bounds[0],
        phase_bounds[1] - phase_bounds[0],
        metrics.callback_min_frames.load(Ordering::Relaxed),
        metrics.callback_max_frames.load(Ordering::Relaxed)
    );
    drop(stream);
    let missing = saturation(&mut worker, &fixture, device, rate, config.clone())?;
    let report = serde_json::json!({
        "device": name, "nominal_sample_rate_hz": rate, "output_peak_fs": OUTPUT_PEAK,
        "response_channel": 0, "reference_channel": 1, "uncalibrated": true,
        "small_response_phase": "Compared to raw-input independent fit; level-independent analog phase is not an acceptance claim",
        "tolerances": {"independent_r_relative": R_REL_TOL, "independent_r_absolute_fs": R_ABS_TOL,
            "independent_phase_degrees": PHASE_TOL, "known_change_r_relative": CHANGE_REL_TOL,
            "known_change_phase_degrees": CHANGE_PHASE_TOL},
        "observations": observations, "spectrum_band_peak_fs": spectrum_peak,
        "stability": {"seconds": seconds, "distinct_observed_windows": count, "r_bounds_fs": r_bounds,
            "phase_delta_bounds_degrees": phase_bounds, "independent_checks": independent_checks,
            "max_independent_r_error_fs": max_independent_r, "max_independent_phase_error_degrees": max_independent_phase,
            "input_dropped": final_snapshot.input_dropped, "lockin_missing": result.missing_samples,
            "callback_min_frames": metrics.callback_min_frames.load(Ordering::Relaxed),
            "callback_max_frames": metrics.callback_max_frames.load(Ordering::Relaxed),
            "complete_windows_since_reset": result.processed_windows,
            "finite_input_end": final_snapshot.history.range().end},
        "deliberate_capture_missing_frames": missing,
    });
    std::fs::write(
        format!("{stem}-report.json"),
        serde_json::to_vec_pretty(&report).map_err(|e| e.to_string())?,
    )
    .map_err(|e| e.to_string())?;
    println!(
        "Stage 4b physical Lock-in QA OK: {name}, {rate} Hz; absolute ADC/DAC calibration, cable attribution and independent clocks require separate evidence"
    );
    Ok(())
}

fn step(
    worker: &mut measurement::Worker,
    fixture: &Fixture,
    settings: lockin::Settings,
    rate: u32,
    baseline: &lockin::Result,
) -> Result<(), String> {
    let settings = lockin::Settings {
        time_constant_seconds: 0.1,
        integration_samples: if rate > 96000 { 16384 } else { 4096 },
        ..settings
    };
    worker.configure_lockin(settings);
    let before = settled(worker, fixture, settings, rate)?;
    worker.recycle(before);
    fixture.select(Tone::Half);
    let target = [baseline.x.unwrap() * 0.5, baseline.y.unwrap() * 0.5];
    let beta = (-(settings.integration_samples as f64)
        / (rate as f64 * settings.time_constant_seconds))
        .exp();
    let clock = Instant::now();
    let mut previous: Vec<lockin::Result> = Vec::new();
    let mut checks = 0;
    let mut excursion = false;
    let mut max_error: f64 = 0.0;
    while clock.elapsed() < Duration::from_secs(3) {
        if let Some(snapshot) = worker.take_latest() {
            clean(&snapshot, fixture)?;
            let r = snapshot.lockin.clone();
            worker.recycle(snapshot);
            if previous
                .last()
                .is_none_or(|p| p.latest_window.end != r.latest_window.end)
            {
                if let Some(amplitude) = r.amplitude_peak {
                    excursion |= amplitude > baseline.amplitude_peak.unwrap() * 0.55
                        && amplitude < baseline.amplitude_peak.unwrap() * 0.95;
                }
                previous.push(r);
                if previous.len() > 3 {
                    previous.remove(0);
                }
                if clock.elapsed() > Duration::from_millis(500)
                    && previous.len() == 3
                    && previous
                        .windows(2)
                        .all(|p| p[1].processed_windows == p[0].processed_windows + 1)
                {
                    for (coordinate, expected) in target.iter().enumerate() {
                        let v: Vec<f64> = previous
                            .iter()
                            .map(|p| {
                                if coordinate == 0 {
                                    p.x.unwrap()
                                } else {
                                    p.y.unwrap()
                                }
                            })
                            .collect();
                        let predicted = 2.0 * beta * v[1] - beta * beta * v[0]
                            + (1.0 - beta).powi(2) * expected;
                        let error = (v[2] - predicted).abs();
                        max_error = max_error.max(error);
                        require(
                            error < baseline.amplitude_peak.unwrap() * 0.002 + R_ABS_TOL,
                            "Physical two-pole step recurrence differs",
                        )?;
                    }
                    checks += 1;
                }
            }
        }
        thread::sleep(Duration::from_millis(5));
    }
    require(
        checks >= 3 && excursion,
        "Physical step lacks transient/adjacent windows",
    )?;
    change(
        previous.last().ok_or("No physical step result")?,
        baseline,
        0.5,
        0.0,
    )?;
    println!(
        "Physical two-pole step OK: tau=0.1s, {checks} adjacent recurrence checks, max error {max_error:.3e} FS"
    );
    Ok(())
}

fn saturation(
    worker: &mut measurement::Worker,
    fixture: &Fixture,
    device: &cpal::Device,
    rate: u32,
    mut config: measurement::Config,
) -> Result<u64, String> {
    let (stream, capture) = audio::start_device(device, Some(rate))?;
    let metrics = capture.metrics.clone();
    thread::sleep(Duration::from_millis(750));
    require(
        metrics.dropped.load(Ordering::Relaxed) > 0,
        "Physical capture queue did not saturate",
    )?;
    println!(
        "Intentional physical saturation attachment: input notification {}",
        metrics.failed.swap(false, Ordering::Relaxed)
    );
    fixture.warmup();
    config.lockin.integration_samples = 65536;
    worker.start_capture(4, capture, config.clone());
    let missing = wait(worker, fixture, config.lockin, |r| {
        r.state == lockin::State::Missing
    })?;
    require(
        missing.lockin.amplitude_peak.is_none() && missing.lockin.processed_windows == 0,
        "Physical gap retained values",
    )?;
    let invalid_end = missing.lockin.latest_window.end;
    worker.recycle(missing);
    let recovered = wait(worker, fixture, config.lockin, |r| {
        r.state == lockin::State::Valid
    })?;
    require(
        recovered.lockin.sample_range.start >= invalid_end,
        "Physical gap recovery mixed old samples",
    )?;
    worker.recycle(recovered);
    let final_snapshot = super::lockin::finish(worker)?;
    fixture.check()?;
    let dropped = metrics.dropped.load(Ordering::Relaxed);
    require(
        !final_snapshot.failed
            && final_snapshot.input_dropped == dropped
            && final_snapshot.lockin.missing_samples == dropped,
        "Physical capture/Lock-in gap accounting differs",
    )?;
    observe("capture gap recovery", &final_snapshot)?;
    drop(stream);
    println!(
        "Physical capture saturation/recovery OK: {dropped} frames; values invalidated and new contiguous average"
    );
    Ok(dropped)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn independent_fit_separates_dc_and_off_bin_phase() {
        let mut history = History::with_channels(4096, 2);
        for i in 0..4096 {
            let angle = TAU * 997.3 * i as f64 / 48000.0;
            history.push([0.3 + 0.125 * (angle + 0.7).sin(), -0.1 + 0.25 * angle.sin()]);
        }
        let r = fit(&history, 0..4096, 0, 48000, 997.3).unwrap();
        assert!((r.dc - 0.3).abs() < 1e-12);
        assert!((r.peak - 0.125).abs() < 1e-12);
        assert!((r.phase - 0.7_f64.to_degrees()).abs() < 1e-10);
        assert!(r.residual_rms < 1e-12);
        history.advance_to(5000);
        assert!(fit(&history, 0..4096, 0, 48000, 997.3).is_err());
    }
}
