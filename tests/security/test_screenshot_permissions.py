import os
import stat
import tempfile
import sys
import shutil

# Ensure we can import src
sys.path.append(os.getcwd())

from src.core.config_manager import ConfigManager

def test_screenshot_directory_is_secure():
    """
    Verify that the screenshot directory is created with restrictive permissions (0o700).
    """
    with tempfile.TemporaryDirectory() as temp_dir:
        config_path = os.path.join(temp_dir, "config.json")

        # Initialize ConfigManager, which triggers _ensure_screenshot_dir
        # We need to mock os.getcwd inside ConfigManager if it's used,
        # but here we pass config_path so config_dir is derived from it.
        cm = ConfigManager(config_path)

        # Get the screenshot directory
        screenshot_dir = cm.get_screenshot_output_dir()

        assert os.path.exists(screenshot_dir), "Screenshot directory should exist"

        # Check permissions
        if os.name == 'posix':
            mode = os.stat(screenshot_dir).st_mode
            permissions = stat.S_IMODE(mode)

            # Check for 0o700 (rwx------)
            # This means NO permissions for group and others
            assert (permissions & 0o077) == 0, f"Permissions too open: {oct(permissions)}"
            # And owner should have rwx
            assert (permissions & 0o700) == 0o700, f"Owner permissions incorrect: {oct(permissions)}"
