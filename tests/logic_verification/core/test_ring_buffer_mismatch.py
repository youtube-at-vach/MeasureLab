import os
import sys
import unittest
import numpy as np

# Adjust path to import src if needed
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../")))

from src.core.ring_buffer import RingBuffer

class TestRingBufferMismatch(unittest.TestCase):
    def test_stereo_to_quad_write(self):
        # Buffer is 4-channel
        rb = RingBuffer(capacity=100, channels=4, dtype=np.float32)

        # Input is 2-channel (stereo)
        data = np.ones((10, 2), dtype=np.float32)

        # This currently raises ValueError
        rb.write(data)

        # Should zero-pad the missing channels
        read_data = rb.read()
        self.assertEqual(read_data.shape, (10, 4))

        # Check first 2 channels are 1.0
        np.testing.assert_array_equal(read_data[:, :2], np.ones((10, 2), dtype=np.float32))

        # Check last 2 channels are 0.0 (padded)
        np.testing.assert_array_equal(read_data[:, 2:], np.zeros((10, 2), dtype=np.float32))

if __name__ == "__main__":
    unittest.main()
