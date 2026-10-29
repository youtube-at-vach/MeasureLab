//! Headless production pipeline QA. The ignored test uses wall-clock input and
//! real CPU competitors; no device, GUI, or QA-only signal path is involved.
use measurelab::{
    audio::{AudioFrame, Capture, Metrics},
    calibration, cepstrum,
    channel::Pair,
    comparison, lockin,
    measurement::{self, Config, ScopeSettings, Snapshot, SpectrumMode},
    spectrogram::history::{self, Collector},
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

fn config(stft: stft::Config, generation: u64) -> Config {
    Config {
        comparison: comparison::Settings {
            enabled: true,
            size: 1024,
            averages: 2,
            ..Default::default()
        },
        lockin: lockin::Settings {
            enabled: true,
            frequency_hz: stft.sample_rate as f64 / 64.0,
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
        stft,
    }
}

fn stft_config(rate: u32, channels: usize, analysis: stft::Analysis) -> stft::Config {
    stft::Config {
        analysis,
        log_floor_db: cepstrum::DEFAULT_LOG_FLOOR_DB,
        sample_rate: rate,
        channels,
        channel: channels - 1,
        size: 1024,
        hop: 128,
        window: Window::Hann,
        remove_dc: true,
        precision: Precision::F64,
    }
}

struct Pipeline {
    core: measurement::Worker,
    stft: stft::Worker,
    collector: Collector,
    input: rtrb::Producer<AudioFrame>,
    metrics: Arc<Metrics>,
    config: Config,
    archive_collected_before: u64,
    end: u64,
    wave: [f64; 64],
}

impl Pipeline {
    fn new(settings: stft::Config) -> Self {
        let stft::Config {
            sample_rate: rate,
            channels,
            ..
        } = settings;
        let mut stft = stft::Worker::new();
        let collector = Collector::new(stft.take_results());
        let generation = stft.configure(settings).unwrap();
        let config = config(settings, generation);
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
            archive_collected_before: 0,
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

    fn restart(&mut self, rate: u32) {
        let settings = stft::Config {
            sample_rate: rate,
            ..self.config.stft
        };
        let channels = settings.channels;
        let generation = self.stft.configure(settings).unwrap();
        self.config = config(settings, generation);
        self.archive_collected_before = self.collector.metrics.collected.load(Ordering::Relaxed);
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

    fn drain_analysis(&self, processed_before: u64) {
        let accepted = self.end - self.metrics.dropped.load(Ordering::Relaxed);
        let stft_accepted = accepted - self.stft.metrics.input_dropped.load(Ordering::Relaxed);
        wait(|| {
            self.stft.metrics.processed_frames.load(Ordering::Acquire)
                == processed_before + stft_accepted
        });
        wait(|| {
            self.collector.metrics.collected.load(Ordering::Relaxed)
                + self
                    .collector
                    .metrics
                    .storage_dropped
                    .load(Ordering::Relaxed)
                == self.stft.metrics.produced.load(Ordering::Relaxed)
        });
    }

    fn retained_result(&self, input_generation: u64) -> Arc<history::Snapshot> {
        let produced = self.stft.metrics.produced.load(Ordering::Relaxed);
        assert!(produced > 0);
        // Collection counters precede publication. Await the final snapshot too.
        wait(|| {
            let s = self.collector.snapshot();
            s.frames().len() as u64 + s.retired
                == self.collector.metrics.collected.load(Ordering::Relaxed)
                    - self.archive_collected_before
        });
        let snapshot = self.collector.snapshot();
        assert_eq!(snapshot.input_generation, input_generation);
        assert_eq!(snapshot.generation, self.config.stft_generation);
        assert_eq!(snapshot.config, Some(self.config.stft));
        assert!(snapshot.frames().len() > 0);
        assert!(snapshot.storage_bytes() <= history::HISTORY_BYTES);
        for frame in snapshot.frames() {
            assert_eq!(frame.input_generation, input_generation);
            assert_eq!(frame.info.generation, self.config.stft_generation);
            assert_eq!(frame.info.config, self.config.stft);
            assert_eq!(
                frame.info.end - frame.info.start,
                self.config.stft.size as u64
            );
            assert!(frame.info.end <= self.end);
        }
        // Known sine × periodic Hann has exactly three nonzero positive bins.
        // Its log spectrum's inverse has a closed form: no production FFT,
        // spectrum normalization, cepstrum or display helper is used here.
        let frame = snapshot.latest().unwrap();
        assert!(frame.valid());
        let n = frame.info.config.size;
        let carrier = n / 64;
        let amplitude: f64 = if frame.info.config.channel.is_multiple_of(2) {
            0.125
        } else {
            0.0625
        };
        match frame.values() {
            stft::Values::SpectrumPower(power) => {
                assert_eq!(frame.info.cepstrum, None);
                for (k, &actual) in power.iter().enumerate() {
                    let expected = if k == carrier {
                        amplitude.powi(2)
                    } else if k.abs_diff(carrier) == 1 {
                        amplitude.powi(2) / 4.0
                    } else {
                        0.0
                    };
                    assert!(
                        (actual - expected).abs() < 1e-12,
                        "bin {k}: {actual} != {expected}"
                    );
                }
            }
            stft::Values::RealCepstrum(coefficients) => {
                let info = frame.info.cepstrum.unwrap();
                assert_eq!(info.status, cepstrum::Status::Valid);
                assert_eq!(info.algorithm, cepstrum::ALGORITHM);
                assert_eq!(info.floored_bins, n / 2 + 1 - 3);
                let depth =
                    -(frame.info.config.log_floor_db as f64) * std::f64::consts::LN_10 / 20.0;
                let floor = (amplitude / 2.0).ln() - depth;
                assert_eq!(coefficients.len(), n / 2 + 1);
                for (q, &actual) in coefficients.iter().enumerate() {
                    let angle = TAU * q as f64 / n as f64;
                    let expected = if q == 0 { floor } else { 0.0 }
                        + 2.0 / n as f64
                            * (depth * (angle * carrier as f64).cos()
                                + (depth - std::f64::consts::LN_2)
                                    * ((angle * (carrier - 1) as f64).cos()
                                        + (angle * (carrier + 1) as f64).cos()));
                    assert!(
                        (actual - expected).abs() < 1e-10,
                        "q {q}: {actual} != {expected}"
                    );
                }
            }
        }
        snapshot
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
    for (rate, channels) in [(48000, 2), (768000, 16)] {
        for analysis in [stft::Analysis::Spectrogram, stft::Analysis::Cepstrogram] {
            for size in [1024, 32768] {
                for overlap in stft::Overlap::ALL {
                    let settings = stft::Config {
                        size,
                        hop: overlap.hop(size),
                        ..stft_config(rate, channels, analysis)
                    };
                    let expected_rows = 1 + (32768 - size) as u64 / settings.hop as u64;
                    let mut p = Pipeline::new(settings);
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
                    p.drain_analysis(0);
                    assert_eq!(p.stft.metrics.input_dropped.load(Ordering::Relaxed), 0);
                    assert_eq!(
                        p.stft.metrics.produced.load(Ordering::Relaxed),
                        expected_rows
                    );
                    assert_eq!(
                        p.collector.metrics.collected.load(Ordering::Relaxed),
                        expected_rows
                    );
                    assert_eq!(p.stft.metrics.result_dropped.load(Ordering::Relaxed), 0);
                    assert_eq!(
                        p.collector.metrics.storage_dropped.load(Ordering::Relaxed),
                        0
                    );
                    let retained = p.retained_result(1);
                    assert_eq!(retained.latest().unwrap().info.end, 32768);
                    recover(&mut p, &retained);
                    if analysis == stft::Analysis::Spectrogram {
                        assert_eq!(p.stft.metrics.cepstrum_nanos.load(Ordering::Relaxed), 0);
                    } else {
                        assert!(p.stft.metrics.cepstrum_nanos.load(Ordering::Relaxed) > 0);
                    }
                }
            }
        }
    }
}

fn recover(p: &mut Pipeline, held: &history::Snapshot) -> serde_json::Value {
    let held_info = held.latest().unwrap().info;
    let held_value = match held.latest().unwrap().values() {
        stft::Values::SpectrumPower(v) | stft::Values::RealCepstrum(v) => v.to_vec(),
    };
    let before = p.core.metrics.input_frames.load(Ordering::Relaxed);
    let stft_before = p.stft.metrics.processed_frames.load(Ordering::Acquire);
    let rows_before = p.stft.metrics.produced.load(Ordering::Relaxed);
    let stft_missing_before = p.stft.metrics.input_dropped.load(Ordering::Relaxed);
    let result_missing_before = p.stft.metrics.result_dropped.load(Ordering::Relaxed);
    let storage_missing_before = p.collector.metrics.storage_dropped.load(Ordering::Relaxed);
    p.restart(48000);
    for end in (4096..=32768).step_by(4096) {
        p.submit_until(end);
        wait(|| p.core.metrics.input_frames.load(Ordering::Relaxed) == before + end);
    }
    let recovered = p.stop();
    numeric_result(&recovered);
    assert_eq!(recovered.generation, 2);
    assert_eq!(recovered.history.range().end, 32768);
    assert_eq!(recovered.input_dropped, 0);
    assert_eq!(recovered.spectrum_info.input_missing, 0);
    assert_eq!(recovered.lockin.missing_samples, 0);
    assert_eq!(recovered.comparison.missing_samples, 0);
    // STFT counters are lifetime totals; prior losses must not be subtracted
    // from the new generation's accepted input or mistaken for new losses.
    assert_eq!(
        p.stft.metrics.input_dropped.load(Ordering::Relaxed),
        stft_missing_before
    );
    wait(|| p.stft.metrics.processed_frames.load(Ordering::Acquire) == stft_before + 32768);
    wait(|| {
        p.collector.metrics.collected.load(Ordering::Relaxed) + storage_missing_before
            == p.stft.metrics.produced.load(Ordering::Relaxed)
    });
    assert_eq!(
        p.stft.metrics.result_dropped.load(Ordering::Relaxed),
        result_missing_before
    );
    assert_eq!(
        p.collector.metrics.storage_dropped.load(Ordering::Relaxed),
        storage_missing_before
    );
    assert_eq!(
        p.stft.metrics.produced.load(Ordering::Relaxed) - rows_before,
        1 + (32768 - p.config.stft.size) as u64 / p.config.stft.hop as u64
    );
    let recovered_history = p.retained_result(2);
    assert_eq!(recovered_history.latest().unwrap().info.end, 32768);
    assert_eq!(held.latest().unwrap().info, held_info);
    assert!(p.collector.peak_frame_bytes() <= history::FRAME_BYTES);
    match held.latest().unwrap().values() {
        stft::Values::SpectrumPower(v) | stft::Values::RealCepstrum(v) => assert_eq!(v, held_value),
    }
    serde_json::json!({
        "analysis": p.config.stft.analysis, "input_generation": recovered.generation,
        "stft_generation": recovered_history.generation,
        "frames": 32768, "stft_rows": p.stft.metrics.produced.load(Ordering::Relaxed) - rows_before,
        "numeric_ok": true, "held_immutable": true,
    })
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
    let analysis = match env("MEASURELAB_STRESS_ANALYSIS", String::from("spectrogram")).as_str() {
        "spectrogram" => stft::Analysis::Spectrogram,
        "cepstrogram" => stft::Analysis::Cepstrogram,
        other => panic!("unknown MEASURELAB_STRESS_ANALYSIS: {other}"),
    };
    let size: usize = env("MEASURELAB_STRESS_STFT_SIZE", 1024);
    let overlap = match env("MEASURELAB_STRESS_OVERLAP", String::from("87.5")).as_str() {
        "50" => stft::Overlap::Half,
        "75" => stft::Overlap::ThreeQuarters,
        "87.5" => stft::Overlap::SevenEighths,
        other => panic!("unknown MEASURELAB_STRESS_OVERLAP: {other}"),
    };
    assert!((1..=3600).contains(&seconds));
    assert!([48000, 192000, 768000].contains(&rate));
    assert!([2, 16].contains(&channels));
    assert!(competitors <= 64);
    let settings = stft::Config {
        size,
        hop: overlap.hop(size),
        ..stft_config(rate, channels, analysis)
    };
    settings.validate().unwrap();
    let mut p = Pipeline::new(settings);
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
    p.drain_analysis(0);
    let held = p.retained_result(1);
    let held_info = held.latest().unwrap().info;
    let report = serde_json::json!({
        "seconds": seconds, "rate": rate, "channels": channels, "competitors": competitors,
        "analysis": analysis, "stft_config": {
            "channel": settings.channel, "size": settings.size, "hop": settings.hop,
            "window": "periodic_hann", "remove_dc": settings.remove_dc, "precision": "f64",
            "log_floor_db": settings.log_floor_db,
            "algorithm": held_info.cepstrum.map(|info| info.algorithm),
        },
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
        "cepstrum_processing_seconds": p.stft.metrics.cepstrum_nanos.load(Ordering::Relaxed) as f64 / 1e9,
        "collector_processing_seconds": p.collector.metrics.processing_nanos.load(Ordering::Relaxed) as f64 / 1e9,
        "history_bytes": held.storage_bytes(), "peak_frame_bytes": p.collector.peak_frame_bytes(),
        "last_stft_start": held_info.start, "last_stft_end": held_info.end,
        "stop_ms": stop_ms, "one_second_stalls": stalls,
    });
    println!("ANALYSIS_RESILIENCE {report}");
    assert!(!s.failed);
    assert_eq!(s.history.range().end, p.end);
    assert_eq!(s.comparison.input_end, p.end);
    if analysis == stft::Analysis::Spectrogram {
        assert_eq!(report["cepstrum_processing_seconds"], 0.0);
    } else {
        assert!(report["cepstrum_processing_seconds"].as_f64().unwrap() > 0.0);
    }
    assert!(
        stalls.is_empty(),
        "acquisition stopped making progress: {report}"
    );
    // Release competitors, restart a new generation, and independently check
    // every numeric result after overload. Prior gaps/averages must not leak.
    drop(competition);
    println!("ANALYSIS_RECOVERY {}", recover(&mut p, &held));
    let continuous = env("MEASURELAB_STRESS_REQUIRE_CONTINUOUS", false);
    if continuous {
        numeric_result(&s);
        let end = report["frames"].as_u64().unwrap();
        assert_eq!(s.spectrum_info.updates, 1 + (end - 8192) / 2048);
        assert_eq!(s.lockin.processed_windows, end / 4096);
        assert_eq!(s.comparison.processed_windows, end / 1024);
        assert_eq!(
            report["stft_rows"],
            1 + (end - size as u64) / settings.hop as u64
        );
        assert_eq!(
            held_info.end,
            size as u64 + (end - size as u64) / settings.hop as u64 * settings.hop as u64
        );
        for (_, _, info) in &s.spectrum_overlays {
            assert_eq!(info.input_missing, 0);
            assert_eq!(info.updates, s.spectrum_info.updates);
        }
        assert_eq!(report["input_dropped"], 0);
        assert_eq!(report["spectrum_missing"], 0);
        assert_eq!(report["lockin_missing"], 0);
        assert_eq!(report["comparison_missing"], 0);
        assert_eq!(report["stft_missing"], 0);
        assert_eq!(report["stft_result_dropped"], 0);
        assert_eq!(report["stft_storage_dropped"], 0);
    }
}
