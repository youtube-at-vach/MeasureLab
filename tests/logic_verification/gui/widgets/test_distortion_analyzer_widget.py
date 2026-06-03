import pytest
import warnings
from unittest.mock import MagicMock

from src.gui.widgets.distortion_analyzer import (
    DistortionAnalyzer,
    DistortionAnalyzerWidget,
)


@pytest.fixture
def mock_audio_engine():
    engine = MagicMock()
    engine.sample_rate = 48000
    engine.calibration.output_gain = 1.0
    return engine


def test_distortion_analyzer_widget_sweep_unit_switch_warning(qtbot, mock_audio_engine):
    analyzer = DistortionAnalyzer(mock_audio_engine)
    widget = DistortionAnalyzerWidget(analyzer)
    qtbot.addWidget(widget)

    # Change to Frequency Sweep Mode
    widget.mode_combo.setCurrentIndex(1)  # Frequency Sweep

    # Add dummy results
    analyzer.sweep_results = [
        {"sweep_param": 100.0, "thdn_percent": 0.1, "thdn_db": -60.0},
        {"sweep_param": 1000.0, "thdn_percent": 0.01, "thdn_db": -80.0},
    ]

    # Initialize Y unit to dB
    widget.sweep_y_unit_combo.setCurrentIndex(0)  # dB
    widget.on_sweep_result(None)  # Draw initial plot

    # Switch from dB to Percent and check for warnings
    with warnings.catch_warnings(record=True) as caught_warnings:
        warnings.simplefilter("always")

        # Trigger switch to Percent (%)
        widget.sweep_y_unit_combo.setCurrentIndex(1)

        # Check if there were any RuntimeWarnings about all-NaN slices
        for w in caught_warnings:
            if issubclass(w.category, RuntimeWarning) and "All-NaN" in str(w.message):
                pytest.fail(f"Warning raised: {w.message}")


def test_aes17_calibration_button(qtbot, mock_audio_engine):
    analyzer = DistortionAnalyzer(mock_audio_engine)
    analyzer.is_running = True
    widget = DistortionAnalyzerWidget(analyzer)
    qtbot.addWidget(widget)

    # 1. Switch to AES17 mode
    widget.out_mode_combo.setCurrentIndex(4)  # AES17 Dynamic Range

    # Verify buttons and initial settings
    assert analyzer.signal_type == "aes17"
    assert not analyzer.aes17_calibrating

    # 2. Toggle calibration ON
    widget.aes17_cal_btn.click()
    assert analyzer.aes17_calibrating
    assert "Calibrating" in widget.aes17_cal_btn.text()
    assert widget.thdn_title_label.text() == "Input Level:"

    # 3. Toggle calibration OFF
    widget.aes17_cal_btn.click()
    assert not analyzer.aes17_calibrating
    assert "Calibrate" in widget.aes17_cal_btn.text()
    assert widget.thdn_title_label.text() == "Dyn Range:"

    # 4. Toggle ON again, then switch mode to Sine
    widget.aes17_cal_btn.click()
    assert analyzer.aes17_calibrating

    widget.out_mode_combo.setCurrentIndex(1)  # Sine Wave
    assert not analyzer.aes17_calibrating
    assert not widget.aes17_cal_btn.isChecked()

    # 5. Verify calibration level detection and color feedback
    widget.out_mode_combo.setCurrentIndex(4)  # Switch back to AES17
    widget.aes17_cal_btn.click()  # Calibration ON
    assert analyzer.aes17_calibrating

    # Test "CLIP!" status
    results_clip = {
        "type": "harmonics",
        "basic_wave": {"amplitude_dbfs": 0.2, "frequency": 997.0},
        "thdn_db": -50.0,
        "thdn_percent": 0.316,
        "sinad_db": 50.0,
        "harmonics": [],
    }
    widget.on_worker_result(results_clip)
    assert "CLIP!" in widget.thdn_db_label.text()
    assert "color: #d32f2f" in widget.thdn_db_label.styleSheet()

    # Test "OK - Optimal" status
    results_optimal = {
        "type": "harmonics",
        "basic_wave": {"amplitude_dbfs": -1.5, "frequency": 997.0},
        "thdn_db": -50.0,
        "thdn_percent": 0.316,
        "sinad_db": 50.0,
        "harmonics": [],
    }
    widget.on_worker_result(results_optimal)
    assert "Optimal" in widget.thdn_db_label.text()
    assert "color: #388e3c" in widget.thdn_db_label.styleSheet()

    # Test "OK" status
    results_ok = {
        "type": "harmonics",
        "basic_wave": {"amplitude_dbfs": -4.0, "frequency": 997.0},
        "thdn_db": -50.0,
        "thdn_percent": 0.316,
        "sinad_db": 50.0,
        "harmonics": [],
    }
    widget.on_worker_result(results_ok)
    assert "OK" in widget.thdn_db_label.text()
    assert "Optimal" not in widget.thdn_db_label.text()
    assert "color: #7cb342" in widget.thdn_db_label.styleSheet()

    # Test "Too Low" status
    results_low = {
        "type": "harmonics",
        "basic_wave": {"amplitude_dbfs": -12.0, "frequency": 997.0},
        "thdn_db": -50.0,
        "thdn_percent": 0.316,
        "sinad_db": 50.0,
        "harmonics": [],
    }
    widget.on_worker_result(results_low)
    assert "Too Low" in widget.thdn_db_label.text()
    assert "color: #f57c00" in widget.thdn_db_label.styleSheet()

    # Test reset status styles when calibration is toggled OFF
    widget.aes17_cal_btn.click()  # Calibration OFF
    results_normal = {
        "type": "harmonics",
        "basic_wave": {"amplitude_dbfs": -60.0, "frequency": 997.0},
        "thdn_db": -55.0,
        "thdn_percent": 0.178,
        "sinad_db": 55.0,
        "harmonics": [],
    }
    widget.on_worker_result(results_normal)
    assert widget.thdn_db_label.styleSheet() == ""
