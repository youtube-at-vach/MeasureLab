use measurelab::signal::{History, Trigger, build_lines};
use std::{hint::black_box, time::Instant};

fn main() {
    for count in [48_000, 192_000, 1_000_000] {
        let mut history = History::new(count);
        for i in 0..count {
            let value = (i as f64 * 0.01).sin();
            history.push([value, value * 0.5]);
        }
        let mut lines = Vec::with_capacity(8192);
        let start = Instant::now();
        let iterations = 200;
        for _ in 0..iterations {
            let sweep = history.sweep(count, Trigger::default());
            black_box(build_lines(
                &history,
                sweep.range,
                1920,
                0.25,
                [true; 2],
                &mut lines,
            ));
            black_box(&lines);
        }
        println!(
            "{count:>7} samples, 1920 px, 2 channels: {:.3} ms/sweep, {} segments",
            start.elapsed().as_secs_f64() * 1000.0 / iterations as f64,
            lines.len()
        );
    }
}
