import sys
import os
import unittest
from unittest.mock import MagicMock, patch
import numpy as np

# Add repo root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from src.core.audio_engine import AudioEngine


class TestAudioErrorHandling(unittest.TestCase):
    def test_callback_error_capture(self):
        # Patch 'src.core.audio_engine.sd' to intercept calls regardless of previous imports
        with patch("src.core.audio_engine.sd") as sd_mock:
            # Setup mock behavior
            sd_mock.CallbackFlags.return_value = 0
            sd_mock.query_devices.return_value = [
                {"name": "Mock Device", "max_input_channels": 2, "max_output_channels": 2, "hostapi": 0}
            ]
            sd_mock.query_hostapis.return_value = [{"name": "Mock API"}]
            sd_mock.default.device = [0, 0]

            # Ensure Stream returns a mock that mimics active state
            stream_mock = MagicMock()
            stream_mock.active = True
            sd_mock.Stream.return_value = stream_mock

            engine = AudioEngine()
            # Manually set devices to trigger stream start logic
            engine.input_device = 0
            engine.output_device = 0

            # Define a callback that raises an error
            error_msg = "Test Error in Callback"

            def bad_callback(indata, outdata, frames, time, status):
                raise RuntimeError(error_msg)

            # Register it - this should trigger _start_master_stream
            engine.register_callback(bad_callback)

            # Check if Stream was initialized
            self.assertTrue(sd_mock.Stream.called, "sd.Stream should have been instantiated")

            # Get the master_callback passed to Stream
            call_args = sd_mock.Stream.call_args
            kwargs = call_args[1]
            master_callback = kwargs.get("callback")

            self.assertIsNotNone(master_callback, "Master callback should be passed to Stream")

            # Prepare dummy data for the callback execution
            frames = 1024
            indata = np.zeros((frames, 2), dtype="float32")
            outdata = np.zeros((frames, 2), dtype="float32")
            time_info = MagicMock()
            status = MagicMock()

            # Execute the callback manually
            # This simulates the audio thread calling the callback
            # It should catch the exception raised by bad_callback and update internal state
            try:
                master_callback(indata, outdata, frames, time_info, status)
            except Exception as e:
                self.fail(f"master_callback raised exception instead of catching it: {e}")

            # Verify status update
            status_dict = engine.get_status()

            self.assertEqual(status_dict["error_count"], 1, "Error count should be 1")
            self.assertEqual(status_dict["last_error"], error_msg, "Last error message should match")

            # Verify reset behavior
            status_dict_2 = engine.get_status()
            self.assertEqual(status_dict_2["error_count"], 0, "Error count should be reset")
            self.assertIsNone(status_dict_2["last_error"], "Last error should be None after reset")


if __name__ == "__main__":
    unittest.main()
