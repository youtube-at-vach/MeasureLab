import time
import numpy as np
import sys
import types

# Mock sounddevice before importing AudioEngine
mock_sd = types.ModuleType("sounddevice")
mock_sd.query_devices = lambda: [{"name": "Mock Device", "max_input_channels": 2, "max_output_channels": 2}]
mock_sd.default = types.SimpleNamespace(device=0)
mock_sd.check_input_settings = lambda **kwargs: True
mock_sd.check_output_settings = lambda **kwargs: True
mock_sd.CallbackFlags = lambda: 0
sys.modules["sounddevice"] = mock_sd

from src.core.audio_engine import AudioEngine  # noqa: E402
from src.gui.widgets.noise_profiler import NoiseProfiler  # noqa: E402


def benchmark_process_data():
    # Setup
    engine = AudioEngine()
    engine.sample_rate = 48000
    profiler = NoiseProfiler(engine)

    # Fill buffer with noise + hum + 1/f
    N = profiler.buffer_size
    t = np.arange(N) / 48000

    # White noise
    noise = np.random.randn(N) * 1e-6
    # Hum (50Hz)
    hum = 1e-5 * np.sin(2 * np.pi * 50 * t)
    # Signal
    signal = noise + hum

    # Stereo
    data = np.column_stack((signal, signal))
    profiler.input_data = data

    # Warmup
    print("Warming up...")
    for _ in range(5):
        profiler.process_data(0, "dBV", False)

    # Benchmark
    print("Benchmarking process_data...")
    iterations = 20
    start_time = time.time()
    for _ in range(iterations):
        profiler.process_data(0, "dBV", False)
    end_time = time.time()

    total_time = end_time - start_time
    avg_time = total_time / iterations

    print(f"Total time for {iterations} iterations: {total_time:.4f}s")
    print(f"Average time per iteration: {avg_time * 1000:.2f}ms")

    return avg_time


if __name__ == "__main__":
    benchmark_process_data()
