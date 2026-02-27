from unittest.mock import MagicMock, patch
from PyQt6.QtWidgets import QTabWidget, QComboBox, QCheckBox, QLineEdit, QSpinBox, QPushButton

# Ensure src is importable (conftest.py handles path)
from src.gui.widgets.settings import SettingsWidget
from src.core.config_manager import ConfigManager

def test_settings_widget_structure(qtbot):
    """
    Verify the structure of SettingsWidget to ensure all components are initialized correctly.
    This test serves as a baseline before refactoring init_ui.
    """
    # Mock AudioEngine
    mock_engine = MagicMock()
    mock_engine.get_host_apis.return_value = [{'name': 'ALSA', 'index': 0}]
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

    # Mock ConfigManager
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

    # Mock Localization Manager
    with patch('src.gui.widgets.settings.get_manager') as mock_get_man:
        mock_man_instance = MagicMock()
        mock_man_instance.available_languages = {"en": "English"}
        mock_man_instance.language = "en"
        mock_get_man.return_value = mock_man_instance

        # Patch internal method to avoid sounddevice import issues during init
        with patch.object(SettingsWidget, '_get_current_host_api_index', return_value=0):
            # Create widget
            widget = SettingsWidget(mock_engine, mock_config)
            qtbot.addWidget(widget)

            # 1. Verify Tabs
            tabs = widget.findChild(QTabWidget)
            assert tabs is not None
            assert tabs.count() == 3
            assert tabs.tabText(0) == "General"
            assert tabs.tabText(1) == "Audio"
            assert tabs.tabText(2) == "Calibration"

            # 2. Verify General Tab Components
            assert hasattr(widget, 'lang_combo')
            assert isinstance(widget.lang_combo, QComboBox)
            assert hasattr(widget, 'theme_combo')
            assert isinstance(widget.theme_combo, QComboBox)
            assert hasattr(widget, 'screenshot_dir_edit')
            assert isinstance(widget.screenshot_dir_edit, QLineEdit)
            assert hasattr(widget, 'regen_fft_btn')
            assert isinstance(widget.regen_fft_btn, QPushButton)

            # 3. Verify Audio Tab Components
            assert hasattr(widget, 'hostapi_combo')
            assert isinstance(widget.hostapi_combo, QComboBox)
            assert hasattr(widget, 'input_combo')
            assert isinstance(widget.input_combo, QComboBox)
            assert hasattr(widget, 'output_combo')
            assert isinstance(widget.output_combo, QComboBox)
            assert hasattr(widget, 'sr_combo')
            assert isinstance(widget.sr_combo, QComboBox)
            assert hasattr(widget, 'bs_combo')
            assert isinstance(widget.bs_combo, QComboBox)
            assert hasattr(widget, 'in_ch_combo')
            assert isinstance(widget.in_ch_combo, QComboBox)
            assert hasattr(widget, 'out_ch_combo')
            assert isinstance(widget.out_ch_combo, QComboBox)
            assert hasattr(widget, 'offline_check')
            assert isinstance(widget.offline_check, QCheckBox)
            assert hasattr(widget, 'offline_rate_spin')
            assert isinstance(widget.offline_rate_spin, QSpinBox)
            assert hasattr(widget, 'pipewire_jack_resident_check')
            assert isinstance(widget.pipewire_jack_resident_check, QCheckBox)
            assert hasattr(widget, 'dithering_check')
            assert isinstance(widget.dithering_check, QCheckBox)
            assert hasattr(widget, 'audio_engine_64bit_check')
            assert isinstance(widget.audio_engine_64bit_check, QCheckBox)

            # 4. Verify Calibration Tab Components
            assert hasattr(widget, 'cal_profile_combo')
            assert isinstance(widget.cal_profile_combo, QComboBox)
            assert hasattr(widget, 'cal_profile_name_edit')
            assert isinstance(widget.cal_profile_name_edit, QLineEdit)
            assert hasattr(widget, 'in_sens_edit')
            assert isinstance(widget.in_sens_edit, QLineEdit)
            assert hasattr(widget, 'out_gain_edit')
            assert isinstance(widget.out_gain_edit, QLineEdit)
            assert hasattr(widget, 'spl_offset_edit')
            assert isinstance(widget.spl_offset_edit, QLineEdit)
            assert hasattr(widget, 'show_adv_cal_check')
            assert isinstance(widget.show_adv_cal_check, QCheckBox)

            # Verify advanced calibration group is hidden initially
            assert hasattr(widget, 'adv_cal_group')
            assert widget.adv_cal_group.isVisible() is False
