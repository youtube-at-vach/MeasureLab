import sys
import time
from unittest.mock import MagicMock

import numpy as np

# Mock sounddevice before importing anything that uses it
sys.modules["sounddevice"] = MagicMock()

from src.core.audio_engine import AudioEngine  # noqa: E402
from src.gui.widgets.noise_profiler import NoiseProfiler  # noqa: E402


def benchmark_noise_profiler_process_data():
    # Mock AudioEngine
    audio_engine = MagicMock(spec=AudioEngine)
    audio_engine.sample_rate = 48000
    audio_engine.calibration = MagicMock()
    audio_engine.calibration.get_input_offset_db.return_value = 0.0

    # Initialize NoiseProfiler
    profiler = NoiseProfiler(audio_engine)
    profiler.buffer_size = 65536 * 4  # HUGE buffer to really test it
    profiler.set_buffer_size(profiler.buffer_size)

    # Fill input data with random noise
    profiler.input_data = np.random.normal(0, 0.1, (profiler.buffer_size, 2))

    print(f"Buffer size: {profiler.buffer_size}")

    # Warmup
    res = profiler.process_data(0, "dBV/√Hz", False)
    if res is None:
        print("Warmup returned None!")
    else:
        print("Warmup success.")

    # Benchmark
    iterations = 20
    start_time = time.time()

    for i in range(iterations):
        res = profiler.process_data(0, "dBV/√Hz", False)
        if res is None:
            print(f"Iteration {i} returned None!")

    end_time = time.time()
    avg_time = (end_time - start_time) / iterations

    print(f"\nAverage process_data time (buffer={profiler.buffer_size}): {avg_time*1000:.2f} ms")


if __name__ == "__main__":
    benchmark_noise_profiler_process_data()
