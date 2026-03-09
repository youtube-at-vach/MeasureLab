import numpy as np
import timeit

def orig_search(freqs, mag_plot, hum_freqs):
    hum_vals = []
    for f in hum_freqs:
        idx = np.argmin(np.abs(freqs - f))
        hum_vals.append(mag_plot[idx])
    return hum_vals

def new_search(freqs, mag_plot, hum_freqs):
    hum_vals = []
    for f in hum_freqs:
        idx = np.searchsorted(freqs, f)
        if idx == 0:
            closest_idx = 0
        elif idx == len(freqs):
            closest_idx = len(freqs) - 1
        else:
            if abs(freqs[idx] - f) < abs(freqs[idx - 1] - f):
                closest_idx = idx
            else:
                closest_idx = idx - 1
        hum_vals.append(mag_plot[closest_idx])
    return hum_vals

N = 16384 // 2 + 1  # Typical rfft output size
freqs = np.linspace(0, 24000, N)
mag_plot = np.random.rand(N)
hum_freqs = [50, 100, 150, 200, 250, 300, 350, 400, 450, 500, 60, 120, 180, 240, 300, 360, 420, 480, 540, 600]

print("Verifying correctness...")
res1 = orig_search(freqs, mag_plot, hum_freqs)
res2 = new_search(freqs, mag_plot, hum_freqs)
assert res1 == res2, "Results do not match!"

print("Running benchmarks...")
n_runs = 1000

t_orig = timeit.timeit(lambda: orig_search(freqs, mag_plot, hum_freqs), number=n_runs)
print(f"Original Time: {t_orig / n_runs:.6f} s per execution")

t_new = timeit.timeit(lambda: new_search(freqs, mag_plot, hum_freqs), number=n_runs)
print(f"New Time: {t_new / n_runs:.6f} s per execution")

speedup = t_orig / t_new if t_new > 0 else 0
print(f"Speedup: {speedup:.2f}x")
