
import time
import numpy as np
import pytest

def benchmark_histogram_original(t, y, bins, rng, intensity, heatmap):
    hist, _, _ = np.histogram2d(t, y, bins=bins, range=rng)
    heatmap += hist * intensity * 100
    return heatmap

def benchmark_histogram_optimized(t, y, bins, rng, intensity, heatmap):
    w, h = bins
    x_min, x_max = rng[0]
    y_min, y_max = rng[1]

    # Pre-calculate scales
    # x_scale = w / (x_max - x_min)
    # y_scale = h / (y_max - y_min)
    # Avoid division by zero if range is 0 (unlikely here but safe coding)
    if x_max <= x_min or y_max <= y_min:
         return heatmap

    x_scale = w / (x_max - x_min)
    y_scale = h / (y_max - y_min)

    # Filter data within range
    # In Oscilloscope, t is always within [0, window_duration] so we can skip checking t range
    # if we are confident. But let's be safe for general equivalence.

    # We can combine the checks.
    mask = (y >= y_min) & (y <= y_max)
    # Assuming t is within range as per logic

    y_valid = y[mask]
    t_valid = t[mask]

    if len(y_valid) == 0:
        return heatmap

    # Calculate indices
    x_idx = ((t_valid - x_min) * x_scale).astype(np.int32)
    y_idx = ((y_valid - y_min) * y_scale).astype(np.int32)

    # Handle edge case: value exactly at max maps to index N, should be N-1
    # This is much faster than clip for all values
    x_idx[x_idx == w] = w - 1
    y_idx[y_idx == h] = h - 1

    # Safety clip to ensure no OOB due to precision
    # Since we filtered y, y_idx should be >= 0. y_idx could be h if y=y_max.
    # We handled y_idx=h.
    # What if y slightly < y_min but float comparison passed?
    # y >= y_min ensures y_idx >= 0.

    # However, let's just clamp to be safe against segfaults/errors in add.at
    np.clip(x_idx, 0, w - 1, out=x_idx)
    np.clip(y_idx, 0, h - 1, out=y_idx)

    np.add.at(heatmap, (x_idx, y_idx), intensity * 100)
    return heatmap

def verify_equivalence():
    sample_rate = 48000
    window_duration = 0.05
    num_samples = int(window_duration * sample_rate)

    t = np.linspace(0, window_duration, num_samples)
    y = 0.8 * np.sin(2 * np.pi * 440 * t)
    # Add some out of bounds values
    y[10] = 1.5
    y[11] = -1.5
    y[12] = 1.1 # Exactly on edge

    w, h = 60, 40 # Smaller for manual inspection if needed
    bins = [w, h]
    rng = [[0, window_duration], [-1.1, 1.1]]
    intensity = 0.5

    hm1 = np.zeros((w, h))
    hm2 = np.zeros((w, h))

    benchmark_histogram_original(t, y, bins, rng, intensity, hm1)
    benchmark_histogram_optimized(t, y, bins, rng, intensity, hm2)

    # Check if they are close
    if not np.allclose(hm1, hm2):
        diff = np.abs(hm1 - hm2)
        print(f"Max difference: {np.max(diff)}")
        print(f"Indices of difference: {np.where(diff > 0)}")
        return False
    return True

if __name__ == "__main__":
    if not verify_equivalence():
        print("Verification FAILED!")
        exit(1)
    else:
        print("Verification PASSED!")

    # Setup parameters similar to Oscilloscope
    sample_rate = 48000
    window_duration = 0.05 # 50ms
    num_samples = int(window_duration * sample_rate)

    t = np.linspace(0, window_duration, num_samples)
    y = 0.8 * np.sin(2 * np.pi * 440 * t) + 0.1 * np.random.normal(size=num_samples)

    w, h = 600, 400
    bins = [w, h]
    rng = [[0, window_duration], [-1.1, 1.1]]
    intensity = 0.5

    iterations = 100

    heatmap = np.zeros((w, h))
    start_time = time.time()
    for _ in range(iterations):
        heatmap.fill(0)
        benchmark_histogram_original(t, y, bins, rng, intensity, heatmap)
    end_time = time.time()
    t_orig = (end_time - start_time) / iterations * 1000
    print(f"Original implementation: {t_orig:.4f} ms per iteration")

    heatmap = np.zeros((w, h))
    start_time = time.time()
    for _ in range(iterations):
        heatmap.fill(0)
        benchmark_histogram_optimized(t, y, bins, rng, intensity, heatmap)
    end_time = time.time()
    t_opt = (end_time - start_time) / iterations * 1000
    print(f"Optimized implementation: {t_opt:.4f} ms per iteration")

    print(f"Speedup: {t_orig / t_opt:.2f}x")
