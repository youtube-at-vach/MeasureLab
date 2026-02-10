
import timeit
import numpy as np
import sys
import os

# Add repo root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from src.core.analysis import get_cached_window

def baseline_method(window_type, length):
    if window_type == "rect":
        return np.ones(length)
    else:
        return getattr(np, window_type)(length)

def optimized_method(window_type, length):
    # Mapping
    scipy_map = {
        "hanning": "hann",
        "rect": "boxcar"
    }
    scipy_name = scipy_map.get(window_type, window_type)

    # Use cached window with fftbins=False to match numpy symmetric
    return get_cached_window(scipy_name, length, fftbins=False)

def benchmark():
    length = 4096
    iterations = 10000

    print(f"Benchmarking Window Generation (N={length}, Iterations={iterations})")

    for w_type in ["hanning", "rect"]:
        print(f"\nWindow Type: {w_type}")

        # Baseline
        t_base = timeit.timeit(lambda w=w_type: baseline_method(w, length), number=iterations)
        print(f"  Baseline (numpy):    {t_base:.4f} seconds")

        # Optimized
        t_opt = timeit.timeit(lambda w=w_type: optimized_method(w, length), number=iterations)
        print(f"  Optimized (cached):  {t_opt:.4f} seconds")

        if t_opt > 0:
            print(f"  Speedup: {t_base / t_opt:.2f}x")

        # Verify correctness
        w_base = baseline_method(w_type, length)
        w_opt = optimized_method(w_type, length)
        if not np.allclose(w_base, w_opt):
            print("  WARNING: Results do not match!")
            print(f"  Max Diff: {np.max(np.abs(w_base - w_opt))}")
        else:
             print("  Correctness: Verified (Identical)")

if __name__ == "__main__":
    benchmark()
