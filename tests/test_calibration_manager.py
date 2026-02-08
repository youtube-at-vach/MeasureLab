import sys
import math
from unittest.mock import MagicMock

# --- Mock numpy before importing src.core.calibration ---
# This is necessary because numpy is not available in the test environment.
# We mock it globally for this module, and will clean it up after.
ORIGINAL_NUMPY = sys.modules.get("numpy")

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
    # This allows us to verify the logic of get_frequency_correction
    # without needing the heavy numpy dependency.
    if not xp or not fp:
        return 0.0

    if x <= xp[0]:
        return fp[0]
    if x >= xp[-1]:
        return fp[-1]

    for i in range(len(xp) - 1):
        if xp[i] <= x <= xp[i+1]:
            t = (x - xp[i]) / (xp[i+1] - xp[i])
            return fp[i] + t * (fp[i+1] - fp[i])
    return 0.0

mock_np = MagicMock()
mock_np.isfinite = lambda x: True
mock_np.log10 = math.log10
mock_np.array = lambda x: MockNumpyArray(x)
mock_np.interp = mock_interp
mock_np.isclose = lambda a, b, atol=1e-8: abs(a - b) <= atol

sys.modules["numpy"] = mock_np
# --------------------------------------------------------

import pytest  # noqa: E402
import os  # noqa: E402
import json  # noqa: E402
from src.core.calibration import CalibrationManager  # noqa: E402
import tempfile  # noqa: E402

# We use our mocked numpy as np in tests too
np = mock_np

@pytest.fixture(scope="module", autouse=True)
def cleanup_numpy_mock():
    yield
    # Restore original numpy or remove mock
    if ORIGINAL_NUMPY:
        sys.modules["numpy"] = ORIGINAL_NUMPY
    else:
        # Only delete if it's still our mock, to avoid deleting something else if things went wild
        if "numpy" in sys.modules and sys.modules["numpy"] is mock_np:
            del sys.modules["numpy"]

@pytest.fixture
def cal_manager(tmp_path):
    """Fixture that provides a CalibrationManager instance with a temporary config path."""
    config_path = tmp_path / "calibration.json"
    cm = CalibrationManager(str(config_path))
    return cm

def test_initialization(cal_manager):
    """Test default values upon initialization."""
    assert cal_manager.input_sensitivity == 1.0
    assert cal_manager.output_gain == 1.0
    assert cal_manager.output_gain_is_calibrated is False
    assert cal_manager.frequency_calibration == 1.0
    assert cal_manager.lockin_gain_offset == 0.0
    assert cal_manager.spl_offset_db is None
    assert cal_manager.profiles == {}
    assert cal_manager.last_profile is None

def test_save_load(cal_manager):
    """Test saving and loading calibration data."""
    cal_manager.input_sensitivity = 2.0
    cal_manager.output_gain = 0.5
    cal_manager.output_gain_is_calibrated = True
    cal_manager.save()

    # Reload in a new instance
    new_cm = CalibrationManager(cal_manager.config_path)
    assert new_cm.input_sensitivity == 2.0
    assert new_cm.output_gain == 0.5
    assert new_cm.output_gain_is_calibrated is True

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
    with pytest.raises(ValueError, match="Invalid SPL calibration values"):
        cal_manager.set_spl_calibration("invalid", 80.0)

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

def test_load_non_existent_profile(cal_manager):
    """Test loading a profile that doesn't exist."""
    with pytest.raises(ValueError, match="Profile 'fake' not found"):
        cal_manager.load_profile("fake")

def test_conversions(cal_manager):
    """Test voltage and dBV conversions."""
    cal_manager.input_sensitivity = 2.0 # 2V at 0 dBFS

    # 0 dBFS -> 2V
    assert np.isclose(cal_manager.dbfs_to_volts(0), 2.0)

    # -6.0206 dBFS -> 1V (approx)
    # 20 * log10(0.5) = -6.0205999...
    db_val = 20 * math.log10(0.5)
    assert np.isclose(cal_manager.dbfs_to_volts(db_val), 1.0, atol=0.001)

    # dBV = dBFS + 20*log10(sensitivity)
    # sensitivity=2.0 -> +6.02 dB
    # 0 dBFS -> 6.02 dBV
    expected_dbv = 20*math.log10(2.0)
    assert np.isclose(cal_manager.dbfs_to_dbv(0), expected_dbv)

    # Check input offset helper
    assert np.isclose(cal_manager.get_input_offset_db(), expected_dbv)

def test_output_gain_validation(cal_manager):
    """Test validation for output gain setting."""
    cal_manager.set_output_gain(2.0)
    assert cal_manager.output_gain == 2.0
    assert cal_manager.output_gain_is_calibrated is True

    with pytest.raises(ValueError, match="Invalid output gain"):
        cal_manager.set_output_gain(-1.0)

    with pytest.raises(ValueError, match="Invalid output gain"):
        cal_manager.set_output_gain(0.0)

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
    data = [
        [100, 10.0, 45.0],
        [1000, 0.0, 0.0],
        [10000, -10.0, -45.0]
    ]
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

def test_frequency_map_security(cal_manager, tmp_path):
    """Test that loading files outside the config directory is rejected."""
    # Create a file in a separate temp directory that is not a child of tmp_path
    with tempfile.TemporaryDirectory() as unsafe_dir:
        unsafe_map = os.path.join(unsafe_dir, "unsafe.json")
        data = [[100, 1.0, 0]]
        with open(unsafe_map, "w") as f:
            json.dump(data, f)

        # Should be rejected because it is not inside tmp_path (where config_path is)
        assert cal_manager.load_frequency_map(unsafe_map) is False

def test_no_frequency_map(cal_manager):
    """Test behavior when no frequency map is loaded."""
    if hasattr(cal_manager, "frequency_map"):
        del cal_manager.frequency_map

    mag, phase = cal_manager.get_frequency_correction(1000)
    assert mag == 0.0
    assert phase == 0.0
