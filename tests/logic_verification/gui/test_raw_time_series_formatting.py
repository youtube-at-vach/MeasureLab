import sys
import os
import unittest
from unittest.mock import MagicMock
import pytest

# Skip if PyQt6 is not installed
pytest.importorskip("PyQt6")

# Mock sounddevice BEFORE importing any module that uses it
if "sounddevice" not in sys.modules:
    sys.modules["sounddevice"] = MagicMock()

# Set offscreen
os.environ["QT_QPA_PLATFORM"] = "offscreen"

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
            self.app = QApplication(sys.argv + ["-platform", "offscreen"])

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
        def mock_init(self_obj, module):
            # Just set the module, skip _init_ui and QTimer
            self_obj.module = module
            self_obj._last_frame = None

        with unittest.mock.patch.object(RawTimeSeriesWidget, "__init__", mock_init):
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
        self.assertEqual(self.widget._format_amplitude(float("inf")), "-")
        self.assertEqual(self.widget._format_amplitude(float("nan")), "-")
        self.assertEqual(self.widget._format_amplitude(-float("inf")), "-")

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


if __name__ == "__main__":
    unittest.main()
