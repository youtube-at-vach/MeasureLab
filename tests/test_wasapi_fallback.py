
import sys
import unittest
from unittest.mock import MagicMock, patch

# Mock sounddevice before importing AudioEngine
sys.modules["sounddevice"] = MagicMock()
import sounddevice as sd

# Setup mock for WasapiSettings
class MockWasapiSettings:
    def __init__(self, exclusive=False, explicit_sample_format=False, auto_convert=False):
        self.exclusive = exclusive

sd.WasapiSettings = MockWasapiSettings
sd.CallbackFlags = MagicMock(return_value=0)

# Mock numpy and scipy if needed (AudioEngine imports numpy)
# sys.modules["numpy"] = MagicMock() # numpy is usually available

from src.core.audio_engine import AudioEngine

class TestWasapiFallback(unittest.TestCase):
    def setUp(self):
        self.engine = AudioEngine()
        self.engine.logger = MagicMock()

    @patch("src.core.audio_engine.sd")
    def test_wasapi_fallback(self, mock_sd):
        # Setup
        self.engine.audio_mode = "measurement"
        self.engine.output_device = 1
        self.engine.input_device = 0
        self.engine.input_channel_mode = "stereo"
        self.engine.output_channel_mode = "stereo"

        # Mock query_devices and query_hostapis to simulate WASAPI
        mock_sd.query_devices.return_value = {"hostapi": 0}
        mock_sd.query_hostapis.return_value = {"name": "Windows WASAPI"}
        mock_sd.default.device = [0, 1]
        
        # Ensure WasapiSettings is available on the mock
        mock_sd.WasapiSettings = MockWasapiSettings

        # Mock Stream to fail first time (with settings), succeed second time (without)
        def stream_side_effect(**kwargs):
            if kwargs.get("extra_settings") is not None:
                raise Exception("Exclusive Mode Failed")
            return MagicMock()

        mock_sd.Stream.side_effect = stream_side_effect

        # Execute
        self.engine._start_master_stream()

        # Verify
        # Check that Stream was called twice
        self.assertEqual(mock_sd.Stream.call_count, 2)
        
        # First call has extra_settings
        call_args_1 = mock_sd.Stream.call_args_list[0]
        self.assertIsNotNone(call_args_1.kwargs.get("extra_settings"))
        self.assertIsInstance(call_args_1.kwargs["extra_settings"], MockWasapiSettings)

        # Second call has None extra_settings
        call_args_2 = mock_sd.Stream.call_args_list[1]
        self.assertIsNone(call_args_2.kwargs.get("extra_settings"))

        # Check logging
        self.engine.logger.warning.assert_called()
        self.assertTrue(any("Stream creation failed with extra settings" in str(c) for c in self.engine.logger.warning.call_args_list))

if __name__ == "__main__":
    unittest.main()
