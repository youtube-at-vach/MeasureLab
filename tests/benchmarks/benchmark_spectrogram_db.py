import time
import numpy as np


def run_benchmark():
    fft_sizes = [8192, 32768, 65536]
    iterations = 5000

    for fft_size in fft_sizes:
        num_bins = fft_size // 2 + 1
        source_mag = np.random.random(num_bins).astype(np.float64)

        print(f"\nBenchmarking with FFT size {fft_size} (bins: {num_bins}), {iterations} iterations.")

        # --- Original ---
        start = time.perf_counter()
        for _ in range(iterations):
            mag = source_mag.copy()
            with np.errstate(divide="ignore"):
                _ = 20 * np.log10(mag + 1e-12)
        duration_original = time.perf_counter() - start
        print(f"Original: {duration_original:.4f} seconds")

        # --- Optimized ---
        start = time.perf_counter()
        for _ in range(iterations):
            mag = source_mag.copy()
            with np.errstate(divide="ignore"):
                np.add(mag, 1e-12, out=mag)
                np.log10(mag, out=mag)
                np.multiply(mag, 20, out=mag)
                # In-place result is in 'mag'
        duration_optimized = time.perf_counter() - start
        print(f"Optimized: {duration_optimized:.4f} seconds")

        improvement = (duration_original - duration_optimized) / duration_original * 100
        print(f"Improvement: {improvement:.2f}%")


if __name__ == "__main__":
    run_benchmark()
