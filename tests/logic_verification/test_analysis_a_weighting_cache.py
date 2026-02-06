import unittest
import numpy as np
from src.core.analysis import AudioCalc, _compute_a_weighting_sq_curve, _get_a_weighting_curve_from_bytes

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
        # Case where cache should NOT be used (freqs[0] != 0)
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

    def test_cache_hit_fallback(self):
        # Verify that the fallback cache updates for non-linear freqs
        _get_a_weighting_curve_from_bytes.cache_clear()

        sampling_rate = 48000.0
        n_bins = 500
        # Start from 20Hz (non-linear with respect to 0-start assumption of primary cache)
        # Note: actually linspace(20, ...) is linear, but doesn't start at 0.
        # The primary cache requires freqs[0] == 0.
        freqs = np.linspace(20, sampling_rate/2, n_bins)
        mag = np.ones_like(freqs)

        # First call
        AudioCalc.calculate_noise_profile(mag, freqs, sampling_rate)
        info1 = _get_a_weighting_curve_from_bytes.cache_info()

        # Should be a miss (or rather, hits should be 0, total calls 1)
        # Note: lru_cache logic: hits count incremented on subsequent access.

        # Second call
        AudioCalc.calculate_noise_profile(mag, freqs, sampling_rate)
        info2 = _get_a_weighting_curve_from_bytes.cache_info()

        self.assertEqual(info2.hits, info1.hits + 1)

if __name__ == "__main__":
    unittest.main()
