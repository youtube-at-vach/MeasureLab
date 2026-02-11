import unittest
from unittest.mock import MagicMock
import sys
import numpy as np

# Mock dependencies
sys.modules['sounddevice'] = MagicMock()
qt_core = MagicMock()
qt_core.QThread = MagicMock
qt_core.pyqtSignal = lambda *args: MagicMock()
sys.modules['PyQt6.QtCore'] = qt_core
sys.modules['PyQt6.QtWidgets'] = MagicMock()

from src.gui.widgets.recorder_player import RecorderPlayer  # noqa: E402
from src.core.audio_engine import AudioEngine  # noqa: E402

class TestRecorderPlayerLogic(unittest.TestCase):
    def setUp(self):
        self.audio_engine = MagicMock(spec=AudioEngine)
        self.audio_engine.sample_rate = 48000
        self.player = RecorderPlayer(self.audio_engine)
        # Mock the write queue for tests that expect recording
        self.player._write_queue = MagicMock()

    def test_recording_stereo(self):
        self.player.is_recording = True
        self.player.input_mode = "Stereo"

        frames = 100
        channels = 2
        indata = np.random.rand(frames, channels).astype(np.float32)
        outdata = np.zeros((frames, channels), dtype=np.float32)

        self.player.audio_callback(indata, outdata, frames, None, None)

        # Verify data was put into queue instead of buffer
        self.player._write_queue.put.assert_called_once()
        args, _ = self.player._write_queue.put.call_args
        self.assertTrue(np.array_equal(args[0], indata))

        self.assertEqual(self.player.recorded_samples, frames)

    def test_recording_left(self):
        self.player.is_recording = True
        self.player.input_mode = "Left"

        frames = 100
        channels = 2
        indata = np.random.rand(frames, channels).astype(np.float32)
        outdata = np.zeros((frames, channels), dtype=np.float32)

        self.player.audio_callback(indata, outdata, frames, None, None)

        # Verify data was put into queue
        self.player._write_queue.put.assert_called_once()
        args, _ = self.player._write_queue.put.call_args
        # Should be indata[:, 0:1] (keep 2D)
        expected = indata[:, 0:1]
        self.assertTrue(np.array_equal(args[0], expected))

        self.assertEqual(self.player.recorded_samples, frames)

    def test_recording_right(self):
        self.player.is_recording = True
        self.player.input_mode = "Right"

        frames = 100
        channels = 2
        indata = np.random.rand(frames, channels).astype(np.float32)
        outdata = np.zeros((frames, channels), dtype=np.float32)

        self.player.audio_callback(indata, outdata, frames, None, None)

        # Verify data was put into queue
        self.player._write_queue.put.assert_called_once()
        args, _ = self.player._write_queue.put.call_args
        # Should be indata[:, 1:2] (keep 2D)
        expected = indata[:, 1:2]
        self.assertTrue(np.array_equal(args[0], expected))

        self.assertEqual(self.player.recorded_samples, frames)

    def test_playback_stereo(self):
        self.player.is_playing = True
        self.player.output_mode = "Stereo"

        frames = 100
        channels = 2

        # Prepare playback buffer
        playback_data = np.random.rand(frames, channels).astype(np.float32)
        self.player.playback_buffer = playback_data

        indata = np.zeros((frames, channels), dtype=np.float32)
        outdata = np.zeros((frames, channels), dtype=np.float32)

        self.player.audio_callback(indata, outdata, frames, None, None)

        np.testing.assert_array_equal(outdata, playback_data)
        self.assertEqual(self.player.playback_pos, frames)

    def test_playback_mono_output(self):
        self.player.is_playing = True
        self.player.output_mode = "Mono"

        frames = 100
        channels = 2 # Playback buffer is stereo

        playback_data = np.random.rand(frames, channels).astype(np.float32)
        self.player.playback_buffer = playback_data

        indata = np.zeros((frames, channels), dtype=np.float32)
        outdata = np.zeros((frames, channels), dtype=np.float32)

        self.player.audio_callback(indata, outdata, frames, None, None)

        # Expected: mean of channels applied to both output channels
        mono_mix = np.mean(playback_data, axis=1)
        expected = np.zeros_like(outdata)
        expected[:, 0] = mono_mix
        expected[:, 1] = mono_mix

        np.testing.assert_allclose(outdata, expected, rtol=1e-5)

    def test_playback_left_output(self):
        self.player.is_playing = True
        self.player.output_mode = "Left"

        frames = 100
        channels = 2

        playback_data = np.random.rand(frames, channels).astype(np.float32)
        self.player.playback_buffer = playback_data

        indata = np.zeros((frames, channels), dtype=np.float32)
        outdata = np.zeros((frames, channels), dtype=np.float32)

        self.player.audio_callback(indata, outdata, frames, None, None)

        expected = np.zeros_like(outdata)
        expected[:, 0] = playback_data[:, 0]
        expected[:, 1] = 0

        np.testing.assert_array_equal(outdata, expected)

    def test_playback_right_output(self):
        self.player.is_playing = True
        self.player.output_mode = "Right"

        frames = 100
        channels = 2

        playback_data = np.random.rand(frames, channels).astype(np.float32)
        self.player.playback_buffer = playback_data

        indata = np.zeros((frames, channels), dtype=np.float32)
        outdata = np.zeros((frames, channels), dtype=np.float32)

        self.player.audio_callback(indata, outdata, frames, None, None)

        expected = np.zeros_like(outdata)
        expected[:, 0] = 0
        # Logic: out_slice[:, 1] = chunk[:, 0] if file_ch == 1 else chunk[:, 1] if file_ch > 1 else 0
        expected[:, 1] = playback_data[:, 1]

        np.testing.assert_array_equal(outdata, expected)

    def test_playback_gain(self):
        self.player.is_playing = True
        self.player.output_mode = "Stereo"
        self.player.playback_gain_db = -6.0 # Half amplitude roughly (actually 10^(-6/20) approx 0.501)

        frames = 100
        channels = 2
        playback_data = np.ones((frames, channels), dtype=np.float32)
        self.player.playback_buffer = playback_data

        indata = np.zeros((frames, channels), dtype=np.float32)
        outdata = np.zeros((frames, channels), dtype=np.float32)

        self.player.audio_callback(indata, outdata, frames, None, None)

        gain = 10 ** (-6.0 / 20.0)
        np.testing.assert_allclose(outdata, playback_data * gain, rtol=1e-5)

    def test_playback_loop(self):
        self.player.is_playing = True
        self.player.loop_playback = True
        self.player.output_mode = "Stereo"

        # Buffer length 50, request 100 frames -> should play twice
        frames_req = 100
        frames_buf = 50
        channels = 2

        # Create a ramp to easily verify continuity
        playback_data = np.arange(frames_buf * channels).reshape(frames_buf, channels).astype(np.float32)
        self.player.playback_buffer = playback_data

        indata = np.zeros((frames_req, channels), dtype=np.float32)
        outdata = np.zeros((frames_req, channels), dtype=np.float32)

        self.player.audio_callback(indata, outdata, frames_req, None, None)

        # Expected output: buffer repeated twice
        expected = np.concatenate([playback_data, playback_data], axis=0)
        np.testing.assert_array_equal(outdata, expected)
        self.assertEqual(self.player.playback_pos, 0) # Should be back at 0 after exactly 2 loops?
        # Wait, if frames_req is exactly multiple of frames_buf, loop logic:
        # 1st loop: copies 50, pos becomes 50 -> reset to 0
        # 2nd loop: copies 50, pos becomes 50 -> reset to 0
        # So yes, pos should be 0.

    def test_playback_stop_at_end(self):
        self.player.is_playing = True
        self.player.loop_playback = False
        self.player.output_mode = "Stereo"

        frames_req = 100
        frames_buf = 50
        channels = 2

        playback_data = np.ones((frames_buf, channels), dtype=np.float32)
        self.player.playback_buffer = playback_data

        indata = np.zeros((frames_req, channels), dtype=np.float32)
        # Initialize outdata with -1 to verify zero-filling
        outdata = np.full((frames_req, channels), -1.0, dtype=np.float32)

        self.player.audio_callback(indata, outdata, frames_req, None, None)

        # First 50 frames should be 1s
        np.testing.assert_array_equal(outdata[:50], np.ones((50, channels), dtype=np.float32))
        # Remaining frames should be 0s
        np.testing.assert_array_equal(outdata[50:], np.zeros((50, channels), dtype=np.float32))

        self.assertFalse(self.player.is_playing)

    def test_idle_callback(self):
        self.player.is_playing = False
        self.player.is_recording = False

        frames = 100
        channels = 2
        indata = np.random.rand(frames, channels).astype(np.float32)
        # Initialize outdata with garbage
        outdata = np.full((frames, channels), 999.0, dtype=np.float32)

        self.player.audio_callback(indata, outdata, frames, None, None)

        # Should be all zeros
        np.testing.assert_array_equal(outdata, np.zeros((frames, channels), dtype=np.float32))
        # Record buffer should be empty
        self.assertEqual(len(self.player.record_buffer), 0)

if __name__ == '__main__':
    unittest.main()
