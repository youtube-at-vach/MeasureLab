use measurelab::{
    spectrogram::{History, ROWS},
    spectrum::Window,
    stft::{Config, Gap, RowInfo},
};
use std::{hint::black_box, time::Instant};

fn main() {
    for size in [1024, 8192, 32768] {
        let config = Config {
            sample_rate: 48000,
            channels: 16,
            channel: 15,
            size,
            hop: size / 4,
            window: Window::Hann,
            remove_dc: true,
        };
        let mut history = History::default();
        history.reset(1, config);
        let db = vec![-80.0; size / 2 + 1];
        let mut placements = Vec::with_capacity(ROWS * 2);
        let iterations = 10000;
        let started = Instant::now();
        for i in 0..iterations {
            let end = (size + i * config.hop) as u64;
            black_box(history.push(
                RowInfo {
                    generation: 1,
                    config,
                    start: end - size as u64,
                    end,
                    gap: Gap::default(),
                },
                &db,
            ));
            history.placements(5.0, &mut placements);
            black_box(&placements);
        }
        println!(
            "{size:>5}-point spectrogram history + time intervals: {:.3} ms/row, {} retained rows, {:.1} MiB CPU storage",
            started.elapsed().as_secs_f64() * 1000.0 / iterations as f64,
            history.len(),
            history.storage_bytes() as f64 / 1048576.0
        );
    }
}
