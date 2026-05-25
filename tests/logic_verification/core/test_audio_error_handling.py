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

    def test_concurrency_error_stats(self):
        # We will run N iterations of error logging across multiple threads, 
        # and concurrently read/reset them using get_status.
        # At the end, the sum of all returned error counts + any remaining error count in engine
        # must equal the total number of errors logged.
        import threading
        import time

        engine = AudioEngine()

        num_writers = 4
        loops_per_writer = 1000
        total_errors = num_writers * loops_per_writer

        sum_retrieved_errors = 0
        reader_active = True

        # Mock class for sd.CallbackFlags
        class MockFlags:
            def __init__(self, val=0):
                self.val = val
            def __ior__(self, other):
                return MockFlags(self.val | getattr(other, 'val', 0))

        # Override accumulated_status so we don't depend on actual sounddevice C bindings in test
        engine.accumulated_status = MockFlags(0)

        # We also need to patch sd.CallbackFlags in engine since get_status initializes it
        with patch("src.core.audio_engine.sd.CallbackFlags", return_value=MockFlags(0)):
            def writer():
                for i in range(loops_per_writer):
                    # Simulate master callback catching an exception
                    with engine._status_lock:
                        engine.last_callback_error = RuntimeError(f"Error {i}")
                        engine.callback_error_count += 1
                        # also simulate status flags update
                        engine.accumulated_status |= MockFlags(1)
                    time.sleep(0.0001)

            def reader():
                nonlocal sum_retrieved_errors
                while reader_active:
                    status = engine.get_status()
                    sum_retrieved_errors += status["error_count"]
                    time.sleep(0.0002)

            writer_threads = [threading.Thread(target=writer) for _ in range(num_writers)]
            reader_thread = threading.Thread(target=reader)

            reader_thread.start()
            for t in writer_threads:
                t.start()

            for t in writer_threads:
                t.join()

            # Wait a tiny bit and stop reader
            time.sleep(0.01)
            reader_active = False
            reader_thread.join()

            # Read any final remaining errors
            final_status = engine.get_status()
            sum_retrieved_errors += final_status["error_count"]

            self.assertEqual(sum_retrieved_errors, total_errors, "No error counts should be lost due to concurrency")


if __name__ == "__main__":
    unittest.main()
