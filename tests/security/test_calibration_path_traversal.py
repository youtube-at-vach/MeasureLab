import os
import json
import tempfile
from src.core.calibration import CalibrationManager


def test_load_frequency_map_allows_external_path():
    """
    Test that load_frequency_map allows loading files from outside the config directory.
    Previously this was restricted, but the restriction was removed for usability.
    """
    # Create two temporary directories:
    # 1. safe_dir: acting as the allowed config directory.
    # 2. external_dir: acting as an outside directory (e.g. Downloads).
    with tempfile.TemporaryDirectory() as safe_dir, tempfile.TemporaryDirectory() as external_dir:
        # Initialize CalibrationManager in safe_dir
        config_path = os.path.join(safe_dir, "calibration.json")
        cal = CalibrationManager(config_path=config_path)

        # Create a valid map file in safe_dir
        valid_map_path = os.path.join(safe_dir, "valid_map.json")
        valid_data = [[1000, 0.0, 0.0]]
        with open(valid_map_path, "w") as f:
            json.dump(valid_data, f)

        # Create a map file in external_dir
        external_map_path = os.path.join(external_dir, "external_map.json")
        external_data = [[1000, 10.0, 10.0]]
        with open(external_map_path, "w") as f:
            json.dump(external_data, f)

        # 1. Load valid map -> Should succeed
        assert cal.load_frequency_map(valid_map_path) is True
        assert len(cal.frequency_map) == 1

        # 2. Load external map -> Should SUCCEED (return True)
        result = cal.load_frequency_map(external_map_path)
        assert result is True, "Should allow file outside config directory"
        # Verify data loaded correctly (external data has gain 10.0)
        assert cal.frequency_map[0][1] == 10.0

        # 3. Test subdirectory in safe_dir -> Should succeed
        sub_dir = os.path.join(safe_dir, "subdir")
        os.makedirs(sub_dir, exist_ok=True)
        sub_map_path = os.path.join(sub_dir, "sub_map.json")
        with open(sub_map_path, "w") as f:
            json.dump(valid_data, f)

        assert cal.load_frequency_map(sub_map_path) is True
