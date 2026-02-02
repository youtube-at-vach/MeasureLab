import sys
import os
import numpy as np
from unittest.mock import MagicMock
import pytest
import re

# Ensure sounddevice is mocked
if 'sounddevice' not in sys.modules:
    sys.modules['sounddevice'] = MagicMock()

# Add src to path
sys.path.append(os.path.join(os.path.dirname(__file__), '../../'))

from src.gui.widgets.spectrum_analyzer import SpectrumAnalyzer, SpectrumAnalyzerWidget
from PyQt6.QtWidgets import QApplication

# Initialize QApplication if not exists
app = QApplication.instance()
if app is None:
    app = QApplication([])

def extract_overall_db(widget):
    text = widget.overall_label.text()
    match = re.search(r"Overall:\s*([\d\.-]+)\s*", text)
    if match:
        return float(match.group(1))
    return None

def test_spectrum_weighting_at_100hz(qtbot):
    """
    Verify that Overall Weighted RMS applies A and C weighting correctly at 100Hz.
    100Hz is a good test frequency because A-weighting has significant attenuation (~-19.1dB)
    while C-weighting is nearly flat (~-0.3dB).
    """
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
    qtbot.addWidget(widget)

    # Generate Sine Wave 100Hz, Amplitude 1.0 (Peak 0dBFS)
    # RMS = -3.01 dBFS (Z)
    fs = 48000
    N = 4096
    t = np.arange(N) / fs
    sig = 1.0 * np.sin(2 * np.pi * 100 * t)

    # Fill buffer
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
    # So expected RMS is -3.01 - 19.14 = -22.15 dB
    sa.weighting = "A"
    widget.update_plot()
    val_a = extract_overall_db(widget)
    print(f"A-weighted RMS at 100Hz: {val_a} dBFS")
    assert val_a == pytest.approx(-3.01 - 19.14, abs=0.5)
    assert "dBFS(A)" in widget.overall_label.text()

    # 3. Test C-weighting
    # C-weighting at 100Hz is approx -0.3 dB
    # So expected RMS is -3.01 - 0.3 = -3.31 dB
    sa.weighting = "C"
    widget.update_plot()
    val_c = extract_overall_db(widget)
    print(f"C-weighted RMS at 100Hz: {val_c} dBFS")
    assert val_c == pytest.approx(-3.01 - 0.3, abs=0.2)
    assert "dBFS(C)" in widget.overall_label.text()

def test_spectrum_spl_offset(qtbot):
    """
    Verify that selecting 'dB SPL' adds the SPL offset to the Overall value.
    """
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
    qtbot.addWidget(widget)

    # Generate Sine Wave 1kHz, Amplitude 1.0 (Peak 0dBFS)
    # RMS = -3.01 dBFS
    fs = 48000
    N = 4096
    t = np.arange(N) / fs
    sig = 1.0 * np.sin(2 * np.pi * 1000 * t)

    sa.input_data[:, 0] = sig
    sa.input_data[:, 1] = sig
    sa.write_head = 0
    sa.analysis_mode = "Spectrum"
    sa.weighting = "Z"
    sa.display_unit = "dBFS" # Start with dBFS

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
    assert "dB SPL(Z)" in widget.overall_label.text()

    # Test SPL with A-weighting at 1kHz (A~0dB)
    sa.weighting = "A"
    widget.update_plot()
    val_spl_a = extract_overall_db(widget)
    print(f"SPL RMS (A): {val_spl_a}")
    assert val_spl_a == pytest.approx(-3.01 + 94.0, abs=0.2) # 1kHz A=0dB
    assert "dB SPL(A)" in widget.overall_label.text()
