import sys
import math
from unittest.mock import MagicMock

# --- Conditional Mock for numpy ---
# Only mock numpy if it's not already installed/available.
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
    np = mock_np

# --------------------------------------------------------

import pytest  # noqa: E402
import json  # noqa: E402
from src.core.calibration import CalibrationManager  # noqa: E402

@pytest.fixture
def legacy_config_path(tmp_path):
    return tmp_path / "legacy_calibration.json"

def test_legacy_speaker_priority(legacy_config_path):
    """Verify that if 'speaker' key exists in spl_calibration, its offset_db is used."""
    data = {
        "spl_calibration": {
            "speaker": {
                "offset_db": 10.5
            },
            "subwoofer": {
                "offset_db": -5.0
            }
        }
    }
    with open(legacy_config_path, "w") as f:
        json.dump(data, f)

    cm = CalibrationManager(str(legacy_config_path))
    assert cm.spl_offset_db == 10.5

def test_legacy_subwoofer_fallback(legacy_config_path):
    """Verify that if 'speaker' is missing but 'subwoofer' exists, its offset_db is used."""
    data = {
        "spl_calibration": {
            "subwoofer": {
                "offset_db": -5.0
            }
        }
    }
    with open(legacy_config_path, "w") as f:
        json.dump(data, f)

    cm = CalibrationManager(str(legacy_config_path))
    assert cm.spl_offset_db == -5.0

def test_legacy_arbitrary_key_fallback(legacy_config_path):
    """Verify that if neither 'speaker' nor 'subwoofer' exists, the first available key's offset_db is used."""
    data = {
        "spl_calibration": {
            "unknown_device": {
                "offset_db": 3.3
            }
        }
    }
    with open(legacy_config_path, "w") as f:
        json.dump(data, f)

    cm = CalibrationManager(str(legacy_config_path))
    assert cm.spl_offset_db == 3.3

def test_legacy_invalid_format(legacy_config_path):
    """Verify behavior with broken JSON structure or invalid values (should result in None)."""
    # Case 1: spl_calibration is not a dict
    data = {
        "spl_calibration": "invalid"
    }
    with open(legacy_config_path, "w") as f:
        json.dump(data, f)
    cm = CalibrationManager(str(legacy_config_path))
    assert cm.spl_offset_db is None

    # Case 2: offset_db is invalid
    data = {
        "spl_calibration": {
            "speaker": {
                "offset_db": "not_a_number"
            }
        }
    }
    with open(legacy_config_path, "w") as f:
        json.dump(data, f)
    cm = CalibrationManager(str(legacy_config_path))
    assert cm.spl_offset_db is None

    # Case 3: entry is not a dict
    data = {
        "spl_calibration": {
            "speaker": "not_a_dict"
        }
    }
    with open(legacy_config_path, "w") as f:
        json.dump(data, f)
    cm = CalibrationManager(str(legacy_config_path))
    assert cm.spl_offset_db is None

def test_legacy_precedence(legacy_config_path):
    """Verify that if the new format spl_offset_db is present at the top level, it takes precedence over the legacy format."""
    data = {
        "spl_offset_db": 20.0,
        "spl_calibration": {
            "speaker": {
                "offset_db": 10.0
            }
        }
    }
    with open(legacy_config_path, "w") as f:
        json.dump(data, f)

    cm = CalibrationManager(str(legacy_config_path))
    assert cm.spl_offset_db == 20.0

def test_legacy_empty_dict(legacy_config_path):
    """Verify behavior when spl_calibration is an empty dict."""
    data = {
        "spl_calibration": {}
    }
    with open(legacy_config_path, "w") as f:
        json.dump(data, f)
    cm = CalibrationManager(str(legacy_config_path))
    assert cm.spl_offset_db is None
