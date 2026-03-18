import os
import math
import pytest
import numpy as np

from src.core.calibration import CalibrationManager


@pytest.fixture
def temp_config_path(tmp_path):
    return str(tmp_path / "calibration.json")


@pytest.fixture
def temp_map_path(tmp_path):
    return str(tmp_path / "map.json")


@pytest.fixture
def calibration_manager(temp_config_path):
    return CalibrationManager(config_filename=temp_config_path)


def test_initialization(calibration_manager, temp_config_path):
    """Test initial state of CalibrationManager."""
    assert calibration_manager.config_path == temp_config_path
    assert calibration_manager.input_sensitivity == 1.0
    assert calibration_manager.output_gain == 1.0
    assert calibration_manager.output_gain_is_calibrated is False
    assert calibration_manager.frequency_calibration == 1.0
    assert calibration_manager.frequency_calibration_1pps == 1.0
    assert calibration_manager.frequency_calibration_source == "basic"
    assert calibration_manager.lockin_gain_offset == 0.0
    assert calibration_manager.spl_offset_db is None
    assert calibration_manager.profiles == {}
    assert calibration_manager.last_profile is None
    assert calibration_manager.frequency_map == []


def test_save_and_load(calibration_manager, temp_config_path):
    """Test saving and loading basic attributes."""
    calibration_manager.input_sensitivity = 2.0
    calibration_manager.output_gain = 0.5
    calibration_manager.output_gain_is_calibrated = True
    calibration_manager.frequency_calibration = 1.05
    calibration_manager.frequency_calibration_1pps = 0.95
    calibration_manager.frequency_calibration_source = "1pps"
    calibration_manager.lockin_gain_offset = 3.5
    calibration_manager.spl_offset_db = 100.0

    calibration_manager.save()

    new_cm = CalibrationManager(config_filename=temp_config_path)
    assert new_cm.input_sensitivity == 2.0
    assert new_cm.output_gain == 0.5
    assert new_cm.output_gain_is_calibrated is True
    assert new_cm.frequency_calibration == 1.05
    assert new_cm.frequency_calibration_1pps == 0.95
    assert new_cm.frequency_calibration_source == "1pps"
    assert new_cm.lockin_gain_offset == 3.5
    assert new_cm.spl_offset_db == 100.0


def test_spl_calibration(calibration_manager):
    """Test SPL calibration calculation and conversions."""
    # Measure 80 dB SPL at -20 dBFS => offset = 100 dB
    calibration_manager.set_spl_calibration(-20.0, 80.0)
    assert calibration_manager.get_spl_offset_db() == 100.0

    spl = calibration_manager.dbfs_to_spl(-10.0)
    assert spl == 90.0

    spl = calibration_manager.dbfs_to_spl(0.0)
    assert spl == 100.0


def test_spl_calibration_invalid(calibration_manager):
    """Test invalid inputs for SPL calibration."""
    with pytest.raises(ValueError):
        calibration_manager.set_spl_calibration("invalid", 80.0)

    with pytest.raises(ValueError):
        calibration_manager.set_spl_calibration(-20.0, "invalid")


def test_set_sensitivities(calibration_manager):
    """Test setting sensitivity and gain."""
    calibration_manager.set_input_sensitivity(2.5)
    assert calibration_manager.input_sensitivity == 2.5

    calibration_manager.set_output_gain(3.0)
    assert calibration_manager.output_gain == 3.0
    assert calibration_manager.output_gain_is_calibrated is True

    with pytest.raises(ValueError):
        calibration_manager.set_output_gain(-1.0)


def test_frequency_calibration_methods(calibration_manager):
    """Test setting various frequency calibrations."""
    calibration_manager.set_frequency_calibration(1.02)
    assert calibration_manager.frequency_calibration == 1.02

    calibration_manager.set_frequency_calibration_1pps(0.98)
    assert calibration_manager.frequency_calibration_1pps == 0.98

    calibration_manager.set_frequency_calibration_source("1pps")
    assert calibration_manager.frequency_calibration_source == "1pps"
    assert calibration_manager.get_active_frequency_calibration() == 0.98

    calibration_manager.set_frequency_calibration_source("basic")
    assert calibration_manager.get_active_frequency_calibration() == 1.02


def test_lockin_gain_offset(calibration_manager):
    """Test lock-in gain offset handling."""
    calibration_manager.set_lockin_gain_offset(5.0)
    assert calibration_manager.lockin_gain_offset == 5.0

    calibration_manager.set_lockin_gain_offset("10.0")
    assert calibration_manager.lockin_gain_offset == 10.0


def test_profile_management(calibration_manager):
    """Test creating, loading, and deleting profiles."""
    calibration_manager.input_sensitivity = 4.0
    calibration_manager.set_spl_calibration(-20.0, 80.0)

    calibration_manager.save_profile("Prof1", "Device A")

    profiles = calibration_manager.get_profiles()
    assert "Prof1" in profiles
    assert profiles["Prof1"]["input_sensitivity"] == 4.0

    # Change current values. Note: set_last_profile triggers a save() which synchronize current values to the profile if last_profile is set
    # We clear the last_profile before changing values to avoid overwriting the saved profile
    calibration_manager.last_profile = None
    calibration_manager.input_sensitivity = 1.0

    # Load profile restores values
    calibration_manager.load_profile("Prof1")
    assert calibration_manager.input_sensitivity == 4.0

    calibration_manager.delete_profile("Prof1")
    assert "Prof1" not in calibration_manager.get_profiles()


def test_dbfs_to_dbv(calibration_manager):
    """Test dBFS to dBV conversions."""
    # Sensitivity = 2.0V => 20*log10(2.0) = 6.02 dB
    calibration_manager.set_input_sensitivity(2.0)

    expected_offset = 20 * math.log10(2.0)
    assert np.isclose(calibration_manager.get_input_offset_db(), expected_offset)

    assert np.isclose(calibration_manager.dbfs_to_dbv(0.0), expected_offset)
    assert np.isclose(calibration_manager.dbfs_to_dbv(-10.0), -10.0 + expected_offset)


def test_frequency_map(calibration_manager, temp_map_path):
    """Test loading, saving, and querying frequency maps."""
    map_data = [
        [10.0, -1.0, 45.0],
        [100.0, 0.0, 0.0],
        [1000.0, 1.0, -45.0]
    ]

    assert calibration_manager.save_frequency_map(temp_map_path, map_data) is True

    # Verify file was created
    assert os.path.exists(temp_map_path)

    # Clear state
    calibration_manager.frequency_map = []
    calibration_manager._update_map_cache()
    assert calibration_manager.get_frequency_correction(100.0) == (0.0, 0.0)

    # Load data
    assert calibration_manager.load_frequency_map(temp_map_path) is True
    assert len(calibration_manager.frequency_map) == 3

    # Exact matches
    mag, phase = calibration_manager.get_frequency_correction(100.0)
    assert mag == 0.0
    assert phase == 0.0

    # Interpolation
    mag, phase = calibration_manager.get_frequency_correction(550.0)
    # Between 100.0 and 1000.0, 550.0 is exactly half way.
    # Mag goes 0.0 to 1.0 => 0.5
    # Phase goes 0.0 to -45.0 => -22.5
    assert np.isclose(mag, 0.5)
    assert np.isclose(phase, -22.5)

    # Out of bounds clamping
    mag, phase = calibration_manager.get_frequency_correction(5.0)
    assert mag == -1.0
    assert phase == 45.0

    mag, phase = calibration_manager.get_frequency_correction(2000.0)
    assert mag == 1.0
    assert phase == -45.0
