
import sys
import os
import time
import numpy as np
from scipy.signal.windows import dpss

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from src.core.fft_manager import fft_manager

def benchmark_multitaper_original(data, windows, K):
    N = len(data)
    n_freqs = N // 2 + 1

    # Simulate surrounding code
    psd_accum_0 = np.zeros(n_freqs)
    psd_accum_1 = np.zeros(n_freqs)

    start_time = time.time()
    for k in range(K):
        w = windows[k]

        # Channel 0
        fft_0 = fft_manager.rfft(data[:, 0] * w)
        psd_accum_0 += np.abs(fft_0) ** 2

        # Channel 1
        fft_1 = fft_manager.rfft(data[:, 1] * w)
        psd_accum_1 += np.abs(fft_1) ** 2

    end_time = time.time()
    return end_time - start_time

def benchmark_multitaper_optimized(data, windows, K):
    N = len(data)
    n_freqs = N // 2 + 1

    # Pre-allocations
    psd_accum_0 = np.zeros(n_freqs)
    psd_accum_1 = np.zeros(n_freqs)

    windowed_buffer = np.empty(N, dtype=data.dtype)
    out_dtype = np.complex128 if data.dtype == np.float64 else np.complex64
    fft_out = np.empty(n_freqs, dtype=out_dtype)
    temp_psd = np.empty(n_freqs, dtype=psd_accum_0.dtype)

    start_time = time.time()
    for k in range(K):
        w = windows[k]

        # Channel 0
        np.multiply(data[:, 0], w, out=windowed_buffer)
        fft_manager.rfft(windowed_buffer, out=fft_out)

        # Optimize abs(fft)**2 -> real**2 + imag**2
        np.square(fft_out.real, out=temp_psd)
        psd_accum_0 += temp_psd
        np.square(fft_out.imag, out=temp_psd)
        psd_accum_0 += temp_psd

        # Channel 1
        np.multiply(data[:, 1], w, out=windowed_buffer)
        fft_manager.rfft(windowed_buffer, out=fft_out)

        np.square(fft_out.real, out=temp_psd)
        psd_accum_1 += temp_psd
        np.square(fft_out.imag, out=temp_psd)
        psd_accum_1 += temp_psd

    end_time = time.time()
    return end_time - start_time

def run_benchmark():
    N = 8192
    NW = 3
    K = 2 * NW - 1

    print(f"Benchmarking Multitaper Loop (N={N}, K={K})...")

    # Prepare data once
    data = np.random.random((N, 2))
    windows = dpss(N, NW, K)

    # Warmup
    benchmark_multitaper_original(data, windows, K)
    benchmark_multitaper_optimized(data, windows, K)

    iterations = 100
    t_orig = 0
    t_opt = 0

    for _ in range(iterations):
        t_orig += benchmark_multitaper_original(data, windows, K)
        t_opt += benchmark_multitaper_optimized(data, windows, K)

    avg_orig = t_orig / iterations * 1000
    avg_opt = t_opt / iterations * 1000

    print(f"Original: {avg_orig:.3f} ms")
    print(f"Optimized: {avg_opt:.3f} ms")
    print(f"Improvement: {(avg_orig - avg_opt)/avg_orig * 100:.1f}%")

if __name__ == "__main__":
    run_benchmark()
