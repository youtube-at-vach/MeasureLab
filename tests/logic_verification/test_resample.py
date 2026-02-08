
import unittest
import sys

# Try to import heavy dependencies
try:
    import numpy as np
    import scipy.signal
    # Assuming src.core.analysis is available if numpy/scipy are
    from src.core.analysis import AudioCalc
    HAS_DEPS = True
except ImportError:
    HAS_DEPS = False

@unittest.skipUnless(HAS_DEPS, "Heavy dependencies (numpy/scipy) not installed")
class TestResampleFunctional(unittest.TestCase):
    def test_resample_no_change(self):
        sr = 48000
        data = np.zeros((100, 2))
        res = AudioCalc.resample(data, sr, sr)
        self.assertTrue(np.array_equal(data, res))

    def test_resample_44100_to_48000_frequency(self):
        """
        Verify resampling from 44.1kHz to 48kHz preserves frequency and amplitude.
        """
        # Create a simple sine wave at 1kHz
        src_sr = 44100
        dst_sr = 48000
        duration = 1.0
        t = np.linspace(0, duration, int(duration * src_sr), endpoint=False)
        freq = 1000.0
        sig = np.sin(2 * np.pi * freq * t)

        # Make stereo, same signal
        data = np.stack((sig, sig), axis=1)

        # Resample
        res = AudioCalc.resample(data, src_sr, dst_sr)

        # 1. Check shape
        # expected len is roughly len * 48000 / 44100
        expected_len = int(len(data) * dst_sr / src_sr)
        # Tolerance of a few samples due to polyphase filter delay/group delay handling
        self.assertTrue(abs(res.shape[0] - expected_len) <= 5)
        self.assertEqual(res.shape[1], 2)

        # 2. Check Frequency Preservation (FFT)
        # We analyze the first channel
        res_sig = res[:, 0]

        # Windowing to reduce spectral leakage
        window = np.blackman(len(res_sig))
        fft_res = np.fft.rfft(res_sig * window)
        fft_freqs = np.fft.rfftfreq(len(res_sig), 1.0 / dst_sr)

        # Find peak frequency
        idx_peak = np.argmax(np.abs(fft_res))
        peak_freq = fft_freqs[idx_peak]

        # The peak should be very close to 1000Hz.
        # Resolution is dst_sr / N_samples ~= 48000 / 48000 = 1Hz.
        self.assertAlmostEqual(peak_freq, freq, delta=2.0)

        # 3. Check Amplitude Preservation
        # RMS of sine wave is Amplitude / sqrt(2) = 1/sqrt(2) ~= 0.707
        # Resampling might introduce slight gain changes or filter ripple.
        input_rms = np.sqrt(np.mean(sig**2))
        output_rms = np.sqrt(np.mean(res_sig**2))

        # Allow small deviation (e.g., 0.1dB which is ~1%)
        self.assertAlmostEqual(output_rms, input_rms, delta=0.01)

    def test_resample_downsample_frequency(self):
        """
        Verify resampling from 48kHz to 24kHz (downsampling) preserves frequency.
        """
        # Downsample 48k -> 24k
        src_sr = 48000
        dst_sr = 24000
        duration = 0.5
        t = np.linspace(0, duration, int(duration * src_sr), endpoint=False)
        freq = 5000.0
        sig = np.sin(2 * np.pi * freq * t)
        data = np.stack((sig,), axis=1)

        res = AudioCalc.resample(data, src_sr, dst_sr)

        # Check shape
        expected_len = int(len(data) * dst_sr / src_sr)
        self.assertTrue(abs(res.shape[0] - expected_len) <= 5)

        # Check Frequency
        res_sig = res[:, 0]
        window = np.blackman(len(res_sig))
        fft_res = np.fft.rfft(res_sig * window)
        fft_freqs = np.fft.rfftfreq(len(res_sig), 1.0 / dst_sr)

        idx_peak = np.argmax(np.abs(fft_res))
        peak_freq = fft_freqs[idx_peak]

        self.assertAlmostEqual(peak_freq, freq, delta=5.0) # slightly looser delta due to lower resolution

    def test_resample_odd_ratio(self):
        """
        Verify resampling with odd ratio (44100 -> 44101) works without error.
        """
        # Stress test with odd ratio (prime-ish)
        src_sr = 44100
        dst_sr = 44101
        data = np.zeros((1000, 1)) # Short signal to avoid huge filter calc time

        res = AudioCalc.resample(data, src_sr, dst_sr)

        self.assertIsInstance(res, np.ndarray)
        # Verify length is approximately correct
        expected = 1000 * 44101 / 44100
        self.assertTrue(abs(len(res) - expected) < 5)

if __name__ == '__main__':
    unittest.main()
