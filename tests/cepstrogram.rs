//! Production worker/collector/viewport regression with finite deterministic input.
use measurelab::{
    cepstrum::{self, Status},
    spectrogram::{
        self,
        history::Collector,
        viewport::{Parameters, Worker as ViewWorker},
    },
    spectrum::{FrequencyScale, Precision, View, Window},
    stft::{Analysis, Config, Overlap, Worker},
};
use std::{
    sync::atomic::Ordering,
    thread,
    time::{Duration, Instant},
};
fn wait(mut ready: impl FnMut() -> bool) {
    let end = Instant::now() + Duration::from_secs(20);
    while !ready() {
        assert!(Instant::now() < end, "cepstrogram timeout");
        thread::sleep(Duration::from_millis(1));
    }
}
fn config(size: usize, overlap: Overlap) -> Config {
    Config {
        analysis: Analysis::Cepstrogram,
        log_floor_db: -160,
        sample_rate: 48000,
        channels: 16,
        channel: 15,
        size,
        hop: overlap.hop(size),
        window: Window::Rectangular,
        remove_dc: false,
        precision: Precision::F64,
    }
}
fn feed(worker: &mut Worker, start: u64, count: usize, size: usize, delay: usize, invalid: bool) {
    let before = worker.metrics.processed_frames.load(Ordering::Acquire);
    for i in 0..count {
        let mut channels = [0.0; 16];
        let q = (start as usize + i) % size;
        channels[15] = if invalid {
            f64::NAN
        } else if q == 0 {
            1.0
        } else if q == delay {
            0.4
        } else {
            0.0
        };
        worker.submit(start + i as u64, &channels);
    }
    worker.flush();
    wait(|| worker.metrics.processed_frames.load(Ordering::Acquire) >= before + count as u64);
}
fn parameters(c: Config) -> Parameters {
    Parameters {
        quefrency: Some(spectrogram::QuefrencyRange::default()),
        manual_range: spectrogram::ColorRange::new(-80.0, 0.0).unwrap(),
        anchor: None,
        seconds: 5.0,
        view: View::full(c.sample_rate, FrequencyScale::Linear, -120.0),
        columns: 64,
        rows: 16,
        auto: true,
        live: false,
    }
}
#[test]
fn all_production_sizes_windows_overlaps_keep_signed_echo_and_generation_identity() {
    let mut worker = Worker::new();
    let collector = Collector::new(worker.take_results());
    let mut view = ViewWorker::default();
    for size in measurelab::spectrum::STFT_SIZES {
        for overlap in Overlap::ALL {
            for window in [Window::Rectangular, Window::Hann, Window::BlackmanHarris] {
                let c = Config {
                    window,
                    ..config(size, overlap)
                };
                let generation = worker.configure(c).unwrap();
                collector.configure(81, generation, c);
                // Full windows only, delivered in deliberately irregular blocks.
                let before = worker.metrics.processed_frames.load(Ordering::Acquire);
                let origin = 1_u64 << 54;
                for start in (0..size).step_by(137) {
                    for n in start..(start + 137).min(size) {
                        let mut channels = [0.0; 16];
                        let middle = size / 2;
                        channels[15] = if n == middle {
                            1.0
                        } else if n == middle + 13 {
                            0.4
                        } else {
                            0.0
                        };
                        worker.submit(origin + n as u64, &channels);
                    }
                    worker.flush();
                }
                wait(|| {
                    worker.metrics.processed_frames.load(Ordering::Acquire) >= before + size as u64
                });
                wait(|| collector.snapshot().latest().is_some());
                let held = collector.snapshot();
                let frame = held.latest().unwrap();
                assert_eq!(frame.info.start, origin);
                assert_eq!(frame.info.end, origin + size as u64);
                assert_eq!(frame.info.config, c);
                assert_eq!(frame.info.cepstrum.unwrap().status, Status::Valid);
                assert_eq!(frame.info.cepstrum.unwrap().algorithm, cepstrum::ALGORITHM);
                assert!(frame.coefficient(13).unwrap() > 0.0);
                assert!(frame.coefficient(26).unwrap() < 0.0);
                assert!(frame.amplitude(13).is_none());
                assert!(frame.level_db(13).is_none());
                assert!(
                    measurelab::spectrum::Result::from_stft(frame.info, frame.values()).is_none()
                );
                // Independent two-impulse analytic result accounts for the selected window's gain ratio.
                let weight = |i: usize| {
                    let x = std::f64::consts::TAU * i as f64 / size as f64;
                    match window {
                        Window::Rectangular => 1.0,
                        Window::Hann => 0.5 - 0.5 * x.cos(),
                        Window::BlackmanHarris => {
                            0.35875 - 0.48829 * x.cos() + 0.14128 * (2.0 * x).cos()
                                - 0.01168 * (3.0 * x).cos()
                        }
                    }
                };
                let ratio = 0.4 * weight(size / 2 + 13) / weight(size / 2);
                assert!((frame.coefficient(13).unwrap() - ratio / 2.0).abs() < 1e-12);
                assert!((frame.coefficient(26).unwrap() + ratio * ratio / 4.0).abs() < 1e-12);
                view.submit(held.clone(), parameters(c));
                let mut prepared = None;
                wait(|| {
                    prepared = view.take();
                    prepared.is_some()
                });
                assert_eq!(prepared.unwrap().snapshot.generation, generation);
                assert_eq!(frame.info.start, origin);
            }
        }
    }
    assert_eq!(worker.metrics.input_dropped.load(Ordering::Relaxed), 0);
    assert_eq!(worker.metrics.result_dropped.load(Ordering::Relaxed), 0);
    assert_eq!(collector.metrics.storage_dropped.load(Ordering::Relaxed), 0);
}
#[test]
fn invalid_recovery_gaps_hold_mode_exchange_and_frozen_stop_do_not_mix_frames() {
    let mut worker = Worker::new();
    let collector = Collector::new(worker.take_results());
    let c = config(1024, Overlap::Half);
    let generation = worker.configure(c).unwrap();
    collector.configure(9, generation, c);
    feed(&mut worker, 0, 1024, 1024, 17, false);
    wait(|| collector.snapshot().latest().is_some());
    let held = collector.snapshot();
    let old = held.latest().unwrap().clone();
    let original = old.coefficient(17).unwrap();
    feed(&mut worker, 1024, 1024, 1024, 17, true);
    wait(|| {
        collector
            .snapshot()
            .latest()
            .is_some_and(|f| f.info.end == 2048)
    });
    assert_eq!(
        collector
            .snapshot()
            .latest()
            .unwrap()
            .info
            .cepstrum
            .unwrap()
            .status,
        Status::NonFinite
    );
    feed(&mut worker, 4096, 1024, 1024, 31, false);
    wait(|| {
        collector
            .snapshot()
            .latest()
            .is_some_and(|f| f.info.end == 5120)
    });
    let current = collector.snapshot();
    let last = current.latest().unwrap();
    assert!(last.valid());
    assert!((last.coefficient(31).unwrap() - 0.2).abs() < 1e-12);
    assert_eq!(last.info.gap.input_frames, 2048);
    assert!(current.at_sample(3000).is_none());
    assert_eq!(old.coefficient(17).unwrap(), original);
    collector.freeze();
    worker.pause();
    let c = Config {
        analysis: Analysis::Spectrogram,
        precision: Precision::F32,
        ..c
    };
    let g = worker.configure(c).unwrap();
    collector.configure(10, g, c);
    feed(&mut worker, 0, 1024, 1024, 17, false);
    wait(|| collector.snapshot().latest().is_some());
    assert_eq!(collector.snapshot().latest().unwrap().info.cepstrum, None);
    assert_eq!(held.config.unwrap().analysis, Analysis::Cepstrogram);
    assert_eq!(old.coefficient(17).unwrap(), original);
    collector.freeze();
    worker.pause();
    let stopped = collector.snapshot();
    worker.submit(1024, &[0.0; 16]);
    worker.flush();
    assert_eq!(
        collector.snapshot().latest().unwrap().info,
        stopped.latest().unwrap().info
    );
}
