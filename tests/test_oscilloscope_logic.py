import unittest
import numpy as np
import sys
import os
from unittest.mock import MagicMock

# Ensure src is in path
sys.path.insert(0, os.getcwd())

# Mock sounddevice BEFORE importing any module that uses it
mock_sd = MagicMock()
sys.modules['sounddevice'] = mock_sd

from src.gui.widgets.oscilloscope import Oscilloscope

class TestOscilloscopeLogic(unittest.TestCase):
    def setUp(self):
        self.mock_engine = MagicMock()
        self.mock_engine.sample_rate = 48000
        # Mock register_callback to return a dummy ID
        self.mock_engine.register_callback.return_value = 123

        self.osc = Oscilloscope(self.mock_engine)
        # Use small buffer size for easy testing
        self.osc.buffer_size = 10
        self.osc.start_analysis()

        # Capture the callback
        # register_callback is called in start_analysis
        args = self.mock_engine.register_callback.call_args
        if args:
            self.callback = args[0][0]
        else:
            self.fail("register_callback not called")

    def test_simple_fill(self):
        # Buffer size 10. Feed 5 samples.
        indata = np.arange(5).reshape(5, 1).astype(float)
        # Expand to stereo
        indata_stereo = np.column_stack((indata, indata))

        outdata = np.zeros_like(indata_stereo)

        # Call callback
        self.callback(indata_stereo, outdata, 5, None, None)

        # Check buffer state
        self.assertEqual(self.osc.write_index, 5)

        # get_display_data should return unrolled data.
        # Originally zeros. So first 5 should be 0 (old), last 5 should be 0..4 (new)

        data = self.osc.get_display_data(10.0) # Request large window to get all buffer

        expected = np.zeros((10, 2))
        expected[5:, 0] = np.arange(5)
        expected[5:, 1] = np.arange(5)

        np.testing.assert_array_equal(data, expected)

    def test_wrap_around(self):
        # Feed 8 samples of 1s
        indata1 = np.ones((8, 2))
        outdata1 = np.zeros_like(indata1)
        self.callback(indata1, outdata1, 8, None, None)

        self.assertEqual(self.osc.write_index, 8)

        # Feed 4 samples of 2s
        indata2 = np.ones((4, 2)) * 2
        outdata2 = np.zeros_like(indata2)
        self.callback(indata2, outdata2, 4, None, None)

        # write_index should be (8+4)%10 = 2.
        self.assertEqual(self.osc.write_index, 2)

        # Result should be: 6 ones (oldest), then 4 twos (newest)
        data = self.osc.get_display_data(10.0)

        expected = np.ones((10, 2))
        expected[:6] = 1
        expected[6:] = 2

        np.testing.assert_array_equal(data, expected)

    def test_larger_than_buffer(self):
        # Feed 15 samples.
        indata = np.ones((15, 2)) * 3
        indata[:5] = 4 # First 5 are 4s
        indata[5:] = 3 # Last 10 are 3s

        outdata = np.zeros_like(indata)
        self.callback(indata, outdata, 15, None, None)

        # write_index should be 0
        self.assertEqual(self.osc.write_index, 0)

        # Buffer should be all 3s
        data = self.osc.get_display_data(10.0)
        expected = np.ones((10, 2)) * 3

        np.testing.assert_array_equal(data, expected)

    def test_mono_input(self):
        # Feed mono input
        indata = np.ones((5, 1)) * 5
        # Pass shape (5, 1)

        outdata = np.zeros((5, 2)) # outdata shape doesn't matter much for logic but strict typing might

        self.callback(indata, outdata, 5, None, None)

        self.assertEqual(self.osc.write_index, 5)

        data = self.osc.get_display_data(10.0)

        expected = np.zeros((10, 2))
        expected[5:, 0] = 5
        expected[5:, 1] = 5

        np.testing.assert_array_equal(data, expected)

if __name__ == '__main__':
    unittest.main()
