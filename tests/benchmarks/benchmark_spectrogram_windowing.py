
import time
import numpy as np
from src.core.analysis import get_cached_window
from src.core.fft_manager import fft_manager

# Configuration
FFT_SIZE = 4096
ITERATIONS = 1000

def setup_data():
    raw_data = np.random.random((FFT_SIZE, 2)).astype(np.float64)
    window = get_cached_window("hann", FFT_SIZE)
    return raw_data, window

def run_current_implementation(raw_data, window, channel_mode):
    # Old logic
    if channel_mode == "Left":
        sig = raw_data[:, 0]
    elif channel_mode == "Right":
        sig = raw_data[:, 1]
    else:
        sig = np.mean(raw_data, axis=1)

    # Windowing
    sig_win = sig * window

    # Correction
    win_correction = 1.0 / np.mean(window)

    # FFT
    fft_res = fft_manager.rfft(sig_win)
    mag = np.abs(fft_res)

    # Normalize
    mag *= (2.0 * win_correction) / len(sig)

    # dB
    with np.errstate(divide="ignore"):
        np.add(mag, 1e-12, out=mag)
        np.log10(mag, out=mag)
        np.multiply(mag, 20, out=mag)
        mag_db = mag

    return mag_db

def run_optimized_implementation(raw_data, window, channel_mode, work_buffer, fft_out_buffer, mag_buffer):
    # Logic in SpectrogramWidget.update_spectrogram

    # Ensure work buffer size matches
    if len(work_buffer) != len(raw_data):
        work_buffer = np.zeros(len(raw_data), dtype=np.float64)
        fft_out_buffer = np.zeros(len(raw_data) // 2 + 1, dtype=np.complex128)
        mag_buffer = np.zeros(len(raw_data) // 2 + 1, dtype=np.float64)

    if channel_mode == "Left":
        work_buffer[:] = raw_data[:, 0]
    elif channel_mode == "Right":
        work_buffer[:] = raw_data[:, 1]
    else:
        np.add(raw_data[:, 0], raw_data[:, 1], out=work_buffer)
        work_buffer *= 0.5

    # Windowing
    # Note: Benchmark reuses window, safe as it's read-only
    work_buffer *= window

    win_correction = 1.0 / np.mean(window)

    # FFT
    fft_manager.rfft(work_buffer, out=fft_out_buffer)

    # Magnitude
    np.abs(fft_out_buffer, out=mag_buffer)

    # Normalize
    mag_buffer *= (2.0 * win_correction) / len(work_buffer)

    # dB
    with np.errstate(divide="ignore"):
        np.add(mag_buffer, 1e-12, out=mag_buffer)
        np.log10(mag_buffer, out=mag_buffer)
        np.multiply(mag_buffer, 20, out=mag_buffer)

    return mag_buffer

def benchmark_scenario(mode, name):
    raw_data, window = setup_data()

    # Warmup
    work_buffer = np.zeros(FFT_SIZE, dtype=np.float64)
    fft_out_buffer = np.zeros(FFT_SIZE // 2 + 1, dtype=np.complex128)
    mag_buffer = np.zeros(FFT_SIZE // 2 + 1, dtype=np.float64)

    # Measure Current
    start_time = time.perf_counter()
    for _ in range(ITERATIONS):
        run_current_implementation(raw_data, window, mode)
    current_time = time.perf_counter() - start_time

    # Measure Optimized
    start_time = time.perf_counter()
    for _ in range(ITERATIONS):
        run_optimized_implementation(raw_data, window, mode, work_buffer, fft_out_buffer, mag_buffer)
    optimized_time = time.perf_counter() - start_time

    print(f"\nScenario: {name}")
    print(f"Current Time:   {current_time:.6f}s")
    print(f"Optimized Time: {optimized_time:.6f}s")
    print(f"Improvement:    {(current_time - optimized_time) / current_time * 100:.2f}%")

if __name__ == "__main__":
    print(f"Benchmarking Spectrogram Full Pipeline (Size={FFT_SIZE}, Iterations={ITERATIONS})")
    benchmark_scenario("Left", "Left Channel (View)")
    benchmark_scenario("Average", "Average Channel (Calc)")
