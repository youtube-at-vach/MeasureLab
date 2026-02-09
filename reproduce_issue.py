import os
import shutil
import tempfile
import stat
import sys

# Ensure src is in python path
sys.path.append(os.getcwd())

from src.core.config_manager import ConfigManager

def test_screenshot_dir_permissions():
    print(f"Testing screenshot directory permissions...")
    with tempfile.TemporaryDirectory() as temp_dir:
        config_path = os.path.join(temp_dir, "config.json")
        try:
            cm = ConfigManager(config_path)
        except Exception as e:
            print(f"Error initializing ConfigManager: {e}")
            return

        # Check default screenshot dir
        screenshot_dir = os.path.join(temp_dir, "screenshots")
        if not os.path.exists(screenshot_dir):
            print("Screenshot directory not created")
            return

        mode = os.stat(screenshot_dir).st_mode
        permissions = stat.S_IMODE(mode)

        print(f"Permissions: {oct(permissions)}")

        # Check if group or others have any permission
        # 0o077 mask checks for any permission for group or others
        if (permissions & 0o077) != 0:
            print("VULNERABLE: Permissions are too open (group/world accessible).")
        else:
            print("SECURE: Permissions are restricted (owner only).")

if __name__ == "__main__":
    test_screenshot_dir_permissions()
