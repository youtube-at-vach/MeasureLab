
import sys
import unittest
from unittest.mock import MagicMock, patch

# Mock sounddevice before importing AudioEngine
sys.modules["sounddevice"] = MagicMock()
import sounddevice as sd  # noqa: E402

# Setup mock for Settings classes
class MockWasapiSettings:
    def __init__(self, exclusive=False, explicit_sample_format=False, auto_convert=False):
        self.exclusive = exclusive

class MockCoreAudioSettings:
    def __init__(self, change_device_parameters=False, fail_if_conversion_required=False):
        self.change_device_parameters = change_device_parameters

sd.WasapiSettings = MockWasapiSettings
sd.CoreAudioSettings = MockCoreAudioSettings
sd.CallbackFlags = MagicMock(return_value=0)

from src.core.audio_engine import AudioEngine  # noqa: E402

class TestAudioModeFallback(unittest.TestCase):
    def setUp(self):
        self.engine = AudioEngine()
        self.engine.logger = MagicMock()
        self.engine.input_device = 0
        self.engine.output_device = 1
        self.engine.input_channel_mode = "stereo"
        self.engine.output_channel_mode = "stereo"

    @patch("src.core.audio_engine.sd")
    def test_wasapi_fallback(self, mock_sd):
        # Setup
        self.engine.audio_mode = "measurement"

        # Mock query_devices and query_hostapis to simulate WASAPI
        mock_sd.query_devices.return_value = {"hostapi": 0}
        mock_sd.query_hostapis.return_value = {"name": "Windows WASAPI"}
        mock_sd.default.device = [0, 1]
        mock_sd.WasapiSettings = MockWasapiSettings

        # Mock Stream to fail first time (with settings), succeed second time (without)
        def stream_side_effect(**kwargs):
            if isinstance(kwargs.get("extra_settings"), MockWasapiSettings):
                raise Exception("Exclusive Mode Failed")
            return MagicMock()

        mock_sd.Stream.side_effect = stream_side_effect

        # Execute
        self.engine._start_master_stream()

        # Verify
        self.assertEqual(mock_sd.Stream.call_count, 2)
        # First call has WasapiSettings
        self.assertIsInstance(mock_sd.Stream.call_args_list[0].kwargs["extra_settings"], MockWasapiSettings)
        # Second call has None
        self.assertIsNone(mock_sd.Stream.call_args_list[1].kwargs.get("extra_settings"))

    @patch("src.core.audio_engine.sd")
    def test_coreaudio_fallback(self, mock_sd):
        # Setup
        self.engine.audio_mode = "measurement"

        # Mock query_devices and query_hostapis to simulate Core Audio
        mock_sd.query_devices.return_value = {"hostapi": 1}
        mock_sd.query_hostapis.return_value = {"name": "Core Audio"}
        mock_sd.default.device = [0, 1]
        mock_sd.CoreAudioSettings = MockCoreAudioSettings

        # Ensure WasapiSettings is NOT available or not used here
        # mock_sd.WasapiSettings might exist on mock, but code shouldn't use it for Core Audio

        # Mock Stream to fail first time (with settings), succeed second time (without)
        def stream_side_effect(**kwargs):
            if isinstance(kwargs.get("extra_settings"), MockCoreAudioSettings):
                raise Exception("Core Audio Format Failed")
            return MagicMock()

        mock_sd.Stream.side_effect = stream_side_effect

        # Execute
        self.engine._start_master_stream()

        # Verify
        self.assertEqual(mock_sd.Stream.call_count, 2)
        # First call has CoreAudioSettings
        self.assertIsInstance(mock_sd.Stream.call_args_list[0].kwargs["extra_settings"], MockCoreAudioSettings)
        # Second call has None
        self.assertIsNone(mock_sd.Stream.call_args_list[1].kwargs.get("extra_settings"))

if __name__ == "__main__":
    unittest.main()
