import numpy as np
import sys
import os

# Adjust path to import src
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../')))

from src.core.analysis import AudioCalc

def test_log_integration_bug():
    # 1. Setup
    # Create a Logarithmic Frequency Axis from 20Hz to 20kHz
    f_start = 20.0
    f_end = 20000.0
    n_bins = 1000
    freqs = np.geomspace(f_start, f_end, n_bins)

    # constant PSD of 1.0 V^2/Hz (for simplicity)
    # Magnitude (V/rtHz) = 1.0
    mag = np.ones_like(freqs)

    # 2. Expected Result (Analytical Integration)
    # Power = Integral(PSD * df)
    # Since PSD = 1.0, Power = f_end - f_start
    expected_power = f_end - f_start
    expected_rms = np.sqrt(expected_power)

    print(f"Expected Power: {expected_power:.4f}")
    print(f"Expected RMS: {expected_rms:.4f}")

    # 3. Actual Result using AudioCalc
    # sampling_rate is just needed for some internal checks, set arbitrarily high
    sampling_rate = 48000

    results = AudioCalc.calculate_noise_profile(mag, freqs, sampling_rate)

    # Check noise_rms_20k (which integrates from 20 to 20k)
    # Note: calculate_noise_profile integrates 20Hz-20kHz.
    # Our axis is exactly 20Hz-20kHz.
    actual_rms = results["noise_rms_20k"]
    actual_power = actual_rms ** 2

    print(f"Actual Power: {actual_power:.4f}")
    print(f"Actual RMS: {actual_rms:.4f}")

    # 4. Analysis
    # In the bug scenario, bin_width is taken as freqs[1] - freqs[0]
    bin_0_width = freqs[1] - freqs[0]
    # Sum of (1.0 * bin_0_width) for n_bins
    bug_power_estimate = n_bins * bin_0_width

    print(f"Bug Estimate (n_bins * bin_0): {bug_power_estimate:.4f}")

    ratio = actual_power / expected_power
    print(f"Ratio (Actual/Expected): {ratio:.6f}")

    assert abs(ratio - 1.0) <= 0.1, "FAIL: Integration is significantly incorrect."
    print("PASS: Integration is correct.")

if __name__ == "__main__":
    test_log_integration_bug()
