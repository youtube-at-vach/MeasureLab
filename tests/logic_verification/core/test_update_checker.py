import sys
import unittest
from unittest.mock import MagicMock, patch

class TestUpdateChecker(unittest.TestCase):
    def setUp(self):
        # Create patches
        self.mock_pyqt_core = MagicMock()
        self.mock_pyqt_modules = {
            "PyQt6": MagicMock(),
            "PyQt6.QtCore": self.mock_pyqt_core,
        }

        # Setup specific mocks on PyQt6.QtCore
        class MockQThread:
            def __init__(self, parent=None): pass
            def start(self): self.run()
            def run(self): pass
            def wait(self): pass

        self.mock_pyqt_core.QThread = MockQThread
        self.mock_signal_instance = MagicMock()
        self.mock_pyqt_core.pyqtSignal = MagicMock(return_value=self.mock_signal_instance)
        self.mock_pyqt_core.QCoreApplication = MagicMock()

        # Start patcher
        self.patcher = patch.dict(sys.modules, self.mock_pyqt_modules)
        self.patcher.start()

        # Import module under test
        if "src.core.update_checker" in sys.modules:
            del sys.modules["src.core.update_checker"]

        import src.core.update_checker
        self.module = src.core.update_checker
        self.UpdateChecker = self.module.UpdateChecker

        # UPDATE_CHECK_URL import
        from src.core.constants import UPDATE_CHECK_URL
        self.UPDATE_CHECK_URL = UPDATE_CHECK_URL

    def tearDown(self):
        self.patcher.stop()
        if "src.core.update_checker" in sys.modules:
            del sys.modules["src.core.update_checker"]

    def test_version_comparison_newer(self):
        checker = self.UpdateChecker()
        self.assertTrue(checker._is_newer("0.4.4", "0.4.3"))
        self.assertTrue(checker._is_newer("1.0.0", "0.4.3"))
        self.assertTrue(checker._is_newer("0.4.3.1", "0.4.3"))

    def test_version_comparison_older_or_equal(self):
        checker = self.UpdateChecker()
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

        checker = self.UpdateChecker()
        # Reset mock on signal (which is self.mock_signal_instance via setUp)
        checker.update_available.emit.reset_mock()

        # Run synchronous for testing
        checker.run()

        # Verify URL usage
        args, _ = mock_urlopen.call_args
        request_obj = args[0]
        self.assertEqual(request_obj.full_url, self.UPDATE_CHECK_URL)

        checker.update_available.emit.assert_called_with("v9.9.9")

    @patch('urllib.request.urlopen')
    def test_update_check_not_found(self, mock_urlopen):
        # Mock response with older version
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read.return_value = b'{"tag_name": "v0.0.1"}'
        mock_urlopen.return_value.__enter__.return_value = mock_response

        checker = self.UpdateChecker()
        checker.update_available.emit.reset_mock()

        checker.run()

        checker.update_available.emit.assert_not_called()

    @patch('urllib.request.urlopen')
    def test_update_check_failure_logs_error(self, mock_urlopen):
        # Mock side effect to raise exception
        mock_urlopen.side_effect = Exception("Network error")

        checker = self.UpdateChecker()

        # Verify logging - logging is imported in update_checker
        # We need to verify logging.getLogger("UpdateChecker").error call
        # Since logging is standard lib, assertLogs should work if logging is configured.
        # But 'src.core.update_checker' imports logging.

        with self.assertLogs('UpdateChecker', level='ERROR') as cm:
            checker.run()

        self.assertTrue(any("Network error" in log for log in cm.output))

if __name__ == '__main__':
    unittest.main()
