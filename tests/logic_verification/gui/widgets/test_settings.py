from unittest.mock import MagicMock, patch
from PyQt6.QtWidgets import QTabWidget
from src.gui.widgets.settings import SettingsWidget
from src.core.config_manager import ConfigManager


def test_settings_widget_instantiation(qtbot):
    """Test basic instantiation of the SettingsWidget."""
    mock_engine = MagicMock()
    mock_engine.get_host_apis.return_value = [{"name": "ALSA", "index": 0}]
    mock_engine.list_devices.return_value = []
    mock_engine.input_device = 0
    mock_engine.output_device = 0
    mock_engine.sample_rate = 48000
    mock_engine.block_size = 1024
    mock_engine.input_channel_mode = "stereo"
    mock_engine.output_channel_mode = "stereo"
    mock_engine.calibration = MagicMock()
    mock_engine.calibration.input_sensitivity = 1.0
    mock_engine.calibration.output_gain = 1.0
    mock_engine.calibration.frequency_calibration = 1.0
    mock_engine.calibration.frequency_calibration_1pps = 1.0
    mock_engine.calibration.lockin_gain_offset = 0.0
    mock_engine.calibration.get_spl_offset_db.return_value = None
    mock_engine.calibration.get_profiles.return_value = {}

    mock_config = MagicMock(spec=ConfigManager)
    mock_config.get_language.return_value = "en"
    mock_config.get_theme.return_value = "system"
    mock_config.get_screenshot_output_dir.return_value = "/tmp"
    mock_config.is_offline_mode.return_value = False
    mock_config.get_offline_sample_rate.return_value = 48000
    mock_config.get_pipewire_jack_resident.return_value = False
    mock_config.get_audio_config.return_value = {}
    mock_config.is_dithering_enabled.return_value = False
    mock_config.get_dithering_bit_depth.return_value = "16"
    mock_config.is_audio_engine_64bit.return_value = False

    with patch("src.gui.widgets.settings.get_manager") as mock_get_man:
        mock_man_instance = MagicMock()
        mock_man_instance.available_languages = {"en": "English"}
        mock_man_instance.language = "en"
        mock_get_man.return_value = mock_man_instance

        with patch.object(SettingsWidget, "_get_current_host_api_index", return_value=0):
            widget = SettingsWidget(mock_engine, mock_config)
            qtbot.addWidget(widget)

            # Basic UI verification
            tabs = widget.findChild(QTabWidget)
            assert tabs is not None
            assert tabs.count() == 3


def test_settings_offline_mode_toggle_ui(qtbot):
    """Test that toggling offline mode correctly disables/enables hardware combos in the UI."""
    mock_engine = MagicMock()
    mock_engine.get_host_apis.return_value = [{"name": "ALSA", "index": 0}]
    mock_engine.list_devices.return_value = []
    mock_engine.input_device = 0
    mock_engine.output_device = 0
    mock_engine.sample_rate = 48000
    mock_engine.block_size = 1024
    mock_engine.input_channel_mode = "stereo"
    mock_engine.output_channel_mode = "stereo"
    mock_engine.calibration = MagicMock()
    mock_engine.calibration.input_sensitivity = 1.0
    mock_engine.calibration.output_gain = 1.0
    mock_engine.calibration.frequency_calibration = 1.0
    mock_engine.calibration.frequency_calibration_1pps = 1.0
    mock_engine.calibration.lockin_gain_offset = 0.0
    mock_engine.calibration.get_spl_offset_db.return_value = None
    mock_engine.calibration.get_profiles.return_value = {}

    mock_config = MagicMock(spec=ConfigManager)
    mock_config.get_language.return_value = "en"
    mock_config.get_theme.return_value = "system"
    mock_config.get_screenshot_output_dir.return_value = "/tmp"
    mock_config.is_offline_mode.return_value = False
    mock_config.get_offline_sample_rate.return_value = 48000
    mock_config.get_pipewire_jack_resident.return_value = False
    mock_config.get_audio_config.return_value = {}
    mock_config.is_dithering_enabled.return_value = False
    mock_config.get_dithering_bit_depth.return_value = "16"
    mock_config.is_audio_engine_64bit.return_value = False

    with patch("src.gui.widgets.settings.get_manager") as mock_get_man:
        mock_man_instance = MagicMock()
        mock_man_instance.available_languages = {"en": "English"}
        mock_man_instance.language = "en"
        mock_get_man.return_value = mock_man_instance

        with patch.object(SettingsWidget, "_get_current_host_api_index", return_value=0):
            widget = SettingsWidget(mock_engine, mock_config)
            qtbot.addWidget(widget)

            # Initially offline is false, combos should be enabled
            assert not widget.offline_check.isChecked()
            assert widget.hostapi_combo.isEnabled()
            assert widget.input_combo.isEnabled()

            # Toggle offline on
            widget.offline_check.setChecked(True)
            assert not widget.hostapi_combo.isEnabled()
            assert not widget.input_combo.isEnabled()

            # Toggle offline off
            widget.offline_check.setChecked(False)
            assert widget.hostapi_combo.isEnabled()
            assert widget.input_combo.isEnabled()


def test_settings_language_change_ui(qtbot):
    """Test changing language combo updates config manager."""
    mock_engine = MagicMock()
    mock_engine.get_host_apis.return_value = [{"name": "ALSA", "index": 0}]
    mock_engine.list_devices.return_value = []
    mock_engine.input_device = 0
    mock_engine.output_device = 0
    mock_engine.sample_rate = 48000
    mock_engine.block_size = 1024
    mock_engine.input_channel_mode = "stereo"
    mock_engine.output_channel_mode = "stereo"
    mock_engine.calibration = MagicMock()
    mock_engine.calibration.input_sensitivity = 1.0
    mock_engine.calibration.output_gain = 1.0
    mock_engine.calibration.frequency_calibration = 1.0
    mock_engine.calibration.frequency_calibration_1pps = 1.0
    mock_engine.calibration.lockin_gain_offset = 0.0
    mock_engine.calibration.get_spl_offset_db.return_value = None
    mock_engine.calibration.get_profiles.return_value = {}

    mock_config = MagicMock(spec=ConfigManager)
    mock_config.get_language.return_value = "en"
    mock_config.get_theme.return_value = "system"
    mock_config.get_screenshot_output_dir.return_value = "/tmp"
    mock_config.is_offline_mode.return_value = False
    mock_config.get_offline_sample_rate.return_value = 48000
    mock_config.get_pipewire_jack_resident.return_value = False
    mock_config.get_audio_config.return_value = {}
    mock_config.is_dithering_enabled.return_value = False
    mock_config.get_dithering_bit_depth.return_value = "16"
    mock_config.is_audio_engine_64bit.return_value = False

    with patch("src.gui.widgets.settings.get_manager") as mock_get_man:
        mock_man_instance = MagicMock()
        mock_man_instance.available_languages = {"en": "English", "ja": "Japanese"}
        mock_man_instance.language = "en"
        mock_get_man.return_value = mock_man_instance

        with patch.object(SettingsWidget, "_get_current_host_api_index", return_value=0):
            with patch("src.gui.widgets.settings.QMessageBox.information"):
                widget = SettingsWidget(mock_engine, mock_config)
                qtbot.addWidget(widget)

                # Set to ja
                idx = widget.lang_combo.findData("ja")
                widget.lang_combo.setCurrentIndex(idx)

                mock_config.set_language.assert_called_with("ja")
