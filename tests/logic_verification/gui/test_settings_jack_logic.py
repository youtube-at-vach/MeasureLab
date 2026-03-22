from unittest.mock import MagicMock, patch

# Ensure src is importable (conftest.py handles path)
from src.gui.widgets.settings import SettingsWidget
from src.core.config_manager import ConfigManager


def test_jack_detection(qtbot):
    """
    Verify JACK detection logic.
    Uses real SettingsWidget (with mocks for dependencies).
    """
    # Mock AudioEngine
    mock_engine = MagicMock()
    # Initial state: JACK is available
    mock_engine.get_host_apis.return_value = [
        {"name": "ALSA", "index": 0},
        {"name": "JACK Audio Connection Kit", "index": 1},
    ]
    mock_engine.input_device = 0
    mock_engine.output_device = 0
    mock_engine.sample_rate = 48000
    mock_engine.block_size = 1024
    mock_engine.input_channel_mode = "stereo"
    mock_engine.output_channel_mode = "stereo"
    mock_engine.list_devices.return_value = []  # Avoid crash in refresh_devices loop

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

    # Mock Localization Manager
    with patch("src.gui.widgets.settings.get_manager") as mock_get_man:
        mock_man_instance = MagicMock()
        mock_man_instance.available_languages = {"en": "English"}
        mock_man_instance.language = "en"
        mock_get_man.return_value = mock_man_instance

        # Patch internal method to avoid sounddevice import issues during init
        with patch.object(SettingsWidget, "_get_current_host_api_index", return_value=0):
            # Create widget
            widget = SettingsWidget(mock_engine, mock_config)
            qtbot.addWidget(widget)

            # Test: JACK is available
            # Need to ensure get_host_apis returns current mocked value
            # SettingsWidget calls it inside _is_jack_available
            assert widget._is_jack_available() is True

            # Test: JACK is NOT available
            mock_engine.get_host_apis.return_value = [{"name": "ALSA", "index": 0}]
            assert widget._is_jack_available() is False

            # Verify UI update calls
            # Test UI behavior: Refresh button should be disabled if JACK is present?
            # Re-set JACK present
            mock_engine.get_host_apis.return_value = [
                {"name": "ALSA", "index": 0},
                {"name": "JACK Audio Connection Kit", "index": 1},
            ]

            # Trigger update
            widget._update_offline_ui_state()

            # Check refresh button enabled state
            # Logic: self.refresh_btn.setEnabled(not is_offline and not is_jack)
            # Here: offline=False, jack=True -> Enabled=False
            assert widget.refresh_btn.isEnabled() is False

            # Remove JACK
            mock_engine.get_host_apis.return_value = [{"name": "ALSA", "index": 0}]
            widget._update_offline_ui_state()

            # Logic: offline=False, jack=False -> Enabled=True
            assert widget.refresh_btn.isEnabled() is True
