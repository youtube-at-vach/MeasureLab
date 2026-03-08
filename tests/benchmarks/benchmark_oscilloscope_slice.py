import time
import numpy as np

def benchmark():
    N = 8192

    # Setup single buffer
    single_buffer = np.random.rand(N, 2).astype(np.float32)

    # Setup double buffer
    double_buffer = np.random.rand(N * 2, 2).astype(np.float32)
    double_buffer[N:] = double_buffer[:N]

    length = 4096

    iterations = 100000

    # 1. Benchmark np.concatenate
    start = time.time()
    for i in range(iterations):
        idx = (i * 123) % N
        part1 = N - idx
        if part1 >= length:
            _ = single_buffer[idx:idx+length].copy()
        else:
            part2 = length - part1
            _ = np.concatenate((single_buffer[idx:N], single_buffer[:part2]), axis=0)
    end1 = time.time()
    print(f"Original (concatenate): {end1 - start:.4f}s")

    # 2. Benchmark double buffer copy
    start = time.time()
    for i in range(iterations):
        idx = (i * 123) % N
        _ = double_buffer[idx:idx+length].copy()
    end2 = time.time()
    print(f"Optimized (double buffer slice): {end2 - start:.4f}s")

if __name__ == '__main__':
    benchmark()
