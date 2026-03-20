import json
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
        self.assertFalse(is_newer_version("not.a.version", "0.4.3"))
        self.assertFalse(is_newer_version("v1.a.b", "0.4.3"))


class TestUpdateChecker(unittest.TestCase):
    def setUp(self):
        self.checker = UpdateChecker()

    @patch('requests.get')
    def test_update_check_found(self, mock_get):
        # Mock response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"version": "9.9.9"}
        mock_get.return_value = mock_response

        # Connect a mock slot to the signal
        mock_slot = MagicMock()
        self.checker.update_available.connect(mock_slot)

        # Run synchronous for testing
        self.checker.run()

        # Verify URL usage
        args, _ = mock_get.call_args
        self.assertEqual(args[0], UPDATE_CHECK_URL)

        # Verify signal emission
        mock_slot.assert_called_once_with("v9.9.9")

    @patch('requests.get')
    def test_update_check_not_found(self, mock_get):
        # Mock response with older version
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"version": "0.0.1"}
        mock_get.return_value = mock_response

        mock_slot = MagicMock()
        self.checker.update_available.connect(mock_slot)

        self.checker.run()

        mock_slot.assert_not_called()

    @patch('requests.get')
    def test_update_check_failure_logs_error(self, mock_get):
        # Mock side effect to raise exception
        mock_get.side_effect = Exception("Network error")

        # Verify logging
        with self.assertLogs('UpdateChecker', level='ERROR') as cm:
            self.checker.run()

        self.assertTrue(any("Network error" in log for log in cm.output))

    @patch('requests.get')
    def test_update_check_invalid_json(self, mock_get):
        # Mock response with invalid JSON
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.side_effect = json.JSONDecodeError("Expecting ',' delimiter", '{"version": "9.9.9"', 19)
        mock_get.return_value = mock_response

        # Verify logging
        with self.assertLogs('UpdateChecker', level='ERROR') as cm:
            self.checker.run()

        self.assertTrue(any("Update check failed" in log for log in cm.output))
        self.assertTrue(any("Expecting ',' delimiter" in log or "Unterminated string" in log or "Expecting property name" in log or "JSONDecodeError" in log for log in cm.output))

    @patch('requests.get')
    def test_update_check_non_200_status(self, mock_get):
        # Mock response with non-200 status
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.json.side_effect = Exception("Should not decode JSON")
        mock_get.return_value = mock_response

        mock_slot = MagicMock()
        self.checker.update_available.connect(mock_slot)

        self.checker.run()

        mock_slot.assert_not_called()

    def test_deprecated_is_newer(self):
        # Test the deprecated wrapper method to ensure it calls is_newer_version correctly
        self.assertTrue(self.checker._is_newer("0.4.4", "0.4.3"))
        self.assertFalse(self.checker._is_newer("0.4.3", "0.4.4"))
        self.assertFalse(self.checker._is_newer("not.a.version", "0.4.3"))


if __name__ == '__main__':
    unittest.main()
