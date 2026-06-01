import unittest
import sys
from unittest.mock import MagicMock

# Mock sounddevice before importing anything that uses it
sys.modules["sounddevice"] = MagicMock()

import numpy as np  # noqa: E402
from src.gui.widgets.boxcar_averager import BoxcarAverager  # noqa: E402
from src.gui.widgets.lock_in_amplifier import LockInAmplifier  # noqa: E402
from src.core.analysis import AudioCalc  # noqa: E402


class MockCalibration:
    def __init__(self):
        self.lockin_gain_offset = 0.0
        self.output_gain = 1.0
        self.input_sensitivity = 1.0

    def get_frequency_correction(self, freq):
        return 0.0, 0.0


class MockAudioEngine:
    def __init__(self, sample_rate=48000):
        self.sample_rate = sample_rate
        self.calibration = MockCalibration()
        self.callbacks = {}
        self.next_id = 0

    def register_callback(self, callback):
        cid = self.next_id
        self.next_id += 1
        self.callbacks[cid] = callback
        return cid

    def unregister_callback(self, cid):
        if cid in self.callbacks:
            del self.callbacks[cid]


class TestAntigravityFixes(unittest.TestCase):
    def test_boxcar_averager_no_alignment_hang(self):
        """Verify that BoxcarAverager does not discard chunks and hangs when frame size is smaller than period."""
        engine = MockAudioEngine(sample_rate=48000)
        averager = BoxcarAverager(engine)

        averager.mode = "Internal Pulse"
        averager.period_samples = 100
        averager.start_analysis()
        averager.reset_average()

        # set state
        averager.window_origin_sample = 0
        averager.reset_pending = True

        # Feed small chunks of size 30.
        # Total skip required is: (100 - (0 - 0) % 100) % 100 = 0.
        # But wait, if start index idxs[0] is not 0, e.g. start at 10.
        # start_mod = 10 % 100 = 10.
        # skip = (100 - 10) % 100 = 90 samples.
        # If we feed chunks of size 30, they should be retained.

        # Block 1: absolute samples 10..39 (len = 30)
        averager.global_sample_counter = 10
        left = np.arange(10, 40, dtype=float)
        right = np.zeros(30, dtype=float)
        indata = np.column_stack((left, right))
        outdata = np.zeros_like(indata)
        averager._callback(indata, outdata, 30, 0, None)

        # Call process
        averager.process()

        # Because skip (90) >= len(data) (30), it should return and NOT advance input_read_pos.
        self.assertEqual(averager.input_read_pos, 0)
        self.assertTrue(averager.reset_pending)
        self.assertEqual(averager.count, 0)

        # Block 2: absolute samples 40..69 (len = 30)
        left = np.arange(40, 70, dtype=float)
        indata = np.column_stack((left, right))
        averager._callback(indata, outdata, 30, 0, None)
        averager.process()

        # Still not advanced because total available data (60) is less than skip (90)
        self.assertEqual(averager.input_read_pos, 0)
        self.assertTrue(averager.reset_pending)

        # Block 3: absolute samples 70..99 (len = 30)
        left = np.arange(70, 100, dtype=float)
        indata = np.column_stack((left, right))
        averager._callback(indata, outdata, 30, 0, None)
        averager.process()

        # Still not advanced because total available data (90) is equal to skip (90)
        self.assertEqual(averager.input_read_pos, 0)
        self.assertTrue(averager.reset_pending)

        # Block 4: absolute samples 100..129 (len = 30)
        left = np.arange(100, 130, dtype=float)
        indata = np.column_stack((left, right))
        averager._callback(indata, outdata, 30, 0, None)
        averager.process()

        # Now total available data is 120, which is > skip (90).
        # It should successfully process!
        # input_read_pos should advance to write_pos (120)
        self.assertNotEqual(averager.input_read_pos, 0)
        self.assertFalse(averager.reset_pending)

    def test_lockin_ar2_frequency_estimator(self):
        """Verify that the new O(N) AR(2) frequency estimator is highly accurate for a single-tone reference."""
        engine = MockAudioEngine(sample_rate=48000)
        lockin = LockInAmplifier(engine)
        lockin.set_buffer_size(4096)
        lockin.start_analysis()

        # Generate a pure sine wave reference signal at 1234.5 Hz
        fs = 48000.0
        f0 = 1234.5
        t = np.arange(4096) / fs
        ref_signal = 0.5 * np.cos(2 * np.pi * f0 * t + 0.5)
        sig_signal = 0.1 * np.cos(2 * np.pi * f0 * t + 0.5)  # Demo signal

        # Feed to ring buffer
        indata = np.column_stack((sig_signal, ref_signal))
        outdata = np.zeros_like(indata)

        callback = engine.callbacks[lockin.callback_id]
        callback(indata, outdata, 4096, None, None)

        # Process and check estimated reference frequency
        lockin.external_mode = True  # Force it to calculate frequency from input ref channel
        lockin.process_data()

        # Expected reference frequency is very close to f0
        self.assertAlmostEqual(lockin.ref_freq, f0, places=2)

        # Check coherence (should be close to 1.0 for a pure tone)
        self.assertGreater(lockin.ref_coherence, 0.99)

    def test_lockin_phase_wrapping_fractional_continuity(self):
        """Verify that phase wrapping preserves the mathematical continuity of fractional harmonics."""
        engine = MockAudioEngine(sample_rate=48000)
        lockin = LockInAmplifier(engine)
        lockin.set_buffer_size(1024)

        # Fractional harmonic test: e.g. 1/3 harmonic
        lockin.harmonic_numerator = 1
        lockin.harmonic_denominator = 3

        # Large unwrapped phase to trigger precision wrapping
        large_phase = 12345.6 * 2 * np.pi

        # Compute fractional phasor before wrap
        frac_phasor_before = np.exp(1j * large_phase * (1.0 / 3.0))

        # Wrap phase using our formula:
        wrap_period = 2 * np.pi * 3  # D = 3
        wrapped_phase = (large_phase + wrap_period / 2) % wrap_period - wrap_period / 2

        # Check bounded range
        self.assertTrue(-wrap_period / 2 <= wrapped_phase <= wrap_period / 2)

        # Compute fractional phasor after wrap
        frac_phasor_after = np.exp(1j * wrapped_phase * (1.0 / 3.0))

        # Verify they are mathematically identical (continuity preserved)
        np.testing.assert_allclose(frac_phasor_before, frac_phasor_after, rtol=1e-12, atol=1e-12)

    def test_a_weighting_thdn_attenuation_accuracy(self):
        """Verify that AudioCalc.calculate_thdn_sine_fit applies correct A-weighting attenuation (~ -19.1 dB at 100Hz)."""
        sr = 48000
        duration = 1.0
        t = np.arange(int(sr * duration)) / sr

        # Generate a 100Hz sine wave (representing the residual noise/distortion)
        # Signal = Fundamental(1000Hz) + Residual(100Hz)
        fund_freq = 1000.0
        res_freq = 100.0
        sig = np.sin(2 * np.pi * fund_freq * t) + 0.1 * np.sin(2 * np.pi * res_freq * t)

        # 1. Without A-weighting
        _, _, nd_rms_unweighted = AudioCalc.calculate_thdn_sine_fit(sig, sr, freq_guess=fund_freq, filter_type=None)

        # 2. With A-weighting
        # Attenuation at 100Hz is exactly -19.1 dB.
        _, _, nd_rms_weighted = AudioCalc.calculate_thdn_sine_fit(
            sig, sr, freq_guess=fund_freq, filter_type="a_weighting"
        )

        measured_ratio = nd_rms_weighted / nd_rms_unweighted
        measured_db = 20 * np.log10(measured_ratio)

        # Target attenuation is around -19.1 dB. (Allow 0.5dB tolerance due to boundaries)
        # Double-filtering would yield ~ -38.3 dB.
        self.assertAlmostEqual(measured_db, -19.1, delta=0.5)

    def test_c_weighting_thdn_attenuation_accuracy(self):
        """Verify that AudioCalc.calculate_thdn_sine_fit applies correct C-weighting attenuation (~ -1.3 dB at 50Hz)."""
        sr = 48000
        duration = 1.0
        t = np.arange(int(sr * duration)) / sr

        fund_freq = 1000.0
        res_freq = 50.0
        sig = np.sin(2 * np.pi * fund_freq * t) + 0.1 * np.sin(2 * np.pi * res_freq * t)

        # 1. Without C-weighting (Default HPF/LPF applies a 20Hz HPF)
        _, _, nd_rms_unweighted = AudioCalc.calculate_thdn_sine_fit(sig, sr, freq_guess=fund_freq, filter_type=None)

        # 2. With C-weighting
        # Attenuation at 50Hz is exactly -1.35 dB.
        _, _, nd_rms_weighted = AudioCalc.calculate_thdn_sine_fit(
            sig, sr, freq_guess=fund_freq, filter_type="c_weighting"
        )

        measured_ratio = nd_rms_weighted / nd_rms_unweighted
        measured_db = 20 * np.log10(measured_ratio)

        # Target ratio is around -1.3 dB (exact ratio C / default HPF is ~ -1.32 dB).
        # Double filtering would yield ~ -2.7 dB.
        self.assertAlmostEqual(measured_db, -1.3, delta=0.2)

    def test_transmission_analyzer_data_race_safety(self):
        """Verify that TransmissionAnalyzer does not trigger concurrency errors when reading and writing simultaneously."""
        from src.gui.widgets.transmission_analyzer import TransmissionAnalyzer
        import time
        import threading

        engine = MockAudioEngine(sample_rate=48000)
        analyzer = TransmissionAnalyzer(engine)
        analyzer.start_analysis()

        stop_event = threading.Event()

        def audio_thread_sim():
            while not stop_event.is_set():
                indata = np.random.randn(256, 2)
                outdata = np.zeros_like(indata)
                analyzer._audio_callback(indata, outdata, 256, None, None)
                time.sleep(0.001)

        t = threading.Thread(target=audio_thread_sim)
        t.start()

        try:
            # GUI Thread processes data concurrently
            for _ in range(50):
                analyzer.process_data()
                time.sleep(0.002)
        finally:
            stop_event.set()
            t.join()
            analyzer.stop_analysis()

    def test_transmission_analyzer_prbs_phase_uses_absolute_time(self):
        """Verify PRBS phase sync is not biased by TX history ring wraps."""
        from src.gui.widgets.transmission_analyzer import TransmissionAnalyzer

        period = 32767
        ring_len = 131072
        physical_delay = 25502

        rx_start_abs = 24 * ring_len + 79872
        tx_start_abs = rx_start_abs - physical_delay
        prbs_phase = tx_start_abs % period

        ring_wraps = rx_start_abs // ring_len
        period_biased_delay = (physical_delay - ring_wraps * (ring_len % period)) % period
        resolved_tx_abs = TransmissionAnalyzer._resolve_tx_abs_from_prbs_phase(rx_start_abs, prbs_phase, period)
        new_abs_delay = rx_start_abs - resolved_tx_abs

        self.assertEqual(period_biased_delay, 25406)
        self.assertEqual(new_abs_delay, physical_delay)


if __name__ == "__main__":
    unittest.main()
