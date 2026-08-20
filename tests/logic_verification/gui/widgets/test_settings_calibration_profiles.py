from unittest.mock import MagicMock, patch

import pytest
from PyQt6.QtWidgets import QMessageBox

from src.core.calibration import CalibrationManager
from src.core.config_manager import ConfigManager
from src.gui.widgets.settings import SettingsWidget


def _make_config():
    config = MagicMock(spec=ConfigManager)
    config.get_language.return_value = "en"
    config.get_theme.return_value = "system"
    config.get_screenshot_output_dir.return_value = "/tmp"
    config.is_offline_mode.return_value = False
    config.get_offline_sample_rate.return_value = 48000
    config.get_pipewire_jack_resident.return_value = False
    config.get_audio_config.return_value = {}
    config.is_dithering_enabled.return_value = False
    config.get_dithering_bit_depth.return_value = "16"
    config.is_audio_engine_64bit.return_value = False
    return config


@pytest.fixture
def profile_settings(qtbot, tmp_path):
    engine = MagicMock()
    engine.get_host_apis.return_value = [{"name": "CoreAudio", "index": 0}]
    engine.list_devices.return_value = [
        {
            "name": "Measurement Input",
            "hostapi": 0,
            "hostapi_name": "CoreAudio",
            "max_input_channels": 2,
            "max_output_channels": 0,
        },
        {
            "name": "Measurement Output",
            "hostapi": 0,
            "hostapi_name": "CoreAudio",
            "max_input_channels": 0,
            "max_output_channels": 2,
        },
    ]
    engine.input_device = 0
    engine.output_device = 1
    engine.sample_rate = 48000
    engine.block_size = 1024
    engine.input_channel_mode = "stereo"
    engine.output_channel_mode = "stereo"
    engine.calibration = CalibrationManager(str(tmp_path / "calibration.json"))

    manager = MagicMock()
    manager.available_languages = {"en": "English"}
    manager.language = "en"
    with (
        patch("src.gui.widgets.settings.get_manager", return_value=manager),
        patch.object(SettingsWidget, "_get_current_host_api_index", return_value=0),
    ):
        widget = SettingsWidget(engine, _make_config())
    qtbot.addWidget(widget)
    return widget, engine


def test_empty_profile_state_is_explicit(profile_settings):
    widget, _engine = profile_settings

    assert widget.cal_profile_combo.count() == 1
    assert widget.cal_profile_combo.currentData() is None
    assert widget.new_prof_btn.isEnabled()
    assert widget.duplicate_prof_btn.isEnabled()
    assert not widget.rename_prof_btn.isEnabled()
    assert not widget.del_prof_btn.isEnabled()
    assert "not assigned" in widget.cal_profile_status_label.text()


def test_profile_metadata_labels_use_theme_text_color(profile_settings):
    widget, _engine = profile_settings

    assert "color:" not in widget.cal_profile_status_label.styleSheet()
    assert "color:" not in widget.cal_profile_device_label.styleSheet()


def test_new_profile_starts_uncalibrated_and_captures_both_devices(profile_settings):
    widget, engine = profile_settings
    engine.calibration.input_sensitivity = 2.0
    engine.calibration.input_sensitivity_is_calibrated = True
    engine.calibration.output_gain = 3.0
    engine.calibration.output_gain_is_calibrated = True

    with patch.object(
        widget,
        "_prompt_profile_name",
        return_value="Fresh Profile",
    ):
        widget.on_new_profile()

    profile = engine.calibration.get_profiles()["Fresh Profile"]
    assert engine.calibration.last_profile == "Fresh Profile"
    assert engine.calibration.input_sensitivity == 1.0
    assert engine.calibration.input_sensitivity_is_calibrated is False
    assert engine.calibration.output_gain_is_calibrated is False
    assert profile["input_device_name"] == "Measurement Input"
    assert profile["output_device_name"] == "Measurement Output"
    assert widget.cal_profile_combo.currentData() == "Fresh Profile"


def test_duplicate_and_rename_have_distinct_state_transitions(profile_settings):
    widget, engine = profile_settings
    engine.calibration.input_sensitivity = 2.5
    engine.calibration.input_sensitivity_is_calibrated = True

    with patch.object(widget, "_prompt_profile_name", return_value="Copy"):
        widget.on_duplicate_profile()

    assert engine.calibration.last_profile == "Copy"
    assert engine.calibration.get_profiles()["Copy"]["input_sensitivity"] == 2.5

    with patch.object(widget, "_prompt_profile_name", return_value="Renamed"):
        widget.on_rename_profile()

    assert engine.calibration.last_profile == "Renamed"
    assert "Copy" not in engine.calibration.get_profiles()
    assert engine.calibration.get_profiles()["Renamed"]["input_sensitivity"] == 2.5


def test_profile_selection_refreshes_advanced_calibration_values(profile_settings):
    widget, engine = profile_settings
    calibration = engine.calibration
    calibration.frequency_calibration = 1.000123
    calibration.frequency_calibration_1pps = 0.999987
    calibration.frequency_calibration_source = "1pps"
    calibration.lockin_gain_offset = 0.25
    calibration.duplicate_profile("Calibrated", "Measurement Input")
    calibration.create_profile("Blank", "Measurement Input")
    widget.refresh_cal_profiles("Blank")

    index = widget.cal_profile_combo.findData("Calibrated")
    widget.cal_profile_combo.setCurrentIndex(index)

    assert calibration.last_profile == "Calibrated"
    assert widget.freq_cal_source_combo.currentData() == "1pps"
    assert widget.freq_cal_ppm_edit.text() == "+123.000 ppm"
    assert widget.freq_cal_1pps_ppm_edit.text() == "-13.000 ppm"
    assert widget.lockin_gain_edit.text() == "250.000 mdB"


def test_refresh_does_not_implicitly_activate_first_profile(profile_settings):
    widget, engine = profile_settings
    calibration = engine.calibration
    calibration.input_sensitivity = 2.0
    calibration.duplicate_profile("Saved", "Measurement Input")
    calibration.activate_profile(None)
    calibration.input_sensitivity = 7.0
    calibration.save()

    widget.refresh_cal_profiles()

    assert widget.cal_profile_combo.currentData() is None
    assert calibration.last_profile is None
    assert calibration.input_sensitivity == 7.0


def test_delete_active_profile_keeps_values_and_detaches(profile_settings):
    widget, engine = profile_settings
    engine.calibration.input_sensitivity = 2.5
    engine.calibration.input_sensitivity_is_calibrated = True
    engine.calibration.duplicate_profile("Disposable", "Measurement Input")
    widget.refresh_cal_profiles("Disposable")

    with patch(
        "src.gui.widgets.settings.QMessageBox.question",
        return_value=QMessageBox.StandardButton.Yes,
    ):
        widget.on_delete_profile()

    assert engine.calibration.last_profile is None
    assert engine.calibration.input_sensitivity == 2.5
    assert widget.cal_profile_combo.currentData() is None


def test_profile_device_mismatch_is_warning_only(profile_settings):
    widget, engine = profile_settings
    engine.calibration.duplicate_profile(
        "Other Hardware",
        "Different Input",
        "CoreAudio",
        "Different Output",
        "CoreAudio",
    )
    widget.refresh_cal_profiles("Other Hardware")

    assert not widget.cal_profile_warning_label.isHidden()
    assert "without changing devices" in widget.cal_profile_warning_label.text()
    engine.set_devices.assert_not_called()
