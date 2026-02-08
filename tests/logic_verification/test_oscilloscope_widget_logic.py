import sys
from unittest.mock import MagicMock
import types

# 1. Mock dependencies

# numpy
mock_np = MagicMock()
sys.modules["numpy"] = mock_np

# scipy
scipy_mock = types.ModuleType("scipy")
sys.modules["scipy"] = scipy_mock
sys.modules["scipy.signal"] = MagicMock()
sys.modules["scipy.fftpack"] = MagicMock()
sys.modules["scipy.fft"] = MagicMock()
sys.modules["scipy.optimize"] = MagicMock()

# sounddevice
mock_sd = MagicMock()
sys.modules["sounddevice"] = mock_sd

# pyqtgraph
mock_pg = MagicMock()
sys.modules["pyqtgraph"] = mock_pg

# PyQt6
mock_qt_core = MagicMock()
mock_qt_gui = MagicMock()
mock_qt_widgets = MagicMock()

# We need QWidget to be a class we can inherit from.
class MockQWidget(MagicMock):
    def _get_child_mock(self, **kw):
        # Return a standard MagicMock instead of an instance of this class (OscilloscopeWidget)
        return MagicMock(**kw)

mock_qt_widgets.QWidget = MockQWidget

# We also need other classes to be instantiable (act as factories)
# Using MagicMock() creates a mock OBJECT that acts as the class.
# Calling it returns a new child mock (or return_value).
mock_qt_widgets.QComboBox = MagicMock()
mock_qt_widgets.QSlider = MagicMock()
mock_qt_widgets.QPushButton = MagicMock()
mock_qt_widgets.QCheckBox = MagicMock()
# mock_qt_widgets.QLabel needs to return our configured instance (or just a generic one)
mock_qt_widgets.QLabel = MagicMock()
# Explicitly set return value if we need to customize the instance
mock_label_instance = MagicMock()
mock_qt_widgets.QLabel.return_value = mock_label_instance

mock_qt_widgets.QGroupBox = MagicMock()
mock_qt_widgets.QVBoxLayout = MagicMock()
mock_qt_widgets.QHBoxLayout = MagicMock()
mock_qt_widgets.QFormLayout = MagicMock()
mock_qt_widgets.QTabWidget = MagicMock()
mock_qt_widgets.QStackedWidget = MagicMock()
mock_qt_widgets.QDoubleSpinBox = MagicMock()
mock_qt_widgets.QApplication = MagicMock()

# QtCore
mock_qt_core.Qt.Orientation.Horizontal = 1
mock_qt_core.Qt.PenStyle.DotLine = 2
mock_qt_core.QTimer = MagicMock

sys.modules["PyQt6"] = MagicMock()
sys.modules["PyQt6.QtCore"] = mock_qt_core
sys.modules["PyQt6.QtGui"] = mock_qt_gui
sys.modules["PyQt6.QtWidgets"] = mock_qt_widgets

# 2. Import module under test
from src.gui.widgets.oscilloscope import OscilloscopeWidget, Oscilloscope  # noqa: E402

def test_slider_sync():
    print("Setting up test...")
    mock_audio_engine = MagicMock()
    mock_audio_engine.calibration.input_sensitivity = 1.0
    oscilloscope = Oscilloscope(mock_audio_engine)

    print("Instantiating Widget...")
    widget = OscilloscopeWidget(oscilloscope)

    # Verify setup
    # widget.timebase_keys should be populated
    assert len(widget.timebase_keys) > 0
    assert len(widget.vscale_keys) > 0

    # ---------------------------------------------------------
    # Test Timebase Slider -> Combo
    # ---------------------------------------------------------
    print("Testing Timebase Slider...")
    keys = widget.timebase_keys
    # Mock currentText to be different
    widget.timebase_combo.currentText.return_value = "DIFFERENT"

    idx = 0
    target_key = keys[idx]

    # Call handler
    widget.on_timebase_slider_changed(idx)

    # Check if combo text was set
    widget.timebase_combo.setCurrentText.assert_called_with(target_key)

    # Reset mock
    widget.timebase_combo.setCurrentText.reset_mock()

    # Test with index out of bounds (should not crash or call)
    widget.on_timebase_slider_changed(-1)
    widget.timebase_combo.setCurrentText.assert_not_called()

    widget.on_timebase_slider_changed(len(keys))
    widget.timebase_combo.setCurrentText.assert_not_called()

    # ---------------------------------------------------------
    # Test VScale Left Slider -> Combo
    # ---------------------------------------------------------
    print("Testing VScale Left Slider...")
    keys = widget.vscale_keys
    widget.vscale_combo_l.currentText.return_value = "DIFFERENT"

    idx = 1
    target_key = keys[idx]

    widget.on_vscale_left_slider_changed(idx)
    widget.vscale_combo_l.setCurrentText.assert_called_with(target_key)

    widget.vscale_combo_l.setCurrentText.reset_mock()

    # ---------------------------------------------------------
    # Test VScale Right Slider -> Combo
    # ---------------------------------------------------------
    print("Testing VScale Right Slider...")
    widget.vscale_combo_r.currentText.return_value = "DIFFERENT"

    idx = 2
    target_key = keys[idx]

    widget.on_vscale_right_slider_changed(idx)
    widget.vscale_combo_r.setCurrentText.assert_called_with(target_key)

    widget.vscale_combo_r.setCurrentText.reset_mock()

    print("All logic verification passed.")

if __name__ == "__main__":
    test_slider_sync()
