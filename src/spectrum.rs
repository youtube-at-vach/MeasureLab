//! Windowed, one-sided amplitude spectra. A bin-centred sine with peak
//! amplitude 1 FS reads 0 dBFS. This is not a PSD or a calibrated dBm meter.
use crate::signal::{History, Line};
use rustfft::{Fft, FftPlanner, num_complex::Complex64};
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

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Settings {
    pub size: usize,
    pub window: Window,
    /// Exponential power average, alpha = 1 / averages; not a batch count.
    pub averages: u32,
    pub remove_dc: bool,
}

impl Default for Settings {
    fn default() -> Self {
        Self {
            size: 8192,
            window: Window::Hann,
            averages: 4,
            remove_dc: true,
        }
    }
}

#[derive(Clone, Copy, Debug)]
pub struct Peak {
    pub frequency: f32,
    pub dbfs: f32,
}

/// FFT plan, work buffers and output storage are allocated only at configuration
/// changes. Acquisition never calls this analyzer. Analyze the newest complete
/// window, at most once per quarter-window of new samples.
pub struct Analyzer {
    settings: Settings,
    sample_rate: u32,
    fft: Arc<dyn Fft<f64>>,
    buffer: Vec<Complex64>,
    scratch: Vec<Complex64>,
    weights: Vec<f64>,
    weight_sum: f64,
    rbw: f32,
    power: Vec<f64>,
    db: Vec<f32>,
    hold: Vec<f32>,
    last_end: Option<u64>,
    last_channel: usize,
}

impl Analyzer {
    pub fn new(settings: Settings, sample_rate: u32) -> Self {
        assert!(FFT_SIZES.contains(&settings.size));
        assert!(sample_rate > 0 && settings.averages > 0);
        let fft = FftPlanner::<f64>::new().plan_fft_forward(settings.size);
        let weights: Vec<_> = (0..settings.size)
            .map(|i| settings.window.weight(i, settings.size))
            .collect();
        let weight_sum = weights.iter().sum::<f64>();
        let rbw = sample_rate as f64 * weights.iter().map(|v| v * v).sum::<f64>()
            / (weight_sum * weight_sum);
        Self {
            buffer: vec![Complex64::default(); settings.size],
            scratch: vec![Complex64::default(); fft.get_inplace_scratch_len()],
            power: vec![0.0; settings.size / 2 + 1],
            db: vec![DB_MIN; settings.size / 2 + 1],
            hold: vec![DB_MIN; settings.size / 2 + 1],
            fft,
            settings,
            sample_rate,
            weights,
            weight_sum,
            rbw: rbw as f32,
            last_end: None,
            last_channel: 0,
        }
    }

    pub fn settings(&self) -> Settings {
        self.settings
    }
    pub fn bin_hz(&self) -> f32 {
        self.sample_rate as f32 / self.settings.size as f32
    }
    pub fn rbw_hz(&self) -> f32 {
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

    pub fn reset(&mut self) {
        self.last_end = None;
        self.power.fill(0.0);
        self.db.fill(DB_MIN);
        self.clear_hold();
    }

    pub fn clear_hold(&mut self) {
        // Restart from the currently displayed trace, including while paused.
        self.hold.copy_from_slice(&self.db);
    }

    pub fn update(&mut self, history: &History, channel: usize) -> bool {
        let end = history.range().end;
        if history.len() < self.settings.size || channel >= history.channels() {
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
        for (offset, value) in self.buffer.iter_mut().enumerate() {
            *value = Complex64::new(
                history.get(range.start + offset as u64).unwrap()[channel] as f64,
                0.0,
            );
        }
        self.process_window(range.end, channel);
        true
    }

    /// Direct 64bit core input, without quantizing through the capture history.
    /// `end` is the exclusive source sample index of this complete window.
    pub fn update_samples(&mut self, samples: &[f64], end: u64) -> bool {
        if samples.len() != self.settings.size || end < samples.len() as u64 {
            return false;
        }
        if self.last_channel != 0 {
            self.reset();
        }
        for (value, &sample) in self.buffer.iter_mut().zip(samples) {
            *value = Complex64::new(sample, 0.0);
        }
        self.process_window(end, 0);
        true
    }

    fn process_window(&mut self, end: u64, channel: usize) {
        let mean = if self.settings.remove_dc {
            self.buffer.iter().map(|v| v.re).sum::<f64>() / self.settings.size as f64
        } else {
            0.0
        };
        for (value, weight) in self.buffer.iter_mut().zip(&self.weights) {
            value.re = (value.re - mean) * weight;
        }
        self.fft
            .process_with_scratch(&mut self.buffer, &mut self.scratch);
        let alpha = 1.0 / self.settings.averages as f64;
        for bin in 0..self.db.len() {
            // DC and Nyquist have no negative-frequency partner to fold in.
            let factor = if bin == 0 || bin == self.settings.size / 2 {
                1.0
            } else {
                2.0
            } / self.weight_sum;
            let power = self.buffer[bin].norm_sqr() * factor * factor;
            self.power[bin] = if self.last_end.is_none() || self.settings.averages == 1 {
                power
            } else {
                self.power[bin] + alpha * (power - self.power[bin])
            };
            self.db[bin] = (10.0 * self.power[bin].max(1e-18).log10()) as f32;
            self.hold[bin] = self.hold[bin].max(self.db[bin]);
        }
        self.last_end = Some(end);
        self.last_channel = channel;
    }

    /// Strongest displayed bin, excluding DC. No sub-bin accuracy is claimed.
    pub fn peak(&self, view: View) -> Option<Peak> {
        if !self.is_ready() {
            return None;
        }
        self.db
            .iter()
            .enumerate()
            .skip(1)
            .filter(|(bin, _)| {
                let hz = *bin as f32 * self.bin_hz();
                hz >= view.min_hz && hz <= view.max_hz
            })
            .max_by(|a, b| a.1.total_cmp(b.1))
            .filter(|(_, db)| **db > DB_MIN)
            .map(|(bin, db)| Peak {
                frequency: bin as f32 * self.bin_hz(),
                dbfs: *db,
            })
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

    fn y(self, db: f32) -> f32 {
        (self.ceiling_db - db) / (self.ceiling_db - self.floor_db)
    }
}

/// Retain both extrema in each physical pixel column, including on a log axis.
/// Dense spectra therefore preserve narrow tones with O(pixels) GPU geometry.
pub fn build_lines(
    analyzer: &Analyzer,
    view: View,
    pixels: usize,
    show_hold: bool,
    output: &mut Vec<Line>,
) {
    output.clear();
    if !analyzer.is_ready() || pixels == 0 {
        return;
    }
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
        for (bin, db) in values.iter().enumerate() {
            let hz = bin as f32 * analyzer.bin_hz();
            if hz < view.min_hz || hz > view.max_hz {
                continue;
            }
            let point = [view.x(hz), view.y(*db)];
            let column = ((point[0] * pixels as f32) as usize).min(pixels - 1);
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
    use std::f32::consts::TAU;

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

    fn tone(size: usize, bin: usize, amplitude: f32, dc: f32) -> History {
        let mut h = History::new(size * 2);
        for i in 0..size {
            h.push([
                dc + amplitude * (TAU * bin as f32 * i as f32 / size as f32).cos(),
                0.0,
            ]);
        }
        h
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
            assert!((a.rbw_hz() / a.bin_hz() - enbw).abs() < 0.001);
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
            samples[15] = 0.5 * (TAU * 32.0 * i as f32 / 1024.0).cos();
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
            let phase = TAU * i as f32 / 8192.0;
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
