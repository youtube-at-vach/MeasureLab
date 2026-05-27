import unittest
from unittest.mock import patch, mock_open, MagicMock

from src.core.localization import LocalizationManager, tr, get_manager


class TestLocalizationManager(unittest.TestCase):
    """Test the LocalizationManager functionality."""

    @patch("src.core.localization.resource_path")
    @patch("os.path.exists")
    @patch("os.listdir")
    def test_initialization_and_scan(self, mock_listdir, mock_exists, mock_resource_path):
        """Test that LocalizationManager scans the correct directory and handles files properly."""
        mock_resource_path.return_value = "/fake/lang/path"
        mock_exists.return_value = True
        mock_listdir.return_value = ["en.json", "jp.json", "ignore.txt"]

        manager = LocalizationManager()

        self.assertEqual(manager.language, "en")
        self.assertIn("en", manager.available_languages)
        self.assertIn("jp", manager.available_languages)
        self.assertNotIn("ignore", manager.available_languages)
        self.assertEqual(manager.available_languages["en"], "en.json")
        self.assertEqual(manager.available_languages["jp"], "jp.json")

    @patch("src.core.localization.resource_path")
    @patch("os.path.exists")
    def test_missing_directory_fallback(self, mock_exists, mock_resource_path):
        """Test fallback behavior when the translation directory does not exist."""
        mock_resource_path.return_value = "/fake/lang/path"
        mock_exists.return_value = False

        manager = LocalizationManager()

        # Should automatically fall back to providing 'en'
        self.assertIn("en", manager.available_languages)
        self.assertEqual(manager.available_languages["en"], "en.json")
        self.assertEqual(len(manager.available_languages), 1)

    @patch("src.core.localization.resource_path")
    @patch("os.path.exists")
    @patch("os.listdir")
    def test_load_language_success(self, mock_listdir, mock_exists, mock_resource_path):
        """Test loading a valid language updates translations and sets current language."""
        mock_resource_path.side_effect = lambda x: x
        mock_exists.return_value = True
        mock_listdir.return_value = ["en.json", "fr.json"]

        mock_json_content = '{"greeting": "bonjour"}'

        with patch("builtins.open", mock_open(read_data=mock_json_content)):
            manager = LocalizationManager()
            manager.load_language("fr")

            self.assertEqual(manager.language, "fr")
            self.assertEqual(manager.translations, {"greeting": "bonjour"})

    @patch("src.core.localization.resource_path")
    @patch("os.path.exists")
    @patch("os.listdir")
    def test_load_language_fallback(self, mock_listdir, mock_exists, mock_resource_path):
        """Test loading an unavailable language defaults back to English."""
        mock_resource_path.side_effect = lambda x: x
        mock_exists.return_value = True
        mock_listdir.return_value = ["en.json"]

        mock_json_content = '{"greeting": "hello"}'

        with patch("builtins.open", mock_open(read_data=mock_json_content)):
            manager = LocalizationManager()
            manager.load_language("jp")  # jp is not in listdir

            self.assertEqual(manager.language, "en")
            self.assertEqual(manager.translations, {"greeting": "hello"})

    @patch("src.core.localization.resource_path")
    @patch("os.path.exists")
    @patch("os.listdir")
    def test_load_language_invalid_json(self, mock_listdir, mock_exists, mock_resource_path):
        """Test behavior when the language JSON file contains invalid data."""
        mock_resource_path.side_effect = lambda x: x
        mock_exists.return_value = True
        mock_listdir.return_value = ["en.json"]

        # Provide invalid JSON
        mock_json_content = '{"greeting": "hello"'

        with patch("builtins.open", mock_open(read_data=mock_json_content)):
            manager = LocalizationManager()

            with patch.object(manager.logger, "error") as mock_error:
                manager.load_language("en")

                self.assertEqual(manager.translations, {})
                self.assertTrue(mock_error.called)
                args, _ = mock_error.call_args
                self.assertIn("Failed to load language en", args[0])

    @patch("src.core.localization.resource_path")
    @patch("os.path.exists")
    def test_get_translation(self, mock_exists, mock_resource_path):
        mock_exists.return_value = False
        """Test fetching a translation key."""
        manager = LocalizationManager()
        manager.translations = {"title": "Application Title", "version": "1.0"}

        # Existing key
        self.assertEqual(manager.get("title"), "Application Title")
        # Missing key, no default
        self.assertEqual(manager.get("missing_key"), "missing_key")
        # Missing key, with default
        self.assertEqual(manager.get("missing_key", "Default Value"), "Default Value")

    @patch("src.core.localization.get_manager")
    def test_global_tr_function(self, mock_get_manager):
        """Test the global tr() shortcut delegates to the manager properly."""
        from unittest.mock import MagicMock

        mock_manager = MagicMock()
        mock_manager.get.side_effect = lambda k, d=None: (
            "test_value" if k == "test_key" else (d if d is not None else k)
        )
        mock_get_manager.return_value = mock_manager

        self.assertEqual(tr("test_key"), "test_value")
        self.assertEqual(tr("nonexistent"), "nonexistent")
        self.assertEqual(tr("nonexistent", "fallback"), "fallback")

        self.assertEqual(mock_get_manager.call_count, 3)

    def test_get_manager_function(self):
        """Test the get_manager() global shortcut."""
        from src.core.localization import _loc_manager

        self.assertIs(get_manager(), _loc_manager)

    @patch("src.core.localization.get_manager")
    def test_tr_exception_propagation(self, mock_get_manager):
        """Test that exceptions in the manager are propagated by the tr() shortcut."""
        mock_manager = MagicMock()
        mock_manager.get.side_effect = Exception("Mocked error")
        mock_get_manager.return_value = mock_manager

        from src.core.localization import tr

        with self.assertRaises(Exception) as context:
            tr("key")
        self.assertEqual(str(context.exception), "Mocked error")

    @patch("src.core.localization._loc_manager.get", side_effect=Exception("Manager failed"))
    def test_get_manager_exception_propagation(self, mock_get):
        """Test that get_manager() correctly returns the manager even if its methods would fail,
        and that subsequent calls on it propagate the exception."""
        from src.core.localization import get_manager

        manager = get_manager()
        self.assertIsNotNone(manager)

        with self.assertRaises(Exception) as context:
            manager.get("key")
        self.assertEqual(str(context.exception), "Manager failed")


if __name__ == "__main__":
    unittest.main()
