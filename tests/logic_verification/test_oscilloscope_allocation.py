import unittest
from unittest.mock import MagicMock
import numpy as np

# Dependencies are installed in the environment, so we can import directly.
from src.gui.widgets.oscilloscope import Oscilloscope

class TestOscilloscopeAllocation(unittest.TestCase):
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

    def test_no_allocation_in_callback(self):
        """
        Verify that the Oscilloscope audio callback does not reallocate the input buffer
        or transfer buffer, ensuring zero-allocation in the audio thread.
        """
        self.osc.start_analysis()

        # Verify initial buffer IDs
        initial_transfer_id = id(self.osc.transfer_buffer)

        # Get the registered callback
        self.assertTrue(len(self.callbacks) > 0, "Callback should be registered")
        cb = self.callbacks[0]

        # Create dummy audio data
        frames = 1024
        indata = np.random.rand(frames, 2).astype(np.float32)
        outdata = np.zeros_like(indata)

        # Run callback multiple times
        for _ in range(10):
            cb(indata, outdata, frames, 0.0, None)

            # Verify transfer buffer object hasn't changed (reallocation check)
            self.assertEqual(id(self.osc.transfer_buffer), initial_transfer_id,
                             "Transfer buffer should not be reallocated in callback")

        # Verify that data was actually written to transfer buffer
        # Write count should be 10 * 1024
        self.assertEqual(self.osc.transfer_write_count, 10 * 1024)

if __name__ == "__main__":
    unittest.main()
