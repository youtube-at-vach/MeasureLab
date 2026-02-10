import sys
import time
import unittest.mock
import numpy as np

# Mock dependencies before import
sys.modules['sounddevice'] = unittest.mock.Mock()
sys.modules['PyQt6'] = unittest.mock.Mock()
sys.modules['PyQt6.QtCore'] = unittest.mock.Mock()
sys.modules['PyQt6.QtWidgets'] = unittest.mock.Mock()

# Mock tr
sys.modules['src.core.localization'] = unittest.mock.Mock()
sys.modules['src.core.localization'].tr = lambda x, default=None: x

from src.core.fft_manager import fft_manager  # noqa: E402

def perform_scan_baseline(max_out, max_in, sample_rate, duration=0.1):
    found_paths = []
    test_freq = 440
    threshold = 0.01

    t = np.linspace(0, duration, int(sample_rate * duration), False, dtype=np.float32)
    test_signal = 0.5 * np.sin(2 * np.pi * test_freq * t)

    # Pre-generate random recorded signal to simulate playrec output
    # We want consistent data for fairness, but random enough to be realistic
    # We generate one block and reuse it for every channel iteration to isolate loop overhead
    recorded_signal_mock = np.random.random((len(test_signal), max_in)).astype(np.float32)

    for out_ch in range(max_out):
        output_signal = np.zeros((len(test_signal), max_out), dtype=np.float32)
        output_signal[:, out_ch] = test_signal

        # Simulate playrec (instant)
        recorded_signal = recorded_signal_mock

        for in_ch in range(max_in):
            # Inefficient Logic: Calculate freqs and target_bin every time
            input_fft = fft_manager.rfft(recorded_signal[:, in_ch])
            freqs = fft_manager.rfftfreq(len(recorded_signal), 1 / sample_rate)

            target_bin = np.argmin(np.abs(freqs - test_freq))
            magnitude = np.abs(input_fft[target_bin]) / len(recorded_signal) * 2

            if magnitude > threshold:
                found_paths.append((out_ch + 1, in_ch + 1, magnitude))

    return found_paths

def perform_scan_optimized(max_out, max_in, sample_rate, duration=0.1):
    found_paths = []
    test_freq = 440
    threshold = 0.01

    t = np.linspace(0, duration, int(sample_rate * duration), False, dtype=np.float32)
    test_signal = 0.5 * np.sin(2 * np.pi * test_freq * t)

    # Optimization: Calculate frequencies and target bin once
    N = len(test_signal)
    freqs = fft_manager.rfftfreq(N, 1 / sample_rate)
    target_bin = np.argmin(np.abs(freqs - test_freq))

    recorded_signal_mock = np.random.random((len(test_signal), max_in)).astype(np.float32)

    for out_ch in range(max_out):
        output_signal = np.zeros((len(test_signal), max_out), dtype=np.float32)
        output_signal[:, out_ch] = test_signal

        recorded_signal = recorded_signal_mock

        for in_ch in range(max_in):
            input_fft = fft_manager.rfft(recorded_signal[:, in_ch])
            # Reuse calculated values

            magnitude = np.abs(input_fft[target_bin]) / len(recorded_signal) * 2

            if magnitude > threshold:
                found_paths.append((out_ch + 1, in_ch + 1, magnitude))

    return found_paths

if __name__ == "__main__":
    MAX_OUT = 32
    MAX_IN = 32
    SAMPLE_RATE = 48000
    DURATION = 0.1
    ITERATIONS = 5

    print(f"Benchmarking LoopbackFinder optimization with {MAX_OUT}x{MAX_IN} channels...")
    print(f"Sample Rate: {SAMPLE_RATE}, Duration: {DURATION}s")

    # Warmup FFT
    fft_manager.rfft(np.zeros(int(SAMPLE_RATE * DURATION), dtype=np.float32))

    # Verification Step
    print("Verifying correctness...")
    np.random.seed(42)
    res_base = perform_scan_baseline(4, 4, SAMPLE_RATE, DURATION)
    np.random.seed(42)
    res_opt = perform_scan_optimized(4, 4, SAMPLE_RATE, DURATION)

    # Check lengths
    if len(res_base) != len(res_opt):
        print(f"FAILED: Result lengths differ! Base: {len(res_base)}, Opt: {len(res_opt)}")
        sys.exit(1)

    # Check content (approximate due to potential float diffs, though logic should be identical)
    for i in range(len(res_base)):
        out_b, in_b, mag_b = res_base[i]
        out_o, in_o, mag_o = res_opt[i]
        if out_b != out_o or in_b != in_o or not np.isclose(mag_b, mag_o):
             print(f"FAILED: Result mismatch at index {i}!")
             print(f"Base: {res_base[i]}")
             print(f"Opt:  {res_opt[i]}")
             sys.exit(1)

    print("Verification PASSED.")

    # Measure Baseline
    start_time = time.time()
    for _ in range(ITERATIONS):
        perform_scan_baseline(MAX_OUT, MAX_IN, SAMPLE_RATE, DURATION)
    end_time = time.time()
    baseline_time = (end_time - start_time) / ITERATIONS
    print(f"Baseline average time: {baseline_time:.4f}s")

    # Measure Optimized
    start_time = time.time()
    for _ in range(ITERATIONS):
        perform_scan_optimized(MAX_OUT, MAX_IN, SAMPLE_RATE, DURATION)
    end_time = time.time()
    optimized_time = (end_time - start_time) / ITERATIONS
    print(f"Optimized average time: {optimized_time:.4f}s")

    if baseline_time > 0:
        improvement = (baseline_time - optimized_time) / baseline_time * 100
        print(f"Improvement: {improvement:.2f}%")
