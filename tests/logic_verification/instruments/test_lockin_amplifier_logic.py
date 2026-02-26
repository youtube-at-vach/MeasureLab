import unittest
import sys
from unittest.mock import MagicMock

# Mock sounddevice before importing anything that uses it
sys.modules['sounddevice'] = MagicMock()

import numpy as np  # noqa: E402
from src.gui.widgets.lock_in_amplifier import LockInAmplifier  # noqa: E402

class MockCalibration:
    def __init__(self):
        self.lockin_gain_offset = 0.0
        self.output_gain = 1.0
        self.input_sensitivity = 1.0

    def get_frequency_correction(self, freq):
        return 0.0, 0.0

class MockAudioEngine:
    def __init__(self):
        self.sample_rate = 48000
        self.calibration = MockCalibration()
        self.callbacks = {}
        self.next_id = 0

    def register_callback(self, callback):
        cid = self.next_id
        self.next_id += 1
        self.callbacks[cid] = callback
        return cid

    def unregister_callback(self, cid):
        if cid in self.callbacks:
            del self.callbacks[cid]

class TestLockInBuffer(unittest.TestCase):
    def setUp(self):
        self.audio_engine = MockAudioEngine()
        self.lockin = LockInAmplifier(self.audio_engine)
        self.lockin.set_buffer_size(100) # Small buffer for easier testing
        self.lockin.start_analysis()
        self.callback = self.audio_engine.callbacks[self.lockin.callback_id]

    def test_ring_buffer_write_no_wrap(self):
        # Initial state: buffer should be all zeros
        np.testing.assert_array_equal(self.lockin.input_data, np.zeros((100, 2)))

        # New data: 10 samples (1..10)
        new_data = np.arange(1, 11).reshape(10, 1)
        new_data = np.hstack((new_data, new_data))

        # Call callback
        outdata = np.zeros((10, 2))
        self.callback(new_data, outdata, 10, None, None)

        # Verify internal state (implementation detail check)
        self.assertEqual(self.lockin.input_buffer_pos, 10)
        np.testing.assert_array_equal(self.lockin.input_data[0:10], new_data)

        # Verify reconstructed data
        ordered, s_idx = self.lockin.get_ordered_input_data()
        expected = np.zeros((100, 2))
        expected[-10:] = new_data

        np.testing.assert_array_equal(ordered, expected)

    def test_ring_buffer_wrap_around(self):
        # Fill buffer almost full: 90 samples
        data_1 = np.ones((90, 2)) * 1
        outdata = np.zeros((90, 2))
        self.callback(data_1, outdata, 90, None, None)

        self.assertEqual(self.lockin.input_buffer_pos, 90)

        # Add 20 samples -> Wrap around
        data_2 = np.ones((20, 2)) * 2
        self.callback(data_2, outdata[:20], 20, None, None)

        # Pos should be 10
        self.assertEqual(self.lockin.input_buffer_pos, 10)

        # Check internal buffer
        # [0..10]: 2s
        # [10..90]: 1s
        # [90..100]: 2s (from data_2)

        np.testing.assert_array_equal(self.lockin.input_data[0:10], data_2[10:])
        np.testing.assert_array_equal(self.lockin.input_data[10:90], data_1[10:])
        np.testing.assert_array_equal(self.lockin.input_data[90:100], data_2[:10])

        # Check reconstruction
        ordered, s_idx = self.lockin.get_ordered_input_data()

        expected = np.concatenate((
            np.ones((80, 2)) * 1, # 80 samples of 1s
            np.ones((20, 2)) * 2  # 20 samples of 2s
        ))

        np.testing.assert_array_equal(ordered, expected)

    def test_large_write_overwrite(self):
        # Write more than buffer size
        # 150 samples
        data = np.arange(150).reshape(150, 1)
        data = np.hstack((data, data))

        outdata = np.zeros((150, 2))
        self.callback(data, outdata, 150, None, None)

        # Should keep last 100
        expected_internal = data[-100:]

        # Implementation: if n > size, write last size samples to 0..size, set pos=0
        self.assertEqual(self.lockin.input_buffer_pos, 0)
        np.testing.assert_array_equal(self.lockin.input_data, expected_internal)

        ordered, s_idx = self.lockin.get_ordered_input_data()
        np.testing.assert_array_equal(ordered, expected_internal)

if __name__ == "__main__":
    unittest.main()
