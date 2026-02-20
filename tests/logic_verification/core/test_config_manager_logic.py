import os
import sys
import shutil
import tempfile
import unittest
import json
from unittest.mock import MagicMock, patch, mock_open
from pathlib import Path

# Adjust path to import src if needed
# Since this file is in tests/logic_verification/core/, we need to go up 3 levels to reach project root.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../")))

# Mock PyQt6 before importing src.core.config_manager
# This allows tests to run in headless environments without PyQt6 installed
sys.modules["PyQt6"] = MagicMock()
sys.modules["PyQt6.QtCore"] = MagicMock()

from src.core.config_manager import ConfigManager, DEFAULT_CONFIG

class TestConfigManagerLogic(unittest.TestCase):
    """
    Consolidated tests for ConfigManager logic including:
    - Merging defaults
    - Loading/Saving
    - Language detection
    - Platform-specific paths
    """

    def setUp(self):
        # Create a temporary directory for config to avoid side effects
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_path = os.path.join(self.temp_dir.name, "config.json")

        # Mock logger to avoid cluttering output
        self.mock_logger = MagicMock()
        self.logger_patcher = patch('src.core.config_manager.logging.getLogger', return_value=self.mock_logger)
        self.logger_patcher.start()

        # Clear singleton instances
        if hasattr(ConfigManager, '_instances'):
            ConfigManager._instances.clear()

    def tearDown(self):
        self.logger_patcher.stop()
        self.temp_dir.cleanup()
        if hasattr(ConfigManager, '_instances'):
            ConfigManager._instances.clear()

    # -------------------------------------------------------------------------
    # Basic Merge Logic (from test_config_manager.py)
    # -------------------------------------------------------------------------

    @patch('src.core.config_manager.ConfigManager._get_default_screenshot_dir', return_value="screenshots")
    def test_merge_with_defaults(self, mock_get_default):
        """Test merging loaded config with defaults."""
        cm = ConfigManager(config_filename=self.config_path)

        # Case: None
        result = cm._merge_with_defaults(None)
        self.assertEqual(result, DEFAULT_CONFIG)
        self.assertIsNot(result, DEFAULT_CONFIG)  # Should return a copy

        # Case: Empty dict
        result = cm._merge_with_defaults({})
        self.assertEqual(result, DEFAULT_CONFIG)

        # Case: Valid audio settings
        loaded = {"audio": {"sample_rate": 96000, "block_size": 2048}}
        result = cm._merge_with_defaults(loaded)
        self.assertEqual(result["audio"]["sample_rate"], 96000)
        self.assertEqual(result["audio"]["block_size"], 2048)
        self.assertEqual(result["audio"]["input_channels"], DEFAULT_CONFIG["audio"]["input_channels"])

        # Case: Partial audio settings
        loaded = {"audio": {"sample_rate": 44100}}
        result = cm._merge_with_defaults(loaded)
        self.assertEqual(result["audio"]["sample_rate"], 44100)
        self.assertEqual(result["audio"]["block_size"], DEFAULT_CONFIG["audio"]["block_size"])

        # Case: Invalid type for section
        loaded = {"audio": [1, 2, 3]}
        result = cm._merge_with_defaults(loaded)
        self.assertEqual(result["audio"], DEFAULT_CONFIG["audio"])

        # Case: Extra keys ignored
        loaded = {"audio": {"sample_rate": 48000, "extra_key": "value"}}
        result = cm._merge_with_defaults(loaded)
        self.assertEqual(result["audio"]["sample_rate"], 48000)
        self.assertNotIn("extra_key", result["audio"])

        # Case: Language
        loaded = {"language": "ja"}
        result = cm._merge_with_defaults(loaded)
        self.assertEqual(result["language"], "ja")

        # Case: Theme
        loaded = {"theme": "dark"}
        result = cm._merge_with_defaults(loaded)
        self.assertEqual(result["theme"], "dark")

        # Case: Screenshot valid
        loaded = {"screenshot": {"output_dir": "custom_screens"}}
        result = cm._merge_with_defaults(loaded)
        self.assertEqual(result["screenshot"]["output_dir"], "custom_screens")

        # Case: Screenshot invalid
        loaded = {"screenshot": "invalid"}
        result = cm._merge_with_defaults(loaded)
        self.assertEqual(result["screenshot"], DEFAULT_CONFIG["screenshot"])

        cm.shutdown()

    @patch('src.core.config_manager.ConfigManager._get_default_screenshot_dir', return_value="screenshots")
    def test_load_config_errors(self, mock_get_default):
        """Test error handling during load_config."""
        cm = ConfigManager(config_filename=self.config_path)

        # Case: Malformed JSON
        with open(self.config_path, "w") as f:
            f.write("{invalid_json")

        config = cm.load_config()
        self.assertEqual(config, DEFAULT_CONFIG)
        # Using mock_logger instead of caplog
        self.mock_logger.error.assert_called()

        # Case: Logic error (mocking _merge_with_defaults to raise TypeError)
        with patch.object(cm, "_merge_with_defaults", side_effect=TypeError("Logic bug")):
            with open(self.config_path, "w") as f:
                f.write("{}")
            with self.assertRaisesRegex(TypeError, "Logic bug"):
                cm.load_config()

        cm.shutdown()

    # -------------------------------------------------------------------------
    # Language Detection (from test_config_manager_language.py)
    # -------------------------------------------------------------------------

    @patch('src.core.config_manager.QLocale')
    @patch('src.core.config_manager.resource_path')
    @patch('src.core.config_manager.os.path.exists')
    @patch('src.core.config_manager.locale.getdefaultlocale')
    @patch('src.core.config_manager.locale.getlocale')
    def test_detect_system_language(self, mock_get, mock_default, mock_exists, mock_resource_path, mock_qlocale):
        """Test system language detection logic."""
        cm = ConfigManager(config_filename=self.config_path)

        # Setup mocks common behavior
        mock_resource_path.side_effect = lambda x: f"/path/to/{x}"

        # Case: Standard locale (ja_JP -> ja)
        mock_qlocale.system.return_value.name.return_value = 'ja_JP'
        mock_get.return_value = ('ja_JP', 'UTF-8')
        mock_exists.side_effect = lambda p: p == '/path/to/src/assets/lang/ja.json'

        lang = cm._detect_system_language()
        self.assertEqual(lang, 'ja')

        # Case: Windows locale mapping (Japanese_Japan -> ja)
        mock_qlocale.system.return_value.name.return_value = 'xx_YY' # Fallback trigger
        mock_get.return_value = ('Japanese_Japan', '932')
        mock_exists.side_effect = lambda p: p == '/path/to/src/assets/lang/ja.json'

        lang = cm._detect_system_language()
        self.assertEqual(lang, 'ja')

        # Case: Fallback to getdefaultlocale
        mock_get.return_value = (None, None)
        mock_default.return_value = ('fr_FR', 'UTF-8')
        mock_exists.side_effect = lambda p: p == '/path/to/src/assets/lang/fr.json'

        lang = cm._detect_system_language()
        self.assertEqual(lang, 'fr')

        # Case: No locale found
        mock_get.return_value = (None, None)
        mock_default.return_value = (None, None)
        mock_exists.return_value = False

        lang = cm._detect_system_language()
        self.assertIsNone(lang)

        # Case: Exception handling
        mock_qlocale.system.side_effect = Exception("Locale error")
        mock_get.side_effect = Exception("Locale error")

        lang = cm._detect_system_language()
        self.assertIsNone(lang)
        self.mock_logger.warning.assert_called()

        cm.shutdown()

    # -------------------------------------------------------------------------
    # Lifecycle & Saving (from test_config_manager_lifecycle.py)
    # -------------------------------------------------------------------------

    @patch('src.core.config_manager.resource_path', side_effect=lambda x: x)
    @patch('src.core.config_manager.os.path.exists')
    @patch('src.core.config_manager.os.makedirs')
    @patch('src.core.config_manager.locale.getlocale')
    @patch('src.core.config_manager.QLocale')
    def test_lifecycle_and_defaults(self, mock_qlocale, mock_getlocale, mock_makedirs, mock_exists, mock_resource_path):
        """Test lifecycle: loading defaults when file missing, auto-detect language."""

        def exists_side_effect(path):
            if path == self.config_path:
                return False
            # Allow language files to "exist"
            if "src/assets/lang" in path:
                return True
            return False
        mock_exists.side_effect = exists_side_effect

        mock_getlocale.return_value = ('en_US', 'UTF-8')
        mock_qlocale.system.return_value.name.return_value = 'en_US'

        cm = ConfigManager(config_filename=self.config_path)

        # Check defaults loaded
        self.assertEqual(cm.config['audio']['sample_rate'], 48000)
        self.assertEqual(cm.config['language'], 'en')

        cm.shutdown()

    @patch('src.core.config_manager.threading.Timer')
    @patch('src.core.config_manager.os.path.exists', return_value=False)
    @patch('src.core.config_manager.os.makedirs')
    def test_save_config_debounced(self, mock_makedirs, mock_exists, mock_timer_cls):
        """Test that save_config starts a timer."""
        cm = ConfigManager(config_filename=self.config_path)
        mock_timer_inst = MagicMock()
        mock_timer_cls.return_value = mock_timer_inst

        cm.save_config(force_sync=False)
        mock_timer_cls.assert_called_with(1.0, cm._flush_config)
        mock_timer_inst.start.assert_called_once()

        cm.save_config(force_sync=False)
        mock_timer_inst.cancel.assert_called_once()
        cm.shutdown()

    @patch('src.core.config_manager.os.path.exists', return_value=False)
    @patch('src.core.config_manager.os.makedirs')
    @patch('src.core.config_manager.os.open')
    @patch('src.core.config_manager.os.fdopen')
    @patch('src.core.config_manager.os.chmod')
    def test_save_config_force_sync(self, mock_chmod, mock_fdopen, mock_open, mock_makedirs, mock_exists):
        """Test that force_sync writes immediately."""
        mock_open.return_value = 123
        mock_file_handle = MagicMock()
        mock_fdopen.return_value.__enter__.return_value = mock_file_handle

        cm = ConfigManager(config_filename=self.config_path)
        cm.config['audio']['sample_rate'] = 88200
        cm.save_config(force_sync=True)

        expected_flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        mock_open.assert_called_with(cm.config_path, expected_flags, 0o600)
        mock_fdopen.assert_called_with(123, 'w')
        mock_chmod.assert_called_with(cm.config_path, 0o600)

        cm.shutdown()

    # -------------------------------------------------------------------------
    # Path Resolution (from test_config_persistence.py)
    # -------------------------------------------------------------------------

    @patch("os.makedirs")
    @patch("sys.platform", "darwin")
    @patch("pathlib.Path.home")
    def test_macos_path_resolution(self, mock_home, mock_makedirs):
        mock_home.return_value = Path("/Users/testuser")

        # Clear existing instance to force re-init with new platform
        ConfigManager._instances.clear()

        cm = ConfigManager() # No filename provided, uses default path logic
        expected_path = "/Users/testuser/Library/Application Support/MeasureLab/config.json"
        self.assertEqual(os.path.abspath(cm.config_path), os.path.abspath(expected_path))

    @patch("os.makedirs")
    @patch("sys.platform", "win32")
    @patch.dict(os.environ, {"APPDATA": r"C:\Users\testuser\AppData\Roaming"})
    @patch("pathlib.Path.home")
    def test_windows_path_resolution(self, mock_home, mock_makedirs):
        mock_home.return_value = Path(r"C:\Users\testuser")

        ConfigManager._instances.clear()

        cm = ConfigManager()
        expected_path = os.path.join(r"C:\Users\testuser\AppData\Roaming", "MeasureLab", "config.json")
        self.assertEqual(os.path.normpath(cm.config_path), os.path.normpath(expected_path))

    @patch("os.makedirs")
    @patch("sys.platform", "linux")
    @patch("pathlib.Path.home")
    def test_linux_path_resolution(self, mock_home, mock_makedirs):
        mock_home.return_value = Path("/home/testuser")

        ConfigManager._instances.clear()

        # Mock XDG_CONFIG_HOME not set
        with patch.dict(os.environ, {}, clear=True):
            cm = ConfigManager()
            expected_path = "/home/testuser/.config/MeasureLab/config.json"
            self.assertEqual(os.path.abspath(cm.config_path), os.path.abspath(expected_path))

    def test_portable_mode(self):
        """Test portable mode detection (config.json in cwd)."""
        # Create a local config file in the current working directory (which is temporarily self.temp_dir in real usage,
        # but here we rely on os.getcwd() unless we change it).
        # We need to switch cwd to self.temp_dir for this test to be safe.

        original_cwd = os.getcwd()
        try:
            os.chdir(self.temp_dir.name)
            with open("config.json", "w") as f:
                json.dump({"test": "value"}, f)

            ConfigManager._instances.clear()
            cm = ConfigManager()

            self.assertEqual(os.path.abspath(cm.config_path), os.path.abspath("config.json"))
            self.assertTrue(os.path.exists(cm.config_path))
        finally:
            os.chdir(original_cwd)

if __name__ == "__main__":
    unittest.main()
