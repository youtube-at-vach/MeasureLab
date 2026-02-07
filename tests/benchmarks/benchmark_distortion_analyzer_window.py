import timeit
from scipy.signal import get_window
import sys
import os

# Add repo root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from src.core.analysis import get_cached_window

def benchmark():
    window_type = 'blackmanharris' # Default in DistortionAnalyzer
    length = 16384 # Default buffer size in DistortionAnalyzer
    iterations = 5000

    print(f"Benchmarking Window Generation (N={length}, Iterations={iterations})")

    # Baseline
    t_base = timeit.timeit(lambda: get_window(window_type, length), number=iterations)
    print(f"Baseline (scipy.signal.get_window): {t_base:.4f} seconds")

    # Optimized
    t_opt = timeit.timeit(lambda: get_cached_window(window_type, length), number=iterations)
    print(f"Optimized (get_cached_window):      {t_opt:.4f} seconds")

    if t_opt > 0:
        print(f"Speedup: {t_base / t_opt:.2f}x")
    else:
        print("Speedup: Infinite (too fast to measure)")

if __name__ == "__main__":
    benchmark()
