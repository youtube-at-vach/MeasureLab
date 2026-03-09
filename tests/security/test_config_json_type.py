import unittest
import os
import json
import tempfile
import shutil
from src.core.config_manager import ConfigManager

class TestConfigJsonType(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.config_path = os.path.join(self.test_dir, "test_config.json")

    def tearDown(self):
        ConfigManager._instances.clear()
        shutil.rmtree(self.test_dir)

    def test_load_config_with_list(self):
        with open(self.config_path, "w") as f:
            json.dump(["invalid", "config", "format"], f)

        cm = ConfigManager(config_filename=self.config_path)

        # Should gracefully fallback to default dict structure
        self.assertIsInstance(cm.config, dict)
        self.assertIn("audio", cm.config)

        cm.shutdown()

    def test_load_config_with_string(self):
        with open(self.config_path, "w") as f:
            json.dump("just a string", f)

        cm = ConfigManager(config_filename=self.config_path)

        # Should gracefully fallback to default dict structure
        self.assertIsInstance(cm.config, dict)
        self.assertIn("audio", cm.config)

        cm.shutdown()

if __name__ == '__main__':
    unittest.main()
