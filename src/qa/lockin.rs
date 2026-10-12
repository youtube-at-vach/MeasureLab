//! Opt-in external virtual-I/O acceptance check. Never opens a physical output.
use crate::{
    audio, calibration, channel::Pair, export, lockin, measurement, results, spectrum, stft,
};
use cpal::traits::{DeviceTrait, HostTrait, StreamTrait};
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

#[derive(Clone, Copy)]
pub enum Tone {
    Base,
    Inverted,
    Tiny,
    Offset,
    Lost,
    Unstable,
    Step,
}

impl Tone {
    fn frequency(self) -> f64 {
        if matches!(self, Self::Offset) {
            1003.0
        } else {
            750.0
        }
    }
    fn amplitude(self) -> f64 {
        match self {
            Self::Tiny => 1.25e-8,
            Self::Step => 0.125,
            _ => 0.0625,
        }
    }
    fn phase(self, rate: u32) -> f64 {
        wrap(
            30.0 - 360.0 * self.frequency() * 3.0 / rate as f64
                + if matches!(self, Self::Inverted) {
                    180.0
                } else {
                    0.0
                },
        )
    }
}

pub struct Fixture {
    _stream: cpal::Stream,
    pub failed: Arc<AtomicBool>,
    errors: Arc<AtomicU64>,
    mode: Arc<AtomicUsize>,
}

impl Fixture {
    pub fn new(name: &str, rate: u32) -> Result<Self, String> {
        if !["BlackHole 2ch", "BlackHole 16ch"].contains(&name) {
            return Err("Lock-in output QA is restricted to BlackHole 2ch/16ch".into());
        }
        let output = cpal::default_host()
            .output_devices()
            .map_err(|e| e.to_string())?
            .find(|d| d.to_string() == name)
            .ok_or("BlackHole output was not found")?;
        let supported = output
            .supported_output_configs()
            .map_err(|e| e.to_string())?
            .filter(|c| c.sample_format() == cpal::SampleFormat::F32)
            .find_map(|c| c.try_with_sample_rate(rate))
            .ok_or("BlackHole f32 output does not support requested rate")?;
        let channels = supported.channels() as usize;
        if ![2, 16].contains(&channels) {
            return Err("Unexpected BlackHole channel count".into());
        }
        // Exactly one second, integer-Hz tones. All allocation/trigonometry is
        // outside the callback; output and input share the BlackHole device clock.
        let cycles: Vec<Vec<f32>> = [
            Tone::Base,
            Tone::Inverted,
            Tone::Tiny,
            Tone::Offset,
            Tone::Lost,
            Tone::Unstable,
            Tone::Step,
        ]
        .into_iter()
        .map(|tone| {
            (0..rate)
                .flat_map(|n| {
                    let theta = TAU * tone.frequency() * n as f64 / rate as f64;
                    let reference = if matches!(tone, Tone::Lost) {
                        0.2
                    } else {
                        0.125 * theta.sin()
                            + if matches!(tone, Tone::Unstable) {
                                0.0625 * (2.0 * theta).sin()
                            } else {
                                0.0
                            }
                    };
                    let response = tone.amplitude() * (theta + tone.phase(rate).to_radians()).sin()
                        + if matches!(tone, Tone::Tiny) { 0.0 } else { 0.2 };
                    (0..channels).map(move |ch| {
                        if ch == 0 {
                            reference as f32
                        } else if ch == channels - 1 {
                            response as f32
                        } else {
                            0.0
                        }
                    })
                })
                .collect()
        })
        .collect();
        let mode = Arc::new(AtomicUsize::new(0));
        let selected = mode.clone();
        let failed = Arc::new(AtomicBool::new(false));
        let errors = failed.clone();
        let error_count = Arc::new(AtomicU64::new(0));
        let count = error_count.clone();
        let mut head = 0;
        let stream = output
            .build_output_stream(
                supported.into(),
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
                    eprintln!("BlackHole Lock-in output error: {error}");
                    errors.store(true, Ordering::Relaxed);
                    count.fetch_add(1, Ordering::Relaxed);
                },
                Some(Duration::from_secs(2)),
            )
            .map_err(|e| e.to_string())?;
        stream.play().map_err(|e| e.to_string())?;
        Ok(Self {
            _stream: stream,
            failed,
            errors: error_count,
            mode,
        })
    }
    pub fn select(&self, tone: Tone) {
        self.mode.store(tone as usize, Ordering::Release);
    }
    pub fn end_warmup(&self, label: &str) {
        self.failed.store(false, Ordering::Relaxed);
        let errors = self.errors.swap(0, Ordering::Relaxed);
        println!(
            "BlackHole attachment warm-up ({label}): output notifications {errors}; excluded from the following measurement interval"
        );
    }
}

fn wrap(value: f64) -> f64 {
    (value + 180.0).rem_euclid(360.0) - 180.0
}

fn attach(device: &cpal::Device, rate: u32) -> Result<(cpal::Stream, audio::Capture), String> {
    let (stream, capture) = audio::start_device(device, Some(rate))?;
    // Keep the first 0.3 s in the bounded capture ring before handing it to
    // the worker, which treats stream failure as fatal. Nothing is renumbered
    // or discarded. The following 0.2 s completes the attachment warm-up;
    // Configure then starts a new average after that excluded interval.
    thread::sleep(Duration::from_millis(300));
    let input_notification = capture.metrics.failed.swap(false, Ordering::Relaxed);
    require(
        capture.metrics.dropped.load(Ordering::Relaxed) == 0,
        "Capture queue overflowed during attachment warm-up",
    )?;
    println!(
        "BlackHole pre-worker attachment warm-up: input notification {input_notification}, capture dropped 0; excluded from the following measurement interval"
    );
    Ok((stream, capture))
}
fn require(condition: bool, message: &str) -> Result<(), String> {
    if condition {
        Ok(())
    } else {
        Err(message.into())
    }
}

pub fn config(rate: u32, channels: usize) -> measurement::Config {
    measurement::Config {
        lockin: lockin::Settings {
            enabled: true,
            frequency_hz: 750.0,
            response_channel: channels - 1,
            ..Default::default()
        },
        spectrum: spectrum::Settings {
            size: 8192,
            averages: 1,
            ..Default::default()
        },
        spectrum_channel: channels - 1,
        spectrum_mode: measurement::SpectrumMode::Latest,
        scope: measurement::ScopeSettings {
            samples: 8192,
            channels: Pair([0, channels - 1]),
            trigger: crate::signal::Trigger {
                edge: crate::signal::Edge::Free,
                ..Default::default()
            },
            ..Default::default()
        },
        calibrations: calibration::Set::default(),
        xy_channels: Pair([0, channels - 1]),
        stft_generation: 1,
        stft: stft::Config {
            sample_rate: rate,
            channels,
            channel: channels - 1,
            size: 8192,
            hop: 2048,
            window: spectrum::Window::Hann,
            remove_dc: true,
            precision: spectrum::Precision::F64,
        },
    }
}

fn wait_result(
    worker: &mut measurement::Worker,
    predicate: impl Fn(&lockin::Result) -> bool,
) -> Result<lockin::Result, String> {
    wait_generation(worker, None, predicate)
}

fn wait_generation(
    worker: &mut measurement::Worker,
    generation: Option<u64>,
    predicate: impl Fn(&lockin::Result) -> bool,
) -> Result<lockin::Result, String> {
    let deadline = Instant::now() + Duration::from_secs(8);
    let mut last = None;
    while Instant::now() < deadline {
        if let Some(snapshot) = worker.take_latest() {
            let result = snapshot.lockin.clone();
            let clean = !snapshot.failed;
            let matches_generation = generation.is_none_or(|g| g == snapshot.generation);
            worker.recycle(snapshot);
            if !matches_generation {
                continue;
            }
            require(clean, "BlackHole input stream failed")?;
            if predicate(&result) {
                return Ok(result);
            }
            last = Some(result);
        }
        thread::sleep(Duration::from_millis(5));
    }
    Err(format!("Timed out waiting for external Lock-in: {last:?}"))
}

fn settled(
    worker: &mut measurement::Worker,
    settings: lockin::Settings,
    rate: u32,
) -> Result<lockin::Result, String> {
    wait_result(worker, |r| {
        r.settings == settings
            && r.state == lockin::State::Valid
            && (r.sample_range.end - r.sample_range.start) as f64
                >= 30.0 * settings.time_constant_seconds * rate as f64
    })
}

pub fn check_tone(result: &lockin::Result, tone: Tone, rate: u32) -> Result<(), String> {
    let amplitude = tone.amplitude();
    let phase = tone.phase(rate);
    let tolerance = if matches!(tone, Tone::Tiny) {
        1e-13
    } else {
        1e-7
    };
    require(
        result.state == lockin::State::Valid,
        "Lock-in is not settled",
    )?;
    for (actual, expected) in [
        (result.x, amplitude * phase.to_radians().cos()),
        (result.y, amplitude * phase.to_radians().sin()),
        (result.amplitude_peak, amplitude),
    ] {
        require(
            actual.is_some_and(|v| (v - expected).abs() < tolerance),
            &format!(
                "External amplitude mismatch: actual {actual:?}, expected {expected}, tolerance {tolerance}"
            ),
        )?;
    }
    require(
        result
            .phase_degrees
            .is_some_and(|v| wrap(v - phase).abs() < 1e-4),
        "External phase mismatch",
    )?;
    require(
        result
            .gain
            .is_some_and(|v| (v - amplitude / 0.125).abs() < tolerance * 10.0),
        "External gain mismatch",
    )?;
    require(
        result
            .reference_frequency_hz
            .is_some_and(|v| (v - tone.frequency()).abs() < 1e-3),
        "External REF frequency mismatch",
    )?;
    require(
        result
            .reference_peak
            .is_some_and(|v| (v - 0.125).abs() < 1e-7),
        "External REF amplitude mismatch",
    )
}

fn finish(worker: &measurement::Worker) -> Result<measurement::Snapshot, String> {
    let mut pending = worker.stop_async();
    let deadline = Instant::now() + Duration::from_secs(10);
    while Instant::now() < deadline {
        if let Some(snapshot) = pending.try_take() {
            return Ok(snapshot);
        }
        thread::sleep(Duration::from_millis(5));
    }
    Err("Finite Stop timed out".into())
}

fn document(
    snapshot: &measurement::Snapshot,
    source: export::Input,
    worker: &measurement::Worker,
) -> Result<export::Document, String> {
    let mut doc = export::Document::capture(
        source,
        export::ScopeView {
            history: &snapshot.history,
            settings: snapshot.scope_settings,
            sweep: snapshot.sweep.clone(),
            calibrations: &snapshot.calibrations,
            measurements: snapshot.measurements,
            readings: snapshot.scope_readings,
        },
        &snapshot.spectrum,
        &snapshot.spectrum_info,
        [0.0, snapshot.sample_rate as f64 / 2.0],
        export::Loss {
            capture_dropped_samples: snapshot.input_dropped,
            scope_missing_samples: snapshot.scope_missing,
            display_snapshots_skipped_since_worker_start: worker
                .metrics
                .display_skipped
                .load(Ordering::Relaxed),
            input_failed: snapshot.failed,
        },
    )?;
    doc.lockin = Some(export::Lockin::capture(
        snapshot.lockin.clone(),
        &snapshot.calibrations,
    ));
    doc.validate()?;
    Ok(doc)
}

fn step_response(
    worker: &mut measurement::Worker,
    fixture: &Fixture,
    settings: lockin::Settings,
    rate: u32,
) -> Result<(), String> {
    fixture.select(Tone::Base);
    worker.configure_lockin(settings);
    settled(worker, settings, rate)?;
    fixture.select(Tone::Step);
    let clock = Instant::now();
    let mut previous: Vec<lockin::Result> = Vec::new();
    let mut checks = 0;
    let mut excursion = false;
    let beta = (-(settings.integration_samples as f64)
        / (rate as f64 * settings.time_constant_seconds))
        .exp();
    let phase = Tone::Step.phase(rate).to_radians();
    let target = [0.125 * phase.cos(), 0.125 * phase.sin()];
    while clock.elapsed() < Duration::from_secs(3) {
        if let Some(snapshot) = worker.take_latest() {
            let r = snapshot.lockin.clone();
            require(
                !snapshot.failed && snapshot.input_dropped == 0,
                "Input loss during step response",
            )?;
            worker.recycle(snapshot);
            if previous
                .last()
                .is_none_or(|p| p.processed_windows != r.processed_windows)
            {
                if let Some(amplitude) = r.amplitude_peak {
                    excursion |= (0.065..0.12).contains(&amplitude);
                }
                previous.push(r);
                if previous.len() > 3 {
                    previous.remove(0);
                }
                // After the output transition/driver buffering, three adjacent
                // full windows obey the independently eliminated two-pole recurrence.
                if clock.elapsed() > Duration::from_millis(500)
                    && previous.len() == 3
                    && previous
                        .windows(2)
                        .all(|p| p[1].processed_windows == p[0].processed_windows + 1)
                {
                    for (coordinate, expected) in target.iter().enumerate() {
                        let values: Vec<_> = previous
                            .iter()
                            .map(|p| if coordinate == 0 { p.x } else { p.y })
                            .collect();
                        let [Some(a), Some(b), Some(c)] = values[..] else {
                            return Err("Invalid step response".into());
                        };
                        let predicted =
                            2.0 * beta * b - beta * beta * a + (1.0 - beta).powi(2) * expected;
                        require(
                            (c - predicted).abs() < 1e-7,
                            "External two-pole step response mismatch",
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
        "Step response did not provide enough transient/adjacent windows",
    )?;
    check_tone(previous.last().ok_or("No step response")?, Tone::Step, rate)?;
    println!(
        "External step response OK: τ={} s, {checks} adjacent-window recurrence checks",
        settings.time_constant_seconds
    );
    Ok(())
}

pub fn smoke_test(name: &str, rate: u32) -> Result<(), Box<dyn std::error::Error>> {
    let seconds = match std::env::var("MEASURELAB_LOCKIN_SECONDS") {
        Ok(value) => value
            .parse::<u64>()
            .ok()
            .filter(|s| (1..=3600).contains(s))
            .ok_or("MEASURELAB_LOCKIN_SECONDS must be 1–3600")?,
        Err(std::env::VarError::NotPresent) => 10,
        Err(_) => return Err("Invalid MEASURELAB_LOCKIN_SECONDS".into()),
    };
    require(
        ["BlackHole 2ch", "BlackHole 16ch"].contains(&name),
        "Lock-in QA requires BlackHole 2ch/16ch",
    )?;
    let device = audio::input_device(Some(name))?;
    let original_rate = device.default_input_config()?.sample_rate();
    let outcome = run(name, rate, seconds, &device).and_then(|()| {
        if std::env::var_os("MEASURELAB_LOCKIN_TRANSITIONS").is_some() {
            transitions()
        } else {
            Ok(())
        }
    });
    // CPAL changes the device's nominal rate on macOS. Restore even on failure,
    // after all measurement/output streams have been released.
    let restore = audio::start_device(&device, Some(original_rate));
    match restore {
        Ok((stream, _)) => {
            drop(stream);
            println!("BlackHole rate restored to {original_rate} Hz");
        }
        Err(error) => {
            return Err(format!(
                "QA outcome {outcome:?}; failed to restore BlackHole rate: {error}"
            )
            .into());
        }
    }
    outcome.map_err(Into::into)
}

fn run(name: &str, rate: u32, seconds: u64, device: &cpal::Device) -> Result<(), String> {
    let run_clock = Instant::now();
    let channels = device
        .default_input_config()
        .map_err(|e| e.to_string())?
        .channels() as usize;
    let fixture = Fixture::new(name, rate)?;
    thread::sleep(Duration::from_millis(300));
    let (stream, capture) = attach(device, rate)?;
    require(
        capture.sample_rate == rate && capture.channels as usize == channels,
        "External input topology/rate mismatch",
    )?;
    let metrics = capture.metrics.clone();
    let mut stft = stft::Worker::new();
    let mut worker = measurement::Worker::new(stft.take_feeder());
    let mut config = config(rate, channels);
    worker.start_capture(1, capture, config.clone());
    thread::sleep(Duration::from_millis(200));
    fixture.end_warmup("baseline");
    worker.configure_lockin(config.lockin);
    check_tone(
        &settled(&mut worker, config.lockin, rate)?,
        Tone::Base,
        rate,
    )?;
    let source = export::Input {
        generation: 1,
        nominal_sample_rate_hz: rate,
        channels,
        source: export::Source::Audio {
            device_id: device.id().ok().map(|id| id.to_string()),
            device_name: name.into(),
            sample_format: "f32".into(),
            requested_sample_rate_hz: Some(rate),
        },
    };
    let first = finish(&worker)?;
    require(
        first.generation == 1,
        "Baseline retained an old input generation",
    )?;
    require(
        !fixture.failed.load(Ordering::Relaxed),
        "Output error during external baseline",
    )?;
    check_tone(&first.lockin, Tone::Base, rate)?;
    require(
        first.input_dropped == 0 && first.lockin.missing_samples == 0 && !first.failed,
        "Loss during baseline capture",
    )?;
    let bin = 750.0 * 8192.0 / rate as f64;
    if bin.fract() == 0.0 {
        require(
            (first.spectrum.power()[bin as usize].sqrt() - 0.0625).abs() < 1e-7,
            "External Spectrum/Lock-in amplitude mismatch",
        )?;
    }
    let held = first.lockin.clone();
    worker.configure_lockin(lockin::Settings {
        frequency_hz: 2000.0,
        ..config.lockin
    });
    require(
        finish(&worker)?.lockin == held,
        "Held Lock-in changed with next-start edits/repeated Stop",
    )?;
    let doc = document(&first, source.clone(), &worker)?;
    let stem = format!("dist/lockin-blackhole-qa/{}-{rate}", channels);
    std::fs::create_dir_all("dist/lockin-blackhole-qa").map_err(|e| e.to_string())?;
    export::save(Path::new(&format!("{stem}.json")), &doc)?;
    results::save_csv(Path::new(&format!("{stem}.csv")), &doc)?;
    require(
        results::load(Path::new(&format!("{stem}.json")))? == doc,
        "Saved external result round trip mismatch",
    )?;
    drop(stream);
    let (stream, capture) = attach(device, rate)?;
    worker.start_capture(2, capture, config.clone());
    thread::sleep(Duration::from_millis(200));
    fixture.end_warmup("recapture");
    worker.configure_lockin(config.lockin);
    check_tone(
        &settled(&mut worker, config.lockin, rate)?,
        Tone::Base,
        rate,
    )?;
    let second = finish(&worker)?;
    require(
        second.generation == 2,
        "Recapture retained an old input generation",
    )?;
    require(
        !fixture.failed.load(Ordering::Relaxed),
        "Output error during external recapture",
    )?;
    let mut second_source = source;
    second_source.generation = 2;
    let second_doc = document(&second, second_source, &worker)?;
    let difference = results::lockin_difference(&doc, &second_doc)
        .ok_or("External recapture is not comparable")?;
    require(
        difference.amplitude_peak.abs() < 1e-7 && difference.phase_degrees.abs() < 1e-4,
        "External save/recapture differs",
    )?;
    println!(
        "External baseline/Stop/restart/save/recapture OK: {name}, {rate} Hz, CH 1 / CH {channels}, R={:.12}, phase={:.9}°, gain={:.12}",
        second.lockin.amplitude_peak.unwrap(),
        second.lockin.phase_degrees.unwrap(),
        second.lockin.gain.unwrap()
    );
    drop(stream);
    let (stream, capture) = attach(device, rate)?;
    let live_metrics = capture.metrics.clone();
    worker.start_capture(3, capture, config.clone());
    thread::sleep(Duration::from_millis(200));
    fixture.end_warmup("live scenarios");
    for (label, tone) in [
        ("polarity", Tone::Inverted),
        ("tiny", Tone::Tiny),
        ("tracking", Tone::Offset),
    ] {
        fixture.select(tone);
        config.lockin.frequency_hz = tone.frequency();
        if matches!(tone, Tone::Offset) {
            config.lockin.frequency_hz = 1000.0;
        }
        worker.configure_lockin(config.lockin);
        // Flush a transitional window before beginning the definitive average.
        thread::sleep(Duration::from_millis(250));
        worker.configure_lockin(config.lockin);
        let result = settled(&mut worker, config.lockin, rate)?;
        check_tone(&result, tone, rate)?;
        println!(
            "External {label} OK: R={:.12e}, phase={:.9}°, REF={:.9} Hz",
            result.amplitude_peak.unwrap(),
            result.phase_degrees.unwrap(),
            result.reference_frequency_hz.unwrap()
        );
    }
    fixture.select(Tone::Base);
    config.lockin.frequency_hz = 750.0;
    worker.configure_lockin(config.lockin);
    settled(&mut worker, config.lockin, rate)?;
    for (tone, state) in [
        (Tone::Lost, lockin::State::ReferenceLost),
        (Tone::Unstable, lockin::State::ReferenceUnstable),
    ] {
        fixture.select(tone);
        let invalid = wait_result(&mut worker, |r| r.state == state)?;
        require(
            invalid.x.is_none() && invalid.gain.is_none() && invalid.processed_windows == 0,
            "Invalid REF retained old readings",
        )?;
        fixture.select(Tone::Base);
        wait_result(&mut worker, |r| {
            r.state == lockin::State::Settling && r.processed_windows > 0
        })?;
        check_tone(
            &settled(&mut worker, config.lockin, rate)?,
            Tone::Base,
            rate,
        )?;
        println!("External {state:?}/re-settling/recovery OK");
    }
    let swapped = lockin::Settings {
        reference_channel: channels - 1,
        response_channel: 0,
        ..config.lockin
    };
    worker.configure_lockin(swapped);
    let result = settled(&mut worker, swapped, rate)?;
    require(
        (result.amplitude_peak.unwrap() - 0.125).abs() < 1e-7
            && wrap(result.phase_degrees.unwrap() + Tone::Base.phase(rate)).abs() < 1e-4
            && (result.gain.unwrap() - 2.0).abs() < 1e-6,
        "Swapped external CH phase/gain mismatch",
    )?;
    let same = lockin::Settings {
        response_channel: 0,
        ..config.lockin
    };
    worker.configure_lockin(same);
    let result = settled(&mut worker, same, rate)?;
    require(
        result.phase_degrees.unwrap().abs() < 1e-10 && (result.gain.unwrap() - 1.0).abs() < 1e-10,
        "External same-CH self-check failed",
    )?;
    println!("External swapped/same CH OK");
    step_response(
        &mut worker,
        &fixture,
        lockin::Settings {
            time_constant_seconds: 0.1,
            // Latest display publications are 30 Hz; at 192 kHz a 4096
            // sample window is shorter than that. Use 16384 here so the
            // transient observer can receive adjacent complete windows.
            integration_samples: if rate > 96000 {
                16384
            } else {
                config.lockin.integration_samples
            },
            ..config.lockin
        },
        rate,
    )?;
    fixture.select(Tone::Base);
    worker.configure_lockin(config.lockin);
    settled(&mut worker, config.lockin, rate)?;
    let mut count = 0;
    let mut amplitude_error: f64 = 0.0;
    let mut phase_error: f64 = 0.0;
    let clock = Instant::now();
    println!(
        "External stability interval starts at {:.3} s after QA entry",
        run_clock.elapsed().as_secs_f64()
    );
    let mut next_report = 60;
    while clock.elapsed() < Duration::from_secs(seconds) {
        if let Some(snapshot) = worker.take_latest() {
            check_tone(&snapshot.lockin, Tone::Base, rate)?;
            require(
                !snapshot.failed
                    && snapshot.input_dropped == 0
                    && snapshot.lockin.missing_samples == 0
                    && !fixture.failed.load(Ordering::Relaxed),
                "Loss during external stability interval",
            )?;
            amplitude_error =
                amplitude_error.max((snapshot.lockin.amplitude_peak.unwrap() - 0.0625).abs());
            phase_error = phase_error
                .max(wrap(snapshot.lockin.phase_degrees.unwrap() - Tone::Base.phase(rate)).abs());
            count += 1;
            worker.recycle(snapshot);
        }
        if clock.elapsed().as_secs() >= next_report {
            println!(
                "External stability progress: {next_report} s, {count} observations, max R error {amplitude_error:.3e} FS peak, max phase error {phase_error:.3e}°, no input/Lock-in gaps or stream errors"
            );
            next_report += 60;
        }
        thread::sleep(Duration::from_millis(5));
    }
    let final_snapshot = finish(&worker)?;
    check_tone(&final_snapshot.lockin, Tone::Base, rate)?;
    require(
        count > 0
            && final_snapshot.input_dropped == 0
            && final_snapshot.lockin.missing_samples == 0
            && !final_snapshot.failed,
        "External stability/finite stop failed",
    )?;
    let r = &final_snapshot.lockin;
    require(
        r.sample_range.end - r.sample_range.start
            == r.processed_windows * config.lockin.integration_samples as u64
            && r.latest_window.end == r.sample_range.end
            && final_snapshot.history.range().end - r.latest_window.end
                < config.lockin.integration_samples as u64,
        "External finite endpoint/window accounting mismatch",
    )?;
    require(
        !fixture.failed.load(Ordering::Relaxed),
        "BlackHole output stream failed",
    )?;
    println!(
        "External stability OK: {seconds} s, {count} observations, max R error {amplitude_error:.3e} FS peak, max phase error {phase_error:.3e}°, {} complete windows, finite input end {}, no input/Lock-in gaps; input callback frames {}..{} (baseline {}..{})",
        r.processed_windows,
        final_snapshot.history.range().end,
        live_metrics.callback_min_frames.load(Ordering::Relaxed),
        live_metrics.callback_max_frames.load(Ordering::Relaxed),
        metrics.callback_min_frames.load(Ordering::Relaxed),
        metrics.callback_max_frames.load(Ordering::Relaxed)
    );
    drop(stream);
    // Real capture-ring saturation: keep callback running while deliberately
    // withholding its consumer, then hand the same numbered frames to the core.
    let (stream, capture) = audio::start_device(device, Some(rate))?;
    let overflow = capture.metrics.clone();
    thread::sleep(Duration::from_millis(750));
    require(
        overflow.dropped.load(Ordering::Relaxed) > 0,
        "External capture queue did not saturate",
    )?;
    fixture.end_warmup("deliberate capture saturation");
    println!(
        "BlackHole saturation attachment warm-up: input notification {}",
        overflow.failed.swap(false, Ordering::Relaxed)
    );
    config.lockin.integration_samples = 65536;
    worker.start_capture(4, capture, config.clone());
    let missing = wait_result(&mut worker, |r| r.state == lockin::State::Missing)?;
    require(
        missing.x.is_none() && missing.gain.is_none(),
        "External gap retained old readings",
    )?;
    let recovered = settled(&mut worker, config.lockin, rate)?;
    check_tone(&recovered, Tone::Base, rate)?;
    let gap = finish(&worker)?;
    let dropped = overflow.dropped.load(Ordering::Relaxed);
    require(
        gap.input_dropped == dropped
            && recovered.missing_samples == dropped
            && gap.lockin.missing_samples == dropped,
        "External gap counts disagree with capture queue",
    )?;
    require(
        recovered.sample_range.start >= missing.latest_window.end && !gap.failed,
        "External gap recovery interval/input failure",
    )?;
    require(
        !fixture.failed.load(Ordering::Relaxed),
        "Output error during external gap recovery",
    )?;
    println!(
        "External capture saturation/recovery OK: {dropped} missing frames, readings invalidated, new contiguous interval {:?}",
        recovered.sample_range
    );
    drop(stream);
    println!(
        "Stage 4b BlackHole Lock-in QA OK (physical REF/response and variable callback coverage require separate evidence)"
    );
    Ok(())
}

fn transitions() -> Result<(), String> {
    let mut stft = stft::Worker::new();
    let mut worker = measurement::Worker::new(stft.take_feeder());
    for (index, (name, rate)) in [
        ("BlackHole 2ch", 48000),
        ("BlackHole 2ch", 96000),
        ("BlackHole 16ch", 96000),
        ("BlackHole 2ch", 44100),
        ("BlackHole 16ch", 192000),
        ("BlackHole 2ch", 48000),
    ]
    .into_iter()
    .enumerate()
    {
        let device = audio::input_device(Some(name))?;
        let original_rate = device
            .default_input_config()
            .map_err(|e| e.to_string())?
            .sample_rate();
        let fixture = Fixture::new(name, rate)?;
        let (stream, capture) = attach(&device, rate)?;
        let channels = capture.channels as usize;
        let generation = index as u64 + 10;
        let mut config = config(rate, channels);
        if index == 3 {
            config.lockin.response_channel = 15;
        }
        worker.start_capture(generation, capture, config.clone());
        thread::sleep(Duration::from_millis(200));
        fixture.end_warmup("Fs/device transition");
        let outcome: Result<(), String> = (|| {
            if index == 3 {
                let unavailable = wait_generation(&mut worker, Some(generation), |r| {
                    r.state == lockin::State::Unavailable
                })?;
                require(
                    unavailable.x.is_none() && unavailable.gain.is_none(),
                    "Unavailable CH 16 retained old readings on 2ch device",
                )?;
                config.lockin.response_channel = channels - 1;
            }
            worker.configure_lockin(config.lockin);
            let result = wait_generation(&mut worker, Some(generation), |r| {
                r.settings == config.lockin
                    && r.state == lockin::State::Valid
                    && (r.sample_range.end - r.sample_range.start) as f64 >= 0.6 * rate as f64
            })?;
            check_tone(&result, Tone::Base, rate)?;
            let snapshot = finish(&worker)?;
            require(
                snapshot.generation == generation
                    && snapshot.sample_rate == rate
                    && snapshot.history.channels() == channels
                    && snapshot.lockin.settings == config.lockin
                    && snapshot.input_dropped == 0
                    && snapshot.lockin.missing_samples == 0
                    && !snapshot.failed,
                "Fs/device transition mixed provenance or lost input",
            )?;
            require(
                !fixture.failed.load(Ordering::Relaxed),
                "Output failed during Fs/device transition",
            )?;
            println!(
                "External Fs/device transition OK: generation {generation}, {name}, {rate} Hz, CH 1 / CH {channels}, phase {:.9}°{}",
                snapshot.lockin.phase_degrees.unwrap(),
                if index == 3 {
                    "; unavailable CH 16 cleared before valid CH 2"
                } else {
                    ""
                }
            );
            Ok(())
        })();
        if outcome.is_err() {
            let _ = finish(&worker);
        }
        drop(stream);
        drop(fixture);
        let (restore, _) = audio::start_device(&device, Some(original_rate))?;
        drop(restore);
        outcome?;
    }
    Ok(())
}
