import time
import numpy as np
from scipy.signal import get_window

from src.core.analysis import AudioCalc
from src.core.fft_manager import fft_manager

def benchmark_distortion_analysis():
    # Setup
    sample_rate = 48000
    buffer_size = 16384
    freq = 1000.0

    # Generate Sine Wave with some harmonics and noise
    t = np.arange(buffer_size) / sample_rate
    signal = 0.5 * np.sin(2 * np.pi * freq * t) # Fundamental
    signal += 0.00005 * np.sin(2 * np.pi * 2 * freq * t) # 2nd Harmonic (-80dB)
    signal += 0.00002 * np.sin(2 * np.pi * 3 * freq * t) # 3rd Harmonic (-88dB)
    signal += np.random.normal(0, 1e-6, buffer_size) # Noise floor

    window_type = "blackmanharris"

    # Measure THD+N Analysis (Harmonics)
    start_time = time.perf_counter()
    results = AudioCalc.analyze_harmonics(signal, freq, window_type, sample_rate)
    end_time = time.perf_counter()

    thd_duration = (end_time - start_time) * 1000
    print(f"\nTHD+N Analysis Duration: {thd_duration:.2f} ms")
    print(f"THD: {results['thd_percent']:.4f}%")

    # Generate SMPTE Signal
    f1 = 60.0
    f2 = 7000.0
    amp_f2 = 0.5 / 5.0
    amp_f1 = amp_f2 * 4.0

    smpte_signal = amp_f1 * np.sin(2 * np.pi * f1 * t) + amp_f2 * np.sin(2 * np.pi * f2 * t)

    # FFT for IMD
    window = get_window(window_type, buffer_size)
    fft_data = fft_manager.rfft(smpte_signal * window)
    mag_linear = np.abs(fft_data) * (2 / np.sum(window))
    freqs = fft_manager.rfftfreq(buffer_size, 1 / sample_rate)

    # Measure IMD Analysis
    start_time = time.perf_counter()
    imd_res = AudioCalc.calculate_imd_smpte(mag_linear, freqs, f1, f2)
    end_time = time.perf_counter()

    imd_duration = (end_time - start_time) * 1000
    print(f"IMD SMPTE Analysis Duration: {imd_duration:.2f} ms")
    print(f"IMD: {imd_res['imd']:.4f}%")

    return thd_duration, imd_duration

if __name__ == "__main__":
    benchmark_distortion_analysis()
