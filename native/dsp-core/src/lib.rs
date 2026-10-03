//! MIG-006-A pure FFT candidate. No Qt, device, callback or shared graph.
//! FFT arithmetic and inverse retain T (f32/f64); reductions and units use f64.

use realfft::num_complex::Complex;
use realfft::{ComplexToReal, FftNum, RealFftPlanner, RealToComplex};
use std::collections::HashSet;
use std::sync::Arc;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Window {
    Boxcar,
    SymmetricHann,
}

#[derive(Debug)]
pub struct Analysis<T> {
    pub channel_ids: Vec<String>,
    pub window: Vec<f64>,
    pub frequency_hz: Vec<f64>,
    /// Bin-major, channel-major, normalized X/N.
    pub fft_over_n: Vec<Complex<f64>>,
    /// Frame-major, channel-major, inverse(forward(x*w))/N.
    pub inverse_windowed: Vec<T>,
    pub peak_fs: Vec<f64>,
    pub tone_rms_fs: Vec<f64>,
    pub psd_fs2_hz: Vec<f64>,
    pub asd_fs_sqrt_hz: Vec<f64>,
    pub rms_fs: Vec<f64>,
    pub integrated_power_fs2: Vec<f64>,
    pub time_window_power_fs2: Vec<f64>,
}

/// One caller owns the mutable scratch. Reusing a plan is not result sharing.
pub struct Analyzer<T: FftNum + realfft::num_traits::ToPrimitive> {
    n: usize,
    rate_hz: f64,
    window: Vec<f64>,
    window_sum: f64,
    window_square_sum: f64,
    forward: Arc<dyn RealToComplex<T>>,
    inverse: Arc<dyn ComplexToReal<T>>,
    forward_scratch: Vec<Complex<T>>,
    inverse_scratch: Vec<Complex<T>>,
}

fn scalar<T: FftNum + realfft::num_traits::ToPrimitive>(value: f64) -> T {
    T::from_f64(value).expect("FftNum supports f64 conversion")
}

fn double<T: FftNum + realfft::num_traits::ToPrimitive>(value: T) -> f64 {
    value.to_f64().expect("FftNum supports conversion to f64")
}

pub fn one_sided_factor(n: usize, bin: usize) -> f64 {
    if bin == 0 || (n.is_multiple_of(2) && bin == n / 2) {
        1.0
    } else {
        2.0
    }
}

impl<T: FftNum + realfft::num_traits::ToPrimitive> Analyzer<T> {
    pub fn new(n: usize, rate_hz: f64, window: Window) -> Result<Self, String> {
        if n < 3 || !rate_hz.is_finite() || rate_hz <= 0.0 {
            return Err("FFT requires N >= 3 and a finite positive sample rate".into());
        }
        let window: Vec<_> = (0..n)
            .map(|i| match window {
                Window::Boxcar => 1.0,
                Window::SymmetricHann => {
                    0.5 - 0.5 * (std::f64::consts::TAU * i as f64 / (n - 1) as f64).cos()
                }
            })
            .collect();
        let window_sum = window.iter().sum::<f64>();
        let window_square_sum = window.iter().map(|w| w * w).sum::<f64>();
        if window_sum <= 0.0 || !window_sum.is_finite() || !window_square_sum.is_finite() {
            return Err("Invalid window normalization".into());
        }
        let mut planner = RealFftPlanner::<T>::new();
        let forward = planner.plan_fft_forward(n);
        let inverse = planner.plan_fft_inverse(n);
        let forward_scratch = forward.make_scratch_vec();
        let inverse_scratch = inverse.make_scratch_vec();
        Ok(Self {
            n,
            rate_hz,
            window,
            window_sum,
            window_square_sum,
            forward,
            inverse,
            forward_scratch,
            inverse_scratch,
        })
    }

    pub fn analyze(&mut self, input: &[T], channel_ids: &[String]) -> Result<Analysis<T>, String> {
        let channels = channel_ids.len();
        if channels == 0
            || channel_ids.iter().any(String::is_empty)
            || channel_ids.iter().collect::<HashSet<_>>().len() != channels
            || self.n.checked_mul(channels) != Some(input.len())
        {
            return Err("Channel IDs or frame-major input dimensions are invalid".into());
        }
        if input.iter().any(|x| !double(*x).is_finite()) {
            return Err("Nonfinite input".into());
        }
        let bins = self.n / 2 + 1;
        let mut result = Analysis {
            channel_ids: channel_ids.to_vec(),
            window: self.window.clone(),
            frequency_hz: (0..bins)
                .map(|k| k as f64 * (self.rate_hz / self.n as f64))
                .collect(),
            fft_over_n: vec![Complex::new(0.0, 0.0); bins * channels],
            inverse_windowed: vec![scalar(0.0); input.len()],
            peak_fs: vec![0.0; bins * channels],
            tone_rms_fs: vec![0.0; bins * channels],
            psd_fs2_hz: vec![0.0; bins * channels],
            asd_fs_sqrt_hz: vec![0.0; bins * channels],
            rms_fs: vec![0.0; channels],
            integrated_power_fs2: vec![0.0; channels],
            time_window_power_fs2: vec![0.0; channels],
        };
        let mut time = self.forward.make_input_vec();
        let mut spectrum = self.forward.make_output_vec();
        let mut inverse_time = self.inverse.make_output_vec();
        for c in 0..channels {
            let mut time_energy = 0.0;
            let mut window_energy = 0.0;
            for i in 0..self.n {
                let x = input[i * channels + c];
                // Match the explicit f32 reference: cast the f64 window before multiplication.
                time[i] = x * scalar(self.window[i]);
                time_energy += double(x).powi(2);
                window_energy += (double(x) * self.window[i]).powi(2);
            }
            self.forward
                .process_with_scratch(&mut time, &mut spectrum, &mut self.forward_scratch)
                .map_err(|e| e.to_string())?;
            let mut psd_sum = 0.0;
            for (k, raw) in spectrum.iter().enumerate() {
                let z = Complex::new(double(raw.re), double(raw.im));
                let factor = one_sided_factor(self.n, k);
                let at = k * channels + c;
                let magnitude = z.norm();
                let peak = factor * magnitude / self.window_sum;
                let psd = factor * magnitude.powi(2) / (self.rate_hz * self.window_square_sum);
                result.fft_over_n[at] = z / self.n as f64;
                result.peak_fs[at] = peak;
                result.tone_rms_fs[at] = if factor == 1.0 {
                    peak
                } else {
                    peak / std::f64::consts::SQRT_2
                };
                result.psd_fs2_hz[at] = psd;
                result.asd_fs_sqrt_hz[at] = psd.sqrt();
                psd_sum += psd;
            }
            self.inverse
                .process_with_scratch(&mut spectrum, &mut inverse_time, &mut self.inverse_scratch)
                .map_err(|e| e.to_string())?;
            for (i, value) in inverse_time.iter().enumerate() {
                result.inverse_windowed[i * channels + c] = *value / scalar(self.n as f64);
            }
            result.rms_fs[c] = (time_energy / self.n as f64).sqrt();
            result.time_window_power_fs2[c] = window_energy / self.window_square_sum;
            result.integrated_power_fs2[c] = psd_sum * (self.rate_hz / self.n as f64);
        }
        if result
            .fft_over_n
            .iter()
            .any(|z| !z.re.is_finite() || !z.im.is_finite())
            || result
                .inverse_windowed
                .iter()
                .any(|x| !double(*x).is_finite())
            || [
                &result.peak_fs,
                &result.tone_rms_fs,
                &result.psd_fs2_hz,
                &result.asd_fs_sqrt_hz,
                &result.rms_fs,
                &result.time_window_power_fs2,
                &result.integrated_power_fs2,
            ]
            .into_iter()
            .flatten()
            .any(|v| !v.is_finite())
        {
            return Err("Nonfinite analysis result".into());
        }
        Ok(result)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn ids(n: usize) -> Vec<String> {
        (0..n).map(|c| format!("input.{c}")).collect()
    }

    #[test]
    fn endpoint_units_and_parseval() {
        let n = 16;
        let input: Vec<_> = (0..n)
            .flat_map(|i| [0.125, if i % 2 == 0 { 0.25 } else { -0.25 }])
            .collect();
        let result = Analyzer::new(n, 48000.0, Window::Boxcar)
            .unwrap()
            .analyze(&input, &ids(2))
            .unwrap();
        for (c, bin, amplitude) in [(0, 0, 0.125), (1, n / 2, 0.25)] {
            assert_eq!(result.peak_fs[bin * 2 + c], amplitude);
            assert_eq!(result.tone_rms_fs[bin * 2 + c], amplitude);
            assert_eq!(result.rms_fs[c], amplitude);
            assert!((result.integrated_power_fs2[c] - amplitude * amplitude).abs() < 1e-15);
        }
        assert_eq!(result.inverse_windowed, input);
        assert_eq!(result.frequency_hz[n / 2], 24000.0);
    }

    #[test]
    fn odd_last_bin_has_complex_phase_and_double_factor() {
        let n = 15;
        let phase = 0.3;
        let input: Vec<f64> = (0..n)
            .map(|i| 0.125 * (std::f64::consts::TAU * 7.0 * i as f64 / n as f64 + phase).cos())
            .collect();
        let result = Analyzer::new(n, 48000.0, Window::Boxcar)
            .unwrap()
            .analyze(&input, &ids(1))
            .unwrap();
        assert!((result.peak_fs[7] - 0.125).abs() < 1e-14);
        assert!((result.fft_over_n[7].arg() - phase).abs() < 1e-14);
        assert!((result.tone_rms_fs[7] - 0.125 / 2.0_f64.sqrt()).abs() < 1e-14);
        for (x, y) in input.iter().zip(result.inverse_windowed) {
            assert!((x - y).abs() < 1e-14);
        }
    }

    #[test]
    fn f32_hann_multichannel_and_plan_reuse() {
        let n = 127;
        let mut analyzer = Analyzer::<f32>::new(n, 48000.0, Window::SymmetricHann).unwrap();
        let input: Vec<_> = (0..n).flat_map(|_| [0.125_f32, -0.25, 0.5, 0.0]).collect();
        let first = analyzer.analyze(&input, &ids(4)).unwrap();
        let second = analyzer.analyze(&vec![0.0; n * 4], &ids(4)).unwrap();
        assert_eq!(first.channel_ids, ids(4));
        assert_eq!(first.window[0], 0.0);
        assert_eq!(first.window[n - 1], 0.0);
        assert_eq!(first.rms_fs, [0.125, 0.25, 0.5, 0.0]);
        for c in 0..4 {
            assert!((first.integrated_power_fs2[c] - first.time_window_power_fs2[c]).abs() < 2e-6);
        }
        assert!(second.fft_over_n.iter().all(|z| z.norm() == 0.0));
        // The previous owned result survives the next execution unchanged.
        assert!(first.fft_over_n[0].norm() > 0.0);
    }

    #[test]
    fn impulse_sign_and_inverse_match_direct_dft() {
        for n in [7, 12, 16] {
            let input: Vec<f64> = (0..n).map(|i| if i == 1 { 1.0 } else { 0.0 }).collect();
            let result = Analyzer::new(n, 48000.0, Window::Boxcar)
                .unwrap()
                .analyze(&input, &ids(1))
                .unwrap();
            for (k, z) in result.fft_over_n.iter().enumerate() {
                let angle = -std::f64::consts::TAU * k as f64 / n as f64;
                assert!((*z - Complex::from_polar(1.0 / n as f64, angle)).norm() < 1e-14);
            }
            assert!((result.rms_fs[0] - (1.0 / n as f64).sqrt()).abs() < 1e-14);
        }
    }

    #[test]
    fn rejects_invalid_dimensions_ids_rates_and_nonfinite_values() {
        for rate in [0.0, -1.0, f64::NAN, f64::INFINITY] {
            assert!(Analyzer::<f64>::new(16, rate, Window::Boxcar).is_err());
        }
        assert!(Analyzer::<f64>::new(2, 48000.0, Window::SymmetricHann).is_err());
        let mut analyzer = Analyzer::new(3, 48000.0, Window::Boxcar).unwrap();
        assert!(analyzer.analyze(&[0.0_f64; 3], &[]).is_err());
        assert!(analyzer.analyze(&[0.0; 3], &[String::new()]).is_err());
        assert!(
            analyzer
                .analyze(&[0.0; 6], &["a".into(), "a".into()])
                .is_err()
        );
        assert!(analyzer.analyze(&[0.0; 2], &ids(1)).is_err());
        assert!(analyzer.analyze(&[f64::NAN; 3], &ids(1)).is_err());
        assert!(analyzer.analyze(&[f64::MAX; 3], &ids(1)).is_err());
    }
}
