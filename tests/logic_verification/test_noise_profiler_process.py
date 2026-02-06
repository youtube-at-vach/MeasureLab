import unittest
from unittest.mock import MagicMock
import numpy as np
import sys
import os

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from src.gui.widgets.noise_profiler import NoiseProfiler

class TestNoiseProfilerProcess(unittest.TestCase):
    def setUp(self):
        self.engine = MagicMock()
        self.engine.sample_rate = 48000
        self.engine.calibration.get_input_offset_db.return_value = 0.0

        self.profiler = NoiseProfiler(self.engine)
        self.profiler.buffer_size = 1024
        # Fill input data
        self.profiler.input_data = np.random.rand(1024, 2)

    def test_process_data_smoke(self):
        # Basic smoke test
        output = self.profiler.process_data(channel_idx=0, unit_mode="dBV", apply_gain_correction=False)

        self.assertIsNotNone(output)
        freqs, mag, results, raw_avg = output

        self.assertIsNotNone(freqs)
        self.assertIsNotNone(mag)
        self.assertIsNotNone(results)
        self.assertEqual(len(freqs), 513) # 1024/2 + 1
        self.assertEqual(len(mag), 513)
        self.assertIn("white_density", results)

    def test_process_data_insufficient_data(self):
        self.profiler.input_data = np.zeros((100, 2)) # Less than buffer_size
        output = self.profiler.process_data(0, "dBV", False)
        self.assertIsNone(output)

if __name__ == '__main__':
    unittest.main()
