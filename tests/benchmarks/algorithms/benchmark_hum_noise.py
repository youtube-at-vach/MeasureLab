import os
import sys
import timeit

import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
from src.core.analysis import AudioCalc


# We will create a dummy environment that mimics the inputs to _calculate_hum_noise
def setup_dummy_data():
    np.random.seed(42)
    N = 48000
    sampling_rate = 48000.0
    freqs = np.fft.rfftfreq(N, 1 / sampling_rate)
    mag = np.abs(np.fft.rfft(np.random.randn(N))) / N * 2
    mag_sq = mag**2
    freq_step = freqs[1] - freqs[0]
    bin_width = freq_step
    is_linear_freqs = True
    start_freq = 0.0
    return mag_sq, freqs, sampling_rate, bin_width, is_linear_freqs, freq_step, start_freq


mag_sq, freqs, sampling_rate, bin_width, is_linear_freqs, freq_step, start_freq = setup_dummy_data()

# We need the AudioCalc import for _get_freq_index


def original_calculate_hum_noise(mag_sq, freqs, sampling_rate, bin_width, is_linear_freqs, freq_step, start_freq=0.0):
    def get_power_in_band(f_center, width=5.0):
        f_start = f_center - width
        f_end = f_center + width
        idx_start = AudioCalc._get_freq_index(freqs, f_start, is_linear_freqs, freq_step, start_freq, side="left")
        idx_end = AudioCalc._get_freq_index(freqs, f_end, is_linear_freqs, freq_step, start_freq, side="right")
        if idx_start >= idx_end:
            return 0.0
        if np.ndim(bin_width) == 0:
            power = np.sum(mag_sq[idx_start:idx_end]) * bin_width
        else:
            power = np.sum(mag_sq[idx_start:idx_end] * bin_width[idx_start:idx_end])
        return power

    p50 = get_power_in_band(50.0)
    p60 = get_power_in_band(60.0)
    base_freq = 50.0 if p50 > p60 else 60.0

    hum_power = 0.0
    hum_components = []
    for i in range(1, 11):
        f_h = base_freq * i
        if f_h > sampling_rate / 2:
            break
        p_h = get_power_in_band(f_h)
        hum_power += p_h
        hum_components.append((f_h, np.sqrt(p_h)))

    return np.sqrt(hum_power), base_freq, hum_components


def optimized_calculate_hum_noise(mag_sq, freqs, sampling_rate, bin_width, is_linear_freqs, freq_step, start_freq=0.0):
    def get_power_in_band(f_center, width=5.0):
        f_start = f_center - width
        f_end = f_center + width
        idx_start = AudioCalc._get_freq_index(freqs, f_start, is_linear_freqs, freq_step, start_freq, side="left")
        idx_end = AudioCalc._get_freq_index(freqs, f_end, is_linear_freqs, freq_step, start_freq, side="right")
        if idx_start >= idx_end:
            return 0.0
        if np.ndim(bin_width) == 0:
            power = np.sum(mag_sq[idx_start:idx_end]) * bin_width
        else:
            power = np.sum(mag_sq[idx_start:idx_end] * bin_width[idx_start:idx_end])
        return power

    p50 = get_power_in_band(50.0)
    p60 = get_power_in_band(60.0)
    base_freq = 50.0 if p50 > p60 else 60.0

    max_i = min(10, int(sampling_rate / (2 * base_freq)))
    p_h_list = [get_power_in_band(base_freq * i) for i in range(1, max_i + 1)]

    hum_power = sum(p_h_list)
    p_h_sqrt = np.sqrt(p_h_list).tolist()
    hum_components = [(base_freq * i, p) for i, p in enumerate(p_h_sqrt, start=1)]

    return np.sqrt(hum_power), base_freq, hum_components


if __name__ == "__main__":
    o_val = original_calculate_hum_noise(
        mag_sq, freqs, sampling_rate, bin_width, is_linear_freqs, freq_step, start_freq
    )
    n_val = optimized_calculate_hum_noise(
        mag_sq, freqs, sampling_rate, bin_width, is_linear_freqs, freq_step, start_freq
    )

    # Validation check
    assert np.isclose(o_val[0], n_val[0], rtol=1e-9), f"{o_val[0]} != {n_val[0]}"
    assert o_val[1] == n_val[1]
    for o_c, n_c in zip(o_val[2], n_val[2], strict=True):
        assert np.isclose(o_c[0], n_c[0], rtol=1e-9)
        assert np.isclose(o_c[1], n_c[1], rtol=1e-9)

    num = 10000
    t_orig = timeit.timeit(
        lambda: original_calculate_hum_noise(
            mag_sq, freqs, sampling_rate, bin_width, is_linear_freqs, freq_step, start_freq
        ),
        number=num,
    )
    t_opt = timeit.timeit(
        lambda: optimized_calculate_hum_noise(
            mag_sq, freqs, sampling_rate, bin_width, is_linear_freqs, freq_step, start_freq
        ),
        number=num,
    )

    print(f"Original:  {t_orig:.4f}s")
    print(f"Optimized: {t_opt:.4f}s")
    print(f"Improvement: {(t_orig - t_opt) / t_orig * 100:.2f}%")
