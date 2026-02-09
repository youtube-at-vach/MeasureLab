import numpy as np
from src.core.analysis import AudioCalc

def test_imd_smpte_check():
    """Verify SMPTE IMD Calculation logic."""
    sr = 48000
    duration = 1.0
    t = np.arange(int(sr * duration)) / sr

    f1 = 60
    f2 = 7000
    ratio = 4.0

    # Amplitudes
    amp_f2 = 0.5 / (ratio + 1)
    amp_f1 = amp_f2 * ratio

    # Generate Clean Signal
    sig = amp_f1 * np.sin(2*np.pi*f1*t) + amp_f2 * np.sin(2*np.pi*f2*t)

    # Add IMD products (sidebands)
    # f2 +/- f1
    # 1% IMD relative to modulation carrier (f2)
    imd_amp = amp_f2 * 0.01
    sig += imd_amp * np.sin(2*np.pi*(f2-f1)*t)
    sig += imd_amp * np.sin(2*np.pi*(f2+f1)*t)

    # FFT
    window = np.blackman(len(sig))
    fft_data = np.fft.rfft(sig * window)
    mag = np.abs(fft_data) * (2 / np.sum(window))
    freqs = np.fft.rfftfreq(len(sig), 1/sr)

    res = AudioCalc.calculate_imd_smpte(mag, freqs, f1, f2)

    # Assertions
    # Two sidebands of 1% amplitude each.
    # SMPTE IMD is typically calculating the RMS of the sidebands relative to the carrier.
    # sqrt(0.01^2 + 0.01^2) = 0.014142... = 1.4142%
    assert abs(res['imd'] - 1.4142) < 0.1, f"SMPTE IMD Result {res['imd']:.4f}% deviates from expected 1.414%"

def test_imd_ccif_check():
    """Verify CCIF IMD Calculation logic."""
    sr = 48000
    duration = 1.0
    t = np.arange(int(sr * duration)) / sr

    f1 = 19000
    f2 = 20000

    # Amplitudes (1:1)
    amp = 0.25

    # Generate Clean Signal
    sig = amp * np.sin(2*np.pi*f1*t) + amp * np.sin(2*np.pi*f2*t)

    # Add IMD product (d2 = f2-f1 = 1kHz)
    # 1% of total amplitude
    imd_amp = (amp + amp) * 0.01
    sig += imd_amp * np.sin(2*np.pi*(f2-f1)*t)

    # FFT
    window = np.blackman(len(sig))
    fft_data = np.fft.rfft(sig * window)
    mag = np.abs(fft_data) * (2 / np.sum(window))
    freqs = np.fft.rfftfreq(len(sig), 1/sr)

    res = AudioCalc.calculate_imd_ccif(mag, freqs, f1, f2)

    # Assertions
    # Expected ~1.0%
    assert abs(res['imd'] - 1.0) < 0.1, f"CCIF IMD Result {res['imd']:.4f}% deviates from expected 1.0%"
