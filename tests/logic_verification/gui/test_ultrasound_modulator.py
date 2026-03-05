import unittest
from unittest.mock import MagicMock, patch
import numpy as np
import sys
import os

# Add src to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from PyQt6.QtWidgets import QApplication
from src.gui.widgets.ultrasound_modulator import UltrasoundModulator, UltrasoundModulatorWidget
import src.gui.widgets.ultrasound_modulator as um_module

class MockAudioEngine:
    def __init__(self):
        self.sample_rate = 48000
    def register_callback(self, cb):
        return 1
    def unregister_callback(self, id):
        pass

class TestUltrasoundModulator(unittest.TestCase):
    def setUp(self):
        self.mock_audio_engine = MagicMock()
        self.modulator = UltrasoundModulator(self.mock_audio_engine)

    def test_update_filter_remez_success(self):
        # Test that coefficients are generated when remez succeeds
        with patch('src.gui.widgets.ultrasound_modulator.remez') as mock_remez:
            mock_remez.return_value = np.ones(65)
            self.modulator._update_filter(48000)
            self.assertTrue(np.array_equal(self.modulator._hilbert_coeffs, np.ones(65)))
            mock_remez.assert_called()

    def test_update_filter_remez_failure_fallback(self):
        # Test fallback when remez fails
        with patch('src.gui.widgets.ultrasound_modulator.remez') as mock_remez:
            mock_remez.side_effect = ValueError("Convergence failed")

            with self.assertLogs('src.gui.widgets.ultrasound_modulator', level='WARNING') as cm:
                self.modulator._update_filter(48000)

            self.assertTrue(any("Error designing Hilbert filter" in output for output in cm.output))
            self.assertIsNotNone(self.modulator._hilbert_coeffs)
            self.assertEqual(len(self.modulator._hilbert_coeffs), 65)

    def test_update_filter_remez_failure_fallback_coeffs(self):
         with patch('src.gui.widgets.ultrasound_modulator.remez') as mock_remez:
            mock_remez.side_effect = ValueError("Convergence failed")
            self.modulator._update_filter(48000)

            # Verify it uses the fallback coefficients
            fallback = getattr(um_module, '_FALLBACK_HILBERT_COEFFS', None)
            if fallback is not None:
                self.assertTrue(np.array_equal(self.modulator._hilbert_coeffs, np.array(fallback)))
            else:
                # If we can't access the constant, at least check it's not zeros
                self.assertFalse(np.all(self.modulator._hilbert_coeffs == 0), "Fallback coefficients should not be all zeros")

class TestUltrasoundSSB(unittest.TestCase):
    def setUp(self):
        self.engine = MockAudioEngine()
        self.mod = UltrasoundModulator(self.engine)

    def test_ssb_suppression(self):
        # Configure for SSB USB
        self.mod.carrier_freq = 10000.0
        self.mod.modulation_mode = "USB"
        self.mod.input_mode = "L"
        self.mod.output_mode = "L"
        self.mod.input_gain = 1.0
        self.mod.output_gain = 1.0
        self.mod.bypass = False

        # Capture the callback
        callback_fn = None
        def register(cb):
            nonlocal callback_fn
            callback_fn = cb
            return 123

        self.engine.register_callback = register
        self.mod.start()

        self.assertIsNotNone(callback_fn)

        fs = 48000
        duration = 0.5 # seconds
        frames = int(fs * duration)

        # Input signal: 1kHz sine wave
        t = np.arange(frames) / fs
        input_sig = np.cos(2 * np.pi * 1000 * t)

        # Process in chunks
        chunk_size = 1024
        output_sig = []

        cursor = 0
        while cursor < frames:
            n = min(chunk_size, frames - cursor)
            indata = np.zeros((n, 2), dtype=np.float32)
            indata[:, 0] = input_sig[cursor:cursor+n]

            outdata = np.zeros((n, 2), dtype=np.float32)

            callback_fn(indata, outdata, n, None, None)

            output_sig.append(outdata[:, 0].copy())
            cursor += n

        output_sig = np.concatenate(output_sig)

        # Analyze Spectrum
        # Skip beginning to avoid filter transient
        skip = fs//4
        stable_output = output_sig[skip:]

        # FFT
        fft_out = np.abs(np.fft.rfft(stable_output))
        freqs = np.fft.rfftfreq(len(stable_output), d=1/fs)

        # Expected: Peak at Carrier + Signal = 10k + 1k = 11kHz.
        # Suppressed: Carrier - Signal = 9kHz.
        # Also Carrier might be present if we added it.

        target_idx = np.argmin(np.abs(freqs - 11000))
        image_idx = np.argmin(np.abs(freqs - 9000))
        # Carrier frequency index is calculated but unused variable 'carrier_amp' removed to fix lint error
        # carrier_idx = np.argmin(np.abs(freqs - 10000))

        target_amp = fft_out[target_idx]
        image_amp = fft_out[image_idx]
        # carrier_amp = fft_out[carrier_idx]

        # Check suppression
        # We expect Target >> Image
        # If image_amp is very small, ratio is huge.
        suppression_ratio = target_amp / (image_amp + 1e-9)

        # Note: 65 taps might not give huge suppression, but should be significant.
        # 20dB = ratio 10.
        self.assertGreater(suppression_ratio, 5.0, "Sideband should be suppressed")

class TestUltrasoundModulatorLogic(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not QApplication.instance():
            cls.app = QApplication(sys.argv + ['-platform', 'offscreen'])
        else:
            cls.app = QApplication.instance()

    def _create_mock_module(self):
        engine = MockAudioEngine()
        mod = UltrasoundModulator(engine)
        mod.carrier_freq = 40000.0
        mod.input_gain = 1.0
        mod.output_gain = 1.0
        mod.lpf_cutoff = 8000.0
        mod.modulation_depth = 1.0
        mod.modulation_mode = "DSB"
        mod.input_mode = "L"
        mod.output_mode = "R"
        mod.enable_predistortion = False
        mod.bypass = False
        mod.is_running = False
        mod.input_level = 0.0
        mod.output_level = 0.0
        return mod

    def test_freq_to_slider_robustness(self):
        """Test conversion of frequency to slider position handles edge cases."""
        mod = self._create_mock_module()
        widget = UltrasoundModulatorWidget(mod)

        # 1. Test Valid Frequency
        val_valid = widget._freq_to_slider(40000.0, 2000.0, 96000.0)
        self.assertTrue(0 <= val_valid <= 1000, f"Valid value out of range: {val_valid}")

        # 2. Test Zero Frequency (The Bug)
        try:
            val_zero = widget._freq_to_slider(0.0, 2000.0, 96000.0)
            # If fixed, it should return 0 (clamped to min)
            self.assertEqual(val_zero, 0, "Zero frequency should map to slider 0")
        except (ValueError, OverflowError, RuntimeWarning) as e:
            self.fail(f"Zero frequency caused crash: {e}")

        # 3. Test Negative Frequency
        try:
            val_neg = widget._freq_to_slider(-100.0, 2000.0, 96000.0)
            self.assertEqual(val_neg, 0, "Negative frequency should map to slider 0")
        except (ValueError, OverflowError) as e:
             self.fail(f"Negative frequency caused crash: {e}")

    def test_slider_to_freq_robustness(self):
        """Test conversion of slider position to frequency handles edge cases."""
        mod = self._create_mock_module()
        widget = UltrasoundModulatorWidget(mod)

        # 1. Valid
        f = widget._slider_to_freq(500, 100.0, 10000.0) # Mid point log scale
        # log(100)=2, log(10000)=4. Mid=3 -> 1000Hz.
        self.assertAlmostEqual(f, 1000.0, delta=1.0)

        # 2. Invalid Min Freq (<= 0)
        # Should be clamped internally to small positive
        try:
            f = widget._slider_to_freq(0, 0.0, 10000.0)
            self.assertTrue(f > 0, "Frequency must be positive")
        except (ValueError, OverflowError, RuntimeWarning) as e:
            self.fail(f"Zero min_f caused crash: {e}")

if __name__ == "__main__":
    unittest.main()
