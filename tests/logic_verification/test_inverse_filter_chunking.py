import unittest
import numpy as np
from scipy import signal

class TestInverseFilterChunking(unittest.TestCase):
    def test_chunked_convolution_logic(self):
        # Parameters
        N = 10000
        M = 101 # Odd kernel length
        chunk_size = 1024

        # Random input and kernel
        np.random.seed(42)
        x = np.random.randn(N).astype(np.float32)
        h = np.random.randn(M).astype(np.float32)

        # Reference: standard mode='same' convolution
        expected = signal.convolve(x, h, mode='same')

        # Chunked Implementation
        # We want to match expected

        # Overlap-Add State
        overlap_buffer = np.zeros(M - 1, dtype=np.float32)

        # Output collection
        output_stream = []

        # Calculate padding/skip for mode='same'
        # mode='same' centers the output.
        # Full convolution length is N + M - 1.
        # Centered output starts at index (M - 1) // 2
        # And has length N.

        delay = (M - 1) // 2
        samples_to_skip = delay
        samples_needed = N

        # Process in chunks
        for i in range(0, N, chunk_size):
            chunk = x[i : i + chunk_size]

            # Convolve chunk with kernel (full mode)
            # Using fftconvolve for speed, but standard convolve is fine for test
            conv_chunk = signal.convolve(chunk, h, mode='full')

            # Add overlap
            L = len(chunk)
            # conv_chunk length is L + M - 1

            # Add previous overlap to the start
            n_overlap = len(overlap_buffer)
            conv_chunk[:n_overlap] += overlap_buffer

            # Save new overlap (last M-1 samples)
            overlap_buffer = conv_chunk[L:]

            # The valid output from this block (linear convolution stream) is the first L samples
            # Wait, linear convolution stream is continuous.
            # The part we take *now* is the first L samples of the result?
            # Yes, standard Overlap-Add:
            # y[n] = sum of overlapping blocks.
            # Block k covers indices k*L to (k+1)*L + M - 1
            # We output indices k*L to (k+1)*L.
            # The tail (beyond (k+1)*L) is saved for next block.

            current_output_full = conv_chunk[:L]
            output_stream.append(current_output_full)

        # Concatenate full linear convolution stream (up to end of input)
        # Note: The last overlap buffer contains the tail of the convolution
        # (the "ring out" after input ends).
        # We might need it if the centered window extends past the input end?
        # N + (M-1)/2 vs N.
        # Yes, we might need samples from the tail.

        output_stream.append(overlap_buffer)

        full_linear_conv = np.concatenate(output_stream)

        # Slice for mode='same'
        # start = delay
        # end = delay + N

        start = delay
        end = start + N

        # Check bounds
        if end > len(full_linear_conv):
             # Should not happen if math is right: len is N + M - 1
             # end is N + (M-1)/2.
             # N + (M-1)/2 < N + M - 1  (since M >= 1)
             pass

        result = full_linear_conv[start:end]

        # Assert close
        np.testing.assert_allclose(result, expected, rtol=1e-5, atol=1e-5)
        print("Test Passed: Chunked logic matches mode='same'")

if __name__ == '__main__':
    unittest.main()
