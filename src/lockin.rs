//! Experimental fundamental-only detector referenced to two synchronous input CHs.
//! REF is checked and phase-corrected before filtering; timing uses integer samples.
use std::{f64::consts::TAU, ops::Range};

#[derive(Clone, Copy, Debug, PartialEq, serde::Serialize, serde::Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Settings {
    pub enabled: bool,
    pub reference_channel: usize,
    pub response_channel: usize,
    /// Expected REF frequency; measured tracking is limited to ±10% of this hint.
    pub frequency_hz: f64,
    pub time_constant_seconds: f64,
    pub reference_min_rms_fs: f64,
    pub integration_samples: usize,
    pub track_reference: bool,
}
impl Default for Settings {
    fn default() -> Self {
        Self {
            enabled: false,
            reference_channel: 0,
            response_channel: 1,
            frequency_hz: 1000.0,
            time_constant_seconds: 0.02,
            reference_min_rms_fs: 0.001,
            integration_samples: 4096,
            track_reference: true,
        }
    }
}
impl Settings {
    pub fn validate(self, rate: u32) -> std::result::Result<(), String> {
        crate::audio::validate_sample_rate(rate)?;
        if self.reference_channel >= 16
            || self.response_channel >= 16
            || !self.frequency_hz.is_finite()
            || self.frequency_hz < 10.0
            || self.frequency_hz >= rate as f64 * 0.45
            || !self.time_constant_seconds.is_finite()
            || !(0.001..=10.0).contains(&self.time_constant_seconds)
            || !self.reference_min_rms_fs.is_finite()
            || self.reference_min_rms_fs <= 0.0
            || ![1024, 4096, 16384, 65536].contains(&self.integration_samples)
        {
            return Err("Invalid Lock-in settings".into());
        }
        Ok(())
    }
}
#[derive(Clone, Copy, Debug, PartialEq, serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum State {
    Disabled,
    Unavailable,
    Settling,
    Valid,
    ReferenceLost,
    ReferenceUnstable,
    Missing,
    NonFinite,
}
#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Result {
    pub state: State,
    pub settings: Settings,
    pub sample_range: Range<u64>,
    pub latest_window: Range<u64>,
    pub missing_samples: u64,
    pub processed_windows: u64,
    pub reference_frequency_hz: Option<f64>,
    pub reference_ac_rms_fs: Option<f64>,
    /// Fraction of REF's AC energy explained by a single sinusoid (not coherence).
    pub reference_sinusoid_fraction: Option<f64>,
    pub reference_peak: Option<f64>,
    pub x: Option<f64>,
    pub y: Option<f64>,
    pub amplitude_peak: Option<f64>,
    pub phase_degrees: Option<f64>,
    pub gain: Option<f64>,
}
pub struct Analyzer {
    settings: Settings,
    rate: u32,
    data: Vec<[f64; 2]>,
    weights: Vec<f64>,
    count: usize,
    start: u64,
    expected: Option<u64>,
    poles: [[f64; 2]; 2],
    gain_poles: [[f64; 2]; 2],
    elapsed: u64,
    calibrations: crate::calibration::Set,
    result: Result,
}
impl Analyzer {
    pub fn new(settings: Settings, rate: u32) -> Self {
        let state = if !settings.enabled {
            State::Disabled
        } else if settings.validate(rate).is_err() {
            State::Unavailable
        } else {
            State::Settling
        };
        Self {
            settings,
            rate,
            data: vec![[0.0; 2]; settings.integration_samples.clamp(1, 65536)],
            weights: (0..settings.integration_samples.clamp(1, 65536))
                .map(|i| {
                    0.5 - 0.5
                        * (TAU * i as f64 / settings.integration_samples.clamp(1, 65536) as f64)
                            .cos()
                })
                .collect(),
            count: 0,
            start: 0,
            expected: None,
            poles: [[0.0; 2]; 2],
            gain_poles: [[0.0; 2]; 2],
            elapsed: 0,
            calibrations: crate::calibration::Set::default(),
            result: Result {
                state,
                settings,
                sample_range: 0..0,
                latest_window: 0..0,
                missing_samples: 0,
                processed_windows: 0,
                reference_frequency_hz: None,
                reference_ac_rms_fs: None,
                reference_sinusoid_fraction: None,
                reference_peak: None,
                x: None,
                y: None,
                amplitude_peak: None,
                phase_degrees: None,
                gain: None,
            },
        }
    }
    pub fn set_calibrations(&mut self, set: crate::calibration::Set) {
        self.calibrations = set;
    }
    pub fn result(&self) -> &Result {
        &self.result
    }
    fn invalidate(&mut self, state: State) {
        self.count = 0;
        self.poles = [[0.0; 2]; 2];
        self.gain_poles = [[0.0; 2]; 2];
        self.elapsed = 0;
        self.result.state = state;
        self.result.sample_range = 0..0;
        self.result.processed_windows = 0;
        self.result.reference_peak = None;
        self.result.x = None;
        self.result.y = None;
        self.result.amplitude_peak = None;
        self.result.phase_degrees = None;
        self.result.gain = None;
        self.result.reference_frequency_hz = None;
        self.result.reference_ac_rms_fs = None;
        self.result.reference_sinusoid_fraction = None;
    }
    pub fn gap_to(&mut self, next: u64) {
        if !self.settings.enabled || self.result.state == State::Unavailable {
            return;
        }
        if let Some(end) = self.expected
            && end != next
        {
            self.result.missing_samples += next.saturating_sub(end);
            self.invalidate(State::Missing);
        }
        self.expected = Some(next);
    }
    pub fn push(&mut self, n: u64, samples: &[f64]) {
        if !self.settings.enabled || self.settings.validate(self.rate).is_err() {
            return;
        }
        if self.settings.reference_channel >= samples.len()
            || self.settings.response_channel >= samples.len()
        {
            self.invalidate(State::Unavailable);
            return;
        }
        let raw = [
            samples[self.settings.reference_channel],
            samples[self.settings.response_channel],
        ];
        self.push_pair(n, raw);
    }
    pub fn push_pair(&mut self, n: u64, raw: [f64; 2]) {
        if !self.settings.enabled || self.settings.validate(self.rate).is_err() {
            return;
        }
        self.gap_to(n);
        self.expected = Some(n + 1);
        if raw.iter().any(|x| !x.is_finite()) {
            self.invalidate(State::NonFinite);
            return;
        }
        if self.count == 0 {
            self.start = n;
        }
        self.data[self.count] = raw;
        self.count += 1;
        if self.count == self.data.len() {
            self.process();
            self.count = 0;
        }
    }
    fn process(&mut self) {
        let size = self.data.len();
        let end = self.start + size as u64;
        self.result.latest_window = self.start..end;
        let mean = self.data.iter().map(|x| x[0]).sum::<f64>() / size as f64;
        let energy = self.data.iter().map(|x| (x[0] - mean).powi(2)).sum::<f64>();
        let rms = (energy / size as f64).sqrt();
        // Gate current raw REF, including DC-only reference, BEFORE any old LPF state.
        if !rms.is_finite() || rms < self.settings.reference_min_rms_fs {
            self.invalidate(State::ReferenceLost);
            self.result.latest_window = self.start..end;
            return;
        }
        let frequency = if self.settings.track_reference {
            let Some(f) = estimate_frequency(
                &self.data,
                &self.weights,
                self.rate,
                self.settings.frequency_hz,
            ) else {
                self.invalidate(State::ReferenceUnstable);
                return;
            };
            f
        } else {
            self.settings.frequency_hz
        };
        if frequency * size as f64 / (self.rate as f64) < 3.0 {
            self.invalidate(State::ReferenceUnstable);
            return;
        }
        let Some((fit, residual)) = project(&self.data, &self.weights, frequency, self.rate) else {
            self.invalidate(State::NonFinite);
            return;
        };
        let fraction = (1.0 - residual / energy).clamp(0.0, 1.0);
        // A noisy or multi-tone REF must not silently become an absolute phase standard.
        if fraction < 0.98 {
            self.invalidate(State::ReferenceUnstable);
            return;
        }
        let ref_gain = self
            .calibrations
            .get(self.settings.reference_channel)
            .map_or(1.0, |c| c.gain());
        let sig_gain = self
            .calibrations
            .get(self.settings.response_channel)
            .map_or(1.0, |c| c.gain());
        let [rx, ry] = [fit[0][1] * ref_gain, fit[0][2] * ref_gain];
        let [sx, sy] = [fit[1][1] * sig_gain, fit[1][2] * sig_gain];
        let reference = rx.hypot(ry);
        if reference <= 0.0 || !reference.is_finite() {
            self.invalidate(State::ReferenceLost);
            return;
        }
        // Fundamental phase rotation cancels the LOCAL oscillator origin exactly.
        // Unlike filtering CH phasors first, it also rejects common REF frequency drift.
        // Normalize REF first: the unnormalized products can overflow or
        // underflow even when the rotated response is representable.
        let [ux, uy] = [rx / reference, ry / reference];
        let rotated = [sx * ux + sy * uy, sy * ux - sx * uy];
        let transfer = rotated.map(|value| value / reference);
        if rotated.iter().chain(&transfer).any(|x| !x.is_finite()) {
            self.invalidate(State::NonFinite);
            return;
        }
        let alpha =
            -(-(size as f64) / (self.rate as f64 * self.settings.time_constant_seconds)).exp_m1();
        if self.elapsed == 0 {
            self.result.sample_range = self.start..end;
        } else {
            self.result.sample_range.end = end;
        }
        for (q, value) in rotated.iter().enumerate() {
            self.poles[0][q] += alpha * (value - self.poles[0][q]);
            self.poles[1][q] += alpha * (self.poles[0][q] - self.poles[1][q]);
            // Average the complex transfer before taking magnitude, so an
            // asynchronous response is rejected in gain as well as in X/Y.
            self.gain_poles[0][q] += alpha * (transfer[q] - self.gain_poles[0][q]);
            self.gain_poles[1][q] += alpha * (self.gain_poles[0][q] - self.gain_poles[1][q]);
        }
        let [x, y] = self.poles[1];
        let amplitude = x.hypot(y);
        let gain = self.gain_poles[1][0].hypot(self.gain_poles[1][1]);
        if [x, y, amplitude, gain]
            .iter()
            .any(|value| !value.is_finite())
        {
            self.invalidate(State::NonFinite);
            return;
        }
        self.elapsed += size as u64;
        self.result.processed_windows += 1;
        self.result.state = if self.elapsed as f64
            >= 10.0 * self.settings.time_constant_seconds * self.rate as f64
        {
            State::Valid
        } else {
            State::Settling
        };
        self.result.reference_frequency_hz = Some(frequency);
        self.result.reference_ac_rms_fs = Some(rms);
        self.result.reference_sinusoid_fraction = Some(fraction);
        self.result.reference_peak = Some(reference);
        self.result.x = Some(x);
        self.result.y = Some(y);
        self.result.amplitude_peak = Some(amplitude);
        self.result.phase_degrees = Some(y.atan2(x).to_degrees());
        self.result.gain = Some(gain);
    }
}

/// Periodic-Hann weighted DC-inclusive least squares avoids finite-window DC and
/// negative-frequency leakage while reducing out-of-band aliasing before decimation.
/// Both channels use exactly the same basis and integer window. Local phase keeps
/// absolute sample indices (including indices > 2^53) out of floating arithmetic.
fn project(
    data: &[[f64; 2]],
    weights: &[f64],
    frequency: f64,
    rate: u32,
) -> Option<([[f64; 3]; 2], f64)> {
    let mut matrix = [[0.0; 3]; 3];
    let mut rhs = [[0.0; 3]; 2];
    basis(data.len(), frequency, rate, |i, b| {
        for row in 0..3 {
            for col in 0..3 {
                matrix[row][col] += weights[i] * b[row] * b[col];
            }
            for ch in 0..2 {
                rhs[ch][row] += weights[i] * data[i][ch] * b[row];
            }
        }
    });
    let fit = [solve(matrix, rhs[0])?, solve(matrix, rhs[1])?];
    let mut residual = 0.0;
    basis(data.len(), frequency, rate, |i, b| {
        let predicted = fit[0].iter().zip(b).map(|(x, y)| x * y).sum::<f64>();
        residual += (data[i][0] - predicted).powi(2);
    });
    Some((fit, residual))
}
fn basis(size: usize, frequency: f64, rate: u32, mut f: impl FnMut(usize, [f64; 3])) {
    let step = TAU * frequency / rate as f64;
    let (ds, dc) = step.sin_cos();
    let (mut s, mut c) = (0.0, 1.0);
    for i in 0..size {
        if i % 256 == 0 {
            (s, c) = ((i as f64 * step).rem_euclid(TAU)).sin_cos();
        }
        f(i, [1.0, s, c]);
        (s, c) = (s * dc + c * ds, c * dc - s * ds);
    }
}
fn estimate_frequency(data: &[[f64; 2]], weights: &[f64], rate: u32, hint: f64) -> Option<f64> {
    // The legacy AR(2) seed is extended with an intercept so arbitrary REF DC
    // and non-integer periods do not bias the recurrence coefficient.
    let count = (data.len() - 2) as f64;
    let mx = data[1..data.len() - 1].iter().map(|x| x[0]).sum::<f64>() / count;
    let my = data.windows(3).map(|w| w[0][0] + w[2][0]).sum::<f64>() / count;
    let mut covariance = 0.0;
    let mut variance = 0.0;
    for w in data.windows(3) {
        let x = w[1][0] - mx;
        covariance += x * (w[0][0] + w[2][0] - my);
        variance += x * x;
    }
    if variance <= 0.0 {
        return None;
    }
    let cosine = covariance / (2.0 * variance);
    if !(-1.0..1.0).contains(&cosine) {
        return None;
    }
    let seed = cosine.acos() * rate as f64 / TAU;
    if !(hint * 0.9..=hint * 1.1).contains(&seed) {
        return None;
    }
    let width = rate as f64 / data.len() as f64 * 0.75;
    let mut lo = (seed - width).max(hint * 0.9);
    let mut hi = (seed + width).min(hint * 1.1);
    let ratio = (5.0_f64.sqrt() - 1.0) / 2.0;
    let mut a = hi - ratio * (hi - lo);
    let mut b = lo + ratio * (hi - lo);
    let mut fa = project(data, weights, a, rate)?.1;
    let mut fb = project(data, weights, b, rate)?.1;
    for _ in 0..54 {
        if fa < fb {
            hi = b;
            b = a;
            fb = fa;
            a = hi - ratio * (hi - lo);
            fa = project(data, weights, a, rate)?.1;
        } else {
            lo = a;
            a = b;
            fa = fb;
            b = lo + ratio * (hi - lo);
            fb = project(data, weights, b, rate)?.1;
        }
    }
    Some((lo + hi) / 2.0)
}
fn solve(mut a: [[f64; 3]; 3], mut b: [f64; 3]) -> Option<[f64; 3]> {
    for col in 0..3 {
        let pivot = (col..3).max_by(|&i, &j| a[i][col].abs().total_cmp(&a[j][col].abs()))?;
        a.swap(col, pivot);
        b.swap(col, pivot);
        let d = a[col][col];
        if !d.is_finite() || d.abs() < 1e-12 {
            return None;
        }
        for value in &mut a[col][col..] {
            *value /= d;
        }
        b[col] /= d;
        for i in 0..3 {
            if i != col {
                let f = a[i][col];
                let pivot_row = a[col];
                for (value, pivot) in a[i][col..].iter_mut().zip(&pivot_row[col..]) {
                    *value -= f * pivot;
                }
                b[i] -= f * b[col];
            }
        }
    }
    b.iter().all(|x| x.is_finite()).then_some(b)
}

#[cfg(test)]
mod tests {
    use super::*;
    fn settings() -> Settings {
        Settings {
            enabled: true,
            integration_samples: 1024,
            ..Default::default()
        }
    }

    fn calibration_gains(reference: f64, response: f64) -> crate::calibration::Set {
        [reference, response].into_iter().enumerate().fold(
            crate::calibration::Set::default(),
            |set, (channel, gain)| {
                let calibration = crate::calibration::Calibration::new(
                    format!("channel-{channel}"),
                    1,
                    gain,
                    0.0,
                    "V".into(),
                    "virtual reference".into(),
                )
                .unwrap();
                set.with(channel, Some(calibration)).unwrap()
            },
        )
    }

    #[test]
    fn calibrated_rotation_preserves_representable_extreme_amplitudes() {
        for scale in [1e-200_f64, -1e-200, 1e200, -1e200] {
            let cfg = Settings {
                time_constant_seconds: 0.001,
                track_reference: false,
                ..settings()
            };
            let mut analyzer = Analyzer::new(cfg, 48000);
            analyzer.set_calibrations(calibration_gains(scale, scale));
            let phase = 0.7_f64;
            for n in 0..4096 {
                let angle = TAU * 1000.0 * n as f64 / 48000.0;
                analyzer.push(n, &[0.125 * angle.sin(), 0.0625 * (angle + phase).sin()]);
            }
            let result = analyzer.result();
            assert_eq!(result.state, State::Valid, "{scale}: {result:?}");
            let amplitude = 0.0625 * scale.abs();
            assert!(
                (result.x.unwrap() / amplitude - phase.cos()).abs() < 1e-10,
                "{scale}: {result:?}"
            );
            assert!((result.y.unwrap() / amplitude - phase.sin()).abs() < 1e-10);
            assert!((result.amplitude_peak.unwrap() / amplitude - 1.0).abs() < 1e-10);
            assert!((result.gain.unwrap() - 0.5).abs() < 1e-10);
        }
    }

    #[test]
    fn unrepresentable_calibrated_gain_invalidates_and_recovers() {
        let cfg = Settings {
            time_constant_seconds: 0.001,
            track_reference: false,
            ..settings()
        };
        // The first case overflows transfer components; the second has finite
        // components whose combined magnitude is outside the f64 range.
        for reference_gain in [1e-310, 1e-308] {
            let mut analyzer = Analyzer::new(cfg, 48000);
            analyzer.set_calibrations(calibration_gains(reference_gain, 1.0));
            for n in 0..4096 {
                let angle = TAU * 1000.0 * n as f64 / 48000.0;
                analyzer.push(n, &[0.125 * angle.sin(), 0.25 * (angle + TAU / 8.0).sin()]);
            }
            let result = analyzer.result();
            assert_eq!(result.state, State::NonFinite, "{result:?}");
            assert!(result.gain.is_none());
            assert!(result.amplitude_peak.is_none());
            assert!(result.x.is_none() && result.y.is_none());
            assert_eq!(result.processed_windows, 0);

            analyzer.set_calibrations(crate::calibration::Set::default());
            for n in 4096..8192 {
                let x = (TAU * 1000.0 * n as f64 / 48000.0).sin();
                analyzer.push(n, &[0.125 * x, 0.0625 * x]);
            }
            assert_eq!(analyzer.result().state, State::Valid);
            assert_eq!(analyzer.result().sample_range, 4096..8192);
            assert!((analyzer.result().gain.unwrap() - 0.5).abs() < 1e-10);
        }
    }

    #[test]
    fn physical_ref_rotation_precedes_filter_and_uses_sample_time() {
        for (rate, f, phase, gain, origin) in [
            (48000, 1000.0, 30.0_f64, 0.5, 0u64),
            (44100, 1003.7, -70.0, 1e-7, (1u64 << 54) + 7),
            (96000, 997.1, 90.0, -0.75, 17),
        ] {
            let mut a = Analyzer::new(settings(), rate);
            for n in 0..rate * 2 {
                let common = 0.3 + TAU * f * n as f64 / rate as f64;
                a.push(
                    origin + n as u64,
                    &[
                        0.25 + 0.125 * common.sin(),
                        0.1 + 0.125 * gain * (common + phase.to_radians()).sin(),
                    ],
                );
            }
            let r = a.result();
            assert_eq!(r.state, State::Valid);
            assert!((r.reference_frequency_hz.unwrap() - f).abs() < 1e-7);
            let tolerance = (0.125 * gain).abs() * 2e-7 + 1e-15;
            assert!(
                (r.x.unwrap() - 0.125 * gain * phase.to_radians().cos()).abs() < tolerance,
                "{r:?}"
            );
            assert!(
                (r.y.unwrap() - 0.125 * gain * phase.to_radians().sin()).abs() < tolerance,
                "{r:?}"
            );
        }
    }
    #[test]
    fn reference_loss_clears_filter_and_restart_requires_settling() {
        let mut a = Analyzer::new(settings(), 48000);
        for n in 0..24000 {
            let x = (TAU * 1000.0 * n as f64 / 48000.0).sin();
            a.push(n, &[0.125 * x, 0.5 * x]);
        }
        assert_eq!(a.result().state, State::Valid);
        for n in 24000..26000 {
            a.push(n, &[0.3, 0.5]);
        }
        assert_eq!(a.result().state, State::ReferenceLost);
        assert!(a.result().amplitude_peak.is_none());
        for n in 26000..29000 {
            let x = (TAU * 1000.0 * n as f64 / 48000.0).sin();
            a.push(n, &[0.125 * x, -0.25 * x]);
        }
        assert_eq!(a.result().state, State::Settling);
        a.push(29010, &[0.1, 0.2]);
        assert_eq!(a.result().state, State::Missing);
        assert_eq!(a.result().missing_samples, 10);
        a.push(29011, &[f64::NAN, 0.0]);
        assert_eq!(a.result().state, State::NonFinite);
    }
    #[test]
    fn common_frequency_offset_is_tracked_but_signal_offset_is_rejected_by_filter() {
        let mut a = Analyzer::new(settings(), 48000);
        for n in 0..96000 {
            let t = n as f64 / 48000.0;
            a.push(
                n,
                &[
                    0.125 * (TAU * 1001.0 * t).sin(),
                    0.0625 * (TAU * 1021.0 * t).sin(),
                ],
            );
        }
        assert_eq!(a.result().state, State::Valid);
        assert!((a.result().reference_frequency_hz.unwrap() - 1001.0).abs() < 1e-7);
        assert!(a.result().amplitude_peak.unwrap() < 0.02);
        assert!(a.result().gain.unwrap() < 0.16);
        let mut a = Analyzer::new(settings(), 48000);
        for n in 0..2048 {
            a.push(n, &[if n % 2 == 0 { 0.125 } else { -0.125 }, 0.5]);
        }
        assert_eq!(a.result().state, State::ReferenceUnstable);
    }

    #[test]
    fn ref_phase_changes_calibration_and_filter_steps_follow_complete_windows() {
        let mut cfg = settings();
        cfg.time_constant_seconds = 0.05;
        let calibration = |id: &str, gain, offset| {
            crate::calibration::Calibration::new(
                id.into(),
                1,
                gain,
                offset,
                "V".into(),
                "virtual reference".into(),
            )
            .unwrap()
        };
        let set = crate::calibration::Set::default()
            .with(0, Some(calibration("ref", -2.0, 500.0)))
            .unwrap()
            .with(1, Some(calibration("sig", 4.0, -700.0)))
            .unwrap();
        let mut a = Analyzer::new(cfg, 48000);
        a.set_calibrations(set);
        let alpha = -(-(1024.0_f64) / (48000.0 * 0.05)).exp_m1();
        let mut p = [0.0; 2];
        for block in 0..24 {
            // A common REF phase jump at a block boundary must cancel BEFORE
            // either low-pass pole. Calibration offsets must not enter AC.
            for i in 0..1024 {
                let phase = TAU * 1003.7 * i as f64 / 48000.0 + block as f64 * 0.37;
                a.push(
                    block * 1024 + i,
                    &[
                        0.25 + 0.125 * phase.sin(),
                        -0.3 + 0.0625 * (phase + 0.5).sin(),
                    ],
                );
            }
            p[0] += alpha * (1.0 - p[0]);
            p[1] += alpha * (p[0] - p[1]);
            let r = a.result();
            assert!((r.x.unwrap() + 0.25 * 0.5_f64.cos() * p[1]).abs() < 1e-10);
            assert!((r.y.unwrap() + 0.25 * 0.5_f64.sin() * p[1]).abs() < 1e-10);
            assert!((r.gain.unwrap() - p[1]).abs() < 1e-10);
            assert_eq!(r.processed_windows, block + 1);
            assert_eq!(r.sample_range, 0..(block + 1) * 1024);
            assert_eq!(
                r.state,
                if block < 23 {
                    State::Settling
                } else {
                    State::Valid
                }
            );
        }
        let held = a.result().clone();
        for i in 0..100 {
            a.push(24576 + i, &[0.1, 0.2]);
        }
        assert_eq!(
            *a.result(),
            held,
            "partial windows cannot update the filter"
        );
    }

    #[test]
    fn noisy_response_delayed_tone_and_same_channel_reference() {
        let cfg = settings();
        let mut a = Analyzer::new(cfg, 48000);
        let mut random = 19u64;
        let delay = 7.0;
        for n in 0..96000 {
            random ^= random << 13;
            random ^= random >> 7;
            random ^= random << 17;
            let noise = (random as f64 / u64::MAX as f64 - 0.5) * 0.004;
            let phase = TAU * 1000.0 * n as f64 / 48000.0;
            a.push(
                n,
                &[
                    0.125 * phase.sin(),
                    0.02 * (phase - TAU * 1000.0 * delay / 48000.0).sin() + noise,
                ],
            );
        }
        let r = a.result();
        assert_eq!(r.state, State::Valid);
        assert!((r.amplitude_peak.unwrap() - 0.02).abs() < 0.00015);
        assert!((r.phase_degrees.unwrap() + 52.5).abs() < 0.5);
        let mut same = Analyzer::new(
            Settings {
                response_channel: 0,
                ..cfg
            },
            48000,
        );
        for n in 0..48000 {
            same.push(n, &[0.125 * (TAU * 1000.0 * n as f64 / 48000.0).sin()]);
        }
        assert!((same.result().gain.unwrap() - 1.0).abs() < 1e-12);
        assert!(same.result().phase_degrees.unwrap().abs() < 1e-12);
    }
}
