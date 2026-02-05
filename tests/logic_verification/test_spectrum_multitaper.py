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

def test_spectrum_multitaper_sine_accuracy(qtbot):
    """
    Verify that Overall Weighted RMS is accurate for a Sine Wave (0dBFS)
    when Multitaper is enabled.
    Expected RMS for Full Scale Sine is -3.01 dB.
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

    # Generate Sine Wave 1kHz, Amplitude 1.0 (Peak 0dBFS)
    fs = 48000
    N = 4096
    t = np.arange(N) / fs
    sig = 1.0 * np.sin(2 * np.pi * 1000 * t)

    # Fill buffer
    sa.input_data[:, 0] = sig
    sa.input_data[:, 1] = sig
    sa.write_head = 0

    # Set Weighting to Z (Flat)
    sa.weighting = "Z"

    # Enable Multitaper
    sa.multitaper_enabled = True
    sa.analysis_mode = "Spectrum"

    # Call update_plot
    widget.update_plot()

    # Check Overall Label
    # Expected: 20*log10(1/sqrt(2)) = -3.01 dB
    text = widget.overall_label.text()
    print(f"Label Text: {text}")

    # Format: "Overall: -3.0 dBFS(Z)"
    match = re.search(r"Overall:\s*([\d\.-]+)\s*dBFS", text)
    assert match is not None
    val = float(match.group(1))

    print(f"Measured RMS dB: {val}")

    # Check accuracy
    # Multitaper should also yield correct RMS for sine
    assert val == pytest.approx(-3.01, abs=0.5)
