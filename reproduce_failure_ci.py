import numpy as np

def check(n_bins):
    start_freq = 20.0
    stop_freq = 20000.0
    freqs = np.geomspace(start_freq, stop_freq, n_bins)

    # Logic from analysis.py
    is_log_freqs = False

    if len(freqs) > 1:
        start_freq_val = freqs[0]
        # Assume linear step from first two bins
        freq_step = freqs[1] - start_freq_val
        expected_end = start_freq_val + freq_step * (len(freqs) - 1)

        # Check approximate linearity
        if abs(freqs[-1] - expected_end) < 1e-5:
            is_linear_freqs = True
            print(f"N={n_bins}: Linear detected (Unexpected)")
        elif start_freq_val > 1e-9:
            # Check for logarithmic spacing (geometric progression)
            ratio = freqs[1] / start_freq_val
            # expected_end = start * ratio^(n-1)
            expected_log_end = start_freq_val * (ratio ** (len(freqs) - 1))

            diff = abs(freqs[-1] - expected_log_end)
            threshold = 1e-4 * expected_log_end

            if diff < threshold:
                is_log_freqs = True
                print(f"N={n_bins}: Log detected (Expected)")
            else:
                 print(f"N={n_bins}: Log FAILED. Diff={diff}, Threshold={threshold}, Rel={diff/expected_log_end}")

check(1000)
check(512)
check(1024)
check(2048)
check(16384)
