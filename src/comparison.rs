//! Synchronous two-channel H1 comparison, independent of excitation and GUI.
//! Disjoint windows form finite arithmetic Welch batches (hop = N, no overlap).
//! Pxy = conj(X) Y; positive phase leads REF, positive delay lags REF.
#![warn(clippy::redundant_clone)]
use crate::{calibration, spectrum::Window};
use rustfft::{Fft, FftPlanner, num_complex::Complex};
use serde::{Deserialize, Serialize};
use std::{f64::consts::TAU, ops::Range, sync::Arc};

pub const SIZES: [usize; 5] = [1024, 2048, 4096, 8192, 16384];
/// Reject narrow-tone window leakage as a broadband delay reference.
pub const DELAY_RELATIVE_POWER_FLOOR: f64 = 0.1;

#[derive(Clone, Copy, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Settings {
    pub enabled: bool,
    pub reference_channel: usize,
    pub response_channel: usize,
    pub size: usize,
    pub window: Window,
    pub averages: usize,
    pub remove_dc: bool,
    /// Raw REF density threshold, before any channel calibration.
    pub reference_min_psd_fs2_hz: f64,
    pub minimum_coherence: f64,
    pub delay_band_hz: [f64; 2],
}
impl Default for Settings {
    fn default() -> Self {
        Self {
            enabled: false,
            reference_channel: 0,
            response_channel: 1,
            size: 4096,
            window: Window::Hann,
            averages: 8,
            remove_dc: true,
            reference_min_psd_fs2_hz: 1e-12,
            minimum_coherence: 0.8,
            delay_band_hz: [20.0, 20000.0],
        }
    }
}
impl Settings {
    pub fn validate(self, rate: u32) -> std::result::Result<(), String> {
        crate::audio::validate_sample_rate(rate)?;
        if self.reference_channel >= 16
            || self.response_channel >= 16
            || self.reference_channel == self.response_channel
            || !self.remove_dc
            || !SIZES.contains(&self.size)
            || !(2..=256).contains(&self.averages)
            || !self.reference_min_psd_fs2_hz.is_finite()
            || !(1e-30..=1.0).contains(&self.reference_min_psd_fs2_hz)
            || !self.minimum_coherence.is_finite()
            || !(0.0..=1.0).contains(&self.minimum_coherence)
            || self
                .delay_band_hz
                .iter()
                .any(|v| !v.is_finite() || *v < 0.0)
            || self.delay_band_hz[0] >= self.delay_band_hz[1]
            || self.delay_band_hz[1] > 384000.0
        {
            return Err("Invalid synchronous comparison settings".into());
        }
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum State {
    Disabled,
    Unavailable,
    Filling,
    Averaging,
    Valid,
    Missing,
    NonFinite,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum BinState {
    ReferenceLost,
    ResponseLost,
    Averaging,
    Incoherent,
    Valid,
}
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Bin {
    pub reference_psd: f64,
    pub response_psd: f64,
    pub cross_re: f64,
    pub cross_im: f64,
    pub coherence: Option<f64>,
    pub transfer_re: Option<f64>,
    pub transfer_im: Option<f64>,
    pub gain: Option<f64>,
    pub phase_lead_degrees: Option<f64>,
    /// Wrapped phase delay; ambiguous by integer multiples of 1/f.
    pub phase_delay_seconds: Option<f64>,
    pub state: BinState,
}
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Delay {
    /// Slope fit over the longest contiguous valid run in the requested band.
    pub seconds: f64,
    pub inclusive_bins: [usize; 2],
    pub phase_residual_rms_degrees: f64,
}
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Result {
    pub generation: u64,
    pub analysis_revision: u64,
    pub nominal_sample_rate_hz: u32,
    pub settings: Settings,
    pub state: State,
    pub sample_range: Range<u64>,
    pub latest_window: Range<u64>,
    pub input_end: u64,
    pub averaged_windows: usize,
    pub processed_windows: u64,
    pub missing_samples: u64,
    pub invalid_samples: u64,
    pub bins: Vec<Bin>,
    pub delay: Option<Delay>,
}
impl Result {
    pub fn empty(
        settings: Settings,
        rate: u32,
        generation: u64,
        revision: u64,
        channels: usize,
    ) -> Self {
        Self {
            generation,
            analysis_revision: revision,
            nominal_sample_rate_hz: rate,
            settings,
            state: if !settings.enabled {
                State::Disabled
            } else if settings.validate(rate).is_err()
                || settings.reference_channel >= channels
                || settings.response_channel >= channels
            {
                State::Unavailable
            } else {
                State::Filling
            },
            sample_range: 0..0,
            latest_window: 0..0,
            input_end: 0,
            averaged_windows: 0,
            processed_windows: 0,
            missing_samples: 0,
            invalid_samples: 0,
            bins: Vec::new(),
            delay: None,
        }
    }
    pub fn bin_width_hz(&self) -> f64 {
        self.nominal_sample_rate_hz as f64 / self.settings.size as f64
    }
    pub fn bin_at(&self, hz: f64) -> Option<(usize, &Bin)> {
        if !hz.is_finite() || !(0.0..=self.nominal_sample_rate_hz as f64 * 0.5).contains(&hz) {
            return None;
        }
        let k = (hz / self.bin_width_hz()).round() as usize;
        self.bins.get(k).map(|b| (k, b))
    }
}

pub struct Analyzer {
    result: Result,
    calibration: calibration::Set,
    data: Vec<[f64; 2]>,
    count: usize,
    start: u64,
    expected: Option<u64>,
    weights: Vec<f64>,
    normalization: f64,
    fft: Arc<dyn Fft<f64>>,
    spectra: [Vec<Complex<f64>>; 2],
    scratch: Vec<Complex<f64>>,
    sums: Vec<[f64; 4]>,
    batch_count: usize,
    batch_start: u64,
}
impl Analyzer {
    pub fn new(
        settings: Settings,
        rate: u32,
        generation: u64,
        revision: u64,
        channels: usize,
        calibration: calibration::Set,
    ) -> Self {
        let result = Result::empty(settings, rate, generation, revision, channels);
        let n = if settings.validate(rate).is_ok() {
            settings.size
        } else {
            1024
        };
        let fft = FftPlanner::new().plan_fft_forward(n);
        let weights: Vec<f64> = (0..n).map(|i| settings.window.weight(i, n)).collect();
        let normalization = 1.0 / (rate as f64 * weights.iter().map(|w| w * w).sum::<f64>());
        Self {
            result,
            calibration,
            data: vec![[0.0; 2]; n],
            count: 0,
            start: 0,
            expected: None,
            weights,
            normalization,
            scratch: vec![Complex::default(); fft.get_inplace_scratch_len()],
            fft,
            spectra: std::array::from_fn(|_| vec![Complex::default(); n]),
            sums: vec![[0.0; 4]; n / 2 + 1],
            batch_count: 0,
            batch_start: 0,
        }
    }
    pub fn result(&self) -> &Result {
        &self.result
    }
    fn active(&self) -> bool {
        !matches!(self.result.state, State::Disabled | State::Unavailable)
    }
    fn invalidate(&mut self, state: State) {
        self.count = 0;
        self.batch_count = 0;
        self.sums.fill([0.0; 4]);
        self.result.state = state;
        self.result.sample_range = 0..0;
        self.result.latest_window = 0..0;
        self.result.averaged_windows = 0;
        self.result.processed_windows = 0;
        self.result.bins.clear();
        self.result.delay = None;
    }
    pub fn gap_to(&mut self, next: u64) {
        if self.active()
            && let Some(end) = self.expected
            && end != next
        {
            self.result.missing_samples = self
                .result
                .missing_samples
                .saturating_add(next.saturating_sub(end));
            self.invalidate(State::Missing);
        }
        self.expected = Some(next);
        self.result.input_end = next;
    }
    pub fn push_pair(&mut self, sequence: u64, raw: [f64; 2]) {
        if !self.active() {
            return;
        }
        self.gap_to(sequence);
        self.expected = Some(sequence + 1);
        self.result.input_end = sequence + 1;
        if raw.iter().any(|v| !v.is_finite()) {
            self.result.invalid_samples = self.result.invalid_samples.saturating_add(1);
            self.invalidate(State::NonFinite);
            return;
        }
        if self.count == 0 {
            self.start = sequence;
        }
        self.data[self.count] = raw;
        self.count += 1;
        if self.count == self.data.len() {
            self.process();
            self.count = 0;
        }
    }
    fn process(&mut self) {
        let s = self.result.settings;
        let n = self.data.len();
        for ch in 0..2 {
            let mean = if s.remove_dc {
                self.data.iter().map(|p| p[ch] / n as f64).sum()
            } else {
                0.0
            };
            for (i, p) in self.data.iter().enumerate() {
                self.spectra[ch][i] = Complex::new((p[ch] - mean) * self.weights[i], 0.0);
            }
            self.fft
                .process_with_scratch(&mut self.spectra[ch], &mut self.scratch);
        }
        if self.batch_count == 0 {
            self.batch_start = self.start;
        }
        let gains = [s.reference_channel, s.response_channel]
            .map(|ch| self.calibration.get(ch).map_or(1.0, |c| c.gain()));
        for (k, sum) in self.sums.iter_mut().enumerate() {
            let scale = self.normalization * if k == 0 || k == n / 2 { 1.0 } else { 2.0 };
            let x = self.spectra[0][k] * gains[0];
            let y = self.spectra[1][k] * gains[1];
            let cross = x.conj() * y;
            let values = [x.norm_sqr(), y.norm_sqr(), cross.re, cross.im].map(|v| v * scale);
            for j in 0..4 {
                sum[j] += values[j] / s.averages as f64;
            }
        }
        if self.sums.iter().flatten().any(|v| !v.is_finite()) {
            self.result.invalid_samples = self.result.invalid_samples.saturating_add(n as u64);
            self.invalidate(State::NonFinite);
            return;
        }
        self.batch_count += 1;
        self.result.processed_windows += 1;
        // A completed batch remains visible while the next batch is assembled.
        // Stop preserves that exact contributing interval, never zero-pads a tail.
        if self.batch_count == s.averages {
            self.result.averaged_windows = s.averages;
            self.result.sample_range = self.batch_start..self.start + n as u64;
            self.result.latest_window = self.start..self.start + n as u64;
            self.result.bins = self
                .sums
                .iter()
                .enumerate()
                .map(|(k, p)| make_bin(*p, k, s, self.result.nominal_sample_rate_hz, gains[0]))
                .collect();
            self.result.delay = fit_delay(&self.result.bins, s, self.result.bin_width_hz());
            self.result.state = State::Valid;
            self.batch_count = 0;
            self.sums.fill([0.0; 4]);
        } else if self.result.bins.is_empty() {
            self.result.state = State::Averaging;
            // Incomplete batches deliberately carry no coherence or transfer values.
        }
    }
}

pub(crate) fn make_bin(p: [f64; 4], k: usize, s: Settings, rate: u32, reference_gain: f64) -> Bin {
    let [xx, yy, re, im] = p;
    let mut b = Bin {
        reference_psd: xx,
        response_psd: yy,
        cross_re: re,
        cross_im: im,
        coherence: None,
        transfer_re: None,
        transfer_im: None,
        gain: None,
        phase_lead_degrees: None,
        phase_delay_seconds: None,
        state: BinState::ReferenceLost,
    };
    let raw_reference = xx / reference_gain / reference_gain;
    if raw_reference < s.reference_min_psd_fs2_hz || xx <= 0.0 {
        return b;
    }
    if yy <= 0.0 {
        b.state = BinState::ResponseLost;
        b.transfer_re = Some(0.0);
        b.transfer_im = Some(0.0);
        b.gain = Some(0.0);
        return b;
    }
    // Divide before squaring to avoid a Pxx*Pyy overflow/underflow.
    let coherence = ((re / xx.sqrt()) / yy.sqrt())
        .hypot((im / xx.sqrt()) / yy.sqrt())
        .powi(2)
        .clamp(0.0, 1.0);
    b.coherence = Some(coherence);
    if coherence < s.minimum_coherence {
        b.state = BinState::Incoherent;
        return b;
    }
    let h = Complex::new(re / xx, im / xx);
    let gain = h.re.hypot(h.im);
    if !h.re.is_finite() || !h.im.is_finite() || !gain.is_finite() {
        b.state = BinState::Incoherent;
        return b;
    }
    b.transfer_re = Some(h.re);
    b.transfer_im = Some(h.im);
    b.gain = Some(gain);
    if gain == 0.0 {
        b.state = BinState::ResponseLost;
        return b;
    }
    b.state = BinState::Valid;
    b.phase_lead_degrees = Some(h.arg().to_degrees());
    if k > 0 && k < s.size / 2 {
        b.phase_delay_seconds = Some(-h.arg() / (TAU * k as f64 * rate as f64 / s.size as f64));
    }
    b
}

pub(crate) fn fit_delay(bins: &[Bin], s: Settings, df: f64) -> Option<Delay> {
    // A single sine and its window leakage must not become a broadband delay.
    // Require >=8 consecutive excited, coherent bins; never unwrap across holes.
    let mut best = 0..0;
    let mut run = 0..0;
    let reference_floor =
        bins.iter().map(|b| b.reference_psd).fold(0.0_f64, f64::max) * DELAY_RELATIVE_POWER_FLOOR;
    for (k, b) in bins.iter().enumerate() {
        let f = k as f64 * df;
        if k > 0
            && k < s.size / 2
            && b.state == BinState::Valid
            && b.reference_psd >= reference_floor
            && f >= s.delay_band_hz[0]
            && f <= s.delay_band_hz[1]
        {
            if run.is_empty() {
                run = k..k + 1;
            } else {
                run.end = k + 1;
            }
            if run.len() > best.len() {
                best = run.clone();
            }
        } else {
            run = 0..0;
        }
    }
    if best.len() < 8 {
        return None;
    }
    let mut points = Vec::with_capacity(best.len());
    let mut previous = bins[best.start].phase_lead_degrees?.to_radians();
    let mut unwrapped = previous;
    for k in best.clone() {
        let p = bins[k].phase_lead_degrees?.to_radians();
        if k != best.start {
            unwrapped +=
                (p - previous + std::f64::consts::PI).rem_euclid(TAU) - std::f64::consts::PI;
        }
        previous = p;
        points.push(((k - best.start) as f64 * df, unwrapped, bins[k].coherence?));
    }
    let weight = points.iter().map(|p| p.2).sum::<f64>();
    let mx = points.iter().map(|p| p.0 * p.2).sum::<f64>() / weight;
    let my = points.iter().map(|p| p.1 * p.2).sum::<f64>() / weight;
    let variance = points.iter().map(|p| p.2 * (p.0 - mx).powi(2)).sum::<f64>();
    let slope = points
        .iter()
        .map(|p| p.2 * (p.0 - mx) * (p.1 - my))
        .sum::<f64>()
        / variance;
    let residual = (points
        .iter()
        .map(|p| p.2 * (p.1 - my - slope * (p.0 - mx)).powi(2))
        .sum::<f64>()
        / weight)
        .sqrt()
        .to_degrees();
    let seconds = -slope / TAU;
    (seconds.is_finite() && residual.is_finite()).then_some(Delay {
        seconds,
        inclusive_bins: [best.start, best.end - 1],
        phase_residual_rms_degrees: residual,
    })
}

#[cfg(test)]
mod tests;
