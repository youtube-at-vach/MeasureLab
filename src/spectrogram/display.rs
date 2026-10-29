//! Display transforms never modify the STFT or its history.
use super::{History, colormaps};
use crate::spectrum::{FrequencyScale, View};
use serde::{Deserialize, Serialize};

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
pub enum ColorMap {
    Blue,
    Heat,
    Grayscale,
    Turbo,
    #[default]
    Viridis,
    Inferno,
    Magma,
    Hot,
    Copper,
}

impl ColorMap {
    pub const ALL: [Self; 9] = [
        Self::Viridis,
        Self::Inferno,
        Self::Turbo,
        Self::Magma,
        Self::Grayscale,
        Self::Blue,
        Self::Heat,
        Self::Hot,
        Self::Copper,
    ];
    pub const MAX_STOPS: usize = 256;

    pub fn name(self) -> &'static str {
        match self {
            Self::Blue => "Blue",
            Self::Heat => "Heat",
            Self::Grayscale => "Grayscale",
            Self::Turbo => "Turbo",
            Self::Viridis => "Viridis",
            Self::Inferno => "Inferno",
            Self::Magma => "Magma",
            Self::Hot => "Hot",
            Self::Copper => "Copper",
        }
    }

    /// These same stops are uploaded to the shader and used by the color bar.
    pub fn stops(self) -> &'static [[f32; 4]] {
        match self {
            Self::Blue => &[
                [0.025, 0.04, 0.10, 0.0],
                [0.05, 0.55, 0.80, 0.0],
                [1.0, 0.85, 0.25, 0.0],
            ],
            Self::Heat => &[
                [0.015, 0.005, 0.005, 0.0],
                [0.8, 0.15, 0.015, 0.0],
                [1.0, 1.0, 0.85, 0.0],
            ],
            Self::Grayscale => &[[0.0; 4], [1.0, 1.0, 1.0, 0.0]],
            Self::Turbo => &colormaps::TURBO,
            Self::Viridis => &colormaps::VIRIDIS,
            Self::Inferno => &colormaps::INFERNO,
            Self::Magma => &colormaps::MAGMA,
            Self::Hot => &[
                [0.0; 4],
                [1.0, 0.0, 0.0, 0.0],
                [1.0, 1.0, 0.0, 0.0],
                [1.0, 1.0, 1.0, 0.0],
            ],
            Self::Copper => &COPPER,
        }
    }

    pub fn rgb(self, fraction: f32) -> [f32; 3] {
        let stops = self.stops();
        let t = fraction.clamp(0.0, 1.0) * (stops.len() - 1) as f32;
        let index = (t as usize).min(stops.len() - 2);
        let t = t - index as f32;
        std::array::from_fn(|i| stops[index][i] + (stops[index + 1][i] - stops[index][i]) * t)
    }
}

// Sample the conventional copper ramp once at compile time. The red channel
// saturates before green/blue; a two-color ramp would lose that distinction.
const COPPER: [[f32; 4]; ColorMap::MAX_STOPS] = {
    let mut colors = [[0.0; 4]; ColorMap::MAX_STOPS];
    let mut i = 0;
    while i < colors.len() {
        let t = i as f32 / (colors.len() - 1) as f32;
        let red = t * 1.25;
        colors[i] = [
            if red > 1.0 { 1.0 } else { red },
            t * 0.7812,
            t * 0.4975,
            0.0,
        ];
        i += 1;
    }
    colors
};

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct ColorRange {
    pub min: f32,
    pub max: f32,
}

impl Default for ColorRange {
    fn default() -> Self {
        Self {
            min: -120.0,
            max: 0.0,
        }
    }
}

impl ColorRange {
    pub fn new(min: f32, max: f32) -> Option<Self> {
        (min.is_finite() && max.is_finite() && min < max && (max - min).is_finite())
            .then_some(Self { min, max })
    }

    pub fn fraction(self, db: f32) -> f32 {
        ((db - self.min) / (self.max - self.min)).clamp(0.0, 1.0)
    }
}

#[derive(Default)]
pub struct AutoRange {
    range: Option<ColorRange>,
    key: Option<(u64, [u32; 3])>,
    updated_at: Option<f64>,
}

impl AutoRange {
    /// At most four scans/sec while live. An unchanged stopped view is stable.
    /// Display cache values are sufficient for color statistics, never readouts.
    pub fn update(
        &mut self,
        history: &History,
        view: View,
        seconds: f64,
        now: f64,
        live: bool,
    ) -> ColorRange {
        let key = (
            history.revision(),
            [
                view.min_hz.to_bits(),
                view.max_hz.to_bits(),
                (seconds as f32).to_bits(),
            ],
        );
        if self.key == Some(key) || (live && self.updated_at.is_some_and(|t| now - t < 0.25)) {
            return self.range.unwrap_or_default();
        }
        self.key = Some(key);
        self.updated_at = Some(now);
        if let Some(target) = history.auto_color_range(view, seconds) {
            self.range = Some(if live {
                self.range.map_or(target, |old| ColorRange {
                    min: if (target.min - old.min).abs() < 1.0 {
                        old.min
                    } else {
                        old.min + 0.25 * (target.min - old.min)
                    },
                    // Include a new strong transient immediately; decay slowly.
                    max: if target.max > old.max {
                        target.max
                    } else if old.max - target.max < 1.0 {
                        old.max
                    } else {
                        old.max + 0.25 * (target.max - old.max)
                    },
                })
            } else {
                target
            });
        }
        self.range.unwrap_or_default()
    }
}

impl History {
    /// Deterministically sampled 20th percentile (1 dB histogram, <= 65,536
    /// bins), exact peak + 3 dB, at least 12 dB of contrast. Silence, invalid
    /// bins and gaps are excluded. This is display contrast, not a measurement.
    pub fn auto_color_range(&self, view: View, seconds: f64) -> Option<ColorRange> {
        let latest = self.latest()?;
        if !seconds.is_finite() || seconds <= 0.0 {
            return None;
        }
        let bin_hz = latest.config.sample_rate as f32 / latest.config.size as f32;
        let first = (view.min_hz / bin_hz).ceil() as usize;
        let last = ((view.max_hz / bin_hz).floor() as usize).min(latest.config.size / 2);
        if first > last {
            return None;
        }
        // Cover all finite f64 powers after 10 log10, at 1 dB resolution.
        let mut histogram = [0_u32; 6656];
        let mut count = 0_u64;
        let mut peak = f32::NEG_INFINITY;
        let mut sampled = 0;
        let step = (self.len() * (last - first + 1)).div_ceil(65536).max(1);
        for slot in 0..super::ROWS {
            let Some((info, db)) = self.row(slot) else {
                continue;
            };
            if TimeAxis::new(latest.end, info.config.sample_rate, seconds).age(info.end) >= seconds
            {
                continue;
            }
            let values = &db[first..=last];
            // Independent lanes avoid a serial max dependency over long FFTs.
            let mut maxima = [f32::NEG_INFINITY; 8];
            let (chunks, remainder) = values.as_chunks::<8>();
            for chunk in chunks {
                for (max, &value) in maxima.iter_mut().zip(chunk) {
                    if value.is_finite() {
                        *max = max.max(value);
                    }
                }
            }
            for &value in remainder {
                if value.is_finite() {
                    peak = peak.max(value);
                }
            }
            peak = maxima.into_iter().fold(peak, f32::max);
            // Rotate the sampling offset between rows to avoid locking the
            // noise-floor estimate to a periodic comb of FFT bins.
            for &value in values.iter().skip(slot % step).step_by(step) {
                if sampled == 65536 {
                    break;
                }
                sampled += 1;
                if !value.is_finite() {
                    continue;
                }
                let index = (value.floor() + 3328.0).clamp(0.0, 6655.0) as usize;
                histogram[index] += 1;
                count += 1;
            }
        }
        if count < 8 {
            return None;
        }
        let threshold = count.div_ceil(5);
        let mut cumulative = 0;
        let percentile = histogram
            .iter()
            .position(|n| {
                cumulative += *n as u64;
                cumulative >= threshold
            })
            .unwrap();
        let max = peak + 3.0;
        ColorRange::new((percentile as f32 - 3328.0 - 3.0).min(max - 12.0), max)
    }
}

#[derive(Clone, Copy, Debug)]
pub struct TimeAxis {
    pub anchor_end: u64,
    pub sample_rate: u32,
    pub seconds: f64,
}

impl TimeAxis {
    pub fn new(anchor_end: u64, sample_rate: u32, seconds: f64) -> Self {
        Self {
            anchor_end,
            sample_rate,
            seconds,
        }
    }
    pub fn age(self, end: u64) -> f64 {
        crate::cursor::signed_distance(self.anchor_end, end) / self.sample_rate as f64
    }
    pub fn fraction(self, end: u64) -> f32 {
        (crate::cursor::signed_distance(self.anchor_end, end)
            / (self.sample_rate as f64 * self.seconds)) as f32
    }
    pub fn age_at(self, fraction: f64) -> f64 {
        fraction * self.seconds
    }
}

#[derive(Clone, Copy, Debug)]
pub struct FrequencyRange {
    pub scale: FrequencyScale,
    pub min: f64,
    pub max: f64,
    bin: f64,
    nyquist: f64,
}

impl FrequencyRange {
    pub fn new(sample_rate: u32, size: usize, scale: FrequencyScale, min: f32, max: f32) -> Self {
        let bin = sample_rate as f64 / size as f64;
        let nyquist = sample_rate as f64 * 0.5;
        let lower = if scale == FrequencyScale::Log {
            bin.min(1.0)
        } else {
            0.0
        };
        let max = if max == 0.0 || !max.is_finite() {
            nyquist
        } else {
            (max as f64).clamp(lower + bin, nyquist)
        };
        let min = if min.is_finite() {
            (min as f64).clamp(lower, max - bin)
        } else {
            lower
        };
        Self {
            scale,
            min,
            max,
            bin,
            nyquist,
        }
    }

    fn coordinate(self, hz: f64) -> f64 {
        if self.scale == FrequencyScale::Log {
            hz.ln()
        } else {
            hz
        }
    }
    fn hz(self, coordinate: f64) -> f64 {
        if self.scale == FrequencyScale::Log {
            coordinate.exp()
        } else {
            coordinate
        }
    }
    fn shifted(self, mut min: f64, mut max: f64) -> Self {
        let lower = self.coordinate(if self.scale == FrequencyScale::Log {
            self.bin.min(1.0)
        } else {
            0.0
        });
        let upper = self.coordinate(self.nyquist);
        if max - min >= upper - lower {
            min = lower;
            max = upper;
        } else {
            if min < lower {
                max += lower - min;
                min = lower;
            }
            if max > upper {
                min -= max - upper;
                max = upper;
            }
        }
        let lower_hz = self.hz(lower);
        let max = self.hz(max).clamp(lower_hz + self.bin, self.nyquist);
        let min = self.hz(min).clamp(lower_hz, max - self.bin);
        Self { min, max, ..self }
    }
    pub fn zoom(self, fraction: f64, factor: f64) -> Self {
        let min = self.coordinate(self.min);
        let max = self.coordinate(self.max);
        let pivot = min + (max - min) * fraction.clamp(0.0, 1.0);
        let factor = factor.clamp(0.1, 10.0);
        self.shifted(
            pivot + (min - pivot) * factor,
            pivot + (max - pivot) * factor,
        )
    }
    /// Positive fractions move towards higher frequencies.
    pub fn pan(self, fraction: f64) -> Self {
        let min = self.coordinate(self.min);
        let max = self.coordinate(self.max);
        let shift = (max - min) * fraction;
        self.shifted(min + shift, max + shift)
    }
    pub fn view(self, range: ColorRange) -> View {
        View {
            scale: self.scale,
            min_hz: self.min as f32,
            max_hz: self.max as f32,
            floor_db: range.min,
            ceiling_db: range.max,
        }
    }
}

/// Requested and effective horizontal coordinates in seconds, independent of Hz.
#[derive(Clone, Copy, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct QuefrencyRange {
    pub min_seconds: f64,
    pub max_seconds: f64,
}

impl Default for QuefrencyRange {
    fn default() -> Self {
        Self {
            min_seconds: 0.0,
            max_seconds: 0.020,
        }
    }
}
impl QuefrencyRange {
    pub fn validate(self) -> Result<(), &'static str> {
        if self.min_seconds.is_finite()
            && self.max_seconds.is_finite()
            && self.min_seconds >= 0.0
            && self.min_seconds < self.max_seconds
        {
            Ok(())
        } else {
            Err("Quefrency range requires finite 0 <= Min < Max")
        }
    }
    pub fn effective(self, sample_rate: u32, size: usize) -> Self {
        let step = 1.0 / sample_rate as f64;
        let upper = size as f64 * 0.5 * step;
        let max_seconds = ((self.max_seconds / step).ceil() * step).clamp(2.0 * step, upper);
        let min_seconds =
            ((self.min_seconds / step).floor() * step).clamp(step, max_seconds - step);
        Self {
            min_seconds,
            max_seconds,
        }
    }
    pub fn at(self, fraction: f64) -> f64 {
        self.min_seconds + (self.max_seconds - self.min_seconds) * fraction
    }
    pub fn fraction(self, seconds: f64) -> f64 {
        (seconds - self.min_seconds) / (self.max_seconds - self.min_seconds)
    }
    fn shifted(self, min: f64, max: f64, sample_rate: u32, size: usize) -> Self {
        let step = 1.0 / sample_rate as f64;
        let upper = size as f64 * 0.5 * step;
        let width = (max - min).clamp(step, upper - step);
        let min_seconds = min.clamp(step, upper - width);
        Self {
            min_seconds,
            max_seconds: min_seconds + width,
        }
    }
    pub fn pan(self, fraction: f64, sample_rate: u32, size: usize) -> Self {
        let shift = (self.max_seconds - self.min_seconds) * fraction;
        self.shifted(
            self.min_seconds + shift,
            self.max_seconds + shift,
            sample_rate,
            size,
        )
    }
    pub fn zoom(self, fraction: f64, factor: f64, sample_rate: u32, size: usize) -> Self {
        let pivot = self.at(fraction.clamp(0.0, 1.0));
        let factor = factor.clamp(0.1, 10.0);
        self.shifted(
            pivot + (self.min_seconds - pivot) * factor,
            pivot + (self.max_seconds - pivot) * factor,
            sample_rate,
            size,
        )
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{
        spectrum::{Precision, Window},
        stft::{Config, Gap, RowInfo},
    };

    fn history() -> History {
        let mut history = History::default();
        history.reset(
            7,
            Config {
                analysis: crate::stft::Analysis::Spectrogram,
                log_floor_db: crate::cepstrum::DEFAULT_LOG_FLOOR_DB,
                sample_rate: 48000,
                channels: 16,
                channel: 15,
                size: 1024,
                hop: 256,
                window: Window::Hann,
                remove_dc: true,
                precision: Precision::F64,
            },
        );
        history
    }

    fn push(history: &mut History, end: u64, db: &[f32]) {
        let config = history.config().unwrap();
        assert!(history.push(
            RowInfo {
                cepstrum: None,
                generation: 7,
                config,
                start: end - config.size as u64,
                end,
                gap: Gap::default()
            },
            db
        ));
    }

    #[test]
    fn shared_palette_normalization_and_luminance() {
        let range = ColorRange::new(-120.0, 0.0).unwrap();
        for map in ColorMap::ALL {
            let stops = map.stops();
            assert!((2..=ColorMap::MAX_STOPS).contains(&stops.len()));
            assert_eq!(map.rgb(range.fraction(-120.0)), stops[0][..3]);
            assert_eq!(map.rgb(range.fraction(0.0)), stops.last().unwrap()[..3]);
            let mut previous = 0.0;
            for i in 0..=4096 {
                let rgb = map.rgb(i as f32 / 4096.0);
                assert!(rgb.iter().all(|c| c.is_finite() && (0.0..=1.0).contains(c)));
                let luminance = rgb[0] * 0.2126 + rgb[1] * 0.7152 + rgb[2] * 0.0722;
                // Turbo is a rainbow with a bright center and a dark red end.
                if map != ColorMap::Turbo {
                    assert!(luminance >= previous, "{map:?} at {i}");
                }
                previous = luminance;
            }
            assert_eq!(map.rgb(range.fraction(f32::NEG_INFINITY)), map.rgb(0.0));
            assert_eq!(map.rgb(range.fraction(f32::INFINITY)), map.rgb(1.0));
        }
        for (min, max) in [
            (0.0, 0.0),
            (1.0, -1.0),
            (f32::NAN, 1.0),
            (-1.0, f32::INFINITY),
            (-f32::MAX, f32::MAX),
        ] {
            assert!(ColorRange::new(min, max).is_none());
        }
    }

    #[test]
    fn standard_palettes_match_reference_colors_and_interpolate_between_samples() {
        // Independent reference samples from the published sRGB tables, covering
        // the full rainbow and the low/mid/high levels of the sequential maps.
        for (map, samples) in [
            (
                ColorMap::Turbo,
                [
                    [0.18995, 0.07176, 0.23217],
                    [0.15844, 0.73551, 0.92305],
                    [0.64362, 0.98999, 0.23356],
                    [0.98360, 0.49291, 0.12849],
                    [0.47960, 0.01583, 0.01055],
                ],
            ),
            (
                ColorMap::Viridis,
                [
                    [0.267004, 0.004874, 0.329415],
                    [0.229739, 0.322361, 0.545706],
                    [0.127568, 0.566949, 0.550556],
                    [0.369214, 0.788888, 0.382914],
                    [0.993248, 0.906157, 0.143936],
                ],
            ),
            (
                ColorMap::Inferno,
                [
                    [0.001462, 0.000466, 0.013866],
                    [0.341500, 0.062325, 0.429425],
                    [0.735683, 0.215906, 0.330245],
                    [0.978422, 0.557937, 0.034931],
                    [0.988362, 0.998364, 0.644924],
                ],
            ),
            (
                ColorMap::Magma,
                [
                    [0.001462, 0.000466, 0.013866],
                    [0.316654, 0.071690, 0.485380],
                    [0.716387, 0.214982, 0.475290],
                    [0.986700, 0.535582, 0.382210],
                    [0.987053, 0.991438, 0.749504],
                ],
            ),
        ] {
            for (index, expected) in [0, 64, 128, 192, 255].into_iter().zip(samples) {
                let actual = map.rgb(index as f32 / 255.0);
                for (actual, expected) in actual.into_iter().zip(expected) {
                    assert!((actual - expected).abs() < 1e-6, "{map:?} at {index}");
                }
            }
            let between = map.rgb(100.5 / 255.0);
            for (i, actual) in between.into_iter().enumerate() {
                let expected = (map.stops()[100][i] + map.stops()[101][i]) * 0.5;
                assert!((actual - expected).abs() < 1e-6);
            }
        }
        assert_eq!(ColorMap::Grayscale.rgb(0.0), [0.0; 3]);
        assert_eq!(ColorMap::Grayscale.rgb(0.5), [0.5; 3]);
        assert_eq!(ColorMap::Grayscale.rgb(1.0), [1.0; 3]);
        assert_eq!(ColorMap::Hot.rgb(0.0), [0.0; 3]);
        assert_eq!(ColorMap::Hot.rgb(1.0 / 3.0), [1.0, 0.0, 0.0]);
        assert_eq!(ColorMap::Hot.rgb(2.0 / 3.0), [1.0, 1.0, 0.0]);
        assert_eq!(ColorMap::Hot.rgb(1.0), [1.0; 3]);
        assert_eq!(ColorMap::Copper.rgb(0.0), [0.0; 3]);
        assert_eq!(ColorMap::Copper.rgb(1.0), [1.0, 0.7812, 0.4975]);
        assert_eq!(ColorMap::Copper.rgb(0.9)[0], 1.0);
    }

    #[test]
    fn auto_uses_visible_bins_and_time_with_peak_headroom_and_ignores_invalid_silence() {
        let mut h = history();
        let mut db = vec![-100.0; 513];
        db[32] = 0.0;
        db[4] = f32::NAN;
        db[5] = f32::NEG_INFINITY;
        db[6] = f32::INFINITY;
        push(&mut h, 1024, &db);
        let view = View::full(48000, FrequencyScale::Linear, -120.0);
        assert_eq!(
            h.auto_color_range(view, 5.0),
            Some(ColorRange {
                min: -103.0,
                max: 3.0
            })
        );
        let mut narrow = view;
        narrow.max_hz = 1000.0;
        assert_eq!(
            h.auto_color_range(narrow, 5.0),
            Some(ColorRange {
                min: -109.0,
                max: -97.0
            })
        );
        db.fill(-80.0);
        push(&mut h, 1280, &db);
        assert_eq!(
            h.auto_color_range(view, 256.0 / 48000.0),
            Some(ColorRange {
                min: -89.0,
                max: -77.0
            })
        );
        db.fill(f32::NEG_INFINITY);
        push(&mut h, 1536, &db);
        assert!(h.auto_color_range(view, 256.0 / 48000.0).is_none());
    }

    #[test]
    fn auto_rate_limit_freeze_and_last_valid_fallback_do_not_mutate_history() {
        let mut h = history();
        let view = View::full(48000, FrequencyScale::Linear, -120.0);
        let mut auto = AutoRange::default();
        assert_eq!(auto.update(&h, view, 5.0, 0.0, true), ColorRange::default());
        push(&mut h, 1024, &vec![-80.0; 513]);
        let first = auto.update(&h, view, 5.0, 1.0, true);
        assert_eq!(first.max, -77.0);
        push(&mut h, 1280, &vec![0.0; 513]);
        assert_eq!(auto.update(&h, view, 5.0, 1.1, true), first);
        let peak = auto.update(&h, view, 5.0, 1.3, true);
        assert_eq!(peak.max, 3.0);
        let revision = h.revision();
        for time in [2.0, 3.0, 10.0] {
            assert_eq!(auto.update(&h, view, 5.0, time, false), peak);
        }
        push(&mut h, 1536, &vec![f32::NEG_INFINITY; 513]);
        assert_eq!(auto.update(&h, view, 0.001, 11.0, false), peak);
        assert_eq!(h.revision(), revision + 1);
    }

    #[test]
    fn sampled_noise_floor_never_omits_an_unsampled_peak() {
        let mut h = history();
        let mut db = vec![-120.0; 513];
        for i in 0..super::super::ROWS {
            if i == super::super::ROWS - 1 {
                db[2] = -1.0;
            }
            push(&mut h, 1024 + i as u64 * 256, &db);
        }
        let view = View::full(48000, FrequencyScale::Linear, -120.0);
        assert_eq!(
            h.auto_color_range(view, 60.0),
            Some(ColorRange {
                min: -123.0,
                max: 2.0
            })
        );
    }

    #[test]
    fn zoom_preserves_pointer_frequency_and_pan_preserves_coordinate_span() {
        for scale in [FrequencyScale::Linear, FrequencyScale::Log] {
            let range = FrequencyRange::new(48000, 32768, scale, 100.0, 20000.0);
            let view = range.view(ColorRange::default());
            for fraction in [0.0, 0.25, 0.9, 1.0] {
                let zoom = range.zoom(fraction, 0.5);
                let pivot = view.frequency(fraction as f32);
                let actual = zoom.view(ColorRange::default()).frequency(fraction as f32);
                assert!(
                    (actual - pivot).abs() < 0.01,
                    "{scale:?}: {actual} / {pivot}"
                );
                let pan = zoom.pan(0.05);
                let span = |r: FrequencyRange| r.coordinate(r.max) - r.coordinate(r.min);
                assert!((span(pan) - span(zoom)).abs() < 1e-9);
            }
        }
    }

    #[test]
    fn repeated_zoom_and_pan_respect_dc_log_lower_nyquist_and_one_bin() {
        for size in crate::spectrum::STFT_SIZES {
            for scale in [FrequencyScale::Linear, FrequencyScale::Log] {
                for pointer in [0.0, 0.5, 1.0] {
                    let mut range = FrequencyRange::new(48000, size, scale, 0.0, 0.0);
                    for _ in 0..100 {
                        range = range.zoom(pointer, 0.1).pan(-0.1);
                        assert!(range.min >= 0.0 && range.max <= 24000.0);
                        assert!(range.max - range.min >= range.bin * (1.0 - 1e-9));
                        if scale == FrequencyScale::Log {
                            assert!(range.min > 0.0);
                        }
                    }
                    range = range.pan(1000.0).zoom(pointer, 10.0);
                    assert!(range.max <= 24000.0 && range.min.is_finite());
                }
            }
        }
    }

    #[test]
    fn signed_sample_clock_and_row_lookup_agree_after_long_runs() {
        let origin = 1_u64 << 54;
        let axis = TimeAxis::new(origin + 1024, 48000, 5.0);
        assert_eq!(axis.age(origin + 1025), -1.0 / 48000.0);
        let mut h = history();
        push(&mut h, origin + 1024, &vec![-80.0; 513]);
        assert_eq!(h.at_age(axis.age_at(0.0)).unwrap().0.end, axis.anchor_end);
        assert!(h.at_age(256.0 / 48000.0).is_none());
        let mut placements = Vec::new();
        h.placements(5.0, &mut placements);
        assert_eq!(placements[0].top, axis.fraction(axis.anchor_end));
        assert_eq!(placements[0].bottom, axis.fraction(axis.anchor_end - 256));
    }
}
