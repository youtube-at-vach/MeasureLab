import unittest
from unittest.mock import MagicMock
import sys
import numpy as np
import os
import soundfile as sf
import tempfile

# Mock sounddevice
sys.modules['sounddevice'] = MagicMock()

# Mock PyQt6
sys.modules['PyQt6.QtCore'] = MagicMock()
sys.modules['PyQt6.QtWidgets'] = MagicMock()

from src.gui.widgets.recorder_player import RecorderPlayer  # noqa: E402

class TestRecorderSaveOptimization(unittest.TestCase):
    def setUp(self):
        self.audio_engine = MagicMock()
        self.audio_engine.sample_rate = 48000
        self.player = RecorderPlayer(self.audio_engine)
        self.temp_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_save_recording_content(self):
        """Verify that saving data chunk-by-chunk produces the correct file."""
        frames_per_chunk = 100
        n_chunks = 5
        channels = 2

        expected_data = []
        for i in range(n_chunks):
            # Create distinct data for each chunk within [-1, 1]
            val = (i / n_chunks) * 0.8  # 0.0, 0.16, 0.32, 0.48, 0.64
            chunk = np.full((frames_per_chunk, channels), val, dtype=np.float32)
            self.player.record_buffer.append(chunk)
            expected_data.append(chunk)

        expected_full = np.concatenate(expected_data, axis=0)

        filepath = os.path.join(self.temp_dir.name, "test_output.wav")

        # Use FLOAT subtype to avoid quantization noise for exact verification
        success, msg = self.player.save_recording(filepath, subtype='FLOAT')

        self.assertTrue(success, f"Save failed: {msg}")
        self.assertTrue(os.path.exists(filepath), "File was not created")

        # Read back and verify
        loaded_data, samplerate = sf.read(filepath, always_2d=True)

        self.assertEqual(samplerate, 48000)
        self.assertEqual(loaded_data.shape, expected_full.shape)
        np.testing.assert_array_equal(loaded_data, expected_full)

    def test_save_recording_mono(self):
        """Verify saving mono data works correctly."""
        frames_per_chunk = 100
        channels = 1

        chunk = np.random.rand(frames_per_chunk, channels).astype(np.float32)
        # Normalize to avoid clipping if any, though rand is [0, 1)
        self.player.record_buffer.append(chunk)

        filepath = os.path.join(self.temp_dir.name, "test_mono.wav")

        # Use FLOAT subtype to avoid quantization noise
        success, msg = self.player.save_recording(filepath, subtype='FLOAT')

        self.assertTrue(success, f"Save failed: {msg}")

        loaded_data, samplerate = sf.read(filepath, always_2d=True)

        # soundfile read always_2d=True returns (N, 1) for mono file
        self.assertEqual(loaded_data.shape, (frames_per_chunk, 1))
        np.testing.assert_allclose(loaded_data, chunk, atol=1e-7)

if __name__ == '__main__':
    unittest.main()
