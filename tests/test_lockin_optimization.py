
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

def test_lockin_buffer_logic_stereo():
    engine = MockAudioEngine()
    lockin = LockInAmplifier(engine)
    lockin.buffer_size = 10 # Small buffer for testing
    lockin.start_analysis()

    assert len(engine.callbacks) > 0
    callback = engine.callbacks[0]

    # Initial state: zeros
    assert np.all(lockin.input_data == 0)

    # Feed 4 stereo samples
    indata = np.array([[1, 1], [2, 2], [3, 3], [4, 4]], dtype=np.float32)
    outdata = np.zeros((4, 2), dtype=np.float32)

    callback(indata, outdata, 4, 0, 0)

    # Expected: [0, 0, ..., 1, 2, 3, 4] (last 4 are new)
    expected = np.zeros((10, 2))
    expected[-4:] = indata

    np.testing.assert_allclose(lockin.input_data, expected)

    # Feed 8 more samples
    indata2 = np.array([[5, 5], [6, 6], [7, 7], [8, 8], [9, 9], [10, 10], [11, 11], [12, 12]], dtype=np.float32)
    outdata2 = np.zeros((8, 2), dtype=np.float32)
    callback(indata2, outdata2, 8, 0, 0)

    # Expected: 2 samples from previous (3, 4) shifted, then 5..12
    # Buffer was [0...0, 1, 2, 3, 4]
    # Shift left by 8.
    # [3, 4] remain at start.
    # [5..12] appended.

    expected_2 = np.zeros((10, 2))
    expected_2[0] = [3, 3]
    expected_2[1] = [4, 4]
    expected_2[2:] = indata2

    np.testing.assert_allclose(lockin.input_data, expected_2)

    # Feed larger than buffer (12 samples)
    indata3 = np.arange(24, dtype=np.float32).reshape(12, 2)
    outdata3 = np.zeros((12, 2), dtype=np.float32)
    callback(indata3, outdata3, 12, 0, 0)

    # Expected: last 10 samples of indata3
    expected_3 = indata3[-10:]
    np.testing.assert_allclose(lockin.input_data, expected_3)

def test_lockin_buffer_logic_mono():
    engine = MockAudioEngine()
    lockin = LockInAmplifier(engine)
    lockin.buffer_size = 10
    lockin.start_analysis()

    callback = engine.callbacks[0]

    # Feed 4 mono samples
    indata = np.array([[1], [2], [3], [4]], dtype=np.float32)
    outdata = np.zeros((4, 2), dtype=np.float32)

    callback(indata, outdata, 4, 0, 0)

    expected = np.zeros((10, 2))
    expected[-4:, 0] = indata.flatten()
    expected[-4:, 1] = indata.flatten()

    np.testing.assert_allclose(lockin.input_data, expected)

    # Feed larger than buffer mono
    indata2 = np.arange(12, dtype=np.float32).reshape(12, 1)
    outdata2 = np.zeros((12, 2), dtype=np.float32)
    callback(indata2, outdata2, 12, 0, 0)

    expected_2 = np.zeros((10, 2))
    src = indata2[-10:].flatten()
    expected_2[:, 0] = src
    expected_2[:, 1] = src

    np.testing.assert_allclose(lockin.input_data, expected_2)
