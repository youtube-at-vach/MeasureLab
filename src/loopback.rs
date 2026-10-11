//! Explicit normal-build software source: generator → known DUT → synchronized input.
use std::f64::consts::TAU;
#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Settings {
    pub frequency_hz: f64,
    pub amplitude_peak: f64,
    pub gain: f64,
    /// Positive phase leads the reference; positive delay lags it.
    pub phase_degrees: f64,
    pub delay_samples: u32,
    pub dc_offset: f64,
    pub noise_rms: f64,
    pub frequency_offset_hz: f64,
    pub reference_enabled: bool,
}
impl Default for Settings {
    fn default() -> Self {
        Self {
            frequency_hz: 1000.0,
            amplitude_peak: 0.125,
            gain: 0.5,
            phase_degrees: 30.0,
            delay_samples: 0,
            dc_offset: 0.0,
            noise_rms: 0.0,
            frequency_offset_hz: 0.0,
            reference_enabled: true,
        }
    }
}
impl Settings {
    pub fn validate(&self, rate: u32) -> Result<(), String> {
        crate::audio::validate_sample_rate(rate)?;
        if [
            self.frequency_hz,
            self.amplitude_peak,
            self.gain,
            self.phase_degrees,
            self.dc_offset,
            self.noise_rms,
            self.frequency_offset_hz,
        ]
        .iter()
        .any(|x| !x.is_finite())
            || self.frequency_hz < 10.0
            || self.frequency_hz >= rate as f64 * 0.45
            || !(0.0..=1.0).contains(&self.amplitude_peak)
            || self.gain.abs() > 100.0
            || self.noise_rms < 0.0
            || self.noise_rms > 1.0
            || self.delay_samples > rate * 2
            || (self.frequency_hz + self.frequency_offset_hz) <= 0.0
            || (self.frequency_hz + self.frequency_offset_hz) >= rate as f64 / 2.0
        {
            return Err("Invalid software loopback conditions".into());
        }
        Ok(())
    }
}
pub struct Generator {
    pub settings: Settings,
    sequence: u64,
    random: u64,
}
impl Generator {
    pub fn new(settings: Settings) -> Self {
        Self {
            settings,
            sequence: 0,
            random: 0x8f3a5b7c9d1e2468,
        }
    }
    pub fn advance(&mut self, samples: u64) {
        self.sequence += samples;
    }
    pub fn next_frame(&mut self, rate: u32) -> [f64; 2] {
        let s = &self.settings;
        let n = self.sequence as f64;
        self.sequence += 1;
        let reference = if s.reference_enabled {
            s.amplitude_peak * (TAU * s.frequency_hz * n / rate as f64).sin()
        } else {
            0.0
        };
        self.random ^= self.random << 13;
        self.random ^= self.random >> 7;
        self.random ^= self.random << 17;
        let noise = ((self.random >> 11) as f64 / (1u64 << 53) as f64 * 2.0 - 1.0)
            * 3.0_f64.sqrt()
            * s.noise_rms;
        // Closed-form delayed sine is the exact output of a gain/delay/phase DUT;
        // zero prehistory is retained until the delay has elapsed.
        let response = if n < s.delay_samples as f64 {
            0.0
        } else {
            s.amplitude_peak
                * s.gain
                * (TAU * (s.frequency_hz + s.frequency_offset_hz) * (n - s.delay_samples as f64)
                    / rate as f64
                    + s.phase_degrees.to_radians())
                .sin()
        };
        [reference, response + s.dc_offset + noise]
    }
}
