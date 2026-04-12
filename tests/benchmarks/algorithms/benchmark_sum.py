import time
import numpy as np

def test_sum():
    K = 100
    N_chunks = 1000

    def get_chunk():
        return np.ones(K, dtype=np.complex128)

    start = time.perf_counter()
    for _ in range(100):
        sum((get_chunk() for _ in range(N_chunks)), np.zeros(K, dtype=np.complex128))
    t1 = time.perf_counter() - start

    start = time.perf_counter()
    for _ in range(100):
        res2 = np.zeros(K, dtype=np.complex128)
        for _ in range(N_chunks):
            res2 += get_chunk()
    t2 = time.perf_counter() - start

    print(f"sum(): {t1:.4f}s")
    print(f"+= loop: {t2:.4f}s")

test_sum()
