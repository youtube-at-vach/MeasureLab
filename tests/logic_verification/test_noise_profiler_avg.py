import os
import sys
import unittest
from unittest.mock import MagicMock

import numpy as np

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from src.gui.widgets.noise_profiler import NoiseProfiler


class MockEngine:
    def __init__(self):
        self.sample_rate = 48000
        self.calibration = MagicMock()
        self.calibration.get_input_offset_db.return_value = 0.0

    def register_callback(self, cb):
        return 1

    def unregister_callback(self, id):
        pass

class TestNoiseProfilerAverage(unittest.TestCase):
    def setUp(self):
        self.engine = MockEngine()
        self.profiler = NoiseProfiler(self.engine)
        # Manually set attributes that will be added
        self.profiler.average_mode = True
        self.profiler.target_averages = 10
        self.profiler.current_avg_count = 0
        self.profiler.accumulated_magnitude = None
        self.profiler._avg_magnitude = None
        self.profiler.buffer_size = 1024
        self.profiler.input_data = np.zeros((1024, 2))

    def test_averaging_logic(self):
        # Simulate 3 updates

        # Test Data
        mag1 = np.ones(513) * 1.0
        mag2 = np.ones(513) * 2.0
        mag3 = np.ones(513) * 3.0

        # Step 1
        self.profiler.update_average(mag1)
        self.assertEqual(self.profiler.current_avg_count, 1)
        np.testing.assert_array_almost_equal(self.profiler._avg_magnitude, mag1)

        # Step 2
        self.profiler.update_average(mag2)
        self.assertEqual(self.profiler.current_avg_count, 2)
        # Avg of 1 and 2 is 1.5
        np.testing.assert_array_almost_equal(self.profiler._avg_magnitude, np.ones(513) * 1.5)

        # Step 3
        self.profiler.update_average(mag3)
        self.assertEqual(self.profiler.current_avg_count, 3)
        # Avg of 1, 2, 3 is 2.0
        np.testing.assert_array_almost_equal(self.profiler._avg_magnitude, np.ones(513) * 2.0)

if __name__ == '__main__':
    unittest.main()
