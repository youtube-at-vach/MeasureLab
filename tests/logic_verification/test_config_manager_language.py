import unittest
import tempfile
import os
from unittest.mock import patch, MagicMock
from src.core.config_manager import ConfigManager, WINDOWS_LOCALE_MAP

class TestConfigManagerLanguage(unittest.TestCase):
    def setUp(self):
        # Create a temporary directory for config to avoid side effects
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_path = os.path.join(self.temp_dir.name, "config.json")

        # Create a ConfigManager instance
        # The constructor calls load_config, which might create directories inside temp_dir
        self.cm = ConfigManager(config_path=self.config_path)

        # Ensure we don't accidentally write to disk or create files
        self.cm._flush_config = MagicMock()
        self.cm.logger = MagicMock()

    def tearDown(self):
        self.cm.shutdown()
        self.temp_dir.cleanup()

    @patch('src.core.config_manager.resource_path')
    @patch('src.core.config_manager.os.path.exists')
    @patch('src.core.config_manager.locale.getdefaultlocale')
    @patch('src.core.config_manager.locale.getlocale')
    def test_detect_language_standard(self, mock_get, mock_default, mock_exists, mock_resource_path):
        """Test standard locale detection (e.g., ja_JP -> ja)."""
        mock_get.return_value = ('ja_JP', 'UTF-8')
        # Setup resource_path to return a dummy path
        mock_resource_path.return_value = '/path/to/src/assets/lang/ja.json'
        # Setup exists to return True for this path
        mock_exists.side_effect = lambda p: p == '/path/to/src/assets/lang/ja.json'

        lang = self.cm._detect_system_language()
        self.assertEqual(lang, 'ja')
        mock_resource_path.assert_called_with('src/assets/lang/ja.json')

    @patch('src.core.config_manager.resource_path')
    @patch('src.core.config_manager.os.path.exists')
    @patch('src.core.config_manager.locale.getdefaultlocale')
    @patch('src.core.config_manager.locale.getlocale')
    def test_detect_language_windows(self, mock_get, mock_default, mock_exists, mock_resource_path):
        """Test Windows locale mapping (e.g., Japanese_Japan -> ja)."""
        mock_get.return_value = ('Japanese_Japan', '932')
        mock_resource_path.return_value = '/path/to/src/assets/lang/ja.json'
        mock_exists.side_effect = lambda p: p == '/path/to/src/assets/lang/ja.json'

        lang = self.cm._detect_system_language()
        self.assertEqual(lang, 'ja')

    @patch('src.core.config_manager.resource_path')
    @patch('src.core.config_manager.os.path.exists')
    @patch('src.core.config_manager.locale.getdefaultlocale')
    @patch('src.core.config_manager.locale.getlocale')
    def test_detect_language_windows_english(self, mock_get, mock_default, mock_exists, mock_resource_path):
        """Test Windows locale mapping for English (e.g., English_United States -> en)."""
        mock_get.return_value = ('English_United States', '1252')
        mock_resource_path.return_value = '/path/to/src/assets/lang/en.json'
        mock_exists.side_effect = lambda p: p == '/path/to/src/assets/lang/en.json'

        lang = self.cm._detect_system_language()
        self.assertEqual(lang, 'en')

    @patch('src.core.config_manager.resource_path')
    @patch('src.core.config_manager.os.path.exists')
    @patch('src.core.config_manager.locale.getdefaultlocale')
    @patch('src.core.config_manager.locale.getlocale')
    def test_detect_language_fallback(self, mock_get, mock_default, mock_exists, mock_resource_path):
        """Test fallback to getdefaultlocale when getlocale returns None."""
        mock_get.return_value = (None, None)
        mock_default.return_value = ('fr_FR', 'UTF-8')
        mock_resource_path.return_value = '/path/to/src/assets/lang/fr.json'
        mock_exists.side_effect = lambda p: p == '/path/to/src/assets/lang/fr.json'

        lang = self.cm._detect_system_language()
        self.assertEqual(lang, 'fr')

    @patch('src.core.config_manager.resource_path')
    @patch('src.core.config_manager.os.path.exists')
    @patch('src.core.config_manager.locale.getdefaultlocale')
    @patch('src.core.config_manager.locale.getlocale')
    def test_detect_language_no_locale(self, mock_get, mock_default, mock_exists, mock_resource_path):
        """Test return None when no locale is found."""
        mock_get.return_value = (None, None)
        mock_default.return_value = (None, None)

        lang = self.cm._detect_system_language()
        self.assertIsNone(lang)

    @patch('src.core.config_manager.resource_path')
    @patch('src.core.config_manager.os.path.exists')
    @patch('src.core.config_manager.locale.getdefaultlocale')
    @patch('src.core.config_manager.locale.getlocale')
    def test_detect_language_unsupported(self, mock_get, mock_default, mock_exists, mock_resource_path):
        """Test return None when language file does not exist."""
        mock_get.return_value = ('xx_YY', 'UTF-8')
        mock_resource_path.return_value = '/path/to/src/assets/lang/xx.json'
        mock_exists.return_value = False

        lang = self.cm._detect_system_language()
        self.assertIsNone(lang)

    @patch('src.core.config_manager.resource_path')
    @patch('src.core.config_manager.os.path.exists')
    @patch('src.core.config_manager.locale.getdefaultlocale')
    @patch('src.core.config_manager.locale.getlocale')
    def test_detect_language_exception(self, mock_get, mock_default, mock_exists, mock_resource_path):
        """Test return None on exception."""
        mock_get.side_effect = Exception("Locale error")

        lang = self.cm._detect_system_language()
        self.assertIsNone(lang)
        # Verify logging
        self.cm.logger.warning.assert_called()

    @patch('src.core.config_manager.resource_path')
    @patch('src.core.config_manager.os.path.exists')
    @patch('src.core.config_manager.locale.getdefaultlocale')
    @patch('src.core.config_manager.locale.getlocale')
    def test_detect_language_windows_unmapped(self, mock_get, mock_default, mock_exists, mock_resource_path):
        """Test Windows locale that is not in the map but file exists (fallback logic)."""
        # Assume "Unknown_Region" -> "unknown" -> check "unknown.json"
        mock_get.return_value = ('Unknown_Region', '1252')
        mock_resource_path.return_value = '/path/to/src/assets/lang/unknown.json'
        mock_exists.side_effect = lambda p: p == '/path/to/src/assets/lang/unknown.json'

        lang = self.cm._detect_system_language()
        self.assertEqual(lang, 'unknown')
