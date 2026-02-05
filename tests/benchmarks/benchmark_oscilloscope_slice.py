
import sys
import time
from unittest.mock import MagicMock

import numpy as np

# Mock sounddevice before importing anything that uses it
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

def benchmark_oscilloscope_slice():
    engine = MockAudioEngine()
    scope = Oscilloscope(engine)
    scope.buffer_size = 100000 # Larger buffer to make copies more expensive
    scope.input_data = np.random.rand(scope.buffer_size, 2)

    # Settings
    scope.trigger_source = 0
    scope.trigger_mode = "Auto" # Ensure it always returns data
    window_duration = 0.01 # 10ms -> 480 samples

    iterations = 10000

    # Case 1: Contiguous access (write_index = 0, taking from end)
    scope.write_index = 0

    start_time = time.time()
    for _ in range(iterations):
        _ = scope.get_display_data(window_duration)
    end_time = time.time()

    print(f"Contiguous Access: {iterations} iterations in {end_time - start_time:.4f}s")
    print(f"  Avg per call: {(end_time - start_time)/iterations*1e6:.2f} us")

    # Case 2: Wrapped access (write_index such that needed data wraps)
    required_samples = int(window_duration * engine.sample_rate)
    scope.write_index = required_samples // 2

    start_time = time.time()
    for _ in range(iterations):
        _ = scope.get_display_data(window_duration)
    end_time = time.time()

    print(f"Wrapped Access:    {iterations} iterations in {end_time - start_time:.4f}s")
    print(f"  Avg per call: {(end_time - start_time)/iterations*1e6:.2f} us")

    # Case 3: Trigger Search Overhead (Contiguous)
    scope.trigger_mode = "Normal"
    scope.trigger_level = 10.0 # Won't trigger, but will search
    scope.write_index = 0

    start_time = time.time()
    for _ in range(iterations):
        _ = scope.get_display_data(window_duration)
    end_time = time.time()

    print(f"Trigger Search (No Trig): {iterations} iterations in {end_time - start_time:.4f}s")
    print(f"  Avg per call: {(end_time - start_time)/iterations*1e6:.2f} us")

if __name__ == "__main__":
    benchmark_oscilloscope_slice()
