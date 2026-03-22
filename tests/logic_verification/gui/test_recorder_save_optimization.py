
import unittest
from unittest.mock import MagicMock, patch
import sys
import numpy as np
import os
import soundfile as sf
import tempfile
try:
    from src.core.analysis import AudioCalc  # noqa: F401
except ImportError:
    pass

class TestRecorderSaveOptimization(unittest.TestCase):
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

        from src.gui.widgets.recorder_player import RecorderPlayer
        self.RecorderPlayer = RecorderPlayer

        self.audio_engine = MagicMock()
        self.audio_engine.sample_rate = 48000
        self.player = self.RecorderPlayer(self.audio_engine)
        self.temp_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        # Cleanup temp file if exists (from player)
        if self.player._temp_record_file and os.path.exists(self.player._temp_record_file):
            try:
                os.remove(self.player._temp_record_file)
            except OSError:
                pass
        self.temp_dir.cleanup()
        self.modules_patcher.stop()

    def test_save_recording_content(self):
        """Verify that saving data chunk-by-chunk produces the correct file."""
        frames_per_chunk = 100
        n_chunks = 5
        channels = 2

        expected_data = []

        # Use public API to record
        self.player.start_recording()

        for i in range(n_chunks):
            # Create distinct data for each chunk within [-1, 1]
            val = (i / n_chunks) * 0.8  # 0.0, 0.16, 0.32, 0.48, 0.64
            chunk = np.full((frames_per_chunk, channels), val, dtype=np.float32)

            # Simulate callback
            self.player.audio_callback(chunk, np.zeros_like(chunk), frames_per_chunk, None, None)
            expected_data.append(chunk)

        self.player.stop_recording()

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

        self.player.input_mode = "Right" # Force mono or specific channel?
        # Actually input_mode="Right" selects channel 1 (if stereo input).
        # But here we provide mono input to callback?
        # audio_callback logic:
        # if input_mode == "Right": rec_data = indata[:, 1:2] if 2ch else zeros

        # Let's assume we want to test mono recording.
        # If we feed 1ch input and set mode to something appropriate?
        # If input_mode="Stereo" and input is 1ch, rec_data is 1ch.
        self.player.input_mode = "Stereo"

        chunk = np.random.rand(frames_per_chunk, channels).astype(np.float32)

        self.player.start_recording()
        self.player.audio_callback(chunk, np.zeros((frames_per_chunk, 2)), frames_per_chunk, None, None)
        self.player.stop_recording()

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
