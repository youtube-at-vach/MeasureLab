import unittest
import os
import stat
import tempfile
import shutil
from src.core.config_manager import ConfigManager

class TestConfigPermissions(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.config_path = os.path.join(self.test_dir, "test_config.json")
        self.cm = ConfigManager(config_path=self.config_path)

    def tearDown(self):
        if hasattr(self, 'cm'):
            self.cm.shutdown()
        shutil.rmtree(self.test_dir)

    def test_config_file_permissions(self):
        # Save configuration
        self.cm.save_config(force_sync=True)

        # Verify file exists
        self.assertTrue(os.path.exists(self.config_path))

        # Check permissions
        st = os.stat(self.config_path)
        mode = st.st_mode

        # Ensure only owner has read/write permissions (0o600)
        # On Windows, os.chmod only handles the read-only bit, so 0o600 checks might be platform dependent.
        # However, checking that group/other have NO permissions is the key.

        if os.name == 'posix':
            # Check strictly for 0o600 (or stricter)
            # Mask 0o077 checks for any permission for group/other
            self.assertEqual(mode & 0o077, 0, "File has permissions for group or other")
            # Ensure owner has rw
            self.assertTrue(mode & stat.S_IRUSR, "Owner cannot read")
            self.assertTrue(mode & stat.S_IWUSR, "Owner cannot write")
        else:
            # Windows is tricky with just os.stat.
            # But at least we can check we didn't crash.
            # The requirement specifically mentions 0o600 which implies a Unix-like environment concern
            # but we should still implement best effort.
            pass

if __name__ == '__main__':
    unittest.main()
