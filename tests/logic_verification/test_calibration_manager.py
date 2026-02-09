import sys
import unittest
import tempfile
import os
import json
import math

# Ensure the repository root is importable
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

# --- Mock Numpy ---
class MockArray:
    def __init__(self, data):
        self.data = data

    def __getitem__(self, key):
        # Support basic slicing [:, 0]
        if isinstance(key, tuple) and len(key) == 2:
            row_slice, col_idx = key
            if row_slice == slice(None) and isinstance(col_idx, int):
                return [row[col_idx] for row in self.data]
        return self.data[key]

class MockNumpy:
    def isfinite(self, x):
        return math.isfinite(x)

    def log10(self, x):
        return math.log10(x)

    def interp(self, x, xp, fp):
        # Basic linear interpolation
        # Check for empty xp
        if len(xp) == 0:
            return 0.0

        if x <= xp[0]:
            return fp[0]
        if x >= xp[-1]:
            return fp[-1]

        for i in range(len(xp) - 1):
            if xp[i] <= x <= xp[i+1]:
                # Avoid division by zero
                if xp[i+1] == xp[i]:
                    return fp[i]
                t = (x - xp[i]) / (xp[i+1] - xp[i])
                return fp[i] + t * (fp[i+1] - fp[i])
        return 0.0

    def array(self, data):
        return MockArray(data)

# Apply patch before importing CalibrationManager
# We only patch if numpy is not already available or if we want to force mock
if "numpy" not in sys.modules:
    sys.modules["numpy"] = MockNumpy()

from src.core.calibration import CalibrationManager # noqa: E402

class TestCalibrationManager(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_path = os.path.join(self.temp_dir.name, "calibration.json")
        self.cm = CalibrationManager(config_path=self.config_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_initialization(self):
        self.assertEqual(self.cm.input_sensitivity, 1.0)
        self.assertEqual(self.cm.output_gain, 1.0)
        self.assertFalse(self.cm.output_gain_is_calibrated)
        self.assertEqual(self.cm.frequency_calibration, 1.0)
        self.assertIsNone(self.cm.spl_offset_db)

    def test_save_load(self):
        self.cm.input_sensitivity = 2.0
        self.cm.output_gain = 0.5
        self.cm.output_gain_is_calibrated = True
        self.cm.save()

        # Load in a new instance
        new_cm = CalibrationManager(config_path=self.config_path)
        self.assertEqual(new_cm.input_sensitivity, 2.0)
        self.assertEqual(new_cm.output_gain, 0.5)
        self.assertTrue(new_cm.output_gain_is_calibrated)

    def test_spl_calibration(self):
        # SPL = dBFS + offset
        # measured_dbfs = -20, measured_spl = 80
        # offset = 80 - (-20) = 100
        self.cm.set_spl_calibration(-20, 80)
        self.assertEqual(self.cm.spl_offset_db, 100.0)

        spl = self.cm.dbfs_to_spl(-10)
        # -10 + 100 = 90
        self.assertEqual(spl, 90.0)

        # Test None if not calibrated
        self.cm.spl_offset_db = None
        self.assertIsNone(self.cm.dbfs_to_spl(-10))

    def test_conversions(self):
        self.cm.input_sensitivity = 1.0
        # 0 dBFS -> 0 dBV (since sens=1.0V)
        self.assertAlmostEqual(self.cm.dbfs_to_dbv(0), 0.0)
        # 0 dBFS -> 1.0 V
        self.assertAlmostEqual(self.cm.dbfs_to_volts(0), 1.0)

        self.cm.input_sensitivity = 2.0
        # 0 dBFS -> 2.0 V -> 20*log10(2) ~= 6.02 dBV
        self.assertAlmostEqual(self.cm.dbfs_to_dbv(0), 20 * math.log10(2.0))
        self.assertAlmostEqual(self.cm.dbfs_to_volts(0), 2.0)

    def test_setters_validation(self):
        with self.assertRaises(ValueError):
            self.cm.set_output_gain(-1.0)
        with self.assertRaises(ValueError):
            self.cm.set_output_gain(0.0)

        self.cm.set_output_gain(1.5)
        self.assertEqual(self.cm.output_gain, 1.5)
        self.assertTrue(self.cm.output_gain_is_calibrated)

    def test_profile_management(self):
        self.cm.save_profile("profile1", "Device A")
        self.cm.input_sensitivity = 5.0
        self.cm.save_profile("profile2", "Device B")

        self.assertEqual(len(self.cm.get_profiles()), 2)

        self.cm.load_profile("profile1")
        self.assertEqual(self.cm.input_sensitivity, 1.0)

        self.cm.load_profile("profile2")
        self.assertEqual(self.cm.input_sensitivity, 5.0)

        self.cm.delete_profile("profile1")
        self.assertNotIn("profile1", self.cm.get_profiles())

    def test_frequency_map(self):
        # Create a dummy frequency map file
        map_path = os.path.join(self.temp_dir.name, "freq_map.json")
        data = [[100, -1.0, 0], [1000, 0.0, 0], [10000, 1.0, 0]]
        with open(map_path, "w") as f:
            json.dump(data, f)

        # Should load successfully
        self.assertTrue(self.cm.load_frequency_map(map_path))

        # Test interpolation
        mag, phase = self.cm.get_frequency_correction(100)
        self.assertEqual(mag, -1.0)

        mag, phase = self.cm.get_frequency_correction(550)
        # Midpoint between 100 (-1) and 1000 (0) -> -0.5
        self.assertAlmostEqual(mag, -0.5)

        # Security check: Outside directory
        outside_path = os.path.abspath(os.path.join(self.temp_dir.name, "..", "outside.json"))
        # Ensure outside_path is actually outside
        if os.path.commonpath([self.temp_dir.name, outside_path]) != self.temp_dir.name:
             self.assertFalse(self.cm._is_path_allowed(outside_path))

if __name__ == '__main__':
    unittest.main()
