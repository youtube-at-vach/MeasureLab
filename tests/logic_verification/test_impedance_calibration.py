import unittest
from unittest.mock import MagicMock
import sys

# Mock dependencies BEFORE importing the module under test
# This is crucial because the module imports PyQt6 at the top level
sys.modules['PyQt6'] = MagicMock()
sys.modules['PyQt6.QtCore'] = MagicMock()
sys.modules['PyQt6.QtGui'] = MagicMock()
sys.modules['PyQt6.QtWidgets'] = MagicMock()
sys.modules['pyqtgraph'] = MagicMock()
sys.modules['sounddevice'] = MagicMock()

# Mock localization
mock_localization = MagicMock()
mock_localization.tr = lambda x, default=None: x
sys.modules['src.core.localization'] = mock_localization

# Now import the class to test
# We use a try-except block to gracefully handle potential import errors
# although mocking should prevent them.
try:
    from src.gui.widgets.impedance_analyzer import ImpedanceAnalyzer
except ImportError:
    ImpedanceAnalyzer = None

class TestImpedanceCalibration(unittest.TestCase):
    def setUp(self):
        if ImpedanceAnalyzer is None:
            self.skipTest("ImpedanceAnalyzer could not be imported")

        self.mock_audio_engine = MagicMock()
        self.mock_audio_engine.sample_rate = 48000

        # Instantiate the analyzer
        # We need to ensure the constructor doesn't crash due to mocks
        self.analyzer = ImpedanceAnalyzer(self.mock_audio_engine)

        # Reset calibration state
        self.analyzer.cal_open = {}
        self.analyzer.cal_short = {}
        self.analyzer.cal_load = {}
        self.analyzer.use_calibration = True
        self.analyzer.load_standard_real = 100.0

    def test_get_interpolated_cal_value(self):
        """Test interpolation logic with known points."""
        cal_dict = {
            100.0: 10 + 10j,
            200.0: 20 + 20j,
            300.0: 30 + 30j
        }

        # Exact match
        val = self.analyzer._get_interpolated_cal_value(cal_dict, 100.0)
        self.assertEqual(val, 10 + 10j)

        val = self.analyzer._get_interpolated_cal_value(cal_dict, 200.0)
        self.assertEqual(val, 20 + 20j)

        # Mid-point (Linear Interpolation)
        # At 150.0 (midway between 100 and 200), expected 15+15j
        val = self.analyzer._get_interpolated_cal_value(cal_dict, 150.0)
        self.assertAlmostEqual(val.real, 15.0)
        self.assertAlmostEqual(val.imag, 15.0)

        # 25% point
        # At 125.0 (25% from 100 to 200), expected 12.5+12.5j
        val = self.analyzer._get_interpolated_cal_value(cal_dict, 125.0)
        self.assertAlmostEqual(val.real, 12.5)
        self.assertAlmostEqual(val.imag, 12.5)

        # Out of bounds (Clamping)
        # Below min -> clamp to min
        val = self.analyzer._get_interpolated_cal_value(cal_dict, 50.0)
        self.assertEqual(val, 10 + 10j)

        # Above max -> clamp to max
        val = self.analyzer._get_interpolated_cal_value(cal_dict, 400.0)
        self.assertEqual(val, 30 + 30j)

    def test_apply_calibration_no_cal(self):
        """Verify returns raw measurement when calibration is disabled or empty."""
        self.analyzer.use_calibration = False
        z_meas = 50 + 50j
        freq = 1000.0

        result = self.analyzer.apply_calibration(z_meas, freq)
        self.assertEqual(result, z_meas)

        # Enable calibration but empty dicts
        self.analyzer.use_calibration = True
        self.analyzer.cal_open = {}
        self.analyzer.cal_short = {}

        result = self.analyzer.apply_calibration(z_meas, freq)
        self.assertEqual(result, z_meas)

    def test_apply_calibration_os(self):
        """Verify Open/Short (OS) calibration logic."""
        # Setup Calibration Points
        freq = 1000.0
        z_open = 1000 + 0j
        z_short = 1 + 0j

        self.analyzer.cal_open = {freq: z_open}
        self.analyzer.cal_short = {freq: z_short}
        self.analyzer.cal_load = {} # Ensure no load cal

        z_meas = 100 + 0j

        # Theoretical Calculation
        # Y_open = 1 / 1000 = 0.001
        # Num = 100 - 1 = 99
        # Denom = 1 - (99 * 0.001) = 1 - 0.099 = 0.901
        # Expected = 99 / 0.901 = 109.8779134

        expected = (z_meas - z_short) / (1 - (z_meas - z_short) / z_open)

        result = self.analyzer.apply_calibration(z_meas, freq)

        self.assertAlmostEqual(result.real, expected.real, places=5)
        self.assertAlmostEqual(result.imag, expected.imag, places=5)

    def test_apply_calibration_osl(self):
        """Verify Open/Short/Load (OSL) calibration logic."""
        freq = 1000.0
        z_std = 100.0
        self.analyzer.load_standard_real = z_std

        z_open = 1000 + 0j
        z_short = 10 + 0j
        z_load = 100 + 0j

        self.analyzer.cal_open = {freq: z_open}
        self.analyzer.cal_short = {freq: z_short}
        self.analyzer.cal_load = {freq: z_load}

        z_meas = 200 + 0j

        # Theoretical Calculation
        # Term1 = 1000 - 100 = 900
        # Term2 = 200 - 10 = 190
        # Num = 100 * 900 * 190 = 17,100,000

        # Denom1 = 1000 - 200 = 800
        # Denom2 = 100 - 10 = 90
        # Denom = 800 * 90 = 72,000

        # Expected = 17,100,000 / 72,000 = 237.5

        result = self.analyzer.apply_calibration(z_meas, freq)

        self.assertAlmostEqual(result.real, 237.5, places=5)
        self.assertAlmostEqual(result.imag, 0.0, places=5)

    def test_apply_calibration_edge_cases(self):
        """Test edge cases like division by zero."""
        freq = 1000.0
        z_open = 1000 + 0j
        z_short = 1 + 0j

        self.analyzer.cal_open = {freq: z_open}
        self.analyzer.cal_short = {freq: z_short}

        # Case 1: Denominator near zero in OS cal
        # Denom = 1 - (Z_meas - Z_short) * Y_open
        # If (Z_meas - Z_short) * Y_open = 1, then Denom = 0
        # (Z_meas - 1) * 0.001 = 1 => Z_meas - 1 = 1000 => Z_meas = 1001

        z_meas_fail = 1001 + 0j
        result = self.analyzer.apply_calibration(z_meas_fail, freq)

        # Expect raw measurement return (fallback)
        self.assertEqual(result, z_meas_fail)

        # Case 2: Zero Open impedance (should avoid 1/0)
        self.analyzer.cal_open = {freq: 0j}
        z_meas = 100 + 0j
        result = self.analyzer.apply_calibration(z_meas, freq)
        self.assertEqual(result, z_meas)

if __name__ == '__main__':
    unittest.main()
