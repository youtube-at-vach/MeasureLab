import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../')))
import os
import json
import unittest
import tempfile
from unittest.mock import MagicMock
import sys

try:
    from src.core.calibration import CalibrationManager
except ImportError:
    # Fallback if other dependencies (e.g. logging?) fail, though unlikely for core
    pass

class TestCalibrationProfiles(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.TemporaryDirectory()
        self.config_path = os.path.join(self.test_dir.name, "test_cal.json")

    def tearDown(self):
        self.test_dir.cleanup()

    def test_save_load_profile(self):
        cm = CalibrationManager(self.config_path)

        # Set some values
        cm.input_sensitivity = 0.5
        cm.output_gain = 2.0
        cm.save_profile("Test Profile", "Test Device")

        # Check file content
        with open(self.config_path, 'r') as f:
            data = json.load(f)
            self.assertIn('profiles', data)
            self.assertIn('Test Profile', data['profiles'])
            self.assertEqual(data['profiles']['Test Profile']['device_name'], "Test Device")
            self.assertEqual(data['profiles']['Test Profile']['input_sensitivity'], 0.5)

        # Modify current values
        cm.input_sensitivity = 1.0
        cm.output_gain = 1.0

        # Load profile
        cm.load_profile("Test Profile")

        # Verify values restored
        self.assertEqual(cm.input_sensitivity, 0.5)
        self.assertEqual(cm.output_gain, 2.0)

    def test_delete_profile(self):
        cm = CalibrationManager(self.config_path)
        cm.save_profile("Delete Me", "Dev")

        self.assertIn("Delete Me", cm.get_profiles())

        cm.delete_profile("Delete Me")

        self.assertNotIn("Delete Me", cm.get_profiles())

        with open(self.config_path, 'r') as f:
            data = json.load(f)
            self.assertNotIn("Delete Me", data['profiles'])

if __name__ == '__main__':
    unittest.main()
