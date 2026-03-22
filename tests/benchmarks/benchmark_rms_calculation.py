import time
import numpy as np
import sys
import os

# Add src to path if not already there
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from src.core.frequency_analysis import calculate_frequency_metrics


def benchmark_rms():
    # Setup large data array to make memory allocation significant
    # 48kHz for 10 seconds = 480,000 samples
    sr = 48000
    duration = 10.0
    N = int(sr * duration)
    data = np.random.randn(N)

    # Ensure data is below gate threshold so we only benchmark the RMS part
    # If the signal is too loud, the function proceeds to FFT which dominates the time.
    # The current implementation uses rms + 1e-12.
    # We want to trigger the early return: `if db < gate_threshold_db: return None, db`
    # So we set a high gate threshold.
    gate_threshold_db = 100.0

    iterations = 1000

    print(
        f"Benchmarking RMS calculation within calculate_frequency_metrics with {N} samples over {iterations} iterations..."
    )

    start_time = time.time()
    for _ in range(iterations):
        calculate_frequency_metrics(data, sr, gate_threshold_db)
    end_time = time.time()

    avg_time = (end_time - start_time) / iterations
    print(f"Average time per call: {avg_time * 1000:.4f} ms")

    # Direct comparison of the math
    print("\nDirect Math Comparison (1000 iterations):")

    start_time = time.time()
    for _ in range(iterations):
        np.sqrt(np.mean(data**2))
    end_time = time.time()
    mean_sq_time = (end_time - start_time) / iterations
    print(f"np.mean(data**2): {mean_sq_time * 1000:.4f} ms")

    start_time = time.time()
    for _ in range(iterations):
        np.sqrt(np.vdot(data, data) / data.size)
    end_time = time.time()
    vdot_time = (end_time - start_time) / iterations
    print(f"np.vdot(data, data): {vdot_time * 1000:.4f} ms")

    improvement = (mean_sq_time - vdot_time) / mean_sq_time * 100
    print(f"Improvement: {improvement:.2f}%")


if __name__ == "__main__":
    benchmark_rms()
