import time
import numpy as np
import sys
import os

# Adjust path to find src
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from src.core.analysis import AudioCalc, get_cached_window
from src.core.fft_manager import fft_manager

def benchmark_distortion_analysis():
    sample_rate = 48000
    buffer_size = 16384
    freq = 1000.0
    amplitude = 0.5

    # Generate test signal (Sine wave + some noise + harmonics)
    t = np.arange(buffer_size) / sample_rate
    signal = amplitude * np.sin(2 * np.pi * freq * t)
    # Add 2nd harmonic
    signal += (amplitude * 0.01) * np.sin(2 * np.pi * (freq * 2) * t)
    # Add noise
    rng = np.random.default_rng(42)
    signal += rng.normal(0, 0.0001, buffer_size)

    window_type = "blackmanharris"

    # Warm up
    print("Warming up...")
    AudioCalc.analyze_harmonics(signal, freq, window_type, sample_rate)

    iterations = 20
    start_time = time.perf_counter()

    for _ in range(iterations):
        AudioCalc.analyze_harmonics(signal, freq, window_type, sample_rate)

    end_time = time.perf_counter()
    avg_time = (end_time - start_time) / iterations

    print(f"Average execution time for analyze_harmonics: {avg_time*1000:.2f} ms")

    # Benchmark IMD SMPTE
    # Signal for IMD
    f1 = 60.0
    f2 = 7000.0
    ratio = 4.0
    amp_f2 = amplitude / (ratio + 1)
    amp_f1 = amp_f2 * ratio
    signal_imd = amp_f1 * np.sin(2 * np.pi * f1 * t) + amp_f2 * np.sin(2 * np.pi * f2 * t)

    # Warm up IMD path (FFT part is shared but logic differs)
    window = get_cached_window(window_type, buffer_size)
    fft_data = fft_manager.rfft(signal_imd * window)
    mag_linear = np.abs(fft_data) * (2 / np.sum(window))
    freqs = fft_manager.rfftfreq(buffer_size, 1 / sample_rate)

    start_time = time.perf_counter()
    for _ in range(iterations):
        # In update_realtime_analysis, FFT is done before calling calc function
        # But we want to benchmark the whole block that is blocking the GUI

        # Simulate what update_realtime_analysis does for IMD
        w = get_cached_window(window_type, len(signal_imd))
        f_data = fft_manager.rfft(signal_imd * w)
        m_linear = np.abs(f_data) * (2 / np.sum(w))
        fs = fft_manager.rfftfreq(len(signal_imd), 1 / sample_rate)

        AudioCalc.calculate_imd_smpte(m_linear, fs, f1, f2)

    end_time = time.perf_counter()
    avg_time_imd = (end_time - start_time) / iterations
    print(f"Average execution time for IMD (including FFT): {avg_time_imd*1000:.2f} ms")

if __name__ == "__main__":
    benchmark_distortion_analysis()
