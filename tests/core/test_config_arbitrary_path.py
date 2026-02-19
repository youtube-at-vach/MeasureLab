
import sys
import os
import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from src.core.config_manager import ConfigManager

class TestConfigArbitraryScreenshotPath(unittest.TestCase):
    def setUp(self):
        ConfigManager._instances.clear()

    @patch('os.makedirs')
    @patch('src.core.config_manager.ConfigManager.save_config')
    def test_arbitrary_path_allowed(self, mock_save, mock_makedirs):
        # Setup a dummy config manager
        with patch('os.path.exists', return_value=True), \
             patch('builtins.open', unittest.mock.mock_open(read_data='{}')):
            config_mgr = ConfigManager("dummy_config.json")
        
        # Test setting a path outside the config directory
        target_path = os.path.abspath(os.path.join(os.getcwd(), '..', 'ExternalScreenshots'))
        
        # Determine strict config dir for comparison
        config_dir = os.path.dirname(os.path.abspath("dummy_config.json"))
        
        # Verify that this path WOULD have triggered path traversal in the old logic
        # logic: commonpath([config_dir, target_path]) != config_dir
        # This is just to confirm our test case is valid for the bug report
        try:
            if os.path.commonpath([config_dir, target_path]) == config_dir:
                print("Warning: Test path is inside config dir, not testing traversal expection!")
        except Exception:
            pass # ValueError is expected if paths are on different drives on Windows, etc.

        # Set the path
        config_mgr.set_screenshot_output_dir(target_path)
        
        # precise check of stored config
        self.assertEqual(config_mgr.config["screenshot"]["output_dir"], target_path)
        
        # check getter
        retrieved_path = config_mgr.get_screenshot_output_dir()
        self.assertEqual(retrieved_path, target_path)

if __name__ == '__main__':
    unittest.main()
