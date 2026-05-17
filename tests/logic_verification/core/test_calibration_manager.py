import sys
import math
from unittest.mock import MagicMock

# --- Conditional Mock for numpy ---
# Only mock numpy if it's not already installed/available.
# This prevents polluting the test environment when running full CI suites.
try:
    import numpy as np
except ImportError:

    class MockNumpyArray:
        def __init__(self, data):
            self.data = data

        def __getitem__(self, key):
            # Handle [:, i] slicing
            if isinstance(key, tuple) and len(key) == 2 and key[0] == slice(None):
                col_idx = key[1]
                return [row[col_idx] for row in self.data]
            return []

    def mock_interp(x, xp, fp):
        # Simple linear interpolation for lists
        if not xp or not fp:
            return 0.0

        if x <= xp[0]:
            return fp[0]
        if x >= xp[-1]:
            return fp[-1]

        for i in range(len(xp) - 1):
            if xp[i] <= x <= xp[i + 1]:
                t = (x - xp[i]) / (xp[i + 1] - xp[i])
                return fp[i] + t * (fp[i + 1] - fp[i])
        return 0.0

    mock_np = MagicMock()
    mock_np.isfinite = lambda x: True
    mock_np.log10 = math.log10
    mock_np.array = lambda x: MockNumpyArray(x)
    mock_np.interp = mock_interp
    mock_np.isclose = lambda a, b, atol=1e-8: abs(a - b) <= atol

    sys.modules["numpy"] = mock_np
    np = mock_np

# --------------------------------------------------------

import pytest  # noqa: E402
import os  # noqa: E402
import json  # noqa: E402
from src.core.calibration import CalibrationManager  # noqa: E402
import tempfile  # noqa: E402


@pytest.fixture
def cal_manager(tmp_path):
    """Fixture that provides a CalibrationManager instance with a temporary config path."""
    config_path = tmp_path / "calibration.json"
    cm = CalibrationManager(str(config_path))
    return cm


def test_save_load(cal_manager):
    """Test saving and loading calibration data."""
    cal_manager.input_sensitivity = 2.0
    cal_manager.output_gain = 0.5
    cal_manager.output_gain_is_calibrated = True
    cal_manager.frequency_calibration_1pps = 0.999
    cal_manager.save()

    # Reload in a new instance
    new_cm = CalibrationManager(cal_manager.config_path)
    assert new_cm.input_sensitivity == 2.0
    assert new_cm.output_gain == 0.5
    assert new_cm.output_gain_is_calibrated is True
    assert new_cm.frequency_calibration_1pps == 0.999


def test_load_missing_file(cal_manager):
    """Test loading when file does not exist (should use defaults)."""
    if os.path.exists(cal_manager.config_path):
        os.remove(cal_manager.config_path)

    cal_manager.load()
    assert cal_manager.input_sensitivity == 1.0


def test_load_corrupted_file(cal_manager):
    """Test loading when file contains invalid JSON."""
    with open(cal_manager.config_path, "w") as f:
        f.write("{invalid_json")

    # Should catch exception and keep defaults
    cal_manager.load()
    assert cal_manager.input_sensitivity == 1.0


def test_spl_calibration(cal_manager):
    """Test SPL calibration logic."""
    # SPL = dBFS + offset
    # 80 dB SPL measured at -20 dBFS => offset = 100 dB
    cal_manager.set_spl_calibration(-20.0, 80.0)
    assert cal_manager.spl_offset_db == 100.0

    spl = cal_manager.dbfs_to_spl(-20.0)
    assert spl == 80.0

    # Test persistence
    cal_manager.save()
    new_cm = CalibrationManager(cal_manager.config_path)
    assert new_cm.spl_offset_db == 100.0


def test_spl_invalid_input(cal_manager):
    """Test invalid input for SPL calibration."""
    # Test invalid type for measured_dbfs_c
    with pytest.raises(ValueError, match="Invalid SPL calibration values"):
        cal_manager.set_spl_calibration("invalid", 80.0)
    with pytest.raises(ValueError, match="Invalid SPL calibration values"):
        cal_manager.set_spl_calibration(None, 80.0)

    # Test invalid type for measured_spl_db
    with pytest.raises(ValueError, match="Invalid SPL calibration values"):
        cal_manager.set_spl_calibration(-20.0, "invalid")
    with pytest.raises(ValueError, match="Invalid SPL calibration values"):
        cal_manager.set_spl_calibration(-20.0, [80.0])

    # Test invalid type for both
    with pytest.raises(ValueError, match="Invalid SPL calibration values"):
        cal_manager.set_spl_calibration("abc", "def")


def test_get_spl_offset_db_none(cal_manager):
    """Test get_spl_offset_db returns None when not calibrated."""
    assert cal_manager.get_spl_offset_db() is None


def test_dbfs_to_spl(cal_manager):
    """Test dbfs_to_spl logic for various inputs and edge cases."""
    # When offset is not set, it should return None
    assert cal_manager.spl_offset_db is None
    assert cal_manager.dbfs_to_spl(-20.0) is None

    # Set up calibration (e.g. 80 dB SPL measured at -20 dBFS => offset = 100 dB)
    cal_manager.set_spl_calibration(-20.0, 80.0)
    assert cal_manager.spl_offset_db == 100.0

    # Test with standard floats
    assert cal_manager.dbfs_to_spl(-20.0) == 80.0
    assert cal_manager.dbfs_to_spl(0.0) == 100.0
    assert cal_manager.dbfs_to_spl(-100.0) == 0.0

    # Test with integers
    assert cal_manager.dbfs_to_spl(-20) == 80.0

    # Test with strings that can be parsed as floats
    assert cal_manager.dbfs_to_spl("-20.0") == 80.0

    # Test ignoring the profile parameter
    assert cal_manager.dbfs_to_spl(-20.0, profile="dummy") == 80.0

    # Test invalid inputs
    with pytest.raises(ValueError):
        cal_manager.dbfs_to_spl("invalid")


def test_profile_management(cal_manager):
    """Test creating, loading, and deleting profiles."""
    cal_manager.input_sensitivity = 0.5
    cal_manager.save_profile("test_profile", "MyDevice")

    assert "test_profile" in cal_manager.get_profiles()
    assert cal_manager.profiles["test_profile"]["input_sensitivity"] == 0.5

    # Change current value
    cal_manager.input_sensitivity = 1.0

    # Load profile
    cal_manager.load_profile("test_profile")
    assert cal_manager.input_sensitivity == 0.5

    # Delete profile
    cal_manager.delete_profile("test_profile")
    assert "test_profile" not in cal_manager.get_profiles()


def test_delete_non_existent_profile(cal_manager):
    """Test deleting a profile that doesn't exist (should not raise error)."""
    # Ensure it handles missing profiles gracefully
    cal_manager.delete_profile("ghost_profile")
    assert "ghost_profile" not in cal_manager.get_profiles()


def test_load_non_existent_profile(cal_manager):
    """Test loading a profile that doesn't exist."""
    with pytest.raises(ValueError, match="Profile 'fake' not found"):
        cal_manager.load_profile("fake")


def test_conversions(cal_manager):
    """Test voltage and dBV conversions."""
    cal_manager.input_sensitivity = 2.0  # 2V at 0 dBFS

    # dBV = dBFS + 20*log10(sensitivity)
    # sensitivity=2.0 -> +6.02 dB
    # 0 dBFS -> 6.02 dBV
    expected_dbv = 20 * math.log10(2.0)

    # Check input offset helper
    assert np.isclose(cal_manager.get_input_offset_db(), expected_dbv)


def test_set_input_sensitivity(cal_manager):
    """Test setting input sensitivity updates value and calls save."""
    from unittest.mock import patch

    with patch.object(cal_manager, "save") as mock_save:
        # Test valid float
        cal_manager.set_input_sensitivity(5.5)
        assert cal_manager.input_sensitivity == 5.5
        mock_save.assert_called_once()
        mock_save.reset_mock()

        # Test valid int
        cal_manager.set_input_sensitivity(10)
        assert cal_manager.input_sensitivity == 10
        mock_save.assert_called_once()
        mock_save.reset_mock()


def test_output_gain_validation(cal_manager):
    """Test validation for output gain setting."""
    cal_manager.set_output_gain(2.0)
    assert cal_manager.output_gain == 2.0
    assert cal_manager.output_gain_is_calibrated is True

    with pytest.raises(ValueError, match="Invalid output gain"):
        cal_manager.set_output_gain(-1.0)

    with pytest.raises(ValueError, match="Invalid output gain"):
        cal_manager.set_output_gain(0.0)


def test_set_lockin_gain_offset(cal_manager):
    """Test setting lock-in gain offset updates value and calls save."""
    from unittest.mock import patch

    with patch.object(cal_manager, "save") as mock_save:
        # Test valid float
        cal_manager.set_lockin_gain_offset(5.5)
        assert cal_manager.lockin_gain_offset == 5.5
        mock_save.assert_called_once()
        mock_save.reset_mock()

        # Test valid int
        cal_manager.set_lockin_gain_offset(10)
        assert cal_manager.lockin_gain_offset == 10.0
        mock_save.assert_called_once()
        mock_save.reset_mock()

        # Test negative value
        cal_manager.set_lockin_gain_offset(-3.2)
        assert cal_manager.lockin_gain_offset == -3.2
        mock_save.assert_called_once()
        mock_save.reset_mock()

        # Test invalid string (fails safely)
        cal_manager.set_lockin_gain_offset("invalid")
        mock_save.assert_not_called()

        # Test invalid type (fails safely)
        cal_manager.set_lockin_gain_offset(None)
        mock_save.assert_not_called()


def test_set_frequency_calibration(cal_manager):
    """Test setting frequency calibration updates value and calls save."""
    from unittest.mock import patch

    with patch.object(cal_manager, "save") as mock_save:
        cal_manager.set_frequency_calibration(1.0001)
        assert cal_manager.frequency_calibration == 1.0001
        mock_save.assert_called_once()


def test_set_frequency_calibration_1pps(cal_manager):
    """Test setting 1PPS frequency calibration updates value and calls save."""
    from unittest.mock import patch

    with patch.object(cal_manager, "save") as mock_save:
        cal_manager.set_frequency_calibration_1pps(0.9999)
        assert cal_manager.frequency_calibration_1pps == 0.9999
        mock_save.assert_called_once()


def test_set_frequency_calibration_source(cal_manager):
    """Test setting frequency calibration source updates value and calls save for valid inputs."""
    from unittest.mock import patch

    with patch.object(cal_manager, "save") as mock_save:
        # Valid source '1pps'
        cal_manager.set_frequency_calibration_source("1pps")
        assert cal_manager.frequency_calibration_source == "1pps"
        mock_save.assert_called_once()
        mock_save.reset_mock()

        # Valid source 'basic'
        cal_manager.set_frequency_calibration_source("basic")
        assert cal_manager.frequency_calibration_source == "basic"
        mock_save.assert_called_once()
        mock_save.reset_mock()

        # Invalid source (should ignore and not save)
        cal_manager.set_frequency_calibration_source("invalid")
        assert cal_manager.frequency_calibration_source == "basic"  # Remains unchanged
        mock_save.assert_not_called()


def test_frequency_map_persistence(cal_manager, tmp_path):
    """Test saving and loading frequency map."""
    map_path = tmp_path / "freq_map.json"
    data = [[100, 1.0, 0], [1000, 0.0, 0]]

    assert cal_manager.save_frequency_map(str(map_path), data) is True
    assert cal_manager.load_frequency_map(str(map_path)) is True

    # Check loaded data
    assert len(cal_manager.frequency_map) == 2
    assert cal_manager.frequency_map[0] == [100, 1.0, 0]


def test_frequency_correction_interpolation(cal_manager, tmp_path):
    """Test frequency correction interpolation."""
    map_path = tmp_path / "freq_map.json"
    # Freq, Mag (dB), Phase (deg)
    data = [[100, 10.0, 45.0], [1000, 0.0, 0.0], [10000, -10.0, -45.0]]
    cal_manager.save_frequency_map(str(map_path), data)
    cal_manager.load_frequency_map(str(map_path))

    # Exact match
    mag, phase = cal_manager.get_frequency_correction(1000)
    assert mag == 0.0
    assert phase == 0.0

    # Interpolation (550 Hz is halfway between 100 and 1000)
    # 100Hz: 10dB, 1000Hz: 0dB. Range 900Hz. Delta -10dB.
    # 550Hz is 450Hz above 100Hz. 450/900 = 0.5
    # Expected: 5.0 dB
    mag, phase = cal_manager.get_frequency_correction(550)
    assert np.isclose(mag, 5.0)

    # Out of bounds (below)
    mag, phase = cal_manager.get_frequency_correction(50)
    assert mag == 10.0

    # Out of bounds (above)
    mag, phase = cal_manager.get_frequency_correction(20000)
    assert mag == -10.0


def test_frequency_map_load_external(cal_manager, tmp_path):
    """Test that loading files outside the config directory is allowed."""
    # Create a file in a separate temp directory that is not a child of tmp_path
    with tempfile.TemporaryDirectory() as unsafe_dir:
        unsafe_map = os.path.join(unsafe_dir, "unsafe.json")
        data = [[100, 1.0, 0]]
        with open(unsafe_map, "w") as f:
            json.dump(data, f)

        # Should be allowed (restriction removed)
        assert cal_manager.load_frequency_map(unsafe_map) is True


def test_no_frequency_map(cal_manager):
    """Test behavior when no frequency map is loaded."""
    # Ensure it's empty
    cal_manager.frequency_map = []
    cal_manager._update_map_cache()

    mag, phase = cal_manager.get_frequency_correction(1000)
    assert mag == 0.0
    assert phase == 0.0


def test_frequency_map_reload_cache_update(cal_manager, tmp_path):
    """Test that reloading a frequency map updates the cache."""
    map_path1 = tmp_path / "map1.json"
    map_path2 = tmp_path / "map2.json"

    # Map 1: 100Hz -> 10.0 dB
    data1 = [[100, 10.0, 0.0]]
    with open(map_path1, "w") as f:
        json.dump(data1, f)

    # Map 2: 100Hz -> 20.0 dB
    data2 = [[100, 20.0, 0.0]]
    with open(map_path2, "w") as f:
        json.dump(data2, f)

    # Load Map 1
    cal_manager.load_frequency_map(str(map_path1))
    mag, _ = cal_manager.get_frequency_correction(100)
    assert mag == 10.0

    # Load Map 2
    cal_manager.load_frequency_map(str(map_path2))
    mag, _ = cal_manager.get_frequency_correction(100)
    assert mag == 20.0


# --- Legacy Support Tests ---


@pytest.fixture
def legacy_config_path(tmp_path):
    return tmp_path / "legacy_calibration.json"


def test_legacy_speaker_priority(legacy_config_path):
    """Verify that if 'speaker' key exists in spl_calibration, its offset_db is used."""
    data = {"spl_calibration": {"speaker": {"offset_db": 10.5}, "subwoofer": {"offset_db": -5.0}}}
    with open(legacy_config_path, "w") as f:
        json.dump(data, f)

    cm = CalibrationManager(str(legacy_config_path))
    assert cm.spl_offset_db == 10.5


def test_legacy_subwoofer_fallback(legacy_config_path):
    """Verify that if 'speaker' is missing but 'subwoofer' exists, its offset_db is used."""
    data = {"spl_calibration": {"subwoofer": {"offset_db": -5.0}}}
    with open(legacy_config_path, "w") as f:
        json.dump(data, f)

    cm = CalibrationManager(str(legacy_config_path))
    assert cm.spl_offset_db == -5.0


def test_legacy_arbitrary_key_fallback(legacy_config_path):
    """Verify that if neither 'speaker' nor 'subwoofer' exists, the first available key's offset_db is used."""
    data = {"spl_calibration": {"unknown_device": {"offset_db": 3.3}}}
    with open(legacy_config_path, "w") as f:
        json.dump(data, f)

    cm = CalibrationManager(str(legacy_config_path))
    assert cm.spl_offset_db == 3.3


def test_legacy_invalid_format(legacy_config_path):
    """Verify behavior with broken JSON structure or invalid values (should result in None)."""
    # Case 1: spl_calibration is not a dict
    data = {"spl_calibration": "invalid"}
    with open(legacy_config_path, "w") as f:
        json.dump(data, f)
    cm = CalibrationManager(str(legacy_config_path))
    assert cm.spl_offset_db is None

    # Case 2: offset_db is invalid
    data = {"spl_calibration": {"speaker": {"offset_db": "not_a_number"}}}
    with open(legacy_config_path, "w") as f:
        json.dump(data, f)
    cm = CalibrationManager(str(legacy_config_path))
    assert cm.spl_offset_db is None

    # Case 3: entry is not a dict
    data = {"spl_calibration": {"speaker": "not_a_dict"}}
    with open(legacy_config_path, "w") as f:
        json.dump(data, f)
    cm = CalibrationManager(str(legacy_config_path))
    assert cm.spl_offset_db is None


def test_legacy_precedence(legacy_config_path):
    """Verify that if the new format spl_offset_db is present at the top level, it takes precedence over the legacy format."""
    data = {"spl_offset_db": 20.0, "spl_calibration": {"speaker": {"offset_db": 10.0}}}
    with open(legacy_config_path, "w") as f:
        json.dump(data, f)

    cm = CalibrationManager(str(legacy_config_path))
    assert cm.spl_offset_db == 20.0


def test_legacy_empty_dict(legacy_config_path):
    """Verify behavior when spl_calibration is an empty dict."""
    data = {"spl_calibration": {}}
    with open(legacy_config_path, "w") as f:
        json.dump(data, f)
    cm = CalibrationManager(str(legacy_config_path))
    assert cm.spl_offset_db is None

def test_update_map_cache(cal_manager):
    """Test that _update_map_cache correctly updates the cache arrays."""
    # Test with empty map
    cal_manager.frequency_map = []
    cal_manager._update_map_cache()

    import numpy as np
    assert cal_manager._freq_cache is None
    assert cal_manager._mag_cache is None
    assert cal_manager._phase_cache is None

    # Test with populated map
    cal_manager.frequency_map = [
        [100.0, 1.0, 10.0],
        [1000.0, 2.0, 20.0],
        [10000.0, 3.0, 30.0]
    ]
    cal_manager._update_map_cache()

    np.testing.assert_array_equal(cal_manager._freq_cache, np.array([100.0, 1000.0, 10000.0]))
    np.testing.assert_array_equal(cal_manager._mag_cache, np.array([1.0, 2.0, 3.0]))
    np.testing.assert_array_equal(cal_manager._phase_cache, np.array([10.0, 20.0, 30.0]))
