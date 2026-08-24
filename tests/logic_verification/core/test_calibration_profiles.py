import os
import json
import unittest
import tempfile

import pytest

from src.core.calibration import CalibrationManager


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
        with open(self.config_path, "r") as f:
            data = json.load(f)
            self.assertIn("profiles", data)
            self.assertIn("Test Profile", data["profiles"])
            self.assertEqual(data["profiles"]["Test Profile"]["device_name"], "Test Device")
            self.assertEqual(data["profiles"]["Test Profile"]["input_sensitivity"], 0.5)

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

        with open(self.config_path, "r") as f:
            data = json.load(f)
            self.assertNotIn("Delete Me", data["profiles"])


def test_create_profile_uses_safe_defaults_and_both_devices(tmp_path):
    manager = CalibrationManager(str(tmp_path / "calibration.json"))
    manager.input_sensitivity = 2.5
    manager.input_sensitivity_is_calibrated = True
    manager.output_gain = 3.5
    manager.output_gain_is_calibrated = True
    manager.spl_offset_db = 96.0

    manager.create_profile(
        "Interface A",
        "Input A",
        "CoreAudio",
        "Output A",
        "CoreAudio",
    )

    profile = manager.get_profiles()["Interface A"]
    assert manager.last_profile == "Interface A"
    assert manager.input_sensitivity == 1.0
    assert manager.input_sensitivity_is_calibrated is False
    assert manager.output_gain == 1.0
    assert manager.output_gain_is_calibrated is False
    assert manager.spl_offset_db is None
    assert profile["input_device_name"] == "Input A"
    assert profile["output_device_name"] == "Output A"
    assert profile["device_name"] == "Input A"


def test_duplicate_profile_copies_current_values_and_activates(tmp_path):
    manager = CalibrationManager(str(tmp_path / "calibration.json"))
    manager.input_sensitivity = 2.0
    manager.input_sensitivity_is_calibrated = True
    manager.output_gain = 4.0
    manager.output_gain_is_calibrated = True
    manager.frequency_calibration_source = "1pps"

    manager.duplicate_profile("Copy", "Input", "ALSA", "Output", "ALSA")

    profile = manager.get_profiles()["Copy"]
    assert manager.last_profile == "Copy"
    assert profile["input_sensitivity"] == 2.0
    assert profile["input_sensitivity_is_calibrated"] is True
    assert profile["output_gain"] == 4.0
    assert profile["frequency_calibration_source"] == "1pps"


def test_rename_active_profile_preserves_values_and_metadata(tmp_path):
    manager = CalibrationManager(str(tmp_path / "calibration.json"))
    manager.duplicate_profile("Before", "Input", "ALSA", "Output", "ALSA")
    original = dict(manager.get_profiles()["Before"])

    manager.rename_profile("Before", "After")

    assert manager.last_profile == "After"
    assert "Before" not in manager.get_profiles()
    assert manager.get_profiles()["After"] == original


def test_delete_active_profile_keeps_current_values_without_named_profile(tmp_path):
    path = tmp_path / "calibration.json"
    manager = CalibrationManager(str(path))
    manager.input_sensitivity = 2.0
    manager.input_sensitivity_is_calibrated = True
    manager.duplicate_profile("Active", "Input")

    manager.delete_profile("Active")

    assert manager.last_profile is None
    assert manager.input_sensitivity == 2.0
    assert manager.input_sensitivity_is_calibrated is True
    assert manager.get_profiles() == {}

    restored = CalibrationManager(str(path))
    assert restored.last_profile is None
    assert restored.input_sensitivity == 2.0
    assert restored.input_sensitivity_is_calibrated is True


def test_profile_names_are_trimmed_and_duplicates_are_rejected(tmp_path):
    manager = CalibrationManager(str(tmp_path / "calibration.json"))
    manager.create_profile("  Trimmed  ")

    assert "Trimmed" in manager.get_profiles()
    with pytest.raises(ValueError, match="already exists"):
        manager.duplicate_profile("Trimmed")
    with pytest.raises(ValueError, match="cannot be empty"):
        manager.create_profile("   ")


if __name__ == "__main__":
    unittest.main()
