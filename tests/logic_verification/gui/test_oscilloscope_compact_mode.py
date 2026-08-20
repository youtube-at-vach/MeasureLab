import os
import sys
import unittest
from unittest.mock import MagicMock
import pytest

pytest.importorskip("PyQt6")

if "sounddevice" not in sys.modules:
    sys.modules["sounddevice"] = MagicMock()

os.environ["QT_QPA_PLATFORM"] = "offscreen"

try:
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QApplication, QFrame
    from src.core.module_constants import MODULE_OSCILLOSCOPE
    from src.gui.module_registry import MODULE_REGISTRY
    from src.gui.widgets.detachable_wrapper import DetachableWidgetWrapper
    from src.gui.widgets.oscilloscope import Oscilloscope, OscilloscopeWidget
except ImportError:
    pytest.skip("Skipping GUI test due to missing dependencies", allow_module_level=True)


class TestOscilloscopeCompactMode(unittest.TestCase):
    def setUp(self):
        self.app = QApplication.instance()
        if self.app is None:
            self.app = QApplication(sys.argv)

        self.mock_engine = MagicMock()
        self.mock_engine.sample_rate = 48000
        self.module = Oscilloscope(self.mock_engine)
        self.widget = OscilloscopeWidget(self.module)

    def test_compact_mode_layout_and_borders(self):
        # Initial state (full mode)
        self.assertFalse(self.widget.is_compact_mode())
        initial_margins = self.widget.layout().contentsMargins()
        initial_spacing = self.widget.layout().spacing()

        # Enter compact mode
        self.widget.set_compact_mode(True)
        self.assertTrue(self.widget.is_compact_mode())

        # Check margins and spacing are zeroed out
        compact_margins = self.widget.layout().contentsMargins()
        self.assertEqual(compact_margins.left(), 0)
        self.assertEqual(compact_margins.top(), 0)
        self.assertEqual(compact_margins.right(), 0)
        self.assertEqual(compact_margins.bottom(), 0)
        self.assertEqual(self.widget.layout().spacing(), 0)

        # Check plot widget frame shape and stylesheet
        self.assertEqual(self.widget.plot_widget.frameShape(), QFrame.Shape.NoFrame)
        self.assertIn("border: none", self.widget.plot_widget.styleSheet())

        # Exit compact mode
        self.widget.set_compact_mode(False)
        self.assertFalse(self.widget.is_compact_mode())

        # Check margins and spacing are restored
        restored_margins = self.widget.layout().contentsMargins()
        self.assertEqual(restored_margins.left(), initial_margins.left())
        self.assertEqual(restored_margins.top(), initial_margins.top())
        self.assertEqual(restored_margins.right(), initial_margins.right())
        self.assertEqual(restored_margins.bottom(), initial_margins.bottom())
        self.assertEqual(self.widget.layout().spacing(), initial_spacing)

        # Check plot widget frame shape is restored
        self.assertEqual(self.widget.plot_widget.frameShape(), QFrame.Shape.StyledPanel)

    def test_hidden_y_axis_suppresses_axis_line_and_keeps_grid_pen(self):
        left_axis = self.widget.plot_widget.getPlotItem().getAxis("left")

        self.assertEqual(left_axis.pen().style(), Qt.PenStyle.NoPen)
        self.assertNotEqual(left_axis.tickPen().style(), Qt.PenStyle.NoPen)

        self.widget.on_show_y_axis_toggled(True)
        self.assertNotEqual(left_axis.pen().style(), Qt.PenStyle.NoPen)

        self.widget.on_show_y_axis_toggled(False)
        self.assertEqual(left_axis.pen().style(), Qt.PenStyle.NoPen)
        self.assertNotEqual(left_axis.tickPen().style(), Qt.PenStyle.NoPen)

        self.widget.set_compact_mode(True)
        self.widget.set_compact_mode(False)
        self.assertEqual(left_axis.pen().style(), Qt.PenStyle.NoPen)
        self.assertNotEqual(left_axis.tickPen().style(), Qt.PenStyle.NoPen)

    def test_split_compact_toggle_restores_display_window_size(self):
        wrapper = DetachableWidgetWrapper(
            self.widget,
            "Oscilloscope",
            capabilities=MODULE_REGISTRY[MODULE_OSCILLOSCOPE].capabilities,
        )
        wrapper.show()
        wrapper.split()
        self.app.processEvents()

        display_window = wrapper.split_display_window
        display_window.resize(800, 600)
        self.app.processEvents()
        normal_size = display_window.size()

        try:
            for _ in range(3):
                wrapper.toggle_compact(True)
                QTest.qWait(10)
                self.assertTrue(self.widget.is_compact_mode())

                wrapper.toggle_compact(False)
                QTest.qWait(10)
                self.assertFalse(self.widget.is_compact_mode())
                self.assertEqual(display_window.size(), normal_size)
        finally:
            wrapper.reattach_all()
            wrapper.close()


if __name__ == "__main__":
    unittest.main()
