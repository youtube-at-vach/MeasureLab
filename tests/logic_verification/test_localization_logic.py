import unittest
from unittest.mock import patch, mock_open
from src.core.localization import LocalizationManager, tr, get_manager

class TestLocalizationManager(unittest.TestCase):
    def setUp(self):
        # Reset the singleton instance before each test
        LocalizationManager._instance = None
        # Reset the global manager if it was created
        # Note: The module level _loc_manager is created on import.
        # We can't easily reset that without reloading the module,
        # but we can reset the class instance to verify new creations.

    def test_singleton(self):
        """Test that LocalizationManager is a singleton."""
        with patch("src.core.localization.resource_path") as mock_path, \
             patch("os.path.exists") as mock_exists, \
             patch("os.listdir") as mock_listdir:

            mock_path.return_value = "/fake/path"
            mock_exists.return_value = True
            mock_listdir.return_value = []

            m1 = LocalizationManager()
            m2 = LocalizationManager()
            self.assertIs(m1, m2)
            self.assertTrue(m1.initialized)

    def test_init_scans_directory(self):
        """Test that available languages are scanned correctly."""
        with patch("src.core.localization.resource_path") as mock_path, \
             patch("os.path.exists") as mock_exists, \
             patch("os.listdir") as mock_listdir:

            mock_path.return_value = "/fake/path/lang"
            mock_exists.return_value = True
            mock_listdir.return_value = ["en.json", "fr.json", "es.txt"]

            manager = LocalizationManager()

            self.assertIn("en", manager.available_languages)
            self.assertIn("fr", manager.available_languages)
            self.assertNotIn("es", manager.available_languages)
            self.assertEqual(manager.available_languages["en"], "en.json")
            self.assertEqual(manager.available_languages["fr"], "fr.json")

    def test_init_handles_missing_directory(self):
        """Test behavior when the language directory does not exist."""
        with patch("src.core.localization.resource_path") as mock_path, \
             patch("os.path.exists") as mock_exists:

            mock_path.return_value = "/fake/path/lang"
            mock_exists.return_value = False # Directory missing

            manager = LocalizationManager()

            # Should still have 'en' as fallback
            self.assertIn("en", manager.available_languages)
            self.assertEqual(manager.available_languages["en"], "en.json")

    def test_load_language_success(self):
        """Test loading a valid language file."""
        with patch("src.core.localization.resource_path") as mock_path, \
             patch("os.path.exists") as mock_exists, \
             patch("os.listdir") as mock_listdir, \
             patch("builtins.open", mock_open(read_data='{"hello": "bonjour"}')):

            mock_path.side_effect = lambda x: f"/fake/{x}"
            # Mock directory exists for init
            # Mock file exists for load_language
            mock_exists.return_value = True
            mock_listdir.return_value = ["fr.json", "en.json"]

            manager = LocalizationManager()
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
            # Only 'en' is available in list
            mock_listdir.return_value = ["en.json"]

            manager = LocalizationManager()
            # Request 'fr' which is not in available_languages
            manager.load_language("fr")

            self.assertEqual(manager.language, "en")
            self.assertEqual(manager.get("hello"), "hello")

    def test_load_language_file_missing(self):
        """Test handling when the language file itself is missing (e.g. deleted after scan)."""
        with patch("src.core.localization.resource_path") as mock_path, \
             patch("os.path.exists") as mock_exists, \
             patch("os.listdir") as mock_listdir:

            # Ensure resource_path reflects file extension logic
            mock_path.side_effect = lambda x: f"/fake/{x}"
            mock_listdir.return_value = ["en.json"]

            # Mock exists: True for directory, False for file
            def exists_side_effect(path):
                if path.endswith(".json"):
                    return False
                return True
            mock_exists.side_effect = exists_side_effect

            manager = LocalizationManager()
            manager.load_language("en")

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

            # Patch the instance logger's error method
            with patch.object(manager.logger, 'error') as mock_error:
                # Should catch JSONDecodeError and log error
                manager.load_language("en")
                self.assertEqual(manager.translations, {})

                # Verify logger.error was called with error message
                self.assertTrue(mock_error.called)
                args, _ = mock_error.call_args
                self.assertIn("Failed to load language en", args[0])

    def test_get_existing_key(self):
        """Test retrieving an existing key."""
        with patch("src.core.localization.resource_path"), \
             patch("os.path.exists"), \
             patch("os.listdir"):

            manager = LocalizationManager()
            manager.translations = {"key": "value"}

            self.assertEqual(manager.get("key"), "value")

    def test_get_missing_key_default(self):
        """Test retrieving a missing key with a default value."""
        with patch("src.core.localization.resource_path"), \
             patch("os.path.exists"), \
             patch("os.listdir"):

            manager = LocalizationManager()
            manager.translations = {}

            self.assertEqual(manager.get("missing", "default"), "default")

    def test_get_missing_key_no_default(self):
        """Test retrieving a missing key without a default value returns the key."""
        with patch("src.core.localization.resource_path"), \
             patch("os.path.exists"), \
             patch("os.listdir"):

            manager = LocalizationManager()
            manager.translations = {}

            self.assertEqual(manager.get("missing"), "missing")

    def test_tr_function(self):
        """Test the global tr helper function."""
        # tr uses the global _loc_manager instance.
        # We need to ensure that global instance has our translations.
        # But _loc_manager is instantiated at import time.
        # We can inject translations into it.
        from src.core.localization import _loc_manager

        original_translations = _loc_manager.translations
        try:
            _loc_manager.translations = {"hello": "world"}
            self.assertEqual(tr("hello"), "world")
            self.assertEqual(tr("missing"), "missing")
        finally:
            _loc_manager.translations = original_translations

    def test_get_manager_function(self):
        """Test the get_manager helper function."""
        from src.core.localization import _loc_manager
        self.assertIs(get_manager(), _loc_manager)

if __name__ == "__main__":
    unittest.main()
