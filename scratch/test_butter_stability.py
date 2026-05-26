import sys
import os
sys.path.append("/Users/vach/MeasureLab")
import numpy as np
import scipy.signal
from src.core.analysis import AudioCalc

def check_butterworth_stability(fs):
    print(f"\n--- Checking Butterworth stability at {fs} Hz ---")
    
    # 1. Bandpass filter 20Hz - 20kHz
    try:
        # Generate some random signal or impulses
        signal = np.zeros(1000)
        signal[0] = 1.0  # Impulse
        
        filtered = AudioCalc.bandpass_filter(signal, fs, lowcut=20.0, highcut=20000.0)
        max_val = np.max(np.abs(filtered))
        is_nan = np.any(np.isnan(filtered))
        is_inf = np.any(np.isinf(filtered))
        is_unstable = max_val > 10.0 or is_nan or is_inf
        
        print(f"Bandpass 20Hz-20kHz: Stable = {not is_unstable}, Max output = {max_val:.6e}, Has NaN/Inf = {is_nan or is_inf}")
        if is_unstable:
            print("  WARNING: Bandpass filter is UNSTABLE / EXPLODED!")
    except Exception as e:
        print(f"Bandpass failed: {e}")
        
    # 2. Highpass filter 20Hz
    try:
        signal = np.zeros(1000)
        signal[0] = 1.0
        filtered = AudioCalc.highpass_filter(signal, fs, cutoff=20.0)
        max_val = np.max(np.abs(filtered))
        is_nan = np.any(np.isnan(filtered))
        is_unstable = max_val > 10.0 or is_nan
        print(f"Highpass 20Hz: Stable = {not is_unstable}, Max output = {max_val:.6e}")
        if is_unstable:
            print("  WARNING: Highpass filter is UNSTABLE / EXPLODED!")
    except Exception as e:
        print(f"Highpass failed: {e}")

# Check with standard high sample rates
for fs in [44100, 48000, 96000, 192000]:
    check_butterworth_stability(fs)
