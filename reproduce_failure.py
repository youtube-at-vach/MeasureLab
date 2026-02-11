import numpy as np
import math

start_freq = 20.0
stop_freq = 20000.0
n_bins = 1000
freqs = np.geomspace(start_freq, stop_freq, n_bins)

ratio = freqs[1] / start_freq
expected_log_end = start_freq * (ratio ** (len(freqs) - 1))
diff = abs(freqs[-1] - expected_log_end)
rel_diff = diff / expected_log_end
is_log = diff < 1e-4 * expected_log_end

print(f"Start: {start_freq}")
print(f"End: {freqs[-1]}")
print(f"Ratio: {ratio}")
print(f"Expected Log End: {expected_log_end}")
print(f"Diff: {diff}")
print(f"Rel Diff: {rel_diff}")
print(f"Threshold (1e-4): {1e-4}")
print(f"Is Log: {is_log}")
