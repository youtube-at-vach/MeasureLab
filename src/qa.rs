//! Opt-in, bounded UI measurements for local QA runs.
use std::time::{Duration, Instant};

/// A finite internal software fixture using the same FFT/history as live input.
/// Includes texture wrapping, a changing tone and an explicit acquisition gap.
pub fn spectrogram_fixture(output: &mut crate::spectrogram::History) -> crate::stft::RowInfo {
    use crate::{
        demo::Demo,
        signal::History,
        spectrum::{Analyzer, Settings},
        stft::{Config, Gap, RowInfo},
    };
    let settings = Settings {
        averages: 1,
        ..Settings::default()
    };
    let config = Config {
        sample_rate: 48000,
        channels: 2,
        channel: 0,
        size: settings.size,
        hop: settings.size / 4,
        window: settings.window,
        remove_dc: true,
    };
    output.reset(1, config);
    let mut source = History::new(config.size);
    let mut demo = Demo::default();
    let mut analyzer = Analyzer::new(settings, config.sample_rate);
    for i in 0..700 {
        demo.frequency = 200.0 * 40_f32.powf(i as f32 / 699.0);
        let mut gap = Gap::default();
        let count = if i == 0 {
            config.size
        } else if i == 620 {
            source.clear_at(source.range().end + 4 * config.hop as u64);
            gap.input_frames = 4 * config.hop as u64;
            gap.discontinuity = true;
            config.size
        } else {
            config.hop
        };
        demo.append(&mut source, count, config.sample_rate);
        let end = source.range().end;
        assert!(analyzer.update_window(&source, end - config.size as u64..end, 0));
        assert!(output.push(
            RowInfo {
                generation: 1,
                config,
                start: end - config.size as u64,
                end,
                gap
            },
            analyzer.db()
        ));
    }
    output.latest().unwrap()
}

pub struct Profile {
    started: Instant,
    duration: Duration,
    intervals_ms: Vec<f64>,
    pub device: Option<String>,
}

impl Profile {
    pub fn from_env() -> Option<Self> {
        let seconds = std::env::var("MEASURELAB_PROFILE_SECONDS")
            .ok()?
            .parse::<u64>()
            .ok()?
            .clamp(1, 60);
        Some(Self {
            started: Instant::now(),
            duration: Duration::from_secs(seconds + 2),
            intervals_ms: Vec::with_capacity(8192),
            device: std::env::var("MEASURELAB_PROFILE_DEVICE").ok(),
        })
    }

    pub fn record(&mut self, elapsed_seconds: f64, running: bool) {
        if running
            && self.started.elapsed() >= Duration::from_secs(2)
            && self.intervals_ms.len() < self.intervals_ms.capacity()
        {
            self.intervals_ms.push(elapsed_seconds * 1000.0);
        }
    }

    pub fn finished(&self) -> bool {
        self.started.elapsed() >= self.duration
    }

    pub fn report(&mut self, input_dropped: u64) {
        self.intervals_ms.sort_unstable_by(f64::total_cmp);
        if self.intervals_ms.is_empty() {
            println!("UI profile: no running frames recorded; input dropped {input_dropped}");
        } else {
            let p95 = self.intervals_ms[(self.intervals_ms.len() - 1) * 95 / 100];
            println!(
                "UI profile: {} frames, frame interval p95 {p95:.3} ms, input dropped {input_dropped}",
                self.intervals_ms.len()
            );
        }
    }
}

/// A local fixture restricted to BlackHole 16ch. The normal app has no audio
/// output path; this opt-in QA check sends a different bin-centred tone to each
/// virtual channel and checks the capture, shared history and CH 16 STFT.
pub fn multichannel_smoke_test() -> Result<(), Box<dyn std::error::Error>> {
    use crate::{
        audio,
        signal::History,
        spectrum::{Analyzer, Settings, Window},
        stft,
    };
    use cpal::traits::{DeviceTrait, HostTrait, StreamTrait};
    use std::{
        f64::consts::TAU,
        sync::{
            Arc,
            atomic::{AtomicBool, Ordering},
        },
        thread,
    };

    let input = audio::input_device(Some("BlackHole 16ch"))?;
    let output = cpal::default_host()
        .output_devices()?
        .find(|d| d.to_string() == "BlackHole 16ch")
        .ok_or("BlackHole 16ch output was not found")?;
    let supported = output.default_output_config()?;
    if supported.channels() != 16 || supported.sample_format() != cpal::SampleFormat::F32 {
        return Err("BlackHole QA requires 16ch f32 output".into());
    }
    let output_rate = supported.sample_rate();
    let (_input_stream, mut capture) = audio::start_device(&input)?;
    if capture.channels != 16 || capture.sample_rate != output_rate {
        return Err("BlackHole QA requires matching input/output rates and 16ch input".into());
    }
    let failed = Arc::new(AtomicBool::new(false));
    let failure = failed.clone();
    let mut sequence = 0_u64;
    let output_stream = output.build_output_stream(
        supported.into(),
        move |data: &mut [f32], _| {
            for frame in data.as_chunks_mut::<16>().0 {
                for (ch, sample) in frame.iter_mut().enumerate() {
                    *sample = (0.125
                        * (TAU * (32 + ch * 7) as f64 * (sequence % 8192) as f64 / 8192.0).sin())
                        as f32;
                }
                sequence += 1;
            }
        },
        move |error| {
            eprintln!("BlackHole fixture output error: {error}");
            failure.store(true, Ordering::Relaxed);
        },
        Some(Duration::from_secs(2)),
    )?;
    output_stream.play()?;
    // CoreAudio can report startup overloads while attaching both streams.
    // Drain and count them during an explicit warm-up, then require a clean
    // measurement interval rather than interpreting startup as measured data.
    let warmup = Instant::now() + Duration::from_millis(500);
    while Instant::now() < warmup {
        while capture.consumer.pop().is_ok() {}
        thread::sleep(Duration::from_millis(5));
    }
    let startup_output_error = failed.swap(false, Ordering::Relaxed);
    let startup_input_error = capture.metrics.failed.swap(false, Ordering::Relaxed);
    let startup_dropped = capture.metrics.dropped.swap(0, Ordering::Relaxed);
    println!(
        "BlackHole fixture warm-up: output error {startup_output_error}, input error {startup_input_error}, capture dropped {startup_dropped}"
    );
    let mut history = History::with_channels(8192, 16);
    let mut worker = stft::Worker::new();
    worker.configure(stft::Config {
        sample_rate: capture.sample_rate,
        channels: 16,
        channel: 15,
        size: 8192,
        hop: 2048,
        window: Window::Hann,
        remove_dc: true,
    })?;
    let mut last_db = None;
    let mut frames = 0;
    let deadline = Instant::now() + Duration::from_secs(2);
    while Instant::now() < deadline {
        let available = capture.consumer.slots();
        if let Ok(chunk) = capture.consumer.read_chunk(available) {
            for frame in chunk {
                history.push_at(frame.sequence, frame.samples);
                worker.submit(frame.sequence, &frame.samples);
                frames += 1;
            }
        }
        worker.flush();
        worker.drain(|row| last_db = Some(row.db()[137]));
        thread::sleep(Duration::from_millis(5));
    }
    let settle = Instant::now() + Duration::from_millis(100);
    while Instant::now() < settle {
        worker.drain(|row| last_db = Some(row.db()[137]));
        thread::sleep(Duration::from_millis(2));
    }
    if failed.load(Ordering::Relaxed)
        || capture.metrics.failed.load(Ordering::Relaxed)
        || capture.metrics.dropped.load(Ordering::Relaxed) > 0
        || worker.metrics.input_dropped.load(Ordering::Relaxed) > 0
        || worker.metrics.result_dropped.load(Ordering::Relaxed) > 0
    {
        return Err(format!("BlackHole QA: output failed {}, input failed {}, capture dropped {}, worker dropped {}, result dropped {}",
            failed.load(Ordering::Relaxed), capture.metrics.failed.load(Ordering::Relaxed),
            capture.metrics.dropped.load(Ordering::Relaxed),
            worker.metrics.input_dropped.load(Ordering::Relaxed),
            worker.metrics.result_dropped.load(Ordering::Relaxed)).into());
    }
    let mut analyzer = Analyzer::new(
        Settings {
            averages: 1,
            ..Settings::default()
        },
        capture.sample_rate,
    );
    let expected_db = 20.0 * 0.125_f32.log10();
    for ch in 0..16 {
        if !analyzer.update(&history, ch) {
            return Err(format!("CH {} has no complete FFT window", ch + 1).into());
        }
        let bin = 32 + ch * 7;
        let (peak_bin, _) = analyzer
            .db()
            .iter()
            .enumerate()
            .skip(1)
            .max_by(|a, b| a.1.total_cmp(b.1))
            .unwrap();
        if peak_bin != bin || (analyzer.db()[bin] - expected_db).abs() > 0.02 {
            return Err(format!(
                "CH {} mapping or amplitude failed: bin {peak_bin}, {:.3} dBFS",
                ch + 1,
                analyzer.db()[bin]
            )
            .into());
        }
    }
    let stft_db = last_db.ok_or("No CH 16 STFT row received")?;
    if (stft_db - expected_db).abs() > 0.02 {
        return Err(format!("CH 16 STFT amplitude failed: {stft_db:.3} dBFS").into());
    }
    println!(
        "BlackHole 16ch tones OK: {} Hz, {frames} frames, all 16 channel mappings / bin frequencies / amplitudes verified, CH 16 STFT {stft_db:.3} dBFS, no capture / worker / result losses",
        capture.sample_rate
    );
    Ok(())
}
