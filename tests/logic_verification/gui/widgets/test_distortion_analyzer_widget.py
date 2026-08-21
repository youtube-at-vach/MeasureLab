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
    engine.calibration.output_gain_is_calibrated = False
    engine.calibration.input_sensitivity_is_calibrated = False
    engine.is_active.return_value = True
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


def test_uncalibrated_output_forces_dbfs_and_reports_conditions(qtbot, mock_audio_engine):
    analyzer = DistortionAnalyzer(mock_audio_engine)
    widget = DistortionAnalyzerWidget(analyzer)
    qtbot.addWidget(widget)

    widget._refresh_calibration_controls()

    assert widget.unit_combo.currentText() == "dBFS"
    for index in range(1, widget.unit_combo.count()):
        assert not widget.unit_combo.model().item(index).isEnabled()
    assert "UNCAL" in widget.status_conditions_label.text()

    mock_audio_engine.calibration.output_gain_is_calibrated = True
    mock_audio_engine.calibration.input_sensitivity_is_calibrated = True
    widget._refresh_calibration_controls()
    widget._update_status_display()

    for index in range(widget.unit_combo.count()):
        assert widget.unit_combo.model().item(index).isEnabled()
    assert "CAL" in widget.status_conditions_label.text()
    assert "UNCAL" not in widget.status_conditions_label.text()


def test_invalid_acquisition_clears_measurement_displays(qtbot, mock_audio_engine):
    analyzer = DistortionAnalyzer(mock_audio_engine)
    analyzer.is_running = True
    analyzer.invalidate_measurement("Input clipping detected", flag="input_clipping")
    widget = DistortionAnalyzerWidget(analyzer)
    qtbot.addWidget(widget)

    widget.on_worker_result(
        {
            "type": "harmonics",
            "basic_wave": {"amplitude_dbfs": -1.0, "frequency": 1000.0},
            "thd_percent": 0.01,
            "thdn_percent": 0.02,
            "thdn_db": -74.0,
            "sinad_db": 74.0,
            "harmonics": [],
        }
    )

    assert widget.thdn_label.text() == "INVALID"
    assert not widget.integrity_warning_label.isHidden()
    assert "Input clipping detected" in widget.integrity_warning_label.text()
    assert analyzer.current_result["measurement_valid"] is False


@pytest.mark.parametrize(
    ("measurement", "f1", "f2", "ratio"),
    [
        ("smpte", 60.0, 7000.0, 4.0),
        ("din", 250.0, 8000.0, 4.0),
        ("ccif", 19000.0, 20000.0, 1.0),
    ],
)
def test_amplitude_sweep_selects_requested_imd_standard(
    qtbot, mock_audio_engine, measurement, f1, f2, ratio
):
    analyzer = DistortionAnalyzer(mock_audio_engine)
    analyzer.start_analysis = MagicMock()
    widget = DistortionAnalyzerWidget(analyzer)
    qtbot.addWidget(widget)
    widget.mode_combo.setCurrentIndex(2)
    widget.sweep_measurement_combo.setCurrentIndex(
        widget.sweep_measurement_combo.findData(measurement)
    )

    with patch("src.gui.widgets.distortion_analyzer.SweepWorker") as worker_class:
        worker_class.return_value.isRunning.return_value = False
        widget.start_sweep(2)

    assert analyzer.signal_type == measurement
    assert analyzer.imd_f1 == f1
    assert analyzer.imd_f2 == f2
    assert analyzer.imd_ratio == ratio


def test_guided_aes17_builds_machine_readable_report(qtbot, mock_audio_engine):
    analyzer = DistortionAnalyzer(mock_audio_engine)
    analyzer.is_running = True
    widget = DistortionAnalyzerWidget(analyzer)
    qtbot.addWidget(widget)

    widget.on_aes17_guide_toggled(True)
    widget._aes17_deadline = 0.0
    widget._advance_aes17_workflow(
        {"basic_wave": {"amplitude_dbfs": -1.5}, "thdn_db": -50.0}
    )
    assert widget._aes17_workflow_state == "measurement_wait"

    widget._aes17_deadline = 0.0
    widget._advance_aes17_workflow(
        {"basic_wave": {"amplitude_dbfs": -60.0}, "thdn_db": -55.0}
    )

    assert widget._aes17_workflow_state == "idle"
    assert analyzer.aes17_report is not None
    assert analyzer.aes17_report["schema"] == "measurelab.aes17_dynamic_range.v1"
    assert analyzer.aes17_report["dynamic_range_db"] == pytest.approx(115.0)
    assert analyzer.aes17_report["measurement_valid"] is True
    assert widget.aes17_save_btn.isEnabled()


def test_stability_log_records_validity_and_metrics(qtbot, mock_audio_engine):
    analyzer = DistortionAnalyzer(mock_audio_engine)
    widget = DistortionAnalyzerWidget(analyzer)
    qtbot.addWidget(widget)
    widget.stability_logging = True
    widget.stability_started_at = 1.0

    result = {
        "type": "harmonics",
        "basic_wave": {"amplitude_dbfs": -6.0, "frequency": 1000.0},
        "thd_db": -90.0,
        "thdn_db": -80.0,
        "sinad_db": 80.0,
    }
    widget._record_stability_sample(result)

    assert len(widget.stability_records) == 1
    assert widget.stability_records[0]["measurement_valid"] is True
    assert widget.stability_records[0]["noise_db"] < -80.0
    _, frequency_data = widget.stability_frequency_curve.getData()
    assert frequency_data.tolist() == [1000.0]

    analyzer.invalidate_measurement("Audio stream XRUN", flag="xrun")
    widget.stability_last_recorded_at = 0.0
    widget._record_stability_sample(result)

    assert len(widget.stability_records) == 2
    assert widget.stability_records[1]["measurement_valid"] is False
    assert widget.stability_records[1]["invalid_reasons"] == "Audio stream XRUN"


def test_comparison_excludes_invalid_sweep_points(qtbot, mock_audio_engine):
    analyzer = DistortionAnalyzer(mock_audio_engine)
    widget = DistortionAnalyzerWidget(analyzer)
    qtbot.addWidget(widget)
    widget.mode_combo.setCurrentIndex(2)
    analyzer.sweep_results = [
        {
            "sweep_param": -30.0,
            "thdn_db": -80.0,
            "measurement_valid": True,
        },
        {
            "sweep_param": -20.0,
            "thdn_db": -10.0,
            "measurement_valid": False,
        },
    ]

    traces = widget.get_comparable_data()

    assert len(traces) == 1
    assert traces[0].x_data == [-30.0]
    assert traces[0].y_data == [-80.0]
    assert traces[0].metadata["invalid_point_count"] == 1


def test_measurement_first_layout_keeps_controls_narrow(qtbot, mock_audio_engine):
    analyzer = DistortionAnalyzer(mock_audio_engine)
    widget = DistortionAnalyzerWidget(analyzer)
    qtbot.addWidget(widget)

    assert widget.control_widget.maximumWidth() == 340
    assert widget.layout().stretch(0) == 1
    assert widget.layout().stretch(1) == 4


def test_amplitude_sweep_negative_db_uses_linear_step(qtbot, mock_audio_engine):
    analyzer = DistortionAnalyzer(mock_audio_engine)
    widget = DistortionAnalyzerWidget(analyzer)
    qtbot.addWidget(widget)
    widget.mode_combo.setCurrentIndex(2)
    widget.sweep_start_spin.setValue(-60.0)

    widget.sweep_start_spin.stepBy(1)

    assert widget.sweep_start_spin.value() == -59.0
