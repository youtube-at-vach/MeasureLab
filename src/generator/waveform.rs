use super::{PI, TAU};

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub enum Waveform {
    #[default]
    Sine,
    Square,
    Triangle,
    Noise,
}

impl Waveform {
    pub const ALL: [Self; 4] = [Self::Sine, Self::Square, Self::Triangle, Self::Noise];
    pub fn label(self) -> &'static str {
        match self {
            Self::Sine => "Sine",
            Self::Square => "Square",
            Self::Triangle => "Triangle",
            Self::Noise => "Noise",
        }
    }
    /// Square uses a Fejer-weighted Fourier series (bounded by unity).
    /// Triangle normalizes its retained odd harmonics to unity at the peak.
    /// Both retain at most 16 odd harmonics strictly below 0.45 Fs.
    pub fn periodic(self, cycles: f64, hz: f64, rate: u32) -> f64 {
        let angle = TAU * cycles.rem_euclid(1.0);
        if !matches!(self, Self::Square | Self::Triangle) {
            return angle.sin();
        }
        let count = (1..=31)
            .step_by(2)
            .take_while(|&k| k as f64 * hz < 0.45 * rate as f64)
            .count()
            .max(1);
        let (mut sin, mut cos) = angle.sin_cos();
        let (sin2, cos2) = (2.0 * angle).sin_cos();
        let mut sum = 0.0;
        let mut norm = 0.0;
        for j in 0..count {
            let k = (2 * j + 1) as f64;
            match self {
                Self::Square => sum += (1.0 - k / (2 * count) as f64) * sin / k * 4.0 / PI,
                _ => {
                    let weight = 1.0 / (k * k);
                    // Python's triangle starts at its positive peak at 0°.
                    sum += cos * weight;
                    norm += weight;
                }
            }
            (sin, cos) = (sin * cos2 + cos * sin2, cos * cos2 - sin * sin2);
        }
        if self == Self::Triangle {
            sum / norm
        } else {
            sum
        }
    }
}

pub(super) fn noise(state: &mut u64) -> f64 {
    *state ^= *state >> 12;
    *state ^= *state << 25;
    *state ^= *state >> 27;
    let bits = state.wrapping_mul(0x2545_f491_4f6c_dd1d) >> 11;
    2.0 * bits as f64 / (1_u64 << 53) as f64 - 1.0
}
