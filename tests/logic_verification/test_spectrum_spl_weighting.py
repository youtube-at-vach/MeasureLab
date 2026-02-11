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

# Specific mocks
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
mock_pg.PlotWidget.return_value.scene.return_value = MagicMock()

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
        if "src.gui.widgets.spectrum_analyzer" in sys.modules:
            del sys.modules["src.gui.widgets.spectrum_analyzer"]
        yield

def extract_overall_db(widget):
    # Check if setText was called
    if widget.overall_label.setText.called:
        text = widget.overall_label.setText.call_args[0][0]
        match = re.search(r"Overall:\s*([\d\.-]+)\s*", text)
        if match:
            return float(match.group(1))
    return None

def test_spectrum_weighting_at_100hz():
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

    # Generate Sine Wave 100Hz, Amplitude 1.0 (Peak 0dBFS)
    fs = 48000
    N = 4096
    t = np.arange(N) / fs
    sig = 1.0 * np.sin(2 * np.pi * 100 * t)

    # Fill buffer
    if sa.input_data.shape[0] < N:
        sa.input_data = np.zeros((N, 2))
    sa.input_data[:, 0] = sig
    sa.input_data[:, 1] = sig
    sa.write_head = 0
    sa.analysis_mode = "Spectrum"
    sa.multitaper_enabled = False

    # 1. Test Z-weighting (Reference)
    sa.weighting = "Z"
    widget.update_plot()
    val_z = extract_overall_db(widget)
    print(f"Z-weighted RMS at 100Hz: {val_z} dBFS")
    assert val_z == pytest.approx(-3.01, abs=0.2)

    # 2. Test A-weighting
    # A-weighting at 100Hz is approx -19.14 dB
    sa.weighting = "A"
    widget.update_plot()
    val_a = extract_overall_db(widget)
    print(f"A-weighted RMS at 100Hz: {val_a} dBFS")
    assert val_a == pytest.approx(-3.01 - 19.14, abs=0.5)

    text = widget.overall_label.setText.call_args[0][0]
    assert "dBFS(A)" in text

    # 3. Test C-weighting
    sa.weighting = "C"
    widget.update_plot()
    val_c = extract_overall_db(widget)
    print(f"C-weighted RMS at 100Hz: {val_c} dBFS")
    assert val_c == pytest.approx(-3.01 - 0.3, abs=0.2)

    text = widget.overall_label.setText.call_args[0][0]
    assert "dBFS(C)" in text

def test_spectrum_spl_offset():
    from src.gui.widgets.spectrum_analyzer import SpectrumAnalyzer, SpectrumAnalyzerWidget

    mock_engine = MagicMock()
    mock_engine.sample_rate = 48000
    mock_engine.calibration = MagicMock()
    mock_engine.calibration.input_sensitivity = 1.0
    mock_engine.calibration.get_input_offset_db.return_value = 0.0
    # Set SPL offset to +94 dB
    mock_engine.calibration.get_spl_offset_db.return_value = 94.0

    sa = SpectrumAnalyzer(mock_engine)
    sa.set_buffer_size(4096)
    sa.start_analysis()

    widget = SpectrumAnalyzerWidget(sa)

    # Generate Sine Wave 1kHz, Amplitude 1.0 (Peak 0dBFS)
    fs = 48000
    N = 4096
    t = np.arange(N) / fs
    sig = 1.0 * np.sin(2 * np.pi * 1000 * t)

    sa.input_data[:, 0] = sig
    sa.input_data[:, 1] = sig
    sa.write_head = 0
    sa.analysis_mode = "Spectrum"
    sa.weighting = "Z"
    sa.display_unit = "dBFS"

    widget.update_plot()
    val_dbfs = extract_overall_db(widget)
    assert val_dbfs == pytest.approx(-3.01, abs=0.2)

    # Switch to SPL
    sa.display_unit = "dB SPL"
    widget.update_plot()
    val_spl = extract_overall_db(widget)
    print(f"SPL RMS (Z): {val_spl}")

    # Expected: -3.01 + 94.0 = 90.99
    assert val_spl == pytest.approx(-3.01 + 94.0, abs=0.2)
    text = widget.overall_label.setText.call_args[0][0]
    assert "dB SPL(Z)" in text

    # Test SPL with A-weighting at 1kHz (A~0dB)
    sa.weighting = "A"
    widget.update_plot()
    val_spl_a = extract_overall_db(widget)
    print(f"SPL RMS (A): {val_spl_a}")
    assert val_spl_a == pytest.approx(-3.01 + 94.0, abs=0.2)

    text = widget.overall_label.setText.call_args[0][0]
    assert "dB SPL(A)" in text
