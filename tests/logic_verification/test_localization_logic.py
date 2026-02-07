import unittest
from unittest.mock import patch, mock_open
import os
from src.core.localization import LocalizationManager

class TestLocalizationLogic(unittest.TestCase):
    def setUp(self):
        # Reset the singleton instance before each test
        LocalizationManager._instance = None

    def test_load_language_success(self):
        """Test loading a valid language file."""
        with patch("src.core.localization.resource_path") as mock_path, \
             patch("os.path.exists") as mock_exists, \
             patch("os.listdir") as mock_listdir, \
             patch("builtins.open", mock_open(read_data='{"hello": "bonjour"}')):

            mock_path.return_value = "/fake/path"
            mock_exists.return_value = True
            # Return files as if scanning directory
            mock_listdir.return_value = ["fr.json", "en.json"]

            manager = LocalizationManager()
            # Ensure initialization happened
            self.assertTrue(manager.initialized)

            # Load 'fr'
            manager.load_language("fr")

            self.assertEqual(manager.language, "fr")
            self.assertEqual(manager.get("hello"), "bonjour")

    def test_load_language_fallback(self):
        """Test fallback to 'en' when requested language is not available."""
        with patch("src.core.localization.resource_path") as mock_path, \
             patch("os.path.exists") as mock_exists, \
             patch("os.listdir") as mock_listdir, \
             patch("builtins.open", mock_open(read_data='{"hello": "hello"}')):

            mock_path.return_value = "/fake/path"
            mock_exists.return_value = True
            # Only 'en' is available
            mock_listdir.return_value = ["en.json"]

            manager = LocalizationManager()

            # Request 'fr' which is not in available_languages
            manager.load_language("fr")

            self.assertEqual(manager.language, "en")
            self.assertEqual(manager.get("hello"), "hello")

    def test_load_language_file_missing(self):
        """Test handling when the language file itself is missing."""
        with patch("src.core.localization.resource_path") as mock_path, \
             patch("os.path.exists") as mock_exists, \
             patch("os.listdir") as mock_listdir:

            # Use side_effect for resource_path to return different paths
            def path_side_effect(relative_path):
                if "src/assets/lang" in relative_path:
                    if relative_path.endswith(".json"):
                        return f"/fake/path/lang/{os.path.basename(relative_path)}"
                    return "/fake/path/lang"
                return relative_path

            mock_path.side_effect = path_side_effect
            mock_listdir.return_value = ["en.json"]

            # os.path.exists should return True for directory, False for file
            def exists_side_effect(path):
                if path == "/fake/path/lang":
                    return True
                elif path == "/fake/path/lang/en.json":
                    return False
                return False

            mock_exists.side_effect = exists_side_effect

            manager = LocalizationManager()
            manager.load_language("en")

            # Translations should be empty if file load failed/skipped
            self.assertEqual(manager.translations, {})

    def test_load_language_json_error(self):
        """Test handling of malformed JSON in language file."""
        with patch("src.core.localization.resource_path") as mock_path, \
             patch("os.path.exists") as mock_exists, \
             patch("os.listdir") as mock_listdir, \
             patch("builtins.open", mock_open(read_data='invalid json')):

            mock_path.return_value = "/fake/path"
            mock_exists.return_value = True
            mock_listdir.return_value = ["en.json"]

            manager = LocalizationManager()

            # This should catch JSONDecodeError and print error, but not crash
            manager.load_language("en")

            self.assertEqual(manager.translations, {})
