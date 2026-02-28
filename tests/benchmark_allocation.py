
import timeit
import numpy as np
import threading

# Simulate the buffer sharing mechanism to benchmark against pure allocation
_analysis_thread_local = threading.local()

def _get_shared_buffers_bench(N, dtype):
    if not hasattr(_analysis_thread_local, "buffer_cache"):
        _analysis_thread_local.buffer_cache = {}

    cache = _analysis_thread_local.buffer_cache
    key = (N, dtype)

    if key in cache:
        return cache[key]

    M = np.empty((N, 3), dtype=dtype)
    M[:, 2] = 1.0
    fitted_buffer = np.empty(N, dtype=dtype)
    residual_buffer = np.empty(N, dtype=dtype)

    cache.clear()
    cache[key] = (M, fitted_buffer, residual_buffer)
    return M, fitted_buffer, residual_buffer

def benchmark_allocation():
    N = 16384
    dtype = np.float64

    def allocate_fresh():
        M = np.empty((N, 3), dtype=dtype)
        M[:, 2] = 1.0
        _fitted = np.empty(N, dtype=dtype)
        _residual = np.empty(N, dtype=dtype)

    def allocate_cached():
        _buffers = _get_shared_buffers_bench(N, dtype)

    # Warm up cache
    allocate_cached()

    iterations = 100000

    t_fresh = timeit.timeit(allocate_fresh, number=iterations)
    print(f"Time for {iterations} fresh allocations: {t_fresh:.4f}s")
    print(f"Time per fresh allocation: {t_fresh/iterations*1000:.4f}ms")

    t_cached = timeit.timeit(allocate_cached, number=iterations)
    print(f"Time for {iterations} cached retrievals: {t_cached:.4f}s")
    print(f"Time per cached retrieval: {t_cached/iterations*1000:.4f}ms")

    speedup = t_fresh / t_cached if t_cached > 0 else float('inf')
    print(f"Speedup: {speedup:.2f}x")

if __name__ == "__main__":
    benchmark_allocation()
