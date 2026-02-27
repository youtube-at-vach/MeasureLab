
import time
import numpy as np
import scipy.signal
import soundfile
import sys
import os

# Add src to python path so we can import AudioCalc
sys.path.append(os.getcwd())

from src.core.analysis import AudioCalc

def benchmark_optimize_frequency():
    sr = 48000
    N = 16384

    t = np.arange(N) / sr
    freq = 1000.0
    signal = np.sin(2 * np.pi * freq * t) + 0.01 * np.random.randn(N)

    # Warm up
    AudioCalc.optimize_frequency(signal, sr, 1005.0)

    iterations = 50

    start_time = time.time()
    for _ in range(iterations):
        AudioCalc.optimize_frequency(signal, sr, 1005.0)
    end_time = time.time()

    print(f"N={N}, Iterations={iterations}")
    print(f"Total time: {end_time - start_time:.4f}s")
    print(f"Avg time per call: {(end_time - start_time)/iterations*1000:.4f}ms")

if __name__ == "__main__":
    benchmark_optimize_frequency()
