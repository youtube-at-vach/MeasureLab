import numpy as np


class BitDepthEstimator:
    """
    Estimates the effective bit depth (ENOB) and analyzes quantization noise
    from a sequence of audio samples.
    """

    def __init__(self, capacity=8192):
        self._capacity = capacity
        # To avoid data type issues during concatenation and preserve precision,
        # we do not force np.float32 for the buffer unless we know it.
        # But we don't know it until the first block, so we initialize as float64
        # to match np.random.randn default, or just dynamically initialize on first add.
        self._buffer = None
        self._write_ptr = 0

    def reset(self):
        self._write_ptr = 0

    def add_samples(self, samples: np.ndarray):
        """Add samples to the internal buffer for later analysis."""
        n = len(samples)
        if self._buffer is None:
            self._buffer = np.zeros(max(self._capacity, n), dtype=samples.dtype)
            self._capacity = len(self._buffer)

        if self._write_ptr + n > self._capacity:
            new_capacity = max(self._capacity * 2, self._write_ptr + n)
            new_buffer = np.zeros(new_capacity, dtype=self._buffer.dtype)
            if self._write_ptr > 0:
                new_buffer[: self._write_ptr] = self._buffer[: self._write_ptr]
            self._buffer = new_buffer
            self._capacity = new_capacity

        self._buffer[self._write_ptr : self._write_ptr + n] = samples
        self._write_ptr += n

    def analyze(self):
        """
        Perform analysis on the accumulated samples.
        Returns a dictionary with results:
        - 'bit_depth': Estimated effective bit depth (float)
        - 'delta_hist': Tuple (hist, bin_edges) for quantization step histogram
        - 'bit_distribution': Array of length 32 representing bit activity probability
        """
        if self._write_ptr == 0:
            return None

        # Just take a copy of the valid data
        full_data = self._buffer[: self._write_ptr].copy()
        self._write_ptr = 0  # Clear buffer after processing

        if len(full_data) < 2:
            return None

        results = {}

        # 1. Delta Estimation & Bit Depth
        diffs = np.abs(np.diff(full_data))
        # Filter out exact zeros (digital silence or repeated samples)
        nonzero_diffs = diffs[diffs > 1e-12]

        estimated_bits = 0.0
        if len(nonzero_diffs) > 0:
            # Find the smallest non-zero step
            min_delta = np.min(nonzero_diffs)

            if min_delta > 0:
                estimated_bits = 1 - np.log2(min_delta)
                # Clamp reasonably (0 to 64)
                estimated_bits = max(0.0, min(64.0, estimated_bits))

        results["bit_depth"] = estimated_bits

        # 2. Delta Histogram
        if len(nonzero_diffs) > 0:
            log_diffs = np.log10(nonzero_diffs)
            # Histogram for log10(delta) from -13 (1e-13) to 0 (1.0)
            hist, bin_edges = np.histogram(log_diffs, bins=50, range=(-13, 0))
            results["delta_hist"] = (hist, bin_edges)
        else:
            results["delta_hist"] = None

        # 3. LSB / Bit Activity
        # Convert to 32-bit int representation
        # Scale to full 32-bit range (-1.0 to 1.0 -> Int32 Min to Max)
        # Note: We use 2^31 - 1 to map 1.0 to MAX_INT.
        clipped_data = np.clip(full_data, -1.0, 1.0)
        int_data = (clipped_data * (2**31 - 1)).astype(np.int32)

        # Convert to sign-magnitude representation to avoid two's complement sign-extension artifacts.
        # Positive values: magnitude is in abs_data (bits 0 to 30), sign bit (bit 31) is 0.
        # Negative values: magnitude is in abs_data (bits 0 to 30), sign bit (bit 31) is 1.
        abs_data = np.abs(int_data).astype(np.uint32)
        sign_bit = (int_data < 0).astype(np.uint32) << 31
        uint_data = abs_data | sign_bit

        n_samples = len(uint_data)
        bit_counts = np.zeros(32)

        # Vectorized bit counting
        # Iterate bits 0 to 31
        # Create a range of powers of 2: [1, 2, 4, ..., 2^31]
        # But we need to do it carefully to avoid memory explosion if we broadcast too much.
        # Loop is fine for 32 iterations.
        for i in range(32):
            mask = np.uint32(1 << i)
            # Count samples where bit i is set
            count = np.count_nonzero(uint_data & mask)
            bit_counts[i] = count / n_samples

        results["bit_distribution"] = bit_counts

        return results
