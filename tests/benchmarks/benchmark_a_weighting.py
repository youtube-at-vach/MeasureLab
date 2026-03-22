import time
import numpy as np
from src.core.analysis import AudioCalc, _calculate_ra_raw

# Mock _compute_a_weighting_sq_curve to ensure we are testing what we think we are testing
# but we want to test the integration in AudioCalc.calculate_noise_profile


def benchmark_a_weighting():
    fs = 48000
    N = 16384

    # Case 1: Standard Linear Frequencies (rfft)
    freqs_linear = np.fft.rfftfreq(N, 1 / fs)
    mag = np.random.random(len(freqs_linear))

    print("--- Linear Frequency Array ---")

    # Warmup
    for _ in range(10):
        AudioCalc.calculate_noise_profile(mag, freqs_linear, fs)

    start = time.time()
    iterations = 100
    for _ in range(iterations):
        AudioCalc.calculate_noise_profile(mag, freqs_linear, fs)
    end = time.time()
    print(f"Time per call (Linear): {(end - start) / iterations * 1000:.4f} ms")

    # Case 2: Non-Linear Frequencies (e.g. log spaced or perturbed)
    # This currently should miss the cache and trigger full calculation
    freqs_nonlinear = freqs_linear.copy()
    freqs_nonlinear[-1] += 0.5  # Break linearity

    print("\n--- Non-Linear Frequency Array ---")

    # Warmup
    for _ in range(10):
        AudioCalc.calculate_noise_profile(mag, freqs_nonlinear, fs)

    start = time.time()
    for _ in range(iterations):
        AudioCalc.calculate_noise_profile(mag, freqs_nonlinear, fs)
    end = time.time()
    print(f"Time per call (Non-Linear): {(end - start) / iterations * 1000:.4f} ms")

    # Verify baseline performance of _calculate_ra_raw (uncached)
    start = time.time()
    for _ in range(iterations):
        ra = _calculate_ra_raw(freqs_nonlinear)
        _ = (ra * 1.2589) ** 2
    end = time.time()
    print(f"Time per call (Raw Calc): {(end - start) / iterations * 1000:.4f} ms")


if __name__ == "__main__":
    benchmark_a_weighting()
