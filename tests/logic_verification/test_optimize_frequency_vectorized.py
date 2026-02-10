import unittest
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
        guess = 2.0 # search width is 5Hz -> -3 to 7.
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
        guess = self.freq # Exact guess

        best_freq = AudioCalc.optimize_frequency(signal, self.sr, guess)
        self.assertAlmostEqual(best_freq, self.freq, places=4)

if __name__ == '__main__':
    unittest.main()
