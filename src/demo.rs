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
        mut consume: impl FnMut(u64, &[f32]),
    ) {
        for _ in 0..count {
            let mut samples = [0.0; 2];
            for (channel, value) in samples.iter_mut().enumerate() {
                let phase = self.phase + channel as f64 * 0.7;
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
                *value = (signal * self.amplitude as f64 * if channel == 0 { 1.0 } else { 0.65 }
                    + noise * self.noise as f64) as f32;
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
    use crate::spectrum::{Analyzer, Settings, Window};

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
