import unittest
import os
import stat
import tempfile
import shutil
from src.core.calibration import CalibrationManager


class TestCalibrationPermissions(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.config_path = os.path.join(self.test_dir, "test_calibration.json")
        self.cm = CalibrationManager(config_filename=self.config_path)

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_calibration_file_permissions(self):
        # Save calibration
        self.cm.save()

        # Verify file exists
        self.assertTrue(os.path.exists(self.config_path))

        # Check permissions
        st = os.stat(self.config_path)
        mode = st.st_mode

        if os.name == "posix":
            # Check for 0o600 (or stricter)
            # This test expects failure if the fix is not applied yet
            # because the current implementation uses default open() permissions
            # which are typically 0o644 or 0o664 depending on umask

            # For reproduction, we can assert that it IS insecure (has group/other read perms)
            # But the goal is to write a test that fails now and passes later.
            # So I will assert the DESIRED state (secure) and expect it to fail.

            self.assertEqual(mode & 0o077, 0, f"File has permissions for group or other: {oct(mode)}")
            # Ensure owner has rw
            self.assertTrue(mode & stat.S_IRUSR, "Owner cannot read")
            self.assertTrue(mode & stat.S_IWUSR, "Owner cannot write")


if __name__ == "__main__":
    unittest.main()
