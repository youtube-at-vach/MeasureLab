import unittest
import numpy as np
import scipy.signal
import scipy.stats
import sys
from unittest.mock import MagicMock, patch

# Mock sounddevice before importing anything that uses it
try:
    import sounddevice  # noqa: F401
except (ImportError, OSError):
    sys.modules["sounddevice"] = MagicMock()

from src.gui.widgets.signal_generator import SignalGenerator, SignalParameters


class TestSignalGeneratorChannels(unittest.TestCase):
    """Tests for channel independence and routing logic."""

    def test_phase_control(self):
        """Verify phase offset control between channels."""
        # Mock AudioEngine
        mock_engine = MagicMock()
        mock_engine.sample_rate = 48000
        mock_engine.calibration.output_gain = 1.0

        sg = SignalGenerator(mock_engine)

        # Start generation to register callback
        sg.start_generation()

        # Capture callback
        args, _ = mock_engine.register_callback.call_args
        callback = args[0]

        frames = 480  # 10ms
        outdata = np.zeros((frames, 2))

        # Case 1: 0 vs 90 degrees (Orthogonal)
        sg.params_L.waveform = "sine"
        sg.params_L.frequency = 1000
        sg.params_L.amplitude = 1.0
        sg.params_L.phase_offset = 0.0
        sg.params_L._phase = 0  # Internal reset

        sg.params_R.waveform = "sine"
        sg.params_R.frequency = 1000
        sg.params_R.amplitude = 1.0
        sg.params_R.phase_offset = 90.0
        sg.params_R._phase = 0  # Internal reset

        sg.output_mode = "STEREO"

        callback(None, outdata, frames, None, None)

        left = outdata[:, 0]
        right = outdata[:, 1]

        # Correlation
        corr = np.sum(left * right) / (np.sqrt(np.sum(left**2)) * np.sqrt(np.sum(right**2)))
        self.assertLess(abs(corr), 0.01, "Correlation of 0 vs 90 deg should be ~0")

        # Case 2: 0 vs 180 degrees (Anti-phase)
        sg.params_R.phase_offset = 180.0
        # Manually reset phases for test determinism
        sg.params_L._phase = 0
        sg.params_R._phase = 0

        outdata.fill(0)
        callback(None, outdata, frames, None, None)

        left = outdata[:, 0]
        right = outdata[:, 1]

        corr = np.sum(left * right) / (np.sqrt(np.sum(left**2)) * np.sqrt(np.sum(right**2)))
        self.assertAlmostEqual(corr, -1.0, delta=0.01, msg="Correlation of 0 vs 180 deg should be ~-1.0")

    def test_independent_channels(self):
        # Mock AudioEngine
        mock_engine = MagicMock()
        mock_engine.sample_rate = 48000
        mock_engine.calibration.output_gain = 1.0

        sg = SignalGenerator(mock_engine)

        # Configure L: Sine 1000Hz
        sg.params_L.waveform = "sine"
        sg.params_L.frequency = 1000.0
        sg.params_L.amplitude = 1.0

        # Configure R: Square 500Hz
        sg.params_R.waveform = "square"
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
        sg.output_mode = "L"
        outdata.fill(0)
        callback(None, outdata, frames, None, None)
        assert np.all(outdata[:, 1] == 0), "Routing L: Right channel should be silent"
        assert not np.all(outdata[:, 0] == 0), "Routing L: Left channel should have signal"

        sg.output_mode = "R"
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
        self.params.waveform = "noise"

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
        log_P = 10 * np.log10(Pxx_sub + 1e-12)  # 10*log10 for Power in dB

        # Linear regression
        slope, intercept, r_value, p_value, std_err = scipy.stats.linregress(log_f, log_P)
        return slope

    def test_white_noise_spectral(self):
        self.params.noise_color = "white"
        noise = self.sg._generate_noise_buffer(self.params, 48000, duration=1.0)
        slope = self._get_spectral_slope(noise, 48000)
        # White noise: Flat power spectrum. Slope ~ 0 dB/dec
        self.assertAlmostEqual(slope, 0, delta=1.5, msg=f"White noise slope {slope:.2f} should be ~0")

    def test_pink_noise_spectral(self):
        self.params.noise_color = "pink"
        noise = self.sg._generate_noise_buffer(self.params, 48000, duration=1.0)
        slope = self._get_spectral_slope(noise, 48000)
        # Pink noise: 1/f power. -10 dB/dec
        self.assertAlmostEqual(slope, -10, delta=1.5, msg=f"Pink noise slope {slope:.2f} should be ~-10")

    def test_brown_noise_spectral(self):
        self.params.noise_color = "brown"
        noise = self.sg._generate_noise_buffer(self.params, 48000, duration=1.0)
        slope = self._get_spectral_slope(noise, 48000)
        # Brown noise: 1/f^2 power. -20 dB/dec
        self.assertAlmostEqual(slope, -20, delta=1.5, msg=f"Brown noise slope {slope:.2f} should be ~-20")

    def test_blue_noise_spectral(self):
        self.params.noise_color = "blue"
        noise = self.sg._generate_noise_buffer(self.params, 48000, duration=1.0)
        slope = self._get_spectral_slope(noise, 48000)
        # Blue noise: f power. +10 dB/dec
        self.assertAlmostEqual(slope, 10, delta=1.5, msg=f"Blue noise slope {slope:.2f} should be ~+10")

    def test_violet_noise_spectral(self):
        self.params.noise_color = "violet"
        noise = self.sg._generate_noise_buffer(self.params, 48000, duration=1.0)
        slope = self._get_spectral_slope(noise, 48000)
        # Violet noise: f^2 power. +20 dB/dec
        self.assertAlmostEqual(slope, 20, delta=1.5, msg=f"Violet noise slope {slope:.2f} should be ~+20")

    def test_grey_noise_spectral(self):
        self.params.noise_color = "grey"
        # Increase duration to 5.0s to reduce variance in spectral estimation
        noise = self.sg._generate_noise_buffer(self.params, 48000, duration=5.0)

        f, Pxx = scipy.signal.welch(noise, fs=48000, nperseg=4096)

        idx_100 = np.argmin(np.abs(f - 100))
        idx_3k = np.argmin(np.abs(f - 3000))
        idx_10k = np.argmin(np.abs(f - 10000))

        P_100 = 10 * np.log10(Pxx[idx_100] + 1e-12)
        P_3k = 10 * np.log10(Pxx[idx_3k] + 1e-12)
        P_10k = 10 * np.log10(Pxx[idx_10k] + 1e-12)

        self.assertGreater(
            P_100,
            P_3k + 8,
            f"Low freq (100Hz={P_100:.1f}dB) should be significantly louder than mid freq (3kHz={P_3k:.1f}dB) for Grey noise",
        )
        # Relax tolerance slightly due to stochastic nature (-1.0 instead of +1.0)
        self.assertGreater(
            P_10k,
            P_3k - 1.0,
            f"High freq (10kHz={P_10k:.1f}dB) should be louder than mid freq (3kHz={P_3k:.1f}dB) for Grey noise",
        )

    def test_normalization(self):
        self.params.noise_color = "white"
        noise = self.sg._generate_noise_buffer(self.params, 48000, duration=1.0)
        max_amp = np.max(np.abs(noise))
        self.assertLessEqual(max_amp, 1.0 + 1e-6, "Noise buffer should be normalized <= 1.0")
        self.assertGreater(max_amp, 0.5, "Noise buffer should be reasonably loud (normalized to peak 1)")

    def test_short_duration(self):
        self.params.noise_color = "white"
        noise = self.sg._generate_noise_buffer(self.params, 48000, duration=0.1)
        expected_len = int(48000 * 0.1)
        self.assertEqual(len(noise), expected_len, "Buffer length mismatch for short duration")
        max_amp = np.max(np.abs(noise))
        self.assertLessEqual(max_amp, 1.0 + 1e-6)
        self.assertGreater(max_amp, 0.5)


class TestSignalGeneratorFilter(unittest.TestCase):
    """Tests for LPF/HPF filtering logic."""

    class MockAudioEngine:
        def __init__(self):
            self.sample_rate = 48000
            self.callback = None
            self.calibration = MagicMock()
            self.calibration.output_gain = 1.0

        def register_callback(self, cb):
            self.callback = cb
            return 1

        def unregister_callback(self, cid):
            self.callback = None

    def test_lpf_filtering(self):
        engine = self.MockAudioEngine()
        sg = SignalGenerator(engine)

        sg.params_L.lpf_enabled = True
        sg.params_L.lpf_freq = 1000.0
        sg.params_L.lpf_order = 4

        # 1. Pass band (500 Hz)
        sg.params_L.waveform = "sine"
        sg.params_L.frequency = 500.0
        sg.params_L.amplitude = 1.0
        sg.start_generation()

        frames = 48000
        outdata = np.zeros((frames, 2))
        engine.callback(None, outdata, frames, 0.0, None)
        signal_pass = outdata[:, 0]
        rms_pass = np.sqrt(np.mean(signal_pass**2))

        # 2. Stop band (5000 Hz)
        sg.stop_generation()
        sg.params_L.frequency = 5000.0
        sg.start_generation()
        outdata.fill(0)
        engine.callback(None, outdata, frames, 0.0, None)
        signal_stop = outdata[:, 0]
        rms_stop = np.sqrt(np.mean(signal_stop**2))

        self.assertGreater(rms_pass, 0.5)
        self.assertLess(rms_stop, rms_pass * 0.1)

    def test_hpf_filtering(self):
        engine = self.MockAudioEngine()
        sg = SignalGenerator(engine)

        sg.params_L.hpf_enabled = True
        sg.params_L.hpf_freq = 1000.0
        sg.params_L.hpf_order = 4

        # 1. Pass band (2000 Hz)
        sg.params_L.waveform = "sine"
        sg.params_L.frequency = 2000.0
        sg.params_L.amplitude = 1.0
        sg.start_generation()

        frames = 48000
        outdata = np.zeros((frames, 2))
        engine.callback(None, outdata, frames, 0.0, None)
        signal_pass = outdata[:, 0]
        rms_pass = np.sqrt(np.mean(signal_pass**2))

        # 2. Stop band (200 Hz)
        sg.stop_generation()
        sg.params_L.frequency = 200.0
        sg.start_generation()
        outdata.fill(0)
        engine.callback(None, outdata, frames, 0.0, None)
        signal_stop = outdata[:, 0]
        rms_stop = np.sqrt(np.mean(signal_stop**2))

        self.assertGreater(rms_pass, 0.5)
        self.assertLess(rms_stop, rms_pass * 0.1)


class TestSignalGeneratorMLS(unittest.TestCase):
    """Tests for MLS generation, including fallback logic."""

    def test_mls_correctness(self):
        """
        Verifies that MLS generation produces a sequence of correct length and values.
        """
        mock_engine = MagicMock()
        sg = SignalGenerator(mock_engine)
        params = SignalParameters()
        params.waveform = "mls"

        for order in [10, 15]:
            params.mls_order = order

            # 1. Get reference signal using actual scipy
            import scipy.signal

            ref_seq, _ = scipy.signal.max_len_seq(order)
            ref_signal = ref_seq.astype(float) * 2 - 1

            # 2. Get generator output
            actual_signal = sg._generate_mls(params, 48000)

            # 3. Verify
            expected_len = 2**order - 1
            self.assertEqual(len(actual_signal), expected_len, f"Length mismatch for order {order}")

            if not np.allclose(actual_signal, ref_signal):
                self.fail(f"Generated MLS signal does not match Scipy implementation for order {order}")


class TestSignalGeneratorGolay(unittest.TestCase):
    """Tests for Golay complementary sequence generation."""

    def test_golay_pair_is_complementary(self):
        mock_engine = MagicMock()
        sg = SignalGenerator(mock_engine)
        params = SignalParameters()
        params.waveform = "golay"
        params.golay_order = 5

        params.golay_pair = "A"
        seq_a = sg._generate_golay(params, 48000)

        params.golay_pair = "B"
        seq_b = sg._generate_golay(params, 48000)

        self.assertEqual(len(seq_a), 2**params.golay_order)
        self.assertEqual(len(seq_b), 2**params.golay_order)
        self.assertTrue(np.all(np.isin(seq_a, [-1.0, 1.0])))
        self.assertTrue(np.all(np.isin(seq_b, [-1.0, 1.0])))

        ac_a = np.correlate(seq_a, seq_a, mode="full")
        ac_b = np.correlate(seq_b, seq_b, mode="full")
        summed = ac_a + ac_b
        center = len(summed) // 2

        self.assertEqual(summed[center], 2 * len(seq_a))
        off_center = np.delete(summed, center)
        np.testing.assert_allclose(off_center, 0.0, atol=1e-9)

    def test_golay_buffer_regenerates_on_pair_change(self):
        mock_engine = MagicMock()
        mock_engine.sample_rate = 48000
        sg = SignalGenerator(mock_engine)
        params = sg.params_L
        params.waveform = "golay"
        params.golay_order = 4
        params.golay_pair = "A"

        sg._prepare_buffer(params, mock_engine.sample_rate)
        seq_a = params._buffer.copy()

        sg.update_param(params, "golay_pair", "B")
        seq_b = params._buffer

        self.assertFalse(np.array_equal(seq_a, seq_b))


class TestSignalGeneratorMultitone(unittest.TestCase):
    """Tests for Multitone generation."""

    def _reference_multitone(self, params, sample_rate):
        """Reference implementation using the slow loop method."""
        if params.start_freq >= params.end_freq:
            freqs = np.array([params.start_freq])
        else:
            freqs = np.logspace(np.log10(params.start_freq), np.log10(params.end_freq), params.multitone_count)

        N = int(sample_rate)
        bin_width = sample_rate / N
        freqs = np.round(freqs / bin_width) * bin_width

        phases = np.pi * (np.arange(len(freqs)) ** 2) / len(freqs)

        t = np.arange(N) / sample_rate
        signal = np.zeros(N)

        for f, p in zip(freqs, phases, strict=False):
            signal += np.sin(2 * np.pi * f * t + p)

        max_val = np.max(np.abs(signal))
        if max_val > 0:
            signal /= max_val

        return signal

    def test_multitone_correctness(self):
        mock_engine = MagicMock()
        mock_engine.sample_rate = 48000
        mock_engine.calibration.output_gain = 1.0
        sg = SignalGenerator(mock_engine)

        sg.params_L.waveform = "multitone"
        sg.params_L.multitone_count = 31
        sg.params_L.start_freq = 20.0
        sg.params_L.end_freq = 20000.0

        optimized_signal = sg._generate_multitone(sg.params_L, 48000)
        reference_signal = self._reference_multitone(sg.params_L, 48000)

        np.testing.assert_allclose(optimized_signal, reference_signal, atol=1e-9, err_msg="Multitone output mismatch")

    def test_multitone_high_count(self):
        mock_engine = MagicMock()
        mock_engine.sample_rate = 48000
        sg = SignalGenerator(mock_engine)

        sg.params_L.multitone_count = 100
        sg.params_L.start_freq = 20.0
        sg.params_L.end_freq = 20000.0

        optimized_signal = sg._generate_multitone(sg.params_L, 48000)
        reference_signal = self._reference_multitone(sg.params_L, 48000)

        np.testing.assert_allclose(optimized_signal, reference_signal, atol=1e-9)

    def test_multitone_dc_nyquist_handling(self):
        mock_engine = MagicMock()
        mock_engine.sample_rate = 100
        sg = SignalGenerator(mock_engine)

        sg.params_L.multitone_count = 2
        sg.params_L.start_freq = 40.0
        sg.params_L.end_freq = 50.0

        optimized_signal = sg._generate_multitone(sg.params_L, 100)
        reference_signal = self._reference_multitone(sg.params_L, 100)

        np.testing.assert_allclose(optimized_signal, reference_signal, atol=1e-9)

    def test_multitone_zero_count(self):
        mock_engine = MagicMock()
        mock_engine.sample_rate = 48000
        sg = SignalGenerator(mock_engine)

        sg.params_L.multitone_count = 0
        sg.params_L.start_freq = 20.0
        sg.params_L.end_freq = 20000.0

        signal = sg._generate_multitone(sg.params_L, 48000)
        self.assertTrue(np.all(signal == 0), "Zero count should produce silence")


class TestSignalGeneratorFilterCache(unittest.TestCase):
    def setUp(self):
        self.mock_audio_engine = MagicMock()
        self.mock_audio_engine.sample_rate = 48000
        self.sg = SignalGenerator(self.mock_audio_engine)

    def test_lpf_caching(self):
        self.sg.params_L.lpf_enabled = True
        self.sg.params_L.lpf_freq = 1000.0
        self.sg.params_L.lpf_order = 4

        with patch("scipy.signal.butter") as mock_butter:
            mock_butter.return_value = np.zeros((2, 6))

            # First call
            sos1 = self.sg._get_filter_sos(self.sg.params_L, "low", 48000)
            mock_butter.assert_called_once()
            mock_butter.reset_mock()

            # Second call - same params
            sos2 = self.sg._get_filter_sos(self.sg.params_L, "low", 48000)
            mock_butter.assert_not_called()
            self.assertIs(sos1, sos2)

            # Third call - change params
            self.sg.params_L.lpf_freq = 2000.0
            self.sg._get_filter_sos(self.sg.params_L, "low", 48000)
            mock_butter.assert_called_once()

    def test_hpf_caching(self):
        self.sg.params_L.hpf_enabled = True
        self.sg.params_L.hpf_freq = 1000.0
        self.sg.params_L.hpf_order = 4

        with patch("scipy.signal.butter") as mock_butter:
            mock_butter.return_value = np.zeros((2, 6))

            # First call
            sos1 = self.sg._get_filter_sos(self.sg.params_L, "high", 48000)
            mock_butter.assert_called_once()
            mock_butter.reset_mock()

            # Second call - same params
            sos2 = self.sg._get_filter_sos(self.sg.params_L, "high", 48000)
            mock_butter.assert_not_called()
            self.assertIs(sos1, sos2)

            # Third call - change params
            self.sg.params_L.hpf_order = 2
            self.sg._get_filter_sos(self.sg.params_L, "high", 48000)
            mock_butter.assert_called_once()

    def test_independent_caches(self):
        self.sg.params_L.lpf_enabled = True
        self.sg.params_L.lpf_freq = 1000.0
        self.sg.params_L.hpf_enabled = True
        self.sg.params_L.hpf_freq = 2000.0

        with patch("scipy.signal.butter") as mock_butter:
            mock_butter.return_value = np.zeros((2, 6))

            # Calculate LPF
            self.sg._get_filter_sos(self.sg.params_L, "low", 48000)
            mock_butter.assert_called_once()
            mock_butter.reset_mock()

            # Calculate HPF
            self.sg._get_filter_sos(self.sg.params_L, "high", 48000)
            mock_butter.assert_called_once()
            mock_butter.reset_mock()

            # Call LPF again
            self.sg._get_filter_sos(self.sg.params_L, "low", 48000)
            mock_butter.assert_not_called()

            # Call HPF again
            self.sg._get_filter_sos(self.sg.params_L, "high", 48000)
            mock_butter.assert_not_called()


if __name__ == "__main__":
    unittest.main()
