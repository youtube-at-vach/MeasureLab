import unittest
from unittest.mock import patch
import numpy as np
from src.core.analysis import AudioCalc


class TestOptimizeFrequencyVectorized(unittest.TestCase):
    def setUp(self):
        self.sr = 48000
        self.duration = 1.0
        self.N = int(self.sr * self.duration)
        self.t = np.arange(self.N) / self.sr
        self.freq = 1000.0
        self.signal = np.sin(2 * np.pi * self.freq * self.t) + 0.1 * np.random.randn(self.N)

    def test_basic_optimization(self):
        # Initial guess slightly off
        guess = 1005.0
        best_freq = AudioCalc.optimize_frequency(self.signal, self.sr, guess)
        self.assertAlmostEqual(best_freq, self.freq, places=2)

    def test_large_signal_chunking(self):
        # Create a signal larger than chunk size (16384)
        N_large = 20000
        t = np.arange(N_large) / self.sr
        freq = 500.0
        signal = np.sin(2 * np.pi * freq * t)

        guess = 502.0
        best_freq = AudioCalc.optimize_frequency(signal, self.sr, guess)
        self.assertAlmostEqual(best_freq, freq, places=2)

    def test_dc_component(self):
        # Signal with DC
        signal_dc = self.signal + 2.0
        guess = 1005.0
        best_freq = AudioCalc.optimize_frequency(signal_dc, self.sr, guess)
        self.assertAlmostEqual(best_freq, self.freq, places=2)

    def test_negative_frequencies_ignored(self):
        # Start from a low frequency where grid might include negative values
        freq = 10.0
        signal = np.sin(2 * np.pi * freq * self.t)
        guess = 2.0  # search width is 5Hz -> -3 to 7.
        # But wait, search width is max(5 * bin_width, 5.0).
        # bin_width = 1.0. search_width = 5.0.
        # Grid: 2.0 +/- 5.0 -> -3.0 to 7.0.
        # Should filter negative.

        # However, the true freq is 10.0, so starting at 2.0 with search width 5.0 (range -3 to 7)
        # will not find 10.0. The best it can find is 7.0 (boundary).
        # This test ensures it doesn't crash on negative freqs.

        best_freq = AudioCalc.optimize_frequency(signal, self.sr, guess)
        self.assertTrue(best_freq > 0)

    def test_exact_match_with_pure_sine(self):
        # For a pure sine, the residual should be near zero.
        signal = np.sin(2 * np.pi * self.freq * self.t)
        guess = self.freq  # Exact guess

        best_freq = AudioCalc.optimize_frequency(signal, self.sr, guess)
        self.assertAlmostEqual(best_freq, self.freq, places=4)

    def test_return_full(self):
        guess = 1005.0
        best_freq, coeffs, M = AudioCalc.optimize_frequency(self.signal, self.sr, guess, return_full=True)
        self.assertAlmostEqual(best_freq, self.freq, places=2)
        self.assertIsNotNone(coeffs)
        self.assertIsNotNone(M)
        self.assertEqual(M.shape, (self.N, 3))
        self.assertEqual(len(coeffs), 3)

    def test_empty_signal(self):
        signal = np.array([])
        freq = AudioCalc.optimize_frequency(signal, self.sr, 1000.0)
        self.assertEqual(freq, 1000.0)

    def test_invalid_sr(self):
        freq = AudioCalc.optimize_frequency(self.signal, 0, 1000.0)
        self.assertEqual(freq, 1000.0)

    def test_optimize_frequency_return_full_empty(self):
        """Test optimize_frequency with return_full=True and empty signal."""
        signal = np.array([])
        sr = 48000
        ret = AudioCalc.optimize_frequency(signal, sr, 1000, return_full=True)
        # Should return a tuple of 3
        self.assertEqual(len(ret), 3)
        best_freq, coeffs, M = ret
        # best_freq should be guess or NaN
        self.assertTrue(best_freq == 1000 or np.isnan(best_freq))
        # coeffs and M might be None or empty
        if M is not None:
            self.assertEqual(len(M), 0)

    def test_perform_coarse_search_linalg_error_batch_only(self):
        """Test _perform_coarse_search when np.linalg.solve raises LinAlgError only on the batch."""
        signal = np.sin(2 * np.pi * self.freq * self.t)
        grid = np.array([990.0, 1000.0, 1010.0])

        real_solve = np.linalg.solve

        def side_effect_func(a, b, *args, **kwargs):
            if len(a.shape) == 3:
                raise np.linalg.LinAlgError("Batch solve failed")
            return real_solve(a, b, *args, **kwargs)

        with patch("numpy.linalg.solve", side_effect=side_effect_func) as mock_solve:
            # Call the method which should catch the error and fallback to loop, then succeed
            best_coarse = AudioCalc._perform_coarse_search(signal, self.t, grid)

            self.assertIn(best_coarse, grid)
            self.assertAlmostEqual(best_coarse, self.freq, places=2)
            self.assertGreater(mock_solve.call_count, 1)

    @patch("numpy.linalg.solve", side_effect=np.linalg.LinAlgError)
    def test_sine_fit_residual_linalg_error(self, mock_solve):
        """Test _sine_fit_residual when np.linalg.solve raises LinAlgError."""
        signal = np.sin(2 * np.pi * self.freq * self.t)
        M = np.empty((self.N, 3), dtype=np.float64)
        fitted_buffer = np.empty(self.N, dtype=np.float64)
        residual_buffer = np.empty(self.N, dtype=np.float64)

        # Call the method which should catch the error and fallback to lstsq
        mse = AudioCalc._sine_fit_residual(self.freq, signal, self.t, M, fitted_buffer, residual_buffer)

        # Verify that solve was actually called and mocked
        self.assertTrue(mock_solve.called)
        # Ensure it didn't crash and returned a valid MSE (should be near 0 for exact match)
        self.assertTrue(mse >= 0.0)
        self.assertAlmostEqual(mse, 0.0, places=4)

    @patch("numpy.linalg.solve", side_effect=np.linalg.LinAlgError)
    def test_perform_coarse_search_linalg_error(self, mock_solve):
        """Test _perform_coarse_search when np.linalg.solve always raises LinAlgError."""
        signal = np.sin(2 * np.pi * self.freq * self.t)
        grid = np.array([990.0, 1000.0, 1010.0])

        # Call the method which should catch the error and fallback to lstsq
        best_coarse = AudioCalc._perform_coarse_search(signal, self.t, grid)

        # Ensure it didn't crash and returned a valid grid frequency
        self.assertIn(best_coarse, grid)
        self.assertAlmostEqual(best_coarse, self.freq, places=2)
        # Verify that solve was actually called and mocked
        self.assertTrue(mock_solve.called)

    @patch("numpy.linalg.solve", side_effect=np.linalg.LinAlgError)
    def test_calculate_residual_linalg_error(self, mock_solve):
        """Test _calculate_residual when np.linalg.solve raises LinAlgError."""
        # _calculate_residual is called internally during fine optimization
        signal = np.sin(2 * np.pi * self.freq * self.t)

        # We start with a good guess so fine optimization will run
        best_freq = AudioCalc.optimize_frequency(signal, self.sr, self.freq)
        self.assertAlmostEqual(best_freq, self.freq, places=2)
        self.assertTrue(mock_solve.called)

    @patch("numpy.linalg.lstsq", side_effect=np.linalg.LinAlgError)
    def test_optimize_frequency_return_full_linalg_error(self, mock_lstsq):
        """Test optimize_frequency final lstsq raising LinAlgError with return_full=True."""
        signal = np.sin(2 * np.pi * self.freq * self.t)

        # When return_full=True, it computes lstsq at the end
        best_freq, coeffs, M = AudioCalc.optimize_frequency(signal, self.sr, self.freq, return_full=True)

        self.assertAlmostEqual(best_freq, self.freq, places=2)
        self.assertIsNotNone(coeffs)
        self.assertIsNotNone(M)
        self.assertTrue(mock_lstsq.called)


if __name__ == "__main__":
    unittest.main()
