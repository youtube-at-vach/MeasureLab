import unittest
import numpy as np
from src.core.analysis import AudioCalc

class TestFreqAxisAnalysis(unittest.TestCase):
    def test_linear_freqs(self):
        # Linear frequency array: 0, 10, 20, ..., 100
        freqs = np.linspace(0, 100, 11)

        is_linear, is_log, step, start, stop, width = AudioCalc._analyze_frequency_axis(freqs)

        self.assertTrue(is_linear)
        self.assertFalse(is_log)
        self.assertAlmostEqual(step, 10.0)
        self.assertAlmostEqual(start, 0.0)
        self.assertAlmostEqual(width, 10.0)
        # stop is only set for log freqs in the original logic? No, let's check.
        # Original logic: stop_freq initialized to 0.0. Only updated if is_log_freqs is True.
        self.assertEqual(stop, 0.0)

    def test_log_freqs(self):
        # Logarithmic frequency array: 10, 100, 1000
        freqs = np.geomspace(10, 1000, 3)
        # 10, 100, 1000. ratio=10.

        is_linear, is_log, step, start, stop, width = AudioCalc._analyze_frequency_axis(freqs)

        self.assertFalse(is_linear)
        self.assertTrue(is_log)
        # step is freqs[1] - freqs[0] = 90.0
        self.assertAlmostEqual(step, 90.0)
        self.assertAlmostEqual(start, 10.0)
        self.assertAlmostEqual(stop, 1000.0)
        self.assertAlmostEqual(width, 90.0)

    def test_irregular_freqs(self):
        # Neither linear nor log
        freqs = np.array([0.0, 10.0, 30.0, 40.0])

        is_linear, is_log, step, start, stop, width = AudioCalc._analyze_frequency_axis(freqs)

        self.assertFalse(is_linear)
        self.assertFalse(is_log)
        self.assertAlmostEqual(step, 10.0) # freqs[1] - freqs[0]
        self.assertAlmostEqual(start, 0.0)
        self.assertEqual(stop, 0.0)
        self.assertAlmostEqual(width, 10.0)

    def test_single_element(self):
        freqs = np.array([100.0])

        is_linear, is_log, step, start, stop, width = AudioCalc._analyze_frequency_axis(freqs)

        self.assertFalse(is_linear)
        self.assertFalse(is_log)
        self.assertAlmostEqual(step, 1.0) # Default
        self.assertAlmostEqual(start, 0.0) # Default start_freq is 0.0 in original logic if len <= 1?
        # Original logic:
        # start_freq = 0.0
        # if len(freqs) > 1: start_freq = freqs[0]
        # So if len=1, start_freq remains 0.0?
        # Let's check original code:
        # start_freq = 0.0
        # if len(freqs) > 1: start_freq = freqs[0]
        # So yes, for len=1, start_freq is 0.0.
        self.assertEqual(start, 0.0)
        self.assertEqual(stop, 0.0)
        self.assertEqual(width, 1.0) # Default

    def test_empty_array(self):
        freqs = np.array([])

        is_linear, is_log, step, start, stop, width = AudioCalc._analyze_frequency_axis(freqs)

        self.assertFalse(is_linear)
        self.assertFalse(is_log)
        self.assertEqual(step, 1.0)
        self.assertEqual(start, 0.0)
        self.assertEqual(stop, 0.0)
        self.assertEqual(width, 1.0)

if __name__ == '__main__':
    unittest.main()
