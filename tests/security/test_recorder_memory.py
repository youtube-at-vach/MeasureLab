import unittest
from unittest.mock import MagicMock, patch
import sys
import numpy as np
import os
import tempfile
import time
import soundfile as sf
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
        self.temp_dir.cleanup()
        self.modules_patcher.stop()

    def test_streaming_to_disk(self):
        """Verify that audio data is streamed to disk and not held in memory."""
        # Start recording
        self.player.start_recording()
        temp_path = self.player._temp_file_path

        self.assertTrue(os.path.exists(temp_path), "Temp file should be created")
        self.assertEqual(len(self.player.record_buffer), 0, "Record buffer should be empty")

        # Simulate callbacks
        chunk = np.random.rand(1024, 2).astype(np.float32)
        out_chunk = np.zeros((1024, 2), dtype=np.float32)
        self.player.audio_callback(chunk, out_chunk, 1024, None, None)
        self.player.audio_callback(chunk, out_chunk, 1024, None, None)

        # Wait for writer thread to flush queue
        # It's async, so we give it a moment
        for _ in range(10):
            if os.path.getsize(temp_path) > 100:
                break
            time.sleep(0.05)

        # Check file size (should be > header)
        # 2048 samples * 2 ch * 4 bytes = 16KB approx
        size = os.path.getsize(temp_path)
        self.assertGreater(size, 1000, "Temp file size should increase significantly")

        # Verify record buffer is STILL empty
        self.assertEqual(len(self.player.record_buffer), 0, "Record buffer should remain empty")

        self.player.stop_recording()

        # Ensure thread logic cleaned up
        self.assertIsNone(self.player._writer_thread)

    def test_save_uses_streaming(self):
        """Verify saving copies from temp file."""
        # Create a dummy source file
        source_data = np.random.rand(1000, 2).astype(np.float32)
        tf = tempfile.NamedTemporaryFile(delete=False, suffix='.wav')
        # Write source as float to avoid clipping/quantization issues for comparison
        sf.write(tf.name, source_data, 48000, subtype='FLOAT')
        tf.close()

        # Inject the temp file into player state
        self.player._temp_file_path = tf.name

        target_path = os.path.join(self.temp_dir.name, "final.wav")

        # Perform save
        success, msg = self.player.save_recording(target_path, subtype='FLOAT')
        self.assertTrue(success, f"Save failed: {msg}")
        self.assertTrue(os.path.exists(target_path))

        # Verify content matches
        loaded_data, sr = sf.read(target_path, always_2d=True)
        np.testing.assert_allclose(loaded_data, source_data, atol=1e-5)

        os.remove(tf.name)

    def test_worker_uses_streaming(self):
        """Verify FileSaveWorker uses streaming (source path)."""
        # Create a dummy source file
        source_data = np.random.rand(1000, 2).astype(np.float32)
        tf = tempfile.NamedTemporaryFile(delete=False, suffix='.wav')
        sf.write(tf.name, source_data, 48000, subtype='FLOAT')
        tf.close()

        target_path = os.path.join(self.temp_dir.name, "worker_out.wav")

        # Instantiate worker with PATHS, not buffer
        worker = self.FileSaveWorker(tf.name, target_path, subtype='FLOAT')
        worker.run() # Synchronous run for test

        self.assertTrue(os.path.exists(target_path))
        loaded_data, sr = sf.read(target_path, always_2d=True)
        np.testing.assert_allclose(loaded_data, source_data, atol=1e-5)

        os.remove(tf.name)

if __name__ == '__main__':
    unittest.main()
