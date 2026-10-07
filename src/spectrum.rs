//! One-sided bin amplitude (1 FS sine peak = 0 dBFS) or power spectral
//! density (FS²/Hz). Numeric results and band integration stay f64.
use crate::{
    channel::ChannelId,
    signal::{History, Line},
};
use rustfft::{Fft, FftNum, FftPlanner, num_complex::Complex, num_traits::ToPrimitive};
use std::{f64::consts::TAU, ops::Range, sync::Arc};

pub const FFT_SIZES: [usize; 6] = [1024, 2048, 4096, 8192, 16384, 32768];
pub const DB_MIN: f32 = -180.0;

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum Window {
    Rectangular,
    #[default]
    Hann,
    BlackmanHarris,
}

impl Window {
    pub fn name(self) -> &'static str {
        match self {
            Self::Rectangular => "Rectangular",
            Self::Hann => "Hann",
            Self::BlackmanHarris => "Blackman-Harris",
        }
    }

    fn weight(self, index: usize, size: usize) -> f64 {
        let phase = TAU * index as f64 / size as f64;
        match self {
            Self::Rectangular => 1.0,
            Self::Hann => 0.5 - 0.5 * phase.cos(),
            Self::BlackmanHarris => {
                0.35875 - 0.48829 * phase.cos() + 0.14128 * (2.0 * phase).cos()
                    - 0.01168 * (3.0 * phase).cos()
            }
        }
    }
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum Precision {
    F32,
    #[default]
    F64,
}

impl Precision {
    pub fn name(self) -> &'static str {
        match self {
            Self::F64 => "64-bit",
            Self::F32 => "32-bit (fast FFT)",
        }
    }
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum Quantity {
    #[default]
    Amplitude,
    Psd,
}

impl Quantity {
    pub fn name(self) -> &'static str {
        match self {
            Self::Amplitude => "Bin amplitude",
            Self::Psd => "Power spectral density",
        }
    }

    pub fn db_unit(self) -> &'static str {
        match self {
            Self::Amplitude => "dBFS",
            Self::Psd => "dB re FS²/Hz",
        }
    }

    pub fn linear_unit(self) -> &'static str {
        match self {
            Self::Amplitude => "FS peak",
            Self::Psd => "FS²/Hz",
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Settings {
    pub quantity: Quantity,
    pub size: usize,
    pub window: Window,
    /// Exponential power average, alpha = 1 / averages; not a batch count.
    pub averages: u32,
    pub remove_dc: bool,
    /// Instrument-local FFT precision; core samples and averaging stay f64.
    pub precision: Precision,
}

impl Default for Settings {
    fn default() -> Self {
        Self {
            quantity: Quantity::Amplitude,
            size: 8192,
            window: Window::Hann,
            averages: 4,
            remove_dc: true,
            precision: Precision::F64,
        }
    }
}

#[derive(Clone, Copy, Debug)]
pub struct Peak {
    pub frequency: f64,
    pub level_db: f64,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct WindowInfo {
    pub start: u64,
    pub end: u64,
    pub sample_rate: u32,
    pub channel: ChannelId,
    pub settings: Settings,
}

#[derive(Clone, Copy, Debug)]
pub struct CursorReading {
    pub window: WindowInfo,
    pub average: AverageInfo,
    pub frequency_hz: f64,
    /// FS peak for amplitude, FS²/Hz for PSD; never reconstructed from f32.
    pub value: f64,
    pub level_db: f64,
    pub hold_level_db: f64,
}

/// Envelope of contributing sample windows, not a claim of uniform weighting
/// or continuous coverage in Latest mode. First window initializes the EMA;
/// subsequent windows use alpha = 1 / settings.averages.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct AverageInfo {
    pub start: u64,
    pub end: u64,
    pub updates: u64,
}

#[derive(Clone, Copy, Debug)]
pub struct BandReading {
    pub window: WindowInfo,
    pub average: AverageInfo,
    pub requested_hz: [f64; 2],
    pub first_bin: usize,
    pub last_bin: usize,
    pub first_hz: f64,
    pub last_hz: f64,
    pub power_fs2: f64,
    pub rms_fs: f64,
}

/// Zero power is -infinity in numeric results. Only drawing has a dB floor.
fn level_db(power: f64) -> f64 {
    10.0 * power.log10()
}

// Both the analyzer and its immutable output expose identical numeric reads.
macro_rules! numeric_reads {
    () => {
        /// Squared peak-bin amplitude (FS²) or density (FS²/Hz), per settings.
        pub fn power(&self) -> &[f64] {
            &self.power
        }

        /// Maximum of the averaged linear values since reset/Clear hold.
        pub fn hold_power(&self) -> &[f64] {
            &self.hold_power
        }

        pub fn average(&self) -> Option<AverageInfo> {
            self.is_ready().then_some(self.average)
        }

        pub fn cursor(&self, frequency_hz: f64) -> Option<CursorReading> {
            let window = self.window()?;
            let bin =
                crate::cursor::nearest_bin(frequency_hz, window.settings.size, window.sample_rate)?;
            Some(CursorReading {
                window,
                average: self.average,
                frequency_hz: bin as f64 * window.sample_rate as f64 / window.settings.size as f64,
                value: match self.settings.quantity {
                    Quantity::Amplitude => self.power[bin].sqrt(),
                    Quantity::Psd => self.power[bin],
                },
                level_db: level_db(self.power[bin]),
                hold_level_db: level_db(self.hold_power[bin]),
            })
        }

        /// Whole-bin sum of averaged PSD * Fs/N. Both requested bounds are
        /// inclusive bin centres. DC/Nyquist receive full bin weight, so the
        /// full-band sum obeys discrete Parseval, without trapezoidal weighting.
        /// No clipping, fractional-bin interpolation, or amplitude-bin summing.
        pub fn band(&self, min_hz: f64, max_hz: f64) -> Option<BandReading> {
            let window = self.window()?;
            if self.settings.quantity != Quantity::Psd
                || !min_hz.is_finite()
                || !max_hz.is_finite()
                || min_hz < 0.0
                || max_hz < min_hz
                || max_hz > window.sample_rate as f64 * 0.5
            {
                return None;
            }
            let bin_hz = window.sample_rate as f64 / window.settings.size as f64;
            let first_bin = (min_hz / bin_hz).ceil() as usize;
            let last_bin = (max_hz / bin_hz).floor() as usize;
            if first_bin > last_bin || last_bin >= self.power.len() {
                return None;
            }
            let power_fs2 = self.power[first_bin..=last_bin].iter().sum::<f64>() * bin_hz;
            Some(BandReading {
                window,
                average: self.average,
                requested_hz: [min_hz, max_hz],
                first_bin,
                last_bin,
                first_hz: first_bin as f64 * bin_hz,
                last_hz: last_bin as f64 * bin_hz,
                power_fs2,
                rms_fs: power_fs2.sqrt(),
            })
        }

        /// Strongest numeric bin, excluding DC. No sub-bin accuracy is claimed.
        pub fn peak(&self, view: View) -> Option<Peak> {
            self.window()?;
            let bin_hz = self.sample_rate as f64 / self.settings.size as f64;
            self.power
                .iter()
                .enumerate()
                .skip(1)
                .filter(|(bin, _)| {
                    let hz = *bin as f64 * bin_hz;
                    hz >= view.min_hz as f64 && hz <= view.max_hz as f64
                })
                .max_by(|a, b| a.1.total_cmp(b.1))
                .filter(|(_, power)| **power > 0.0)
                .map(|(bin, power)| Peak {
                    frequency: bin as f64 * bin_hz,
                    level_db: level_db(*power),
                })
        }
    };
}

/// Immutable measurement output copied into a bounded display snapshot. FFT
/// workspaces stay on the measurement worker; precision values stay f64.
#[derive(Clone)]
pub struct Result {
    settings: Settings,
    sample_rate: u32,
    rbw: f64,
    power: Vec<f64>,
    hold_power: Vec<f64>,
    average: AverageInfo,
    db: Vec<f32>,
    hold: Vec<f32>,
    last_end: Option<u64>,
    last_channel: usize,
}

impl Result {
    pub fn empty(settings: Settings, sample_rate: u32) -> Self {
        let sum: f64 = (0..settings.size)
            .map(|i| settings.window.weight(i, settings.size))
            .sum();
        let squares: f64 = (0..settings.size)
            .map(|i| settings.window.weight(i, settings.size).powi(2))
            .sum();
        Self {
            settings,
            sample_rate,
            rbw: sample_rate as f64 * squares / sum.powi(2),
            power: vec![0.0; settings.size / 2 + 1],
            hold_power: vec![0.0; settings.size / 2 + 1],
            average: AverageInfo::default(),
            db: vec![DB_MIN; settings.size / 2 + 1],
            hold: vec![DB_MIN; settings.size / 2 + 1],
            last_end: None,
            last_channel: 0,
        }
    }

    numeric_reads!();

    pub fn clear_hold(&mut self) {
        self.hold_power.copy_from_slice(&self.power);
        self.hold.copy_from_slice(&self.db);
    }
    pub fn settings(&self) -> Settings {
        self.settings
    }
    pub fn bin_hz(&self) -> f32 {
        self.sample_rate as f32 / self.settings.size as f32
    }
    pub fn rbw_hz(&self) -> f64 {
        self.rbw
    }
    pub fn nyquist(&self) -> f32 {
        self.sample_rate as f32 * 0.5
    }
    pub fn is_ready(&self) -> bool {
        self.last_end.is_some()
    }
    pub fn db(&self) -> &[f32] {
        &self.db
    }
    pub fn hold(&self) -> &[f32] {
        &self.hold
    }

    /// Metadata belongs to the displayed result, including when next-run
    /// settings are edited while input is stopped. Averaged values describe
    /// the accumulated power; this is the latest contributing window.
    pub fn window(&self) -> Option<WindowInfo> {
        let end = self.last_end?;
        Some(WindowInfo {
            start: end - self.settings.size as u64,
            end,
            sample_rate: self.sample_rate,
            channel: self.last_channel,
            settings: self.settings,
        })
    }
}

/// Shared rendering access for an analyzer or its published result.
pub trait Trace {
    fn is_ready(&self) -> bool;
    fn bin_hz(&self) -> f32;
    fn db(&self) -> &[f32];
    fn hold(&self) -> &[f32];
}

macro_rules! impl_trace {
    ($type:ty) => {
        impl Trace for $type {
            fn is_ready(&self) -> bool {
                self.is_ready()
            }
            fn bin_hz(&self) -> f32 {
                self.bin_hz()
            }
            fn db(&self) -> &[f32] {
                self.db()
            }
            fn hold(&self) -> &[f32] {
                self.hold()
            }
        }
    };
}
impl_trace!(Result);
impl_trace!(Analyzer);

/// FFT plan, work buffers and output storage are allocated only at configuration
/// changes. Acquisition never calls this analyzer. Analyze the newest complete
/// window, at most once per quarter-window of new samples.
pub struct Analyzer {
    settings: Settings,
    sample_rate: u32,
    transform: Transform,
    samples: Vec<f64>,
    weights: Vec<f64>,
    rbw: f64,
    power: Vec<f64>,
    hold_power: Vec<f64>,
    average: AverageInfo,
    db: Vec<f32>,
    hold: Vec<f32>,
    last_end: Option<u64>,
    last_channel: usize,
}

enum Transform {
    F64(Workspace<f64>),
    F32(Workspace<f32>),
}

struct Workspace<T: FftNum> {
    fft: Arc<dyn Fft<T>>,
    buffer: Vec<Complex<T>>,
    scratch: Vec<Complex<T>>,
    twiddles: Vec<Complex<T>>,
}

impl<T: FftNum + ToPrimitive> Workspace<T> {
    fn new(size: usize) -> Self {
        // Pack even/odd real samples into one half-size complex FFT. Recover
        // only the one-sided bins used by these instruments.
        let fft = FftPlanner::<T>::new().plan_fft_forward(size / 2);
        Self {
            buffer: vec![Complex::new(T::zero(), T::zero()); size / 2],
            scratch: vec![Complex::new(T::zero(), T::zero()); fft.get_inplace_scratch_len()],
            twiddles: (0..=size / 2)
                .map(|bin| {
                    let phase = -TAU * bin as f64 / size as f64;
                    // -i/2 * exp(-i * 2pi * k/N)
                    Complex::new(
                        T::from_f64(0.5 * phase.sin()).unwrap(),
                        T::from_f64(-0.5 * phase.cos()).unwrap(),
                    )
                })
                .collect(),
            fft,
        }
    }

    fn process(
        &mut self,
        samples: &[f64],
        weights: &[f64],
        mean: f64,
        power: &mut [f64],
        alpha: f64,
        factors: [f64; 2],
    ) {
        // DC subtraction precedes the optional narrowing, so a small AC signal
        // on a large DC offset is not erased by quantizing the raw input.
        for ((value, samples), weights) in self
            .buffer
            .iter_mut()
            .zip(samples.as_chunks::<2>().0)
            .zip(weights.as_chunks::<2>().0)
        {
            *value = Complex::new(
                T::from_f64((samples[0] - mean) * weights[0]).unwrap(),
                T::from_f64((samples[1] - mean) * weights[1]).unwrap(),
            );
        }
        self.fft
            .process_with_scratch(&mut self.buffer, &mut self.scratch);
        let nyquist = samples.len() / 2;
        let half = T::from_f64(0.5).unwrap();
        for (bin, averaged) in power.iter_mut().enumerate() {
            let value = if bin == 0 {
                Complex::new(self.buffer[0].re + self.buffer[0].im, T::zero())
            } else if bin == nyquist {
                Complex::new(self.buffer[0].re - self.buffer[0].im, T::zero())
            } else {
                let a = self.buffer[bin];
                let b = self.buffer[nyquist - bin].conj();
                (a + b) * half + self.twiddles[bin] * (a - b)
            };
            let endpoint = bin == 0 || bin == nyquist;
            let factor = factors[usize::from(!endpoint)];
            // Optional f32 FFT must not square weak bins in f32 and underflow
            // before the f64 average/integration sees them.
            let current =
                (value.re.to_f64().unwrap().powi(2) + value.im.to_f64().unwrap().powi(2)) * factor;
            *averaged = if alpha == 1.0 {
                current
            } else {
                *averaged + alpha * (current - *averaged)
            };
        }
    }
}

impl Analyzer {
    pub fn new(settings: Settings, sample_rate: u32) -> Self {
        assert!(FFT_SIZES.contains(&settings.size));
        assert!(sample_rate > 0 && settings.averages > 0);
        let mut weights: Vec<_> = (0..settings.size)
            .map(|i| settings.window.weight(i, settings.size))
            .collect();
        let weight_sum = weights.iter().sum::<f64>();
        let rbw = sample_rate as f64 * weights.iter().map(|v| v * v).sum::<f64>()
            / (weight_sum * weight_sum);
        // Normalize once at configuration time instead of dividing every bin.
        for weight in &mut weights {
            *weight /= weight_sum;
        }
        Self {
            samples: vec![0.0; settings.size],
            transform: match settings.precision {
                Precision::F64 => Transform::F64(Workspace::new(settings.size)),
                Precision::F32 => Transform::F32(Workspace::new(settings.size)),
            },
            power: vec![0.0; settings.size / 2 + 1],
            hold_power: vec![0.0; settings.size / 2 + 1],
            average: AverageInfo::default(),
            db: vec![DB_MIN; settings.size / 2 + 1],
            hold: vec![DB_MIN; settings.size / 2 + 1],
            settings,
            sample_rate,
            weights,
            rbw,
            last_end: None,
            last_channel: 0,
        }
    }

    /// Reuse the result's allocation on each publication.
    pub fn copy_result(&self, result: &mut Result) {
        result.settings = self.settings;
        result.sample_rate = self.sample_rate;
        result.rbw = self.rbw;
        result.power.clone_from(&self.power);
        result.hold_power.clone_from(&self.hold_power);
        result.average = self.average;
        result.db.clone_from(&self.db);
        result.hold.clone_from(&self.hold);
        result.last_end = self.last_end;
        result.last_channel = self.last_channel;
    }

    numeric_reads!();

    pub fn settings(&self) -> Settings {
        self.settings
    }
    pub fn bin_hz(&self) -> f32 {
        self.sample_rate as f32 / self.settings.size as f32
    }
    pub fn rbw_hz(&self) -> f64 {
        self.rbw
    }
    pub fn nyquist(&self) -> f32 {
        self.sample_rate as f32 * 0.5
    }
    pub fn is_ready(&self) -> bool {
        self.last_end.is_some()
    }
    pub fn db(&self) -> &[f32] {
        &self.db
    }
    pub fn hold(&self) -> &[f32] {
        &self.hold
    }

    /// Metadata belongs to the displayed result, including when next-run
    /// settings are edited while input is stopped. Averaged values describe
    /// the accumulated power; this is the latest contributing window.
    pub fn window(&self) -> Option<WindowInfo> {
        let end = self.last_end?;
        Some(WindowInfo {
            start: end - self.settings.size as u64,
            end,
            sample_rate: self.sample_rate,
            channel: self.last_channel,
            settings: self.settings,
        })
    }

    pub fn reset(&mut self) {
        self.last_end = None;
        self.average = AverageInfo::default();
        self.power.fill(0.0);
        self.db.fill(DB_MIN);
        self.clear_hold();
    }

    pub fn clear_hold(&mut self) {
        // Restart from the currently displayed trace, including while paused.
        self.hold_power.copy_from_slice(&self.power);
        self.hold.copy_from_slice(&self.db);
    }

    pub fn update(&mut self, history: &History, channel: usize) -> bool {
        let end = history.range().end;
        if end - history.contiguous_range().start < self.settings.size as u64
            || channel >= history.channels()
        {
            self.reset();
            return false;
        }
        if channel != self.last_channel {
            self.reset();
        }
        if self.last_end.is_some_and(|previous| {
            end >= previous && end - previous < (self.settings.size / 4) as u64
        }) {
            return false;
        }
        let start = end - self.settings.size as u64;
        self.update_window(history, start..end, channel)
    }

    /// Analyze an explicit complete window without the snapshot hop gate.
    /// Continuous STFT owns scheduling; FFT buffers and normalization are shared.
    pub fn update_window(&mut self, history: &History, range: Range<u64>, channel: usize) -> bool {
        if channel >= history.channels()
            || range.end.checked_sub(range.start) != Some(self.settings.size as u64)
            || range.start < history.range().start
            || range.end > history.range().end
        {
            return false;
        }
        if channel != self.last_channel {
            self.reset();
        }
        for (value, frame) in self.samples.iter_mut().zip(history.samples(range.clone())) {
            let Some(frame) = frame else {
                self.reset();
                return false;
            };
            *value = frame[channel];
        }
        self.process_window(range.end, channel);
        true
    }

    /// Direct f64 input without requiring a capture history.
    /// `end` is the exclusive source sample index of this complete window.
    pub fn update_samples(&mut self, samples: &[f64], end: u64) -> bool {
        if samples.len() != self.settings.size || end < samples.len() as u64 {
            return false;
        }
        if self.last_channel != 0 {
            self.reset();
        }
        self.samples.copy_from_slice(samples);
        self.process_window(end, 0);
        true
    }

    fn process_window(&mut self, end: u64, channel: usize) {
        let mean = if self.settings.remove_dc {
            self.samples.iter().sum::<f64>() / self.settings.size as f64
        } else {
            0.0
        };
        let alpha = if self.last_end.is_none() {
            1.0
        } else {
            1.0 / self.settings.averages as f64
        };
        let factors = match self.settings.quantity {
            Quantity::Amplitude => [1.0, 4.0],
            Quantity::Psd => [1.0 / self.rbw, 2.0 / self.rbw],
        };
        match &mut self.transform {
            Transform::F64(workspace) => workspace.process(
                &self.samples,
                &self.weights,
                mean,
                &mut self.power,
                alpha,
                factors,
            ),
            Transform::F32(workspace) => workspace.process(
                &self.samples,
                &self.weights,
                mean,
                &mut self.power,
                alpha,
                factors,
            ),
        }
        for bin in 0..self.db.len() {
            self.hold_power[bin] = self.hold_power[bin].max(self.power[bin]);
            self.db[bin] = level_db(self.power[bin]).max(DB_MIN as f64) as f32;
            self.hold[bin] = level_db(self.hold_power[bin]).max(DB_MIN as f64) as f32;
        }
        if self.last_end.is_none() || self.settings.averages == 1 {
            self.average.start = end - self.settings.size as u64;
        }
        self.average.end = end;
        self.average.updates += 1;
        self.last_end = Some(end);
        self.last_channel = channel;
    }
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum FrequencyScale {
    Linear,
    #[default]
    Log,
}

#[derive(Clone, Copy, Debug)]
pub struct View {
    pub scale: FrequencyScale,
    pub min_hz: f32,
    pub max_hz: f32,
    pub floor_db: f32,
    pub ceiling_db: f32,
}

impl View {
    pub fn full(sample_rate: u32, scale: FrequencyScale, floor_db: f32) -> Self {
        Self {
            scale,
            min_hz: if scale == FrequencyScale::Log {
                20.0
            } else {
                0.0
            },
            max_hz: sample_rate as f32 * 0.5,
            floor_db,
            ceiling_db: 6.0,
        }
    }

    pub fn x(self, hz: f32) -> f32 {
        match self.scale {
            FrequencyScale::Linear => (hz - self.min_hz) / (self.max_hz - self.min_hz),
            FrequencyScale::Log => (hz / self.min_hz).ln() / (self.max_hz / self.min_hz).ln(),
        }
    }

    pub fn frequency(self, x: f32) -> f32 {
        match self.scale {
            FrequencyScale::Linear => self.min_hz + x * (self.max_hz - self.min_hz),
            FrequencyScale::Log => self.min_hz * (self.max_hz / self.min_hz).powf(x),
        }
    }

    #[cfg(test)]
    fn y(self, db: f32) -> f32 {
        (self.ceiling_db - db) / (self.ceiling_db - self.floor_db)
    }
}

/// Cached bin-to-pixel projection, independent of the GUI and FFT precision.
/// Only frequency axis, sample rate, FFT length or width changes rebuild it.
#[derive(Default)]
pub struct LineBuilder {
    key: Option<(FrequencyScale, f32, f32, f32, usize, usize)>,
    coordinates: Vec<(usize, f32, usize)>,
}

impl LineBuilder {
    /// Preserve both extrema in each physical pixel column, including narrow
    /// peaks on a log axis. New power/hold values never invalidate the x axis.
    pub fn build(
        &mut self,
        analyzer: &impl Trace,
        view: View,
        pixels: usize,
        show_hold: bool,
        output: &mut Vec<Line>,
    ) {
        output.clear();
        if !analyzer.is_ready() || pixels == 0 {
            return;
        }
        let bin_hz = analyzer.bin_hz();
        let key = (
            view.scale,
            view.min_hz,
            view.max_hz,
            bin_hz,
            analyzer.db().len(),
            pixels,
        );
        if self.key != Some(key) {
            self.coordinates.clear();
            let inverse_span = 1.0 / (view.max_hz - view.min_hz);
            let inverse_log_span = 1.0 / (view.max_hz / view.min_hz).ln();
            for bin in 0..analyzer.db().len() {
                let hz = bin as f32 * bin_hz;
                if hz < view.min_hz || hz > view.max_hz {
                    continue;
                }
                let x = match view.scale {
                    FrequencyScale::Linear => (hz - view.min_hz) * inverse_span,
                    FrequencyScale::Log => (hz / view.min_hz).ln() * inverse_log_span,
                };
                let column = ((x * pixels as f32) as usize).min(pixels - 1);
                self.coordinates.push((bin, x, column));
            }
            self.key = Some(key);
        }
        let inverse_db_span = 1.0 / (view.ceiling_db - view.floor_db);
        for (channel, values) in [analyzer.db(), analyzer.hold()].into_iter().enumerate() {
            if channel == 1 && !show_hold {
                break;
            }
            let mut previous = None;
            let mut bucket: Option<Bucket> = None;
            let mut flush = |Bucket {
                                 first,
                                 last,
                                 min_y,
                                 max_y,
                                 ..
                             }: Bucket| {
                if let Some(a) = previous {
                    output.push(Line {
                        a,
                        b: first,
                        channel,
                    });
                }
                if min_y < max_y {
                    let x = (first[0] + last[0]) * 0.5;
                    output.push(Line {
                        a: [x, min_y],
                        b: [x, max_y],
                        channel,
                    });
                }
                previous = Some(last);
            };
            for &(bin, x, column) in &self.coordinates {
                let point = [x, (view.ceiling_db - values[bin]) * inverse_db_span];
                if let Some(current) = bucket.as_mut()
                    && current.column == column
                {
                    current.last = point;
                    current.min_y = current.min_y.min(point[1]);
                    current.max_y = current.max_y.max(point[1]);
                    continue;
                }
                if let Some(completed) = bucket.take() {
                    flush(completed);
                }
                bucket = Some(Bucket {
                    column,
                    first: point,
                    last: point,
                    min_y: point[1],
                    max_y: point[1],
                });
            }
            if let Some(completed) = bucket {
                flush(completed);
            }
        }
    }
}

/// One-shot projection for callers that do not retain display state.
pub fn build_lines(
    analyzer: &impl Trace,
    view: View,
    pixels: usize,
    show_hold: bool,
    output: &mut Vec<Line>,
) {
    LineBuilder::default().build(analyzer, view, pixels, show_hold, output);
}

struct Bucket {
    column: usize,
    first: [f32; 2],
    last: [f32; 2],
    min_y: f32,
    max_y: f32,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn missing_frames_reject_fft_windows_and_reset_averages_before_recovery() {
        for precision in [Precision::F64, Precision::F32] {
            let mut history = History::new(4096);
            let mut analyzer = Analyzer::new(
                Settings {
                    size: 1024,
                    averages: 4,
                    precision,
                    ..Settings::default()
                },
                48000,
            );
            let sample = |i: u64, amplitude: f64| {
                amplitude * (std::f64::consts::TAU * 32.0 * i as f64 / 1024.0).cos()
            };
            for i in 0..1024 {
                history.push_at(i, [sample(i, 0.5), 0.0]);
            }
            assert!(analyzer.update(&history, 0));
            assert!((analyzer.db()[32] + 6.0206).abs() < 0.003);
            // Even inside the snapshot hop gate, a loss invalidates the old result.
            history.push_at(1025, [sample(1025, 0.25), 0.0]);
            assert!(!analyzer.update(&history, 0));
            assert!(analyzer.window().is_none());
            assert!(history.get(1023).is_some());
            assert!(history.get(1024).is_none());
            assert!(!analyzer.update_window(&history, 2..1026, 0));
            assert!(analyzer.window().is_none());
            for i in 1026..2049 {
                history.push_at(i, [sample(i, 0.25), 0.0]);
            }
            assert!(analyzer.update(&history, 0));
            assert_eq!(analyzer.window().unwrap().start, 1025);
            assert!((analyzer.db()[32] + 12.0412).abs() < 0.003);
            assert_eq!(analyzer.hold()[32], analyzer.db()[32]);
        }
    }

    #[test]
    fn cursor_reports_actual_channel_window_and_average_without_reprocessing() {
        let settings = Settings {
            size: 1024,
            averages: 4,
            ..Settings::default()
        };
        let mut history = History::with_channels(2048, 16);
        let origin = 1_u64 << 54;
        for i in 0..2048 {
            let mut frame = [0.0; 16];
            frame[15] = 0.5 * (TAU * 32.0 * i as f64 / 1024.0).sin();
            history.push_at(origin + i, frame);
        }
        let mut analyzer = Analyzer::new(settings, 48000);
        assert!(analyzer.update(&history, 15));
        let held = analyzer.db().to_vec();
        let reading = analyzer.cursor(1501.0).unwrap();
        assert_eq!(reading.frequency_hz, 1500.0);
        assert!((reading.level_db + 6.0206).abs() < 0.001);
        assert_eq!(reading.window.start, origin + 1024);
        assert_eq!(reading.window.end, origin + 2048);
        assert_eq!(reading.window.channel, 15);
        assert_eq!(reading.window.settings, settings);
        for hz in [0.0, 200.0, 1000.0, 24000.0] {
            assert!(analyzer.cursor(hz).is_some());
        }
        assert_eq!(analyzer.db(), held);
        analyzer.reset();
        assert!(analyzer.cursor(1500.0).is_none());
    }
    use std::f64::consts::TAU;

    #[test]
    fn psd_full_band_obeys_parseval_for_off_bin_tones_dc_nyquist_and_transients() {
        for size in FFT_SIZES {
            let samples: Vec<_> = (0..size)
                .map(|i| {
                    let phase = TAU * i as f64 / size as f64;
                    0.125
                        + 0.4 * (31.5 * phase).cos()
                        + 0.2 * (79.0 * phase).sin()
                        + if i % 2 == 0 { 0.05 } else { -0.05 }
                        + if i == size / 3 { 0.8 } else { 0.0 }
                })
                .collect();
            for window in [Window::Rectangular, Window::Hann, Window::BlackmanHarris] {
                for remove_dc in [false, true] {
                    let mean = if remove_dc {
                        samples.iter().sum::<f64>() / size as f64
                    } else {
                        0.0
                    };
                    let mut energy = 0.0;
                    let mut weight_energy = 0.0;
                    for (i, &sample) in samples.iter().enumerate() {
                        let w2 = window.weight(i, size).powi(2);
                        energy += (sample - mean).powi(2) * w2;
                        weight_energy += w2;
                    }
                    let expected = energy / weight_energy;
                    for precision in [Precision::F64, Precision::F32] {
                        let settings = Settings {
                            quantity: Quantity::Psd,
                            size,
                            window,
                            remove_dc,
                            precision,
                            averages: 1,
                        };
                        let mut analyzer = Analyzer::new(settings, 48000);
                        assert!(analyzer.update_samples(&samples, size as u64));
                        let band = analyzer.band(0.0, 24000.0).unwrap();
                        let tolerance = if precision == Precision::F64 {
                            2e-13
                        } else {
                            5e-8
                        };
                        assert!(
                            (band.power_fs2 - expected).abs() < tolerance,
                            "{size} {window:?} {precision:?} DC={remove_dc}"
                        );
                        assert!((band.rms_fs.powi(2) - band.power_fs2).abs() < 1e-15);
                        assert_eq!((band.first_bin, band.last_bin), (0, size / 2));
                    }
                }
            }
        }
    }

    #[test]
    fn psd_tone_band_power_is_invariant_under_size_window_and_rate() {
        for size in FFT_SIZES {
            for sample_rate in [48000, 96000] {
                let bin_hz = sample_rate as f64 / size as f64;
                let samples: Vec<_> = (0..size)
                    .map(|i| {
                        let phase = TAU * i as f64 / size as f64;
                        0.5 * (31.0 * phase).cos()
                            + 0.25 * (79.0 * phase).sin()
                            + 0.125
                            + if i % 2 == 0 { 0.0625 } else { -0.0625 }
                    })
                    .collect();
                for window in [Window::Rectangular, Window::Hann, Window::BlackmanHarris] {
                    let mut analyzer = Analyzer::new(
                        Settings {
                            quantity: Quantity::Psd,
                            size,
                            window,
                            remove_dc: false,
                            averages: 1,
                            ..Settings::default()
                        },
                        sample_rate,
                    );
                    assert!(analyzer.update_samples(&samples, size as u64));
                    assert!(
                        (analyzer
                            .band(27.0 * bin_hz, 35.0 * bin_hz)
                            .unwrap()
                            .power_fs2
                            - 0.125)
                            .abs()
                            < 1e-13
                    );
                    assert!(
                        (analyzer
                            .band(75.0 * bin_hz, 83.0 * bin_hz)
                            .unwrap()
                            .power_fs2
                            - 0.03125)
                            .abs()
                            < 1e-13
                    );
                    assert!(
                        (analyzer
                            .band(0.0, sample_rate as f64 * 0.5)
                            .unwrap()
                            .power_fs2
                            - 0.17578125)
                            .abs()
                            < 1e-13
                    );
                    assert!(
                        (analyzer.cursor(31.0 * bin_hz).unwrap().value - 0.125 / analyzer.rbw_hz())
                            .abs()
                            < 1e-14
                    );
                }
            }
        }
    }

    #[test]
    fn psd_band_uses_inclusive_centres_and_full_dc_nyquist_weights() {
        let mut analyzer = Analyzer::new(
            Settings {
                quantity: Quantity::Psd,
                size: 1024,
                window: Window::Rectangular,
                remove_dc: false,
                averages: 1,
                ..Settings::default()
            },
            48000,
        );
        assert!(analyzer.band(0.0, 24000.0).is_none());
        assert!(analyzer.update(&tone(1024, 512, 0.25, 0.5), 0));
        assert!((analyzer.band(0.0, 0.0).unwrap().power_fs2 - 0.25).abs() < 1e-14);
        assert!((analyzer.band(24000.0, 24000.0).unwrap().power_fs2 - 0.0625).abs() < 1e-14);
        assert!((analyzer.band(0.0, 24000.0).unwrap().power_fs2 - 0.3125).abs() < 1e-14);
        let bin_hz = 48000.0 / 1024.0;
        assert!(analyzer.band(0.1 * bin_hz, 0.9 * bin_hz).is_none());
        for bounds in [
            [-1.0, 24000.0],
            [0.0, 24001.0],
            [100.0, 1.0],
            [f64::NAN, 10.0],
            [0.0, f64::INFINITY],
        ] {
            assert!(analyzer.band(bounds[0], bounds[1]).is_none());
        }
        let selected = analyzer.band(bin_hz, 24000.0 - bin_hz).unwrap();
        assert_eq!((selected.first_bin, selected.last_bin), (1, 511));
        assert_eq!(selected.power_fs2, 0.0);
        let mut amplitude = Analyzer::new(
            Settings {
                size: 1024,
                ..Settings::default()
            },
            48000,
        );
        amplitude.update(&tone(1024, 32, 0.5, 0.0), 0);
        assert!(amplitude.band(0.0, 24000.0).is_none());
    }

    #[test]
    fn deterministic_white_noise_density_and_integral_match_known_variance() {
        let variance = 0.2_f64.powi(2) / 3.0;
        for size in [1024, 8192, 32768] {
            for window in [Window::Rectangular, Window::Hann, Window::BlackmanHarris] {
                let mut analyzer = Analyzer::new(
                    Settings {
                        quantity: Quantity::Psd,
                        size,
                        window,
                        averages: 1,
                        remove_dc: false,
                        ..Settings::default()
                    },
                    48000,
                );
                let mut state = 0x5a71_eb09_1254_8123_u64;
                let mut integral = 0.0;
                let mut band_power = 0.0;
                for frame in 1..=32 {
                    let samples: Vec<_> = (0..size)
                        .map(|_| {
                            state ^= state << 13;
                            state ^= state >> 7;
                            state ^= state << 17;
                            0.2 * (2.0 * (state >> 11) as f64 / (1_u64 << 53) as f64 - 1.0)
                        })
                        .collect();
                    analyzer.update_samples(&samples, frame * size as u64);
                    integral += analyzer.band(0.0, 24000.0).unwrap().power_fs2;
                    band_power += analyzer.band(6000.0, 12000.0).unwrap().power_fs2;
                }
                assert!(
                    (integral / 32.0 / variance - 1.0).abs() < 0.03,
                    "{size} {window:?}"
                );
                // Expected one-sided white density is 2*variance/Fs. Account for
                // the exact number of inclusive bins, rather than a drawn span.
                let band = analyzer.band(6000.0, 12000.0).unwrap();
                let bandwidth = (band.last_bin - band.first_bin + 1) as f64 * 48000.0 / size as f64;
                let density = band_power / 32.0 / bandwidth;
                assert!((density / (2.0 * variance / 48000.0) - 1.0).abs() < 0.08);
            }
        }
    }

    #[test]
    fn numeric_cursor_band_average_and_hold_survive_the_display_floor_and_copy() {
        for quantity in [Quantity::Amplitude, Quantity::Psd] {
            let settings = Settings {
                quantity,
                size: 1024,
                averages: 4,
                ..Settings::default()
            };
            let mut analyzer = Analyzer::new(settings, 48000);
            let small: Vec<_> = (0..1024)
                .map(|i| 1e-12 * (TAU * 32.0 * i as f64 / 1024.0).cos())
                .collect();
            assert!(analyzer.update_samples(&small, 1024));
            let initial = analyzer.power()[32];
            assert_eq!(analyzer.db()[32], DB_MIN);
            let first = analyzer.cursor(1501.0).unwrap();
            assert_eq!(first.frequency_hz, 1500.0);
            assert!(first.level_db < DB_MIN as f64);
            assert!(first.value > 0.0);
            assert!(
                analyzer
                    .peak(View::full(48000, FrequencyScale::Log, -120.0))
                    .unwrap()
                    .level_db
                    < DB_MIN as f64
            );
            assert!(analyzer.update_samples(&vec![0.0; 1024], 2048));
            assert!((analyzer.power()[32] / initial - 0.75).abs() < 1e-14);
            assert_eq!(analyzer.hold_power()[32], initial);
            assert_eq!(
                analyzer.average(),
                Some(AverageInfo {
                    start: 0,
                    end: 2048,
                    updates: 2
                })
            );
            let mut result = Result::empty(Settings::default(), 96000);
            analyzer.copy_result(&mut result);
            assert_eq!(result.settings(), settings);
            assert_eq!(
                result.cursor(1500.0).unwrap().value,
                analyzer.cursor(1500.0).unwrap().value
            );
            assert_eq!(result.hold_power(), analyzer.hold_power());
            if quantity == Quantity::Psd {
                let power = result.band(0.0, 24000.0).unwrap().power_fs2;
                assert!((power / (0.75e-24 / 2.0) - 1.0).abs() < 1e-13);
            }
            result.clear_hold();
            assert_eq!(result.hold_power(), result.power());
            assert_eq!(result.average(), analyzer.average());
            analyzer.reset();
            assert!(analyzer.average().is_none());
            assert!(analyzer.cursor(1500.0).is_none());
            assert!(result.cursor(1500.0).is_some());
            assert!(analyzer.update_samples(&vec![0.0; 1024], 3072));
            assert_eq!(analyzer.cursor(1500.0).unwrap().level_db, f64::NEG_INFINITY);
        }
    }

    #[test]
    fn averaging_off_reports_only_the_latest_contribution() {
        let mut analyzer = Analyzer::new(
            Settings {
                size: 1024,
                averages: 1,
                ..Settings::default()
            },
            48000,
        );
        assert!(analyzer.update_samples(&vec![0.0; 1024], 1024));
        assert!(analyzer.update_samples(&vec![0.0; 1024], 1280));
        assert_eq!(
            analyzer.average(),
            Some(AverageInfo {
                start: 256,
                end: 1280,
                updates: 2
            })
        );
    }

    #[test]
    fn f32_fft_keeps_weak_psd_power_when_the_magnitude_is_squared_in_f64() {
        let mut analyzer = Analyzer::new(
            Settings {
                quantity: Quantity::Psd,
                size: 1024,
                averages: 1,
                precision: Precision::F32,
                ..Settings::default()
            },
            48000,
        );
        let samples: Vec<_> = (0..1024)
            .map(|i| 1e-24 * (TAU * 32.0 * i as f64 / 1024.0).cos())
            .collect();
        assert!(analyzer.update_samples(&samples, 1024));
        let power = analyzer.band(0.0, 24000.0).unwrap().power_fs2;
        assert!((power / 0.5e-48 - 1.0).abs() < 2e-6);
        assert!(analyzer.cursor(1500.0).unwrap().level_db < -480.0);
    }

    #[test]
    fn real_fft_matches_full_complex_reference_for_every_size_and_precision() {
        for size in FFT_SIZES {
            let samples: Vec<_> = (0..size)
                .map(|i| {
                    let phase = TAU * i as f64 / size as f64;
                    0.125
                        + 0.4 * (31.25 * phase).cos()
                        + 0.03 * (123.0 * phase).sin()
                        + if i % 2 == 0 { 0.05 } else { -0.05 }
                })
                .collect();
            for window in [Window::Rectangular, Window::Hann, Window::BlackmanHarris] {
                for remove_dc in [false, true] {
                    let weights: Vec<_> = (0..size).map(|i| window.weight(i, size)).collect();
                    let sum = weights.iter().sum::<f64>();
                    let mean = if remove_dc {
                        samples.iter().sum::<f64>() / size as f64
                    } else {
                        0.0
                    };
                    let mut reference: Vec<_> = samples
                        .iter()
                        .zip(&weights)
                        .map(|(&sample, &weight)| Complex::new((sample - mean) * weight / sum, 0.0))
                        .collect();
                    FftPlanner::<f64>::new()
                        .plan_fft_forward(size)
                        .process(&mut reference);
                    let rbw = 48000.0 * weights.iter().map(|w| w * w).sum::<f64>() / sum.powi(2);
                    for quantity in [Quantity::Amplitude, Quantity::Psd] {
                        for precision in [Precision::F64, Precision::F32] {
                            let mut analyzer = Analyzer::new(
                                Settings {
                                    quantity,
                                    size,
                                    window,
                                    remove_dc,
                                    precision,
                                    averages: 1,
                                },
                                48000,
                            );
                            assert!(analyzer.update_samples(&samples, size as u64));
                            for (bin, &actual) in analyzer.power.iter().enumerate() {
                                let endpoint = bin == 0 || bin == size / 2;
                                let factor = match quantity {
                                    Quantity::Amplitude => {
                                        if endpoint {
                                            1.0
                                        } else {
                                            4.0
                                        }
                                    }
                                    Quantity::Psd => (if endpoint { 1.0 } else { 2.0 }) / rbw,
                                };
                                let expected = reference[bin].norm_sqr() * factor;
                                // Absolute amplitude error includes low bins at the f32 noise floor.
                                let tolerance = if precision == Precision::F64 {
                                    1e-13
                                } else {
                                    2e-7
                                };
                                assert!(
                                    (actual.sqrt() - expected.sqrt()).abs() < tolerance,
                                    "N={size}, {window:?}, {precision:?}, DC={remove_dc}, {quantity:?}, bin={bin}"
                                );
                            }
                        }
                    }
                }
            }
        }
    }

    #[test]
    fn fast_fft_subtracts_dc_before_narrowing_and_keeps_power_average() {
        let samples: Vec<_> = (0..1024)
            .map(|i| 1.0 + 1e-8 * (TAU * 32.0 * i as f64 / 1024.0).cos())
            .collect();
        let mut history = History::new(1024);
        for &sample in &samples {
            history.push([sample, 0.0]);
        }
        for precision in [Precision::F64, Precision::F32] {
            let mut analyzer = Analyzer::new(
                Settings {
                    size: 1024,
                    averages: 2,
                    precision,
                    ..Settings::default()
                },
                48000,
            );
            assert!(analyzer.update(&history, 0));
            assert!((analyzer.db()[32] + 160.0).abs() < 0.001);
            assert!(analyzer.update_samples(&vec![0.0; 1024], 2048));
            assert!((analyzer.db()[32] + 163.0103).abs() < 0.001);
            assert!((analyzer.hold()[32] + 160.0).abs() < 0.001);
        }
        assert_eq!(Settings::default().precision, Precision::F64);
    }

    #[test]
    fn direct_f64_input_preserves_small_ac_on_large_dc() {
        let samples: Vec<_> = (0..1024)
            .map(|i| 1.0 + 1e-8 * (std::f64::consts::TAU * 32.0 * i as f64 / 1024.0).cos())
            .collect();
        let mut analyzer = Analyzer::new(
            Settings {
                size: 1024,
                averages: 1,
                ..Settings::default()
            },
            48000,
        );
        assert!(analyzer.update_samples(&samples, 1024));
        assert!((analyzer.db()[32] + 160.0).abs() < 0.001);
        assert!(samples.iter().all(|v| *v as f32 == 1.0));
        let loud: Vec<_> = (0..1024)
            .map(|i| (std::f64::consts::TAU * 32.0 * i as f64 / 1024.0).cos())
            .collect();
        assert!(analyzer.update_samples(&loud, 2048));
        assert!(analyzer.db()[32].abs() < 0.001);
        assert!(analyzer.update_samples(&samples, 3072));
        assert!((analyzer.db()[32] + 160.0).abs() < 0.001);
        assert!(!analyzer.update_samples(&samples[..1023], 1024));
    }

    fn tone(size: usize, bin: usize, amplitude: f64, dc: f64) -> History {
        let mut h = History::new(size * 2);
        for i in 0..size {
            h.push([
                dc + amplitude * (TAU * bin as f64 * i as f64 / size as f64).cos(),
                0.0,
            ]);
        }
        h
    }

    #[test]
    fn cached_projection_tracks_axes_rate_size_and_new_power_without_losing_peaks() {
        let mut builder = LineBuilder::default();
        let mut lines = Vec::new();
        for (size, sample_rate) in [(1024, 48000), (8192, 96000), (32768, 48000)] {
            let mut analyzer = Analyzer::new(
                Settings {
                    size,
                    averages: 1,
                    ..Settings::default()
                },
                sample_rate,
            );
            assert!(analyzer.update(&tone(size, 32, 0.5, 0.0), 0));
            for (scale, pixels) in [
                (FrequencyScale::Linear, 100),
                (FrequencyScale::Log, 100),
                (FrequencyScale::Log, 331),
            ] {
                let mut view = View::full(sample_rate, scale, -120.0);
                // Span and floor changes must affect the next build, even with
                // the same cached analyzer and no new samples.
                for max_hz in [sample_rate as f32 * 0.5, 4000.0] {
                    view.max_hz = max_hz;
                    for floor in [-120.0, -60.0] {
                        view.floor_db = floor;
                        builder.build(&analyzer, view, pixels, true, &mut lines);
                        let expected_x = view.x(32.0 * analyzer.bin_hz());
                        let expected_y = view.y(analyzer.db()[32]);
                        assert!(lines.len() <= pixels * 4);
                        assert!(
                            lines
                                .iter()
                                .filter(|l| l.channel == 0)
                                .flat_map(|l| [l.a, l.b])
                                .any(|p| (p[0] - expected_x).abs() <= 1.0 / pixels as f32
                                    && (p[1] - expected_y).abs() < 1e-5)
                        );
                    }
                }
            }
            assert!(analyzer.update_window(&tone(size, 32, 0.05, 0.0), 0..size as u64, 0));
            let view = View::full(sample_rate, FrequencyScale::Log, -120.0);
            builder.build(&analyzer, view, 100, true, &mut lines);
            for (channel, db) in [(0, -26.0206), (1, -6.0206)] {
                assert!(
                    lines
                        .iter()
                        .filter(|l| l.channel == channel)
                        .flat_map(|l| [l.a[1], l.b[1]])
                        .any(|y| (y - view.y(db)).abs() < 1e-5)
                );
            }
        }
    }

    #[test]
    fn coherent_sine_amplitude_and_window_bandwidth() {
        for (window, enbw) in [
            (Window::Rectangular, 1.0),
            (Window::Hann, 1.5),
            (Window::BlackmanHarris, 2.0044),
        ] {
            let mut a = Analyzer::new(
                Settings {
                    size: 4096,
                    window,
                    ..Settings::default()
                },
                48000,
            );
            assert!(a.update(&tone(4096, 85, 0.5, 0.0), 0));
            assert!((a.db()[85] + 6.0206).abs() < 0.002);
            assert!((a.rbw_hz() / a.bin_hz() as f64 - enbw).abs() < 0.001);
            let peak = a
                .peak(View::full(48000, FrequencyScale::Log, -120.0))
                .unwrap();
            assert!((peak.frequency - 996.09375).abs() < 0.01);
        }
    }

    #[test]
    fn sixteenth_channel_is_analyzed_without_aliasing_to_stereo() {
        let mut h = History::with_channels(1024, 16);
        for i in 0..1024 {
            let mut samples = [0.0; 16];
            samples[15] = 0.5 * (TAU * 32.0 * i as f64 / 1024.0).cos();
            h.push(samples);
        }
        let mut a = Analyzer::new(
            Settings {
                size: 1024,
                ..Settings::default()
            },
            48000,
        );
        assert!(a.update(&h, 15));
        assert!((a.db()[32] + 6.0206).abs() < 0.002);
        assert!(a.update(&h, 1));
        assert!(a.db().iter().all(|db| *db == DB_MIN));
        assert!(!a.update(&h, 16));
        assert!(!a.is_ready());
    }

    #[test]
    fn dc_and_nyquist_are_not_doubled_and_dc_can_be_removed() {
        let settings = Settings {
            size: 1024,
            window: Window::Rectangular,
            remove_dc: false,
            ..Settings::default()
        };
        let mut a = Analyzer::new(settings, 48000);
        a.update(&tone(1024, 512, 0.25, 0.5), 0);
        assert!((a.db()[0] + 6.0206).abs() < 0.002);
        assert!((a.db()[512] + 12.0412).abs() < 0.002);
        let mut removed = Analyzer::new(
            Settings {
                remove_dc: true,
                ..settings
            },
            48000,
        );
        removed.update(&tone(1024, 512, 0.25, 0.5), 0);
        assert_eq!(removed.db()[0], DB_MIN);
    }

    #[test]
    fn power_average_hold_reset_and_channel_change() {
        let mut h = tone(1024, 30, 1.0, 0.0);
        let mut a = Analyzer::new(
            Settings {
                size: 1024,
                averages: 2,
                ..Settings::default()
            },
            48000,
        );
        assert!(a.update(&h, 0));
        assert!(!a.update(&h, 0)); // Repaints must not re-average the same samples.
        for _ in 0..1024 {
            h.push([0.0, 0.0]);
        }
        a.update(&h, 0);
        assert!((a.db()[30] + 3.0103).abs() < 0.002);
        assert!(a.hold()[30].abs() < 0.002);
        a.clear_hold();
        assert!((a.hold()[30] + 3.0103).abs() < 0.002);
        a.update(&h, 1);
        assert!(a.db().iter().all(|db| *db == DB_MIN));
        h.clear();
        assert!(!a.update(&h, 0));
        assert!(!a.is_ready());
    }

    #[test]
    fn wrapped_history_two_tones_and_log_pixel_peak_preservation() {
        let mut h = History::new(8192);
        for i in 0..20000 {
            let phase = TAU * i as f64 / 8192.0;
            h.push([
                0.5 * (170.0 * phase).cos() + 0.05 * (510.0 * phase).cos(),
                0.0,
            ]);
        }
        let mut a = Analyzer::new(Settings::default(), 48000);
        a.update(&h, 0);
        assert!((a.db()[170] - a.db()[510] - 20.0).abs() < 0.01);
        let mut lines = Vec::new();
        for scale in [FrequencyScale::Linear, FrequencyScale::Log] {
            let view = View::full(48000, scale, -120.0);
            build_lines(&a, view, 100, true, &mut lines);
            assert!(lines.len() <= 400);
            assert!(
                lines
                    .iter()
                    .flat_map(|l| [l.a[1], l.b[1]])
                    .any(|y| (y - view.y(a.db()[170])).abs() < 1e-5)
            );
            assert!((view.frequency(view.x(1000.0)) - 1000.0).abs() < 0.01);
        }
    }
}
