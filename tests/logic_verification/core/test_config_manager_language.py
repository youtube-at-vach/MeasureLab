import unittest
import tempfile
import os
from unittest.mock import patch, MagicMock
from src.core.config_manager import ConfigManager

class TestConfigManagerLanguage(unittest.TestCase):
    def setUp(self):
        # Create a temporary directory for config to avoid side effects
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_path = os.path.join(self.temp_dir.name, "config.json")

        # Create a ConfigManager instance
        # The constructor calls load_config, which might create directories inside temp_dir
        self.cm = ConfigManager(config_filename=self.config_path)

        # Ensure we don't accidentally write to disk or create files
        self.cm._flush_config = MagicMock()
        self.cm.logger = MagicMock()

    def tearDown(self):
        self.cm.shutdown()
        self.temp_dir.cleanup()

    @patch('src.core.config_manager.QLocale')
    @patch('src.core.config_manager.resource_path')
    @patch('src.core.config_manager.os.path.exists')
    @patch('src.core.config_manager.locale.getdefaultlocale')
    @patch('src.core.config_manager.locale.getlocale')
    def test_detect_language_standard(self, mock_get, mock_default, mock_exists, mock_resource_path, mock_qlocale):
        """Test standard locale detection (e.g., ja_JP -> ja)."""
        # Mock QLocale to match standard locale expectation or fail to fallback
        # Here we want to test that if QLocale works, it returns 'ja'
        mock_qlocale.system.return_value.name.return_value = 'ja_JP'
        mock_get.return_value = ('ja_JP', 'UTF-8')
        # Use side_effect for resource_path to differentiate calls
        mock_resource_path.side_effect = lambda x: f"/path/to/{x}"
        # Setup exists to return True for this path
        mock_exists.side_effect = lambda p: p == '/path/to/src/assets/lang/ja.json'

        lang = self.cm._detect_system_language()
        self.assertEqual(lang, 'ja')
        mock_resource_path.assert_called_with('src/assets/lang/ja.json')

    @patch('src.core.config_manager.QLocale')
    @patch('src.core.config_manager.resource_path')
    @patch('src.core.config_manager.os.path.exists')
    @patch('src.core.config_manager.locale.getdefaultlocale')
    @patch('src.core.config_manager.locale.getlocale')
    def test_detect_language_windows(self, mock_get, mock_default, mock_exists, mock_resource_path, mock_qlocale):
        """Test Windows locale mapping (e.g., Japanese_Japan -> ja)."""
        # Return a dummy locale from QLocale that won't be found, triggering fallback
        mock_qlocale.system.return_value.name.return_value = 'xx_YY'
        mock_get.return_value = ('Japanese_Japan', '932')
        mock_resource_path.side_effect = lambda x: f"/path/to/{x}"
        mock_exists.side_effect = lambda p: p == '/path/to/src/assets/lang/ja.json'

        lang = self.cm._detect_system_language()
        self.assertEqual(lang, 'ja')

    @patch('src.core.config_manager.QLocale')
    @patch('src.core.config_manager.resource_path')
    @patch('src.core.config_manager.os.path.exists')
    @patch('src.core.config_manager.locale.getdefaultlocale')
    @patch('src.core.config_manager.locale.getlocale')
    def test_detect_language_windows_english(self, mock_get, mock_default, mock_exists, mock_resource_path, mock_qlocale):
        """Test Windows locale mapping for English (e.g., English_United States -> en)."""
        # Return a dummy locale from QLocale that won't be found
        mock_qlocale.system.return_value.name.return_value = 'xx_YY'
        mock_get.return_value = ('English_United States', '1252')
        mock_resource_path.side_effect = lambda x: f"/path/to/{x}"
        mock_exists.side_effect = lambda p: p == '/path/to/src/assets/lang/en.json'

        lang = self.cm._detect_system_language()
        self.assertEqual(lang, 'en')

    @patch('src.core.config_manager.QLocale')
    @patch('src.core.config_manager.resource_path')
    @patch('src.core.config_manager.os.path.exists')
    @patch('src.core.config_manager.locale.getdefaultlocale')
    @patch('src.core.config_manager.locale.getlocale')
    def test_detect_language_fallback(self, mock_get, mock_default, mock_exists, mock_resource_path, mock_qlocale):
        """Test fallback to getdefaultlocale when getlocale returns None."""
        # Return a dummy locale from QLocale that won't be found
        mock_qlocale.system.return_value.name.return_value = 'xx_YY'
        mock_get.return_value = (None, None)
        mock_default.return_value = ('fr_FR', 'UTF-8')
        mock_resource_path.side_effect = lambda x: f"/path/to/{x}"
        mock_exists.side_effect = lambda p: p == '/path/to/src/assets/lang/fr.json'

        lang = self.cm._detect_system_language()
        self.assertEqual(lang, 'fr')

    @patch('src.core.config_manager.QLocale')
    @patch('src.core.config_manager.resource_path')
    @patch('src.core.config_manager.os.path.exists')
    @patch('src.core.config_manager.locale.getdefaultlocale')
    @patch('src.core.config_manager.locale.getlocale')
    def test_detect_language_no_locale(self, mock_get, mock_default, mock_exists, mock_resource_path, mock_qlocale):
        """Test return None when no locale is found."""
        # Return a dummy locale from QLocale that won't be found
        mock_qlocale.system.return_value.name.return_value = 'xx_YY'
        mock_get.return_value = (None, None)
        mock_default.return_value = (None, None)
        # Ensure exists returns False
        mock_exists.return_value = False

        lang = self.cm._detect_system_language()
        self.assertIsNone(lang)

    @patch('src.core.config_manager.QLocale')
    @patch('src.core.config_manager.resource_path')
    @patch('src.core.config_manager.os.path.exists')
    @patch('src.core.config_manager.locale.getdefaultlocale')
    @patch('src.core.config_manager.locale.getlocale')
    def test_detect_language_unsupported(self, mock_get, mock_default, mock_exists, mock_resource_path, mock_qlocale):
        """Test return None when language file does not exist."""
        # Force QLocale to fail (or return the unsupported one)
        mock_qlocale.system.side_effect = Exception("QLocale missing")
        mock_get.return_value = ('xx_YY', 'UTF-8')
        mock_resource_path.side_effect = lambda x: f"/path/to/{x}"
        mock_exists.return_value = False

        lang = self.cm._detect_system_language()
        self.assertIsNone(lang)

    @patch('src.core.config_manager.QLocale')
    @patch('src.core.config_manager.resource_path')
    @patch('src.core.config_manager.os.path.exists')
    @patch('src.core.config_manager.locale.getdefaultlocale')
    @patch('src.core.config_manager.locale.getlocale')
    def test_detect_language_exception(self, mock_get, mock_default, mock_exists, mock_resource_path, mock_qlocale):
        """Test return None on exception."""
        # Force everything to fail
        mock_qlocale.system.side_effect = Exception("Locale error")
        # Ensure fallback also fails
        mock_get.side_effect = Exception("Locale error")

        lang = self.cm._detect_system_language()
        self.assertIsNone(lang)
        # Verify logging
        self.cm.logger.warning.assert_called()

    @patch('src.core.config_manager.QLocale')
    @patch('src.core.config_manager.resource_path')
    @patch('src.core.config_manager.os.path.exists')
    @patch('src.core.config_manager.locale.getdefaultlocale')
    @patch('src.core.config_manager.locale.getlocale')
    def test_detect_language_windows_unmapped(self, mock_get, mock_default, mock_exists, mock_resource_path, mock_qlocale):
        """Test Windows locale that is not in the map but file exists (fallback logic)."""
        # Return a dummy locale from QLocale that won't be found
        mock_qlocale.system.return_value.name.return_value = 'xx_YY'
        # Assume "Unknown_Region" -> "unknown" -> check "unknown.json"
        mock_get.return_value = ('Unknown_Region', '1252')
        mock_resource_path.side_effect = lambda x: f"/path/to/{x}"
        mock_exists.side_effect = lambda p: p == '/path/to/src/assets/lang/unknown.json'

        lang = self.cm._detect_system_language()
        self.assertEqual(lang, 'unknown')
