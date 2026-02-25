import importlib
import sys
import unittest
from unittest.mock import MagicMock, patch
from src.core.constants import UPDATE_CHECK_URL  # noqa: E402

class TestUpdateChecker(unittest.TestCase):
    def setUp(self):
        # Create mocks
        self.mock_pyqt_core = MagicMock()
        self.mock_pyqt6 = MagicMock()

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

        self.mock_pyqt_core.QThread = MockQThread
        self.mock_pyqt_core.QCoreApplication = MagicMock()

        # Mock pyqtSignal
        mock_signal_instance = MagicMock()
        self.mock_pyqt_core.pyqtSignal = MagicMock(return_value=mock_signal_instance)

        self.modules_patcher = patch.dict(sys.modules, {
            "PyQt6": self.mock_pyqt6,
            "PyQt6.QtCore": self.mock_pyqt_core
        })
        self.modules_patcher.start()

        # Import/Reload module under test
        import src.core.update_checker
        importlib.reload(src.core.update_checker)
        self.UpdateChecker = src.core.update_checker.UpdateChecker

    def tearDown(self):
        self.modules_patcher.stop()
        # Clean up imported module to avoid stale mocks
        if 'src.core.update_checker' in sys.modules:
            # We can either reload it with real modules (if they existed) or leave it
            # But since we patched sys.modules, the 'real' PyQt6 might be back.
            # Ideally, reload it again so it picks up the real PyQt6 if needed.
            # However, for this test suite, avoiding side effects is key.
            pass

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
        checker.update_available.emit.reset_mock()

        # Run synchronous for testing
        checker.run()

        # Verify URL usage
        args, _ = mock_urlopen.call_args
        request_obj = args[0]
        self.assertEqual(request_obj.full_url, UPDATE_CHECK_URL)

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

        # Verify logging
        with self.assertLogs('UpdateChecker', level='ERROR') as cm:
            checker.run()

        self.assertTrue(any("Network error" in log for log in cm.output))

if __name__ == '__main__':
    unittest.main()
