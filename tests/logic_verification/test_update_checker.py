import sys
import unittest
from unittest.mock import MagicMock, patch

# Mock PyQt6 modules before importing UpdateChecker
mock_pyqt_core = MagicMock()
sys.modules["PyQt6"] = MagicMock()
sys.modules["PyQt6.QtCore"] = mock_pyqt_core

# Define QThread mock
class MockQThread:
    def __init__(self, parent=None):
        pass
    def start(self):
        self.run()
    def run(self):
        pass
    def wait(self):
        pass

mock_pyqt_core.QThread = MockQThread
# pyqtSignal is called as pyqtSignal(str), so we need it to return a Mock that acts as the signal
mock_signal_instance = MagicMock()
mock_pyqt_core.pyqtSignal = MagicMock(return_value=mock_signal_instance)
mock_pyqt_core.QCoreApplication = MagicMock()

# Now import the module under test
from src.core.update_checker import UpdateChecker  # noqa: E402

class TestUpdateChecker(unittest.TestCase):
    def setUp(self):
        pass

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
        checker.update_available.emit.reset_mock()

        # Run synchronous for testing
        checker.run()

        checker.update_available.emit.assert_called_with("v9.9.9")

    @patch('urllib.request.urlopen')
    def test_update_check_not_found(self, mock_urlopen):
        # Mock response with older version
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read.return_value = b'{"tag_name": "v0.0.1"}'
        mock_urlopen.return_value.__enter__.return_value = mock_response

        checker = UpdateChecker()
        checker.update_available.emit.reset_mock()

        checker.run()

        checker.update_available.emit.assert_not_called()

    @patch('urllib.request.urlopen')
    def test_update_check_failure_logs_error(self, mock_urlopen):
        # Mock side effect to raise exception
        mock_urlopen.side_effect = Exception("Network error")

        checker = UpdateChecker()

        # Verify logging
        with self.assertLogs('UpdateChecker', level='ERROR') as cm:
            checker.run()

        self.assertTrue(any("Network error" in log for log in cm.output))

if __name__ == '__main__':
    unittest.main()
