
import time
import numpy as np

def benchmark_roll_vs_concat():
    # Sizes relevant to "Normal Rolling Mode" (< 500,000)
    sizes = [1024, 4096, 8192, 16384, 32768, 65536, 131072, 262144]
    channels = 2
    iterations = 200

    print(f"{'Buffer Size':<15} | {'np.roll (s)':<12} | {'Concat (s)':<12} | {'Speedup':<8}")
    print("-" * 55)

    for buffer_size in sizes:
        input_data = np.random.rand(buffer_size, channels)
        write_head = buffer_size // 2  # Worst case split

        # Benchmark np.roll
        start_time = time.time()
        for _ in range(iterations):
            data_roll = np.roll(input_data, -write_head, axis=0)
        roll_duration = time.time() - start_time

        # Benchmark concatenation
        start_time = time.time()
        for _ in range(iterations):
            if write_head == 0:
                data_concat = input_data.copy()
            else:
                data_concat = np.concatenate((input_data[write_head:], input_data[:write_head]), axis=0)
        concat_duration = time.time() - start_time

        # Verify correctness
        np.testing.assert_array_equal(data_roll, data_concat)

        print(f"{buffer_size:<15} | {roll_duration:.4f}       | {concat_duration:.4f}       | {roll_duration / concat_duration:.2f}x")

if __name__ == "__main__":
    benchmark_roll_vs_concat()
