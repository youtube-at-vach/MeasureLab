import unittest
from unittest.mock import patch
import os
import sys

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from src.core.config_manager import ConfigManager

class TestConfigAutoDetect(unittest.TestCase):
    def setUp(self):
        self.test_config_path = "test_config_autodetect.json"
        if os.path.exists(self.test_config_path):
            os.remove(self.test_config_path)

    def tearDown(self):
        if os.path.exists(self.test_config_path):
            os.remove(self.test_config_path)

    @patch('src.core.config_manager.locale.getlocale')
    @patch('src.core.config_manager.locale.getdefaultlocale')
    def test_detect_ja(self, mock_def_locale, mock_locale):
        # Mock system returning Japanese
        mock_locale.return_value = ('ja_JP', 'UTF-8')
        mock_def_locale.return_value = ('ja_JP', 'UTF-8')

        cm = ConfigManager(self.test_config_path)
        self.assertEqual(cm.get_language(), 'ja')

        # Verify it persisted to memory only (until saved, but logic says it returns config)
        # The current implementation returns the config dict with "language": "ja"
        # ConfigManager.__init__ sets self.config = self.load_config()

    @patch('src.core.config_manager.locale.getlocale')
    @patch('src.core.config_manager.locale.getdefaultlocale')
    def test_detect_en(self, mock_def_locale, mock_locale):
        # Mock system returning English
        mock_locale.return_value = ('en_US', 'UTF-8')
        mock_def_locale.return_value = ('en_US', 'UTF-8')

        cm = ConfigManager(self.test_config_path)
        self.assertEqual(cm.get_language(), 'en')

    @patch('src.core.config_manager.locale.getlocale')
    @patch('src.core.config_manager.locale.getdefaultlocale')
    def test_detect_unsupported(self, mock_def_locale, mock_locale):
        # Mock system returning Italian (unsupported in our list presumably)
        # Note: We rely on actual file existence in src/assets/lang
        # If 'it' doesn't exist, it should fallback to default 'en'
        mock_locale.return_value = ('it_IT', 'UTF-8')
        mock_def_locale.return_value = ('it_IT', 'UTF-8')

        cm = ConfigManager(self.test_config_path)
        # Should remain default 'en'
        self.assertEqual(cm.get_language(), 'en')

    @patch('src.core.config_manager.locale.getlocale')
    def test_no_override_existing(self, mock_locale):
        # Create a config file with 'fr'
        with open(self.test_config_path, 'w') as f:
            f.write('{"language": "fr"}')

        # Mock system as 'ja'
        mock_locale.return_value = ('ja_JP', 'UTF-8')

        cm = ConfigManager(self.test_config_path)
        # Should respect file 'fr', ignoring system 'ja'
        self.assertEqual(cm.get_language(), 'fr')

if __name__ == '__main__':
    unittest.main()
