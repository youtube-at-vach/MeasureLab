import os
import sys
import unittest
from unittest.mock import MagicMock

import numpy as np
import pytest

pytest.importorskip("PyQt6")

if "sounddevice" not in sys.modules:
    sys.modules["sounddevice"] = MagicMock()

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PyQt6.QtWidgets import QApplication

from src.core.localization import get_manager
from src.gui.widgets.oscilloscope import Oscilloscope, OscilloscopeWidget


class TestOscilloscopeFeatures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        get_manager().load_language("en")

        self.engine = MagicMock()
        self.engine.sample_rate = 48000
        self.engine.calibration.input_sensitivity = 1.0
        self.engine.calibration.input_sensitivity_is_calibrated = False

        self.module = Oscilloscope(self.engine)
        self.widget = OscilloscopeWidget(self.module)

    def tearDown(self):
        self.widget.close()

    def test_overload_clipping_detection_and_latching(self):
        """Verify clipping is detected and latched until the next run starts."""
        self.assertFalse(self.module.clipping_latched_l)
        self.assertFalse(self.module.clipping_latched_r)

        # Normal signal (no clipping)
        normal_data = np.full((100, 2), 0.5)
        self.module.check_clipping(normal_data)
        self.assertFalse(self.module.clipping_detected_l)
        self.assertFalse(self.module.clipping_latched_l)

        # Clipped signal on left channel (>= 0.999)
        clipped_data = np.zeros((100, 2))
        clipped_data[10, 0] = 1.0
        self.module.check_clipping(clipped_data)
        self.assertTrue(self.module.clipping_detected_l)
        self.assertTrue(self.module.clipping_latched_l)

        # Subsequent normal frame: detection resets, but latch stays True
        self.module.check_clipping(normal_data)
        self.assertFalse(self.module.clipping_detected_l)
        self.assertTrue(self.module.clipping_latched_l)

        # Widget badge visibility should be True when latched
        self.widget.show()
        self.module.is_running = True
        self.widget.update_plot()
        self.assertFalse(self.widget.clipping_warning_badge.isHidden())

        # Reset latch on new start_analysis
        self.module.reset_clipping_latch()
        self.assertFalse(self.module.clipping_latched_l)

    def test_auto_scale_engine(self):
        """Verify Auto Scale selects optimal Time/Div, V/Div, and Trigger settings."""
        sr = 48000
        t = np.arange(sr // 10) / sr  # 0.1s
        f = 1000.0  # 1 kHz
        y = 0.8 * np.sin(2 * np.pi * f * t)  # Vpp ~ 1.6 FS

        data = np.zeros((len(t), 2))
        data[:, 0] = y
        data[:, 1] = 0.0

        success = self.module.auto_scale(data)
        self.assertTrue(success)

        # Primary channel should be Left (0)
        self.assertEqual(self.module.trigger_source, 0)
        # For 1 kHz, period is 1 ms. 3 cycles = 3 ms over 10 div -> ~0.5 ms/div or 1 ms/div
        self.assertIn(self.module.time_div, [0.0002, 0.0005, 0.001])
        # For ~1.6 Vpp, desired V/div is around 0.32 -> closest in 1-2-5 is 0.5 or 0.25
        self.assertIn(self.module.vdiv_left, [0.2, 0.25, 0.5])
        self.assertEqual(self.module.trigger_mode, "Auto")

    def test_direct_manipulation_trigger_line_sync(self):
        """Verify trigger line drag updates spinbox and vice versa."""
        self.module.vdiv_left = 0.25
        self.module.trigger_source = 0

        # Spinbox -> Trigger line & Module
        self.widget.trig_level_spin.setValue(2.0)  # +2 div -> 0.5 FS
        self.assertAlmostEqual(self.widget.trig_line.value(), 2.0, places=3)
        self.assertAlmostEqual(self.module.trigger_level, 0.5, places=3)

        # Trigger line drag -> Spinbox & Module
        self.widget.trig_line.setPos(-1.5)
        self.widget.on_trig_line_dragged()
        self.assertAlmostEqual(self.widget.trig_level_spin.value(), -1.5, places=3)
        self.assertAlmostEqual(self.module.trigger_level, -0.375, places=3)

    def test_channel_badges_and_scaling(self):
        """Verify channel badges reflect active scale and state."""
        self.widget._update_badges()
        self.assertIn("CH1:", self.widget.badge_l_label.text())
        self.assertIn("CH2:", self.widget.badge_r_label.text())
        self.assertIn("TIME:", self.widget.badge_status_label.text())
        self.assertIn("TRIG:", self.widget.badge_status_label.text())
