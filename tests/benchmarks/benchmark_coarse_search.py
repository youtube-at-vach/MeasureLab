import time
import numpy as np
import sys
import os

# Adjust path to find src
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from src.core.analysis import AudioCalc

def benchmark_coarse_search():
    sample_rate = 48000
    duration = 1.0 # 1 second
    N = int(sample_rate * duration)
    t = np.arange(N) / sample_rate

    # Generate test signal
    true_freq = 1000.0
    amplitude = 1.0
    signal = amplitude * np.sin(2 * np.pi * true_freq * t)

    # Grid search parameters
    grid = np.linspace(900.0, 1100.0, 200) # 200 frequencies

    # Warm up
    print("Warming up...")
    AudioCalc._perform_coarse_search(signal, t, grid)

    iterations = 50
    start_time = time.perf_counter()

    for _ in range(iterations):
        AudioCalc._perform_coarse_search(signal, t, grid)

    end_time = time.perf_counter()
    avg_time = (end_time - start_time) / iterations

    print(f"Average execution time for _perform_coarse_search: {avg_time * 1000:.2f} ms")

if __name__ == "__main__":
    benchmark_coarse_search()
