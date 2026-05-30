import numpy as np
import scipy.signal

class PRBSGenerator:
    """
    Linear Feedback Shift Register (LFSR) based PRBS Generator.
    Supports PRBS-15 (x^15 + x^14 + 1) and PRBS-9 (x^9 + x^5 + 1).
    """
    def __init__(self, mode="PRBS-15", seed=0x7FFF):
        self.mode = mode
        if mode == "PRBS-15":
            self.mask = 0x7FFF
            self.seed = seed & self.mask
            if self.seed == 0:
                self.seed = 0x7FFF
            self.tap1 = 14
            self.tap2 = 13
        elif mode == "PRBS-9":
            self.mask = 0x01FF
            self.seed = seed & self.mask
            if self.seed == 0:
                self.seed = 0x01FF
            self.tap1 = 8
            self.tap2 = 4
        else:
            raise ValueError(f"Unknown PRBS mode: {mode}")

        self.state = self.seed

    def reset(self):
        self.state = self.seed

    def next_bit(self):
        if self.mode == "PRBS-15":
            bit = ((self.state >> self.tap1) ^ (self.state >> self.tap2)) & 1
            self.state = ((self.state << 1) | bit) & self.mask
        else:  # PRBS-9
            bit = ((self.state >> self.tap1) ^ (self.state >> self.tap2)) & 1
            self.state = ((self.state << 1) | bit) & self.mask
        return bit

    def next_sample_16(self):
        """Generate a 16-bit float sample in range [-1.0, 1.0)"""
        val = 0
        for _ in range(16):
            val = (val << 1) | self.next_bit()
        if val >= 32768:
            val -= 65566  # Map to signed 16-bit int
        return float(val) / 32768.0

    def next_sample_24(self):
        """Generate a 24-bit float sample in range [-1.0, 1.0)"""
        val = 0
        for _ in range(24):
            val = (val << 1) | self.next_bit()
        if val >= 8388608:
            val -= 16777216  # Map to signed 24-bit int
        return float(val) / 8388608.0

    def next_sample_8(self):
        """Generate an 8-bit float sample in range [-1.0, 1.0)"""
        val = 0
        for _ in range(8):
            val = (val << 1) | self.next_bit()
        if val >= 128:
            val -= 256  # Map to signed 8-bit int
        return float(val) / 128.0

    def generate_reference_sequence(self, length, bit_depth=24):
        """Generate a deterministic reference sequence of float samples."""
        self.reset()
        seq = np.empty(length, dtype=np.float32)
        if bit_depth == 24:
            for i in range(length):
                seq[i] = self.next_sample_24()
        elif bit_depth == 16:
            for i in range(length):
                seq[i] = self.next_sample_16()
        else:
            for i in range(length):
                seq[i] = self.next_sample_8()
        return seq

def find_sequence_delay(rx_segment, ref_cycle):
    """
    Finds the integer sample delay (offset) of rx_segment in ref_cycle using
    mathematically exact sliding Pearson correlation (zero-mean normalized).

    rx_segment: 1D array, length N (e.g. 1024)
    ref_cycle: 1D array, length M (e.g. 32767)
    Returns: (offset, correlation_coefficient)
    """
    N = len(rx_segment)
    M = len(ref_cycle)

    if N >= M:
        # Segment is too long, truncate it for correlation
        rx_segment = rx_segment[:M // 2]
        N = len(rx_segment)

    # 1. Normalize rx_segment to have zero mean and unit L2 norm
    rx_ac = rx_segment - np.mean(rx_segment)
    rx_norm_l2 = np.linalg.norm(rx_ac)
    if rx_norm_l2 < 1e-6:
        return 0, 0.0
    rx_norm = rx_ac / rx_norm_l2

    # 2. Duplicate ref_cycle to handle circular wrap-around during cross-correlation
    ref_double = np.concatenate((ref_cycle, ref_cycle[:N]))

    # 3. Compute sliding cross-correlation of ref_double with zero-mean rx_norm.
    # Since rx_norm has exactly zero-mean (sum(rx_norm) == 0), the sliding dot(ref_w, rx_norm)
    # is mathematically identical to dot(ref_w - mean_ref_w, rx_norm).
    corr = scipy.signal.correlate(ref_double, rx_norm, mode='valid')

    # 4. Compute sliding zero-mean L2 norm of the reference window:
    # norm(ref_w - mean_ref_w) = sqrt( sum(ref_w^2) - (sum(ref_w))^2 / N )
    ones_window = np.ones(N)
    sum_ref_sq = scipy.signal.convolve(ref_double ** 2, ones_window, mode='valid')
    sum_ref = scipy.signal.convolve(ref_double, ones_window, mode='valid')

    ref_var = sum_ref_sq - (sum_ref ** 2) / N
    ref_zero_mean_norms = np.sqrt(np.maximum(0.0, ref_var))

    # 5. Compute sliding normalized correlation coefficient
    norm_corr = corr / (ref_zero_mean_norms + 1e-12)

    best_offset = np.argmax(norm_corr)
    best_val = norm_corr[best_offset]

    return int(best_offset % M), float(best_val)

def diagnose_bit_perfection(rx, ref):
    """
    Analyzes rx and ref (which are aligned) to determine bit-perfection status.
    rx: 1D array of recorded samples
    ref: 1D array of expected reference samples
    Returns a dict with diagnostic metrics.
    """
    N = len(rx)
    epsilon = 1e-12

    # 1. Exact match check
    # 24-bit floats have approx 7 decimal digits of precision, 
    # but we store exact 24-bit values which fit exactly into float32 mantissa.
    # float32 has 24 bits of mantissa, so it can represent 24-bit ints exactly.
    exact_matches = np.sum(np.abs(rx - ref) < 1e-7)
    exact_ratio = exact_matches / N

    if exact_ratio > 0.9999:
        return {
            "bit_perfect": True,
            "reason": "Perfect bit-for-bit match.",
            "gain_db": 0.0,
            "bit_depth": 24,
            "bit_errors": 0,
            "error_rate": 0.0,
            "active_bits": 24
        }

    # 2. Gain detection (rx = K * ref)
    dot_ref_ref = np.dot(ref, ref)
    if dot_ref_ref > epsilon:
        K = np.dot(rx, ref) / dot_ref_ref
    else:
        K = 1.0

    gain_db = 20 * np.log10(abs(K) + epsilon)

    # If gain is extremely close to 1.0, treat it as 1.0
    if abs(K - 1.0) < 1e-6:
        K = 1.0
        gain_db = 0.0

    scaled_diff = rx - K * ref
    scaled_rms = np.sqrt(np.mean(scaled_diff ** 2))

    ref_rms = np.sqrt(np.mean(ref ** 2))
    rel_error = scaled_rms / (ref_rms + epsilon)

    # Bit error count (how many samples don't match expected scaled values)
    tol = 1e-6
    errors = np.sum(np.abs(rx - K * ref) > tol)
    error_rate = errors / N

    # 3. Detect Bit Depth / Truncation
    rx_scaled = rx / (K + epsilon)

    # Check if 16-bit:
    rx_scaled_16 = np.round(rx_scaled * 32768.0) / 32768.0
    diff_16 = np.abs(rx_scaled - rx_scaled_16)
    if np.max(diff_16) < 1e-6:
        reason = "Volume altered, bit depth reduced to 16-bit." if abs(gain_db) > 0.01 else "Bit depth reduced to 16-bit."
        return {
            "bit_perfect": False,
            "reason": reason,
            "gain_db": gain_db,
            "bit_depth": 16,
            "bit_errors": errors,
            "error_rate": error_rate,
            "active_bits": 16
        }

    # Check if 24-bit:
    rx_scaled_24 = np.round(rx_scaled * 8388608.0) / 8388608.0
    diff_24 = np.abs(rx_scaled - rx_scaled_24)
    if np.max(diff_24) < 1e-8:
        if abs(gain_db) > 0.01:
            reason = "Volume altered by {:.2f} dB (Not Bit-Perfect).".format(gain_db)
            return {
                "bit_perfect": False,
                "reason": reason,
                "gain_db": gain_db,
                "bit_depth": 24,
                "bit_errors": errors,
                "error_rate": error_rate,
                "active_bits": 24
            }

    # Check if 8-bit:
    rx_scaled_8 = np.round(rx_scaled * 128.0) / 128.0
    diff_8 = np.abs(rx_scaled - rx_scaled_8)
    if np.max(diff_8) < 1e-4:
        reason = "Volume altered, bit depth reduced to 8-bit." if abs(gain_db) > 0.01 else "Bit depth reduced to 8-bit."
        return {
            "bit_perfect": False,
            "reason": reason,
            "gain_db": gain_db,
            "bit_depth": 8,
            "bit_errors": errors,
            "error_rate": error_rate,
            "active_bits": 8
        }

    # If scaled_rms is large, then it is NOT bit-perfect at all (altered or high distortion)
    if rel_error > 0.005:
        return {
            "bit_perfect": False,
            "reason": "Signal altered (Resampling, high distortion, or heavy processing detected).",
            "gain_db": gain_db,
            "bit_depth": 0,
            "bit_errors": N,
            "error_rate": 1.0,
            "active_bits": 0
        }

    # General non-bit-perfect (minor alterations)
    return {
        "bit_perfect": False,
        "reason": "Data modified (small differences or dither detected).",
        "gain_db": gain_db,
        "bit_depth": 24,
        "bit_errors": errors,
        "error_rate": error_rate,
        "active_bits": 24
    }
