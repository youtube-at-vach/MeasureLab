import time
import numpy as np

def benchmark_buffer():
    buffer_size = 65536
    block_size = 1024
    num_iterations = 1000

    # Setup
    input_data_roll = np.zeros((buffer_size, 2))
    input_data_ring = np.zeros((buffer_size, 2))

    new_data = np.random.rand(block_size, 2)

    # 1. Benchmark np.roll
    start_time = time.perf_counter()
    for _ in range(num_iterations):
        if len(new_data) > buffer_size:
            input_data_roll[:] = new_data[-buffer_size:]
        else:
            input_data_roll = np.roll(input_data_roll, -len(new_data), axis=0)
            input_data_roll[-len(new_data):] = new_data
    end_time = time.perf_counter()
    roll_time = end_time - start_time

    # 2. Benchmark Ring Buffer
    start_time = time.perf_counter()
    buffer_pos = 0
    for _ in range(num_iterations):
        # Ring buffer logic
        chunk_len = len(new_data)

        # Determine write indices
        idx1 = buffer_pos
        idx2 = buffer_pos + chunk_len

        if idx2 <= buffer_size:
            # Simple case: fits without wrapping
            input_data_ring[idx1:idx2] = new_data
            buffer_pos = idx2 if idx2 < buffer_size else 0
        else:
            # Wrap around
            first_part = buffer_size - idx1
            second_part = chunk_len - first_part

            input_data_ring[idx1:] = new_data[:first_part]
            input_data_ring[:second_part] = new_data[first_part:]

            buffer_pos = second_part

    end_time = time.perf_counter()
    ring_time = end_time - start_time

    print(f"Buffer Size: {buffer_size}, Block Size: {block_size}, Iterations: {num_iterations}")
    print(f"np.roll Time: {roll_time:.6f} s")
    print(f"Ring Buffer Time: {ring_time:.6f} s")
    print(f"Speedup: {roll_time / ring_time:.2f}x")

if __name__ == "__main__":
    benchmark_buffer()
