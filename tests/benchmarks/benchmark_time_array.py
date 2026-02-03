import timeit
import numpy as np
import tracemalloc
import sys
import os

# Add repo root to path to import src
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from src.core.analysis import _get_time_array

def benchmark():
    N = 10_000_000
    sr = 44100.0
    iterations = 20

    print(f"Benchmarking _get_time_array (N={N}, sr={sr}, Iterations={iterations})")

    # Access the unwrapped function to bypass lru_cache for benchmarking
    # lru_cache wraps the function, the original function is available as __wrapped__ if available,
    # or we can just clear cache every time. But clearing cache is easier.

    # Actually, we want to measure the function execution itself, not the cache hit.
    # So we should call it with different N or clear cache.
    # But for micro-benchmarking, clearing cache adds overhead.
    # Accessing .__wrapped__ is better.

    # Define baseline simulation (what the code currently does)
    def current_impl():
        # logic: t = np.arange(N) / sr
        return np.arange(N) / sr

    # Define optimized simulation
    def optimized_impl():
        t = np.arange(N, dtype=np.float64)
        t /= sr
        return t

    # Verify correctness
    t1 = current_impl()
    t2 = optimized_impl()
    if not np.allclose(t1, t2):
        print("ERROR: Implementations differ in result!")
        return

    # Measure Time
    t_base = timeit.timeit(current_impl, number=iterations)
    print(f"Baseline Time:  {t_base:.4f} seconds")

    t_opt = timeit.timeit(optimized_impl, number=iterations)
    print(f"Optimized Time: {t_opt:.4f} seconds")

    if t_opt > 0:
        print(f"Speedup: {t_base / t_opt:.2f}x")

    # Measure Memory
    tracemalloc.start()
    current_impl()
    _, peak_base = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    tracemalloc.start()
    optimized_impl()
    _, peak_opt = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    print(f"Baseline Peak Memory:  {peak_base / 1024 / 1024:.2f} MB")
    print(f"Optimized Peak Memory: {peak_opt / 1024 / 1024:.2f} MB")
    print(f"Memory Reduction: {100 * (1 - peak_opt/peak_base):.1f}%")

if __name__ == "__main__":
    benchmark()
