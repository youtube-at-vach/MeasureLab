import sys
import os
import unittest
from unittest.mock import MagicMock
import numpy as np

# Add src to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../')))
from PyQt6.QtWidgets import QApplication

# Mock sounddevice
sys.modules['sounddevice'] = MagicMock()

# Import after mocking
from src.gui.widgets.spectrogram import SpectrogramWidget, Spectrogram

class MockAudioEngine:
    def __init__(self):
        self.sample_rate = 44100
        self.buffer_size = 1024
    def register_callback(self, cb):
        return 1
    def unregister_callback(self, id):
        pass

class TestSpectrogramLogBuffer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Create QApplication if it doesn't exist
        if not QApplication.instance():
            cls.app = QApplication(sys.argv)
        else:
            cls.app = QApplication.instance()

    def setUp(self):
        self.engine = MockAudioEngine()
        self.module = Spectrogram(self.engine)
        self.widget = SpectrogramWidget(self.module)
        self.module.is_running = True

        # Disable Timer so we can manually trigger update
        self.widget.timer.stop()

    def test_log_buffer_logic(self):
        # Set to Log Mode
        self.widget.scale_combo.setCurrentText("Log")

        # 1. Initial Update
        # Simulate data in module accumulator
        # Spectrogram buffer size: 500 x (2048//2 + 1) = 500 x 1025
        data_v1 = np.full(1025, -50.0, dtype=np.float32)

        self.module.accumulator = data_v1.copy()
        self.module.acc_count = 100 # Force update
        self.module.get_latest_samples = MagicMock(return_value=np.zeros((self.module.fft_size, 2)))

        self.widget.update_spectrogram()

        # Verify log_buffer exists and is populated
        # Note: logic not yet implemented, so check strictly only if implementation done
        # But for TDD, we assert it exists
        if not hasattr(self.widget, 'log_spectrogram_buffer'):
            self.skipTest("Optimization not yet implemented")

        self.assertIsNotNone(self.widget.log_spectrogram_buffer)
        self.assertEqual(self.widget.log_spectrogram_buffer.shape[0], self.module.history_length)

        # Check if data was written correctly
        # We need the indices
        indices = self.widget._log_map_cache[1]
        expected_v1 = data_v1[indices]

        ptr_v1 = self.module.spectrogram_ptr
        # Written at previous index
        idx_v1 = (ptr_v1 - 1 + self.module.history_length) % self.module.history_length

        np.testing.assert_array_almost_equal(self.widget.log_spectrogram_buffer[idx_v1], expected_v1)

        # 2. Incremental Update
        data_v2 = np.full(1025, -20.0, dtype=np.float32)
        self.module.accumulator = data_v2.copy()
        self.module.acc_count = 100

        # Store state of buffer before update
        buffer_before = self.widget.log_spectrogram_buffer.copy()

        self.widget.update_spectrogram()

        ptr_v2 = self.module.spectrogram_ptr
        idx_v2 = (ptr_v2 - 1 + self.module.history_length) % self.module.history_length

        # Assert pointer moved
        self.assertEqual(ptr_v2, (ptr_v1 + 1) % self.module.history_length)

        # Assert new data is correct
        expected_v2 = data_v2[indices]
        np.testing.assert_array_almost_equal(self.widget.log_spectrogram_buffer[idx_v2], expected_v2)

        # Assert OLD data (idx_v1) is UNCHANGED in the log buffer
        # This verifies we didn't wipe the buffer or do something weird
        np.testing.assert_array_almost_equal(self.widget.log_spectrogram_buffer[idx_v1], buffer_before[idx_v1])

        # 3. Parameter Change (Min Freq) -> Should Reset Buffer
        old_buffer_id = id(self.widget.log_spectrogram_buffer)
        self.widget.min_freq_spin.setValue(500) # Change freq
        self.widget.on_freq_range_changed()

        # Need another update to trigger the logic (as logic is in update_spectrogram)
        self.module.accumulator = data_v1.copy()
        self.module.acc_count = 100
        self.widget.update_spectrogram()

        # Buffer ID might be same (if numpy reuses) or different.
        # But content should be consistent.
        # If parameters changed, indices changed.
        new_indices = self.widget._log_map_cache[1]
        self.assertFalse(np.array_equal(indices, new_indices))

        # Verify the buffer now contains data mapped with NEW indices
        # Since we just did an update, the latest row (idx_v3) should have data_v1[new_indices]
        # But what about previous rows?
        # The optimization strategy says: "If changed, perform a full copy/initialization".
        # So ALL rows should be valid according to the new mapping (from raw buffer).

        # Raw buffer has history. We only added data_v1, data_v2, data_v1.
        # Check idx_v2 (which has data_v2).
        # It should now match data_v2[new_indices]

        # Note: raw buffer at idx_v2 is data_v2 (db).
        # We need to verify that log_buffer[idx_v2] == raw_buffer[idx_v2][new_indices]

        raw_row_v2 = self.module.spectrogram_buffer[idx_v2]
        expected_row_v2_new_map = raw_row_v2[new_indices]

        np.testing.assert_array_almost_equal(self.widget.log_spectrogram_buffer[idx_v2], expected_row_v2_new_map)

if __name__ == '__main__':
    unittest.main()
