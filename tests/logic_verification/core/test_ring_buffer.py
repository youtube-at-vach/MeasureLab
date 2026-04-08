import pytest
import numpy as np
from src.core.ring_buffer import RingBuffer

def test_initialization():
    rb = RingBuffer(100, 2)
    assert rb.capacity == 100
    assert rb.channels == 2
    assert rb.available() == 0

    with pytest.raises(ValueError):
        RingBuffer(0, 1)
    with pytest.raises(ValueError):
        RingBuffer(-1, 1)
    with pytest.raises(ValueError):
        RingBuffer(10, 0)

def test_basic_write_read():
    rb = RingBuffer(10, 2)
    data = np.ones((5, 2), dtype=np.float32)
    rb.write(data)
    assert rb.available() == 5

    read_data = rb.read(5)
    assert read_data.shape == (5, 2)
    np.testing.assert_array_equal(read_data, data)
    assert rb.available() == 0

def test_wrap_around():
    rb = RingBuffer(10, 1)
    # Write 8
    rb.write(np.ones((8, 1)))
    # Read 5 (3 remaining)
    rb.read(5)
    assert rb.available() == 3

    # Write 5 (Total 8 samples in buffer, wrapping around)
    data2 = np.full((5, 1), 2.0)
    rb.write(data2)

    assert rb.available() == 8

    # Read all
    all_data = rb.read()
    assert all_data.shape == (8, 1)
    # Expected: 3 ones (from first write), 5 twos (from second write)
    expected = np.concatenate((np.ones((3, 1)), np.full((5, 1), 2.0)))
    np.testing.assert_array_equal(all_data, expected)

def test_overflow_behavior():
    rb = RingBuffer(10, 1)
    # Write 15 samples (capacity 10) - sequential writes
    data = np.arange(15, dtype=np.float32).reshape(-1, 1)
    rb.write(data[:8])  # Write 8
    rb.write(data[8:])  # Write 7 (Total 15)

    assert rb.available() == 10

    read_data = rb.read()
    assert read_data.shape == (10, 1)
    expected = np.arange(5, 15, dtype=np.float32).reshape(-1, 1)
    np.testing.assert_array_equal(read_data, expected)

def test_huge_write_overflow():
    # Test writing a single chunk larger than capacity
    rb = RingBuffer(10, 1)
    data = np.arange(25, dtype=np.float32).reshape(-1, 1)
    rb.write(data)

    assert rb.available() == 10
    read_data = rb.read()
    # Should contain the last 10 samples (15 to 24)
    expected = np.arange(15, 25, dtype=np.float32).reshape(-1, 1)
    np.testing.assert_array_equal(read_data, expected)

def test_mono_broadcasting():
    rb = RingBuffer(10, 2)
    # Write mono data (5, 1)
    data = np.arange(5, dtype=np.float32).reshape(-1, 1)
    rb.write(data)

    read_data = rb.read()
    assert read_data.shape == (5, 2)
    expected_col = np.arange(5, dtype=np.float32)
    np.testing.assert_array_equal(read_data[:, 0], expected_col)
    np.testing.assert_array_equal(read_data[:, 1], expected_col)

def test_1d_array_write():
    rb = RingBuffer(10, 2)
    # Write 1D data (5,)
    data = np.arange(5, dtype=np.float32)
    rb.write(data)

    read_data = rb.read()
    assert read_data.shape == (5, 2)
    expected_col = np.arange(5, dtype=np.float32)
    np.testing.assert_array_equal(read_data[:, 0], expected_col)
    np.testing.assert_array_equal(read_data[:, 1], expected_col)

def test_extra_channels_write():
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
    assert read_data.shape == (5, 2)
    # Should keep first 2 channels
    expected = np.zeros((5, 2), dtype=np.float32)
    expected[:, 0] = 1.0
    expected[:, 1] = 2.0

    np.testing.assert_array_equal(read_data, expected)

def test_reset():
    rb = RingBuffer(10, 1)
    rb.write(np.ones((5, 1)))
    rb.reset()
    assert rb.available() == 0
    # Also verify internal indices are reset
    assert rb._write_index == 0
    assert rb._read_index == 0

def test_partial_read_limit():
    rb = RingBuffer(10, 1)
    rb.write(np.ones((5, 1)))

    # Try to read 10, should only return 5
    read_data = rb.read(10)
    assert read_data.shape == (5, 1)
    assert rb.available() == 0

def test_read_empty():
    rb = RingBuffer(10, 2)
    # Read from empty buffer
    read_data = rb.read()
    assert read_data.shape == (0, 2)
    assert rb.available() == 0

    # Write and read all, then read again
    rb.write(np.ones((5, 2)))
    rb.read()
    read_data_again = rb.read()
    assert read_data_again.shape == (0, 2)
    assert rb.available() == 0
