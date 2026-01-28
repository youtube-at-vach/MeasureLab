import sys
import os
import unittest
from unittest.mock import MagicMock, patch

# Set offscreen
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

# Mock sounddevice BEFORE importing any module that uses it
if 'sounddevice' in sys.modules:
    del sys.modules['sounddevice']
mock_sd = MagicMock()
sys.modules['sounddevice'] = mock_sd

from PyQt6.QtWidgets import QApplication  # noqa: E402

# Ensure src is in path
sys.path.insert(0, os.getcwd())

from src.gui.widgets.linearity_analyzer import LinearityAnalyzer, LinearityAnalyzerWidget  # noqa: E402

class TestLinearityAnalyzerError(unittest.TestCase):
    def setUp(self):
        self.app = QApplication.instance()
        if self.app is None:
            self.app = QApplication(sys.argv)

        self.mock_engine = MagicMock()
        self.mock_engine.sample_rate = 48000
        # Mock calibration
        self.mock_engine.calibration = MagicMock()

        self.module = LinearityAnalyzer(self.mock_engine)
        self.widget = LinearityAnalyzerWidget(self.module)

    def test_error_message_box(self):
        # Patch QMessageBox.critical where it will be used (or generally in QtWidgets)
        with patch('PyQt6.QtWidgets.QMessageBox.critical') as mock_critical:
            test_msg = "Test Error Message"
            self.widget.on_error(test_msg)

            # Assert that critical was called
            mock_critical.assert_called()

            # Check arguments
            # Signature: critical(parent, title, text, ...)
            args, _ = mock_critical.call_args
            self.assertEqual(args[0], self.widget)
            self.assertIn("Error", args[1])
            self.assertIn(test_msg, args[2])

if __name__ == '__main__':
    unittest.main()
