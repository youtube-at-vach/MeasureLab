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
        sg.transition_ms = 0.0

        sg.params_L.waveform = "sine"
        sg.params_L.frequency = 1000
        sg.params_L.amplitude = 1.0
        sg.params_L.phase_offset = 0.0

        sg.params_R.waveform = "sine"
        sg.params_R.frequency = 1000
        sg.params_R.amplitude = 1.0
        sg.params_R.phase_offset = 90.0

        # Start generation to register callback
        sg.start_generation()

        # Capture callback
        args, _ = mock_engine.register_callback.call_args
        callback = args[0]

        frames = 480  # 10ms
        outdata = np.zeros((frames, 2))

        # Case 1: 0 vs 90 degrees (Orthogonal)
        sg.output_mode = "STEREO"

        callback(None, outdata, frames, None, None)

        left = outdata[:, 0]
        right = outdata[:, 1]

        # Correlation
        corr = np.sum(left * right) / (np.sqrt(np.sum(left**2)) * np.sqrt(np.sum(right**2)))
        self.assertLess(abs(corr), 0.01, "Correlation of 0 vs 90 deg should be ~0")

        # Case 2: 0 vs 180 degrees (Anti-phase)
        sg.update_param(sg.params_R, "phase_offset", 180.0)

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
        sg.transition_ms = 0.0

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

    def test_enabled_filters_are_applied_as_one_equivalent_sos_cascade(self):
        engine = self.MockAudioEngine()
        sg = SignalGenerator(engine)
        params = sg.params_L
        params.lpf_enabled = True
        params.lpf_freq = 18000.0
        params.hpf_enabled = True
        params.hpf_freq = 20.0
        params.notch_enabled = True
        params.notch_freq = 1000.0

        sections = [
            sg._get_filter_sos(params, "low", engine.sample_rate),
            sg._get_filter_sos(params, "high", engine.sample_rate),
            sg._get_filter_sos(params, "notch", engine.sample_rate),
        ]
        states = [np.zeros((sos.shape[0], 2)) for sos in sections]
        blocks = np.random.default_rng(7).standard_normal((3, 1024))

        for block in blocks:
            expected = block
            for index, sos in enumerate(sections):
                expected, states[index] = scipy.signal.sosfilt(sos, expected, zi=states[index])

            with patch("scipy.signal.sosfilt", wraps=scipy.signal.sosfilt) as mock_sosfilt:
                actual = sg._apply_filters(block, params, engine.sample_rate)

            mock_sosfilt.assert_called_once()
            np.testing.assert_array_equal(actual, expected)


class TestSignalGeneratorRealtimeOptimizations(unittest.TestCase):
    class MockAudioEngine:
        def __init__(self):
            self.sample_rate = 48000
            self.callback = None
            self.calibration = MagicMock()
            self.calibration.output_gain = 1.0

        def register_callback(self, callback):
            self.callback = callback
            return 1

        def unregister_callback(self, _callback_id):
            self.callback = None

    def test_buffer_is_reused_when_starting_after_waveform_selection(self):
        engine = self.MockAudioEngine()
        sg = SignalGenerator(engine)
        sg.output_mode = "L"

        with patch.object(sg, "_generate_noise_buffer", wraps=sg._generate_noise_buffer) as generate:
            sg.update_waveform(sg.params_L, "noise", engine.sample_rate)
            selected_buffer = sg.params_L._buffer
            sg.start_generation()

        generate.assert_called_once()
        self.assertIs(sg.params_L._buffer, selected_buffer)

    def test_inactive_buffer_is_prepared_only_when_routing_activates_it(self):
        engine = self.MockAudioEngine()
        sg = SignalGenerator(engine)
        sg.output_mode = "L"
        sg.params_R.waveform = "prbs"
        sg.params_R.prbs_order = 10

        with patch.object(sg, "_generate_prbs", wraps=sg._generate_prbs) as generate:
            sg.start_generation()
            generate.assert_not_called()

            sg.output_mode = "R"
            generate.assert_called_once()

        self.assertIsNotNone(sg.params_R._buffer)

    def test_deterministic_stereo_buffers_share_immutable_samples(self):
        engine = self.MockAudioEngine()
        sg = SignalGenerator(engine)
        for params in (sg.params_L, sg.params_R):
            params.waveform = "prbs"
            params.prbs_order = 10
            params.prbs_seed = 17

        sg.start_generation()

        self.assertIs(sg.params_L._buffer, sg.params_R._buffer)
        self.assertEqual(sg.params_L._buffer_index, 0)
        self.assertEqual(sg.params_R._buffer_index, 0)

    def test_stereo_noise_buffers_remain_independent(self):
        engine = self.MockAudioEngine()
        sg = SignalGenerator(engine)
        sg.params_L.waveform = "noise"
        sg.params_R.waveform = "noise"

        sg.start_generation()

        self.assertIsNot(sg.params_L._buffer, sg.params_R._buffer)
        self.assertFalse(np.array_equal(sg.params_L._buffer, sg.params_R._buffer))

    def test_prbs_seed_does_not_reset_process_random_state(self):
        engine = self.MockAudioEngine()
        sg = SignalGenerator(engine)
        params = SignalParameters(waveform="prbs", prbs_order=10, prbs_seed=17)

        np.random.seed(12345)
        state_before = np.random.get_state()
        sg._generate_prbs(params, engine.sample_rate)
        observed = np.random.random(8)

        np.random.set_state(state_before)
        expected = np.random.random(8)
        np.testing.assert_array_equal(observed, expected)

    def test_short_buffer_read_matches_modular_reference_across_blocks(self):
        engine = self.MockAudioEngine()
        sg = SignalGenerator(engine)
        params = SignalParameters(waveform="golay", amplitude=0.25)
        params._buffer = np.array([1.0, -1.0, 0.5, -0.5])

        expected_index = 0
        for frames in (37, 37, 5):
            indices = (expected_index + np.arange(frames)) % len(params._buffer)
            expected = params._buffer[indices] * params.amplitude
            actual = sg._generate_buffered_signal(params, frames, engine.sample_rate, np.empty(0), engine.sample_rate)
            np.testing.assert_array_equal(actual, expected)
            expected_index = int((expected_index + frames) % len(params._buffer))

        self.assertEqual(params._buffer_index, expected_index)

    def test_direct_periodic_path_matches_general_generator(self):
        engine = self.MockAudioEngine()
        for waveform in SignalGenerator.PERIODIC_WAVEFORMS:
            direct = SignalGenerator(engine)
            reference = SignalGenerator(engine)
            for generator in (direct, reference):
                params = generator.params_L
                params.waveform = waveform
                params.frequency = 1234.5
                params.amplitude = 0.37
                params.phase_offset = 27.0
                params.pulse_width = 31.0
                params.sawtooth_type = "Falling"

            if waveform == "tone_noise":
                np.random.seed(123)
            actual = np.empty(1024)
            t = direct._get_block_time(len(actual), engine.sample_rate)
            direct._generate_channel_into(direct.params_L, len(actual), t, engine.sample_rate, actual)

            if waveform == "tone_noise":
                np.random.seed(123)
            expected = reference._generate_channel_signal(reference.params_L, len(actual), t, engine.sample_rate)

            np.testing.assert_allclose(actual, expected, rtol=0.0, atol=1e-14, err_msg=waveform)


class TestSignalGeneratorOutputTransitions(unittest.TestCase):
    class MockAudioEngine:
        def __init__(self):
            self.sample_rate = 48000
            self.callback = None
            self.calibration = MagicMock()
            self.calibration.output_gain = 1.0

        def register_callback(self, callback):
            self.callback = callback
            return 1

        def unregister_callback(self, _callback_id):
            self.callback = None

    @staticmethod
    def _raised_cosine(samples):
        position = np.arange(samples, dtype=float) / (samples - 1)
        return 0.5 - 0.5 * np.cos(np.pi * position)

    def _generator(self, mode="L"):
        engine = self.MockAudioEngine()
        generator = SignalGenerator(engine)
        generator.output_mode = mode
        generator.transition_ms = 10.0
        for params in (generator.params_L, generator.params_R):
            params.waveform = "pulse"
            params.frequency = 1.0
            params.amplitude = 1.0
            params.pulse_width = 99.9
        return generator, engine

    def test_start_ramp_is_continuous_across_audio_blocks(self):
        generator, engine = self._generator()
        generator.start_generation()

        blocks = []
        for frames in (173, 307):
            outdata = np.zeros((frames, 2))
            engine.callback(None, outdata, frames, None, None)
            blocks.append(outdata[:, 0].copy())

        actual = np.concatenate(blocks)
        expected = self._raised_cosine(480)
        np.testing.assert_allclose(actual, expected, rtol=0.0, atol=1e-12)

    def test_live_amplitude_change_crossfades_without_gain_bump(self):
        generator, engine = self._generator()
        generator.start_generation()
        engine.callback(None, np.zeros((480, 2)), 480, None, None)

        generator.update_param(generator.params_L, "amplitude", 0.25)
        outdata = np.zeros((480, 2))
        engine.callback(None, outdata, 480, None, None)

        new_gain = self._raised_cosine(480)
        expected = 1.0 - 0.75 * new_gain
        np.testing.assert_allclose(outdata[:, 0], expected, rtol=0.0, atol=1e-12)
        self.assertLessEqual(float(np.max(np.abs(outdata[:, 0]))), 1.0)

    def test_rapid_updates_coalesce_to_latest_settings(self):
        generator, engine = self._generator()
        generator.start_generation()
        engine.callback(None, np.zeros((480, 2)), 480, None, None)

        generator.update_param(generator.params_L, "amplitude", 0.8)
        generator.update_param(generator.params_L, "amplitude", 0.2)
        outdata = np.zeros((480, 2))
        engine.callback(None, outdata, 480, None, None)

        state = generator._playback_states["L"]
        self.assertIsNone(state.pending)
        self.assertIsNone(state.next)
        self.assertAlmostEqual(state.current.amplitude, 0.2)
        self.assertAlmostEqual(outdata[-1, 0], 0.2)

    def test_route_change_fades_removed_channel_only(self):
        generator, engine = self._generator(mode="STEREO")
        generator.start_generation()
        engine.callback(None, np.zeros((480, 2)), 480, None, None)

        generator.output_mode = "L"
        outdata = np.zeros((480, 2))
        engine.callback(None, outdata, 480, None, None)

        np.testing.assert_allclose(outdata[:, 0], 1.0, rtol=0.0, atol=1e-12)
        np.testing.assert_allclose(outdata[:, 1], 1.0 - self._raised_cosine(480), rtol=0.0, atol=1e-12)

        outdata.fill(1.0)
        engine.callback(None, outdata, 480, None, None)
        np.testing.assert_array_equal(outdata[:, 1], 0.0)

    def test_requested_stop_fades_before_callback_is_unregistered(self):
        generator, engine = self._generator()
        generator.start_generation()
        engine.callback(None, np.zeros((480, 2)), 480, None, None)

        generator.request_stop_generation()
        self.assertTrue(generator.is_stopping)
        self.assertIsNotNone(engine.callback)

        outdata = np.zeros((480, 2))
        engine.callback(None, outdata, 480, None, None)
        np.testing.assert_allclose(outdata[:, 0], 1.0 - self._raised_cosine(480), rtol=0.0, atol=1e-12)
        self.assertTrue(generator._stop_fade_complete)
        self.assertTrue(generator.complete_stop_if_ready())
        self.assertFalse(generator.is_playing)
        self.assertIsNone(engine.callback)

    def test_zero_transition_time_preserves_sample_exact_output(self):
        generator, engine = self._generator()
        generator.transition_ms = 0.0
        generator.start_generation()

        outdata = np.zeros((128, 2))
        engine.callback(None, outdata, 128, None, None)
        np.testing.assert_array_equal(outdata[:, 0], 1.0)


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
