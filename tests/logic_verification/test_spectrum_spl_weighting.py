import sys
import numpy as np
from unittest.mock import MagicMock, patch
import pytest
import re

# Mock dependencies
mock_modules = {
    "PyQt6": MagicMock(),
    "PyQt6.QtCore": MagicMock(),
    "PyQt6.QtGui": MagicMock(),
    "PyQt6.QtWidgets": MagicMock(),
    "pyqtgraph": MagicMock(),
    "sounddevice": MagicMock(),
}

class MockQThread:
    def __init__(self, parent=None): pass
    def start(self): pass
    def wait(self): pass
    def requestInterruption(self): pass
    def isInterruptionRequested(self): return False
    def msleep(self, ms): pass

mock_modules["PyQt6.QtCore"].QThread = MockQThread
mock_modules["PyQt6.QtCore"].pyqtSignal = lambda *args: MagicMock()

@pytest.fixture(autouse=True)
def mock_deps():
    with patch.dict(sys.modules, mock_modules):
        if "src.gui.widgets.spectrum_analyzer" in sys.modules:
            del sys.modules["src.gui.widgets.spectrum_analyzer"]
        yield

def test_spectrum_weighting_at_100hz():
    from src.gui.widgets.spectrum_analyzer import SpectrumAnalyzer, SpectrumAnalysisWorker

    mock_engine = MagicMock()
    mock_engine.sample_rate = 48000
    mock_engine.calibration = MagicMock()
    mock_engine.calibration.input_sensitivity = 1.0
    mock_engine.calibration.get_input_offset_db.return_value = 0.0
    mock_engine.calibration.get_spl_offset_db.return_value = 0.0

    sa = SpectrumAnalyzer(mock_engine)
    sa.set_buffer_size(4096)
    sa.start_analysis()

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

    worker = SpectrumAnalysisWorker(sa)

    # 1. Test Z-weighting (Reference)
    sa.weighting = "Z"
    result_z = worker.process_cycle()
    val_z = result_z.overall_db
    print(f"Z-weighted RMS at 100Hz: {val_z} dBFS")
    assert val_z == pytest.approx(-3.01, abs=0.2)

    # 2. Test A-weighting
    # A-weighting at 100Hz is approx -19.14 dB
    sa.weighting = "A"
    # Reset averaging to avoid smoothing influence
    sa.reset_averaging_request = True
    result_a = worker.process_cycle()
    val_a = result_a.overall_db
    print(f"A-weighted RMS at 100Hz: {val_a} dBFS")
    assert val_a == pytest.approx(-3.01 - 19.14, abs=0.5)

    assert "A" in result_a.unit_display

    # 3. Test C-weighting
    sa.weighting = "C"
    sa.reset_averaging_request = True
    result_c = worker.process_cycle()
    val_c = result_c.overall_db
    print(f"C-weighted RMS at 100Hz: {val_c} dBFS")
    assert val_c == pytest.approx(-3.01 - 0.3, abs=0.2)

    assert "C" in result_c.unit_display

def test_spectrum_spl_offset():
    from src.gui.widgets.spectrum_analyzer import SpectrumAnalyzer, SpectrumAnalysisWorker

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

    worker = SpectrumAnalysisWorker(sa)

    result_dbfs = worker.process_cycle()
    val_dbfs = result_dbfs.overall_db
    assert val_dbfs == pytest.approx(-3.01, abs=0.2)

    # Switch to SPL
    sa.display_unit = "dB SPL"
    sa.reset_averaging_request = True # Force reset if needed

    result_spl = worker.process_cycle()
    val_spl = result_spl.overall_db
    print(f"SPL RMS (Z): {val_spl}")

    # Expected: -3.01 + 94.0 = 90.99
    assert val_spl == pytest.approx(-3.01 + 94.0, abs=0.2)
    assert "dB SPL" in result_spl.unit_display

    # Test SPL with A-weighting at 1kHz (A~0dB)
    sa.weighting = "A"
    sa.reset_averaging_request = True

    result_spl_a = worker.process_cycle()
    val_spl_a = result_spl_a.overall_db
    print(f"SPL RMS (A): {val_spl_a}")
    assert val_spl_a == pytest.approx(-3.01 + 94.0, abs=0.2)

    assert "A" in result_spl_a.unit_display
