import time
import itertools
from collections import deque

def benchmark():
    # Setup
    cal_samples = deque()
    # Fill with dummy data
    for i in range(256):
        cal_samples.append((float(i), i, float(i), float(i)))

    need = 30
    iterations = 100000

    # Baseline: list conversion then slicing
    start_time = time.perf_counter()
    for _ in range(iterations):
        samples = list(cal_samples)
        if len(samples) >= need:
             samples[-need:]
    end_time = time.perf_counter()
    baseline_duration = end_time - start_time
    print(f"Baseline (full copy + slice): {baseline_duration:.6f} seconds")

    # Optimization 1: islice from start (skipping N-need)
    start_time = time.perf_counter()
    for _ in range(iterations):
        length = len(cal_samples)
        if length >= need:
            start_index = length - need
            list(itertools.islice(cal_samples, start_index, length))
    end_time = time.perf_counter()
    opt1_duration = end_time - start_time
    print(f"Optimization 1 (islice forward): {opt1_duration:.6f} seconds")

    # Optimization 4: reversed + islice + reverse list
    start_time = time.perf_counter()
    for _ in range(iterations):
        if len(cal_samples) >= need:
            # reversed(cal_samples) gives iterator from end.
            # islice takes first 'need' items (which are last 'need' items in reverse)
            rev_subset = list(itertools.islice(reversed(cal_samples), need))
            # Reverse back
            rev_subset[::-1]
    end_time = time.perf_counter()
    opt4_duration = end_time - start_time
    print(f"Optimization 4 (reversed+islice): {opt4_duration:.6f} seconds")

    print(f"Speedup vs Baseline (Opt 4): {baseline_duration / opt4_duration:.2f}x")

if __name__ == "__main__":
    benchmark()
