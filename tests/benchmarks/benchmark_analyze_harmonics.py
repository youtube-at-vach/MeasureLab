
import time
import numpy as np
from src.core.analysis import AudioCalc

def benchmark_analyze_harmonics():
    # Setup parameters
    sampling_rate = 48000
    duration = 0.5  # seconds
    t = np.linspace(0, duration, int(sampling_rate * duration), endpoint=False)

    fundamental_freq = 1000.0
    signal = np.sin(2 * np.pi * fundamental_freq * t)

    # Add harmonics
    for i in range(2, 11):
        signal += 0.1 * np.sin(2 * np.pi * fundamental_freq * i * t)

    # Add some noise
    signal += 0.01 * np.random.normal(size=len(t))

    window_name = "hann"

    # Warmup
    for _ in range(5):
        AudioCalc.analyze_harmonics(signal, fundamental_freq, window_name, sampling_rate)

    # Benchmark
    iterations = 100
    start_time = time.perf_counter()
    for _ in range(iterations):
        AudioCalc.analyze_harmonics(signal, fundamental_freq, window_name, sampling_rate)
    end_time = time.perf_counter()

    avg_time = (end_time - start_time) / iterations
    print(f"Average time per call: {avg_time * 1000:.4f} ms")

if __name__ == "__main__":
    benchmark_analyze_harmonics()
