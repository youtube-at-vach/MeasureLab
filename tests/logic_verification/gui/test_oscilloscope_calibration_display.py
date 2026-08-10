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


class TestOscilloscopeCalibrationDisplay(unittest.TestCase):
    def setUp(self):
        self.app = QApplication.instance() or QApplication(sys.argv)
        get_manager().load_language("en")

        self.engine = MagicMock()
        self.engine.sample_rate = 48000
        self.engine.calibration.input_sensitivity = 2.0
        self.engine.calibration.input_sensitivity_is_calibrated = False

        self.module = Oscilloscope(self.engine)
        self.widget = OscilloscopeWidget(self.module)

    def tearDown(self):
        self.widget.close()

    def test_uncalibrated_measurements_and_cursors_use_full_scale(self):
        data = np.array([[0.0, 0.0], [0.5, 0.0], [-0.5, 0.0]])
        measurements = self.module.get_measurements(data)
        self.widget._set_measurement_labels(measurements)

        self.assertEqual(self.widget.calibration_status_label.text(), "Input: Uncalibrated (FS)")
        self.assertIn("0.408 FS", self.widget.meas_l_label.text())
        self.assertIn("1.000 FS", self.widget.meas_l_label.text())
        self.assertNotIn(" V", self.widget.meas_l_label.text())

        self.widget.latest_t = np.array([0.0, 1.0])
        self.widget.latest_data = np.array([[0.0, 0.0], [0.5, 0.0]])
        self.widget.chk_cursors.setChecked(True)
        self.widget.cursor_1.setPos(0.0)
        self.widget.cursor_2.setPos(1.0)
        self.widget.update_cursor_info()

        cursor_text = self.widget.cursor_info_label.text()
        self.assertIn("A1: 0.000 FS", cursor_text)
        self.assertIn("A2: 0.500 FS", cursor_text)
        self.assertNotIn("V1:", cursor_text)

    def test_calibrated_measurements_and_cursors_use_volts(self):
        self.engine.calibration.input_sensitivity_is_calibrated = True
        self.widget.show()
        self.app.processEvents()

        data = np.array([[0.0, 0.0], [0.5, 0.0], [-0.5, 0.0]])
        measurements = self.module.get_measurements(data)
        self.widget._set_measurement_labels(measurements)

        self.assertEqual(self.widget.calibration_status_label.text(), "Input: Calibrated (2 V/FS)")
        self.assertIn("0.816 V", self.widget.meas_l_label.text())
        self.assertIn("2.000 V", self.widget.meas_l_label.text())

        self.widget.latest_t = np.array([0.0, 1.0])
        self.widget.latest_data = np.array([[0.0, 0.0], [0.5, 0.0]])
        self.widget.chk_cursors.setChecked(True)
        self.widget.cursor_1.setPos(0.0)
        self.widget.cursor_2.setPos(1.0)
        self.widget.update_cursor_info()

        cursor_text = self.widget.cursor_info_label.text()
        self.assertIn("V1: 0.000V", cursor_text)
        self.assertIn("V2: 1.000V", cursor_text)

    def test_comparison_trace_unit_matches_calibration_state(self):
        self.module.show_right = False
        self.widget.last_display_time = np.array([0.0, 1.0])
        self.widget.last_display_data = np.array([[0.0, 0.0], [0.5, 0.0]])

        uncalibrated_trace = self.widget.get_comparable_data()[0]
        self.assertEqual(uncalibrated_trace.y_axis.display_unit, "FS")
        self.assertEqual(uncalibrated_trace.calibration.reference_level, "relative")
        np.testing.assert_allclose(uncalibrated_trace.y_data, [0.0, 0.5])

        self.engine.calibration.input_sensitivity_is_calibrated = True
        calibrated_trace = self.widget.get_comparable_data()[0]
        self.assertEqual(calibrated_trace.y_axis.display_unit, "V")
        self.assertEqual(calibrated_trace.calibration.reference_level, "absolute")
        np.testing.assert_allclose(calibrated_trace.y_data, [0.0, 1.0])


if __name__ == "__main__":
    unittest.main()
