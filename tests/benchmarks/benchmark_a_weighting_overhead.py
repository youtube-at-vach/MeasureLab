import numpy as np
import time
import sys
import os

# Adjust path to import src
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from src.core.analysis import AudioCalc


def benchmark():
    fs = 48000
    N = 65536
    freqs_full = np.fft.rfftfreq(N, d=1 / fs)

    print(f"Benchmark Config: fs={fs}, N={N}")

    # Case 1: Full array (starts at 0)
    mag = np.zeros_like(freqs_full)
    start = time.time()
    for _ in range(100):
        AudioCalc.calculate_noise_profile(mag, freqs_full, fs)
    end = time.time()
    print(f"Full array (starts at 0): {end - start:.4f}s")

    # Case 2: Sliced array (starts > 0)
    # Using slice indices to ensure perfect linearity in floating point representation if relevant
    idx_start = int(20 / (fs / N))
    idx_end = int(20000 / (fs / N))
    freqs_sliced = freqs_full[idx_start:idx_end]
    mag_sliced = np.zeros_like(freqs_sliced)

    start = time.time()
    for _ in range(100):
        AudioCalc.calculate_noise_profile(mag_sliced, freqs_sliced, fs)
    end = time.time()
    print(f"Sliced array (starts > 0): {end - start:.4f}s")

    # Case 3: Log spaced (Logarithmic)
    start_freq = max(1.0, freqs_sliced[0])
    stop_freq = freqs_sliced[-1]
    n_log = len(freqs_sliced)
    freqs_log = np.geomspace(start_freq, stop_freq, n_log)
    mag_log = np.zeros_like(freqs_log)

    start = time.time()
    for _ in range(100):
        AudioCalc.calculate_noise_profile(mag_log, freqs_log, fs)
    end = time.time()
    print(f"Log spaced (Logarithmic): {end - start:.4f}s")

    # Case 4: Arbitrary (Random)
    # Ensure sorted so integration logic doesn't break horribly (though noise profile assumes sorted for some ops?)
    # Most ops use searchsorted which assumes sorted.
    freqs_rand = np.sort(np.random.uniform(20, 20000, n_log))
    mag_rand = np.zeros_like(freqs_rand)

    start = time.time()
    for _ in range(100):
        AudioCalc.calculate_noise_profile(mag_rand, freqs_rand, fs)
    end = time.time()
    print(f"Random (Arbitrary): {end - start:.4f}s")


if __name__ == "__main__":
    benchmark()
