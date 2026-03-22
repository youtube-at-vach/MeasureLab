import sys
import unittest
from unittest.mock import MagicMock, patch
import numpy as np
import scipy.signal

# Mock modules that are imported by src.core.analysis
mock_modules = {
    "soundfile": MagicMock(),
    "src.core.fft_manager": MagicMock(),
}

# Apply mocks
with patch.dict(sys.modules, mock_modules):
    from src.core.analysis import AudioCalc


class TestWeightingDesign(unittest.TestCase):
    def test_design_c_weighting_validity(self):
        """Test that the function returns valid SOS coefficients."""
        sr = 48000
        sos = AudioCalc.design_c_weighting(sr)

        self.assertIsInstance(sos, np.ndarray)
        self.assertEqual(sos.ndim, 2)
        self.assertEqual(sos.shape[1], 6)
        self.assertEqual(sos.dtype, np.float64)

    def test_design_c_weighting_frequency_response(self):
        """Verify the C-weighting frequency response at key frequencies (IEC 61672).

        We use 192kHz sample rate to minimize bilinear transform warping effects
        at high frequencies (20kHz), allowing us to verify the filter design
        parameters (poles/zeros) against the analog standard.
        """
        sr = 192000
        sos = AudioCalc.design_c_weighting(sr)

        # Test frequencies: 20Hz, 1kHz, 20kHz
        test_freqs = [20.0, 1000.0, 20000.0]

        # Calculate frequency response
        w, h = scipy.signal.sosfreqz(sos, worN=test_freqs, fs=sr)
        gain_db = 20 * np.log10(np.abs(h) + 1e-12)

        # 1. Gain at 1 kHz must be exactly 0 dB
        gain_1k = gain_db[1]
        self.assertAlmostEqual(gain_1k, 0.0, places=1, msg=f"Gain at 1kHz ({gain_1k:.2f} dB) should be approx 0 dB")

        # 2. Gain at 20 Hz (approx -6.2 dB)
        gain_20 = gain_db[0]
        self.assertAlmostEqual(
            gain_20, -6.2, delta=0.5, msg=f"Gain at 20Hz ({gain_20:.2f} dB) should be approx -6.2 dB"
        )

        # 3. Gain at 20 kHz (approx -11.2 dB)
        # At 192k, warping is minimal.
        gain_20k = gain_db[2]
        self.assertAlmostEqual(
            gain_20k, -11.2, delta=0.5, msg=f"Gain at 20kHz ({gain_20k:.2f} dB) should be approx -11.2 dB"
        )

    def test_design_a_weighting_validity(self):
        """Test that A-weighting design returns valid SOS."""
        sr = 48000
        sos = AudioCalc.design_a_weighting(sr)
        self.assertIsInstance(sos, np.ndarray)
        self.assertEqual(sos.ndim, 2)
        self.assertEqual(sos.shape[1], 6)

    def test_design_a_weighting_frequency_response(self):
        """Verify A-weighting frequency response at key frequencies.
        Using 192kHz to minimize warping.
        """
        sr = 192000
        sos = AudioCalc.design_a_weighting(sr)

        test_freqs = [20.0, 1000.0, 20000.0]

        w, h = scipy.signal.sosfreqz(sos, worN=test_freqs, fs=sr)
        gain_db = 20 * np.log10(np.abs(h) + 1e-12)

        # 1kHz
        gain_1k = gain_db[1]
        self.assertAlmostEqual(gain_1k, 0.0, places=1, msg="A-weighting 1kHz should be 0dB")

        # 20Hz
        gain_20 = gain_db[0]
        self.assertAlmostEqual(gain_20, -50.5, delta=1.0, msg="A-weighting 20Hz should be approx -50.5dB")

        # 20kHz
        gain_20k = gain_db[2]
        self.assertAlmostEqual(gain_20k, -9.3, delta=1.0, msg="A-weighting 20kHz should be approx -9.3dB")

    def test_design_invalid_sr(self):
        """Test invalid sample rates raise ValueError."""
        with self.assertRaises(ValueError):
            AudioCalc.design_c_weighting(0)
        with self.assertRaises(ValueError):
            AudioCalc.design_a_weighting(-100)


if __name__ == "__main__":
    unittest.main()
