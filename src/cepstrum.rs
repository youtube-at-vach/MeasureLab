//! Gain-normalized f64 real cepstrum. No GUI, calibration or display floor.
use rustfft::{Fft, FftPlanner, num_complex::Complex};
use std::sync::Arc;

pub const ALGORITHM: &str = "real-cepstrum-window-gain-relative-floor-v1";
pub const DEFAULT_LOG_FLOOR_DB: i16 = -160;

pub fn validate_floor(db: i16) -> Result<(), &'static str> {
    if (-300..=-60).contains(&db) {
        Ok(())
    } else {
        Err("Cepstrum log floor must be -300..=-60 dB")
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Status {
    Valid,
    NoSignal,
    NonFinite,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Info {
    pub algorithm: &'static str,
    pub status: Status,
    pub floored_bins: usize,
}

/// All buffers and the inverse FFT plan are created once per configuration.
pub struct Analyzer {
    inverse: Arc<dyn Fft<f64>>,
    buffer: Vec<Complex<f64>>,
    scratch: Vec<Complex<f64>>,
    coefficients: Vec<f64>,
    log_floor_db: i16,
}

impl Analyzer {
    pub fn new(size: usize, log_floor_db: i16) -> Result<Self, &'static str> {
        validate_floor(log_floor_db)?;
        if size < 2 || !size.is_power_of_two() {
            return Err("Invalid cepstrum size");
        }
        let inverse = FftPlanner::new().plan_fft_inverse(size);
        let scratch = vec![Complex::default(); inverse.get_inplace_scratch_len()];
        Ok(Self {
            inverse,
            buffer: vec![Complex::default(); size],
            scratch,
            coefficients: vec![f64::NAN; size / 2 + 1],
            log_floor_db,
        })
    }

    /// Accepts normalized one-sided *amplitude squared*, never PSD or dB.
    /// DC and Nyquist have no one-sided doubling. IFFT is normalized by N.
    pub fn process(&mut self, power: &[f64]) -> Info {
        self.coefficients.fill(f64::NAN);
        let mut info = Info {
            algorithm: ALGORITHM,
            status: Status::NonFinite,
            floored_bins: 0,
        };
        if power.len() != self.coefficients.len()
            || power.iter().any(|p| !p.is_finite() || *p < 0.0)
        {
            return info;
        }
        let half = self.buffer.len() / 2;
        let mut maximum = f64::NEG_INFINITY;
        for (k, &p) in power.iter().enumerate() {
            let log = 0.5 * p.ln()
                - if k == 0 || k == half {
                    0.0
                } else {
                    std::f64::consts::LN_2
                };
            self.buffer[k] = Complex::new(log, 0.0);
            maximum = maximum.max(log);
        }
        if maximum == f64::NEG_INFINITY {
            info.status = Status::NoSignal;
            return info;
        }
        let floor = maximum + self.log_floor_db as f64 * std::f64::consts::LN_10 / 20.0;
        for k in 0..=half {
            if self.buffer[k].re < floor {
                self.buffer[k].re = floor;
                info.floored_bins += 1;
            }
            if k > 0 && k < half {
                self.buffer[2 * half - k] = self.buffer[k];
            }
        }
        self.inverse
            .process_with_scratch(&mut self.buffer, &mut self.scratch);
        let n = self.buffer.len() as f64;
        for (c, value) in self.coefficients.iter_mut().zip(&self.buffer) {
            *c = value.re / n;
        }
        if self.coefficients.iter().all(|c| c.is_finite()) {
            info.status = Status::Valid;
        } else {
            self.coefficients.fill(f64::NAN);
        }
        info
    }

    /// Signed coefficients q=0..=N/2. Invalid states have no numerical values.
    pub fn coefficients(&self) -> &[f64] {
        &self.coefficients
    }

    pub fn storage_bytes(&self) -> usize {
        (self.buffer.capacity() + self.scratch.capacity()) * std::mem::size_of::<Complex<f64>>()
            + self.coefficients.capacity() * std::mem::size_of::<f64>()
    }
}

/// Power cepstrum convention: (2c)^2, dB re 1. Avoid squaring tiny c.
pub fn level_db(c: f64) -> f64 {
    20.0 * (c.abs().log10() + std::f64::consts::LOG10_2)
}

pub fn nearest_quefrency(seconds: f64, size: usize, sample_rate: u32) -> Option<usize> {
    if !seconds.is_finite() || seconds <= 0.0 || sample_rate == 0 || size < 2 {
        return None;
    }
    Some(
        (seconds * sample_rate as f64)
            .round()
            .clamp(1.0, (size / 2) as f64) as usize,
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::f64::consts::TAU;

    // Independent O(N²) complex DFT / real inverse DFT, with no production
    // normalization, floor, display or FFT helpers in the expected-value path.
    fn reference(
        input: &[f64],
        window: crate::spectrum::Window,
        dc: bool,
        floor_db: i16,
    ) -> (Vec<f64>, Vec<f64>, usize) {
        let n = input.len();
        let weights: Vec<_> = (0..n)
            .map(|i| {
                let x = TAU * i as f64 / n as f64;
                match window {
                    crate::spectrum::Window::Rectangular => 1.0,
                    crate::spectrum::Window::Hann => (1.0 - x.cos()) / 2.0,
                    crate::spectrum::Window::BlackmanHarris => {
                        0.35875 - 0.48829 * x.cos() + 0.14128 * (2.0 * x).cos()
                            - 0.01168 * (3.0 * x).cos()
                    }
                }
            })
            .collect();
        let gain: f64 = weights.iter().sum();
        let mean = if dc {
            input.iter().sum::<f64>() / n as f64
        } else {
            0.0
        };
        let amplitudes: Vec<_> = (0..n)
            .map(|k| {
                let (mut re, mut im) = (0.0, 0.0);
                for (i, (&x, &w)) in input.iter().zip(&weights).enumerate() {
                    let angle = TAU * k as f64 * i as f64 / n as f64;
                    re += (x - mean) * w * angle.cos();
                    im -= (x - mean) * w * angle.sin();
                }
                re.hypot(im) / gain
            })
            .collect();
        let max = amplitudes.iter().copied().fold(0.0, f64::max);
        let floor = max * 10.0_f64.powf(floor_db as f64 / 20.0);
        let logs: Vec<_> = amplitudes.iter().map(|a| a.max(floor).ln()).collect();
        let expected = (0..=n / 2)
            .map(|q| {
                logs.iter()
                    .enumerate()
                    .map(|(k, l)| l * (TAU * k as f64 * q as f64 / n as f64).cos())
                    .sum::<f64>()
                    / n as f64
            })
            .collect();
        let power = amplitudes[..=n / 2]
            .iter()
            .enumerate()
            .map(|(k, a)| (a * if k == 0 || k == n / 2 { 1.0 } else { 2.0 }).powi(2))
            .collect();
        let count = amplitudes[..=n / 2].iter().filter(|&&a| a < floor).count();
        (power, expected, count)
    }

    #[test]
    fn direct_dft_inverse_reference_all_windows_dc_and_relative_floors() {
        for n in [8, 16, 32, 64] {
            let input: Vec<_> = (0..n)
                .map(|i| ((i * 37 + i * i * 3) % 101) as f64 / 71.0 - 0.6)
                .collect();
            for window in [
                crate::spectrum::Window::Rectangular,
                crate::spectrum::Window::Hann,
                crate::spectrum::Window::BlackmanHarris,
            ] {
                for dc in [false, true] {
                    for floor in [-300, -160, -60] {
                        let (power, expected, count) = reference(&input, window, dc, floor);
                        let mut analyzer = Analyzer::new(n, floor).unwrap();
                        let info = analyzer.process(&power);
                        assert_eq!(info.status, Status::Valid);
                        assert_eq!(info.floored_bins, count);
                        for (q, (&actual, &expected)) in
                            analyzer.coefficients().iter().zip(&expected).enumerate()
                        {
                            assert!(
                                (actual - expected).abs() < 2e-10,
                                "n={n} {window:?} dc={dc} floor={floor} q={q}: {actual} vs {expected}"
                            );
                        }
                    }
                }
            }
        }
    }

    #[test]
    fn two_impulses_echo_sign_and_gain_invariance_include_coefficient_zero() {
        let n = 1024;
        let delay = 13;
        let echo = 0.4_f64;
        let power: Vec<_> = (0..=n / 2)
            .map(|k| {
                let angle = TAU * k as f64 * delay as f64 / n as f64;
                let square = (1.0 + echo * angle.cos()).powi(2) + (echo * angle.sin()).powi(2);
                square / (n * n) as f64 * if k == 0 || k == n / 2 { 1.0 } else { 4.0 }
            })
            .collect();
        let mut a = Analyzer::new(n, -160).unwrap();
        assert_eq!(a.process(&power).status, Status::Valid);
        let baseline = a.coefficients().to_vec();
        assert!((baseline[0] + (n as f64).ln()).abs() < 1e-13);
        for order in 1_i32..=6 {
            let expected =
                if order % 2 == 1 { 1.0 } else { -1.0 } * echo.powi(order) / (2 * order) as f64;
            assert!((baseline[order as usize * delay] - expected).abs() < 1e-13);
        }
        for gain in [1e-100_f64, -0.01, 3.0, -1e100] {
            let scaled: Vec<_> = power.iter().map(|p| p * gain * gain).collect();
            assert_eq!(a.process(&scaled).status, Status::Valid);
            assert!((a.coefficients()[0] - baseline[0] - gain.abs().ln()).abs() < 1e-12);
            for (&actual, &before) in a.coefficients()[1..].iter().zip(&baseline[1..]) {
                assert!((actual - before).abs() < 1e-12);
            }
        }
    }

    #[test]
    fn silence_flat_spectrum_subnormal_invalid_and_recovery_are_distinct() {
        let mut a = Analyzer::new(8, -160).unwrap();
        assert_eq!(a.process(&[0.0; 5]).status, Status::NoSignal);
        assert!(a.coefficients().iter().all(|c| c.is_nan()));
        for base in [1.0, f64::MIN_POSITIVE, f64::from_bits(1)] {
            let power = [base, 4.0 * base, 4.0 * base, 4.0 * base, base];
            assert_eq!(a.process(&power).status, Status::Valid);
            assert!(a.coefficients()[1..].iter().all(|c| c.abs() < 1e-13));
        }
        for bad in [-1.0, f64::NAN, f64::INFINITY, f64::NEG_INFINITY] {
            assert_eq!(
                a.process(&[1.0, 1.0, bad, 1.0, 1.0]).status,
                Status::NonFinite
            );
            assert!(a.coefficients().iter().all(|c| c.is_nan()));
        }
        assert_eq!(a.process(&[1.0; 4]).status, Status::NonFinite);
        let info = a.process(&[1.0, 0.0, 1e-200, 0.0, 1.0]);
        assert_eq!(info.status, Status::Valid);
        assert_eq!(info.floored_bins, 3);
        assert_eq!(level_db(0.0), f64::NEG_INFINITY);
        assert_eq!(level_db(-0.25), level_db(0.25));
        assert!(level_db(f64::from_bits(1)).is_finite());
        for floor in [-301, -59] {
            assert!(Analyzer::new(1024, floor).is_err());
        }
    }
}

#[cfg(test)]
mod periodic_tests {
    use super::*;
    #[test]
    fn harmonic_period_changes_with_noise_match_an_independent_inverse_sum() {
        let n = 1024;
        for period in [64, 128] {
            let signal: Vec<_> = (0..n)
                .map(|i| {
                    (1..=8)
                        .map(|h| {
                            (std::f64::consts::TAU * h as f64 * i as f64 / period as f64).cos()
                                / h as f64
                        })
                        .sum::<f64>()
                        + 1e-3 * (((i * 37 + i * i * 7) % 101) as f64 / 50.0 - 1.0)
                })
                .collect();
            // Independent raw-input direct DFT. Compare selected inverse bins
            // without using the production power-to-log or display helpers.
            let log: Vec<_> = (0..n)
                .map(|k| {
                    let (mut re, mut im) = (0.0_f64, 0.0_f64);
                    for (i, &x) in signal.iter().enumerate() {
                        let phase = std::f64::consts::TAU * k as f64 * i as f64 / n as f64;
                        re += x * phase.cos();
                        im -= x * phase.sin();
                    }
                    (re.hypot(im) / n as f64).ln()
                })
                .collect();
            let max = log.iter().copied().fold(f64::NEG_INFINITY, f64::max);
            let floor = max - 8.0 * 10.0_f64.ln();
            let power: Vec<_> = log[..=n / 2]
                .iter()
                .enumerate()
                .map(|(k, &l)| (l.exp() * if k == 0 || k == n / 2 { 1.0 } else { 2.0 }).powi(2))
                .collect();
            let mut analyzer = Analyzer::new(n, -160).unwrap();
            assert_eq!(analyzer.process(&power).status, Status::Valid);
            for q in [0, 1, period - 1, period, period + 1, n / 2] {
                let expected = log
                    .iter()
                    .enumerate()
                    .map(|(k, &l)| {
                        l.max(floor)
                            * (std::f64::consts::TAU * k as f64 * q as f64 / n as f64).cos()
                    })
                    .sum::<f64>()
                    / n as f64;
                assert!((analyzer.coefficients()[q] - expected).abs() < 1e-10);
            }
            // Noise changes peak ordering; correctness here is the independent
            // inverse reference, not a pitch-detection guarantee.
        }
    }
}
