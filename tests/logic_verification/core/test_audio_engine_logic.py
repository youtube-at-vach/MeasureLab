import unittest
from unittest.mock import MagicMock, patch
import sys
import importlib
import numpy as np


class TestAudioEngineLogic(unittest.TestCase):
    def setUp(self):
        # Patch sys.modules to mock sounddevice
        self.patcher = patch.dict(sys.modules, {"sounddevice": MagicMock()})
        self.patcher.start()

        # Import and reload AudioEngine to use the mock
        import src.core.audio_engine

        importlib.reload(src.core.audio_engine)
        self.AudioEngineClass = src.core.audio_engine.AudioEngine

        self.engine = self.AudioEngineClass()
        self.engine.stream = MagicMock()  # Pretend stream is created so we don't hit _start_master_stream logic logic
        self.engine.logger = MagicMock()

    def tearDown(self):
        self.patcher.stop()

    def test_register_unregister(self):
        def cb(*args):
            pass

        # Test Register
        cid = self.engine.register_callback(cb)

        # Check internal state
        self.assertIn(cid, self.engine.callbacks)
        self.assertEqual(self.engine.callbacks[cid], cb)

        # Check logging happened
        self.engine.logger.debug.assert_called()
        # Verify call args
        args, _ = self.engine.logger.debug.call_args
        self.assertIn(f"Registered callback {cid}", args[0])

        # Reset mock
        self.engine.logger.reset_mock()

        # Test Unregister
        self.engine.unregister_callback(cid)
        self.assertNotIn(cid, self.engine.callbacks)

        # Check logging happened
        self.engine.logger.debug.assert_called()

        # We look through all calls because stop_stream might also log
        found_msg = False
        for call in self.engine.logger.debug.call_args_list:
            if f"Unregistered callback {cid}" in call[0][0]:
                found_msg = True
                break

        self.assertTrue(found_msg, f"Did not find 'Unregistered callback {cid}' in logs")

    def test_stop_stream_exception(self):
        # Create a mock stream that raises an exception when stopped
        mock_stream = MagicMock()
        mock_stream.stop.side_effect = Exception("Mock exception on stop")

        self.engine.stream = mock_stream

        # This should handle the exception and log it, rather than raising it to the caller
        self.engine.stop_stream()

        # Check if the logger was called with the exception
        self.engine.logger.error.assert_called_once()
        args, _ = self.engine.logger.error.call_args
        self.assertIn("Mock exception on stop", args[0])

        # Verify stream is set to None even when exception occurs
        self.assertIsNone(self.engine.stream)

    def test_unregister_nonexistent(self):
        # Unregistering a non-existent callback should not crash and might not log "Unregistered callback"
        # or it handles it gracefully.

        self.engine.unregister_callback(999)
        # Check callbacks still empty
        self.assertEqual(len(self.engine.callbacks), 0)

        # Check if it logged. The current code logs only "if callback_id in self.callbacks".
        # So it should NOT log "Unregistered callback 999"
        # Let's inspect calls.

        found_log = False
        for call in self.engine.logger.info.call_args_list:
            if "Unregistered callback 999" in call[0][0]:
                found_log = True

        self.assertFalse(found_log, "Should not log unregister for non-existent callback")

    def test_set_channel_mode_restarts_stream(self):
        # Setup: stream is active
        self.engine.stream.active = True

        # Mock _restart_stream to verify it's called
        self.engine._restart_stream = MagicMock()

        self.engine.set_channel_mode("left", "right")

        self.engine._restart_stream.assert_called_once()
        self.assertEqual(self.engine.input_channel_mode, "left")
        self.assertEqual(self.engine.output_channel_mode, "right")

    def test_set_mute_output(self):
        # Test enabling mute
        self.engine.set_mute_output(True)
        self.assertTrue(self.engine.mute_output)
        self.engine.logger.debug.assert_called_with("Set mute output: True")

        # Reset mock
        self.engine.logger.debug.reset_mock()

        # Test disabling mute
        self.engine.set_mute_output(False)
        self.assertFalse(self.engine.mute_output)
        self.engine.logger.debug.assert_called_with("Set mute output: False")

    def test_set_audio_engine_64bit(self):
        # Mock _restart_stream to verify it's called
        self.engine._restart_stream = MagicMock()

        # Test enabling 64-bit precision
        self.engine.set_audio_engine_64bit(True)

        self.assertTrue(self.engine.audio_engine_64bit)
        self.engine._restart_stream.assert_called_once()
        self.engine.logger.debug.assert_called_with("64-bit Audio Engine (float64) setting changed to: True")

        # Reset mocks
        self.engine._restart_stream.reset_mock()
        self.engine.logger.debug.reset_mock()

        # Test disabling 64-bit precision
        self.engine.set_audio_engine_64bit(False)

        self.assertFalse(self.engine.audio_engine_64bit)
        self.engine._restart_stream.assert_called_once()
        self.engine.logger.debug.assert_called_with("64-bit Audio Engine (float64) setting changed to: False")

    def test_set_channel_mode_no_restart_if_inactive(self):
        # Setup: stream is NOT active
        self.engine.stream = None

        self.engine._restart_stream = MagicMock()

        self.engine.set_channel_mode("left", "right")

        self.engine._restart_stream.assert_not_called()
        self.assertEqual(self.engine.input_channel_mode, "left")
        self.assertEqual(self.engine.output_channel_mode, "right")

    def test_update_channel_modes_stereo(self):
        self.engine.input_channel_mode = "stereo"
        self.engine.output_channel_mode = "stereo"

        # Call the method
        hw_in, hw_out = self.engine._update_channel_modes()

        self.assertEqual(self.engine._current_in_mode, self.AudioEngineClass.MODE_STEREO)
        self.assertEqual(self.engine._current_out_mode, self.AudioEngineClass.MODE_STEREO)
        self.assertEqual(hw_in, 2)
        self.assertEqual(hw_out, 2)

    def test_update_channel_modes_left(self):
        self.engine.input_channel_mode = "left"
        self.engine.output_channel_mode = "left"

        hw_in, hw_out = self.engine._update_channel_modes()

        self.assertEqual(self.engine._current_in_mode, self.AudioEngineClass.MODE_LEFT)
        self.assertEqual(self.engine._current_out_mode, self.AudioEngineClass.MODE_LEFT)
        self.assertEqual(hw_in, 1)
        self.assertEqual(hw_out, 1)

    def test_update_channel_modes_right(self):
        self.engine.input_channel_mode = "right"
        self.engine.output_channel_mode = "right"

        hw_in, hw_out = self.engine._update_channel_modes()

        self.assertEqual(self.engine._current_in_mode, self.AudioEngineClass.MODE_RIGHT)
        self.assertEqual(self.engine._current_out_mode, self.AudioEngineClass.MODE_RIGHT)
        self.assertEqual(hw_in, 2)
        self.assertEqual(hw_out, 2)

    @patch("sounddevice.query_devices")
    @patch("sounddevice.query_hostapis")
    def test_get_jack_settings_with_jack(self, mock_hostapis, mock_devices):
        # NOTE: patching 'sounddevice.query_devices' patches the attribute on the mock object in sys.modules

        # Setup mocks to simulate a JACK device
        self.engine.output_device = 1
        self.engine.jack_client_name = "TestClient"

        # Mock device query return.
        # Now _get_jack_settings calls sd.query_devices() with no args to get a list, then indexes it.
        # We need a list where index 1 has "hostapi": 0.
        mock_devices.return_value = [{"hostapi": 0, "name": "Dummy0"}, {"hostapi": 0, "name": "Dummy1"}]

        # Mock hostapi query return
        # Since the AudioEngine optimization expects a list of hostapis when calling query_hostapis() without index,
        # we return a list containing the mock dict at index 0.
        mock_hostapis.return_value = [{"name": "JACK Audio Connection Kit"}]  # Hostapi 0 is JACK

        # Call method
        settings = self.engine._get_jack_settings()

        # Verify it returns a JackSettings object
        import sounddevice as sd

        # sd is the mock
        sd.JackSettings.assert_called_with(client_name="TestClient")
        self.assertEqual(settings, sd.JackSettings.return_value)

    @patch("sounddevice.query_devices")
    @patch("sounddevice.query_hostapis")
    def test_get_jack_settings_no_jack(self, mock_hostapis, mock_devices):
        self.engine.output_device = 1

        mock_devices.return_value = [{"hostapi": 0, "name": "Dummy0"}, {"hostapi": 0, "name": "Dummy1"}]
        mock_hostapis.return_value = {"name": "ALSA"}  # Not JACK

        settings = self.engine._get_jack_settings()

        self.assertIsNone(settings)

    @patch("sounddevice.query_devices")
    def test_get_jack_settings_no_device(self, mock_devices):
        self.engine.output_device = None

        import sounddevice as sd

        # Mock sd.default.device to return [0, 1]
        type(sd.default).device = unittest.mock.PropertyMock(return_value=[0, 1])

        # Mock device 1 as non-JACK
        mock_devices.return_value = [{"hostapi": 0, "name": "Dummy0"}, {"hostapi": 0, "name": "Dummy1"}]

        settings = self.engine._get_jack_settings()
        self.assertIsNone(settings)

    @patch("sounddevice.query_hostapis")
    def test_get_host_apis_cache_expiration(self, mock_query_hostapis):
        # Setup fake initial cache
        self.engine._host_apis_cache = [{"name": "Fake API"}]

        # Set cache time to 3 seconds ago (older than 2.0s limit)
        import time
        self.engine._last_cache_time = time.time() - 3.0

        # Mock the return value of query_hostapis
        mock_query_hostapis.return_value = [{"name": "New API"}]

        # Call get_host_apis
        result = self.engine.get_host_apis()

        # Verify query_hostapis was called due to cache expiration
        mock_query_hostapis.assert_called_once()
        self.assertEqual(result, [{"name": "New API"}])
        self.assertEqual(self.engine._host_apis_cache, [{"name": "New API"}])


class TestAudioEngineChannelMapping(unittest.TestCase):
    def setUp(self):
        # Mock sounddevice before importing AudioEngine
        self.mock_sd = MagicMock()
        self.mock_sd.query_devices.return_value = [
            {"name": "default", "hostapi": 0, "max_input_channels": 2, "max_output_channels": 2}
        ]
        self.mock_sd.query_hostapis.return_value = [{"name": "ALSA"}]
        self.mock_sd.default.device = [0, 0]
        self.mock_sd.CallbackFlags.return_value = 0

        # Patch sys.modules
        self.patcher = patch.dict(sys.modules, {"sounddevice": self.mock_sd})
        self.patcher.start()

        import importlib
        import src.core.audio_engine

        # Reload to ensure it picks up the mocked sounddevice
        importlib.reload(src.core.audio_engine)
        self.engine = src.core.audio_engine.AudioEngine()
        self.engine.offline_mode = False
        self.engine.loopback = False

        self.frames = 100
        self.time_info = MagicMock()
        self.status = 0

        # Capture the callback logic
        self.captured_logical_in = None
        self.captured_client_out = None

    def tearDown(self):
        if self.engine.stream:
            self.engine.stop_stream()
        self.patcher.stop()

    def _dummy_callback(self, logical_in, client_out, frames, time, status):
        # Store a copy of input so we can verify it
        self.captured_logical_in = logical_in.copy()
        # Fill client_out with something known to verify output mapping
        client_out[:] = 1.0
        self.captured_client_out = client_out

    def _get_master_callback(self):
        # Trigger stream start
        if not self.engine.callbacks:
            self.engine.register_callback(self._dummy_callback)
        else:
            # If already registered, restart stream to apply changes
            self.engine._restart_stream()

        if self.mock_sd.Stream.called:
            args, kwargs = self.mock_sd.Stream.call_args
            return kwargs.get("callback")
        return None

    def test_input_mapping_left(self):
        self.engine.input_channel_mode = "left"
        self.engine.output_channel_mode = "stereo"

        # Prepare input: Channel 0 has 0.5, Channel 1 has 0.8
        indata = np.zeros((self.frames, 2), dtype="float32")
        indata[:, 0] = 0.5
        indata[:, 1] = 0.8
        outdata = np.zeros((self.frames, 2), dtype="float32")

        master_callback = self._get_master_callback()
        self.assertIsNotNone(master_callback)

        master_callback(indata, outdata, self.frames, self.time_info, self.status)

        # Verify logical_in has channel 0
        # logical_in shape for "left" should be (frames, 1)
        self.assertEqual(self.captured_logical_in.shape, (self.frames, 1))
        np.testing.assert_allclose(self.captured_logical_in[:, 0], 0.5)

    def test_input_mapping_right(self):
        self.engine.input_channel_mode = "right"
        self.engine.output_channel_mode = "stereo"

        indata = np.zeros((self.frames, 2), dtype="float32")
        indata[:, 0] = 0.5
        indata[:, 1] = 0.8
        outdata = np.zeros((self.frames, 2), dtype="float32")

        master_callback = self._get_master_callback()
        self.assertIsNotNone(master_callback)

        master_callback(indata, outdata, self.frames, self.time_info, self.status)

        # Verify logical_in has channel 1
        self.assertEqual(self.captured_logical_in.shape, (self.frames, 1))
        np.testing.assert_allclose(self.captured_logical_in[:, 0], 0.8)

    def test_input_mapping_stereo(self):
        self.engine.input_channel_mode = "stereo"
        self.engine.output_channel_mode = "stereo"

        indata = np.zeros((self.frames, 2), dtype="float32")
        indata[:, 0] = 0.5
        indata[:, 1] = 0.8
        outdata = np.zeros((self.frames, 2), dtype="float32")

        master_callback = self._get_master_callback()
        self.assertIsNotNone(master_callback)

        master_callback(indata, outdata, self.frames, self.time_info, self.status)

        # Verify logical_in has both channels
        self.assertEqual(self.captured_logical_in.shape, (self.frames, 2))
        np.testing.assert_allclose(self.captured_logical_in[:, 0], 0.5)
        np.testing.assert_allclose(self.captured_logical_in[:, 1], 0.8)

    def test_output_mapping_left(self):
        self.engine.input_channel_mode = "stereo"
        self.engine.output_channel_mode = "left"

        indata = np.zeros((self.frames, 2), dtype="float32")
        outdata = np.zeros((self.frames, 2), dtype="float32")

        master_callback = self._get_master_callback()
        self.assertIsNotNone(master_callback)

        master_callback(indata, outdata, self.frames, self.time_info, self.status)

        # Output mode left means outdata[:, 0] should be mixed, others 0
        np.testing.assert_allclose(outdata[:, 0], 1.0)
        np.testing.assert_allclose(outdata[:, 1], 0.0)

    def test_output_mapping_right(self):
        self.engine.input_channel_mode = "stereo"
        self.engine.output_channel_mode = "right"

        indata = np.zeros((self.frames, 2), dtype="float32")
        outdata = np.zeros((self.frames, 2), dtype="float32")

        master_callback = self._get_master_callback()
        self.assertIsNotNone(master_callback)

        master_callback(indata, outdata, self.frames, self.time_info, self.status)

        # Output mode right means outdata[:, 1] = mix_buffer, outdata[:, 0] = 0
        np.testing.assert_allclose(outdata[:, 0], 0.0)
        np.testing.assert_allclose(outdata[:, 1], 1.0)


if __name__ == "__main__":
    unittest.main()
