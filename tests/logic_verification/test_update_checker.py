
import sys
import unittest
import urllib.error
from unittest.mock import MagicMock, patch

# --- MOCK PYQT6 ---
# We mock PyQt6.QtCore before importing UpdateChecker because it inherits from QThread.
try:
    from PyQt6.QtCore import QCoreApplication, QThread, pyqtSignal
except ImportError:
    # If PyQt6 is not installed, we create mocks

    # Mock QThread
    class MockQThread:
        def __init__(self, parent=None):
            pass
        def start(self):
            self.run()
        def run(self):
            pass
        def wait(self):
            pass

    # Mock pyqtSignal
    class MockSignal:
        def __init__(self, *args):
            self._callbacks = []
        def connect(self, callback):
            self._callbacks.append(callback)
        def emit(self, *args):
            for callback in self._callbacks:
                callback(*args)

    # Setup the mock module structure
    mock_qt_core = MagicMock()
    mock_qt_core.QThread = MockQThread
    mock_qt_core.pyqtSignal = MockSignal

    # QCoreApplication mock
    mock_app = MagicMock()
    mock_app.instance.return_value = MagicMock()
    mock_qt_core.QCoreApplication = mock_app

    # Patch sys.modules
    sys.modules["PyQt6"] = MagicMock()
    sys.modules["PyQt6.QtCore"] = mock_qt_core

    # Now we can import QCoreApplication safely (it will come from our mock)
    # We assign it locally to satisfy the import below if needed, though we imported it inside try block
    QCoreApplication = mock_app

# --- IMPORT MODULE UNDER TEST ---
from src.core.update_checker import UpdateChecker


class TestUpdateChecker(unittest.TestCase):
    def setUp(self):
        # Create a QCoreApplication instance if it doesn't exist
        # With our mock, this just calls the mock.
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

    @patch('builtins.print')
    @patch('urllib.request.urlopen')
    def test_network_error_graceful_handling(self, mock_urlopen, mock_print):
        # Simulate network error
        mock_urlopen.side_effect = urllib.error.URLError("Network unreachable")

        checker = UpdateChecker()

        # Mock signal emission
        signal_mock = MagicMock()
        checker.update_available.connect(signal_mock)

        # Run
        checker.run()

        # Verify signal was not emitted
        signal_mock.assert_not_called()

        # Verify error was logged/printed
        # The code prints f"Update check failed: {e}"
        # str(URLError("Network unreachable")) is "<urlopen error Network unreachable>"
        mock_print.assert_called_with("Update check failed: <urlopen error Network unreachable>")

if __name__ == '__main__':
    unittest.main()
