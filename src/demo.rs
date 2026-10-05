//! Deterministic internal source, never sent to an audio output device.
use crate::signal::History;
use std::f64::consts::TAU;

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum Waveform {
    Sine,
    #[default]
    Harmonics,
    Square,
}

impl Waveform {
    pub fn name(self) -> &'static str {
        match self {
            Self::Sine => "Sine",
            Self::Harmonics => "Sine + harmonics",
            Self::Square => "Band-limited square",
        }
    }
}

pub struct Demo {
    pub waveform: Waveform,
    pub frequency: f32,
    pub amplitude: f32,
    pub noise: f32,
    pub phase_degrees: f64,
    pub channel_2_gain: f64,
    phase: f64,
    random: u32,
}

impl Default for Demo {
    fn default() -> Self {
        Self {
            waveform: Waveform::Harmonics,
            frequency: 1000.0,
            amplitude: 0.7,
            noise: 0.0002,
            phase_degrees: 0.7_f64.to_degrees(),
            channel_2_gain: 0.65,
            phase: 0.0,
            random: 0x12345678,
        }
    }
}

impl Demo {
    pub fn append(&mut self, history: &mut History, count: usize, sample_rate: u32) {
        self.append_with(history, count, sample_rate, |_, _| {});
    }

    pub fn append_with(
        &mut self,
        history: &mut History,
        count: usize,
        sample_rate: u32,
        mut consume: impl FnMut(u64, &[f64]),
    ) {
        for _ in 0..count {
            let mut samples = [0.0; 2];
            for (channel, value) in samples.iter_mut().enumerate() {
                let phase = self.phase + channel as f64 * self.phase_degrees.to_radians();
                let mut signal = phase.sin();
                match self.waveform {
                    Waveform::Sine => {}
                    Waveform::Harmonics => {
                        for (harmonic, level) in [(2, 0.12), (3, 0.045), (5, 0.015), (7, 0.006)] {
                            if harmonic as f32 * self.frequency < sample_rate as f32 * 0.5 {
                                signal += level * (harmonic as f64 * phase).sin();
                            }
                        }
                    }
                    Waveform::Square => {
                        for harmonic in (3..=63).step_by(2) {
                            if harmonic as f32 * self.frequency >= sample_rate as f32 * 0.5 {
                                break;
                            }
                            signal += (harmonic as f64 * phase).sin() / harmonic as f64;
                        }
                        signal *= 4.0 / std::f64::consts::PI;
                    }
                }
                self.random ^= self.random << 13;
                self.random ^= self.random >> 17;
                self.random ^= self.random << 5;
                let noise = self.random as f64 / u32::MAX as f64 * 2.0 - 1.0;
                *value = signal
                    * self.amplitude as f64
                    * if channel == 0 {
                        1.0
                    } else {
                        self.channel_2_gain
                    }
                    + noise * self.noise as f64;
            }
            let sequence = history.range().end;
            history.push(samples);
            consume(sequence, &samples);
            self.phase = (self.phase + TAU * self.frequency as f64 / sample_rate as f64) % TAU;
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::signal::{Trigger, build_sweep_lines};
    use crate::spectrum::{Analyzer, Settings, Window};

    #[test]
    fn noisy_zero_trigger_keeps_subsample_alignment() {
        let mut demo = Demo::default();
        let mut history = History::new(2048);
        let mut lines = Vec::new();
        let mut min = f64::INFINITY;
        let mut max = f64::NEG_INFINITY;
        let mut amplitude_min = [f64::INFINITY; 2];
        let mut amplitude_max = [f64::NEG_INFINITY; 2];
        for _ in 0..128 {
            demo.append(&mut history, 800, 48000);
            let sweep = history.sweep(480, Trigger::default());
            assert!(sweep.triggered);
            build_sweep_lines(&history, &sweep, 1000, 0.25, [true; 2], &mut lines);
            // Locate the rendered rising zero crossing nearest the trigger.
            let crossing = lines
                .iter()
                .filter(|line| line.channel == 0 && line.a[1] > 0.5 && line.b[1] <= 0.5)
                .map(|line| {
                    let fraction = (line.a[1] as f64 - 0.5) / (line.a[1] as f64 - line.b[1] as f64);
                    (line.a[0] as f64 + fraction * (line.b[0] as f64 - line.a[0] as f64)) * 479.0
                })
                .min_by(|a, b| (a - 96.0).abs().total_cmp(&(b - 96.0).abs()))
                .unwrap();
            min = min.min(crossing);
            max = max.max(crossing);
            assert!((crossing - 96.0).abs() < 0.001);
            // Both displayed channels must stay stable away from the trigger,
            // too. Small genuine noise remains, without sample-sized jumps.
            let x = (96.0 + 5.5) / 479.0;
            for channel in 0..2 {
                let line = lines
                    .iter()
                    .find(|line| line.channel == channel && line.a[0] <= x && line.b[0] >= x)
                    .unwrap();
                let fraction = (x - line.a[0]) / (line.b[0] - line.a[0]);
                let amplitude =
                    (0.5 - (line.a[1] + fraction * (line.b[1] - line.a[1]))) as f64 * 2.0;
                amplitude_min[channel] = amplitude_min[channel].min(amplitude);
                amplitude_max[channel] = amplitude_max[channel].max(amplitude);
            }
        }
        assert!(max - min < 0.01, "trigger moved by {} samples", max - min);
        for channel in 0..2 {
            assert!(amplitude_max[channel] - amplitude_min[channel] < 0.002);
        }
    }

    #[test]
    fn chunked_generation_keeps_phase_and_noise_continuous() {
        let mut a = Demo::default();
        let mut b = Demo::default();
        let mut whole = History::new(2048);
        let mut chunks = History::new(2048);
        a.append(&mut whole, 2048, 48000);
        b.append(&mut chunks, 711, 48000);
        b.append(&mut chunks, 1337, 48000);
        for i in whole.range() {
            assert_eq!(whole.get(i), chunks.get(i));
        }
    }

    #[test]
    fn xy_phase_presets_and_channel_gain_produce_known_sample_pairs() {
        for phase in [0.0, 90.0, 180.0] {
            let mut demo = Demo {
                waveform: Waveform::Sine,
                frequency: 1000.0,
                amplitude: 0.5,
                noise: 0.0,
                phase_degrees: phase,
                channel_2_gain: 1.0,
                ..Demo::default()
            };
            let mut history = History::new(48);
            demo.append(&mut history, 13, 48000);
            let initial = history.get(0).unwrap();
            let quarter = history.get(12).unwrap();
            assert!(initial[0].abs() < 1e-12);
            assert!((quarter[0] - 0.5).abs() < 1e-12);
            match phase {
                0.0 => assert!((quarter[1] - 0.5).abs() < 1e-12),
                90.0 => {
                    assert!((initial[1] - 0.5).abs() < 1e-12);
                    assert!(quarter[1].abs() < 1e-12);
                }
                _ => assert!((quarter[1] + 0.5).abs() < 1e-12),
            }
            demo.channel_2_gain = 0.5;
            demo.append(&mut history, 48, 48000);
            let rms = (history
                .samples(history.range())
                .map(|frame| frame[1].powi(2))
                .sum::<f64>()
                / 48.0)
                .sqrt();
            assert!((rms - 0.25 / 2.0_f64.sqrt()).abs() < 1e-12);
        }
    }

    #[test]
    fn square_omits_harmonics_above_nyquist() {
        let mut demo = Demo {
            waveform: Waveform::Square,
            frequency: 9000.0,
            amplitude: 0.5,
            noise: 0.0,
            ..Demo::default()
        };
        let mut h = History::new(1024);
        demo.append(&mut h, 1024, 48000);
        let mut analyzer = Analyzer::new(
            Settings {
                size: 1024,
                window: Window::Rectangular,
                ..Settings::default()
            },
            48000,
        );
        analyzer.update(&h, 0);
        let expected = 20.0 * (2.0 / std::f32::consts::PI).log10();
        assert!((analyzer.db()[192] - expected).abs() < 0.002);
        // A naive square's third harmonic at 27 kHz aliases into 21 kHz.
        assert!(analyzer.db()[448] < -120.0);
    }
}
