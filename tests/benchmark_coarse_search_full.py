
import time
import numpy as np
import sys
import os
import unittest

# Add src to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../')))

try:
    from src.core.analysis import AudioCalc
except ImportError:
    sys.path.append(os.getcwd())
    from src.core.analysis import AudioCalc

class BenchmarkCoarseSearch(unittest.TestCase):
    def test_benchmark_performance(self):
        sr = 48000
        duration = 10.0 # 10 seconds, 480k samples
        N = int(sr * duration)
        # Mock t array
        t = np.arange(N, dtype=np.float64) / sr
        t.flags.writeable = False

        # Generate a signal
        freq_target = 1000.0
        signal = np.sin(2 * np.pi * freq_target * t) + 0.01 * np.random.randn(N)

        # Grid search parameters
        center_freq = 1000.0
        width = 5.0
        step = 0.1
        # Create grid
        grid = np.arange(center_freq - width, center_freq + width, step)

        print(f"\nSignal length N: {N}")
        print(f"Grid size K: {len(grid)}")

        iterations = 3
        print(f"Running {iterations} iterations...")

        start_time = time.perf_counter()

        for _ in range(iterations):
            best_freq = AudioCalc._perform_coarse_search(signal, t, grid)

        end_time = time.perf_counter()
        avg_time = (end_time - start_time) / iterations

        print(f"Average time per call: {avg_time:.4f} seconds")
        print(f"Total time: {end_time - start_time:.4f} seconds")
        print(f"Best freq found: {best_freq}")

if __name__ == "__main__":
    unittest.main()
