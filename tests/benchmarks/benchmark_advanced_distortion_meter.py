import time
import numpy as np
from src.core.analysis import AudioCalc
from src.core.fft_manager import fft_manager


def benchmark_analysis():
    # Setup parameters matching AdvancedDistortionMeter
    buffer_size = 65536
    sr = 48000

    # Generate synthetic data (Multitone)
    mim_tone_count = 31
    mim_min_freq = 20.0
    mim_max_freq = 20000.0

    bin_width = sr / buffer_size
    raw_freqs = np.logspace(np.log10(mim_min_freq), np.log10(mim_max_freq), mim_tone_count)
    mim_freqs = np.round(raw_freqs / bin_width) * bin_width

    # Create a signal with these tones + some noise
    t = np.arange(buffer_size) / sr
    signal = np.random.normal(0, 0.0001, buffer_size)  # Noise floor

    for f in mim_freqs:
        signal += 0.05 * np.sin(2 * np.pi * f * t)  # Tones

    # Benchmark Loop
    iterations = 50
    start_time = time.time()

    for _ in range(iterations):
        # 1. FFT
        fft_res = fft_manager.rfft(signal)
        freqs = fft_manager.rfftfreq(len(signal), 1 / sr)

        # 2. Magnitude Calculation
        mag = np.abs(fft_res) * 2 / len(signal)
        # mag_db = 20 * np.log10(mag + 1e-12) # GUI does this for plotting, let's include it

        # 3. Metrics (MIM mode is heaviest usually due to many tones)
        _ = AudioCalc.calculate_multitone_tdn(mag, freqs, mim_freqs)

    end_time = time.time()
    avg_time = (end_time - start_time) / iterations
    print(f"Average analysis time (MIM): {avg_time * 1000:.2f} ms")

    # Benchmark PIM
    # PIM involves calculating products
    pim_f1 = 1800.0
    pim_f2 = 2100.0

    start_time = time.time()
    for _ in range(iterations):
        # FFT (assume new data)
        fft_res = fft_manager.rfft(signal)
        freqs = fft_manager.rfftfreq(len(signal), 1 / sr)
        mag = np.abs(fft_res) * 2 / len(signal)

        _ = AudioCalc.calculate_pim(mag, freqs, pim_f1, pim_f2)

    end_time = time.time()
    avg_time = (end_time - start_time) / iterations
    print(f"Average analysis time (PIM): {avg_time * 1000:.2f} ms")


if __name__ == "__main__":
    benchmark_analysis()
