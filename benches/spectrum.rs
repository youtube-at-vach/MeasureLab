use ras::{
    demo::Demo,
    signal::History,
    spectrum::{Analyzer, FrequencyScale, Settings, View, build_lines},
};
use std::{hint::black_box, time::Instant};

fn main() {
    for size in [1024, 8192, 32768] {
        let mut history = History::new(size);
        Demo::default().append(&mut history, size, 48000);
        let mut analyzer = Analyzer::new(
            Settings {
                size,
                ..Settings::default()
            },
            48000,
        );
        let mut lines = Vec::with_capacity(8192);
        let view = View::full(48000, FrequencyScale::Log, -120.0);
        let iterations = 200;
        let started = Instant::now();
        for _ in 0..iterations {
            analyzer.reset();
            black_box(analyzer.update(&history, 0));
            build_lines(&analyzer, view, 1920, true, &mut lines);
            black_box(&lines);
        }
        println!(
            "{size:>5}-point FFT + log plot / hold, 1920 px: {:.3} ms/update, {} segments",
            started.elapsed().as_secs_f64() * 1000.0 / iterations as f64,
            lines.len()
        );
    }
}
