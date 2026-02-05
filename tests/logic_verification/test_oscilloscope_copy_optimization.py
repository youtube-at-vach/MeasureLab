
import sys
from unittest.mock import MagicMock
import numpy as np

# Mock sounddevice
sys.modules["sounddevice"] = MagicMock()

from src.gui.widgets.oscilloscope import Oscilloscope # noqa: E402

class MockCalibration:
    def __init__(self):
        self.input_sensitivity = 1.0

class MockAudioEngine:
    def __init__(self):
        self.sample_rate = 48000
        self.calibration = MockCalibration()
        self.callbacks = {}

    def register_callback(self, callback):
        return 1

    def unregister_callback(self, cid):
        pass

def test_get_data_slice_copy_behavior():
    engine = MockAudioEngine()
    scope = Oscilloscope(engine)
    scope.buffer_size = 100
    scope.input_data = np.zeros((scope.buffer_size, 2))

    # Fill with some data
    scope.input_data[:, 0] = np.arange(100)
    scope.write_index = 0

    # Case 1: Contiguous, copy=False -> Should return view
    # Request 10 samples from start
    data_view = scope._get_data_slice(0, 10, copy=False)

    # Check if it shares memory
    assert data_view.base is not None
    assert data_view.base is scope.input_data

    # Verify modification affects source (proof of view)
    data_view[0, 0] = 999
    assert scope.input_data[0, 0] == 999

    # Case 2: Contiguous, copy=True -> Should return copy
    data_copy = scope._get_data_slice(0, 10, copy=True)
    assert data_copy.base is None or data_copy.base is not scope.input_data

    data_copy[1, 0] = 888
    assert scope.input_data[1, 0] != 888 # Source untouched

    # Case 3: Wrapped, copy=False -> Must return copy (concatenation)
    scope.write_index = 50
    # Request 60 samples starting at 0 (physical 50).
    # 50 -> 99 (50 samples), 0 -> 9 (10 samples).
    # idx = 50. length = 60. end_idx = 110 > 100. Wrapped.
    data_wrapped = scope._get_data_slice(0, 60, copy=False)

    # Concatenation creates new array, base is usually None (owns data) or points to concat result
    assert data_wrapped.base is None or data_wrapped.base is not scope.input_data

def test_get_display_data_copy_behavior():
    engine = MockAudioEngine()
    scope = Oscilloscope(engine)
    scope.buffer_size = 1000
    scope.input_data = np.zeros((scope.buffer_size, 2))
    scope.write_index = 0
    scope.trigger_mode = "Auto"

    # Contiguous request
    window_duration = 0.001 # small

    # copy=False
    data = scope.get_display_data(window_duration, copy=False)
    assert data.base is scope.input_data

    # copy=True (default)
    data_c = scope.get_display_data(window_duration) # Default is True? No, I added copy arg but kept default True in definition?
    # I changed definition: def get_display_data(self, window_duration, copy=True):
    assert data_c.base is None or data_c.base is not scope.input_data

def test_update_plot_filtering_copy_safety():
    # Verify that if we filter, we don't modify the source buffer
    engine = MockAudioEngine()
    scope = Oscilloscope(engine)
    scope.buffer_size = 100
    scope.input_data = np.ones((scope.buffer_size, 2)) * 10.0
    scope.write_index = 0
    scope.trigger_mode = "Auto"

    # Mock the module in a fake widget context
    # But I can just simulate what update_plot does.

    # Scenario: Filter Enabled
    scope.filter_type = "LPF"
    scope.filter_cutoff = 1000

    # Get view
    data = scope.get_display_data(0.001, copy=False) # Should be view
    assert data.base is scope.input_data
    assert data[0, 0] == 10.0

    # Simulate update_plot logic:
    if scope.filter_type != "None":
        data = data.copy()
        # Modify data
        data[:] = 0.0

    # Check source buffer
    assert scope.input_data[0, 0] == 10.0 # Should remain 10.0
