import unittest
import numpy as np
import scipy.signal
import scipy.stats
import sys
import os
from unittest.mock import MagicMock

# Mock sounddevice before importing anything that uses it
sys.modules['sounddevice'] = MagicMock()

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from src.gui.widgets.signal_generator import SignalGenerator, SignalParameters

class TestSignalGeneratorChannels(unittest.TestCase):
    """Tests for channel independence and routing logic."""

    def test_independent_channels(self):
        # Mock AudioEngine
        mock_engine = MagicMock()
        mock_engine.sample_rate = 48000
        mock_engine.calibration.output_gain = 1.0

        sg = SignalGenerator(mock_engine)

        # Configure L: Sine 1000Hz
        sg.params_L.waveform = 'sine'
        sg.params_L.frequency = 1000.0
        sg.params_L.amplitude = 1.0

        # Configure R: Square 500Hz
        sg.params_R.waveform = 'square'
        sg.params_R.frequency = 500.0
        sg.params_R.amplitude = 0.5

        # Start generation
        sg.start_generation()

        # Simulate callback
        frames = 480
        outdata = np.zeros((frames, 2))

        # We need to access the callback that was registered
        args, _ = mock_engine.register_callback.call_args
        callback = args[0]

        callback(None, outdata, frames, None, None)

        # Analyze output
        sig_l = outdata[:, 0]
        sig_r = outdata[:, 1]

        # Check L (Sine)
        t = np.arange(frames) / 48000
        expected_l = np.sin(2 * np.pi * 1000 * t)

        # Check R (Square)
        expected_r = 0.5 * np.sign(np.sin(2 * np.pi * 500 * t))

        # Verify
        np.testing.assert_allclose(sig_l, expected_l, atol=1e-5, err_msg="Left Channel (Sine 1000Hz) mismatch")
        np.testing.assert_allclose(sig_r, expected_r, atol=1e-5, err_msg="Right Channel (Square 500Hz) mismatch")

        # Test Output Routing
        sg.output_mode = 'L'
        outdata.fill(0)
        callback(None, outdata, frames, None, None)
        assert np.all(outdata[:, 1] == 0), "Routing L: Right channel should be silent"
        assert not np.all(outdata[:, 0] == 0), "Routing L: Left channel should have signal"

        sg.output_mode = 'R'
        outdata.fill(0)
        callback(None, outdata, frames, None, None)
        assert np.all(outdata[:, 0] == 0), "Routing R: Left channel should be silent"
        assert not np.all(outdata[:, 1] == 0), "Routing R: Right channel should have signal"


class TestSignalGeneratorNoiseSpectral(unittest.TestCase):
    """Tests for noise color spectral properties."""

    def setUp(self):
        self.mock_engine = MagicMock()
        self.mock_engine.sample_rate = 48000
        self.mock_engine.calibration.output_gain = 1.0
        self.sg = SignalGenerator(self.mock_engine)
        self.params = SignalParameters()
        self.params.waveform = 'noise'

    def _get_spectral_slope(self, noise, sample_rate, low_cutoff=100, high_cutoff=10000):
        # Compute Power Spectral Density using Welch's method
        f, Pxx = scipy.signal.welch(noise, fs=sample_rate, nperseg=4096)

        # Select frequency range
        idx = np.where((f >= low_cutoff) & (f <= high_cutoff))[0]
        if len(idx) == 0:
            return 0.0

        f_sub = f[idx]
        Pxx_sub = Pxx[idx]

        # Log-log scale
        log_f = np.log10(f_sub)
        log_P = 10 * np.log10(Pxx_sub + 1e-12) # 10*log10 for Power in dB

        # Linear regression
        slope, intercept, r_value, p_value, std_err = scipy.stats.linregress(log_f, log_P)
        return slope

    def test_white_noise_spectral(self):
        self.params.noise_color = 'white'
        noise = self.sg._generate_noise_buffer(self.params, 48000, duration=1.0)
        slope = self._get_spectral_slope(noise, 48000)
        # White noise: Flat power spectrum. Slope ~ 0 dB/dec
        self.assertAlmostEqual(slope, 0, delta=1.5, msg=f"White noise slope {slope:.2f} should be ~0")

    def test_pink_noise_spectral(self):
        self.params.noise_color = 'pink'
        noise = self.sg._generate_noise_buffer(self.params, 48000, duration=1.0)
        slope = self._get_spectral_slope(noise, 48000)
        # Pink noise: 1/f power. -10 dB/dec
        self.assertAlmostEqual(slope, -10, delta=1.5, msg=f"Pink noise slope {slope:.2f} should be ~-10")

    def test_brown_noise_spectral(self):
        self.params.noise_color = 'brown'
        noise = self.sg._generate_noise_buffer(self.params, 48000, duration=1.0)
        slope = self._get_spectral_slope(noise, 48000)
        # Brown noise: 1/f^2 power. -20 dB/dec
        self.assertAlmostEqual(slope, -20, delta=1.5, msg=f"Brown noise slope {slope:.2f} should be ~-20")

    def test_blue_noise_spectral(self):
        self.params.noise_color = 'blue'
        noise = self.sg._generate_noise_buffer(self.params, 48000, duration=1.0)
        slope = self._get_spectral_slope(noise, 48000)
        # Blue noise: f power. +10 dB/dec
        self.assertAlmostEqual(slope, 10, delta=1.5, msg=f"Blue noise slope {slope:.2f} should be ~+10")

    def test_violet_noise_spectral(self):
        self.params.noise_color = 'violet'
        noise = self.sg._generate_noise_buffer(self.params, 48000, duration=1.0)
        slope = self._get_spectral_slope(noise, 48000)
        # Violet noise: f^2 power. +20 dB/dec
        self.assertAlmostEqual(slope, 20, delta=1.5, msg=f"Violet noise slope {slope:.2f} should be ~+20")

    def test_grey_noise_spectral(self):
        self.params.noise_color = 'grey'
        noise = self.sg._generate_noise_buffer(self.params, 48000, duration=1.0)

        f, Pxx = scipy.signal.welch(noise, fs=48000, nperseg=4096)

        # Get levels at specific frequencies (approx)
        # 100 Hz (Low)
        # 3000 Hz (Mid, near A-weighting peak)
        # 10000 Hz (High)

        idx_100 = np.argmin(np.abs(f - 100))
        idx_3k = np.argmin(np.abs(f - 3000))
        idx_10k = np.argmin(np.abs(f - 10000))

        P_100 = 10 * np.log10(Pxx[idx_100] + 1e-12)
        P_3k = 10 * np.log10(Pxx[idx_3k] + 1e-12)
        P_10k = 10 * np.log10(Pxx[idx_10k] + 1e-12)

        # Inverted A-weighting means "smile curve": High at low/high, low at mid
        # Assert low > mid
        self.assertGreater(P_100, P_3k + 8, f"Low freq (100Hz={P_100:.1f}dB) should be significantly louder than mid freq (3kHz={P_3k:.1f}dB) for Grey noise")
        # Assert high > mid (A-weighting at 10k is ~-2.5dB, at 3k is ~+1.2dB. Inverted: 10k is +2.5, 3k is -1.2. Diff ~3.7dB)
        # Relax tolerance slightly due to stochastic nature
        self.assertGreater(P_10k, P_3k + 1.0, f"High freq (10kHz={P_10k:.1f}dB) should be louder than mid freq (3kHz={P_3k:.1f}dB) for Grey noise")

    def test_normalization(self):
        self.params.noise_color = 'white'
        noise = self.sg._generate_noise_buffer(self.params, 48000, duration=1.0)
        max_amp = np.max(np.abs(noise))
        # Allow slight overshoot due to float precision if any, but implementation divides by max_val so it should be exactly 1.0 or less.
        self.assertLessEqual(max_amp, 1.0 + 1e-6, "Noise buffer should be normalized <= 1.0")
        # Ensure it's not silent
        self.assertGreater(max_amp, 0.5, "Noise buffer should be reasonably loud (normalized to peak 1)")

    def test_short_duration(self):
        self.params.noise_color = 'white'
        noise = self.sg._generate_noise_buffer(self.params, 48000, duration=0.1)
        expected_len = int(48000 * 0.1)
        self.assertEqual(len(noise), expected_len, "Buffer length mismatch for short duration")
        max_amp = np.max(np.abs(noise))
        self.assertLessEqual(max_amp, 1.0 + 1e-6)
        self.assertGreater(max_amp, 0.5)

if __name__ == '__main__':
    unittest.main()
