import unittest
from unittest.mock import MagicMock
import numpy as np

# Dependencies are installed in the environment, so we can import directly.
from src.gui.widgets.oscilloscope import Oscilloscope

class TestOscilloscopeDataFlow(unittest.TestCase):
    def setUp(self):
        self.mock_engine = MagicMock()
        self.mock_engine.sample_rate = 48000
        self.mock_engine.calibration = MagicMock()
        self.mock_engine.calibration.input_sensitivity = 1.0

        # Capture callback registration
        self.callbacks = {}
        def register_callback(cb):
            cid = len(self.callbacks)
            self.callbacks[cid] = cb
            return cid
        self.mock_engine.register_callback.side_effect = register_callback

        self.osc = Oscilloscope(self.mock_engine)

    def test_oscilloscope_queue_data_flow(self):
        """
        Verify that data flows from callback -> transfer_buffer -> process_queue -> input_data.
        """
        self.osc.start_analysis()

        # Verify buffer is empty/reset
        self.assertEqual(self.osc.transfer_write_count, 0)
        self.assertEqual(self.osc.transfer_read_count, 0)

        # Get the registered callback
        self.assertTrue(len(self.callbacks) > 0)
        cb = self.callbacks[0]

        # Create test data
        frames = 100
        indata = np.ones((frames, 2), dtype=np.float32) * 0.5
        outdata = np.zeros_like(indata)

        # Call callback
        cb(indata, outdata, frames, 0.0, None)

        # Verify data is in transfer buffer
        self.assertEqual(self.osc.transfer_write_count, 100)
        self.assertEqual(self.osc.transfer_read_count, 0)

        # Check data content in transfer buffer
        # transfer_buffer is large, we check the first 100 samples
        self.assertTrue(np.allclose(self.osc.transfer_buffer[0:100], 0.5))

        # Verify input_data is still zero (before process_queue)
        self.assertTrue(np.all(self.osc.input_data == 0))

        # Call process_queue
        self.osc.process_queue()

        # Verify transfer buffer is read
        self.assertEqual(self.osc.transfer_read_count, 100)

        # Verify input_data has data
        # osc.input_data is ring buffer. write_index should be advanced.
        # We wrote 100 frames. write_index should be 100 % buffer_size.
        # Buffer initialized to 0.

        self.assertEqual(self.osc.write_index, 100)
        self.assertTrue(np.allclose(self.osc.input_data[0:100], 0.5))
        # The rest should be 0
        self.assertTrue(np.all(self.osc.input_data[100:] == 0))

if __name__ == "__main__":
    unittest.main()
