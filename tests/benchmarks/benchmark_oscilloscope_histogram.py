import time
import numpy as np
import sys
import os
from unittest.mock import MagicMock

# Mock sounddevice
sys.modules['sounddevice'] = MagicMock()

# Add src to path
sys.path.append(os.path.join(os.path.dirname(__file__), '../../'))
from src.gui.widgets.oscilloscope import fast_histogram2d  # noqa: E402

def benchmark_histogram():
    # Setup
    sample_rate = 48000
    duration = 1.0 # 1000ms
    N = int(sample_rate * duration)
    t = np.linspace(0, duration, N)
    # Add some outliers
    y = np.sin(2 * np.pi * 440 * t) + np.random.normal(0, 0.1, N)
    y[0] = 10.0 # Outlier
    y[1] = -10.0 # Outlier

    w, h = 600, 400
    rng = [[0, duration], [-1.1, 1.1]]

    print(f"N = {N}")

    # Baseline: np.histogram2d
    start_time = time.perf_counter()
    iterations = 50
    for _ in range(iterations):
        hist, _, _ = np.histogram2d(t, y, bins=[w, h], range=rng)
    end_time = time.perf_counter()
    avg_time = (end_time - start_time) / iterations
    print(f"Baseline (np.histogram2d): {avg_time*1000:.4f} ms per call")

    # Optimization: fast_histogram2d
    start_time = time.perf_counter()
    for _ in range(iterations):
        _ = fast_histogram2d(t, y, bins=[w, h], range=rng)

    end_time = time.perf_counter()
    avg_time_opt = (end_time - start_time) / iterations
    print(f"Optimization (fast_histogram2d): {avg_time_opt*1000:.4f} ms per call")
    print(f"Speedup: {avg_time / avg_time_opt:.2f}x")

    # Verify correctness just in case
    expected, _, _ = np.histogram2d(t, y, bins=[w, h], range=rng)
    assert np.array_equal(fast_histogram2d(t, y, bins=[w, h], range=rng), expected)
    print("Verification passed.")

if __name__ == "__main__":
    benchmark_histogram()
