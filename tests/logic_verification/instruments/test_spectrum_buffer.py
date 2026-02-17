import numpy as np

def test_spectrum_buffer_unroll_logic():
    """
    Verify that the manual concatenation logic produces the same result
    as np.roll for unrolling a ring buffer.
    """
    buffer_sizes = [1024, 4096, 50000]

    for size in buffer_sizes:
        # Test various write positions
        write_positions = [0, 10, size // 2, size - 1]

        # Create test data (e.g. indices)
        # Shape (size, 2)
        input_data = np.zeros((size, 2))
        input_data[:, 0] = np.arange(size)
        input_data[:, 1] = np.arange(size) + 100000

        for write_head in write_positions:
            # Expected result using np.roll
            # np.roll shift is -write_head (shift left by write_head)
            expected = np.roll(input_data, -write_head, axis=0)

            # Optimized logic
            if write_head == 0:
                result = input_data.copy()
            else:
                result = np.concatenate(
                    (input_data[write_head:], input_data[:write_head]),
                    axis=0
                )

            np.testing.assert_array_equal(
                result,
                expected,
                err_msg=f"Failed for size={size}, write_head={write_head}"
            )

if __name__ == "__main__":
    test_spectrum_buffer_unroll_logic()
    print("test_spectrum_buffer_unroll_logic passed.")
