from unittest.mock import MagicMock, patch

import pytest

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


@pytest.mark.parametrize(
    ("imd_index", "sweep_index", "imd_signal_type"),
    [
        (2, 1, "smpte"),
        (3, 2, "ccif"),
    ],
)
def test_sweep_mode_uses_sine_and_restores_realtime_imd(
    qtbot, mock_audio_engine, imd_index, sweep_index, imd_signal_type
):
    analyzer = DistortionAnalyzer(mock_audio_engine)
    widget = DistortionAnalyzerWidget(analyzer)
    qtbot.addWidget(widget)

    widget.out_mode_combo.setCurrentIndex(imd_index)
    assert analyzer.signal_type == imd_signal_type

    widget.mode_combo.setCurrentIndex(sweep_index)

    assert widget.out_mode_combo.currentIndex() == 1
    assert not widget.out_mode_combo.isEnabled()
    assert analyzer.output_enabled
    assert analyzer.signal_type == "sine"

    widget.mode_combo.setCurrentIndex(0)

    assert widget.out_mode_combo.isEnabled()
    assert widget.out_mode_combo.currentIndex() == imd_index
    assert analyzer.signal_type == imd_signal_type


def test_start_sweep_defensively_restores_sine_state(qtbot, mock_audio_engine):
    analyzer = DistortionAnalyzer(mock_audio_engine)
    analyzer.start_analysis = MagicMock()
    widget = DistortionAnalyzerWidget(analyzer)
    qtbot.addWidget(widget)
    widget.mode_combo.setCurrentIndex(1)

    analyzer.signal_type = "smpte"
    analyzer.output_enabled = False

    with patch("src.gui.widgets.distortion_analyzer.SweepWorker") as worker_class:
        widget.start_sweep(1)

    assert analyzer.signal_type == "sine"
    assert analyzer.output_enabled
    analyzer.start_analysis.assert_called_once_with()
    worker_class.assert_called_once()
    worker_class.return_value.start.assert_called_once_with()
