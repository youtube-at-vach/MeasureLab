import unittest
from unittest.mock import MagicMock, patch
import sys
import numpy as np
import os
import tempfile
import scipy.signal  # noqa: F401
# Pre-load analysis to avoid re-import issues with scipy during sys.modules patching
try:
    from src.core.analysis import AudioCalc  # noqa: F401
except ImportError:
    pass

class TestRecorderMemory(unittest.TestCase):
    def setUp(self):
        # Create a mock for QtCore that has a proper QThread class
        qt_core = MagicMock()
        class MockQThread:
            def __init__(self, parent=None): pass
            def run(self): pass
            def start(self): self.run()
            def wait(self): pass
            finished = MagicMock()

        qt_core.QThread = MockQThread
        # pyqtSignal must be a class-like thing or handled by QThread, but here it's used as class attribute
        # In the code: finished = pyqtSignal(...)
        # So pyqtSignal needs to be something that returns a descriptor or similar?
        # But usually just MagicMock() works if it's assigned to a class attribute.
        # NOTE: pyqtSignal(bool, str) calls MagicMock(bool, str), which interprets bool as 'spec', causing AttributeError on 'emit'.
        # We must use a lambda/function to swallow args and return a fresh MagicMock.
        qt_core.pyqtSignal = lambda *args, **kwargs: MagicMock()

        # Patch sys.modules to mock sounddevice and PyQt6
        self.modules_patcher = patch.dict(sys.modules, {
            'sounddevice': MagicMock(),
            'PyQt6.QtCore': qt_core,
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

    def test_save_recording_uses_buffered_writes(self):
        """Verify that save_recording uses buffered writes (np.concatenate is called)."""
        # Setup some data
        chunk = np.zeros((100, 2), dtype=np.float32)
        self.player.record_buffer.append(chunk)
        self.player.record_buffer.append(chunk)

        filepath = os.path.join(self.temp_dir.name, "test_output.wav")

        # Mock np.concatenate to verify it is called for buffering
        with patch('numpy.concatenate') as mock_concat:
            # We must return a valid array to prevent downstream errors if needed
            # But the mock will handle it if we don't set side_effect to raise
            mock_concat.return_value = np.zeros((200, 2), dtype=np.float32)

            success, msg = self.player.save_recording(filepath)

            self.assertTrue(success, f"Save failed: {msg}")
            self.assertTrue(mock_concat.called, "np.concatenate should be called for buffered writes!")

    def test_worker_run_uses_buffered_writes(self):
        """Verify that FileSaveWorker.run uses buffered writes (np.concatenate is called)."""
        # Setup some data
        chunk = np.zeros((100, 2), dtype=np.float32)
        record_buffer = [chunk, chunk]

        filepath = os.path.join(self.temp_dir.name, "test_worker_output.wav")

        worker = self.FileSaveWorker(record_buffer, 48000, filepath)

        # Verify worker.run exists and is the method we defined
        # print(f"Worker type: {type(worker)}")
        # print(f"Worker run: {worker.run}")

        # Mock np.concatenate
        with patch('numpy.concatenate') as mock_concat:
            mock_concat.return_value = np.zeros((200, 2), dtype=np.float32)

            # Run the worker synchronously
            worker.run()

            # print(f"Mock call count: {mock_concat.call_count}")

            self.assertTrue(mock_concat.called, "np.concatenate should be called inside worker for buffered writes!")

if __name__ == '__main__':
    unittest.main()
