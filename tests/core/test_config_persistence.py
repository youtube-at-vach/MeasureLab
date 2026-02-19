
import os
import sys
import unittest
from unittest.mock import patch, MagicMock
import json
import shutil
import tempfile
from pathlib import Path

# Adjust path to import src
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from src.core.config_manager import ConfigManager

class TestConfigPersistence(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.original_cwd = os.getcwd()
        os.chdir(self.test_dir)

        # Clear singleton instances
        ConfigManager._instances.clear()

    def tearDown(self):
        os.chdir(self.original_cwd)
        shutil.rmtree(self.test_dir)
        ConfigManager._instances.clear()

    @patch("os.makedirs")
    @patch("sys.platform", "darwin")
    @patch("pathlib.Path.home")
    def test_macos_path_resolution(self, mock_home, mock_makedirs):
        mock_home.return_value = Path("/Users/testuser")

        # Case 1: No local config, should use user data dir
        cm = ConfigManager()
        expected_path = "/Users/testuser/Library/Application Support/MeasureLab/config.json"
        self.assertEqual(os.path.abspath(cm.config_path), os.path.abspath(expected_path))

    @patch("os.makedirs")
    @patch("sys.platform", "win32")
    @patch.dict(os.environ, {"APPDATA": r"C:\Users\testuser\AppData\Roaming"})
    @patch("pathlib.Path.home")
    def test_windows_path_resolution(self, mock_home, mock_makedirs):
        mock_home.return_value = Path(r"C:\Users\testuser")

        cm = ConfigManager()
        # Use os.path.join to match the behavior of the code running on the host OS
        expected_path = os.path.join(r"C:\Users\testuser\AppData\Roaming", "MeasureLab", "config.json")

        # Normalize paths for comparison (handle separators)
        self.assertEqual(os.path.normpath(cm.config_path), os.path.normpath(expected_path))

    @patch("os.makedirs")
    @patch("sys.platform", "linux")
    @patch("pathlib.Path.home")
    def test_linux_path_resolution(self, mock_home, mock_makedirs):
        mock_home.return_value = Path("/home/testuser")

        # Mock XDG_CONFIG_HOME not set
        with patch.dict(os.environ, {}, clear=True):
            cm = ConfigManager()
            expected_path = "/home/testuser/.config/MeasureLab/config.json"
            self.assertEqual(os.path.abspath(cm.config_path), os.path.abspath(expected_path))

    def test_portable_mode(self):
        # Create a local config file
        with open("config.json", "w") as f:
            json.dump({"test": "value"}, f)

        cm = ConfigManager()
        self.assertEqual(os.path.abspath(cm.config_path), os.path.abspath("config.json"))
        self.assertTrue(os.path.exists(cm.config_path))

    @patch("src.core.config_manager.QLocale")
    @patch("src.core.config_manager.os.path.exists") # Mock resource check
    def test_locale_detection_qlocale(self, mock_exists, mock_qlocale):
        # Mock QLocale system
        mock_system = MagicMock()
        mock_system.name.return_value = "ja_JP"
        mock_qlocale.system.return_value = mock_system

        # Mock resource_path check to return True for 'ja'
        def side_effect(path):
            if "ja.json" in path:
                return True
            return False
        mock_exists.side_effect = side_effect

        cm = ConfigManager()
        # Should detect 'ja'
        self.assertEqual(cm._detect_system_language(), "ja")

if __name__ == "__main__":
    unittest.main()
