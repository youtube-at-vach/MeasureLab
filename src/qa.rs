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
        precision: crate::spectrum::Precision::F64,
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

/// Cursor screenshots use the same retained frames for every instrument,
/// including an acquisition gap and a complete latest FFT window.
pub fn cursor_fixture(
    output: &mut crate::spectrogram::History,
    source: &mut crate::signal::History,
    demo: &mut crate::demo::Demo,
    sample_rate: u32,
) -> crate::stft::RowInfo {
    use crate::{
        spectrum::{Analyzer, Settings},
        stft::{Config, Gap, RowInfo},
    };
    let settings = Settings {
        averages: 1,
        ..Settings::default()
    };
    let config = Config {
        sample_rate,
        channels: source.channels(),
        channel: 0,
        size: settings.size,
        hop: settings.size / 4,
        window: settings.window,
        remove_dc: settings.remove_dc,
        precision: settings.precision,
    };
    output.reset(1, config);
    source.clear_at(0);
    let mut analyzer = Analyzer::new(settings, sample_rate);
    for index in 0..40 {
        let mut gap = Gap::default();
        let count = if index == 0 {
            config.size
        } else if index == 24 {
            gap.input_frames = 2 * config.hop as u64;
            gap.discontinuity = true;
            source.clear_at(source.range().end + gap.input_frames);
            config.size
        } else {
            config.hop
        };
        demo.append(source, count, sample_rate);
        let end = source.range().end;
        assert!(analyzer.update_window(source, end - config.size as u64..end, 0));
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

// Fixed-size histograms cover the entire run, including long and unthrottled
// runs. Keeping only the first 8,192 frames hid later stalls and memory growth.
const BUCKET_MS: f64 = 0.01;
const BUCKETS: usize = 20_001;

struct Distribution {
    bins: Vec<u64>,
    count: u64,
    max: f64,
}

impl Default for Distribution {
    fn default() -> Self {
        Self {
            bins: vec![0; BUCKETS],
            count: 0,
            max: 0.0,
        }
    }
}

impl Distribution {
    fn record(&mut self, milliseconds: f64) {
        if !milliseconds.is_finite() || milliseconds < 0.0 {
            return;
        }
        let bucket = (milliseconds / BUCKET_MS).ceil() as usize;
        self.bins[bucket.min(BUCKETS - 1)] += 1;
        self.count += 1;
        self.max = self.max.max(milliseconds);
    }

    fn p95(&self) -> Option<f64> {
        if self.count == 0 {
            return None;
        }
        let target = (self.count * 95).div_ceil(100);
        let mut count = 0;
        for (index, &bin) in self.bins.iter().enumerate() {
            count += bin;
            if count >= target {
                // The overflow bucket gives a conservative upper bound.
                return Some(if index == BUCKETS - 1 {
                    self.max
                } else {
                    index as f64 * BUCKET_MS
                });
            }
        }
        unreachable!("histogram count");
    }
}

#[derive(Clone, Copy)]
pub enum Work {
    Input,
    Scope,
    Spectrum,
    Spectrogram,
    Xy,
}

impl Work {
    fn name(self) -> &'static str {
        match self {
            Self::Input => "control events / snapshot ingestion",
            Self::Scope => "Scope preparation",
            Self::Spectrum => "Spectrum preparation",
            Self::Spectrogram => "STFT result / history ingestion",
            Self::Xy => "XY preparation",
        }
    }
}

pub struct Profile {
    started: Instant,
    duration: Duration,
    intervals_ms: Distribution,
    cpu_ms: Distribution,
    work: [Distribution; 5],
    input_dropped: u64,
    previous_input_dropped: u64,
    pub device: Option<String>,
}

impl Profile {
    pub fn from_env() -> Result<Option<Self>, String> {
        let seconds = match std::env::var("MEASURELAB_PROFILE_SECONDS") {
            Ok(seconds) => seconds,
            Err(std::env::VarError::NotPresent) => return Ok(None),
            Err(error) => return Err(error.to_string()),
        };
        let seconds = seconds
            .parse::<u64>()
            .map_err(|_| "MEASURELAB_PROFILE_SECONDS must be 1..=3600".to_owned())?;
        if !(1..=3600).contains(&seconds) {
            return Err("MEASURELAB_PROFILE_SECONDS must be 1..=3600".into());
        }
        Ok(Some(Self {
            started: Instant::now(),
            duration: Duration::from_secs(seconds + 2),
            intervals_ms: Distribution::default(),
            cpu_ms: Distribution::default(),
            work: std::array::from_fn(|_| Distribution::default()),
            input_dropped: 0,
            previous_input_dropped: 0,
            device: std::env::var("MEASURELAB_PROFILE_DEVICE").ok(),
        }))
    }

    pub fn record(&mut self, elapsed_seconds: f64, running: bool, cpu_seconds: Option<f32>) {
        if running && self.started.elapsed() >= Duration::from_secs(2) {
            self.intervals_ms.record(elapsed_seconds * 1000.0);
            if let Some(cpu) = cpu_seconds {
                self.cpu_ms.record(cpu as f64 * 1000.0);
            }
        }
    }

    pub fn record_work(&mut self, work: Work, milliseconds: f64) {
        if self.started.elapsed() >= Duration::from_secs(2) {
            self.work[work as usize].record(milliseconds);
        }
    }

    pub fn record_input_loss(&mut self, dropped: u64) {
        self.input_dropped += dropped.saturating_sub(self.previous_input_dropped);
        self.previous_input_dropped = dropped;
    }

    pub fn new_input(&mut self, dropped: u64) {
        self.record_input_loss(dropped);
        self.previous_input_dropped = 0;
    }

    pub fn finished(&self) -> bool {
        self.started.elapsed() >= self.duration
    }

    pub fn report(&self, input_dropped: u64) {
        let input_dropped =
            self.input_dropped + input_dropped.saturating_sub(self.previous_input_dropped);
        let p95 = self
            .intervals_ms
            .p95()
            .expect("QA recorded no running frames");
        println!(
            "UI profile: {} frames over {:.1} s, frame interval p95 {p95:.3} ms, max {:.3} ms, input dropped {input_dropped}",
            self.intervals_ms.count,
            self.started.elapsed().as_secs_f64(),
            self.intervals_ms.max
        );
        if let Some(cpu_p95) = self.cpu_ms.p95() {
            println!(
                "UI CPU profile: frame work p95 {cpu_p95:.3} ms (eframe, excluding VSync wait)"
            );
        }
        for work in [
            Work::Input,
            Work::Scope,
            Work::Spectrum,
            Work::Spectrogram,
            Work::Xy,
        ] {
            let distribution = &self.work[work as usize];
            if let Some(p95) = distribution.p95() {
                println!(
                    "CPU component: {} / {} calls / p95 {p95:.3} ms / max {:.3} ms",
                    work.name(),
                    distribution.count,
                    distribution.max
                );
            }
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
        precision: crate::spectrum::Precision::F64,
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
    for pair in [crate::channel::Pair([15, 7]), crate::channel::Pair([7, 15])] {
        let measurements = crate::signal::measure(&history, history.range(), pair);
        for (channel, measurement) in pair.0.into_iter().zip(measurements) {
            if measurement.samples != 8192
                || (measurement.rms - 0.125 / 2.0_f64.sqrt()).abs() > 1e-8
                || (measurement.peak - 0.125).abs() > 1e-5
                || (measurement.peak_to_peak - 0.25).abs() > 2e-5
            {
                return Err(format!(
                    "CH {} Scope raw statistics failed: {measurement:?}",
                    channel + 1
                )
                .into());
            }
        }
        let settings = crate::xy::Settings {
            channels: pair,
            milliseconds: 200.0,
            ..Default::default()
        };
        let mut lines = Vec::new();
        let xy = crate::xy::build_lines(&history, capture.sample_rate, settings, &mut lines);
        if xy.range != history.range() || lines.len() != 8191 {
            return Err("XY routed capture incomplete".into());
        }
        let sample = xy.range.end - 17;
        let raw = pair
            .values(history.get(sample).ok_or("XY sample missing")?)
            .unwrap();
        let point = settings.fraction_at_point(raw);
        let nearest = crate::xy::nearest_sample(&history, xy.range, settings, point)
            .ok_or("XY routed snap unavailable")?;
        if pair.values(history.get(nearest).unwrap()) != Some(raw) {
            return Err("XY routed snap selected a different pair".into());
        }
    }
    println!(
        "BlackHole routed Scope/XY OK: CH 16 / CH 8 and swapped sources; 0.125 FS peak, RMS 0.125/√2, P-P 0.25 FS, synchronous Trace Snap"
    );
    println!(
        "BlackHole 16ch tones OK: {} Hz, {frames} frames, all 16 channel mappings / bin frequencies / amplitudes verified, CH 16 STFT {stft_db:.3} dBFS, no capture / worker / result losses",
        capture.sample_rate
    );
    Ok(())
}

#[cfg(test)]
mod tests {
    #[test]
    fn profile_keeps_late_frames_and_bounded_storage() {
        let mut distribution = super::Distribution::default();
        let capacity = distribution.bins.capacity();
        for _ in 0..20_000 {
            distribution.record(4.001);
        }
        for _ in 0..2_000 {
            distribution.record(31.999);
        }
        assert_eq!(distribution.count, 22_000);
        assert_eq!(distribution.p95(), Some(32.0));
        assert_eq!(distribution.bins.capacity(), capacity);
        assert_eq!(distribution.max, 31.999);
        distribution.record(f64::NAN);
        distribution.record(-1.0);
        assert_eq!(distribution.count, 22_000);
    }

    #[test]
    fn profile_accounts_for_overflow_and_capture_restarts() {
        let mut distribution = super::Distribution::default();
        assert_eq!(distribution.p95(), None);
        distribution.record(1000.0);
        assert_eq!(distribution.p95(), Some(1000.0));
        let mut profile = super::Profile {
            started: std::time::Instant::now(),
            duration: std::time::Duration::from_secs(1),
            intervals_ms: super::Distribution::default(),
            cpu_ms: super::Distribution::default(),
            work: std::array::from_fn(|_| super::Distribution::default()),
            input_dropped: 0,
            previous_input_dropped: 0,
            device: None,
        };
        profile.record_input_loss(4);
        profile.record_input_loss(4);
        profile.new_input(6);
        profile.record_input_loss(3);
        assert_eq!(profile.input_dropped, 9);
    }

    #[test]
    fn shared_cursor_fixture_agrees_across_raw_scope_xy_and_frequency_windows() {
        use crate::{
            cursor::Cursors,
            demo::{Demo, Waveform},
            signal::{History, Trigger},
            spectrum::{Analyzer, Settings},
            xy,
        };
        let mut history = History::new(96000);
        let mut spectrogram = crate::spectrogram::History::default();
        let mut demo = Demo::default();
        demo.frequency = 1500.0;
        demo.waveform = Waveform::Sine;
        demo.noise = 0.0;
        demo.phase_degrees = 90.0;
        demo.channel_2_gain = 1.0;
        let row = super::cursor_fixture(&mut spectrogram, &mut history, &mut demo, 48000);
        let mut analyzer = Analyzer::new(Settings::default(), 48000);
        assert!(analyzer.update(&history, 0));
        let scope = history.sweep(480, Trigger::default());
        let mut cursors = Cursors::default();
        cursors.set_time(0, scope.range.end - 240);
        cursors.set_time(1, scope.range.end - 120);
        let mut lines = Vec::new();
        let xy = xy::build_lines(&history, 48000, xy::Settings::default(), &mut lines);
        for time in cursors.times.into_iter().flatten() {
            let sample = cursors.sample(time, scope.range.clone()).unwrap();
            assert!(scope.range.contains(&sample));
            assert!(xy.range.contains(&sample));
            let frame = history.get(sample).unwrap();
            assert!(
                (frame[0].powi(2) + frame[1].powi(2) - (demo.amplitude as f64).powi(2)).abs()
                    < 1e-10
            );
            let (selected, db) = spectrogram.at_sample(sample).unwrap();
            let reading = analyzer.cursor(1500.0).unwrap();
            assert_eq!(selected.start, reading.window.start);
            assert_eq!(selected.end, reading.window.end);
            assert!((db[256] - reading.dbfs).abs() < 1e-5);
        }
        assert_eq!(analyzer.window().unwrap().end, row.end);
        assert_eq!(cursors.delta_seconds(48000, scope.range), Some(0.0025));
    }
}
