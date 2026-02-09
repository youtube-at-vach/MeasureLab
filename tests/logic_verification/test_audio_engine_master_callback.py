import unittest
from unittest.mock import MagicMock, patch
import numpy as np
import sys
import importlib

# Mock sounddevice at module level to allow import
sys.modules['sounddevice'] = MagicMock()

import src.core.audio_engine  # noqa: E402

class TestAudioEngineMasterCallback(unittest.TestCase):
    def setUp(self):
        # Setup mock sounddevice for THIS test
        self.mock_sd = MagicMock()
        self.sd_patcher = patch.dict(sys.modules, {'sounddevice': self.mock_sd})
        self.sd_patcher.start()

        # Reload AudioEngine to use the mock
        importlib.reload(src.core.audio_engine)
        from src.core.audio_engine import AudioEngine
        self.AudioEngine = AudioEngine

        self.engine = self.AudioEngine()
        self.engine.stream = None
        self.engine.logger = MagicMock()

    def tearDown(self):
        self.sd_patcher.stop()

    def test_stereo_passthrough(self):
        """Test basic stereo input -> client -> stereo output flow."""
        self.engine.input_channel_mode = "stereo"
        self.engine.output_channel_mode = "stereo"

        # We need to capture the callback passed to sd.Stream
        with patch('sounddevice.Stream') as mock_stream_cls:
            # Trigger stream start by registering a callback
            # We pass a dummy callback first
            self.engine.register_callback(lambda i, o, f, t, s: None)

            # Get the callback passed to Stream constructor
            # Stream(device=..., callback=master_callback, ...)
            args, kwargs = mock_stream_cls.call_args
            callback = kwargs.get('callback')
            self.assertIsNotNone(callback, "Callback was not passed to sd.Stream")

            # Prepare data
            frames = 10
            indata = np.ones((frames, 2), dtype='float32') # stereo input 1s
            outdata = np.zeros((frames, 2), dtype='float32') # buffer to write to
            time_info = MagicMock()
            status = self.mock_sd.CallbackFlags()

            # Configure client to copy input to output
            def client_cb(indata_cl, outdata_cl, frames_cl, time_cl, status_cl):
                # indata_cl should be (frames, 2)
                # outdata_cl should be (frames, 2)
                outdata_cl[:] = indata_cl

            # Update the registered callback to our test logic
            cid = list(self.engine.callbacks.keys())[0]
            self.engine.callbacks[cid] = client_cb
            # Force update cached callbacks
            self.engine._cached_callbacks = [client_cb]

            # Run the captured master_callback
            callback(indata, outdata, frames, time_info, status)

            # Verify output
            # client copies indata (ones) to outdata_cl.
            # master adds outdata_cl to outdata.
            np.testing.assert_array_equal(outdata, indata)

    def test_mono_input_mapping(self):
        """Test mapping from Mono Hardware Input -> Stereo Logical Input."""
        self.engine.input_channel_mode = "left" # HW In Ch = 1
        self.engine.output_channel_mode = "stereo"

        with patch('sounddevice.Stream') as mock_stream_cls:
            self.engine.register_callback(lambda i, o, f, t, s: None)
            args, kwargs = mock_stream_cls.call_args
            callback = kwargs.get('callback')

            frames = 10
            # Hardware input: 1 channel, value 0.5
            indata = np.full((frames, 1), 0.5, dtype='float32')
            outdata = np.zeros((frames, 2), dtype='float32')

            # Client receives stereo logical input.

            captured_shape = []

            def client_cb(indata_cl, outdata_cl, frames_cl, time_cl, status_cl):
                captured_shape.append(indata_cl.shape)
                # Just output silence
                outdata_cl[:] = 0

            cid = list(self.engine.callbacks.keys())[0]
            self.engine.callbacks[cid] = client_cb
            self.engine._cached_callbacks = [client_cb]

            callback(indata, outdata, frames, MagicMock(), self.mock_sd.CallbackFlags())

            # logical_in = indata[:, 0:1] -> shape (frames, 1)
            self.assertEqual(captured_shape[0], (frames, 1))

    def test_loopback_logic(self):
        """Test that loopback uses last output buffer."""
        self.engine.input_channel_mode = "stereo"
        self.engine.output_channel_mode = "stereo"
        self.engine.loopback = True

        with patch('sounddevice.Stream') as mock_stream_cls:
            self.engine.register_callback(lambda i, o, f, t, s: None)
            args, kwargs = mock_stream_cls.call_args
            callback = kwargs.get('callback')

            frames = 10
            # indata (hardware) is silence
            indata = np.zeros((frames, 2), dtype='float32')
            outdata = np.zeros((frames, 2), dtype='float32')

            # Pre-seed last_output_buffer to simulate previous block
            # Logic: if use_loopback and self.last_output_buffer is not None ...
            self.engine.last_output_buffer = np.full((frames, 2), 0.8, dtype='float32')

            # Client should receive last_output_buffer content
            captured_input = []

            def client_cb(indata_cl, outdata_cl, frames_cl, time_cl, status_cl):
                captured_input.append(indata_cl.copy())
                # Output something different
                outdata_cl[:] = 0.5

            cid = list(self.engine.callbacks.keys())[0]
            self.engine.callbacks[cid] = client_cb
            self.engine._cached_callbacks = [client_cb]

            callback(indata, outdata, frames, MagicMock(), self.mock_sd.CallbackFlags())

            # Check client received the loopback data (0.8) not indata (0.0)
            # Note: self.engine.last_output_buffer has been updated to 0.5 by now, so we compare against expected 0.8
            expected_input = np.full((frames, 2), 0.8, dtype='float32')
            np.testing.assert_array_equal(captured_input[0], expected_input)

            # Check that last_output_buffer is updated with NEW output (0.5)
            # The master_callback updates last_output_buffer at the END.
            np.testing.assert_array_equal(self.engine.last_output_buffer, np.full((frames, 2), 0.5, dtype='float32'))
