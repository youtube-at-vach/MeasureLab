
import time
import numpy as np
from scipy.signal import sosfiltfilt
from src.core.analysis import AudioCalc, _get_butter_sos

def lowpass_filter_optimized(signal, sampling_rate, cutoff=20000.0):
    nyquist = 0.5 * sampling_rate
    cutoff = min(nyquist - 1, max(0.1, cutoff))
    # Optimization: Pass fs directly to avoid division and leverage cache better if fs/cutoff are standard
    sos = _get_butter_sos(8, cutoff, "lowpass", fs=sampling_rate)
    return sosfiltfilt(sos, signal)

def benchmark_lowpass():
    # Setup
    sr = 48000
    duration = 1.0 # 1 second
    signal = np.random.randn(int(sr * duration))
    cutoff = 20000.0

    iterations = 1000

    # Warmup
    AudioCalc.lowpass_filter(signal, sr, cutoff)
    lowpass_filter_optimized(signal, sr, cutoff)

    # Measure Original
    start = time.perf_counter()
    for _ in range(iterations):
        AudioCalc.lowpass_filter(signal, sr, cutoff)
    end = time.perf_counter()
    original_time = end - start

    # Measure Optimized
    start = time.perf_counter()
    for _ in range(iterations):
        lowpass_filter_optimized(signal, sr, cutoff)
    end = time.perf_counter()
    optimized_time = end - start

    print(f"Original Time: {original_time:.6f} s")
    print(f"Optimized Time: {optimized_time:.6f} s")
    print(f"Improvement: {original_time - optimized_time:.6f} s")
    if optimized_time > 0:
        print(f"Speedup: {original_time / optimized_time:.2f}x")

if __name__ == "__main__":
    benchmark_lowpass()
