import unittest
import sys
from unittest.mock import MagicMock

sys.modules["sounddevice"] = MagicMock()

import numpy as np  # noqa: E402
from src.gui.widgets.spectrogram import Spectrogram  # noqa: E402

# Mock AudioEngine
class MockAudioEngine:
    def __init__(self):
        self.sample_rate = 48000
        self.block_size = 1024
    def register_callback(self, cb):
        return 1
    def unregister_callback(self, cb_id):
        pass

class TestSpectrogramBuffer(unittest.TestCase):
    def setUp(self):
        self.audio_engine = MockAudioEngine()
        self.spectrogram = Spectrogram(self.audio_engine)
        # Set a small buffer size for easier testing
        self.spectrogram.fft_size = 10
        self.spectrogram.reset_buffers()
        # audio_buffer size is fft_size * 2 = 20
        # self.spectrogram.audio_buffer is (20, 2)

    def test_linear_fill(self):
        frames = 5
        indata = np.ones((frames, 2))
        outdata = np.zeros((frames, 2))

        # Fill first 5
        self.spectrogram._callback(indata, outdata, frames, None, None)
        self.assertEqual(self.spectrogram.audio_buffer_pos, 5)

        latest = self.spectrogram.get_latest_samples(5)
        np.testing.assert_array_equal(latest, np.ones((5, 2)))

    def test_wrap_around(self):
        # Buffer size is 20.
        # Fill 15 samples (ones)
        indata_1 = np.ones((15, 2))
        outdata = np.zeros((15, 2))
        self.spectrogram._callback(indata_1, outdata, 15, None, None)
        self.assertEqual(self.spectrogram.audio_buffer_pos, 15)

        # Fill 10 samples (twos). This should wrap.
        # 15 + 10 = 25. Mod 20 = 5.
        # Buffer should have:
        # [0-4]: 2 (newest part 2)
        # [5-14]: 1 (old ones) -> overwritten?
        # Wait.
        # Original: pos 15.
        # Write 10 samples.
        # 5 samples go to [15:20].
        # 5 samples go to [0:5].
        # Final pos = 5.

        indata_2 = np.full((10, 2), 2.0)
        self.spectrogram._callback(indata_2, outdata, 10, None, None)

        self.assertEqual(self.spectrogram.audio_buffer_pos, 5)

        # Check buffer content manually
        # [0:5] should be 2.0
        np.testing.assert_array_equal(self.spectrogram.audio_buffer[0:5], np.full((5, 2), 2.0))
        # [5:15] should be 1.0 (from first write)
        np.testing.assert_array_equal(self.spectrogram.audio_buffer[5:15], np.ones((10, 2)))
        # [15:20] should be 2.0 (from second write part 1)
        np.testing.assert_array_equal(self.spectrogram.audio_buffer[15:20], np.full((5, 2), 2.0))

        # Check get_latest_samples
        # We want latest 10 samples.
        # Should be all 2.0
        latest = self.spectrogram.get_latest_samples(10)
        np.testing.assert_array_equal(latest, np.full((10, 2), 2.0))

        # We want latest 15 samples.
        # Should be 10 samples of 2.0 and 5 samples of 1.0 (the ones at [10:15])
        # Wait. The newest data is the 10 samples of 2.0.
        # The data before that was the 15 samples of 1.0.
        # But we overwrote the first 5 samples of the buffer (which were 1.0) with 2.0.
        # So effective history is:
        # Time -25 to -10: 1.0
        # Time -10 to 0: 2.0
        # Wait, buffer size 20.
        # Only last 20 samples are kept.
        # We wrote 15 (1s), then 10 (2s). Total 25.
        # Only last 20 survive.
        # So oldest 5 (from the 15 1s) are lost.
        # Remaining 1s: 10 samples.
        # Newest 2s: 10 samples.
        # So latest 20 should be: 10 of 1.0, then 10 of 2.0.

        latest_20 = self.spectrogram.get_latest_samples(20)
        expected = np.concatenate((np.ones((10, 2)), np.full((10, 2), 2.0)))
        np.testing.assert_array_equal(latest_20, expected)

if __name__ == '__main__':
    unittest.main()
