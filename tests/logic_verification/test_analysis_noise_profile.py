import unittest
import numpy as np
from src.core.analysis import AudioCalc

class TestNoiseProfile(unittest.TestCase):
    def setUp(self):
        self.fs = 48000
        self.n_fft = 32768  # Higher resolution (~1.46 Hz bins)
        self.freqs = np.fft.rfftfreq(self.n_fft, 1/self.fs)
        # Create a basic magnitude spectrum (flat white noise)
        self.mag_white = np.ones_like(self.freqs) * 1e-7 # 100 nV/rtHz

    def test_white_noise_profile(self):
        results = AudioCalc.calculate_noise_profile(self.mag_white, self.freqs, self.fs)

        # White noise density should be approx 1e-7 * 1.2011 (correction factor in code)
        expected_density = 1e-7 * 1.2011
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
