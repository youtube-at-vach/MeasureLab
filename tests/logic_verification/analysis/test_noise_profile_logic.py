import unittest
import numpy as np
import sys
import os

# Ensure repo root is in path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from src.core.analysis import AudioCalc, RAYLEIGH_RMS_FACTOR

class TestNoiseProfileLogic(unittest.TestCase):
    def setUp(self):
        self.fs = 48000
        self.n_fft = 32768  # Higher resolution (~1.46 Hz bins)
        self.freqs = np.fft.rfftfreq(self.n_fft, 1/self.fs)
        # Create a basic magnitude spectrum (flat white noise)
        self.mag_white = np.ones_like(self.freqs) * 1e-7 # 100 nV/rtHz

    # From test_analysis_noise_profile.py
    def test_white_noise_profile(self):
        results = AudioCalc.calculate_noise_profile(self.mag_white, self.freqs, self.fs)

        # White noise density should be approx 1e-7 * RAYLEIGH_RMS_FACTOR (correction factor in code)
        expected_density = 1e-7 * RAYLEIGH_RMS_FACTOR
        self.assertAlmostEqual(results['white_density'], expected_density, delta=1e-9)

        # Hum should be negligible (sum of 10 harmonics integration of noise floor)
        # Approx RMS ~ sqrt(10 * (1e-7)^2 * 10Hz) ~ sqrt(1e-12) ~ 1e-6
        self.assertLess(results['hum_rms'], 5e-6)

        # Flicker slope should be near 0
        self.assertAlmostEqual(results['flicker_slope'], 0.0, delta=0.1)

    def test_hum_detection_50hz(self):
        mag = self.mag_white.copy()
        # Inject 50Hz hum
        # With 1.46Hz bins, 50Hz is around bin 34
        # 50 / 1.46 = 34.1
        idx_50 = np.searchsorted(self.freqs, 50.0)

        # Inject narrow peak
        mag[idx_50] = 1e-3

        results = AudioCalc.calculate_noise_profile(mag, self.freqs, self.fs)

        self.assertEqual(results['hum_freq'], 50.0)
        self.assertGreater(results['hum_rms'], 1e-4)

    def test_hum_detection_60hz(self):
        mag = self.mag_white.copy()
        # Inject 60Hz hum
        idx_60 = np.searchsorted(self.freqs, 60.0)
        mag[idx_60] = 1e-3

        results = AudioCalc.calculate_noise_profile(mag, self.freqs, self.fs)

        self.assertEqual(results['hum_freq'], 60.0)

    def test_1f_noise(self):
        # Generate 1/f noise spectrum
        # PSD ~ 1/f => Mag ~ 1/sqrt(f)
        mag = self.mag_white.copy()
        valid_mask = self.freqs > 0
        # Use stronger 1/f to dominate white noise
        mag[valid_mask] = 1e-5 / np.sqrt(self.freqs[valid_mask])
        mag[0] = mag[1] # Handle DC

        results = AudioCalc.calculate_noise_profile(mag, self.freqs, self.fs)

        self.assertAlmostEqual(results['flicker_slope'], -0.5, delta=0.1)

    def test_integrated_noise(self):
        results = AudioCalc.calculate_noise_profile(self.mag_white, self.freqs, self.fs)

        bin_width = self.freqs[1] - self.freqs[0]
        idx_start = np.searchsorted(self.freqs, 20.0)
        idx_end = np.searchsorted(self.freqs, 20000.0)

        expected_rms = np.sqrt(np.sum(self.mag_white[idx_start:idx_end]**2) * bin_width)

        # Relax tolerance slightly due to integration implementation details (searchsorted vs get_index)
        # get_index uses searchsorted but handles edges
        self.assertAlmostEqual(results['noise_rms_20k'], expected_rms, delta=1e-7)

    def test_peak_noise(self):
        mag = self.mag_white.copy()
        idx_1k = np.searchsorted(self.freqs, 1000.0)
        mag[idx_1k] = 2e-6

        results = AudioCalc.calculate_noise_profile(mag, self.freqs, self.fs)

        self.assertAlmostEqual(results['peak_freq'], self.freqs[idx_1k], delta=self.freqs[1])
        self.assertAlmostEqual(results['peak_amp'], 2e-6, delta=1e-9)

    def test_a_weighting(self):
        results = AudioCalc.calculate_noise_profile(self.mag_white, self.freqs, self.fs)
        self.assertIn('noise_rms_a_weighted', results)
        self.assertGreater(results['noise_rms_a_weighted'], 0)

    # From test_analysis_correctness.py
    def test_hum_detection_harmonics(self):
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

    def test_white_noise_estimation_high_level(self):
        # Create white noise spectrum (flat)
        sampling_rate = 48000.0
        N = 48000
        freqs = np.linspace(0, sampling_rate/2, N//2 + 1)
        # Density = 1e-4 V/rtHz
        mag = np.ones_like(freqs) * 1e-4

        results = AudioCalc.calculate_noise_profile(mag, freqs, sampling_rate)

        # Allow some margin because median estimate factor is approx
        # For flat magnitude, median = mean = 1e-4.
        # But the function multiplies by RAYLEIGH_RMS_FACTOR (assuming Rayleigh).
        # Wait, if input is constant 1e-4, median is 1e-4.
        # Expected result = 1e-4 * RAYLEIGH_RMS_FACTOR

        expected = 1e-4 * RAYLEIGH_RMS_FACTOR
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

    def test_1f_noise_insufficient_data(self):
        # Create a scenario where the 1/f fit region has <= 5 points
        # Freq step 2.0 Hz. Range 1.0 - 6.0 Hz contains [2.0, 4.0, 6.0] (3 points)
        # We need knee detection to clamp f_max_fit to 6.0 Hz

        freqs = np.arange(0, 22000, 2.0)
        mag = np.ones_like(freqs) * 1e-9 # Low background

        # Inject "slope" points that are high but drop quickly
        idx_2 = np.searchsorted(freqs, 2.0)
        idx_4 = np.searchsorted(freqs, 4.0)

        mag[idx_2] = 1e-3
        mag[idx_4] = 1e-5
        # mag at 6.0 Hz remains 1e-9, which should trigger knee if white density is higher than ~5e-10

        # White density from 1k-20k (median of 1e-9) is ~1.2e-9.
        # Knee threshold ~ 2.4e-9.
        # mag[idx_6] (1e-9) < 2.4e-9. So knee at 6.0 Hz.
        # f_max_fit = max(6.0, 5.0) = 6.0.
        # Points in [1.0, 6.0]: 2.0, 4.0, 6.0. Count = 3.
        # 3 <= 5.

        results = AudioCalc.calculate_noise_profile(mag, freqs, self.fs)

        # Should fallback to 0.0 despite the clear slope in first few points
        self.assertEqual(results['flicker_slope'], 0.0)
        self.assertEqual(results['flicker_intercept'], 0.0)
        self.assertEqual(results['corner_freq'], 0.0)

    def test_zero_frequency_step_handling(self):
        """
        Regression test for potential DivisionByZero/OverflowError when frequency step is 0.
        Caused by _analyze_frequency_axis incorrectly flagging constant frequency array as linear.
        """
        freqs = np.array([100.0, 100.0, 100.0], dtype=np.float64)
        mag = np.array([0.5, 0.5, 0.5], dtype=np.float64)

        # This calls calculate_noise_profile -> _analyze_frequency_axis
        # Should complete without error
        try:
            results = AudioCalc.calculate_noise_profile(mag, freqs, self.fs)
        except Exception as e:
            self.fail(f"calculate_noise_profile raised exception with zero-step frequency array: {e}")

        # Verify that it didn't return garbage or crash
        # With non-linear handling, it should fallback to robust methods
        self.assertIn("white_density", results)

if __name__ == '__main__':
    unittest.main()
