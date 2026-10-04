use measurelab::{
    demo::Demo,
    signal::History,
    spectrum::{Analyzer, FrequencyScale, LineBuilder, Precision, Settings, View},
};
use std::{hint::black_box, time::Instant};

fn main() {
    for size in [1024, 8192, 32768] {
        let mut history = History::new(size);
        Demo::default().append(&mut history, size, 48000);
        for precision in [Precision::F64, Precision::F32] {
            let mut analyzer = Analyzer::new(
                Settings {
                    size,
                    precision,
                    ..Settings::default()
                },
                48000,
            );
            let mut lines = Vec::with_capacity(8192);
            let mut builder = LineBuilder::default();
            let view = View::full(48000, FrequencyScale::Log, -120.0);
            let iterations = 1000;
            // Warm plans and data before timing. Configuration allocation is excluded.
            black_box(analyzer.update(&history, 0));
            builder.build(&analyzer, view, 1920, true, &mut lines);
            let started = Instant::now();
            for _ in 0..iterations {
                analyzer.reset();
                black_box(analyzer.update(&history, 0));
            }
            let fft_ms = started.elapsed().as_secs_f64() * 1000.0 / iterations as f64;
            let started = Instant::now();
            for _ in 0..iterations {
                builder.build(&analyzer, view, 1920, true, &mut lines);
                black_box(&lines);
            }
            let plot_ms = started.elapsed().as_secs_f64() * 1000.0 / iterations as f64;
            println!(
                "{size:>5}-point {precision:?} real FFT {fft_ms:.3} ms + cached log plot / hold {plot_ms:.3} ms = {:.3} ms/update, {} segments",
                fft_ms + plot_ms,
                lines.len()
            );
        }
    }
}
