import unittest
from unittest.mock import MagicMock
import numpy as np
import sys
import os

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from src.gui.widgets.frequency_counter import FrequencyCounter

class TestFrequencyCounterCallback(unittest.TestCase):
    def setUp(self):
        self.mock_audio_engine = MagicMock()
        self.mock_audio_engine.sample_rate = 48000
        # Mock register_callback to capture the callback function
        self.callback_func = None
        def side_effect(func):
            self.callback_func = func
            return 123 # callback_id
        self.mock_audio_engine.register_callback.side_effect = side_effect

        self.counter = FrequencyCounter(self.mock_audio_engine)

    def test_callback_ignores_status(self):
        # Start analysis to register the callback
        self.counter.start_analysis()

        self.assertIsNotNone(self.callback_func, "Callback should be registered")

        # Prepare dummy data for callback
        frames = 1024
        indata = np.zeros((frames, 2), dtype=np.float32)
        outdata = np.zeros((frames, 2), dtype=np.float32)
        time_info = MagicMock()

        # Call with status=None
        try:
            self.callback_func(indata, outdata, frames, time_info, None)
        except Exception as e:
            self.fail(f"Callback failed with status=None: {e}")

        # Call with status object (simulating a CFFI object or similar that might be printable)
        status_obj = MagicMock()
        status_obj.__str__.return_value = "Input overflow"

        try:
            self.callback_func(indata, outdata, frames, time_info, status_obj)
        except Exception as e:
            self.fail(f"Callback failed with status object: {e}")

    def test_callback_buffer_logic(self):
        # Verify that data is actually processed
        self.counter.start_analysis()

        frames = 1024
        # Create a distinctive signal
        indata = np.ones((frames, 2), dtype=np.float32) * 0.5
        outdata = np.zeros((frames, 2), dtype=np.float32)
        time_info = MagicMock()

        self.callback_func(indata, outdata, frames, time_info, None)

        # Check if input_buffer was updated (last 1024 samples should be 0.5)
        # buffer_size is 8192 by default
        self.assertTrue(np.allclose(self.counter.input_buffer[-frames:], 0.5))

if __name__ == '__main__':
    unittest.main()
