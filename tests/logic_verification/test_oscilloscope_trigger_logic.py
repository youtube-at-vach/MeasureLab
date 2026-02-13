import numpy as np

# Dependencies are installed in the environment, so we can import directly.
from src.gui.widgets.oscilloscope import Oscilloscope

class MockCalibration:
    def __init__(self):
        self.input_sensitivity = 1.0

class MockAudioEngine:
    def __init__(self):
        self.sample_rate = 1000 # Use simplistic sample rate for easy index calc
        self.calibration = MockCalibration()
        self.callbacks = {}

    def register_callback(self, callback):
        return 1

    def unregister_callback(self, cid):
        pass

def test_get_display_data_basic():
    engine = MockAudioEngine()
    scope = Oscilloscope(engine)
    scope.buffer_size = 100
    scope.input_data = np.zeros((scope.buffer_size, 2))

    # Create a signal with a pulse
    # Time 0 to 0.1s (100 samples)
    # Pulse at sample 50
    scope.input_data[:, 0] = 0.0
    scope.input_data[50:55, 0] = 1.0

    # Write index at 0 (full buffer, oldest at 0)
    scope.write_index = 0

    scope.trigger_source = 0
    scope.trigger_mode = "Normal"
    scope.trigger_level = 0.5
    scope.trigger_slope = "Rising"

    # Display 10 samples (10ms)
    window_duration = 0.01

    # Trigger should find the pulse at index 50.
    # required_samples = 10
    # search_end = 100 - 10 = 90.
    # search_window = 2048 (clamped to available) -> searches [0, 90]
    # Crossing at 50.
    # Should return data[50 : 60]

    data = scope.get_display_data(window_duration)
    assert data is not None
    assert len(data) == 10
    assert data[0, 0] == 1.0 # The trigger point (or close to it)
    assert np.all(data[:5, 0] == 1.0)
    assert np.all(data[5:, 0] == 0.0)

def test_get_display_data_wrap_around():
    engine = MockAudioEngine()
    scope = Oscilloscope(engine)
    scope.buffer_size = 100
    scope.input_data = np.zeros((scope.buffer_size, 2))

    # Write index at 50.
    # Oldest data at 50. Newest at 49.
    # Logical indices:
    # 0 -> physical 50
    # 49 -> physical 99
    # 50 -> physical 0
    # 99 -> physical 49

    scope.write_index = 50

    # Put a pulse at logical index 80.
    # Physical index = (50 + 80) % 100 = 30.
    scope.input_data[30:35, 0] = 1.0

    scope.trigger_source = 0
    scope.trigger_mode = "Normal"
    scope.trigger_level = 0.5
    scope.trigger_slope = "Rising"

    window_duration = 0.01 # 10 samples

    data = scope.get_display_data(window_duration)

    assert data is not None
    assert len(data) == 10
    # Should capture the pulse
    assert data[0, 0] == 1.0
    assert np.all(data[:5, 0] == 1.0)

def test_get_display_data_trigger_at_wrap_boundary():
    engine = MockAudioEngine()
    scope = Oscilloscope(engine)
    scope.buffer_size = 100
    scope.input_data = np.zeros((scope.buffer_size, 2))

    # Pulse spans across physical boundary
    # write_index = 50.
    # Logical index 45 to 55 crosses physical 95 -> 4
    # Pulse at logical 48.
    # Physical: (50+48)%100 = 98.
    # 98, 99, 0, 1, 2

    scope.write_index = 50
    scope.input_data[98, 0] = 1.0
    scope.input_data[99, 0] = 1.0
    scope.input_data[0, 0] = 1.0
    scope.input_data[1, 0] = 1.0
    scope.input_data[2, 0] = 1.0

    scope.trigger_source = 0
    scope.trigger_mode = "Normal"
    scope.trigger_level = 0.5
    scope.trigger_slope = "Rising"

    window_duration = 0.01 # 10 samples

    data = scope.get_display_data(window_duration)

    assert data is not None
    assert len(data) == 10
    assert data[0, 0] == 1.0

def test_single_mode_stops_capture():
    engine = MockAudioEngine()
    engine.sample_rate = 48000
    scope = Oscilloscope(engine)

    scope.trigger_source = 0
    scope.trigger_slope = 'Rising'
    scope.trigger_level = 0.0
    scope.trigger_mode = 'Single'
    scope.single_shot_armed = True
    scope.single_shot_fired = False

    # We need a larger buffer for this test logic to work as expected
    scope.buffer_size = 10000
    scope.input_data = np.full((scope.buffer_size, 2), -1.0) # Reset buffer

    # Make a buffer with a clean rising crossing inside the search window.
    # Search window is typically 2048.
    # buffer_size = 10000.
    # required_samples (for 10ms) = 480.
    # search_end = 10000 - 480 = 9520.
    # search_window = 2048.
    # Searches [7472, 9520].

    crossing_prev = 7700
    crossing_now = 7701
    scope.input_data[crossing_prev, 0] = -0.5
    scope.input_data[crossing_now, 0] = 0.5

    window_duration = 0.01  # 10ms
    data = scope.get_display_data(window_duration)

    assert data is not None, "Should capture trigger"
    assert scope.single_shot_fired is True, "Should set fired flag"
    assert scope.single_shot_armed is False, "Should disarm"

    # After firing, further calls should not produce new data until re-armed.
    data2 = scope.get_display_data(window_duration)
    assert data2 is None, "Should not capture after firing in Single mode"
