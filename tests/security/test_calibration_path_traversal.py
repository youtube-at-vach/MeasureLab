import os
import json
import tempfile
from src.core.calibration import CalibrationManager


def test_load_frequency_map_traversal():
    """
    Test that load_frequency_map prevents path traversal.
    """
    # Create two temporary directories:
    # 1. safe_dir: acting as the allowed config directory.
    # 2. malicious_dir: acting as an outside directory.
    with tempfile.TemporaryDirectory() as safe_dir, tempfile.TemporaryDirectory() as malicious_dir:
        # Initialize CalibrationManager in safe_dir
        config_path = os.path.join(safe_dir, "calibration.json")
        cal = CalibrationManager(config_path=config_path)

        # Create a valid map file in safe_dir
        valid_map_path = os.path.join(safe_dir, "valid_map.json")
        valid_data = [[1000, 0.0, 0.0]]
        with open(valid_map_path, "w") as f:
            json.dump(valid_data, f)

        # Create a malicious map file in malicious_dir
        malicious_map_path = os.path.join(malicious_dir, "malicious_map.json")
        malicious_data = [[1000, 10.0, 10.0]]
        with open(malicious_map_path, "w") as f:
            json.dump(malicious_data, f)

        # 1. Load valid map -> Should succeed
        assert cal.load_frequency_map(valid_map_path) is True
        assert len(cal.frequency_map) == 1

        # 2. Load malicious map -> Should FAIL (return False)
        # Note: Before the fix, this will likely return True.
        # After the fix, it should return False.
        result = cal.load_frequency_map(malicious_map_path)
        assert result is False, "Should reject file outside config directory"

        # 3. Test subdirectory in safe_dir -> Should succeed
        sub_dir = os.path.join(safe_dir, "subdir")
        os.makedirs(sub_dir, exist_ok=True)
        sub_map_path = os.path.join(sub_dir, "sub_map.json")
        with open(sub_map_path, "w") as f:
            json.dump(valid_data, f)

        assert cal.load_frequency_map(sub_map_path) is True
