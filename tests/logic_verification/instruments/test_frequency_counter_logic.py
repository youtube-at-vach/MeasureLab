import unittest
from unittest.mock import MagicMock
import numpy as np
import sys
import os
from collections import deque

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../")))

from src.gui.widgets.frequency_counter import FrequencyCounter


class TestFrequencyCounterLogic(unittest.TestCase):
    def setUp(self):
        self.mock_audio_engine = MagicMock()
        self.mock_audio_engine.sample_rate = 48000
        self.counter = FrequencyCounter(self.mock_audio_engine)
        self.counter.is_running = True  # Simulate running

    def test_process_silence(self):
        # Create silence buffer
        self.counter.input_buffer = np.zeros(self.counter.buffer_size)

        # Process
        freq = self.counter.process()

        # Should return None because of gate
        self.assertIsNone(freq)
        self.assertLess(self.counter.current_amp_db, self.counter.gate_threshold_db)

    def test_process_sine_wave(self):
        # Create sine wave 1kHz
        sr = 48000
        t = np.arange(self.counter.buffer_size) / sr
        target_freq = 1000.0
        signal = 0.5 * np.sin(2 * np.pi * target_freq * t)  # -6dBFS

        self.counter.input_buffer = signal

        # Process
        freq = self.counter.process()

        # Should detect frequency
        self.assertIsNotNone(freq)
        self.assertAlmostEqual(freq, target_freq, delta=1.0)  # Allow small error
        self.assertGreater(self.counter.current_amp_db, self.counter.gate_threshold_db)

    def test_buffer_management(self):
        # Test that buffer rolls correctly (mocking the callback logic partially)
        # Manually manipulating buffer to simulate callback effect

        # Fill with 1s
        self.counter.input_buffer = np.ones(self.counter.buffer_size)

        # New data (0s)
        new_data = np.zeros(100)

        # Roll logic from callback
        self.counter.input_buffer = np.roll(self.counter.input_buffer, -len(new_data))
        self.counter.input_buffer[-len(new_data) :] = new_data

        # Check end is 0
        self.assertTrue(np.all(self.counter.input_buffer[-100:] == 0))
        # Check start is 1
        self.assertTrue(np.all(self.counter.input_buffer[:-100] == 1))


class TestFrequencyCounterWarmup(unittest.TestCase):
    def setUp(self):
        self.mock_audio_engine = MagicMock()
        self.mock_audio_engine.sample_rate = 48000

    def test_warmup_samples_are_not_added_to_history(self):
        counter = FrequencyCounter(self.mock_audio_engine)
        counter.warmup_discard_points = 2
        counter._warmup_remaining = 2

        # First two valid readings should be discarded from history
        recorded = counter.record_frequency_measurement(1000.0, now_t=100.0)
        self.assertFalse(recorded)
        self.assertEqual(len(counter.freq_history), 0)

        recorded = counter.record_frequency_measurement(1000.0, now_t=100.1)
        self.assertFalse(recorded)
        self.assertEqual(len(counter.freq_history), 0)

        # Third one should be accepted
        recorded = counter.record_frequency_measurement(1000.0, now_t=100.2)
        self.assertTrue(recorded)
        self.assertEqual(len(counter.freq_history), 1)
        self.assertAlmostEqual(counter.freq_history[-1], 1000.0, places=6)


class TestFrequencyCounterStats(unittest.TestCase):
    def setUp(self):
        self.mock_audio_engine = MagicMock()
        self.counter = FrequencyCounter(self.mock_audio_engine)
        self.counter.freq_history = deque(maxlen=100)

    def test_stats_constant(self):
        # Constant frequency
        self.counter.freq_history.extend([1000.0] * 10)
        self.counter.calculate_stats()

        self.assertEqual(self.counter.std_dev, 0.0)
        self.assertEqual(self.counter.allan_deviation, 0.0)

    def test_stats_linear_drift(self):
        # Linear drift: 0, 1, 2, 3, 4
        data = [0.0, 1.0, 2.0, 3.0, 4.0]
        self.counter.freq_history.extend(data)
        self.counter.calculate_stats()

        # Std Dev
        # Mean = 2.0
        # Variance (ddof=1) = ((4+1+0+1+4) / 4) = 2.5
        expected_std = np.sqrt(2.5)
        self.assertAlmostEqual(self.counter.std_dev, expected_std, places=5)

        # Allan Dev
        # Diffs = [1, 1, 1, 1]
        # Mean(Diffs^2) = 1
        # Sigma = sqrt(0.5 * 1) = 0.70710678
        expected_allan = np.sqrt(0.5)
        self.assertAlmostEqual(self.counter.allan_deviation, expected_allan, places=5)

    def test_stats_alternating(self):
        # Alternating: 1000, 1002, 1000, 1002
        data = [1000.0, 1002.0, 1000.0, 1002.0]
        self.counter.freq_history.extend(data)
        self.counter.calculate_stats()

        # Std Dev
        # Mean = 1001
        # Variance = ((1+1+1+1)/3) = 4/3 = 1.333...
        expected_std = np.sqrt(4 / 3)
        self.assertAlmostEqual(self.counter.std_dev, expected_std, places=5)

        # Allan Dev
        # Diffs = [2, -2, 2]
        # Diffs^2 = [4, 4, 4]
        # Mean(Diffs^2) = 4
        # Sigma = sqrt(0.5 * 4) = sqrt(2) = 1.4142...
        expected_allan = np.sqrt(2)
        self.assertAlmostEqual(self.counter.allan_deviation, expected_allan, places=5)


class TestFrequencyCounterCallback(unittest.TestCase):
    def setUp(self):
        self.mock_audio_engine = MagicMock()
        self.mock_audio_engine.sample_rate = 48000
        # Mock register_callback to capture the callback function
        self.callback_func = None

        def side_effect(func):
            self.callback_func = func
            return 123  # callback_id

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


if __name__ == "__main__":
    unittest.main()
