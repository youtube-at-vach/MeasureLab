
import numpy as np
import math

def test_index_logic():
    # Simulate freqs array
    N = 16384
    sr = 48000
    freqs = np.fft.rfftfreq(N, 1/sr)
    bin_width = freqs[1]

    print(f"Bin width: {bin_width}")

    # Test cases around bin boundaries
    test_freqs = [
        1000.0, 
        1000.0 + bin_width * 0.1,
        1000.0 + bin_width * 0.5,
        1000.0 + bin_width * 0.9,
        1000.0 + bin_width * 0.999999,
        1000.0 + bin_width * 1.0,
        1000.0 + bin_width * 1.000001
    ]

    errors = 0

    for f in test_freqs:
        # Original logic
        idx_search = np.searchsorted(freqs, f)

        # New logic
        # "search_window" isn't involved here, we are just finding the index of 'f'
        # The code was: ceil((freq - window) / bin_width)
        # Effectively finding index >= val.

        idx_calc = int(math.ceil(f / bin_width))
        idx_calc_min = max(0, min(len(freqs), idx_calc))

        if idx_search != idx_calc:
            print(f"Mismatch at {f}: Search={idx_search}, Calc={idx_calc}")
            errors += 1

    print(f"Total mismatches: {errors}")

if __name__ == "__main__":
    test_index_logic()
