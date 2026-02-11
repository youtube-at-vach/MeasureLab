import sys
import numpy as np
from unittest.mock import MagicMock, patch
import pytest

# Mock dependencies
mock_modules = {
    "PyQt6": MagicMock(),
    "PyQt6.QtCore": MagicMock(),
    "PyQt6.QtGui": MagicMock(),
    "PyQt6.QtWidgets": MagicMock(),
    "pyqtgraph": MagicMock(),
    "sounddevice": MagicMock(),
}

# We need QThread from QtCore to be a class we can inherit if SpectrumAnalysisWorker inherits it
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
        # Clean import
        if "src.gui.widgets.spectrum_analyzer" in sys.modules:
            del sys.modules["src.gui.widgets.spectrum_analyzer"]
        yield

def test_spectrum_rms_sine_accuracy():
    from src.gui.widgets.spectrum_analyzer import SpectrumAnalyzer, SpectrumAnalysisWorker

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

    # Init Worker
    worker = SpectrumAnalysisWorker(sa)

    # Process cycle
    result = worker.process_cycle()

    assert result is not None
    val = result.overall_db
    print(f"Measured RMS dB: {val}")

    # Expected: 20*log10(1/sqrt(2)) = -3.01 dB
    assert val == pytest.approx(-3.01, abs=0.2)

def test_spectrum_rms_silence():
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

    # Silence
    sa.input_data.fill(0)
    sa.write_head = 0

    worker = SpectrumAnalysisWorker(sa)
    result = worker.process_cycle()

    assert result is not None
    val = result.overall_db

    print(f"Silence RMS dB: {val}")
    assert val < -100.0
