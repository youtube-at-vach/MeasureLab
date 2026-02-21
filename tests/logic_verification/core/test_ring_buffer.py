import os
import sys
import unittest
import numpy as np
import threading

# Adjust path to import src if needed
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../")))

from src.core.ring_buffer import RingBuffer

class TestRingBuffer(unittest.TestCase):
    def test_initialization(self):
        rb = RingBuffer(100, 2)
        self.assertEqual(rb.capacity, 100)
        self.assertEqual(rb.channels, 2)
        self.assertEqual(rb.available(), 0)

        with self.assertRaises(ValueError):
            RingBuffer(0, 1)
        with self.assertRaises(ValueError):
            RingBuffer(10, 0)

    def test_basic_write_read(self):
        rb = RingBuffer(10, 2)
        data = np.ones((5, 2), dtype=np.float32)
        rb.write(data)
        self.assertEqual(rb.available(), 5)

        read_data = rb.read(5)
        self.assertEqual(read_data.shape, (5, 2))
        np.testing.assert_array_equal(read_data, data)
        self.assertEqual(rb.available(), 0)

    def test_wrap_around(self):
        rb = RingBuffer(10, 1)
        # Write 8
        rb.write(np.ones((8, 1)))
        # Read 5 (3 remaining)
        rb.read(5)
        self.assertEqual(rb.available(), 3)

        # Write 5 (Total 8 samples in buffer, wrapping around)
        # buffer size 10.
        # Indices: write was 8, read was 5.
        # write 5 more -> write index 13.
        # read index 5.
        # available = 8.
        # buffer stores at 8, 9, 0, 1, 2.
        data2 = np.full((5, 1), 2.0)
        rb.write(data2)

        self.assertEqual(rb.available(), 8)

        # Read all
        all_data = rb.read()
        self.assertEqual(all_data.shape, (8, 1))
        # Expected: 3 ones (from first write), 5 twos (from second write)
        expected = np.concatenate((np.ones((3, 1)), np.full((5, 1), 2.0)))
        np.testing.assert_array_equal(all_data, expected)

    def test_overflow_behavior(self):
        rb = RingBuffer(10, 1)
        # Write 15 samples (capacity 10) - sequential writes
        # This tests reader handling overflow
        data = np.arange(15, dtype=np.float32).reshape(-1, 1)
        rb.write(data[:8]) # Write 8
        rb.write(data[8:]) # Write 7 (Total 15)

        # Should have overwritten old data.
        # Capacity is 10.
        # Should have samples 5 to 14.
        self.assertEqual(rb.available(), 10)

        read_data = rb.read()
        self.assertEqual(read_data.shape, (10, 1))
        expected = np.arange(5, 15, dtype=np.float32).reshape(-1, 1)
        np.testing.assert_array_equal(read_data, expected)

    def test_huge_write_overflow(self):
        # Test writing a single chunk larger than capacity
        rb = RingBuffer(10, 1)
        data = np.arange(25, dtype=np.float32).reshape(-1, 1)
        rb.write(data)

        self.assertEqual(rb.available(), 10)
        read_data = rb.read()
        # Should contain the last 10 samples (15 to 24)
        expected = np.arange(15, 25, dtype=np.float32).reshape(-1, 1)
        np.testing.assert_array_equal(read_data, expected)

    def test_mono_broadcasting(self):
        rb = RingBuffer(10, 2)
        # Write mono data (5, 1)
        data = np.arange(5, dtype=np.float32).reshape(-1, 1)
        rb.write(data)

        read_data = rb.read()
        self.assertEqual(read_data.shape, (5, 2))
        # Column 0 should be 0..4, Column 1 should be 0..4
        expected_col = np.arange(5, dtype=np.float32)
        np.testing.assert_array_equal(read_data[:, 0], expected_col)
        np.testing.assert_array_equal(read_data[:, 1], expected_col)

    def test_1d_array_write(self):
        rb = RingBuffer(10, 2)
        # Write 1D data (5,)
        data = np.arange(5, dtype=np.float32)
        rb.write(data)

        read_data = rb.read()
        self.assertEqual(read_data.shape, (5, 2))
        expected_col = np.arange(5, dtype=np.float32)
        np.testing.assert_array_equal(read_data[:, 0], expected_col)
        np.testing.assert_array_equal(read_data[:, 1], expected_col)

    def test_extra_channels_write(self):
        # Test writing 4 channels to 2 channel buffer
        rb = RingBuffer(10, 2)
        # Data: (5, 4)
        data = np.zeros((5, 4), dtype=np.float32)
        data[:, 0] = 1.0
        data[:, 1] = 2.0
        data[:, 2] = 3.0
        data[:, 3] = 4.0

        rb.write(data)

        read_data = rb.read()
        self.assertEqual(read_data.shape, (5, 2))
        # Should keep first 2 channels
        expected = np.zeros((5, 2), dtype=np.float32)
        expected[:, 0] = 1.0
        expected[:, 1] = 2.0

        np.testing.assert_array_equal(read_data, expected)

    def test_reset(self):
        rb = RingBuffer(10, 1)
        rb.write(np.ones((5, 1)))
        rb.reset()
        self.assertEqual(rb.available(), 0)
        self.assertEqual(rb._write_index, 0)
        self.assertEqual(rb._read_index, 0)

    def test_partial_read_limit(self):
        rb = RingBuffer(10, 1)
        rb.write(np.ones((5, 1)))

        # Try to read 10
        read_data = rb.read(10)
        self.assertEqual(read_data.shape, (5, 1))
        self.assertEqual(rb.available(), 0)

if __name__ == "__main__":
    unittest.main()
