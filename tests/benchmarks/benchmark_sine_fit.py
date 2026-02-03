
import time
import numpy as np
from src.core.analysis import AudioCalc

def benchmark_sine_fit():
    sampling_rate = 48000
    duration = 1.0
    N = int(sampling_rate * duration)
    t = np.arange(N) / sampling_rate
    freq = 1000.0

    # Generate signal with some noise
    signal = np.sin(2 * np.pi * freq * t) + 0.1 * np.random.randn(N)

    # Warm up
    AudioCalc.optimize_frequency(signal, sampling_rate, freq)

    iterations = 50
    start_time = time.time()
    for _ in range(iterations):
        AudioCalc.optimize_frequency(signal, sampling_rate, freq)
    end_time = time.time()

    avg_time = (end_time - start_time) / iterations
    print(f"Average time per call: {avg_time*1000:.4f} ms")

if __name__ == "__main__":
    benchmark_sine_fit()
