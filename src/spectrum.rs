//! Windowed, one-sided amplitude spectra. A bin-centred sine with peak
//! amplitude 1 FS reads 0 dBFS. This is not a PSD or a calibrated dBm meter.
use crate::signal::{History, Line};
use rustfft::{Fft, FftPlanner, num_complex::Complex32};
use std::{f32::consts::TAU, sync::Arc};

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

    fn weight(self, index: usize, size: usize) -> f32 {
        let phase = TAU * index as f32 / size as f32;
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
    fft: Arc<dyn Fft<f32>>,
    buffer: Vec<Complex32>,
    scratch: Vec<Complex32>,
    weights: Vec<f32>,
    weight_sum: f32,
    rbw: f32,
    power: Vec<f32>,
    db: Vec<f32>,
    hold: Vec<f32>,
    last_end: Option<u64>,
    last_channel: usize,
}

impl Analyzer {
    pub fn new(settings: Settings, sample_rate: u32) -> Self {
        assert!(FFT_SIZES.contains(&settings.size));
        assert!(sample_rate > 0 && settings.averages > 0);
        let fft = FftPlanner::<f32>::new().plan_fft_forward(settings.size);
        let weights: Vec<_> = (0..settings.size)
            .map(|i| settings.window.weight(i, settings.size))
            .collect();
        let weight_sum = weights.iter().sum::<f32>();
        let rbw = sample_rate as f32 * weights.iter().map(|v| v * v).sum::<f32>()
            / (weight_sum * weight_sum);
        Self {
            buffer: vec![Complex32::default(); settings.size],
            scratch: vec![Complex32::default(); fft.get_inplace_scratch_len()],
            power: vec![0.0; settings.size / 2 + 1],
            db: vec![DB_MIN; settings.size / 2 + 1],
            hold: vec![DB_MIN; settings.size / 2 + 1],
            fft,
            settings,
            sample_rate,
            weights,
            weight_sum,
            rbw,
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
        let channel = channel.min(1);
        let end = history.range().end;
        if history.len() < self.settings.size {
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
        let mean = if self.settings.remove_dc {
            (start..end)
                .map(|i| history.get(i).unwrap()[channel] as f64)
                .sum::<f64>() as f32
                / self.settings.size as f32
        } else {
            0.0
        };
        for (offset, value) in self.buffer.iter_mut().enumerate() {
            *value = Complex32::new(
                (history.get(start + offset as u64).unwrap()[channel] - mean)
                    * self.weights[offset],
                0.0,
            );
        }
        self.fft
            .process_with_scratch(&mut self.buffer, &mut self.scratch);
        let alpha = 1.0 / self.settings.averages as f32;
        for bin in 0..self.db.len() {
            // DC and Nyquist have no negative-frequency partner to fold in.
            let factor = if bin == 0 || bin == self.settings.size / 2 {
                1.0
            } else {
                2.0
            } / self.weight_sum;
            let power = self.buffer[bin].norm_sqr() * factor * factor;
            self.power[bin] = if self.last_end.is_none() {
                power
            } else {
                self.power[bin] + alpha * (power - self.power[bin])
            };
            self.db[bin] = (10.0 * self.power[bin].max(1e-18).log10()).max(DB_MIN);
            self.hold[bin] = self.hold[bin].max(self.db[bin]);
        }
        self.last_end = Some(end);
        self.last_channel = channel;
        true
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
