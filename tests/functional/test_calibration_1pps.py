import unittest
import os
import json
import tempfile
import shutil
from src.core.calibration import CalibrationManager

class TestCalibration1PPS(unittest.TestCase):
    def setUp(self):
        # Create a temporary directory/file for calibration
        self.test_dir = tempfile.mkdtemp()
        self.config_path = os.path.join(self.test_dir, "test_calibration.json")
        self.manager = CalibrationManager(config_path=self.config_path)

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_default_value(self):
        """Test that the default value is 1.0"""
        self.assertEqual(self.manager.frequency_calibration_1pps, 1.0)

    def test_set_and_save(self):
        """Test setting the value and saving it to file."""
        target_factor = 0.999999
        self.manager.set_frequency_calibration_1pps(target_factor)
        
        self.assertEqual(self.manager.frequency_calibration_1pps, target_factor)
        
        # Verify file content
        with open(self.config_path, "r") as f:
            data = json.load(f)
            self.assertEqual(data["frequency_calibration_1pps"], target_factor)

    def test_load(self):
        """Test loading the value from file."""
        target_factor = 1.000005
        
        # Manually write to file
        with open(self.config_path, "w") as f:
            json.dump({"frequency_calibration_1pps": target_factor}, f)
            
        # Create new manager to load
        new_manager = CalibrationManager(config_path=self.config_path)
        self.assertEqual(new_manager.frequency_calibration_1pps, target_factor)

    def test_ppm_calculation_logic(self):
        """Test the logic used in OnePPSMonitor for conversion."""
        # Logic from GUI:
        # new_factor = 1.0 / (1.0 + current_ppm / 1e6)
        
        # Case 1: 0 ppm error -> Factor 1.0
        current_ppm = 0.0
        factor = 1.0 / (1.0 + current_ppm / 1e6)
        self.assertEqual(factor, 1.0)
        
        # Case 2: +10 ppm error (Measured is faster than nominal)
        # We need to slow it down, so factor should be < 1.0
        current_ppm = 10.0
        factor = 1.0 / (1.0 + 10.0 / 1e6)
        self.assertLess(factor, 1.0)
        self.assertAlmostEqual(factor, 0.999990, places=6)
        
        # Reverse Logic (Display):
        # ppm = (1.0 / factor - 1.0) * 1e6
        calculated_ppm = (1.0 / factor - 1.0) * 1e6
        self.assertAlmostEqual(calculated_ppm, 10.0, places=5)
        
        # Case 3: -50 ppm error (Measured is slower)
        # We need to speed it up, factor > 1.0
        current_ppm = -50.0
        factor = 1.0 / (1.0 + (-50.0) / 1e6)
        self.assertGreater(factor, 1.0)
        
        calculated_ppm = (1.0 / factor - 1.0) * 1e6
        self.assertAlmostEqual(calculated_ppm, -50.0, places=5)

if __name__ == '__main__':
    unittest.main()
