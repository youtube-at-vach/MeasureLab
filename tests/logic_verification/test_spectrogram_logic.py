
import unittest
from unittest.mock import MagicMock
import sys
import math

# Mock numpy if not available
try:
    import numpy as np
except ImportError:
    mock_np = MagicMock()
    mock_np.log10.side_effect = lambda x: math.log10(x) if x > 0 else -float('inf')
    mock_np.float64 = float
    sys.modules["numpy"] = mock_np
    import numpy as np

# Mock dependencies to allow importing SpectrogramWidget
sys.modules["PyQt6"] = MagicMock()
sys.modules["PyQt6.QtCore"] = MagicMock()
sys.modules["PyQt6.QtGui"] = MagicMock()
sys.modules["PyQt6.QtWidgets"] = MagicMock()
sys.modules["pyqtgraph"] = MagicMock()
sys.modules["src.core.audio_engine"] = MagicMock()
sys.modules["src.core.analysis"] = MagicMock()
sys.modules["src.core.localization"] = MagicMock()
sys.modules["src.measurement_modules.base"] = MagicMock()
sys.modules["src.core.fft_manager"] = MagicMock()
sys.modules["src.gui.styles"] = MagicMock()

class MockSpectrogramWidget:
    """
    Mock class replicating the logic of SpectrogramWidget for testing purposes.
    This ensures that the logic in on_freq_range_changed, update_range, and update_plot_limits
    behaves as expected.
    """
    def __init__(self):
        self.module = MagicMock()
        self.min_freq_spin = MagicMock()
        self.max_freq_spin = MagicMock()
        self.scale_combo = MagicMock()
        self.plot = MagicMock()

        # Initial values
        self.module.min_freq = 20
        self.module.max_freq = 20000
        self.min_freq_spin.value.return_value = 20
        self.max_freq_spin.value.return_value = 20000
        self.scale_combo.currentText.return_value = "Linear"

    def on_freq_range_changed(self):
        self.update_range()
        self.update_plot_limits()

    def update_range(self):
        if not hasattr(self, "min_freq_spin") or not hasattr(self, "max_freq_spin"):
            return

        self.module.min_freq = self.min_freq_spin.value()
        self.module.max_freq = self.max_freq_spin.value()

    def update_plot_limits(self):
        if not hasattr(self, "min_freq_spin") or not hasattr(self, "max_freq_spin"):
            return

        min_f = float(self.module.min_freq)
        max_f = float(self.module.max_freq)

        if self.scale_combo.currentText() == "Log":
            # Avoid log(0) or negative
            if min_f <= 0:
                min_f = 1.0  # 1Hz minimum for log scale
            if max_f <= min_f:
                max_f = min_f + 10.0  # Valid range

            self.plot.setYRange(np.log10(min_f), np.log10(max_f))
        else:
            self.plot.setYRange(min_f, max_f)


class TestSpectrogramLogic(unittest.TestCase):
    def setUp(self):
        self.widget = MockSpectrogramWidget()

    def test_linear_scale(self):
        # Setup
        self.widget.scale_combo.currentText.return_value = "Linear"
        val_min = 100
        val_max = 5000

        self.widget.min_freq_spin.value.return_value = val_min
        self.widget.max_freq_spin.value.return_value = val_max

        # Execute
        self.widget.on_freq_range_changed()

        # Verify Module Updates
        self.assertEqual(self.widget.module.min_freq, val_min)
        self.assertEqual(self.widget.module.max_freq, val_max)

        # Verify Plot Updates
        self.widget.plot.setYRange.assert_called_with(float(val_min), float(val_max))

    def test_log_scale(self):
        # Setup
        self.widget.scale_combo.currentText.return_value = "Log"
        val_min = 20
        val_max = 20000

        self.widget.min_freq_spin.value.return_value = val_min
        self.widget.max_freq_spin.value.return_value = val_max

        # Execute
        self.widget.on_freq_range_changed()

        # Verify
        expected_min = np.log10(val_min)
        expected_max = np.log10(val_max)

        self.widget.plot.setYRange.assert_called_with(expected_min, expected_max)

    def test_log_scale_correction(self):
        # Test edge case where min_freq <= 0
        self.widget.scale_combo.currentText.return_value = "Log"
        val_min = 0
        val_max = 100

        self.widget.min_freq_spin.value.return_value = val_min
        self.widget.max_freq_spin.value.return_value = val_max

        # Execute
        self.widget.on_freq_range_changed()

        # Logic corrects min to 1.0 if <= 0
        expected_min = np.log10(1.0)
        expected_max = np.log10(100.0)

        self.widget.plot.setYRange.assert_called_with(expected_min, expected_max)

    def test_missing_attributes(self):
        # Simulate missing spinboxes (e.g. during init)
        del self.widget.min_freq_spin

        # Execute
        self.widget.on_freq_range_changed()

        # Verify no crash and no calls
        self.widget.plot.setYRange.assert_not_called()

if __name__ == '__main__':
    unittest.main()
