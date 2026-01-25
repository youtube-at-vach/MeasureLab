
import numpy as np
import pytest
from unittest.mock import MagicMock
# We mock AudioEngine to avoid importing sounddevice or heavy dependencies if possible,
# but we need to import LockInAmplifier which imports AudioEngine.
# Assuming AudioEngine import is safe (it imports sounddevice but doesn't init it immediately usually).
from src.gui.widgets.lock_in_amplifier import LockInAmplifier

class MockAudioEngine:
    def __init__(self):
        self.sample_rate = 48000
        self.callbacks = []
        self.calibration = MagicMock()

    def register_callback(self, callback):
        self.callbacks.append(callback)
        return len(self.callbacks) - 1

    def unregister_callback(self, id):
        pass

def test_lockin_buffer_logic_deque():
    engine = MockAudioEngine()
    lockin = LockInAmplifier(engine)
    lockin.buffer_size = 10
    lockin.start_analysis()

    callback = engine.callbacks[0]

    # 1. Feed 4 stereo samples
    indata = np.array([[1, 1], [2, 2], [3, 3], [4, 4]], dtype=np.float32)
    outdata = np.zeros((4, 2), dtype=np.float32)
    callback(indata, outdata, 4, 0, 0)

    # Verify deque content
    assert len(lockin.input_blocks) == 1
    np.testing.assert_allclose(lockin.input_blocks[0], indata)

    # Verify reconstruction (process_data logic)
    # Concatenate blocks. Pad if less than buffer_size?
    # Current implementation pads with zeros at start if < buffer_size.

    # Mock process_data logic manually to test it
    blocks = list(lockin.input_blocks)
    full_data = np.concatenate(blocks)
    if len(full_data) < lockin.buffer_size:
        padding = np.zeros((lockin.buffer_size - len(full_data), 2))
        data = np.vstack((padding, full_data))
    else:
        data = full_data[-lockin.buffer_size:]

    expected = np.zeros((10, 2))
    expected[-4:] = indata
    np.testing.assert_allclose(data, expected)

    # 2. Feed 8 more samples
    indata2 = np.array([[5, 5], [6, 6], [7, 7], [8, 8], [9, 9], [10, 10], [11, 11], [12, 12]], dtype=np.float32)
    outdata2 = np.zeros((8, 2), dtype=np.float32)
    callback(indata2, outdata2, 8, 0, 0)

    # Total samples fed: 12. Buffer size: 10.
    # Deque logic keeps "at least" buffer_size?
    # Deque: [4 samples], [8 samples] -> Total 12.
    # Pruning: while size - first >= 10.
    # 12 - 4 = 8 < 10. So it keeps both blocks.

    assert len(lockin.input_blocks) == 2

    # Verify reconstruction
    # Should contain last 10 samples: [3..12]
    # Input was [1..4] then [5..12].
    # Concatenated: [1..12].
    # Last 10: [3..12].

    blocks = list(lockin.input_blocks)
    full_data = np.concatenate(blocks)
    data = full_data[-lockin.buffer_size:]

    expected_2 = np.vstack((indata[-2:], indata2)) # [3, 4] + [5..12]
    np.testing.assert_allclose(data, expected_2)

    # 3. Feed huge block (15 samples)
    indata3 = np.ones((15, 2), dtype=np.float32) * 99
    outdata3 = np.zeros((15, 2), dtype=np.float32)
    callback(indata3, outdata3, 15, 0, 0)

    # Deque: [4], [8], [15]. Size = 27.
    # Pruning:
    # 27 - 4 = 23 >= 10. Pop [4]. Size = 23.
    # 23 - 8 = 15 >= 10. Pop [8]. Size = 15.
    # 15 - 15 = 0 < 10. Stop.
    # Remaining: [15].

    assert len(lockin.input_blocks) == 1
    np.testing.assert_allclose(lockin.input_blocks[0], indata3)

    # Verify data is just the last 10 of indata3
    blocks = list(lockin.input_blocks)
    full_data = np.concatenate(blocks)
    data = full_data[-lockin.buffer_size:]

    np.testing.assert_allclose(data, indata3[-10:])

def test_lockin_buffer_logic_mono_expansion():
    engine = MockAudioEngine()
    lockin = LockInAmplifier(engine)
    lockin.buffer_size = 10
    lockin.start_analysis()

    callback = engine.callbacks[0]

    # Feed 4 mono samples
    indata = np.array([[1], [2], [3], [4]], dtype=np.float32) # (4, 1)
    outdata = np.zeros((4, 2), dtype=np.float32)
    callback(indata, outdata, 4, 0, 0)

    # Verify stored block is (4, 1)
    assert len(lockin.input_blocks) == 1
    assert lockin.input_blocks[0].shape == (4, 1)

    # Verify reconstruction expands to stereo
    blocks = list(lockin.input_blocks)
    full_data = np.concatenate(blocks)

    # Expansion logic
    if full_data.shape[1] < 2:
        col = full_data[:, 0]
        full_data = np.column_stack((col, col))

    if len(full_data) < 10:
        padding = np.zeros((10 - len(full_data), 2))
        data = np.vstack((padding, full_data))

    expected = np.zeros((10, 2))
    expected[-4:, 0] = indata.flatten()
    expected[-4:, 1] = indata.flatten()

    np.testing.assert_allclose(data, expected)
