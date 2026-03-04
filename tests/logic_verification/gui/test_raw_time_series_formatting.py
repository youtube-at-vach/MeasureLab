import sys
import os
import unittest
from unittest.mock import MagicMock
import pytest
import numpy as np

# Skip if PyQt6 is not installed
pytest.importorskip("PyQt6")

# Mock sounddevice BEFORE importing any module that uses it
if "sounddevice" not in sys.modules:
    sys.modules["sounddevice"] = MagicMock()

# Set offscreen
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

try:
    from PyQt6.QtWidgets import QApplication
    from src.gui.widgets.raw_time_series import RawTimeSeriesWidget
except ImportError as e:
    print(f"Import Error: {e}")
    pytest.skip(f"Skipping GUI test due to missing dependencies: {e}", allow_module_level=True)

class TestRawTimeSeriesFormatting(unittest.TestCase):
    def setUp(self):
        # Ensure QApplication exists
        self.app = QApplication.instance()
        if self.app is None:
            self.app = QApplication(sys.argv + ['-platform', 'offscreen'])

        # Create a mock module so we don't need to instantiate the real RawTimeSeries
        self.mock_module = MagicMock()
        self.mock_module.audio_engine = MagicMock()
        self.mock_module.audio_engine.calibration = MagicMock()
        self.mock_module.audio_engine.calibration.input_sensitivity = 2.5

        # Set default values for properties expected by the widget
        self.mock_module.show_volts = False
        self.mock_module.show_dc_offset = False
        self.mock_module.time_span_s = 10.0
        self.mock_module.vscale = 1.0

        # We need to mock _init_ui to avoid actual pyqtgraph/Qt rendering issues in offscreen mode
        # The formatting functions don't depend on the UI being fully built
        original_init = RawTimeSeriesWidget.__init__

        def mock_init(self_obj, module):
            # Just set the module, skip _init_ui and QTimer
            self_obj.module = module
            self_obj._last_frame = None

        with unittest.mock.patch.object(RawTimeSeriesWidget, '__init__', mock_init):
            self.widget = RawTimeSeriesWidget(self.mock_module)

    def test_get_unit_factor(self):
        # show_volts = False
        self.mock_module.show_volts = False
        self.assertEqual(self.widget._get_unit_factor(), 1.0)

        # show_volts = True
        self.mock_module.show_volts = True
        self.assertEqual(self.widget._get_unit_factor(), 2.5)

        # Test exception handling fallback
        self.mock_module.audio_engine.calibration.input_sensitivity = MagicMock(side_effect=Exception("mock error"))
        self.assertEqual(self.widget._get_unit_factor(), 1.0)

    def test_get_unit_label(self):
        self.mock_module.show_volts = False
        self.assertEqual(self.widget._get_unit_label(), "FS")

        self.mock_module.show_volts = True
        self.assertEqual(self.widget._get_unit_label(), "V")

    def test_format_amplitude_fs(self):
        self.mock_module.show_volts = False

        # Normal value
        self.assertEqual(self.widget._format_amplitude(0.1234567), "0.123457 FS")
        self.assertEqual(self.widget._format_amplitude(-1.5), "-1.5 FS")

        # Invalid numeric
        self.assertEqual(self.widget._format_amplitude("not_a_number"), "-")
        self.assertEqual(self.widget._format_amplitude(None), "-")

        # Inf/NaN
        self.assertEqual(self.widget._format_amplitude(float('inf')), "-")
        self.assertEqual(self.widget._format_amplitude(float('nan')), "-")
        self.assertEqual(self.widget._format_amplitude(-float('inf')), "-")

    def test_format_amplitude_volts(self):
        self.mock_module.show_volts = True

        # format_si uses different logic internally
        # We'll just verify it contains a 'V' and is a string
        formatted = self.widget._format_amplitude(0.123)
        self.assertIsInstance(formatted, str)
        self.assertTrue("V" in formatted)

        # Zero
        formatted_zero = self.widget._format_amplitude(0.0)
        self.assertIsInstance(formatted_zero, str)

    def test_decimate_for_plot(self):
        # The decimate_for_plot method is a static method

        # Test empty/None cases
        t_empty, y_empty = RawTimeSeriesWidget._decimate_for_plot(None, None, 10)
        self.assertEqual(len(t_empty), 0)
        self.assertEqual(len(y_empty), 0)

        t_empty, y_empty = RawTimeSeriesWidget._decimate_for_plot(np.array([]), np.array([]), 10)
        self.assertEqual(len(t_empty), 0)

        # Test no decimation needed (len <= max_points)
        t = np.arange(5)
        y = np.arange(5)
        t_out, y_out = RawTimeSeriesWidget._decimate_for_plot(t, y, max_points=10)
        np.testing.assert_array_equal(t_out, t)
        np.testing.assert_array_equal(y_out, y)

        # Test decimation needed (len > max_points)
        t = np.arange(20)
        y = np.arange(20)
        t_out, y_out = RawTimeSeriesWidget._decimate_for_plot(t, y, max_points=5)
        # step = max(1, 20 // 5) = 4
        # t_out should be [0, 4, 8, 12, 16]
        np.testing.assert_array_equal(t_out, np.array([0, 4, 8, 12, 16]))
        np.testing.assert_array_equal(y_out, np.array([0, 4, 8, 12, 16]))

        # Another decimation test
        t = np.arange(100)
        y = np.arange(100)
        t_out, y_out = RawTimeSeriesWidget._decimate_for_plot(t, y, max_points=33)
        # step = max(1, 100 // 33) = 3
        # len should be ceil(100 / 3) = 34
        self.assertEqual(len(t_out), 34)
        np.testing.assert_array_equal(t_out[:3], np.array([0, 3, 6]))

if __name__ == '__main__':
    unittest.main()
