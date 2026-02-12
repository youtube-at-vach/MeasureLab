
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
        if self.player._temp_record_file and os.path.exists(self.player._temp_record_file):
            try:
                os.remove(self.player._temp_record_file)
            except OSError:
                pass
        self.temp_dir.cleanup()
        self.modules_patcher.stop()

    def test_audio_callback_streams_to_disk(self):
        """Verify audio callback pushes to queue/disk instead of memory buffer."""
        self.player.start_recording()
        chunk = np.zeros((100, 2), dtype=np.float32)

        self.player.audio_callback(chunk, np.zeros_like(chunk), 100, None, None)

        # Buffer should be empty (primary fix for OOM)
        self.assertEqual(len(self.player.record_buffer), 0)

        self.player.stop_recording()

        # Temp file should exist and have data
        self.assertTrue(os.path.exists(self.player._temp_record_file))
        # Header (44) + 100 frames * 2 channels * 4 bytes = 844 bytes
        self.assertGreater(os.path.getsize(self.player._temp_record_file), 44)

    def test_save_recording_from_temp_file(self):
        """Verify save_recording copies from temp file correctly."""
        # Create some recording data
        self.player.start_recording()
        chunk = np.zeros((100, 2), dtype=np.float32)
        self.player.audio_callback(chunk, np.zeros_like(chunk), 100, None, None)
        self.player.stop_recording()

        filepath = os.path.join(self.temp_dir.name, "output.wav")

        success, msg = self.player.save_recording(filepath)

        self.assertTrue(success, f"Save failed: {msg}")
        self.assertTrue(os.path.exists(filepath))
        self.assertGreater(os.path.getsize(filepath), 44)

    def test_worker_uses_streaming_copy(self):
        """Verify that FileSaveWorker processes the file path, not a buffer."""

        # Create a dummy source file
        source_path = os.path.join(self.temp_dir.name, "source.wav")
        import soundfile as sf
        sf.write(source_path, np.zeros((100, 2)), 48000)

        target_path = os.path.join(self.temp_dir.name, "target.wav")

        # Worker initialized with paths, not buffer
        worker = self.FileSaveWorker(source_path, target_path)

        # Run worker synchronously
        worker.run()

        self.assertTrue(os.path.exists(target_path))
        self.assertEqual(os.path.getsize(target_path), os.path.getsize(source_path))

if __name__ == '__main__':
    unittest.main()
