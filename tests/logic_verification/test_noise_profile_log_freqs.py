import unittest
from unittest.mock import patch
import numpy as np
from src.core.analysis import AudioCalc

class TestNoiseProfileLogFreqs(unittest.TestCase):
    def setUp(self):
        # Common setup if needed
        self.sampling_rate = 48000.0

    def test_log_frequency_detection(self):
        """
        Verifies that logarithmic frequency spacing is detected and uses the optimized path.
        """
        # Create a logarithmic frequency array
        # 1000 points from 20Hz to 20kHz
        freqs = np.geomspace(20.0, 20000.0, 1000)

        # Create a dummy magnitude array (e.g., flat noise floor)
        mag = np.ones_like(freqs) * 1e-6  # 1uV/rtHz

        # Spy on the log weighting curve function to ensure it's called
        with patch('src.core.analysis._compute_a_weighting_sq_curve_log') as mock_log_curve, \
             patch('src.core.analysis._compute_a_weighting_sq_curve') as mock_lin_curve:
            # We need the mock to return actual data so calculations don't fail
            # The original function is wrapped in lru_cache, so patching it might be tricky if not careful.
            # However, patching the module level name 'src.core.analysis._compute_a_weighting_sq_curve_log'
            # should replace the cached function object with the mock.
            # We must set side_effect to the original function if we want real results,
            # OR just return a valid array of correct shape.

            # Let's use a side_effect that just returns ones, or we can try to wrap the original.
            # Easier: just return ones of correct size, as we only care that it's called
            # and that calculate_noise_profile doesn't crash.
            # Actually, to be safe for "valid data" assertions, let's try to mimic basic behavior or return ones.
            # AudioCalc expects (ra * gain)**2.

            mock_log_curve.return_value = np.ones(len(freqs))

            results = AudioCalc.calculate_noise_profile(mag, freqs, self.sampling_rate)

            # Assertions
            self.assertTrue(mock_log_curve.called, "Logarithmic frequency optimization was not triggered")
            self.assertFalse(mock_lin_curve.called, "Linear frequency optimization was triggered incorrectly")

            # Check results integrity
            self.assertIn('noise_rms_a_weighted', results)
            self.assertGreater(results['noise_rms_a_weighted'], 0.0)
            self.assertIn('hum_rms', results)
            self.assertIn('white_density', results)

    def test_arbitrary_frequency_fallback(self):
        """
        Verifies that arbitrary frequency spacing falls back to the safe path.
        """
        # Create an arbitrary frequency array (not linear, not log)
        # e.g. Random spacing
        freqs = np.sort(np.random.uniform(20.0, 20000.0, 1000))
        # Ensure it's not accidentally linear or log by perturbing start/end logic check
        # But random uniform sorted is usually sufficient to fail "linear" and "log" checks

        mag = np.ones_like(freqs) * 1e-6

        with patch('src.core.analysis._compute_a_weighting_sq_curve_log') as mock_log_curve, \
             patch('src.core.analysis._compute_a_weighting_sq_curve') as mock_lin_curve:

            results = AudioCalc.calculate_noise_profile(mag, freqs, self.sampling_rate)

            self.assertFalse(mock_log_curve.called, "Log optimization called incorrectly for arbitrary freqs")
            self.assertFalse(mock_lin_curve.called, "Linear optimization called incorrectly for arbitrary freqs")

            self.assertIn('noise_rms_a_weighted', results)

if __name__ == '__main__':
    unittest.main()
