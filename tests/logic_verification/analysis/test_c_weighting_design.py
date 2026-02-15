import sys
import unittest
from unittest.mock import MagicMock, patch
import numpy as np
import scipy.signal

# Mock modules that are imported by src.gui.widgets.settings but not needed for _design_c_weighting
# We must do this BEFORE importing the function under test
mock_modules = {
    "PyQt6": MagicMock(),
    "PyQt6.QtCore": MagicMock(),
    "PyQt6.QtWidgets": MagicMock(),
    "src.core.audio_engine": MagicMock(),
    "src.core.config_manager": MagicMock(),
    "src.core.localization": MagicMock(),
    "src.core.fft_manager": MagicMock(),
    "sounddevice": MagicMock(),
    "pyqtgraph": MagicMock(),
    "pyqtgraph.Qt": MagicMock(),
}

# Apply mocks
with patch.dict(sys.modules, mock_modules):
    # Import the function to test
    from src.gui.widgets.settings import _design_c_weighting

class TestCWeightingDesign(unittest.TestCase):
    def test_design_c_weighting_validity(self):
        """Test that the function returns valid filter coefficients."""
        sr = 48000
        b, a = _design_c_weighting(sr)

        self.assertIsInstance(b, np.ndarray)
        self.assertIsInstance(a, np.ndarray)
        self.assertEqual(b.ndim, 1)
        self.assertEqual(a.ndim, 1)
        # Verify it's not empty
        self.assertGreater(len(b), 0)
        self.assertGreater(len(a), 0)
        # Verify dtype
        self.assertEqual(b.dtype, np.float64)
        self.assertEqual(a.dtype, np.float64)

    def test_design_c_weighting_frequency_response(self):
        """Verify the frequency response at key frequencies (IEC 61672 C-weighting).

        We use a high sample rate (192 kHz) for this test to minimize frequency warping
        effects of the bilinear transform near Nyquist, allowing us to verify that the
        analog prototype parameters (poles/zeros) are correct.
        At 48 kHz, the gain at 20 kHz deviates significantly due to warping (-27 dB vs -11.2 dB).
        """
        sr = 192000
        b, a = _design_c_weighting(sr)

        # Test frequencies
        test_freqs = [10.0, 20.0, 1000.0, 20000.0]

        # Calculate frequency response at specific points
        w, h = scipy.signal.freqz(b, a, worN=test_freqs, fs=sr)
        gain_db = 20 * np.log10(np.abs(h) + 1e-12)

        # 1. Gain at 1 kHz must be exactly 0 dB (normalization point)
        # 1000.0 is at index 2
        gain_1k = gain_db[2]
        self.assertAlmostEqual(gain_1k, 0.0, places=1, msg=f"Gain at 1kHz ({gain_1k:.2f} dB) should be approx 0 dB")

        # 2. Gain at 20 Hz (approx -6.2 dB)
        # 20.0 is at index 1
        gain_20 = gain_db[1]
        self.assertAlmostEqual(gain_20, -6.2, delta=0.5, msg=f"Gain at 20Hz ({gain_20:.2f} dB) should be approx -6.2 dB")

        # 3. Gain at 20 kHz (approx -11.2 dB)
        # 20000.0 is at index 3
        gain_20k = gain_db[3]
        # Using delta=1.0 because discretization error still exists.
        # Ideally it's around -11.75 dB vs -11.2 nominal.
        self.assertAlmostEqual(gain_20k, -11.2, delta=1.0, msg=f"Gain at 20kHz ({gain_20k:.2f} dB) should be approx -11.2 dB")

        # 4. Check rolloff behavior (low frequency should be dropping)
        # 10.0 is at index 0
        gain_10 = gain_db[0]
        self.assertLess(gain_10, gain_20, msg="Gain at 10Hz should be lower than at 20Hz")

    def test_design_c_weighting_invalid_sr(self):
        """Test invalid sample rates raise ValueError."""
        with self.assertRaises(ValueError):
            _design_c_weighting(0)
        with self.assertRaises(ValueError):
            _design_c_weighting(-48000)

if __name__ == "__main__":
    unittest.main()
