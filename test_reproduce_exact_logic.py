import numpy as np
from src.core.analysis import AudioCalc

# Exact copy of the failing test logic
class TestExact:
    def test_log(self):
        freqs = np.geomspace(20.0, 20000.0, 1000)

        # Replicate analysis.py internal logic manually to see variables
        start_freq = freqs[0]
        stop_freq = freqs[-1]

        # Check if freqs is linear or logarithmic
        is_linear_freqs = False
        is_log_freqs = False

        if len(freqs) > 1:
            start_freq = freqs[0]
            # Assume linear step from first two bins
            freq_step = freqs[1] - start_freq
            expected_end = start_freq + freq_step * (len(freqs) - 1)

            # Check approximate linearity
            # Use absolute tolerance suitable for frequency precision
            if abs(freqs[-1] - expected_end) < 1e-5:
                is_linear_freqs = True
                print("Linear detected")
            elif start_freq > 1e-9:
                # Check for logarithmic spacing (geometric progression)
                # ratio = f[1] / f[0]
                ratio = freqs[1] / start_freq
                # expected_end = start * ratio^(n-1)
                # Use log space calculation to avoid overflow/precision issues with huge exponents?
                # For audio range (20Hz-20kHz), direct power is fine.
                expected_log_end = start_freq * (ratio ** (len(freqs) - 1))

                diff = abs(freqs[-1] - expected_log_end)
                threshold = 1e-4 * expected_log_end

                print(f"Start: {start_freq}")
                print(f"End: {freqs[-1]}")
                print(f"Ratio: {ratio}")
                print(f"Expected Log End: {expected_log_end}")
                print(f"Diff: {diff}")
                print(f"Threshold: {threshold}")

                if diff < threshold:
                    is_log_freqs = True
                    print("Log detected")
                    stop_freq = freqs[-1]
                else:
                    print("Log NOT detected")

        return is_log_freqs

t = TestExact()
res = t.test_log()
print(f"Result: {res}")
