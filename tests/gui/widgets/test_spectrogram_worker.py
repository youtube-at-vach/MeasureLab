import sys
import os
import unittest
import numpy as np
from unittest.mock import MagicMock

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

# Mock sounddevice to avoid import errors or audio device initialization
sys.modules['sounddevice'] = MagicMock()

try:
    from PyQt6.QtCore import QThreadPool, QObject, pyqtSignal
    from PyQt6.QtWidgets import QApplication
    from src.gui.widgets.spectrogram import SpectrogramWorker
except ImportError:
    SpectrogramWorker = None
    QApplication = None

class TestSpectrogramWorker(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Create a QApplication instance if one doesn't exist
        if QApplication is not None:
            cls.app = QApplication.instance()
            if cls.app is None:
                # Use offscreen platform for headless environments
                cls.app = QApplication(sys.argv + ['-platform', 'offscreen'])

    def test_spectrogram_worker_logic(self):
        """
        Verify that SpectrogramWorker correctly processes audio data and emits a result.
        """
        if SpectrogramWorker is None:
            self.skipTest("SpectrogramWorker or PyQt6 not found")

        # 1. Setup Input Data
        fft_size = 1024
        # Create dummy stereo data (random noise)
        # Shape: (frames, channels)
        raw_data = np.random.random((fft_size, 2))
        window_type = "hann"
        channel_mode = "Left"

        # 2. Instantiate Worker
        worker = SpectrogramWorker(raw_data, window_type, channel_mode)

        # 3. Connect Signal to capture result
        results = []
        def handle_result(data):
            results.append(data)

        # Connect using the signal defined in the worker's signals object
        worker.signals.result.connect(handle_result)

        # 4. Run Worker directly (synchronous execution for test)
        # QRunnable usually runs in a thread pool, but for testing logic we call run() directly.
        worker.run()

        # 5. Verify Output
        self.assertEqual(len(results), 1, "Worker should emit exactly one result")
        output = results[0]

        # Expected size for rfft is N//2 + 1
        expected_size = fft_size // 2 + 1
        self.assertEqual(len(output), expected_size, f"Output size should be {expected_size}")

        # Verify values are finite (dB calculation handles log(0) safely)
        self.assertTrue(np.all(np.isfinite(output)), "Output contains non-finite values")

        # basic check: should not be empty
        self.assertGreater(len(output), 0)

if __name__ == '__main__':
    unittest.main()
