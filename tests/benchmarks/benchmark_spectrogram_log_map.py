import time
import numpy as np


def benchmark_log_map():
    # Parameters
    history_length = 500
    fft_size = 8192
    n_bins = fft_size // 2 + 1
    sample_rate = 44100
    min_freq = 20
    max_freq = 20000

    # Setup Buffer (Spectrogram history)
    buffer = np.random.rand(history_length, n_bins).astype(np.float32)

    # Setup Log Map Indices
    log_freqs = np.logspace(np.log10(min_freq), np.log10(max_freq), n_bins)
    freq_res = sample_rate / fft_size
    linear_indices = log_freqs / freq_res
    indices = np.clip(linear_indices, 0, n_bins - 1).astype(int)

    # Target Log Buffer (for incremental update)
    log_buffer = np.zeros_like(buffer)

    iterations = 1000

    print(f"Benchmark: History={history_length}, FFT={fft_size}, Bins={n_bins}, Iterations={iterations}")

    # --- Baseline: Full Copy ---
    start_time = time.perf_counter()
    for _ in range(iterations):
        # Simulate frame update
        # In the widget, this happens every frame:
        display_buffer = buffer[:, indices]  # noqa: F841
    end_time = time.perf_counter()
    baseline_time = end_time - start_time
    print(f"Baseline (Full Copy): {baseline_time:.4f} s ({baseline_time / iterations * 1000:.4f} ms/frame)")

    # --- Optimized: Incremental Update ---
    # We only update one row per frame
    ptr = 0
    new_row = np.random.rand(n_bins).astype(np.float32)

    # Pre-populate log buffer
    log_buffer = buffer[:, indices].copy()  # Ensure it's writable/owned

    start_time = time.perf_counter()
    for _ in range(iterations):
        # Simulate new data arriving
        # 1. Update raw buffer (cheap)
        buffer[ptr] = new_row

        # 2. Update log buffer incrementally (Optimization)
        log_buffer[ptr] = new_row[indices]

        # 3. Get display buffer (cheap reference)
        # display_buffer = log_buffer

        ptr = (ptr + 1) % history_length

    end_time = time.perf_counter()
    opt_time = end_time - start_time
    print(f"Optimized (Incremental): {opt_time:.4f} s ({opt_time / iterations * 1000:.4f} ms/frame)")

    print(f"Speedup: {baseline_time / opt_time:.2f}x")


if __name__ == "__main__":
    benchmark_log_map()
