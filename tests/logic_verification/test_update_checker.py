
import unittest
from unittest.mock import MagicMock, patch

from PyQt6.QtCore import QCoreApplication

from src.core.update_checker import UpdateChecker


class TestUpdateChecker(unittest.TestCase):
    def setUp(self):
        # Create a QCoreApplication instance if it doesn't exist
        if not QCoreApplication.instance():
            self.app = QCoreApplication([])

    def test_version_comparison_newer(self):
        checker = UpdateChecker()
        self.assertTrue(checker._is_newer("0.4.4", "0.4.3"))
        self.assertTrue(checker._is_newer("1.0.0", "0.4.3"))
        self.assertTrue(checker._is_newer("0.4.3.1", "0.4.3"))

    def test_version_comparison_older_or_equal(self):
        checker = UpdateChecker()
        self.assertFalse(checker._is_newer("0.4.3", "0.4.3"))
        self.assertFalse(checker._is_newer("0.4.2", "0.4.3"))
        self.assertFalse(checker._is_newer("0.3.9", "0.4.3"))

    @patch('urllib.request.urlopen')
    def test_update_check_found(self, mock_urlopen):
        # Mock response
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read.return_value = b'{"tag_name": "v9.9.9"}'
        mock_urlopen.return_value.__enter__.return_value = mock_response

        checker = UpdateChecker()

        # Mock signal emission
        signal_mock = MagicMock()
        checker.update_available.connect(signal_mock)

        # Run synchronous for testing (normally runs in thread)
        checker.run()

        signal_mock.assert_called_with("v9.9.9")

    @patch('urllib.request.urlopen')
    def test_update_check_not_found(self, mock_urlopen):
        # Mock response with older version
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read.return_value = b'{"tag_name": "v0.0.1"}'
        mock_urlopen.return_value.__enter__.return_value = mock_response

        checker = UpdateChecker()

        # Mock signal emission
        signal_mock = MagicMock()
        checker.update_available.connect(signal_mock)

        checker.run()

        signal_mock.assert_not_called()

if __name__ == '__main__':
    unittest.main()
