import unittest
from unittest.mock import MagicMock, patch
import time
import numpy as np

import sys
import importlib

# Mock sounddevice early before importing AudioEngine
sys.modules["sounddevice"] = MagicMock()

from src.core.audio_engine import AudioEngine, VirtualStream, _DummyTime  # noqa: E402


class TestDummyTime(unittest.TestCase):
    def test_dummy_time_initialization(self):
        t = 100.0
        interval = 0.5
        dt = _DummyTime(t, interval)
        self.assertEqual(dt.inputBufferAdcTime, 100.0)
        self.assertEqual(dt.outputBufferDacTime, 100.5)
        self.assertEqual(dt.currentTime, 100.0)


class TestVirtualStream(unittest.TestCase):
    def setUp(self):
        self.callback_mock = MagicMock()
        self.samplerate = 48000
        self.blocksize = 1024

        # Test with single int channel
        self.stream_int = VirtualStream(
            samplerate=self.samplerate, blocksize=self.blocksize, channels=2, callback=self.callback_mock
        )

        # Test with tuple channels
        self.stream_tuple = VirtualStream(
            samplerate=self.samplerate, blocksize=self.blocksize, channels=(2, 2), callback=self.callback_mock
        )

    def test_start_stop_close(self):
        self.assertFalse(self.stream_int.active)

        # Test start
        self.stream_int.start()
        self.assertTrue(self.stream_int.active)
        self.assertIsNotNone(self.stream_int._thread)
        self.assertTrue(self.stream_int._thread.is_alive())

        # Calling start again shouldn't do anything bad
        self.stream_int.start()
        self.assertTrue(self.stream_int.active)

        # Test stop
        self.stream_int.stop()
        self.assertFalse(self.stream_int.active)
        self.assertTrue(self.stream_int._stop_event.is_set())

        # Calling stop again shouldn't do anything bad
        self.stream_int.stop()
        self.assertFalse(self.stream_int.active)

        # Test close
        self.stream_int.start()
        self.assertTrue(self.stream_int.active)
        self.stream_int.close()
        self.assertFalse(self.stream_int.active)

    def test_run_loop_callback_invocation(self):
        # We start and immediately stop the stream to let it run briefly
        self.stream_tuple.start()
        time.sleep(0.1)  # Let it run for a bit
        self.stream_tuple.stop()

        # The callback should have been called
        self.assertTrue(self.callback_mock.called)

        # Verify callback arguments
        args, kwargs = self.callback_mock.call_args
        indata, outdata, frames, t, status = args

        self.assertEqual(frames, self.blocksize)
        self.assertIsInstance(indata, np.ndarray)
        self.assertIsInstance(outdata, np.ndarray)
        self.assertEqual(indata.shape, (self.blocksize, 2))
        self.assertEqual(outdata.shape, (self.blocksize, 2))
        self.assertIsInstance(t, _DummyTime)


class TestAudioEngineBasicSettings(unittest.TestCase):
    def setUp(self):
        self.engine = AudioEngine()
        self.engine.logger = MagicMock()
        self.engine._restart_stream = MagicMock()
        self.engine._start_master_stream = MagicMock()

    def test_set_loopback(self):
        self.assertFalse(self.engine.loopback)
        self.engine.set_loopback(True)
        self.assertTrue(self.engine.loopback)
        self.engine.logger.debug.assert_called_with("Set software loopback: True")

        self.engine.set_loopback(False)
        self.assertFalse(self.engine.loopback)
        self.engine.logger.debug.assert_called_with("Set software loopback: False")

    def test_set_mute_output(self):
        self.assertFalse(self.engine.mute_output)
        self.engine.set_mute_output(True)
        self.assertTrue(self.engine.mute_output)
        self.engine.logger.debug.assert_called_with("Set mute output: True")

        self.engine.set_mute_output(False)
        self.assertFalse(self.engine.mute_output)
        self.engine.logger.debug.assert_called_with("Set mute output: False")

    def test_set_offline_mode(self):
        self.assertFalse(self.engine.offline_mode)

        # Enable
        self.engine.set_offline_mode(True)
        self.assertTrue(self.engine.offline_mode)
        # Should restart stream if active, but stream is not active here
        self.engine.is_active = MagicMock(return_value=False)
        self.engine._restart_stream.assert_not_called()

        # Mock active stream
        self.engine.is_active = MagicMock(return_value=True)
        # Disable
        self.engine.set_offline_mode(False)
        self.assertFalse(self.engine.offline_mode)
        self.engine._restart_stream.assert_called_once()

        self.engine._restart_stream.reset_mock()
        # Set to same value (False -> False) shouldn't restart
        self.engine.set_offline_mode(False)
        self.assertFalse(self.engine.offline_mode)
        self.engine._restart_stream.assert_not_called()

    def test_set_pipewire_jack_resident(self):
        self.assertFalse(self.engine.pipewire_jack_resident)

        # Enable resident mode
        self.engine.set_pipewire_jack_resident(True)
        self.assertTrue(self.engine.pipewire_jack_resident)
        self.engine._start_master_stream.assert_called_once()

        # Disable resident mode without clients
        self.engine.callbacks = {}
        self.engine.stop_stream = MagicMock()
        self.engine.set_pipewire_jack_resident(False)
        self.assertFalse(self.engine.pipewire_jack_resident)
        self.engine.stop_stream.assert_called_once()

        # Disable resident mode with clients
        self.engine.stop_stream.reset_mock()
        self.engine.callbacks = {1: MagicMock()}
        self.engine.set_pipewire_jack_resident(False)
        self.assertFalse(self.engine.pipewire_jack_resident)
        self.engine.stop_stream.assert_not_called()

    def test_get_status(self):
        # Set some properties
        self.engine.offline_mode = True
        self.engine.input_channel_mode = "stereo"
        self.engine.output_channel_mode = "left"
        self.engine.sample_rate = 96000
        self.engine.input_device = 1
        self.engine.output_device = 2

        # Mock stream properties
        self.engine.is_active = MagicMock(return_value=True)
        self.engine.stream = MagicMock()
        self.engine.stream.cpu_load = 0.45

        # Add a callback
        self.engine.callbacks = {1: MagicMock(), 2: MagicMock()}

        # Mock some errors/status
        import sounddevice as sd

        self.engine.accumulated_status = sd.CallbackFlags()
        self.engine.callback_error_count = 5
        self.engine.last_callback_error = "Test Error"

        status = self.engine.get_status()

        self.assertTrue(status["active"])
        self.assertTrue(status["offline_mode"])
        self.assertEqual(status["input_channels"], "stereo")
        self.assertEqual(status["output_channels"], "left")
        self.assertEqual(status["sample_rate"], 96000)
        self.assertEqual(status["cpu_load"], 0.45)
        self.assertEqual(status["active_clients"], 2)
        self.assertEqual(status["input_device"], 1)
        self.assertEqual(status["output_device"], 2)
        self.assertEqual(status["error_count"], 5)
        self.assertEqual(status["last_error"], "Test Error")

        # Verify stats are reset after get_status
        self.assertEqual(self.engine.callback_error_count, 0)
        self.assertIsNone(self.engine.last_callback_error)

    def test_get_input_latency(self):
        # Test with no stream
        self.engine.stream = None
        self.engine.sample_rate = 48000
        self.engine.block_size = 1024
        # Should fallback to block_size / sample_rate
        expected_fallback = 1024.0 / 48000.0
        self.assertAlmostEqual(self.engine.get_input_latency(), expected_fallback)

        # Test with VirtualStream (should be 0.0)
        self.engine.stream = VirtualStream(48000, 1024, 2, MagicMock())
        self.assertEqual(self.engine.get_input_latency(), 0.0)

        # Test with real stream (mocked) tuple latency
        self.engine.stream = MagicMock()
        self.engine.stream.latency = (0.015, 0.025)
        self.assertAlmostEqual(self.engine.get_input_latency(), 0.015)

        # Test with real stream float latency
        self.engine.stream.latency = 0.012
        self.assertAlmostEqual(self.engine.get_input_latency(), 0.012)

        # Test with stream where latency raises exception
        type(self.engine.stream).latency = unittest.mock.PropertyMock(side_effect=Exception("Failed"))
        self.assertAlmostEqual(self.engine.get_input_latency(), expected_fallback)


class TestAudioEngineRefreshBackend(unittest.TestCase):
    def setUp(self):
        self.engine = AudioEngine()
        self.engine.logger = MagicMock()
        self.engine.stop_stream = MagicMock()

    def test_refresh_backend_terminate_error(self):
        from unittest.mock import patch

        # Call refresh_backend with patch
        error_msg = "Mock PortAudio error"
        with (
            patch("src.core.audio_engine.sd._initialize") as mock_init,
            patch("src.core.audio_engine.sd._terminate", side_effect=Exception(error_msg)),
        ):
            self.engine.refresh_backend()

            # Verify stop_stream was called
            self.engine.stop_stream.assert_called_once()

            # Verify the exception was caught and logged as a warning
            self.engine.logger.warning.assert_any_call(f"Error terminating PortAudio: {error_msg}")

            # Verify it still attempted to re-initialize
            mock_init.assert_called_once()


class TestAudioEngineGetHostApis(unittest.TestCase):
    def setUp(self):

        self.engine = AudioEngine()

        self.engine._host_apis_cache = None

        self.engine._last_cache_time = 0

    @patch("src.core.audio_engine.sd.query_hostapis")
    def test_get_host_apis_success(self, mock_query):

        mock_query.return_value = [{"name": "ALSA"}, {"name": "PulseAudio"}]

        result = self.engine.get_host_apis()

        self.assertEqual(result, [{"name": "ALSA"}, {"name": "PulseAudio"}])

        mock_query.assert_called_once()

        self.assertEqual(self.engine._host_apis_cache, [{"name": "ALSA"}, {"name": "PulseAudio"}])

    @patch("src.core.audio_engine.sd.query_hostapis")
    def test_get_host_apis_caching(self, mock_query):

        mock_query.return_value = [{"name": "ALSA"}]

        # First call sets cache

        result1 = self.engine.get_host_apis()

        mock_query.assert_called_once()

        # Second call uses cache (time hasn't advanced 2 seconds)

        mock_query.reset_mock()

        result2 = self.engine.get_host_apis()

        mock_query.assert_not_called()

        self.assertEqual(result1, result2)

    @patch("src.core.audio_engine.sd.query_hostapis")
    @patch("src.core.audio_engine.time.time")
    def test_get_host_apis_cache_expiration(self, mock_time, mock_query):

        mock_query.return_value = [{"name": "ALSA"}]

        mock_time.return_value = 100.0

        # First call sets cache at t=100

        self.engine.get_host_apis()

        self.assertEqual(mock_query.call_count, 1)

        # Advance time by 2.1 seconds

        mock_time.return_value = 162.1

        self.engine.get_host_apis()

        self.assertEqual(mock_query.call_count, 2)

    @patch("src.core.audio_engine.sd.query_hostapis")
    def test_get_host_apis_exception(self, mock_query):

        mock_query.side_effect = Exception("Failed to query")

        result = self.engine.get_host_apis()

        self.assertEqual(result, [])


class TestAudioEngineCoreAudioSettings(unittest.TestCase):
    def setUp(self):
        self.engine = AudioEngine()
        self.engine.logger = MagicMock()
        self.engine._restart_stream = MagicMock()

    def test_coreaudio_settings_defaults_and_setters(self):
        # Test defaults
        self.assertTrue(self.engine.coreaudio_fail_if_conversion_required)
        self.assertTrue(self.engine.coreaudio_change_device_parameters)
        self.assertEqual(self.engine.coreaudio_conversion_quality, "min")

        # Test setters
        self.engine._restart_stream.reset_mock()
        self.engine.set_coreaudio_fail_if_conversion_required(False)
        self.assertFalse(self.engine.coreaudio_fail_if_conversion_required)
        self.engine._restart_stream.assert_called_once()

        self.engine._restart_stream.reset_mock()
        self.engine.set_coreaudio_change_device_parameters(False)
        self.assertFalse(self.engine.coreaudio_change_device_parameters)
        self.engine._restart_stream.assert_called_once()

        self.engine._restart_stream.reset_mock()
        self.engine.set_coreaudio_conversion_quality("medium")
        self.assertEqual(self.engine.coreaudio_conversion_quality, "medium")
        self.engine._restart_stream.assert_called_once()

    @patch("sys.platform", "linux")
    def test_get_coreaudio_settings_non_mac(self):
        settings = self.engine._get_coreaudio_settings()
        self.assertIsNone(settings)

    @patch("sys.platform", "darwin")
    def test_get_coreaudio_settings_mac(self):
        mock_settings_cls = MagicMock()
        with patch("src.core.audio_engine.sd.CoreAudioSettings", mock_settings_cls):
            self.engine.coreaudio_fail_if_conversion_required = True
            self.engine.coreaudio_change_device_parameters = False
            self.engine.coreaudio_conversion_quality = "max"

            settings = self.engine._get_coreaudio_settings()

            self.assertIsNotNone(settings)
            self.assertEqual(len(settings), 2)

            # Verify sd.CoreAudioSettings was called with correct parameters
            mock_settings_cls.assert_any_call(
                change_device_parameters=False, fail_if_conversion_required=True, conversion_quality="max"
            )

    @patch("sys.platform", "darwin")
    def test_start_master_stream_mac(self):
        self.engine.offline_mode = False
        self.engine.input_device = 1
        self.engine.output_device = 2
        self.engine.sample_rate = 48000
        self.engine.block_size = 1024

        mock_settings = ("mock_in", "mock_out")
        self.engine._get_coreaudio_settings = MagicMock(return_value=mock_settings)
        self.engine._update_channel_modes = MagicMock(return_value=(1, 2))

        mock_stream = MagicMock()
        with patch("src.core.audio_engine.sd.Stream", mock_stream):
            self.engine._start_master_stream()

            mock_stream.assert_called_once_with(
                device=(1, 2),
                samplerate=48000,
                blocksize=1024,
                callback=self.engine._master_callback,
                channels=(1, 2),
                dtype="float32",
                latency="high",
                extra_settings=mock_settings,
            )


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

    def test_stop_stream_close_exception(self):
        # Create a mock stream that succeeds on stop but raises an exception on close
        mock_stream = MagicMock()
        mock_stream.stop.return_value = None
        mock_stream.close.side_effect = Exception("Mock exception on close")

        self.engine.stream = mock_stream

        # This should handle the exception and log it
        self.engine.stop_stream()

        # Check if the logger was called with the exception
        self.engine.logger.error.assert_called_once()
        args, _ = self.engine.logger.error.call_args
        self.assertIn("Mock exception on close", args[0])

        # Verify stream is set to None
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


class TestAudioEngineDithering(unittest.TestCase):
    def setUp(self):
        # Patch sys.modules to mock sounddevice
        self.patcher = patch.dict(sys.modules, {"sounddevice": MagicMock()})
        self.patcher.start()

        # Import and reload AudioEngine to use the mock
        import src.core.audio_engine

        importlib.reload(src.core.audio_engine)
        self.AudioEngineClass = src.core.audio_engine.AudioEngine

        self.engine = self.AudioEngineClass()
        # Mock stream so register_callback doesn't try to start it
        self.engine.stream = MagicMock()
        self.engine.logger = MagicMock()

        # Prepare dummy callback for tests
        self.frames = 1024
        self.indata = np.zeros((self.frames, 2), dtype="float32")
        self.outdata = np.zeros((self.frames, 2), dtype="float32")

        # Register a callback that outputs silence (zeros)
        # This ensures that any output is purely from the dithering process
        def silence_cb(indata, outdata, frames, time, status):
            outdata.fill(0)

        self.engine.register_callback(silence_cb)

    def tearDown(self):
        self.patcher.stop()

    def test_dithering_8bit(self):
        """Verify that 8-bit TPDF dither is applied correctly."""
        self.engine.dithering_enabled = True
        self.engine.dithering_bit_depth = "8"

        # Invoke callback
        self.engine._master_callback(self.indata, self.outdata, self.frames, None, 0)

        # Verify output is not zero
        max_val = np.max(np.abs(self.outdata))
        self.assertGreater(max_val, 0, "Dither output should not be zero")

        # 8-bit LSB = 1 / 2^7
        lsb_8 = 1.0 / (2**7)

        # We allow a tiny epsilon for float precision
        self.assertLess(max_val, lsb_8 * 1.01, f"Dither should be within approx 1 LSB ({lsb_8}), got {max_val}")
        self.assertGreater(max_val, lsb_8 * 0.1, "Dither noise seems too small for 8-bit")

    def test_dithering_16bit(self):
        """Verify that 16-bit TPDF dither is applied correctly."""
        self.engine.dithering_enabled = True
        self.engine.dithering_bit_depth = "16"

        # Invoke callback
        self.engine._master_callback(self.indata, self.outdata, self.frames, None, 0)

        # Verify output is not zero
        max_val = np.max(np.abs(self.outdata))
        self.assertGreater(max_val, 0, "Dither output should not be zero")

        # 16-bit LSB = 1 / 2^15
        lsb_16 = 1.0 / (2**15)

        # TPDF dither is sum of two uniform distributions (-LSB/2 to LSB/2), or rather:
        # Code: (rand1 - rand2) * lsb
        # rand1 is [0, 1), rand2 is [0, 1). diff is (-1, 1).
        # So range is strictly (-LSB, LSB).
        # We allow a tiny epsilon for float precision
        self.assertLess(max_val, lsb_16 * 1.01, f"Dither should be within approx 1 LSB ({lsb_16}), got {max_val}")

        # Also check it's reasonably large (not just 1e-20)
        # Random noise should cover a good portion of the range over 1024 samples
        self.assertGreater(max_val, lsb_16 * 0.1, "Dither noise seems too small for 16-bit")

    def test_dithering_24bit(self):
        """Verify that 24-bit TPDF dither is applied correctly."""
        self.engine.dithering_enabled = True
        self.engine.dithering_bit_depth = "24"

        # Invoke callback
        self.engine._master_callback(self.indata, self.outdata, self.frames, None, 0)

        # Verify output is not zero
        max_val = np.max(np.abs(self.outdata))
        self.assertGreater(max_val, 0, "Dither output should not be zero")

        # 24-bit LSB = 1 / 2^23
        lsb_24 = 1.0 / (2**23)

        self.assertLess(max_val, lsb_24 * 1.01, f"Dither should be within approx 1 LSB ({lsb_24}), got {max_val}")
        self.assertGreater(max_val, lsb_24 * 0.1, "Dither noise seems too small for 24-bit")

    def test_dithering_disabled(self):
        """Verify that output is zero when dithering is disabled."""
        self.engine.dithering_enabled = False

        # Invoke callback
        self.engine._master_callback(self.indata, self.outdata, self.frames, None, 0)

        # Verify output is exactly zero
        max_val = np.max(np.abs(self.outdata))
        self.assertEqual(max_val, 0.0, "Output should be zero when dithering is disabled")

    def test_dithering_logic_parsing(self):
        """Verify string parsing for bit depth selection."""
        self.engine.dithering_enabled = True

        # Test "8-bit" string
        self.engine.dithering_bit_depth = "8-bit"
        self.outdata.fill(0)
        self.engine._master_callback(self.indata, self.outdata, self.frames, None, 0)
        max_val_8 = np.max(np.abs(self.outdata))
        lsb_8 = 1.0 / (2**7)
        self.assertGreater(max_val_8, lsb_8 * 0.1, "Should detect 8-bit mode")

        # Test "16-bit" string
        self.engine.dithering_bit_depth = "16-bit"
        self.outdata.fill(0)  # Reset buffer
        self.engine._master_callback(self.indata, self.outdata, self.frames, None, 0)
        max_val_16 = np.max(np.abs(self.outdata))

        lsb_16 = 1.0 / (2**15)
        # Should be roughly 16-bit level
        self.assertGreater(max_val_16, lsb_16 * 0.1, "Should detect 16-bit mode")

        # Test "32-bit float" (should fallback to 24-bit logic as per code)
        self.engine.dithering_bit_depth = "32-bit float"
        self.outdata.fill(0)  # Reset buffer
        self.engine._master_callback(self.indata, self.outdata, self.frames, None, 0)
        max_val_32 = np.max(np.abs(self.outdata))

        lsb_24 = 1.0 / (2**23)
        # Should be roughly 24-bit level (much smaller than 16-bit)
        self.assertLess(max_val_32, lsb_24 * 1.01, "Should default to 24-bit mode for non-16 strings")

        # Compare magnitudes to be sure
        self.assertGreater(max_val_8, max_val_16 * 100, "8-bit dither should be much larger than 16-bit dither")
        self.assertGreater(max_val_16, max_val_32 * 100, "16-bit dither should be much larger than 24-bit dither")


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
                return MockFlags(self.val | getattr(other, "val", 0))

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
