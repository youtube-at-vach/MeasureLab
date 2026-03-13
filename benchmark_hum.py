import timeit
import numpy as np

def mock_get_power_in_band(f):
    return f * 0.1

def orig(sampling_rate, base_freq):
    hum_power = 0.0
    hum_components = []
    for i in range(1, 11):
        f_h = base_freq * i
        if f_h > sampling_rate / 2:
            break
        p_h = mock_get_power_in_band(f_h)
        hum_power += p_h
        hum_components.append((f_h, np.sqrt(p_h)))
    return np.sqrt(hum_power), base_freq, hum_components

def new_comp_np2(sampling_rate, base_freq):
    max_i = min(10, int(sampling_rate / (2 * base_freq)))
    p_h_list = [mock_get_power_in_band(base_freq * i) for i in range(1, max_i + 1)]
    hum_power = sum(p_h_list)
    p_h_sqrt = np.sqrt(p_h_list).tolist()
    hum_components = [(base_freq * i, p) for i, p in enumerate(p_h_sqrt, start=1)]
    return np.sqrt(hum_power), base_freq, hum_components

print("orig:", timeit.timeit(lambda: orig(48000, 50.0), number=100000))
print("new_comp_np2:", timeit.timeit(lambda: new_comp_np2(48000, 50.0), number=100000))
