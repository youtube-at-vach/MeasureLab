//! Headless production pipeline QA. The ignored test uses wall-clock input and
//! real CPU competitors; no device, GUI, or QA-only signal path is involved.
use measurelab::{
    audio::{AudioFrame, Capture, Metrics},
    calibration,
    channel::Pair,
    comparison, lockin,
    measurement::{self, Config, ScopeSettings, Snapshot, SpectrumMode},
    spectrogram::history::Collector,
    spectrum::{self, Precision, Window},
    stft,
};
use rtrb::RingBuffer;
use std::{
    f64::consts::TAU,
    hint::black_box,
    sync::{
        Arc,
        atomic::{AtomicBool, Ordering},
    },
    thread,
    time::{Duration, Instant},
};

fn wait(mut ready: impl FnMut() -> bool) {
    let deadline = Instant::now() + Duration::from_secs(30);
    while !ready() {
        assert!(
            Instant::now() < deadline,
            "analysis pipeline did not finish"
        );
        thread::sleep(Duration::from_millis(1));
    }
}

fn config(rate: u32, channels: usize, generation: u64) -> Config {
    Config {
        comparison: comparison::Settings {
            enabled: true,
            size: 1024,
            averages: 2,
            ..Default::default()
        },
        lockin: lockin::Settings {
            enabled: true,
            frequency_hz: rate as f64 / 64.0,
            integration_samples: 4096,
            time_constant_seconds: 0.001,
            ..Default::default()
        },
        spectrum: spectrum::Settings {
            size: 8192,
            precision: Precision::F64,
            ..Default::default()
        },
        spectrum_channel: 0,
        spectrum_mode: SpectrumMode::Continuous,
        scope: ScopeSettings::default(),
        calibrations: calibration::Set::default(),
        xy_channels: Pair::default(),
        stft_generation: generation,
        stft: stft::Config {
            analysis: measurelab::stft::Analysis::Spectrogram,
            log_floor_db: measurelab::cepstrum::DEFAULT_LOG_FLOOR_DB,
            sample_rate: rate,
            channels,
            channel: channels - 1,
            size: 1024,
            hop: 128,
            window: Window::Hann,
            remove_dc: true,
            precision: Precision::F64,
        },
    }
}

struct Pipeline {
    core: measurement::Worker,
    stft: stft::Worker,
    collector: Collector,
    input: rtrb::Producer<AudioFrame>,
    metrics: Arc<Metrics>,
    config: Config,
    end: u64,
    wave: [f64; 64],
}

impl Pipeline {
    fn new(rate: u32, channels: usize) -> Self {
        let mut stft = stft::Worker::new();
        let collector = Collector::new(stft.take_results());
        let generation = stft.configure(config(rate, channels, 0).stft).unwrap();
        let config = config(rate, channels, generation);
        collector.configure(1, generation, config.stft);
        let core = measurement::Worker::new(stft.take_feeder());
        core.configure_spectrum_display(
            true,
            [
                Some(1),
                (channels > 2).then_some(2),
                (channels > 3).then_some(3),
            ],
        );
        let (input, consumer) = RingBuffer::new(262144);
        let metrics = Arc::new(Metrics::default());
        core.start_capture(
            1,
            Capture {
                consumer,
                sample_rate: rate,
                channels: channels as u16,
                format: "synthetic f64 callback frames".into(),
                metrics: metrics.clone(),
            },
            config.clone(),
        );
        Self {
            core,
            stft,
            collector,
            input,
            metrics,
            config,
            end: 0,
            wave: std::array::from_fn(|i| 0.125 * (TAU * i as f64 / 64.0).sin()),
        }
    }

    fn submit_until(&mut self, end: u64) {
        for sequence in self.end..end {
            let x = self.wave[sequence as usize % 64];
            let samples = std::array::from_fn(|ch| if ch % 2 == 0 { x } else { -0.5 * x });
            if self
                .input
                .push(AudioFrame {
                    sequence,
                    samples,
                    #[cfg(feature = "qa")]
                    available_at: Some(Instant::now()),
                })
                .is_err()
            {
                self.metrics.dropped.fetch_add(1, Ordering::Relaxed);
            }
        }
        self.end = end;
        self.metrics.callbacks.fetch_add(1, Ordering::Relaxed);
        self.metrics.input_end.store(end, Ordering::Release);
    }

    fn restart(&mut self, rate: u32, channels: usize) {
        let generation = self.stft.configure(config(rate, channels, 0).stft).unwrap();
        self.config = config(rate, channels, generation);
        self.collector.configure(2, generation, self.config.stft);
        let (input, consumer) = RingBuffer::new(262144);
        self.input = input;
        self.metrics = Arc::new(Metrics::default());
        self.end = 0;
        self.core.start_capture(
            2,
            Capture {
                consumer,
                sample_rate: rate,
                channels: channels as u16,
                format: "synthetic f64 callback frames".into(),
                metrics: self.metrics.clone(),
            },
            self.config.clone(),
        );
    }

    fn stop(&self) -> Snapshot {
        let mut pending = self.core.stop_async();
        let mut snapshot = None;
        wait(|| {
            snapshot = pending.try_take();
            snapshot.is_some()
        });
        snapshot.unwrap()
    }
}

fn numeric_result(s: &Snapshot) {
    assert!(!s.failed);
    assert_eq!(s.comparison.state, comparison::State::Valid);
    assert!((s.comparison.bins[16].gain.unwrap() - 0.5).abs() < 1e-9);
    assert!((s.comparison.bins[16].coherence.unwrap() - 1.0).abs() < 1e-9);
    assert_eq!(s.lockin.state, lockin::State::Valid);
    assert!((s.lockin.gain.unwrap() - 0.5).abs() < 1e-8);
    assert!((s.lockin.amplitude_peak.unwrap() - 0.0625).abs() < 1e-8);
    assert_eq!(s.spectrum.validity(), spectrum::Validity::Valid);
    assert!((s.spectrum.power()[128] - 0.125_f64.powi(2)).abs() < 1e-10);
}

#[test]
fn blocked_display_keeps_all_analysis_windows_and_exact_finite_end() {
    for channels in [2, 16] {
        let mut p = Pipeline::new(48000, channels);
        // Feed bounded bursts, never wait on a result/display publication.
        for end in (4096..=32768).step_by(4096) {
            p.submit_until(end);
            wait(|| p.core.metrics.input_frames.load(Ordering::Relaxed) == end);
        }
        let s = p.stop();
        numeric_result(&s);
        assert_eq!(s.history.range().end, 32768);
        assert_eq!(s.input_dropped, 0);
        assert_eq!(s.spectrum_info.input_missing, 0);
        assert_eq!(s.spectrum_info.updates, 13);
        assert_eq!(s.comparison.processed_windows, 32);
        assert_eq!(s.comparison.missing_samples, 0);
        assert_eq!(s.lockin.processed_windows, 8);
        assert_eq!(s.lockin.missing_samples, 0);
        for (_, result, info) in &s.spectrum_overlays {
            assert_eq!(info.updates, 13);
            assert_eq!(info.input_missing, 0);
            assert_eq!(result.validity(), spectrum::Validity::Valid);
        }
        wait(|| p.stft.metrics.processed_frames.load(Ordering::Acquire) == 32768);
        assert_eq!(p.stft.metrics.input_dropped.load(Ordering::Relaxed), 0);
        assert_eq!(p.stft.metrics.produced.load(Ordering::Relaxed), 249);
        wait(|| p.collector.metrics.collected.load(Ordering::Relaxed) == 249);
        assert_eq!(p.stft.metrics.result_dropped.load(Ordering::Relaxed), 0);
    }
}

struct Competition {
    stop: Arc<AtomicBool>,
    handles: Vec<thread::JoinHandle<()>>,
}
impl Competition {
    fn new(count: usize) -> Self {
        let stop = Arc::new(AtomicBool::new(false));
        let handles = (0..count)
            .map(|_| {
                let stop = stop.clone();
                thread::spawn(move || {
                    let mut x = 0.123_f64;
                    while !stop.load(Ordering::Relaxed) {
                        for _ in 0..16384 {
                            x = black_box(x).sin() + 0.5;
                        }
                        black_box(x);
                    }
                })
            })
            .collect();
        Self { stop, handles }
    }
}
impl Drop for Competition {
    fn drop(&mut self) {
        self.stop.store(true, Ordering::Relaxed);
        for handle in self.handles.drain(..) {
            handle.join().unwrap();
        }
    }
}

fn env<T: std::str::FromStr>(name: &str, default: T) -> T
where
    T::Err: std::fmt::Debug,
{
    std::env::var(name).map_or(default, |v| v.parse().expect(name))
}

#[test]
#[ignore = "wall-clock CPU contention QA; run explicitly in release mode"]
fn sustained_cpu_contention_reports_continuity_and_recovers() {
    let seconds: u64 = env("MEASURELAB_STRESS_SECONDS", 120);
    let rate: u32 = env("MEASURELAB_STRESS_RATE", 192000);
    let channels: usize = env("MEASURELAB_STRESS_CHANNELS", 2);
    let competitors: usize = env("MEASURELAB_STRESS_COMPETITORS", 3);
    assert!((1..=3600).contains(&seconds));
    assert!([48000, 192000, 768000].contains(&rate));
    assert!([2, 16].contains(&channels));
    assert!(competitors <= 64);
    let mut p = Pipeline::new(rate, channels);
    let competition = Competition::new(competitors);
    let clock = Instant::now();
    let mut max_lag = 0;
    let mut stalls = Vec::new();
    let mut checked = 0;
    let mut previous = 0;
    while clock.elapsed() < Duration::from_secs(seconds) {
        let elapsed = clock.elapsed();
        let target = ((elapsed.as_secs_f64() * rate as f64) as u64).min(seconds * rate as u64);
        p.submit_until(target);
        let processed = p.core.metrics.input_frames.load(Ordering::Relaxed);
        max_lag = max_lag.max(target.saturating_sub(processed));
        if elapsed.as_secs() > checked {
            if processed == previous {
                stalls.push(elapsed.as_secs());
            }
            previous = processed;
            checked = elapsed.as_secs();
        }
        thread::sleep(Duration::from_millis(2));
    }
    p.submit_until(seconds * rate as u64);
    let stop_clock = Instant::now();
    let s = p.stop();
    let stop_ms = stop_clock.elapsed().as_secs_f64() * 1000.0;
    let accepted = p.end - p.metrics.dropped.load(Ordering::Relaxed);
    let stft_accepted = accepted - p.stft.metrics.input_dropped.load(Ordering::Relaxed);
    wait(|| p.stft.metrics.processed_frames.load(Ordering::Acquire) == stft_accepted);
    wait(|| {
        p.collector.metrics.collected.load(Ordering::Relaxed)
            + p.collector.metrics.storage_dropped.load(Ordering::Relaxed)
            == p.stft.metrics.produced.load(Ordering::Relaxed)
    });
    let report = serde_json::json!({
        "seconds": seconds, "rate": rate, "channels": channels, "competitors": competitors,
        "frames": p.end, "input_dropped": s.input_dropped, "core_max_lag_frames": max_lag,
        "spectrum_missing": s.spectrum_info.input_missing,
        "spectrum_updates": s.spectrum_info.updates,
        "spectrum_missing_windows": s.spectrum_info.missing_windows,
        "lockin_missing": s.lockin.missing_samples, "lockin_windows": s.lockin.processed_windows,
        "comparison_missing": s.comparison.missing_samples, "comparison_windows": s.comparison.processed_windows,
        "stft_missing": p.stft.metrics.input_dropped.load(Ordering::Relaxed),
        "stft_queue_peak_blocks": p.stft.metrics.input_high_water.load(Ordering::Relaxed),
        "stft_result_dropped": p.stft.metrics.result_dropped.load(Ordering::Relaxed),
        "stft_rows": p.stft.metrics.produced.load(Ordering::Relaxed),
        "stft_storage_dropped": p.collector.metrics.storage_dropped.load(Ordering::Relaxed),
        "display_skipped": p.core.metrics.display_skipped.load(Ordering::Relaxed),
        "core_processing_seconds": p.core.metrics.processing_nanos.load(Ordering::Relaxed) as f64 / 1e9,
        "spectrum_processing_seconds": p.core.spectrum.metrics.processing_nanos.load(Ordering::Relaxed) as f64 / 1e9,
        "stft_processing_seconds": p.stft.metrics.processing_nanos.load(Ordering::Relaxed) as f64 / 1e9,
        "stop_ms": stop_ms, "one_second_stalls": stalls,
    });
    println!("ANALYSIS_RESILIENCE {report}");
    assert!(!s.failed);
    assert_eq!(s.history.range().end, p.end);
    assert_eq!(s.comparison.input_end, p.end);
    let continuous = env("MEASURELAB_STRESS_REQUIRE_CONTINUOUS", false);
    if continuous {
        numeric_result(&s);
        assert_eq!(s.spectrum_info.updates, 1 + (p.end - 8192) / 2048);
        assert_eq!(s.lockin.processed_windows, p.end / 4096);
        assert_eq!(s.comparison.processed_windows, p.end / 1024);
        assert_eq!(
            p.stft.metrics.produced.load(Ordering::Relaxed),
            1 + (p.end - 1024) / 128
        );
        for (_, _, info) in &s.spectrum_overlays {
            assert_eq!(info.input_missing, 0);
            assert_eq!(info.updates, s.spectrum_info.updates);
        }
    }
    assert!(
        stalls.is_empty(),
        "acquisition stopped making progress: {report}"
    );
    // Release competitors, restart a new generation, and independently check
    // every numeric result after overload. Prior gaps/averages must not leak.
    drop(competition);
    let before = p.core.metrics.input_frames.load(Ordering::Relaxed);
    p.restart(48000, channels);
    for end in (4096..=32768).step_by(4096) {
        p.submit_until(end);
        wait(|| p.core.metrics.input_frames.load(Ordering::Relaxed) == before + end);
    }
    let s = p.stop();
    numeric_result(&s);
    assert_eq!(s.generation, 2);
    assert_eq!(s.input_dropped, 0);
    assert_eq!(s.spectrum_info.input_missing, 0);
    assert_eq!(s.lockin.missing_samples, 0);
    assert_eq!(s.comparison.missing_samples, 0);
    if continuous {
        assert_eq!(report["input_dropped"], 0);
        assert_eq!(report["spectrum_missing"], 0);
        assert_eq!(report["lockin_missing"], 0);
        assert_eq!(report["comparison_missing"], 0);
        assert_eq!(report["stft_missing"], 0);
        assert_eq!(report["stft_result_dropped"], 0);
        assert_eq!(report["stft_storage_dropped"], 0);
    }
}
