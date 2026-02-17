import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../')))
import unittest
import numpy as np
from src.core.analysis import AudioCalc, _compute_a_weighting_sq_curve, _get_a_weighting_curve_from_bytes, _compute_a_weighting_sq_curve_log

class TestAWeightingCache(unittest.TestCase):
    def test_a_weighting_standard_fft(self):
        # Case where cache should be used (freqs[0]==0)
        sampling_rate = 48000.0
        n_bins = 1000
        freqs = np.linspace(0, sampling_rate/2, n_bins)
        mag = np.ones_like(freqs) # Flat magnitude

        # Run method
        results = AudioCalc.calculate_noise_profile(mag, freqs, sampling_rate)

        # Manually calculate A-weighting rms
        f = freqs
        f2 = f**2
        const = 12194**2 * f**4
        denom = (f2 + 20.6**2) * np.sqrt((f2 + 107.7**2) * (f2 + 737.9**2)) * (f2 + 12194**2)
        denom[denom == 0] = 1.0
        Ra = const / denom
        weighting_linear = Ra * 1.2589
        mag_a = mag * weighting_linear

        i_a_start = np.searchsorted(freqs, 20.0, side='left')
        i_a_end = np.searchsorted(freqs, 20000.0, side='right')
        bin_width = freqs[1] - freqs[0]
        expected_rms = np.sqrt(np.sum(mag_a[i_a_start:i_a_end]**2) * bin_width)

        self.assertAlmostEqual(results['noise_rms_a_weighted'], expected_rms, places=6)

    def test_a_weighting_non_standard(self):
        # Case where linear cache should be used (freqs[0] != 0 but linear)
        sampling_rate = 48000.0
        n_bins = 1000
        # Start from 20Hz
        freqs = np.linspace(20, sampling_rate/2, n_bins)
        mag = np.ones_like(freqs)

        results = AudioCalc.calculate_noise_profile(mag, freqs, sampling_rate)

        # Manual check
        f = freqs
        f2 = f**2
        const = 12194**2 * f**4
        denom = (f2 + 20.6**2) * np.sqrt((f2 + 107.7**2) * (f2 + 737.9**2)) * (f2 + 12194**2)
        denom[denom == 0] = 1.0
        Ra = const / denom
        weighting_linear = Ra * 1.2589
        mag_a = mag * weighting_linear

        i_a_start = np.searchsorted(freqs, 20.0, side='left')
        i_a_end = np.searchsorted(freqs, 20000.0, side='right')
        bin_width = freqs[1] - freqs[0]
        expected_rms = np.sqrt(np.sum(mag_a[i_a_start:i_a_end]**2) * bin_width)

        self.assertAlmostEqual(results['noise_rms_a_weighted'], expected_rms, places=6)

    def test_cache_hit(self):
        # Verify that the cache info updates
        _compute_a_weighting_sq_curve.cache_clear()

        sampling_rate = 48000.0
        n_bins = 500
        freqs = np.linspace(0, sampling_rate/2, n_bins)
        mag = np.ones_like(freqs)

        # First call
        AudioCalc.calculate_noise_profile(mag, freqs, sampling_rate)
        info1 = _compute_a_weighting_sq_curve.cache_info()

        # Second call
        AudioCalc.calculate_noise_profile(mag, freqs, sampling_rate)
        info2 = _compute_a_weighting_sq_curve.cache_info()

        self.assertEqual(info2.hits, info1.hits + 1)

    def test_cache_hit_linear_non_zero_start(self):
        # Verify that linear cache is used even for non-zero start
        _compute_a_weighting_sq_curve.cache_clear()
        _get_a_weighting_curve_from_bytes.cache_clear()

        sampling_rate = 48000.0
        n_bins = 500
        # Start from 20Hz (linear step)
        freqs = np.linspace(20, sampling_rate/2, n_bins)
        mag = np.ones_like(freqs)

        # First call
        AudioCalc.calculate_noise_profile(mag, freqs, sampling_rate)
        info1 = _compute_a_weighting_sq_curve.cache_info()
        info_bytes1 = _get_a_weighting_curve_from_bytes.cache_info()

        # Should be a HIT/MISS on linear cache (1 call)
        # And 0 calls on bytes cache
        self.assertEqual(info1.misses, 1)
        self.assertEqual(info_bytes1.hits + info_bytes1.misses, 0)

        # Second call
        AudioCalc.calculate_noise_profile(mag, freqs, sampling_rate)
        info2 = _compute_a_weighting_sq_curve.cache_info()

        self.assertEqual(info2.hits, 1)

    def test_cache_hit_log(self):
        # Verify that the LOG cache updates for log freqs
        _compute_a_weighting_sq_curve_log.cache_clear()

        sampling_rate = 48000.0
        n_bins = 500
        start_freq = 20.0
        stop_freq = sampling_rate/2
        freqs = np.geomspace(start_freq, stop_freq, n_bins)
        mag = np.ones_like(freqs)

        # First call
        AudioCalc.calculate_noise_profile(mag, freqs, sampling_rate)
        info1 = _compute_a_weighting_sq_curve_log.cache_info()

        self.assertEqual(info1.misses, 1)

        # Second call
        AudioCalc.calculate_noise_profile(mag, freqs, sampling_rate)
        info2 = _compute_a_weighting_sq_curve_log.cache_info()

        self.assertEqual(info2.hits, 1)

    def test_cache_hit_arbitrary(self):
        _get_a_weighting_curve_from_bytes.cache_clear()

        # Random arbitrary
        freqs = np.sort(np.random.uniform(20, 20000, 500))
        mag = np.ones_like(freqs)

        # First call
        AudioCalc.calculate_noise_profile(mag, freqs, 48000)
        info1 = _get_a_weighting_curve_from_bytes.cache_info()

        self.assertEqual(info1.misses, 1)

        # Second call (same array content)
        AudioCalc.calculate_noise_profile(mag, freqs, 48000)
        info2 = _get_a_weighting_curve_from_bytes.cache_info()

        self.assertEqual(info2.hits, 1)

if __name__ == "__main__":
    unittest.main()
