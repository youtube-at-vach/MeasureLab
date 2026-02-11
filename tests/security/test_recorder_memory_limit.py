import unittest
from unittest.mock import MagicMock, patch
import sys
import numpy as np

# Mock sounddevice before importing anything that uses it
sys.modules['sounddevice'] = MagicMock()

from src.gui.widgets.recorder_player import RecorderPlayer  # noqa: E402
from src.core.analysis import AudioCalc  # noqa: E402

class TestRecorderMemoryLimit(unittest.TestCase):
    def setUp(self):
        self.mock_engine = MagicMock()
        self.mock_engine.sample_rate = 48000
        # RecorderPlayer expects audio_engine.sample_rate

        self.recorder = RecorderPlayer(self.mock_engine)

    def test_unbounded_recording(self):
        """
        Demonstrates that recording continues indefinitely without a limit.
        (This test expects the current vulnerable behavior).
        """
        self.recorder.start_recording()

        # Simulate callbacks
        frames = 1000
        indata = np.zeros((frames, 2), dtype=np.float32)
        outdata = np.zeros((frames, 2), dtype=np.float32)

        # Call it many times
        for _ in range(10):
            self.recorder.audio_callback(indata, outdata, frames, None, None)

        self.assertTrue(self.recorder.is_recording)
        self.assertEqual(self.recorder.recorded_samples, 10 * frames)

    @patch.object(AudioCalc, 'MAX_AUDIO_SAMPLES', 5000)
    def test_recording_limit_enforcement(self):
        """
        Verifies that recording stops when the limit is reached.
        This test is expected to FAIL before the fix.
        """
        self.recorder.start_recording()

        # Frame size 1000. Limit is 5000.
        frames = 1000
        indata = np.zeros((frames, 2), dtype=np.float32)
        outdata = np.zeros((frames, 2), dtype=np.float32)

        # 1. frames=1000, total=1000
        self.recorder.audio_callback(indata, outdata, frames, None, None)
        self.assertTrue(self.recorder.is_recording)

        # 2. frames=1000, total=2000
        self.recorder.audio_callback(indata, outdata, frames, None, None)

        # 3. frames=1000, total=3000
        self.recorder.audio_callback(indata, outdata, frames, None, None)

        # 4. frames=1000, total=4000
        self.recorder.audio_callback(indata, outdata, frames, None, None)

        # 5. frames=1000, total=5000 (Exactly limit)
        self.recorder.audio_callback(indata, outdata, frames, None, None)
        # Assuming we check limit AFTER adding, or BEFORE?
        # If we check after, it might stop now for NEXT frame.
        # If we check "if current + frames > limit", it might stop BEFORE adding this chunk.

        # 6. frames=1000, total=6000 (Exceeds limit)
        self.recorder.audio_callback(indata, outdata, frames, None, None)

        # ASSERTION: Should have stopped
        self.assertFalse(self.recorder.is_recording, "Recording should stop when limit is exceeded")

        # Check if flag is set (part of the fix)
        self.assertTrue(self.recorder.recording_limit_reached)

if __name__ == '__main__':
    unittest.main()
