//! Independent DFT of retained real input, including the physical signal path.
use crate::{measurement, signal::History, spectrogram::history, spectrum, stft};
use std::f64::consts::TAU;

/// Executed after the finite input/collector barrier, outside measured UI work.
pub fn validate(input: &measurement::Snapshot, retained: &history::Snapshot, origin: u64) {
    assert_eq!(retained.input_generation, input.generation);
    assert_eq!(retained.generation, input.stft_generation);
    assert_eq!(retained.config, Some(input.stft_config));
    let config = input.stft_config;
    let mut previous = None;
    for frame in retained.frames() {
        assert_eq!(frame.input_generation, input.generation);
        assert_eq!(frame.info.generation, input.stft_generation);
        assert_eq!(frame.info.config, config);
        assert_eq!(frame.info.end - frame.info.start, config.size as u64);
        assert_eq!((frame.info.start - origin) % config.hop as u64, 0);
        assert_eq!(frame.info.gap.input_frames, 0);
        assert_eq!(frame.info.gap.result_rows, 0);
        if let Some(end) = previous {
            assert_eq!(frame.info.end - end, config.hop as u64);
        }
        previous = Some(frame.info.end);
    }
    let raw = input.history.contiguous_range();
    let frames: Vec<_> = retained
        .frames()
        .filter(|frame| frame.info.start >= raw.start && frame.info.end <= raw.end)
        .collect();
    assert!(
        frames.len() >= 3,
        "insufficient retained windows for independent DFT"
    );
    let mut max_error = 0.0_f64;
    for index in [0, frames.len() / 2, frames.len() - 1] {
        let frame = frames[index];
        max_error = max_error.max(check_frame(&input.history, frame.info, frame.power()));
    }
    println!(
        "Spectrogram numerical QA OK: {} Hz, CH {}, N {}, hop {}, {} retained windows; independent raw-input DFT at 3 times, max amplitude error {max_error:.3e} FS; original f64 Spectrum reads",
        config.sample_rate,
        config.channel + 1,
        config.size,
        config.hop,
        retained.frames().len(),
    );
}

fn check_frame(raw: &History, info: stft::RowInfo, power: &[f64]) -> f64 {
    let config = info.config;
    let signal: Vec<_> = (info.start..info.end)
        .map(|n| raw.get(n).expect("raw FFT window missing")[config.channel])
        .collect();
    let mean = if config.remove_dc {
        signal.iter().sum::<f64>() / config.size as f64
    } else {
        0.0
    };
    // Periodic window equations are independent of Analyzer/Window::weight.
    let weighted: Vec<_> = signal
        .iter()
        .enumerate()
        .map(|(n, &x)| {
            let angle = TAU * n as f64 / config.size as f64;
            let weight = match config.window {
                spectrum::Window::Rectangular => 1.0,
                spectrum::Window::Hann => (1.0 - angle.cos()) / 2.0,
                spectrum::Window::BlackmanHarris => {
                    0.35875 - 0.48829 * angle.cos() + 0.14128 * (2.0 * angle).cos()
                        - 0.01168 * (3.0 * angle).cos()
                }
            };
            ((x - mean) * weight, weight)
        })
        .collect();
    let weight_sum = weighted.iter().map(|x| x.1).sum::<f64>();
    let peak = power
        .iter()
        .enumerate()
        .max_by(|a, b| a.1.total_cmp(b.1))
        .unwrap()
        .0;
    let mut bins = vec![
        0,
        1,
        config.size / 2,
        peak.saturating_sub(1),
        peak,
        (peak + 1).min(config.size / 2),
    ];
    bins.sort_unstable();
    bins.dedup();
    let result = spectrum::Result::from_stft(info, power).expect("retained Spectrum adapter");
    let mut max_error = 0.0_f64;
    for bin in bins {
        let (mut re, mut im) = (0.0, 0.0);
        for (n, &(x, _)) in weighted.iter().enumerate() {
            let (sin, cos) = (TAU * bin as f64 * n as f64 / config.size as f64).sin_cos();
            re += x * cos;
            im -= x * sin;
        }
        let multiplier = if bin == 0 || bin == config.size / 2 {
            1.0
        } else {
            2.0
        };
        let expected = re.hypot(im) * multiplier / weight_sum;
        let actual = power[bin].sqrt();
        let tolerance = match config.precision {
            spectrum::Precision::F64 => 2e-11 + expected * 1e-8,
            spectrum::Precision::F32 => 1e-8 + expected * 1e-6,
        };
        let error = (actual - expected).abs();
        assert!(
            error <= tolerance,
            "retained STFT bin {bin}: {actual} vs independent DFT {expected}, tolerance {tolerance}"
        );
        let hz = bin as f64 * config.sample_rate as f64 / config.size as f64;
        assert_eq!(result.cursor(hz).unwrap().value.to_bits(), actual.to_bits());
        max_error = max_error.max(error);
    }
    max_error
}

#[cfg(test)]
mod tests {
    use super::*;

    fn fixture() -> (History, stft::RowInfo, Vec<f64>) {
        let mut raw = History::with_channels(1024, 2);
        for n in 0..1024 {
            raw.push([0.0, 0.5 * (TAU * 32.0 * n as f64 / 1024.0).sin() + 0.2]);
        }
        let info = stft::RowInfo {
            generation: 1,
            config: stft::Config {
                sample_rate: 48000,
                channels: 2,
                channel: 1,
                size: 1024,
                hop: 128,
                window: spectrum::Window::Rectangular,
                remove_dc: true,
                precision: spectrum::Precision::F64,
            },
            start: 0,
            end: 1024,
            gap: stft::Gap::default(),
        };
        let mut power = vec![0.0; 513];
        power[32] = 0.25;
        (raw, info, power)
    }

    #[test]
    fn raw_dft_checks_channel_dc_and_original_spectrum_readout() {
        let (raw, info, power) = fixture();
        assert!(check_frame(&raw, info, &power) < 1e-12);
    }

    #[test]
    #[should_panic(expected = "independent DFT")]
    fn raw_dft_rejects_an_incorrect_retained_amplitude() {
        let (raw, info, mut power) = fixture();
        power[32] *= 1.01;
        check_frame(&raw, info, &power);
    }
}
