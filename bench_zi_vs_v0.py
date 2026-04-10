import time
import numpy as np
from scipy.signal import lfilter

order = 8
alpha = 0.1
state = np.zeros(order, dtype=np.complex128)
x = 1.0 + 0.5j

N = 100000

t0 = time.perf_counter()
for _ in range(N):
    v = (1 - alpha) * state
    v[0] += alpha * x
    state[:] = lfilter([1], [1, -alpha], v)
t1 = time.perf_counter()
print(f"v[0] + lfilter: {t1-t0:.6f} s")

t0 = time.perf_counter()
for _ in range(N):
    v = (1 - alpha) * state
    zi = np.array([alpha * x])
    state[:], _ = lfilter([1], [1, -alpha], v, zi=zi)
t1 = time.perf_counter()
print(f"lfilter with zi: {t1-t0:.6f} s")
