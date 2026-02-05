import time
import numpy as np
import sys
import os

# Ensure src is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from src.core.analysis import AudioCalc

def benchmark_optimize_frequency():
    sr = 48000
    freq = 1000.0
    duration = 0.1 # 100ms buffer, typical for updates
    N = int(sr * duration)
    t = np.arange(N) / sr
    # Create signal
    signal = np.sin(2 * np.pi * freq * t) + 0.01 * np.random.normal(size=N)

    # Warmup
    for _ in range(10):
        AudioCalc.optimize_frequency(signal, sr, freq)

    iterations = 200

    # Case 1: Without buffer (original)
    start_time = time.time()
    for _ in range(iterations):
        AudioCalc.optimize_frequency(signal, sr, freq)
    end_time = time.time()
    avg_time_no_buf = (end_time - start_time) / iterations
    print(f"Average time per call (no buffer): {avg_time_no_buf*1000:.4f} ms")

    # Case 2: With buffer
    m_buffer = np.empty((N, 3), dtype=np.float64)
    start_time = time.time()
    for _ in range(iterations):
        AudioCalc.optimize_frequency(signal, sr, freq, m_buffer=m_buffer)
    end_time = time.time()
    avg_time_buf = (end_time - start_time) / iterations
    print(f"Average time per call (with buffer): {avg_time_buf*1000:.4f} ms")

    improvement = (avg_time_no_buf - avg_time_buf) / avg_time_no_buf * 100
    print(f"Improvement: {improvement:.2f}%")

if __name__ == "__main__":
    benchmark_optimize_frequency()
