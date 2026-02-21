
import sys
from unittest.mock import MagicMock, mock_open, patch
import json

# Define a base class for MeasurementModule
class MockMeasurementModule:
    def __init__(self, audio_engine=None):
        pass

# Mock modules before importing the target file
sys.modules['numpy'] = MagicMock()
sys.modules['pyqtgraph'] = MagicMock()
sys.modules['PyQt6'] = MagicMock()
sys.modules['PyQt6.QtCore'] = MagicMock()
sys.modules['PyQt6.QtGui'] = MagicMock()
sys.modules['PyQt6.QtWidgets'] = MagicMock()

sys.modules['src.core.analysis'] = MagicMock()
sys.modules['src.core.audio_engine'] = MagicMock()
sys.modules['src.core.localization'] = MagicMock()
sys.modules['src.core.utils'] = MagicMock()

# Mock src.measurement_modules.base.MeasurementModule with our simple class
mock_base_module = MagicMock()
mock_base_module.MeasurementModule = MockMeasurementModule
sys.modules['src.measurement_modules.base'] = mock_base_module

from src.gui.widgets.impedance_analyzer import ImpedanceAnalyzer

import unittest

class TestImpedanceAnalyzerDeserialization(unittest.TestCase):
    def test_deserialize_cal_raises_on_invalid_data(self):
        analyzer = ImpedanceAnalyzer(MagicMock())

        # Test data with invalid entry
        data = {
            "1000.0": [1.0, 0.0],
            "invalid_freq": [1.0, 0.0]
        }

        # Expectation: Should raise ValueError or similar
        with self.assertRaises(Exception):
            analyzer._deserialize_cal(data)

    def test_load_calibration_catches_exception(self):
        analyzer = ImpedanceAnalyzer(MagicMock())

        # Mock data with invalid content
        mock_data = {
            "cal_open": {
                "invalid_freq": [1.0, 0.0]
            }
        }

        with patch("builtins.open", mock_open(read_data=json.dumps(mock_data))), \
             patch("json.load", return_value=mock_data):

            # This triggers _deserialize_cal, which should raise Exception.
            # load_calibration catches it and returns False.
            success, msg = analyzer.load_calibration("dummy.json")
            print(f"load_calibration result: success={success}, msg='{msg}'")

            self.assertFalse(success, "load_calibration should return False on invalid data")
            self.assertNotEqual(msg, "", "load_calibration should return an error message")

if __name__ == "__main__":
    unittest.main()
