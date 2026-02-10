import sys
import unittest
from unittest.mock import MagicMock, patch
import importlib
import numpy as np

# Define a dummy QWidget to serve as base class
class DummyQWidget:
    def __init__(self, *args, **kwargs):
        pass

    def __getattr__(self, name):
        return MagicMock()

    def __call__(self, *args, **kwargs):
        return MagicMock()

class TestOscilloscopePersistence(unittest.TestCase):
    def setUp(self):
        # Create a mock module for QtWidgets
        mock_qt_widgets = MagicMock()
        mock_qt_widgets.QWidget = DummyQWidget

        # Patch modules
        self.patched_modules = {
            "PyQt6.QtCore": MagicMock(),
            "PyQt6.QtGui": MagicMock(),
            "PyQt6.QtWidgets": mock_qt_widgets,
            "pyqtgraph": MagicMock(),
            "sounddevice": MagicMock(),
        }
        self.original_modules = {}
        for name, mock in self.patched_modules.items():
            if name in sys.modules:
                self.original_modules[name] = sys.modules[name]
            sys.modules[name] = mock

        # Mock QRectF specifically
        rect_side_effect = lambda x, y, w, h: (x, y, w, h)
        self.patched_modules["PyQt6.QtCore"].QRectF = MagicMock(side_effect=rect_side_effect)
        self.patched_modules["pyqtgraph"].QtCore.QRectF = MagicMock(side_effect=rect_side_effect)

        # Ensure Qt constants are available
        self.patched_modules["PyQt6.QtCore"].Qt.PenStyle.DotLine = 1
        self.patched_modules["PyQt6.QtCore"].Qt.Orientation.Horizontal = 1

        # Import module under test
        import src.gui.widgets.oscilloscope
        importlib.reload(src.gui.widgets.oscilloscope)
        self.oscilloscope_module = src.gui.widgets.oscilloscope

        # Setup mocks for dependencies
        self.mock_audio_engine = MagicMock()
        self.mock_audio_engine.sample_rate = 48000
        self.mock_audio_engine.calibration.input_sensitivity = 1.0

        # Create module instance
        self.osc_logic = self.oscilloscope_module.Oscilloscope(self.mock_audio_engine)

        # Instantiate Widget
        self.osc_widget = self.oscilloscope_module.OscilloscopeWidget(self.osc_logic)

        # Configure mocks to prevent crashes
        self.osc_widget.cursor_1.value.return_value = 0.0
        self.osc_widget.cursor_2.value.return_value = 0.0

    def tearDown(self):
        # Restore modules
        for name in self.patched_modules:
            if name in self.original_modules:
                sys.modules[name] = self.original_modules[name]
            else:
                del sys.modules[name]

    def test_persistence_set_rect_update(self):
        # Enable persistence
        self.osc_logic.persistence_mode = True
        self.osc_logic.heatmap_l = np.zeros((600, 400))
        self.osc_logic.heatmap_r = np.zeros((600, 400))
        self.osc_logic.is_running = True
        self.osc_logic.heatmap_size = (600, 400)

        # Mock get_display_data to return some data
        self.osc_logic.get_display_data = MagicMock(return_value=np.zeros((480, 2)))

        # Mock process_queue
        self.osc_logic.process_queue = MagicMock()

        # Set timebase to 10ms
        self.osc_logic.timebase = 0.01

        # Call update_plot
        self.osc_widget.update_plot()

        # Check setRect call
        self.osc_widget.persistence_img.setRect.assert_called_with((0, -1.1, 0.01, 2.2))

        # Change timebase to 20ms
        self.osc_logic.timebase = 0.02
        self.osc_logic.get_display_data.return_value = np.zeros((960, 2))

        # Call update_plot again
        self.osc_widget.update_plot()

        # Check setRect call with new width
        self.osc_widget.persistence_img.setRect.assert_called_with((0, -1.1, 0.02, 2.2))

if __name__ == '__main__':
    unittest.main()
