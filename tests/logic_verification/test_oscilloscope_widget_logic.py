import sys
from unittest.mock import MagicMock, patch
import types

# Helper to create mock QWidget-like class
class MockQWidget(MagicMock):
    def _get_child_mock(self, **kw):
        return MagicMock(**kw)

def test_slider_sync():
    # Define mocks
    mock_np = MagicMock()

    # Configure scipy
    scipy_mock = types.ModuleType("scipy")
    scipy_mock.signal = MagicMock()
    scipy_mock.fftpack = MagicMock()
    scipy_mock.fft = MagicMock()
    scipy_mock.optimize = MagicMock()

    mock_sd = MagicMock()
    mock_pg = MagicMock()

    # Configure Qt
    mock_qt_core = MagicMock()
    mock_qt_core.Qt.Orientation.Horizontal = 1
    mock_qt_core.Qt.PenStyle.DotLine = 2
    mock_qt_core.QTimer = MagicMock()

    mock_qt_widgets = MagicMock()
    mock_qt_widgets.QWidget = MockQWidget
    mock_qt_widgets.QComboBox = MagicMock()
    mock_qt_widgets.QSlider = MagicMock()
    mock_qt_widgets.QPushButton = MagicMock()
    mock_qt_widgets.QCheckBox = MagicMock()

    # Configure QLabel specifically
    mock_label_instance = MagicMock()
    mock_qt_widgets.QLabel = MagicMock(return_value=mock_label_instance)

    mock_qt_widgets.QGroupBox = MagicMock()
    mock_qt_widgets.QVBoxLayout = MagicMock()
    mock_qt_widgets.QHBoxLayout = MagicMock()
    mock_qt_widgets.QFormLayout = MagicMock()
    mock_qt_widgets.QTabWidget = MagicMock()
    mock_qt_widgets.QStackedWidget = MagicMock()
    mock_qt_widgets.QDoubleSpinBox = MagicMock()
    mock_qt_widgets.QApplication = MagicMock()

    mock_modules = {
        "numpy": mock_np,
        "scipy": scipy_mock,
        "scipy.signal": scipy_mock.signal,
        "scipy.fftpack": scipy_mock.fftpack,
        "scipy.fft": scipy_mock.fft,
        "scipy.optimize": scipy_mock.optimize,
        "sounddevice": mock_sd,
        "pyqtgraph": mock_pg,
        "PyQt6": MagicMock(),
        "PyQt6.QtCore": mock_qt_core,
        "PyQt6.QtGui": MagicMock(),
        "PyQt6.QtWidgets": mock_qt_widgets,
    }

    # Patch modules only within this test scope
    with patch.dict(sys.modules, mock_modules):
        # Force a fresh import of the module under test to ensure it uses the mocks
        # even if it was previously loaded by other tests.
        # patch.dict will restore the original module (if any) upon exit.
        if "src.gui.widgets.oscilloscope" in sys.modules:
            del sys.modules["src.gui.widgets.oscilloscope"]

        from src.gui.widgets.oscilloscope import OscilloscopeWidget, Oscilloscope  # noqa: E402

        print("Setting up test...")
        mock_audio_engine = MagicMock()
        mock_audio_engine.calibration.input_sensitivity = 1.0
        oscilloscope = Oscilloscope(mock_audio_engine)

        print("Instantiating Widget...")
        widget = OscilloscopeWidget(oscilloscope)

        # Verify setup
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

        # Test with index out of bounds
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
