//! Optional TPDF dither and fixed-depth quantization at the device boundary.
//! Generator math and the internal f64 loopback remain full precision.
use super::device::Pcm;

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub enum BitDepth {
    #[serde(rename = "8")]
    Bits8,
    #[serde(rename = "16")]
    Bits16,
    #[default]
    #[serde(rename = "24")]
    Bits24,
}

impl BitDepth {
    pub const ALL: [Self; 3] = [Self::Bits8, Self::Bits16, Self::Bits24];

    pub fn bits(self) -> u32 {
        match self {
            Self::Bits8 => 8,
            Self::Bits16 => 16,
            Self::Bits24 => 24,
        }
    }

    pub fn label(self) -> &'static str {
        match self {
            Self::Bits8 => "8-bit",
            Self::Bits16 => "16-bit",
            Self::Bits24 => "24-bit",
        }
    }

    pub fn supported(self, pcm: Pcm) -> bool {
        let bits = match pcm {
            Pcm::I8 | Pcm::U8 => 8,
            Pcm::I16 | Pcm::U16 => 16,
            _ => 24,
        };
        self.bits() <= bits
    }
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Dither {
    pub enabled: bool,
    pub bit_depth: BitDepth,
}

impl Dither {
    pub fn validate(self, pcm: Pcm) -> Result<(), String> {
        if self.enabled && !self.bit_depth.supported(pcm) {
            return Err("Dithering bit depth exceeds the output PCM precision".into());
        }
        Ok(())
    }

    /// Keep the selected depth representable when the user changes PCM.
    pub fn for_pcm(mut self, pcm: Pcm) -> Self {
        if !self.bit_depth.supported(pcm) {
            self.bit_depth = match pcm {
                Pcm::I8 | Pcm::U8 => BitDepth::Bits8,
                _ => BitDepth::Bits16,
            };
        }
        self
    }
}

pub(super) struct Quantizer {
    enabled: bool,
    scale: f64,
    // Each OUT has its own sequence, independent of callback partitioning,
    // other OUTs and the Generator's noise waveform seed. Reopened streams
    // replay the same dither sequence for reproducible known-input tests.
    random: [u64; crate::signal::MAX_CHANNELS],
}

impl Quantizer {
    pub(super) fn new(settings: Dither) -> Self {
        Self {
            enabled: settings.enabled,
            scale: (1_u32 << (settings.bit_depth.bits() - 1)) as f64,
            random: std::array::from_fn(|ch| ch as u64),
        }
    }

    pub(super) fn apply(&mut self, sample: f64, channel: usize, active: bool) -> f64 {
        if !self.enabled || !active {
            return sample;
        }
        let state = &mut self.random[channel];
        let tpdf = uniform(state) - uniform(state);
        // Match the legacy round-to-nearest-even quantizer. Values lie on a
        // binary grid exactly representable in f32 and all supported wider PCM.
        (sample * self.scale + tpdf)
            .round_ties_even()
            .clamp(-self.scale, self.scale - 1.0)
            / self.scale
    }
}

/// SplitMix64: fixed-cost, allocation-free draws in [0, 1).
fn uniform(state: &mut u64) -> f64 {
    *state = state.wrapping_add(0x9e37_79b9_7f4a_7c15);
    let mut bits = *state;
    bits = (bits ^ (bits >> 30)).wrapping_mul(0xbf58_476d_1ce4_e5b9);
    bits = (bits ^ (bits >> 27)).wrapping_mul(0x94d0_49bb_1331_11eb);
    ((bits ^ (bits >> 31)) >> 11) as f64 / (1_u64 << 53) as f64
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn tpdf_quantization_is_unbiased_with_signal_independent_error_power() {
        for bit_depth in BitDepth::ALL {
            for fraction in [0.0, 0.1, 0.25, 0.5, 0.9, -0.1, -0.5, -0.9] {
                let mut q = Quantizer::new(Dither {
                    enabled: true,
                    bit_depth,
                });
                let sample = fraction / q.scale;
                let mut sum = 0.0;
                let mut squares = 0.0;
                const COUNT: usize = 131_072;
                for _ in 0..COUNT {
                    let output = q.apply(sample, 0, true);
                    let code = output * q.scale;
                    assert_eq!(code, code.round());
                    let error = code - fraction;
                    assert!(error.abs() <= 1.5);
                    sum += error;
                    squares += error * error;
                }
                // Non-subtractive 2-LSB peak-to-peak TPDF plus nearest
                // quantization has zero mean and 1/4 LSB² error power.
                assert!(
                    (sum / COUNT as f64).abs() < 0.008,
                    "{bit_depth:?} {fraction}"
                );
                assert!((squares / COUNT as f64 - 0.25).abs() < 0.01);
                assert!((-1.0..=-1.0 + 1.0 / q.scale).contains(&q.apply(-1.0, 0, true)));
                assert_eq!(q.apply(1.0, 0, true), 1.0 - 1.0 / q.scale);
            }
        }
    }

    #[test]
    fn channels_are_independent_reproducible_and_do_not_share_noise_state() {
        let settings = Dither {
            enabled: true,
            bit_depth: BitDepth::Bits24,
        };
        let mut stereo = Quantizer::new(settings);
        let mut single = Quantizer::new(settings);
        let mut replay = Quantizer::new(settings);
        let mut cross = 0.0;
        let mut different = 0;
        for _ in 0..65_536 {
            let a = stereo.apply(0.0, 0, true);
            let b = stereo.apply(0.0, 1, true);
            assert_eq!(a, single.apply(0.0, 0, true));
            assert_eq!(a, replay.apply(0.0, 0, true));
            assert_eq!(b, replay.apply(0.0, 1, true));
            different += usize::from(a != b);
            cross += a * b * stereo.scale * stereo.scale;
        }
        assert!(different > 10_000);
        assert!((cross / 65_536.0).abs() < 0.01);
    }

    #[test]
    fn bypass_and_inactive_outputs_preserve_samples_and_random_state() {
        let mut bypass = Quantizer::new(Dither::default());
        let mut active = Quantizer::new(Dither {
            enabled: true,
            ..Dither::default()
        });
        let initial = active.random;
        for sample in [-1.0, -0.12345, -0.0, 0.0, 0.12345, 1.0] {
            assert_eq!(bypass.apply(sample, 0, true).to_bits(), sample.to_bits());
            assert_eq!(active.apply(sample, 0, false).to_bits(), sample.to_bits());
        }
        assert_eq!(active.random, initial);
    }

    #[test]
    fn depth_validation_and_pcm_changes_preserve_representable_choices() {
        for pcm in [
            Pcm::F32,
            Pcm::F64,
            Pcm::I8,
            Pcm::U8,
            Pcm::I16,
            Pcm::U16,
            Pcm::I24,
            Pcm::U24,
            Pcm::I32,
            Pcm::U32,
            Pcm::I64,
            Pcm::U64,
        ] {
            for bit_depth in BitDepth::ALL {
                let settings = Dither {
                    enabled: true,
                    bit_depth,
                };
                assert_eq!(settings.validate(pcm).is_ok(), bit_depth.supported(pcm));
                let adjusted = settings.for_pcm(pcm);
                adjusted.validate(pcm).unwrap();
                assert!(adjusted.bit_depth.bits() <= bit_depth.bits());
                assert!(
                    Dither {
                        enabled: false,
                        bit_depth
                    }
                    .validate(pcm)
                    .is_ok()
                );
            }
        }
        assert!(serde_json::from_str::<Dither>(r#"{"enabled":true,"bit_depth":"32"}"#).is_err());
    }
}
