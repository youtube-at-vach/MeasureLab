import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../')))
import sys
import numpy as np
from unittest.mock import MagicMock, patch
import pytest
import re

# Mock GUI dependencies
mock_qt_core = MagicMock()
class MockQObject:
    def __init__(self): pass
class MockQWidget:
    def __init__(self, *args, **kwargs): pass
    def update(self): pass
    def setStyleSheet(self, style): pass
    def setLayout(self, layout): pass

mock_qt_core.QObject = MockQObject
mock_qt_core.pyqtSignal = MagicMock(side_effect=lambda *args: MagicMock())
mock_qt_core.Qt.Orientation.Horizontal = 1
mock_qt_core.Qt.PenStyle.DashLine = 2

mock_qt_widgets = MagicMock()
mock_qt_widgets.QWidget = MockQWidget

# Specific mocks for widget components
mock_combo = MagicMock()
mock_combo.findData.return_value = -1
mock_combo.findText.return_value = -1
mock_qt_widgets.QComboBox = MagicMock(return_value=mock_combo)

mock_label = MagicMock()
mock_label.text.return_value = "Overall: -- dB"
mock_qt_widgets.QLabel = MagicMock(return_value=mock_label)

mock_pg = MagicMock()
mock_plot_item = MagicMock()
mock_axis = MagicMock()
mock_plot_item.getAxis.return_value = mock_axis
mock_pg.PlotWidget.return_value.getPlotItem.return_value = mock_plot_item
# Scene mock
mock_scene = MagicMock()
mock_pg.PlotWidget.return_value.scene.return_value = mock_scene

mock_modules = {
    "PyQt6": MagicMock(),
    "PyQt6.QtCore": mock_qt_core,
    "PyQt6.QtGui": MagicMock(),
    "PyQt6.QtWidgets": mock_qt_widgets,
    "pyqtgraph": mock_pg,
    "sounddevice": MagicMock(),
}

@pytest.fixture(autouse=True)
def mock_deps():
    with patch.dict(sys.modules, mock_modules):
        # Clean import
        if "src.gui.widgets.spectrum_analyzer" in sys.modules:
            del sys.modules["src.gui.widgets.spectrum_analyzer"]
        yield

def test_spectrum_rms_sine_accuracy():
    from src.gui.widgets.spectrum_analyzer import SpectrumAnalyzer, SpectrumAnalyzerWidget

    # Mock AudioEngine
    mock_engine = MagicMock()
    mock_engine.sample_rate = 48000
    mock_engine.calibration = MagicMock()
    mock_engine.calibration.input_sensitivity = 1.0
    mock_engine.calibration.get_input_offset_db.return_value = 0.0
    mock_engine.calibration.get_spl_offset_db.return_value = 0.0

    # Init SpectrumAnalyzer
    sa = SpectrumAnalyzer(mock_engine)
    sa.set_buffer_size(4096)
    sa.start_analysis()

    # Init Widget
    widget = SpectrumAnalyzerWidget(sa)

    # Capture label updates
    # widget.overall_label is a Mock object

    # Generate Sine Wave 1kHz, Amplitude 1.0 (Peak 0dBFS)
    fs = 48000
    N = 4096
    t = np.arange(N) / fs
    sig = 1.0 * np.sin(2 * np.pi * 1000 * t)

    # Fill buffer
    if sa.input_data.shape[0] < N:
        sa.input_data = np.zeros((N, 2))
    sa.input_data[:, 0] = sig
    sa.input_data[:, 1] = sig
    sa.write_head = 0

    # Set Weighting to Z (Flat)
    sa.weighting = "Z"
    sa.multitaper_enabled = False
    sa.analysis_mode = "Spectrum"

    # Call update_plot
    widget.update_plot()

    # Check Overall Label
    # Expected: 20*log10(1/sqrt(2)) = -3.01 dB

    # Get the last call to setText
    # widget.overall_label.setText.call_args[0][0]

    assert widget.overall_label.setText.called
    text = widget.overall_label.setText.call_args[0][0]
    print(f"Label Text: {text}")

    # Format: "Overall: -3.0 dBFS(Z)"
    match = re.search(r"Overall:\s*([\d\.-]+)\s*dBFS", text)
    assert match is not None
    val = float(match.group(1))

    print(f"Measured RMS dB: {val}")

    # Check accuracy
    assert val == pytest.approx(-3.01, abs=0.2)

def test_spectrum_rms_silence():
    from src.gui.widgets.spectrum_analyzer import SpectrumAnalyzer, SpectrumAnalyzerWidget

    mock_engine = MagicMock()
    mock_engine.sample_rate = 48000
    mock_engine.calibration = MagicMock()
    mock_engine.calibration.input_sensitivity = 1.0
    mock_engine.calibration.get_input_offset_db.return_value = 0.0
    mock_engine.calibration.get_spl_offset_db.return_value = 0.0

    sa = SpectrumAnalyzer(mock_engine)
    sa.set_buffer_size(4096)
    sa.start_analysis()

    widget = SpectrumAnalyzerWidget(sa)

    # Silence
    sa.input_data.fill(0)
    sa.write_head = 0

    widget.update_plot()

    assert widget.overall_label.setText.called
    text = widget.overall_label.setText.call_args[0][0]

    match = re.search(r"Overall:\s*([\d\.-]+)\s*dBFS", text)
    assert match is not None
    val = float(match.group(1))

    print(f"Silence RMS dB: {val}")
    assert val < -100.0
