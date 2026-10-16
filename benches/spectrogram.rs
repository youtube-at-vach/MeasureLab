use measurelab::{
    spectrogram::{
        ROWS,
        history::Collector,
        viewport::{MAX_COLUMNS, Parameters, Worker as ViewWorker},
    },
    spectrum::{FrequencyScale, Precision, View, Window},
    stft::{Config, Overlap, Worker},
};
use std::{
    f64::consts::TAU,
    hint::black_box,
    sync::atomic::Ordering,
    thread,
    time::{Duration, Instant},
};

mod common;

fn wait(mut ready: impl FnMut() -> bool) {
    let deadline = Instant::now() + Duration::from_secs(20);
    while !ready() {
        assert!(Instant::now() < deadline, "Spectrogram benchmark timed out");
        thread::sleep(Duration::from_micros(50));
    }
}

fn main() {
    for (size, overlap) in [1024, 8192, 32768]
        .into_iter()
        .flat_map(|size| Overlap::ALL.map(|overlap| (size, overlap)))
    {
        let config = Config {
            sample_rate: 48000,
            channels: 16,
            channel: 15,
            size,
            hop: overlap.hop(size),
            window: Window::Hann,
            remove_dc: true,
            precision: Precision::F64,
        };
        let mut stft = Worker::new();
        let collector = Collector::new(stft.take_results());
        let generation = stft.configure(config).unwrap();
        collector.configure(1, generation, config);
        // cargo test exercises each case once. Explicit cargo bench fills a
        // 60-second history and measures the production preparation worker.
        let rows = common::iterations((60 * config.sample_rate as usize).div_ceil(config.hop));
        let frames = size + (rows - 1) * config.hop;
        let wave: [f64; 256] = std::array::from_fn(|n| 0.5 * (TAU * n as f64 / 256.0).cos());
        for start in (0..frames).step_by(8192) {
            let end = (start + 8192).min(frames);
            let processed = stft.metrics.processed_frames.load(Ordering::Acquire);
            for n in start..end {
                let mut channels = [0.0; 16];
                channels[15] = wave[n % wave.len()];
                stft.submit(n as u64, &channels);
            }
            stft.flush();
            wait(|| {
                stft.metrics.processed_frames.load(Ordering::Acquire)
                    >= processed + (end - start) as u64
            });
        }
        wait(|| {
            collector
                .snapshot()
                .latest()
                .is_some_and(|f| f.info.end == frames as u64)
        });
        assert_eq!(stft.metrics.produced.load(Ordering::Relaxed), rows as u64);
        assert_eq!(stft.metrics.input_dropped.load(Ordering::Relaxed), 0);
        assert_eq!(stft.metrics.result_dropped.load(Ordering::Relaxed), 0);
        assert_eq!(collector.metrics.storage_dropped.load(Ordering::Relaxed), 0);
        collector.freeze();
        let snapshot = collector.snapshot();
        println!(
            "{size:>5}-point f64 STFT + collector, CH 16 / 48000 Hz: {rows} FFTs, overlap {}, {:.3} ms/FFT, {:.3} ms/collected row, {:.3} s retained, {:.3} MiB frames",
            overlap.name(),
            stft.metrics.processing_nanos.load(Ordering::Relaxed) as f64 / 1e6 / rows as f64,
            collector.metrics.processing_nanos.load(Ordering::Relaxed) as f64 / 1e6 / rows as f64,
            snapshot.retained_seconds(),
            collector.peak_frame_bytes() as f64 / 1048576.0,
        );
        let mut worker = ViewWorker::default();
        for auto in [false, true] {
            let mut times = Vec::new();
            for iteration in 0..common::iterations(30) {
                worker.submit(
                    snapshot.clone(),
                    Parameters {
                        anchor: Some(frames as u64 - iteration as u64),
                        seconds: 60.0,
                        view: View::full(48000, FrequencyScale::Linear, -120.0),
                        columns: MAX_COLUMNS,
                        rows: ROWS,
                        auto,
                        live: false,
                    },
                );
                let mut prepared = None;
                wait(|| {
                    prepared = worker.take();
                    prepared.is_some()
                });
                let prepared = prepared.unwrap();
                times.push(prepared.processing_ms);
                black_box(&prepared.history);
            }
            times.sort_by(f64::total_cmp);
            println!(
                "{size:>5}-point numerical history -> {MAX_COLUMNS}x{ROWS} raster, Auto {auto}, 60 s: mean {:.3} / p95 {:.3} / max {:.3} ms; {:.3} MiB peak raster reservation",
                times.iter().sum::<f64>() / times.len() as f64,
                times[(times.len() * 95 / 100).min(times.len() - 1)],
                times.last().unwrap(),
                worker.peak_cache_bytes() as f64 / 1048576.0,
            );
        }
    }
}
