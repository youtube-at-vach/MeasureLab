import sys
import os
import time
from unittest.mock import MagicMock
import numpy as np

# Mock sounddevice before importing anything else that might import it
sys.modules["sounddevice"] = MagicMock()

# Add src to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from src.gui.widgets.sound_level_meter import SoundLevelMeter  # noqa: E402


class MockAudioEngine:
    def __init__(self):
        self.sample_rate = 48000

    def register_callback(self, cb):
        return 1

    def unregister_callback(self, id):
        pass


def benchmark_slm_history():
    engine = MockAudioEngine()
    slm = SoundLevelMeter(engine)

    slm.set_freq_weighting("Z")
    slm.set_time_weighting("FAST")
    slm.start_analysis()

    # Fill up ln_history to simulate long running app
    num_existing_items = 360000
    slm.ln_history_count = num_existing_items
    slm.ln_history_ptr = 0
    slm.ln_history = np.full(slm.ln_history_capacity, 0.1, dtype=np.float32)

    # We want to benchmark the callback which does append
    # and calculate_ln_statistics which does list -> array conversion

    iterations = 1000
    frames = 1024

    # Create fake audio data
    indata = np.random.rand(frames, 2)

    # 1. Benchmark callback overhead (list append vs array insert)
    # The callback appends to ln_history every 0.1 seconds.
    # To benchmark this specifically, we can directly manipulate last_sample_time

    start_time_cb = time.perf_counter()
    for _ in range(iterations):
        # Force a history append
        slm.last_sample_time = 0
        slm.callback(indata, None, frames, None, None)
    end_time_cb = time.perf_counter()

    cb_time = end_time_cb - start_time_cb
    print(f"Callback (with append) time for {iterations} calls: {cb_time:.4f} s")

    # 2. Benchmark statistics calculation (list -> array conversion)
    stats_iterations = 100
    start_time_stats = time.perf_counter()
    for _ in range(stats_iterations):
        slm.calculate_ln_statistics()
    end_time_stats = time.perf_counter()

    stats_time = end_time_stats - start_time_stats
    print(
        f"Stats calculation time for {stats_iterations} calls (array size {slm.ln_history_count}): {stats_time:.4f} s"
    )


if __name__ == "__main__":
    benchmark_slm_history()
