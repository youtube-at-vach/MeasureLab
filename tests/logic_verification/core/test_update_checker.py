import unittest
from unittest.mock import MagicMock, patch
from src.core.update_checker import UpdateChecker, is_newer_version
from src.core.constants import UPDATE_CHECK_URL


class TestVersionComparison(unittest.TestCase):
    def test_version_newer(self):
        self.assertTrue(is_newer_version("0.4.4", "0.4.3"))
        self.assertTrue(is_newer_version("1.0.0", "0.4.3"))
        self.assertTrue(is_newer_version("0.4.3.1", "0.4.3"))

    def test_version_older_or_equal(self):
        self.assertFalse(is_newer_version("0.4.3", "0.4.3"))
        self.assertFalse(is_newer_version("0.4.2", "0.4.3"))
        self.assertFalse(is_newer_version("0.3.9", "0.4.3"))

    def test_invalid_version_string(self):
        # Should return False on ValueError
        self.assertFalse(is_newer_version("invalid", "0.4.3"))
        self.assertFalse(is_newer_version("0.4.3", "invalid"))


class TestUpdateChecker(unittest.TestCase):
    def setUp(self):
        self.checker = UpdateChecker()

    @patch('urllib.request.urlopen')
    def test_update_check_found(self, mock_urlopen):
        # Mock response
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read.return_value = b'{"tag_name": "v9.9.9"}'
        mock_urlopen.return_value.__enter__.return_value = mock_response

        # Connect a mock slot to the signal
        mock_slot = MagicMock()
        self.checker.update_available.connect(mock_slot)

        # Run synchronous for testing
        self.checker.run()

        # Verify URL usage
        args, _ = mock_urlopen.call_args
        request_obj = args[0]
        self.assertEqual(request_obj.full_url, UPDATE_CHECK_URL)

        # Verify signal emission
        mock_slot.assert_called_once_with("v9.9.9")

    @patch('urllib.request.urlopen')
    def test_update_check_not_found(self, mock_urlopen):
        # Mock response with older version
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read.return_value = b'{"tag_name": "v0.0.1"}'
        mock_urlopen.return_value.__enter__.return_value = mock_response

        mock_slot = MagicMock()
        self.checker.update_available.connect(mock_slot)

        self.checker.run()

        mock_slot.assert_not_called()

    @patch('urllib.request.urlopen')
    def test_update_check_failure_logs_error(self, mock_urlopen):
        # Mock side effect to raise exception
        mock_urlopen.side_effect = Exception("Network error")

        # Verify logging
        with self.assertLogs('UpdateChecker', level='ERROR') as cm:
            self.checker.run()

        self.assertTrue(any("Network error" in log for log in cm.output))


if __name__ == '__main__':
    unittest.main()
