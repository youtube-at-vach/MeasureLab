use measurelab::spectrum::{
    Analyzer, FrequencyScale, LineBuilder, Precision, Result, Settings, View,
};
use std::{f64::consts::TAU, hint::black_box, time::Instant};

mod common;

fn measure(mut work: impl FnMut()) -> (f64, f64, f64) {
    for _ in 0..common::iterations(5) {
        work();
    }
    let iterations = common::iterations(200);
    let mut times = Vec::with_capacity(iterations);
    for _ in 0..iterations {
        let clock = Instant::now();
        work();
        times.push(clock.elapsed().as_secs_f64() * 1000.0);
    }
    let mean = times.iter().sum::<f64>() / times.len() as f64;
    times.sort_by(f64::total_cmp);
    let p95 = (times.len() * 95).div_ceil(100) - 1;
    (mean, times[p95], times[times.len() - 1])
}

fn main() {
    println!(
        "N,precision,planning_ms,analysis_mean_ms,analysis_p95_ms,analysis_max_ms,copy_p95_ms,log_plot_p95_ms,narrow_plot_p95_ms,segments"
    );
    for size in [1024, 8192, 32768, 65536, 131072, 262144, 524288] {
        let samples: Vec<_> = (0..size)
            .map(|i| 0.5 * (TAU * 123.0 * i as f64 / size as f64).sin())
            .collect();
        for precision in [Precision::F64, Precision::F32] {
            let settings = Settings {
                size,
                precision,
                ..Settings::default()
            };
            let clock = Instant::now();
            let mut analyzer = Analyzer::new(settings, 48000);
            let planning = clock.elapsed().as_secs_f64() * 1000.0;
            let (mean, p95, max) = measure(|| {
                black_box(analyzer.update_samples(&samples, size as u64));
            });
            let mut result = Result::empty(settings, 48000);
            let (_, copy, _) = measure(|| {
                analyzer.copy_result(&mut result);
                black_box(&result);
            });
            let mut lines = Vec::with_capacity(8192);
            let mut builder = LineBuilder::default();
            let view = View::full(48000, FrequencyScale::Log, -120.0);
            builder.build(&analyzer, view, 1920, true, &mut lines);
            let (_, plot, _) = measure(|| {
                builder.build(&analyzer, view, 1920, true, &mut lines);
                black_box(&lines);
            });
            let segments = lines.len();
            let mut narrow = View::full(48000, FrequencyScale::Linear, -120.0);
            let frequency = 123.0 * 48000.0 / size as f32;
            narrow.min_hz = (frequency - 1.0).max(0.0);
            narrow.max_hz = frequency + 1.0;
            let (_, zoom, _) = measure(|| {
                builder.build(&analyzer, narrow, 1920, true, &mut lines);
                black_box(&lines);
            });
            println!(
                "{size},{precision:?},{planning:.3},{mean:.3},{p95:.3},{max:.3},{copy:.3},{plot:.3},{zoom:.3},{segments}"
            );
        }
    }
}
