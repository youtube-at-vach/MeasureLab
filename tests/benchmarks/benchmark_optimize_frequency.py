import time
import numpy as np
from src.core.analysis import AudioCalc


def benchmark():
    sr = 48000
    duration = 1.0  # 1 second -> 48000 samples
    N = int(sr * duration)
    t = np.arange(N) / sr
    freq = 1000.0
    # Add noise
    signal = np.sin(2 * np.pi * freq * t) + 0.1 * np.random.randn(N)

    # Run once to warm up cache
    AudioCalc.optimize_frequency(signal, sr, freq)

    iterations = 20  # Reduce iterations as it will be slower
    start_time = time.time()
    for _ in range(iterations):
        AudioCalc.optimize_frequency(signal, sr, freq)
    end_time = time.time()

    avg_time = (end_time - start_time) / iterations
    print(f"Average time per call: {avg_time*1000:.4f} ms")


if __name__ == "__main__":
    benchmark()
