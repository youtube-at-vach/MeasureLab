
import sys
import unittest
from unittest.mock import MagicMock, patch
import pytest

# Skip if PyQt6 is not installed
pytest.importorskip("PyQt6")

class TestFrequencyCounterUIStructure(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Patch sounddevice and soundfile specifically for this test class context
        # We use a patcher to ensure it's reversible
        cls.modules_patcher = patch.dict(sys.modules, {
            "sounddevice": MagicMock(),
            "soundfile": MagicMock()
        })
        cls.modules_patcher.start()

        # Import modules AFTER patching
        try:
            from PyQt6.QtWidgets import QApplication, QLabel, QPushButton, QTabWidget
            from src.gui.widgets.frequency_counter import FrequencyCounter, FrequencyCounterWidget

            # Store imported classes on the class instance
            cls.QApplication = QApplication
            cls.QLabel = QLabel
            cls.QPushButton = QPushButton
            cls.QTabWidget = QTabWidget
            cls.FrequencyCounter = FrequencyCounter
            cls.FrequencyCounterWidget = FrequencyCounterWidget

            # Create QApplication if it doesn't exist
            if not QApplication.instance():
                cls.app = QApplication([])
            else:
                cls.app = QApplication.instance()

        except ImportError:
            cls.modules_patcher.stop()
            raise unittest.SkipTest("Missing dependencies")

    @classmethod
    def tearDownClass(cls):
        # Stop the patcher to restore original modules
        if hasattr(cls, 'modules_patcher'):
            cls.modules_patcher.stop()

    def setUp(self):
        self.mock_audio_engine = MagicMock()
        self.mock_audio_engine.sample_rate = 48000
        self.mock_audio_engine.calibration = MagicMock()
        self.mock_audio_engine.calibration.frequency_calibration = 1.0

        # Use the locally imported class refs
        self.counter = self.FrequencyCounter(self.mock_audio_engine)
        self.widget = self.FrequencyCounterWidget(self.counter)

    def test_ui_components_exist(self):
        """Verify that essential UI components are created."""
        self.assertIsInstance(self.widget.freq_label, self.QLabel)
        self.assertIsInstance(self.widget.amp_label, self.QLabel)
        self.assertIsInstance(self.widget.run_btn, self.QPushButton)
        self.assertIsInstance(self.widget.tab_widget, self.QTabWidget)

        # Check specific text to ensure they are the right labels
        self.assertIn("Hz", self.widget.freq_label.text())
        self.assertIn("dBFS", self.widget.amp_label.text())
        self.assertEqual(self.widget.run_btn.text(), "Start")

    def test_tabs_exist(self):
        """Verify that the tabs are correctly added."""
        self.assertEqual(self.widget.tab_widget.count(), 3)
        self.assertEqual(self.widget.tab_widget.tabText(0), "Frequency Drift")
        self.assertEqual(self.widget.tab_widget.tabText(1), "Allan Deviation")
        self.assertEqual(self.widget.tab_widget.tabText(2), "Jitter Histogram")

    def test_controls_exist(self):
        """Verify that control widgets exist."""
        self.assertTrue(hasattr(self.widget, "gate_spin"))
        self.assertTrue(hasattr(self.widget, "ch_combo"))
        self.assertTrue(hasattr(self.widget, "speed_combo"))
        self.assertTrue(hasattr(self.widget, "display_combo"))
        self.assertTrue(hasattr(self.widget, "cal_btn"))

    def test_display_frame_is_in_layout(self):
        """Verify that the display frame (containing frequency label) is added to the main layout."""
        # The freq_label is inside a QFrame, which should be in the main layout.
        # Find the frame that contains the freq_label
        freq_label_parent = self.widget.freq_label.parent()
        self.assertIsNotNone(freq_label_parent)

        # Check if this parent (the QFrame) is in the main layout
        layout = self.widget.layout()
        self.assertIsNotNone(layout)

        # Check if the frame is a child of the widget's layout
        index = layout.indexOf(freq_label_parent)
        self.assertNotEqual(index, -1, "Display frame not found in main layout")

if __name__ == '__main__':
    unittest.main()
