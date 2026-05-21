import unittest
from unittest.mock import MagicMock, patch
import time
import numpy as np

import sys

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
        self.assertFalse(self.engine.coreaudio_change_device_parameters)
        self.assertEqual(self.engine.coreaudio_conversion_quality, "max")

        # Test setters
        self.engine._restart_stream.reset_mock()
        self.engine.set_coreaudio_fail_if_conversion_required(False)
        self.assertFalse(self.engine.coreaudio_fail_if_conversion_required)
        self.engine._restart_stream.assert_called_once()

        self.engine._restart_stream.reset_mock()
        self.engine.set_coreaudio_change_device_parameters(True)
        self.assertTrue(self.engine.coreaudio_change_device_parameters)
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


if __name__ == "__main__":
    unittest.main()
