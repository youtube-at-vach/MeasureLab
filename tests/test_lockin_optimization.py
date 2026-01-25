
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

def test_lockin_buffer_logic_stereo_circular():
    engine = MockAudioEngine()
    lockin = LockInAmplifier(engine)
    lockin.buffer_size = 10 # Small buffer for testing
    lockin.start_analysis()

    assert len(engine.callbacks) > 0
    callback = engine.callbacks[0]

    # Initial state: zeros
    assert np.all(lockin.input_data == 0)
    assert lockin.write_index == 0

    # Feed 4 stereo samples
    # Buffer is size 10. Index starts at 0.
    # Should write to [0, 1, 2, 3]. Index becomes 4.
    indata = np.array([[1, 1], [2, 2], [3, 3], [4, 4]], dtype=np.float32)
    outdata = np.zeros((4, 2), dtype=np.float32)

    callback(indata, outdata, 4, 0, 0)

    # Check raw buffer
    expected_raw = np.zeros((10, 2))
    expected_raw[0:4] = indata

    np.testing.assert_allclose(lockin.input_data, expected_raw)
    assert lockin.write_index == 4

    # Verify reconstruction logic (simulate what process_data does)
    # Reconstructed: roll(input, -index)
    # roll([1, 2, 3, 4, 0...], -4) -> [0, 0, ..., 1, 2, 3, 4] (Correct order: oldest 0s, newest 4s)
    # Wait, initially buffer is 0.
    # Oldest data is at index 4 (0.0). Newest is at index 3 (4.0).
    # We want oldest -> newest.
    # [0, 0, 0, 0, 0, 0, 1, 2, 3, 4] is the desired logical view?
    # Yes, typically we want [t-N ... t].

    reconstructed = np.roll(lockin.input_data, -lockin.write_index, axis=0)
    expected_logical = np.zeros((10, 2))
    expected_logical[-4:] = indata

    np.testing.assert_allclose(reconstructed, expected_logical)

    # Feed 8 more samples
    # Index is 4. Remaining space is 6 (indices 4..9).
    # We feed 8.
    # First 6 go to [4..9].
    # Next 2 wrap to [0..1].
    # Index becomes 2.

    indata2 = np.array([[5, 5], [6, 6], [7, 7], [8, 8], [9, 9], [10, 10], [11, 11], [12, 12]], dtype=np.float32)
    outdata2 = np.zeros((8, 2), dtype=np.float32)
    callback(indata2, outdata2, 8, 0, 0)

    assert lockin.write_index == 2

    # Expected Raw Buffer:
    # [0]: 11 (wrapped)
    # [1]: 12 (wrapped)
    # [2]: 3 (old)
    # [3]: 4 (old)
    # [4]: 5 (new)
    # ...
    # [9]: 10 (new)

    expected_raw_2 = np.zeros((10, 2))
    expected_raw_2[0] = [11, 11]
    expected_raw_2[1] = [12, 12]
    expected_raw_2[2] = [3, 3]
    expected_raw_2[3] = [4, 4]
    expected_raw_2[4:] = indata2[:6]

    np.testing.assert_allclose(lockin.input_data, expected_raw_2)

    # Verify reconstruction
    # roll(raw, -2).
    # [3, 4, 5, 6, 7, 8, 9, 10, 11, 12]
    # This preserves the order: 3, 4 (from first batch), 5..12 (second batch).
    # 1, 2 from first batch were overwritten.

    reconstructed_2 = np.roll(lockin.input_data, -lockin.write_index, axis=0)

    expected_logical_2 = np.zeros((10, 2))
    expected_logical_2[0] = [3, 3]
    expected_logical_2[1] = [4, 4]
    expected_logical_2[2:] = indata2

    np.testing.assert_allclose(reconstructed_2, expected_logical_2)

def test_lockin_buffer_logic_mono_circular():
    engine = MockAudioEngine()
    lockin = LockInAmplifier(engine)
    lockin.buffer_size = 10
    lockin.start_analysis()

    callback = engine.callbacks[0]

    # Feed 4 mono samples
    indata = np.array([[1], [2], [3], [4]], dtype=np.float32)
    outdata = np.zeros((4, 2), dtype=np.float32)

    callback(indata, outdata, 4, 0, 0)

    expected_raw = np.zeros((10, 2))
    expected_raw[0:4, 0] = indata.flatten()
    expected_raw[0:4, 1] = indata.flatten()

    np.testing.assert_allclose(lockin.input_data, expected_raw)
    assert lockin.write_index == 4

    reconstructed = np.roll(lockin.input_data, -lockin.write_index, axis=0)
    expected_logical = np.zeros((10, 2))
    expected_logical[-4:, 0] = indata.flatten()
    expected_logical[-4:, 1] = indata.flatten()

    np.testing.assert_allclose(reconstructed, expected_logical)
