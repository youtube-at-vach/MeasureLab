
import os
import unittest
from unittest.mock import MagicMock
import pytest

# Skip if PyQt6 is not installed
pytest.importorskip("PyQt6")

try:
    from PyQt6.QtWidgets import QApplication
    # Import the module under test
    # We assume src is in python path or pytest handles it.
    # The original file did sys.path.append(os.getcwd())
    # Pytest usually adds root to path.
    from src.gui.widgets.frequency_counter import FrequencyCounter, FrequencyCounterWidget
except ImportError:
    pytest.skip("Skipping GUI test due to missing dependencies", allow_module_level=True)

# Set environment for headless testing
os.environ["QT_QPA_PLATFORM"] = "offscreen"

class TestFrequencyCounterReset(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Create QApplication if it doesn't exist
        if not QApplication.instance():
            cls.app = QApplication([])
        else:
            cls.app = QApplication.instance()

    def setUp(self):
        self.mock_audio_engine = MagicMock()
        self.mock_audio_engine.sample_rate = 48000
        self.mock_audio_engine.calibration = MagicMock()
        self.mock_audio_engine.calibration.frequency_calibration = 1.0

        self.counter = FrequencyCounter(self.mock_audio_engine)

        # Simulate running state
        self.counter.is_running = True
        self.counter.start_time = 1000.0
        self.counter.freq_history.append(100.0)
        self.counter.time_history.append(0.1)
        self.counter.selected_channel = 0

    def test_reset_state_clears_history(self):
        # Test the reset_state method directly
        self.counter.reset_state()
        self.assertEqual(len(self.counter.freq_history), 0)
        self.assertEqual(len(self.counter.time_history), 0)
        self.assertNotEqual(self.counter.start_time, 1000.0)

    def test_widget_channel_change_resets_history(self):
        # Create widget
        widget = FrequencyCounterWidget(self.counter)

        # Verify initial state (history has 1 item from setUp)
        self.assertEqual(len(self.counter.freq_history), 1)

        # Call on_channel_changed (simulate UI event)
        widget.on_channel_changed(1)

        # Verify channel updated
        self.assertEqual(self.counter.selected_channel, 1)

        # Verify history cleared
        self.assertEqual(len(self.counter.freq_history), 0)

if __name__ == '__main__':
    unittest.main()
