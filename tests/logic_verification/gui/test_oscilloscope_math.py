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
    from src.gui.widgets.oscilloscope import Oscilloscope, OscilloscopeWidget
except ImportError as e:
    print(f"Import Error: {e}")
    pytest.skip(f"Skipping GUI test due to missing dependencies: {e}", allow_module_level=True)

class TestOscilloscopeMath(unittest.TestCase):
    def setUp(self):
        # Ensure QApplication exists
        self.app = QApplication.instance()
        if self.app is None:
            self.app = QApplication(sys.argv)

        self.mock_engine = MagicMock()
        self.mock_engine.sample_rate = 48000
        # Mock register_callback to return a dummy ID
        self.mock_engine.register_callback.return_value = 123
        # Mock calibration
        self.mock_engine.calibration = MagicMock()
        self.mock_engine.calibration.input_sensitivity = 1.0

        self.module = Oscilloscope(self.mock_engine)
        self.widget = OscilloscopeWidget(self.module)

    def test_math_mode_empty_data_crash(self):
        # 1. Enable Math Mode
        self.module.math_mode = "A + B"
        # self.widget.math_combo.setCurrentText("A + B") # UI creation might fail in headless without proper mocking, rely on module state

        # Ensure module is considered "running" so update_plot proceeds
        self.module.is_running = True

        # 2. Simulate Empty Data from get_display_data
        # We can achieve this by mocking get_display_data directly
        # or by setting timebase very small.
        # Let's mock get_display_data to return an empty array of shape (0, 2)
        self.module.get_display_data = MagicMock(return_value=np.empty((0, 2)))

        # Also need process_queue to not crash or do anything weird
        self.module.process_queue = MagicMock()

        # 3. Call update_plot
        # This should NOT raise ValueError: zero-size array to reduction operation minimum which has no identity
        try:
            self.widget.update_plot()
        except ValueError as e:
            self.fail(f"update_plot raised ValueError with empty data: {e}")
        except Exception as e:
            self.fail(f"update_plot raised unexpected exception: {e}")

if __name__ == '__main__':
    unittest.main()
