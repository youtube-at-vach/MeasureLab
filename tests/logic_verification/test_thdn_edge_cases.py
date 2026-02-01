
import numpy as np
from src.core.analysis import AudioCalc

def test_thdn_sine_fit_small_n():
    """
    Test that calculate_thdn_sine_fit handles small N (< 8) without returning NaN.
    When N < 8, trim = N//8 = 0.
    The code currently executes residual[0:-0] which is empty, resulting in NaN.
    """
    sr = 48000
    # Create a simple sine wave
    t = np.linspace(0, 1, sr, endpoint=False)
    signal = np.sin(2 * np.pi * 1000 * t)

    # Test with N=7
    small_signal = signal[:7]
    thdn_db, fund_rms, noise_rms = AudioCalc.calculate_thdn_sine_fit(small_signal, sr, 1000)

    print(f"N=7 -> THD+N: {thdn_db}, Fund: {fund_rms}, Noise: {noise_rms}")

    assert not np.isnan(thdn_db), "THD+N should not be NaN for N=7"
    assert not np.isnan(fund_rms), "Fund RMS should not be NaN for N=7"
    assert not np.isnan(noise_rms), "Noise RMS should not be NaN for N=7"

if __name__ == "__main__":
    test_thdn_sine_fit_small_n()
