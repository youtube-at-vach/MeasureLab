import sys
import os
import unittest
import numpy as np
from unittest.mock import MagicMock, patch
import pytest

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
    print(f"ImportError: {e}")
    pytest.skip(f"Skipping GUI test due to missing dependencies: {e}", allow_module_level=True)

class TestOscilloscopeRefactor(unittest.TestCase):
    def setUp(self):
        # Ensure QApplication exists
        self.app = QApplication.instance()
        if self.app is None:
            self.app = QApplication(sys.argv)

        self.mock_engine = MagicMock()
        self.mock_engine.sample_rate = 48000
        self.mock_engine.calibration.input_sensitivity = 1.0

        self.module = Oscilloscope(self.mock_engine)
        self.module.is_running = True # Simulate running

        # Mock methods to control data flow
        self.module.process_queue = MagicMock()
        self.module.get_display_data = MagicMock()

        self.widget = OscilloscopeWidget(self.module)

        # Disable timer to manually control updates
        self.widget.timer.stop()

    def test_update_plot_standard_mode(self):
        # Setup data
        t_len = 100
        data = np.random.rand(t_len, 2)
        self.module.get_display_data.return_value = data
        self.module.timebase = 0.01

        # Check initial state (force hidden to verify update shows them)
        self.widget.curve_l.setVisible(False)
        self.widget.curve_r.setVisible(False)
        self.assertFalse(self.widget.curve_l.isVisible())
        self.assertFalse(self.widget.curve_r.isVisible())

        # Call update_plot
        self.widget.update_plot()

        # Verify curves updated
        self.assertTrue(self.widget.curve_l.isVisible())
        self.assertTrue(self.widget.curve_r.isVisible())

        # Check data set to curves
        x_l, y_l = self.widget.curve_l.getData()
        x_r, y_r = self.widget.curve_r.getData()

        self.assertEqual(len(x_l), t_len)
        self.assertTrue(np.allclose(y_l, data[:, 0]))
        self.assertTrue(np.allclose(y_r, data[:, 1]))

    def test_update_plot_persistence_mode(self):
        self.module.persistence_mode = True
        self.module.reset_persistence()
        self.widget.on_persist_toggled(True)

        t_len = 100
        data = np.random.rand(t_len, 2)
        self.module.get_display_data.return_value = data
        self.module.timebase = 0.01

        # Call update_plot
        self.widget.update_plot()

        # Verify persistence image visible, curves hidden
        self.assertTrue(self.widget.persistence_img.isVisible())
        self.assertFalse(self.widget.curve_l.isVisible())
        self.assertFalse(self.widget.curve_r.isVisible())

    def test_update_plot_math_mode(self):
        self.module.math_mode = "A + B"
        self.widget.on_math_changed("A + B")

        t_len = 100
        # A=0.5, B=0.2 -> A+B=0.7
        data = np.ones((t_len, 2))
        data[:, 0] = 0.5
        data[:, 1] = 0.2
        self.module.get_display_data.return_value = data
        self.module.timebase = 0.01

        # Call update_plot
        self.widget.update_plot()

        # Verify math curve updated
        x_m, y_m = self.widget.curve_math.getData()
        self.assertEqual(len(x_m), t_len)
        expected = 0.7
        self.assertTrue(np.allclose(y_m, expected))

    def test_update_plot_with_filter(self):
        self.module.filter_type = "LPF"
        self.module.filter_cutoff = 1000

        t_len = 100
        data = np.random.rand(t_len, 2)
        self.module.get_display_data.return_value = data.copy() # Return copy so we can check mod
        self.module.timebase = 0.01

        with patch('src.core.analysis.AudioCalc.lowpass_filter') as mock_lpf:
            # return modified data
            mock_lpf.side_effect = lambda d, sr, f: d * 0.5

            self.widget.update_plot()

            # Verify filter called
            self.assertEqual(mock_lpf.call_count, 2) # Once for L, once for R

            # Verify displayed data is filtered result
            _, y_l = self.widget.curve_l.getData()
            # Since we mocked it to return d*0.5
            self.assertTrue(np.allclose(y_l, data[:, 0] * 0.5))

    def test_measurements_update(self):
        t_len = 100
        data = np.zeros((t_len, 2))
        # 1V RMS sine wave approx? Just use DC for simplicity of check
        # RMS of 1.0 is 1.0
        data[:, 0] = 1.0
        data[:, 1] = 0.5
        self.module.get_display_data.return_value = data
        self.module.timebase = 0.01

        self.widget.update_plot()

        # Check label text contains reasonable values
        # 1.0 Vrms
        self.assertIn("1.000 V", self.widget.meas_l_label.text())
        # 0.5 Vrms
        self.assertIn("0.500 V", self.widget.meas_r_label.text())

if __name__ == '__main__':
    unittest.main()
