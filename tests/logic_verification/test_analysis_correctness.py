
import unittest
import numpy as np
from src.core.analysis import AudioCalc

class TestAudioCalcNoiseProfile(unittest.TestCase):
    def test_hum_detection(self):
        # Create spectrum with 50Hz hum
        sampling_rate = 1000.0 # Low SR for speed
        N = 2000
        freqs = np.linspace(0, sampling_rate/2, N//2 + 1)
        mag = np.ones_like(freqs) * 1e-6 # Low noise floor

        # Inject 50Hz and harmonics
        # 50Hz
        idx_50 = np.searchsorted(freqs, 50.0)
        mag[idx_50-1:idx_50+2] = 0.1 # Peak

        # 150Hz (3rd harmonic)
        idx_150 = np.searchsorted(freqs, 150.0)
        mag[idx_150-1:idx_150+2] = 0.05

        results = AudioCalc.calculate_noise_profile(mag, freqs, sampling_rate)

        self.assertAlmostEqual(results['hum_freq'], 50.0)
        self.assertGreater(results['hum_rms'], 0.0)

        # Check components
        components = results['hum_components']
        self.assertTrue(len(components) > 0)
        self.assertAlmostEqual(components[0][0], 50.0)

    def test_white_noise_estimation(self):
        # Create white noise spectrum (flat)
        sampling_rate = 48000.0
        N = 48000
        freqs = np.linspace(0, sampling_rate/2, N//2 + 1)
        # Density = 1e-4 V/rtHz
        mag = np.ones_like(freqs) * 1e-4

        results = AudioCalc.calculate_noise_profile(mag, freqs, sampling_rate)

        # Allow some margin because median estimate factor is approx
        # For flat magnitude, median = mean = 1e-4.
        # But the function multiplies by 1.2011 (assuming Rayleigh).
        # Wait, if input is constant 1e-4, median is 1e-4.
        # Expected result = 1e-4 * 1.2011

        expected = 1e-4 * 1.2011
        self.assertAlmostEqual(results['white_density'], expected, delta=expected*0.1)

    def test_masking_logic_correctness(self):
        # Ensure that hum masking actually excludes hum from fit
        # If we have a huge hum peak, it shouldn't ruin 1/f fit (which is low freq)

        sampling_rate = 1000.0
        N = 2000
        freqs = np.linspace(0, sampling_rate/2, N//2 + 1)

        # 1/f noise: 1/f
        # At 10Hz = 0.1, at 100Hz = 0.01
        # Avoid zero freq
        safe_freqs = freqs.copy()
        safe_freqs[0] = 1e-9
        mag = 1.0 / safe_freqs

        # Inject huge hum at 50Hz (within 1/f range 1-100Hz)
        idx_50 = np.searchsorted(freqs, 50.0)
        mag[idx_50-2:idx_50+3] = 1000.0 # Huge peak

        results = AudioCalc.calculate_noise_profile(mag, freqs, sampling_rate)

        # The slope should be approx -1 (log10(1/f) = -log10(f))
        # log(mag) = -1 * log(freq)
        self.assertAlmostEqual(results['flicker_slope'], -1.0, delta=0.2)

        # If masking failed, the 50Hz peak would pull the slope up or down significantly or ruin fit

if __name__ == "__main__":
    unittest.main()
