
import sys
import os
import unittest
from unittest.mock import MagicMock

import numpy as np
from PyQt6.QtWidgets import QApplication

# Ensure we can import from src
sys.path.insert(0, os.getcwd())

# Mock sounddevice at top level as Spectrogram imports it
sys.modules["sounddevice"] = MagicMock()

from src.gui.widgets.spectrogram import Spectrogram, SpectrogramWidget  # noqa: E402

# Mock AudioEngine
class MockAudioEngine:
    def __init__(self):
        self.sample_rate = 44100

    def register_callback(self, callback):
        return 1

    def unregister_callback(self, id):
        pass

class TestSpectrogramOptimization(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Create QApplication
        if not QApplication.instance():
            cls.app = QApplication(sys.argv)
        else:
            cls.app = QApplication.instance()

    def setUp(self):
        self.audio_engine = MockAudioEngine()
        self.module = Spectrogram(self.audio_engine)
        self.widget = SpectrogramWidget(self.module)

        # Initialize audio buffer with some random data
        self.module.audio_buffer[:] = np.random.random(self.module.audio_buffer.shape)
        self.module.audio_buffer_pos = 0 # reset

    def test_update_spectrogram_fast_mode(self):
        self.module.sweep_speed_index = 0 # Fast
        self.module.start_analysis()

        # First update
        self.widget.update_spectrogram()

        # Check mag_buffer is created
        self.assertIsNotNone(self.module.mag_buffer)
        self.assertEqual(len(self.module.mag_buffer), self.module.fft_size // 2 + 1)

        # Check accumulator behavior for Fast mode (target_frames=1)
        self.assertIsNone(self.module.accumulator)

        # Run again
        self.widget.update_spectrogram()
        self.assertIsNone(self.module.accumulator)

    def test_update_spectrogram_medium_mode(self):
        self.module.sweep_speed_index = 1 # Medium, target=4
        self.module.start_analysis()

        # First update
        self.widget.update_spectrogram()

        # acc_count should be 1
        self.assertEqual(self.module.acc_count, 1)
        self.assertIsNotNone(self.module.accumulator)

        # Verify accumulator is a COPY
        self.assertIsNot(self.module.accumulator, self.module.mag_buffer, "Accumulator should be a copy in Medium mode")

        # Second update
        self.widget.update_spectrogram()
        self.assertEqual(self.module.acc_count, 2)

        # Third
        self.widget.update_spectrogram()
        self.assertEqual(self.module.acc_count, 3)

        # Fourth (Should trigger push and reset)
        self.widget.update_spectrogram()

        self.assertIsNone(self.module.accumulator)
        self.assertEqual(self.module.acc_count, 0)

    def test_buffer_resize(self):
        self.module.start_analysis()
        self.widget.update_spectrogram()

        old_buffer = self.module.mag_buffer
        self.assertIsNotNone(old_buffer)

        # Change FFT size
        new_size = 1024
        self.module.set_fft_size(new_size)

        # Buffer should be None after reset
        self.assertIsNone(self.module.mag_buffer)

        # Update
        self.widget.update_spectrogram()

        # New buffer created
        self.assertIsNotNone(self.module.mag_buffer)
        self.assertEqual(len(self.module.mag_buffer), new_size // 2 + 1)
        self.assertIsNot(self.module.mag_buffer, old_buffer)

if __name__ == "__main__":
    unittest.main()
