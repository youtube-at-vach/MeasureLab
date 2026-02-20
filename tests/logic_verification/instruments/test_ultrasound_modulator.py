import unittest
from unittest.mock import MagicMock, patch
import numpy as np

# Import the module under test
from src.gui.widgets.ultrasound_modulator import UltrasoundModulator

# We can't easily import the constant from the test if it's not exposed,
# but we can inspect the module.
import src.gui.widgets.ultrasound_modulator as um_module

class TestUltrasoundModulator(unittest.TestCase):
    def setUp(self):
        self.mock_audio_engine = MagicMock()
        self.modulator = UltrasoundModulator(self.mock_audio_engine)

    def test_update_filter_remez_success(self):
        # Test that coefficients are generated when remez succeeds
        with patch('scipy.signal.remez') as mock_remez:
            mock_remez.return_value = np.ones(65)
            self.modulator._update_filter(48000)
            self.assertTrue(np.array_equal(self.modulator._hilbert_coeffs, np.ones(65)))
            mock_remez.assert_called()

    def test_update_filter_remez_failure_fallback(self):
        # Test fallback when remez fails
        with patch('scipy.signal.remez') as mock_remez:
            mock_remez.side_effect = ValueError("Convergence failed")

            with self.assertLogs('src.gui.widgets.ultrasound_modulator', level='WARNING') as cm:
                self.modulator._update_filter(48000)

            self.assertTrue(any("Error designing Hilbert filter" in output for output in cm.output))
            self.assertIsNotNone(self.modulator._hilbert_coeffs)
            self.assertEqual(len(self.modulator._hilbert_coeffs), 65)

    def test_update_filter_remez_failure_fallback_coeffs(self):
         with patch('scipy.signal.remez') as mock_remez:
            mock_remez.side_effect = ValueError("Convergence failed")
            self.modulator._update_filter(48000)

            # Verify it uses the fallback coefficients
            fallback = getattr(um_module, '_FALLBACK_HILBERT_COEFFS', None)
            if fallback is not None:
                self.assertTrue(np.array_equal(self.modulator._hilbert_coeffs, np.array(fallback)))
            else:
                # If we can't access the constant, at least check it's not zeros
                self.assertFalse(np.all(self.modulator._hilbert_coeffs == 0), "Fallback coefficients should not be all zeros")
