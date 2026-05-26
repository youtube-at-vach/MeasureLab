import sys

sys.path.append("/Users/vach/MeasureLab")
import numpy as np
import scipy.signal


def _prewarp(f, fs):
    # Clamp f to a safe fraction of Nyquist frequency to avoid tangent divergence and negative poles
    safe_f = min(f, 0.95 * (fs / 2.0))
    return (fs / np.pi) * np.tan(np.pi * safe_f / fs)


def design_a_weighting_safe(sampling_rate):
    fs = float(sampling_rate)
    if fs <= 0:
        raise ValueError("Invalid sample rate")

    f1 = _prewarp(20.598997, fs)
    f2 = _prewarp(107.65265, fs)
    f3 = _prewarp(737.86223, fs)
    f4 = _prewarp(12194.217, fs)

    pi = np.pi
    z = [0, 0, 0, 0]
    p = [
        -2 * pi * f1,
        -2 * pi * f1,
        -2 * pi * f2,
        -2 * pi * f3,
        -2 * pi * f4,
        -2 * pi * f4,
    ]
    k = 1.0

    zd, pd, kd = scipy.signal.bilinear_zpk(z, p, k, fs)
    sos = scipy.signal.zpk2sos(zd, pd, kd)

    w, h = scipy.signal.sosfreqz(sos, worN=[1000], fs=fs)
    gain_1k = np.abs(h[0])
    if gain_1k > 1e-12:
        sos[0, :3] /= gain_1k

    return sos


def design_c_weighting_safe(sampling_rate):
    fs = float(sampling_rate)
    if fs <= 0:
        raise ValueError("Invalid sample rate")

    f1 = _prewarp(20.598997, fs)
    f4 = _prewarp(12194.217, fs)

    pi = np.pi
    z = [0, 0]
    p = [-2 * pi * f1, -2 * pi * f1, -2 * pi * f4, -2 * pi * f4]
    k = 1.0

    zd, pd, kd = scipy.signal.bilinear_zpk(z, p, k, fs)
    sos = scipy.signal.zpk2sos(zd, pd, kd)

    w, h = scipy.signal.sosfreqz(sos, worN=[1000], fs=fs)
    gain_1k = np.abs(h[0])
    if gain_1k > 1e-12:
        sos[0, :3] /= gain_1k

    return sos


def check_stability_safe(fs):
    print(f"\n--- Checking Clamped Sample Rate: {fs} Hz ---")
    try:
        sos_a = design_a_weighting_safe(fs)
        poles_a = []
        for section in sos_a:
            a = section[3:]
            p = np.roots(a)
            poles_a.extend(p)

        max_pole_a = max(abs(p) for p in poles_a)
        stable_a = all(abs(p) < 1.0 for p in poles_a)
        print(f"A-weighting: Max pole magnitude = {max_pole_a:.6f}, Stable = {stable_a}")
        if not stable_a:
            print("  WARNING: A-weighting is UNSTABLE!")

    except Exception as e:
        print(f"A-weighting design failed: {e}")

    try:
        sos_c = design_c_weighting_safe(fs)
        poles_c = []
        for section in sos_c:
            a = section[3:]
            p = np.roots(a)
            poles_c.extend(p)
        max_pole_c = max(abs(p) for p in poles_c)
        stable_c = all(abs(p) < 1.0 for p in poles_c)
        print(f"C-weighting: Max pole magnitude = {max_pole_c:.6f}, Stable = {stable_c}")
        if not stable_c:
            print("  WARNING: C-weighting is UNSTABLE!")
    except Exception as e:
        print(f"C-weighting design failed: {e}")


for fs in [48000, 44100, 32000, 24000, 22050, 16000, 11025, 8000]:
    check_stability_safe(fs)
