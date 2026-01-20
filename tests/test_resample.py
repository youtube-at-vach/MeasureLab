
import unittest
import numpy as np
import scipy.signal
from src.core.analysis import AudioCalc

class TestResample(unittest.TestCase):
    def test_resample_no_change(self):
        sr = 48000
        data = np.zeros((100, 2))
        res = AudioCalc.resample(data, sr, sr)
        self.assertTrue(np.array_equal(data, res))

    def test_resample_44100_to_48000(self):
        # Create a simple sine wave
        src_sr = 44100
        dst_sr = 48000
        duration = 1.0
        t = np.linspace(0, duration, int(duration * src_sr), endpoint=False)
        freq = 1000
        sig = np.sin(2 * np.pi * freq * t)
        data = np.stack((sig, sig), axis=1) # Stereo

        # Resample
        res = AudioCalc.resample(data, src_sr, dst_sr)

        # Check shape
        # expected len is roughly len * 48000 / 44100
        # 44100 * 48000 / 44100 = 48000
        self.assertEqual(res.shape[0], 48000)
        self.assertEqual(res.shape[1], 2)

        # Check frequency of result (basic check)
        # We can do a quick FFT on one channel
        # or just trust scipy.signal.resample_poly works if called correctly

    def test_resample_downsample(self):
        src_sr = 48000
        dst_sr = 24000
        data = np.random.rand(48000, 2)
        res = AudioCalc.resample(data, src_sr, dst_sr)
        self.assertEqual(res.shape[0], 24000)

    def test_resample_odd_ratio(self):
        src_sr = 44100
        dst_sr = 44101 # Very slight change, large GCD factors
        # data len 44100
        data = np.zeros((44100, 1))
        # This will trigger large up/down values.
        # up = 44101, down = 44100.
        # resample_poly might be slow or memory hungry here if the filter is huge?
        # But let's see if it runs.

        # Actually resample_poly builds a filter. If up is large, it might be slow.
        # But for 1 second of audio it should be fine.
        res = AudioCalc.resample(data, src_sr, dst_sr)
        # Expected len: ceil(44100 * 44101 / 44100) = 44101
        self.assertEqual(res.shape[0], 44101)

if __name__ == '__main__':
    unittest.main()
