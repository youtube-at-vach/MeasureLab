use measurelab::{
    signal::History,
    xy::{self, Settings},
};
use std::{hint::black_box, time::Instant};

fn main() {
    for sample_rate in [48_000, 192_000, 1_000_000] {
        let count = sample_rate as usize / 5;
        let mut history = History::new(count);
        for i in 0..count {
            let phase = std::f64::consts::TAU * 1000.0 * i as f64 / sample_rate as f64;
            history.push([phase.sin(), phase.cos()]);
        }
        let mut lines = Vec::with_capacity(xy::MAX_POINTS);
        let start = Instant::now();
        let iterations = 1000;
        for _ in 0..iterations {
            black_box(xy::build_lines(
                &history,
                sample_rate,
                Settings {
                    milliseconds: 200.0,
                    ..Settings::default()
                },
                &mut lines,
            ));
            black_box(&lines);
        }
        println!(
            "{sample_rate} Hz, 200 ms XY: {:.3} ms/prep, {} segments",
            start.elapsed().as_secs_f64() * 1000.0 / iterations as f64,
            lines.len()
        );
    }
}
