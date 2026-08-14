import os
import sys
import unittest
from unittest.mock import MagicMock

import pytest

pytest.importorskip("PyQt6")

if "sounddevice" not in sys.modules:
    sys.modules["sounddevice"] = MagicMock()

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PyQt6.QtWidgets import QApplication, QWidget

from src.core.module_constants import MODULE_NOISE_PROFILER
from src.gui.module_registry import MODULE_REGISTRY
from src.gui.widgets.detachable_wrapper import DetachableWidgetWrapper
from src.gui.widgets.noise_profiler import NoiseProfiler, NoiseProfilerWidget
from src.gui.widgets.splittable_interface import SplittableWidgetInterface


class TestNoiseProfilerSplit(unittest.TestCase):
    def setUp(self):
        self.app = QApplication.instance()
        if self.app is None:
            self.app = QApplication(sys.argv)

        self.mock_engine = MagicMock()
        self.mock_engine.sample_rate = 48000
        self.mock_engine.calibration.get_input_offset_db.return_value = 0.0

        self.module = NoiseProfiler(self.mock_engine)
        self.widget = NoiseProfilerWidget(self.module)

    def test_splittable_interface_implementation(self):
        self.assertIsInstance(self.widget, SplittableWidgetInterface)

        display_widget = self.widget.get_display_widget()
        control_widget = self.widget.get_control_widget()

        self.assertIsInstance(display_widget, QWidget)
        self.assertIsInstance(control_widget, QWidget)
        self.assertEqual(display_widget, self.widget.display_widget)
        self.assertEqual(control_widget, self.widget.sidebar)

    def test_detachable_wrapper_split_flow(self):
        wrapper = DetachableWidgetWrapper(
            self.widget,
            "Noise Profiler",
            capabilities=MODULE_REGISTRY[MODULE_NOISE_PROFILER].capabilities,
        )
        self.assertTrue(wrapper.is_splittable)
        self.assertIsNotNone(wrapper.split_btn)
        self.assertTrue(wrapper.split_btn.isEnabled())

        wrapper.split()
        self.assertTrue(wrapper.is_split)
        self.assertIsNotNone(wrapper.split_display_window)
        self.assertIsNotNone(wrapper.split_control_window)

        self.widget.set_compact_mode(True)
        self.assertTrue(self.widget.is_compact_mode())
        self.assertFalse(self.widget.sidebar.isHidden())

        wrapper.reattach_all()
        self.assertFalse(wrapper.is_split)
        self.assertEqual(self.widget.display_widget.parent(), self.widget)
        self.assertEqual(self.widget.sidebar.parent(), self.widget)


if __name__ == "__main__":
    unittest.main()
