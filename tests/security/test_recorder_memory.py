import unittest
from unittest.mock import MagicMock, patch
import sys
import numpy as np
import os
import tempfile

class TestRecorderMemory(unittest.TestCase):
    def setUp(self):
        # Patch sys.modules to mock sounddevice and PyQt6
        self.modules_patcher = patch.dict(sys.modules, {
            'sounddevice': MagicMock(),
            'PyQt6.QtCore': MagicMock(),
            'PyQt6.QtWidgets': MagicMock()
        })
        self.modules_patcher.start()

        # Import RecorderPlayer locally to ensure it uses the mocked modules
        if 'src.gui.widgets.recorder_player' in sys.modules:
            del sys.modules['src.gui.widgets.recorder_player']

        from src.gui.widgets.recorder_player import RecorderPlayer, FileSaveWorker
        self.RecorderPlayer = RecorderPlayer
        self.FileSaveWorker = FileSaveWorker

        self.audio_engine = MagicMock()
        self.audio_engine.sample_rate = 48000
        self.player = self.RecorderPlayer(self.audio_engine)
        self.temp_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp_dir.cleanup()
        self.modules_patcher.stop()

    def test_save_recording_does_not_use_concatenate(self):
        """Verify that save_recording does not use np.concatenate."""
        # Setup some data
        chunk = np.zeros((100, 2), dtype=np.float32)
        self.player.record_buffer.append(chunk)
        self.player.record_buffer.append(chunk)

        filepath = os.path.join(self.temp_dir.name, "test_output.wav")

        # Mock np.concatenate to fail if called
        with patch('numpy.concatenate') as mock_concat:
            mock_concat.side_effect = AssertionError("np.concatenate should not be called!")

            # This should NOT trigger the assertion
            success, msg = self.player.save_recording(filepath)

            self.assertTrue(success, f"Save failed: {msg}")
            self.assertFalse(mock_concat.called, "np.concatenate was called!")

    def test_worker_run_does_not_use_concatenate(self):
        """Verify that FileSaveWorker.run does not use np.concatenate."""
        # Setup some data
        chunk = np.zeros((100, 2), dtype=np.float32)
        record_buffer = [chunk, chunk]

        filepath = os.path.join(self.temp_dir.name, "test_worker_output.wav")

        worker = self.FileSaveWorker(record_buffer, 48000, filepath)

        # Mock np.concatenate
        with patch('numpy.concatenate') as mock_concat:
            mock_concat.side_effect = AssertionError("np.concatenate should not be called!")

            # Run the worker synchronously
            worker.run()

            self.assertFalse(mock_concat.called, "np.concatenate was called inside worker!")

if __name__ == '__main__':
    unittest.main()
