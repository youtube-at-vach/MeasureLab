import sys
import os
import unittest
from unittest.mock import MagicMock

# Set offscreen
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

# Mock sounddevice BEFORE importing any module that uses it
mock_sd = MagicMock()
sys.modules['sounddevice'] = mock_sd

# Add src to path
sys.path.insert(0, os.getcwd())

from PyQt6.QtWidgets import QApplication  # noqa: E402
from PyQt6.QtGui import QCloseEvent  # noqa: E402
from src.gui.widgets.oscilloscope import Oscilloscope, OscilloscopeWidget  # noqa: E402

class TestOscilloscopeCleanup(unittest.TestCase):
    def setUp(self):
        # Ensure QApplication exists
        self.app = QApplication.instance()
        if self.app is None:
            self.app = QApplication(sys.argv)

        self.mock_engine = MagicMock()
        self.mock_engine.sample_rate = 48000
        # Mock register_callback to return a dummy ID
        self.mock_engine.register_callback.return_value = 123

        self.module = Oscilloscope(self.mock_engine)
        self.widget = OscilloscopeWidget(self.module)

    def test_cleanup_on_close(self):
        # Start analysis
        self.module.start_analysis()
        self.widget.timer.start()

        # Verify running
        self.assertTrue(self.module.is_running)
        self.assertTrue(self.widget.timer.isActive())

        # Create a mock CloseEvent
        event = QCloseEvent()

        # Call closeEvent
        try:
            self.widget.closeEvent(event)
        except Exception as e:
            print(f"closeEvent raised: {e}")

        # Check if stopped
        self.assertFalse(self.module.is_running, "Module should stop running after closeEvent")
        self.assertFalse(self.widget.timer.isActive(), "Timer should stop after closeEvent")

if __name__ == '__main__':
    unittest.main()
