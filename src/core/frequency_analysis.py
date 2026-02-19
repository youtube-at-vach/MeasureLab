import numpy as np
from src.core.analysis import AudioCalc
from src.core.fft_manager import fft_manager


def calculate_frequency_metrics(data, sr, gate_threshold_db, calibration_factor=1.0):
    """
    Calculates frequency metrics (frequency and amplitude).

    Args:
        data (np.ndarray): Audio data buffer.
        sr (int): Sample rate.
        gate_threshold_db (float): Minimum amplitude in dB to consider a signal.
        calibration_factor (float): Calibration factor to apply to frequency.

    Returns:
        tuple: (frequency_hz, amplitude_db)
               frequency_hz is None if below gate threshold.
    """
    # 1. Check Amplitude (Gate)
    rms = np.sqrt(np.vdot(data, data) / data.size)
    db = 20 * np.log10(rms + 1e-12)

    if db < gate_threshold_db:
        return None, db

    # 2. Coarse Estimate (FFT)
    window = np.hamming(len(data))
    fft_res = fft_manager.rfft(data * window)
    freqs = fft_manager.rfftfreq(len(data), 1 / sr)

    idx = np.argmax(np.abs(fft_res))
    coarse_freq = freqs[idx]

    # 3. Fine Estimate (Parabolic)
    # (Already implemented in AudioCalc.analyze_harmonics, but let's do a quick one here or skip to optimization)
    # Optimization is robust enough if coarse is close.

    # 4. Precision Estimate (Sine Fit)
    # Only run if we have a reasonable signal
    if coarse_freq > 10:  # Avoid DC/VLF noise
        try:
            precise_freq = AudioCalc.optimize_frequency(data, sr, coarse_freq)
            precise_freq = float(precise_freq) * calibration_factor
            return precise_freq, db
        except Exception:
            return coarse_freq, db
    else:
        return coarse_freq, db


def calculate_allan_deviation(data, dt_seconds):
    """
    Calculates Allan Deviation for multiple Tau values.

    Args:
        data (np.ndarray): Array of frequency measurements (or period).
        dt_seconds (float): Time interval between samples (update_interval).

    Returns:
        tuple: (taus, devs) lists of Tau values (seconds) and Allan Deviations.
    """
    n = len(data)
    taus = []
    devs = []
    max_m = n // 2
    m = 1

    # Optimization: Don't calculate EVERY m if n is huge.
    while m <= max_m:
        num_samples = (n // m) * m
        if num_samples < 2 * m:
            break

        # Efficient mean calculation
        # Reshape data to (N//m, m) and take mean along axis 1
        # This gives us the sequence of averages y_k
        y = data[:num_samples].reshape(-1, m).mean(axis=1)

        if len(y) < 2:
            break

        diffs = np.diff(y)
        sigma = float(np.sqrt(0.5 * np.mean(diffs**2)))
        tau_seconds = m * dt_seconds

        taus.append(tau_seconds)
        devs.append(sigma)

        m *= 2

    return taus, devs
