import sys

sys.path.append("/Users/vach/MeasureLab")
import numpy as np
from src.core.analysis import AudioCalc


def check_stability(fs):
    print(f"\n--- Checking Sample Rate: {fs} Hz ---")
    try:
        sos_a = AudioCalc.design_a_weighting(fs)
        # Check poles of SOS A-weighting
        poles_a = []
        for section in sos_a:
            # SOS format: [b0, b1, b2, a0, a1, a2]
            a = section[3:]
            # Roots of z^2 + a1*z + a2 = 0
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
        sos_c = AudioCalc.design_c_weighting(fs)
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


# Check standard and low sample rates
for fs in [48000, 44100, 32000, 24000, 22050, 16000, 11025, 8000]:
    check_stability(fs)
