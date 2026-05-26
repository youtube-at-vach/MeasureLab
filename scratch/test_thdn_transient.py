import sys

sys.path.append("/Users/vach/MeasureLab")
import numpy as np
from src.core.analysis import AudioCalc


def check_thdn_with_length(N, fs=48000, freq=1000.0):
    t = np.arange(N) / fs
    # Pure sine wave, amplitude = 1.0 (no noise, no distortion)
    signal = np.sin(2 * np.pi * freq * t)

    # Calculate THD+N using sine fit
    thdn_db, fund_rms, nd_rms = AudioCalc.calculate_thdn_sine_fit(signal, fs, freq)
    print(
        f"N = {N:6d} ({N / fs * 1000:6.2f} ms): THD+N = {thdn_db:8.2f} dB, Fund RMS = {fund_rms:.6f}, Noise RMS = {nd_rms:.6e}"
    )


print("--- Testing THD+N vs Signal Length for Pure Sine Wave (No Noise/Distortion) ---")
for N in [48000, 24000, 12000, 4096, 2048, 1024, 512]:
    check_thdn_with_length(N)
