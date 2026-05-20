import os
import json
import numpy as np
import pytest
from unittest.mock import MagicMock, patch
from PyQt6.QtWidgets import QMessageBox

from src.gui.widgets.arbitrary_harmonic_generator import (
    ArbitraryHarmonicGenerator,
    MAX_HARMONICS
)

@pytest.fixture
def generator_widget(qtbot):
    engine = MagicMock()
    engine.sample_rate = 48000
    engine.calibration.output_gain = 1.0
    engine.register_callback = MagicMock(return_value="mock_callback_id")
    engine.unregister_callback = MagicMock()

    module = ArbitraryHarmonicGenerator(engine)
    widget = module.get_widget()
    qtbot.addWidget(widget)
    return widget, module, engine

def test_initialization(generator_widget):
    widget, module, _engine = generator_widget

    assert module.name == "Arbitrary Harmonic Generator"
    assert "distortion compensation" in module.description.lower()

    # Widget UI Defaults
    assert widget.freq_spin.value() == 1000.0
    assert widget.amp_spin.value() == pytest.approx(-6.02, abs=1e-2)
    assert widget.phase_spin.value() == 0.0
    assert widget.spin_max_harm.value() == 20
    assert widget.table.rowCount() == 19  # Max 20 harmonics means rows for 2nd to 20th
    assert not widget.chk_comp_enable.isEnabled()

def test_fundamental_and_harmonics_signal_generation(generator_widget):
    widget, module, engine = generator_widget

    # Start generation to capture callback
    module.start_generation()
    assert engine.register_callback.called
    callback = engine.register_callback.call_args[0][0]

    # Set parameters: 1000 Hz, 0.5 amplitude
    module.gen_frequency = 1000.0
    module.gen_amplitude = 0.5
    module.gen_phase = 90.0  # Phase shift
    module.max_harmonic = 5

    # Set 3rd harmonic to -20 dBFS (0.1 linear) and 180 degrees
    module.harmonics_amps[2] = 0.1
    module.harmonics_phases_deg[2] = 180.0

    frames = 1024
    outdata = np.zeros((frames, 2))

    # Call the callback
    callback(None, outdata, frames, None, None)

    # Reconstruct the expected mathematical signal
    t = np.arange(frames) / 48000.0
    # Fundamental: A_1 * sin(w * t + phase_1)
    # phase_1 is 90 deg = pi/2 rad, so sin(wt + pi/2) = cos(wt)
    expected_fund = 0.5 * np.cos(2 * np.pi * 1000.0 * t)

    # 3rd Harmonic: A_3 * sin(3 * w * t + phase_3)
    # phase_3 is 180 deg = pi rad, so sin(3wt + pi) = -sin(3wt)
    expected_h3 = 0.1 * np.sin(3 * 2 * np.pi * 1000.0 * t + np.pi)

    expected_total = expected_fund + expected_h3

    # outdata channel 0 and 1 should match
    np.testing.assert_allclose(outdata[:, 0], expected_total, atol=1e-6)
    np.testing.assert_allclose(outdata[:, 1], expected_total, atol=1e-6)

def test_compensation_signal_generation(generator_widget):
    widget, module, engine = generator_widget

    module.gen_frequency = 1000.0
    module.gen_amplitude = 0.5
    module.gen_phase = 0.0
    module.max_harmonic = 5

    # Enable compensation and set 2nd harmonic complex coefficient
    module.compensation_enabled = True
    # c_2 = 0.03 + 0.04j
    module.compensation_coeffs[1] = 0.03 + 0.04j

    module.start_generation()
    callback = engine.register_callback.call_args[0][0]

    frames = 1024
    outdata = np.zeros((frames, 2))
    callback(None, outdata, frames, None, None)

    t = np.arange(frames) / 48000.0
    # Expected: fundamental + compensation
    # Compensation component: c.real * cos(n * wt) + c.imag * sin(n * wt)
    expected_fund = 0.5 * np.sin(2 * np.pi * 1000.0 * t)
    expected_comp_h2 = 0.03 * np.cos(2 * 2 * np.pi * 1000.0 * t) + 0.04 * np.sin(2 * 2 * np.pi * 1000.0 * t)
    expected_total = expected_fund + expected_comp_h2

    np.testing.assert_allclose(outdata[:, 0], expected_total, atol=1e-6)

def test_export_and_import_compensation(generator_widget, tmp_path):
    widget, module, _engine = generator_widget

    # Mock data inside module for lockin analyzer mock context
    # Let's say we have dummy compensation coefficients from a calibration
    mock_coeffs = np.zeros(MAX_HARMONICS, dtype=complex)
    mock_coeffs[1] = 0.01 - 0.02j  # H2
    mock_coeffs[2] = -0.005 + 0.008j  # H3

    # Create a mock analyzer module / widget context or call on_export_comp via a patch
    from src.gui.widgets.lockin_harmonic_analyzer import LockInHarmonicWidget
    analyzer_engine = MagicMock()
    analyzer_engine.sample_rate = 48000
    analyzer_module = MagicMock()
    analyzer_module.audio_engine = analyzer_engine
    analyzer_module.gen_frequency = 1000.0
    analyzer_module.max_harmonic = 10
    analyzer_module.comp_max_harmonic = 10
    analyzer_module.output_channel = 2
    analyzer_module.compensation_enabled = False
    analyzer_module.compensation_coeffs = mock_coeffs

    analyzer_widget = LockInHarmonicWidget(analyzer_module)

    temp_file = os.path.join(tmp_path, "comp.json")

    # Export using patch to bypass QFileDialog
    with patch("PyQt6.QtWidgets.QFileDialog.getSaveFileName", return_value=(temp_file, "JSON Files (*.json)")):
        analyzer_widget.on_export_comp()

    # Confirm file was written
    assert os.path.exists(temp_file)
    with open(temp_file, "r") as f:
        data = json.load(f)

    assert data["format"] == "MeasureLab_Harmonic_Compensation"
    assert data["fundamental_frequency"] == 1000.0
    assert data["max_harmonic"] == 10
    assert len(data["compensation_coeffs"]) > 0

    # Import the data in our ArbitraryHarmonicWidget
    with patch("PyQt6.QtWidgets.QFileDialog.getOpenFileName", return_value=(temp_file, "JSON Files (*.json)")):
        widget.on_load_compensation()

    # Check imported coefficients
    assert module.compensation_enabled
    assert widget.chk_comp_enable.isEnabled()
    assert widget.chk_comp_enable.isChecked()
    assert module.compensation_freq == 1000.0
    assert module.compensation_coeffs[1] == pytest.approx(0.01 - 0.02j)
    assert module.compensation_coeffs[2] == pytest.approx(-0.005 + 0.008j)

def test_frequency_mismatch_warning(generator_widget, tmp_path):
    widget, module, _engine = generator_widget

    # Create a calibration JSON file for 1000 Hz fundamental frequency
    temp_file = os.path.join(tmp_path, "comp_mismatch.json")
    data = {
        "format": "MeasureLab_Harmonic_Compensation",
        "version": "1.0",
        "fundamental_frequency": 1000.0,
        "max_harmonic": 5,
        "compensation_coeffs": [
            {"harmonic": 2, "real": 0.01, "imag": -0.02, "amp_linear": 0.022, "phase_deg": -63.4}
        ]
    }
    with open(temp_file, "w") as f:
        json.dump(data, f)

    # Set widget frequency spin to 2000.0 Hz (which causes mismatch warning)
    widget.freq_spin.setValue(2000.0)

    # 1. Test clicking "No" on warning dialog
    with patch("PyQt6.QtWidgets.QFileDialog.getOpenFileName", return_value=(temp_file, "JSON Files (*.json)")), \
         patch("PyQt6.QtWidgets.QMessageBox.warning", return_value=QMessageBox.StandardButton.No) as mock_warn:
        widget.on_load_compensation()
        assert mock_warn.called
        assert not module.compensation_enabled  # Should NOT apply

    # 2. Test clicking "Yes" on warning dialog
    with patch("PyQt6.QtWidgets.QFileDialog.getOpenFileName", return_value=(temp_file, "JSON Files (*.json)")), \
         patch("PyQt6.QtWidgets.QMessageBox.warning", return_value=QMessageBox.StandardButton.Yes) as mock_warn:
        widget.on_load_compensation()
        assert mock_warn.called
        assert module.compensation_enabled  # Should apply anyway
