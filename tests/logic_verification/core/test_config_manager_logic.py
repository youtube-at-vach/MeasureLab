import os
import sys
import tempfile
import unittest
import json
from unittest.mock import MagicMock, patch
from pathlib import Path

# Adjust path to import src if needed
# Since this file is in tests/logic_verification/core/, we need to go up 3 levels to reach project root.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../")))


class TestConfigManagerLogic(unittest.TestCase):
    """
    Consolidated tests for ConfigManager logic including:
    - Merging defaults
    - Loading/Saving
    - Language detection
    - Platform-specific paths
    """

    def setUp(self):
        # Patch sys.modules to mock PyQt6 dependencies BEFORE importing ConfigManager
        self.modules_patcher = patch.dict(sys.modules, {"PyQt6": MagicMock(), "PyQt6.QtCore": MagicMock()})
        self.modules_patcher.start()

        # Import ConfigManager inside setUp to ensure mocks are active
        # and avoid top-level import errors or linter E402
        from src.core.config_manager import ConfigManager, DEFAULT_CONFIG

        self.ConfigManager = ConfigManager
        self.DEFAULT_CONFIG = DEFAULT_CONFIG

        # Create a temporary directory for config to avoid side effects
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_path = os.path.join(self.temp_dir.name, "config.json")

        # Mock logger to avoid cluttering output
        self.mock_logger = MagicMock()
        self.logger_patcher = patch("src.core.config_manager.logging.getLogger", return_value=self.mock_logger)
        self.logger_patcher.start()

        # Clear singleton instances
        if hasattr(self.ConfigManager, "_instances"):
            self.ConfigManager._instances.clear()

    def tearDown(self):
        self.logger_patcher.stop()
        self.temp_dir.cleanup()
        if hasattr(self.ConfigManager, "_instances"):
            self.ConfigManager._instances.clear()

        # Stop module patching
        self.modules_patcher.stop()

    # -------------------------------------------------------------------------
    # Basic Merge Logic (from test_config_manager.py)
    # -------------------------------------------------------------------------

    @patch("src.core.config_manager.ConfigManager._get_default_screenshot_dir", return_value="screenshots")
    def test_merge_with_defaults(self, mock_get_default):
        """Test merging loaded config with defaults."""
        cm = self.ConfigManager(config_filename=self.config_path)

        # Case: None
        result = cm._merge_with_defaults(None)
        self.assertEqual(result, self.DEFAULT_CONFIG)
        self.assertIsNot(result, self.DEFAULT_CONFIG)  # Should return a copy

        # Case: Empty dict
        result = cm._merge_with_defaults({})
        self.assertEqual(result, self.DEFAULT_CONFIG)

        # Case: Valid audio settings
        loaded = {"audio": {"sample_rate": 96000, "block_size": 2048}}
        result = cm._merge_with_defaults(loaded)
        self.assertEqual(result["audio"]["sample_rate"], 96000)
        self.assertEqual(result["audio"]["block_size"], 2048)
        self.assertEqual(result["audio"]["input_channels"], self.DEFAULT_CONFIG["audio"]["input_channels"])

        # Case: Partial audio settings
        loaded = {"audio": {"sample_rate": 44100}}
        result = cm._merge_with_defaults(loaded)
        self.assertEqual(result["audio"]["sample_rate"], 44100)
        self.assertEqual(result["audio"]["block_size"], self.DEFAULT_CONFIG["audio"]["block_size"])

        # Case: Invalid type for section
        loaded = {"audio": [1, 2, 3]}
        result = cm._merge_with_defaults(loaded)
        self.assertEqual(result["audio"], self.DEFAULT_CONFIG["audio"])

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
        self.assertEqual(result["screenshot"], self.DEFAULT_CONFIG["screenshot"])

        cm.shutdown()

    @patch("src.core.config_manager.ConfigManager._get_default_screenshot_dir", return_value="screenshots")
    def test_load_config_errors(self, mock_get_default):
        """Test error handling during load_config."""
        cm = self.ConfigManager(config_filename=self.config_path)

        # Case: Malformed JSON
        with open(self.config_path, "w") as f:
            f.write("{invalid_json")

        config = cm.load_config()
        self.assertEqual(config, self.DEFAULT_CONFIG)
        # Using mock_logger instead of caplog
        self.mock_logger.error.assert_called()

        # Case: Logic error (mocking _merge_with_defaults to raise TypeError)
        with patch.object(cm, "_merge_with_defaults", side_effect=TypeError("Logic bug")):
            with open(self.config_path, "w") as f:
                f.write("{}")
            with self.assertRaisesRegex(TypeError, "Logic bug"):
                cm.load_config()

        cm.shutdown()

    def test_audio_engine_64bit_settings(self):
        """Test getting and setting the 64-bit audio engine configuration."""
        cm = self.ConfigManager(config_filename=self.config_path)

        # Mock save_config so we don't write to disk repeatedly
        cm.save_config = MagicMock()

        # Check default value (should be False unless DEFAULT_CONFIG changes)
        self.assertFalse(cm.is_audio_engine_64bit())

        # Enable 64-bit engine
        cm.set_audio_engine_64bit(True)
        self.assertTrue(cm.is_audio_engine_64bit())
        self.assertTrue(cm.config["audio"]["audio_engine_64bit"])
        cm.save_config.assert_called_once()

        # Disable 64-bit engine
        cm.save_config.reset_mock()
        cm.set_audio_engine_64bit(False)
        self.assertFalse(cm.is_audio_engine_64bit())
        self.assertFalse(cm.config["audio"]["audio_engine_64bit"])
        cm.save_config.assert_called_once()

        # Edge case: "audio" key is missing
        cm.save_config.reset_mock()
        del cm.config["audio"]
        cm.set_audio_engine_64bit(True)
        self.assertIn("audio", cm.config)
        self.assertTrue(cm.config["audio"]["audio_engine_64bit"])
        self.assertTrue(cm.is_audio_engine_64bit())
        cm.save_config.assert_called_once()

        cm.shutdown()

    # -------------------------------------------------------------------------
    # Language Detection (from test_config_manager_language.py)
    # -------------------------------------------------------------------------

    @patch("src.core.config_manager.ConfigManager.save_config")
    def test_set_language(self, mock_save_config):
        """Test setting the language updates the config and calls save_config."""
        cm = self.ConfigManager(config_filename=self.config_path)

        mock_save_config.reset_mock()

        cm.set_language("fr")

        self.assertEqual(cm.config["language"], "fr")
        self.assertEqual(cm.get_language(), "fr")
        mock_save_config.assert_called_once()

        cm.shutdown()

    @patch("src.core.config_manager.QLocale")
    @patch("src.core.config_manager.resource_path")
    @patch("src.core.config_manager.os.path.exists")
    @patch("src.core.config_manager.locale.getlocale")
    def test_detect_system_language(self, mock_get, mock_exists, mock_resource_path, mock_qlocale):
        """Test system language detection logic."""
        cm = self.ConfigManager(config_filename=self.config_path)

        # Setup mocks common behavior
        mock_resource_path.side_effect = lambda x: f"/path/to/{x}"

        # Case: Standard locale (ja_JP -> ja)
        mock_qlocale.system.return_value.name.return_value = "ja_JP"
        mock_get.return_value = ("ja_JP", "UTF-8")
        mock_exists.side_effect = lambda p: p == "/path/to/src/assets/lang/ja.json"

        lang = cm._detect_system_language()
        self.assertEqual(lang, "ja")

        # Case: Windows locale mapping (Japanese_Japan -> ja)
        mock_qlocale.system.return_value.name.return_value = "xx_YY"  # Fallback trigger
        mock_get.return_value = ("Japanese_Japan", "932")
        mock_exists.side_effect = lambda p: p == "/path/to/src/assets/lang/ja.json"

        lang = cm._detect_system_language()
        self.assertEqual(lang, "ja")

        # Case: Fallback to POSIX locale environment
        mock_get.return_value = (None, None)
        mock_exists.side_effect = lambda p: p == "/path/to/src/assets/lang/fr.json"

        with patch.dict("src.core.config_manager.os.environ", {"LANG": "fr_FR.UTF-8"}, clear=True):
            lang = cm._detect_system_language()
        self.assertEqual(lang, "fr")

        # Case: No locale found
        mock_get.return_value = (None, None)
        mock_exists.return_value = False

        with patch.dict("src.core.config_manager.os.environ", {}, clear=True):
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

    @patch("src.core.config_manager.resource_path", side_effect=lambda x: x)
    @patch("src.core.config_manager.os.path.exists")
    @patch("src.core.config_manager.os.makedirs")
    @patch("src.core.config_manager.locale.getlocale")
    @patch("src.core.config_manager.QLocale")
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

        mock_getlocale.return_value = ("en_US", "UTF-8")
        mock_qlocale.system.return_value.name.return_value = "en_US"

        cm = self.ConfigManager(config_filename=self.config_path)

        # Check defaults loaded
        self.assertEqual(cm.config["audio"]["sample_rate"], 48000)
        self.assertEqual(cm.config["language"], "en")

        cm.shutdown()

    @patch("src.core.config_manager.threading.Timer")
    @patch("src.core.config_manager.os.path.exists", return_value=False)
    @patch("src.core.config_manager.os.makedirs")
    def test_save_config_debounced(self, mock_makedirs, mock_exists, mock_timer_cls):
        """Test that save_config starts a timer."""
        cm = self.ConfigManager(config_filename=self.config_path)
        mock_timer_inst = MagicMock()
        mock_timer_cls.return_value = mock_timer_inst

        cm.save_config(force_sync=False)
        mock_timer_cls.assert_called_with(1.0, cm._flush_config)
        mock_timer_inst.start.assert_called_once()

        cm.save_config(force_sync=False)
        mock_timer_inst.cancel.assert_called_once()
        cm.shutdown()

    @patch("src.core.config_manager.os.path.exists", return_value=False)
    @patch("src.core.config_manager.os.makedirs")
    @patch("src.core.config_manager.os.open")
    @patch("src.core.config_manager.os.fdopen")
    @patch("src.core.config_manager.os.chmod")
    @patch("builtins.hasattr", return_value=False)
    def test_save_config_force_sync(
        self, mock_hasattr, mock_chmod, mock_fdopen, mock_open_func, mock_makedirs, mock_exists
    ):
        """Test that force_sync writes immediately."""
        mock_open_func.return_value = 123
        mock_file_handle = MagicMock()
        mock_fdopen.return_value.__enter__.return_value = mock_file_handle

        cm = self.ConfigManager(config_filename=self.config_path)
        cm.config["audio"]["sample_rate"] = 88200
        cm.save_config(force_sync=True)

        expected_flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        mock_open_func.assert_called_with(cm.config_path, expected_flags, 0o600)
        mock_fdopen.assert_called_with(123, "w")
        mock_chmod.assert_called_with(cm.config_path, 0o600)

        cm.shutdown()

    # -------------------------------------------------------------------------
    # Path Resolution (from test_config_persistence.py)
    # -------------------------------------------------------------------------

    def test_get_app_root_dir(self):
        """Test getting the application root directory."""
        # Case 1: Running from source (sys.frozen is False or not present)
        # Mock sys.frozen to be False just in case
        with patch.object(sys, "frozen", False, create=True):
            # Since get_app_root_dir uses __file__ of config_manager.py (which is in src/core)
            # and goes 2 levels up, the expected result is the project root.
            # We can mock __file__ to control the output deterministically.
            mock_file_path = os.path.abspath(os.path.join("fake", "project", "src", "core", "config_manager.py"))
            expected_dir = os.path.dirname(os.path.dirname(os.path.dirname(mock_file_path)))
            with patch("src.core.config_manager.__file__", mock_file_path):
                actual_dir = os.path.normpath(self.ConfigManager.get_app_root_dir())
                self.assertEqual(actual_dir, expected_dir)

        # Case 2: Running from PyInstaller (sys.frozen is True)
        with patch.object(sys, "frozen", True, create=True):
            mock_executable = os.path.abspath(os.path.join("fake", "path", "to", "executable", "app.exe"))
            expected_dir = os.path.dirname(mock_executable)
            with patch.object(sys, "executable", mock_executable):
                actual_dir = os.path.normpath(self.ConfigManager.get_app_root_dir())
                self.assertEqual(actual_dir, expected_dir)

    @patch("os.makedirs")
    @patch("sys.platform", "darwin")
    @patch("pathlib.Path.home")
    def test_macos_path_resolution(self, mock_home, mock_makedirs):
        mock_home.return_value = Path("/Users/testuser")

        # Clear existing instance to force re-init with new platform
        self.ConfigManager._instances.clear()

        cm = self.ConfigManager()  # No filename provided, uses default path logic
        expected_path = "/Users/testuser/Library/Application Support/MeasureLab/config.json"
        self.assertEqual(os.path.abspath(cm.config_path), os.path.abspath(expected_path))

    @patch("os.makedirs")
    @patch("sys.platform", "win32")
    @patch.dict(os.environ, {"APPDATA": r"C:\Users\testuser\AppData\Roaming"})
    @patch("pathlib.Path.home")
    def test_windows_path_resolution(self, mock_home, mock_makedirs):
        mock_home.return_value = Path(r"C:\Users\testuser")

        self.ConfigManager._instances.clear()

        cm = self.ConfigManager()
        expected_path = os.path.join(r"C:\Users\testuser\AppData\Roaming", "MeasureLab", "config.json")
        self.assertEqual(os.path.normpath(cm.config_path), os.path.normpath(expected_path))

    @patch("os.makedirs")
    @patch("sys.platform", "linux")
    @patch("pathlib.Path.home")
    def test_linux_path_resolution(self, mock_home, mock_makedirs):
        mock_home.return_value = Path("/home/testuser")

        self.ConfigManager._instances.clear()

        # Mock XDG_CONFIG_HOME not set
        with patch.dict(os.environ, {}, clear=True):
            cm = self.ConfigManager()
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

            self.ConfigManager._instances.clear()
            cm = self.ConfigManager()

            self.assertEqual(os.path.abspath(cm.config_path), os.path.abspath("config.json"))
            self.assertTrue(os.path.exists(cm.config_path))
        finally:
            os.chdir(original_cwd)

    def test_coreaudio_conversion_quality_settings(self):
        """Test getting and setting the CoreAudio conversion quality."""
        cm = self.ConfigManager(config_filename=self.config_path)

        # Mock save_config
        cm.save_config = MagicMock()

        # Check default value (should be 'min' as per DEFAULT_CONFIG)
        self.assertEqual(cm.get_coreaudio_conversion_quality(), "min")

        # Enable setting
        cm.set_coreaudio_conversion_quality("max")
        self.assertEqual(cm.get_coreaudio_conversion_quality(), "max")
        self.assertEqual(cm.config["audio"]["coreaudio_conversion_quality"], "max")
        cm.save_config.assert_called_once()

        # Edge case: "audio" key is missing
        cm.save_config.reset_mock()
        del cm.config["audio"]

        # Test getting without audio config (should fallback to default)
        self.assertEqual(cm.get_coreaudio_conversion_quality(), "min")

        # Test setting without audio config
        cm.set_coreaudio_conversion_quality("normal")
        self.assertIn("audio", cm.config)
        self.assertEqual(cm.config["audio"]["coreaudio_conversion_quality"], "normal")
        self.assertEqual(cm.get_coreaudio_conversion_quality(), "normal")
        cm.save_config.assert_called_once()

        cm.shutdown()

    def test_is_dithering_enabled(self):
        """Test checking if audio dithering is enabled."""
        cm = self.ConfigManager(config_filename=self.config_path)

        # Default is False
        self.assertFalse(cm.is_dithering_enabled())

        # Test returning True
        cm.config["audio"]["dithering_enabled"] = True
        self.assertTrue(cm.is_dithering_enabled())

        # Test returning False
        cm.config["audio"]["dithering_enabled"] = False
        self.assertFalse(cm.is_dithering_enabled())

        # Test with missing 'audio' section (should default to False)
        if "audio" in cm.config:
            del cm.config["audio"]
        self.assertFalse(cm.is_dithering_enabled())

        cm.shutdown()

    def test_set_dithering_enabled(self):
        """Test enabling and disabling dithering updates the config."""
        cm = self.ConfigManager(config_filename=self.config_path)

        # Test setting True
        cm.set_dithering_enabled(True)
        self.assertTrue(cm.config["audio"]["dithering_enabled"])

        # Test setting False
        cm.set_dithering_enabled(False)
        self.assertFalse(cm.config["audio"]["dithering_enabled"])

        # Test with missing 'audio' section
        if "audio" in cm.config:
            del cm.config["audio"]

        cm.set_dithering_enabled(True)
        self.assertTrue(cm.config["audio"]["dithering_enabled"])

        cm.shutdown()

    @patch("src.core.config_manager.ConfigManager.save_config")
    @patch("src.core.config_manager.ConfigManager._ensure_screenshot_dir")
    def test_set_screenshot_output_dir(self, mock_ensure, mock_save):
        """Test setting the screenshot output directory updates the config."""
        cm = self.ConfigManager(config_filename=self.config_path)

        # Ensure starting state
        self.assertIn("screenshot", cm.config)

        # Test setting a new directory
        cm.set_screenshot_output_dir("/new/screenshot/path")
        self.assertEqual(cm.config["screenshot"]["output_dir"], "/new/screenshot/path")
        mock_ensure.assert_called_with(cm.config)
        mock_save.assert_called()

        # Test with missing 'screenshot' section
        del cm.config["screenshot"]

        mock_ensure.reset_mock()
        mock_save.reset_mock()

        cm.set_screenshot_output_dir("another/path")
        self.assertIn("screenshot", cm.config)
        self.assertEqual(cm.config["screenshot"]["output_dir"], "another/path")
        mock_ensure.assert_called_with(cm.config)
        mock_save.assert_called()

        # Test with invalid 'screenshot' section (not a dict)
        cm.config["screenshot"] = "invalid_string"

        mock_ensure.reset_mock()
        mock_save.reset_mock()

        cm.set_screenshot_output_dir("fallback/path")
        self.assertIsInstance(cm.config["screenshot"], dict)
        self.assertEqual(cm.config["screenshot"]["output_dir"], "fallback/path")
        mock_ensure.assert_called_with(cm.config)
        mock_save.assert_called()

        cm.shutdown()


if __name__ == "__main__":
    unittest.main()
