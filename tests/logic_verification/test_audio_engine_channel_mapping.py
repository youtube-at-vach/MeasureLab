import sys
import unittest
import numpy as np
from unittest.mock import MagicMock, patch

class TestAudioEngineChannelMapping(unittest.TestCase):
    def setUp(self):
        # Mock sounddevice before importing AudioEngine
        self.mock_sd = MagicMock()
        self.mock_sd.query_devices.return_value = [{'name': 'default', 'hostapi': 0, 'max_input_channels': 2, 'max_output_channels': 2}]
        self.mock_sd.query_hostapis.return_value = [{'name': 'ALSA'}]
        self.mock_sd.default.device = [0, 0]
        self.mock_sd.CallbackFlags.return_value = 0

        # Patch sys.modules
        self.patcher = patch.dict(sys.modules, {'sounddevice': self.mock_sd})
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
            return kwargs.get('callback')
        return None

    def test_input_mapping_left(self):
        self.engine.input_channel_mode = "left"
        self.engine.output_channel_mode = "stereo"

        # Prepare input: Channel 0 has 0.5, Channel 1 has 0.8
        indata = np.zeros((self.frames, 2), dtype='float32')
        indata[:, 0] = 0.5
        indata[:, 1] = 0.8
        outdata = np.zeros((self.frames, 2), dtype='float32')

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

        indata = np.zeros((self.frames, 2), dtype='float32')
        indata[:, 0] = 0.5
        indata[:, 1] = 0.8
        outdata = np.zeros((self.frames, 2), dtype='float32')

        master_callback = self._get_master_callback()
        self.assertIsNotNone(master_callback)

        master_callback(indata, outdata, self.frames, self.time_info, self.status)

        # Verify logical_in has channel 1
        self.assertEqual(self.captured_logical_in.shape, (self.frames, 1))
        np.testing.assert_allclose(self.captured_logical_in[:, 0], 0.8)

    def test_input_mapping_stereo(self):
        self.engine.input_channel_mode = "stereo"
        self.engine.output_channel_mode = "stereo"

        indata = np.zeros((self.frames, 2), dtype='float32')
        indata[:, 0] = 0.5
        indata[:, 1] = 0.8
        outdata = np.zeros((self.frames, 2), dtype='float32')

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

        indata = np.zeros((self.frames, 2), dtype='float32')
        outdata = np.zeros((self.frames, 2), dtype='float32')

        master_callback = self._get_master_callback()
        self.assertIsNotNone(master_callback)

        master_callback(indata, outdata, self.frames, self.time_info, self.status)

        # Output mode left means outdata[:, 0] should be mixed, others 0
        np.testing.assert_allclose(outdata[:, 0], 1.0)
        np.testing.assert_allclose(outdata[:, 1], 0.0)

    def test_output_mapping_right(self):
        self.engine.input_channel_mode = "stereo"
        self.engine.output_channel_mode = "right"

        indata = np.zeros((self.frames, 2), dtype='float32')
        outdata = np.zeros((self.frames, 2), dtype='float32')

        master_callback = self._get_master_callback()
        self.assertIsNotNone(master_callback)

        master_callback(indata, outdata, self.frames, self.time_info, self.status)

        # Output mode right means outdata[:, 1] = mix_buffer, outdata[:, 0] = 0
        np.testing.assert_allclose(outdata[:, 0], 0.0)
        np.testing.assert_allclose(outdata[:, 1], 1.0)

if __name__ == '__main__':
    unittest.main()
