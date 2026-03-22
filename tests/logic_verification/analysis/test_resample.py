import unittest
import numpy as np

try:
    from src.core.analysis import AudioCalc

    deps_available = True
except ImportError:
    deps_available = False


@unittest.skipUnless(deps_available, "numpy or src.core.analysis not available")
class TestResampleAccuracy(unittest.TestCase):
    def test_frequency_and_amplitude_preservation(self):
        """
        Verify that resampling a sine wave preserves its frequency and amplitude
        when upsampling (44.1kHz -> 48kHz).
        """
        source_sr = 44100
        target_sr = 48000
        duration = 1.0
        freq = 1000.0

        # Generate 1kHz sine wave at 44.1kHz
        t = np.arange(int(source_sr * duration)) / source_sr
        signal = np.sin(2 * np.pi * freq * t)

        # Resample to 48kHz
        resampled_signal = AudioCalc.resample(signal, source_sr, target_sr)

        # Check new length
        # resample_poly logic: len * up / down.
        # 44100 * 48000 / 44100 = 48000.
        expected_len = int(len(signal) * target_sr / source_sr)
        self.assertAlmostEqual(len(resampled_signal), expected_len, delta=1)

        # Check Amplitude (RMS)
        # 1.0 amplitude sine wave has RMS = 0.707...
        original_rms = np.sqrt(np.mean(signal**2))
        resampled_rms = np.sqrt(np.mean(resampled_signal**2))

        # Allow small deviation due to filter ripple/windowing (0.01 is plenty, usually < 0.001)
        self.assertAlmostEqual(resampled_rms, original_rms, delta=0.01)

        # Check Frequency
        # Use FFT to find peak frequency
        # Apply window to reduce spectral leakage for better peak detection
        window = np.hanning(len(resampled_signal))
        fft_res = np.fft.rfft(resampled_signal * window)
        freqs = np.fft.rfftfreq(len(resampled_signal), 1 / target_sr)

        peak_idx = np.argmax(np.abs(fft_res))
        peak_freq = freqs[peak_idx]

        # Resolution of FFT is target_sr / N = 1Hz.
        self.assertAlmostEqual(peak_freq, freq, delta=1.0)

    def test_downsampling_accuracy(self):
        """
        Verify that resampling a sine wave preserves its frequency and amplitude
        when downsampling (48kHz -> 44.1kHz).
        """
        source_sr = 48000
        target_sr = 44100
        duration = 1.0
        freq = 1000.0

        # Generate 1kHz sine wave at 48kHz
        t = np.arange(int(source_sr * duration)) / source_sr
        signal = np.sin(2 * np.pi * freq * t)

        # Resample to 44.1kHz
        resampled_signal = AudioCalc.resample(signal, source_sr, target_sr)

        # Check new length
        expected_len = int(len(signal) * target_sr / source_sr)
        self.assertAlmostEqual(len(resampled_signal), expected_len, delta=1)

        # Check Amplitude (RMS)
        original_rms = np.sqrt(np.mean(signal**2))
        resampled_rms = np.sqrt(np.mean(resampled_signal**2))
        self.assertAlmostEqual(resampled_rms, original_rms, delta=0.01)

        # Check Frequency
        window = np.hanning(len(resampled_signal))
        fft_res = np.fft.rfft(resampled_signal * window)
        freqs = np.fft.rfftfreq(len(resampled_signal), 1 / target_sr)

        peak_idx = np.argmax(np.abs(fft_res))
        peak_freq = freqs[peak_idx]

        self.assertAlmostEqual(peak_freq, freq, delta=1.0)

    def test_edge_cases(self):
        """
        Verify behavior for invalid inputs and identity transforms.
        """
        # Invalid SR
        data = np.array([1.0, 2.0, 3.0])
        self.assertTrue(np.array_equal(AudioCalc.resample(data, 0, 48000), data))
        self.assertTrue(np.array_equal(AudioCalc.resample(data, 44100, -1), data))

        # Same SR
        self.assertTrue(np.array_equal(AudioCalc.resample(data, 44100, 44100), data))

    def test_resample_odd_ratio(self):
        src_sr = 44100
        dst_sr = 44101  # Very slight change, large GCD factors
        # data len 44100
        data = np.zeros((44100, 1))
        # This will trigger large up/down values.
        # up = 44101, down = 44100.
        res = AudioCalc.resample(data, src_sr, dst_sr)
        # Expected len: ceil(44100 * 44101 / 44100) = 44101
        self.assertEqual(res.shape[0], 44101)


if __name__ == "__main__":
    unittest.main()
