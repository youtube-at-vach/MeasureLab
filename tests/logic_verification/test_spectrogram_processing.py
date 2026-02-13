import unittest
from unittest.mock import MagicMock
import numpy as np

# Use real PyQt6 (with offscreen platform)
from PyQt6.QtWidgets import QApplication

# Use real dependencies for logic verification where possible
# But mock sounddevice and soundfile to avoid hardware dependency
from unittest.mock import patch
import sys

# We patch sys.modules inside setUpContext? No, we can patch just for imports if needed.
# But Spectrogram imports at module level.
# Since we installed soundfile, we can use it (mocked if needed for writing).
# Spectrogram doesn't use soundfile directly, only sounddevice.
# We should mock sounddevice if not already mocked by conftest.

from src.gui.widgets.spectrogram import Spectrogram, SpectrogramWorker

class TestSpectrogramProcessing(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Ensure QApplication exists
        if not QApplication.instance():
            cls.app = QApplication([])
        else:
            cls.app = QApplication.instance()

    def setUp(self):
        self.mock_engine = MagicMock()
        self.mock_engine.sample_rate = 48000

        self.spec = Spectrogram(self.mock_engine)
        self.spec.set_fft_size(1024)

    def test_spectrogram_worker_logic(self):
        """
        Verify that SpectrogramWorker correctly computes FFT and dB magnitude.
        """
        # Generate a sine wave
        # 1000 Hz at 48kHz
        t = np.linspace(0, 1024/48000, 1024, endpoint=False)
        freq = 1000
        sine = 0.5 * np.sin(2 * np.pi * freq * t)

        # Create input buffer (stereo)
        raw_data = np.column_stack((sine, sine))

        # Create Worker
        worker = SpectrogramWorker(raw_data, "hann", "Left")

        # Capture result
        result_container = []
        def capture_result(res):
            result_container.append(res)

        worker.signals.result.connect(capture_result)

        # Run worker (synchronously in this thread)
        worker.run()

        # With real signals, direct connection (default for same thread) works immediately.
        self.assertEqual(len(result_container), 1)
        mag_db = result_container[0]

        # Check output shape
        # rfft of 1024 -> 513 bins
        self.assertEqual(len(mag_db), 513)

        # Check peak frequency
        peak_bin = np.argmax(mag_db)
        peak_freq = peak_bin * (48000 / 1024)

        self.assertTrue(abs(peak_freq - 1000) < 50, f"Expected ~1000Hz, got {peak_freq}Hz")

        # Check amplitude
        peak_amp = mag_db[peak_bin]
        self.assertTrue(peak_amp > -10, f"Expected > -10dB, got {peak_amp}dB")

    def test_buffer_update(self):
        """
        Verify that add_spectrum updates the ring buffer correctly.
        """
        self.spec.history_length = 5
        self.spec.reset_buffers()

        # Dummy spectrum
        frame = np.zeros(self.spec.fft_size // 2 + 1)
        frame[0] = 10.0 # DC offset

        self.spec.add_spectrum(frame)

        # Check buffer content
        # ptr should be 1
        self.assertEqual(self.spec.spectrogram_ptr, 1)
        self.assertTrue(np.array_equal(self.spec.spectrogram_buffer[0], frame))

        # Add more to wrap around
        for i in range(5):
            frame[0] = i
            self.spec.add_spectrum(frame.copy())

        # Total writes: 1 + 5 = 6.
        # Buffer len 5.
        # Ptr should be 6 % 5 = 1.
        self.assertEqual(self.spec.spectrogram_ptr, 1)

        # Index 0 should be the last write (i=4)
        expected = np.zeros_like(frame)
        expected[0] = 4
        self.assertTrue(np.array_equal(self.spec.spectrogram_buffer[0], expected))

if __name__ == "__main__":
    unittest.main()
