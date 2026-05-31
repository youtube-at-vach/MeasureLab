import logging
import numpy as np
import scipy.signal

logger = logging.getLogger(__name__)

class PRBSGenerator:
    """
    Linear Feedback Shift Register (LFSR) based PRBS Generator.
    Supports PRBS-7, PRBS-9, PRBS-15, PRBS-23, and PRBS-31.
    """
    def __init__(self, mode="PRBS-15", seed=0x7FFFFFFF):
        self.mode = mode
        # LFSR properties based on the selected PRBS mode (ITU-T O.150 standard taps)
        if mode == "PRBS-7":
            self.mask = 0x7F         # 7 bits
            self.seed = seed & self.mask
            if self.seed == 0:
                self.seed = 0x7F
            self.tap1 = 6            # x^7 + x^6 + 1 => index 6, 5 (0-based)
            self.tap2 = 5
            self.period = 127
        elif mode == "PRBS-9":
            self.mask = 0x01FF       # 9 bits
            self.seed = seed & self.mask
            if self.seed == 0:
                self.seed = 0x01FF
            self.tap1 = 8            # x^9 + x^5 + 1 => index 8, 4 (0-based)
            self.tap2 = 4
            self.period = 511
        elif mode == "PRBS-15":
            self.mask = 0x7FFF       # 15 bits
            self.seed = seed & self.mask
            if self.seed == 0:
                self.seed = 0x7FFF
            self.tap1 = 14           # x^15 + x^14 + 1 => index 14, 13 (0-based)
            self.tap2 = 13
            self.period = 32767
        elif mode == "PRBS-23":
            self.mask = 0x7FFFFF     # 23 bits
            self.seed = seed & self.mask
            if self.seed == 0:
                self.seed = 0x7FFFFF
            self.tap1 = 22           # x^23 + x^18 + 1 => index 22, 17 (0-based)
            self.tap2 = 17
            self.period = 8388607
        elif mode == "PRBS-31":
            self.mask = 0x7FFFFFFF   # 31 bits
            self.seed = seed & self.mask
            if self.seed == 0:
                self.seed = 0x7FFFFFFF
            self.tap1 = 30           # x^31 + x^28 + 1 => index 30, 27 (0-based)
            self.tap2 = 27
            self.period = 2147483647
        else:
            raise ValueError(f"Unknown PRBS mode: {mode}")

        self.state = self.seed

    def reset(self):
        self.state = self.seed

    def next_bit(self) -> int:
        """Advance LFSR and return the next pseudo-random bit."""
        bit = ((self.state >> self.tap1) ^ (self.state >> self.tap2)) & 1
        self.state = ((self.state << 1) | bit) & self.mask
        return bit

    def next_sample_8(self) -> float:
        """Generate a float sample representing 8-bit depth [-1.0, 1.0)"""
        val = 0
        for _ in range(8):
            val = (val << 1) | self.next_bit()
        if val >= 128:
            val -= 256
        return float(val) / 128.0

    def next_sample_16(self) -> float:
        """Generate a float sample representing 16-bit depth [-1.0, 1.0)"""
        val = 0
        for _ in range(16):
            val = (val << 1) | self.next_bit()
        if val >= 32768:
            val -= 65536
        return float(val) / 32768.0

    def next_sample_24(self) -> float:
        """Generate a float sample representing 24-bit depth [-1.0, 1.0)"""
        val = 0
        for _ in range(24):
            val = (val << 1) | self.next_bit()
        if val >= 8388608:
            val -= 16777216
        return float(val) / 8388608.0

    def next_sample(self, bit_depth=24) -> float:
        """Generate a single sample at specified bit depth dynamically."""
        if bit_depth == 24:
            return self.next_sample_24()
        elif bit_depth == 16:
            return self.next_sample_16()
        else:
            return self.next_sample_8()

    def generate_reference_sequence(self, length: int, bit_depth=24) -> np.ndarray:
        """Generate a sequence of samples deterministically from reset state."""
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


def find_sequence_delay(rx_segment: np.ndarray, ref_cycle: np.ndarray) -> tuple[int, float]:
    """
    Finds the integer sample delay (offset) of rx_segment in ref_cycle using
    sliding Pearson correlation.
    
    rx_segment: 1D array of received signal (usually 1024 or 2048 samples)
    ref_cycle: 1D array of expected reference sequence
    Returns: (offset, correlation_coefficient)
    """
    N = len(rx_segment)
    M = len(ref_cycle)

    if N >= M:
        rx_segment = rx_segment[:M // 2]
        N = len(rx_segment)

    rx_ac = rx_segment - np.mean(rx_segment)
    rx_norm_l2 = np.linalg.norm(rx_ac)
    if rx_norm_l2 < 1e-6:
        return 0, 0.0
    rx_norm = rx_ac / rx_norm_l2

    ref_double = np.concatenate((ref_cycle, ref_cycle[:N]))

    corr = scipy.signal.correlate(ref_double, rx_norm, mode='valid')

    ones_window = np.ones(N)
    sum_ref_sq = scipy.signal.convolve(ref_double ** 2, ones_window, mode='valid')
    sum_ref = scipy.signal.convolve(ref_double, ones_window, mode='valid')

    ref_var = sum_ref_sq - (sum_ref ** 2) / N
    ref_zero_mean_norms = np.sqrt(np.maximum(0.0, ref_var))

    norm_corr = corr / (ref_zero_mean_norms + 1e-12)

    best_offset = np.argmax(norm_corr)
    best_val = norm_corr[best_offset]

    return int(best_offset % M), float(best_val)


def track_jitter(rx_block: np.ndarray, tx_history: np.ndarray, last_offset: int, max_search=8) -> tuple[int, float]:
    """
    Refines and tracks synchronization offset changes (jitter/slips) block-by-block.
    Looks in a small neighborhood around last_offset.
    
    Returns: (new_offset, correlation)
    """
    N = len(rx_block)
    H = len(tx_history)
    
    best_corr = -1.0
    best_offset = last_offset

    # Compute correlation for offsets in [last_offset - max_search, last_offset + max_search]
    rx_ac = rx_block - np.mean(rx_block)
    rx_norm = np.linalg.norm(rx_ac)
    if rx_norm < 1e-6:
        return last_offset, 0.0
    rx_ac /= rx_norm

    for delta in range(-max_search, max_search + 1):
        test_offset = (last_offset + delta) % H
        # Extract corresponding TX segment from history
        if test_offset + N <= H:
            tx_seg = tx_history[test_offset : test_offset + N]
        else:
            part = H - test_offset
            tx_seg = np.concatenate((tx_history[test_offset:], tx_history[: N - part]))
            
        tx_ac = tx_seg - np.mean(tx_seg)
        tx_norm = np.linalg.norm(tx_ac)
        if tx_norm < 1e-6:
            continue
        tx_ac /= tx_norm
        
        corr = np.dot(rx_ac, tx_ac)
        if corr > best_corr:
            best_corr = corr
            best_offset = test_offset

    return best_offset, float(best_corr)


def extract_impulse_response(rx_block: np.ndarray, tx_block: np.ndarray, regularization=1e-4) -> np.ndarray:
    """
    Extracts the impulse response h[t] of the transmission path via FFT deconvolution:
    H(f) = Y(f) * X*(f) / (|X(f)|^2 + reg)
    """
    N = len(rx_block)
    # Apply Hanning window to reduce boundary artifacts in deconvolution
    window = np.hanning(N)
    
    rx_win = rx_block * window
    tx_win = tx_block * window

    X = np.fft.fft(tx_win)
    Y = np.fft.fft(rx_win)
    
    # Regularized deconvolution
    H = (Y * np.conj(X)) / (np.abs(X) ** 2 + regularization * np.max(np.abs(X) ** 2))
    h = np.fft.ifft(H)
    
    # Return real part, centered/shifted
    return np.real(h)


def extract_frequency_response(rx_block: np.ndarray, tx_block: np.ndarray, sr: float, regularization=1e-4) -> tuple[np.ndarray, np.ndarray]:
    """
    Computes magnitude frequency response (dB vs Hz) of the channel.
    
    Returns: (freqs, magnitude_db)
    """
    N = len(rx_block)
    window = np.hanning(N)
    
    X = np.fft.rfft(tx_block * window)
    Y = np.fft.rfft(rx_block * window)
    
    # Regulator to avoid log(0)
    H = Y / (X + 1e-12)
    mag_db = 20 * np.log10(np.abs(H) + 1e-6)
    
    freqs = np.fft.rfftfreq(N, 1.0 / sr)
    return freqs, mag_db


def calculate_evm(rx_block: np.ndarray, tx_block: np.ndarray) -> float:
    """
    Calculates Error Vector Magnitude (EVM) in %.
    Matches gains and scales before computing discrepancy.
    """
    # Align gains (least squares scale)
    dot_tx = np.dot(tx_block, tx_block)
    if dot_tx < 1e-12:
        return 100.0
    scale = np.dot(rx_block, tx_block) / dot_tx
    
    error_vector = rx_block - scale * tx_block
    rms_error = np.sqrt(np.mean(error_vector ** 2))
    rms_reference = np.sqrt(np.mean(tx_block ** 2))
    
    if rms_reference < 1e-12:
        return 100.0
    
    evm_percent = (rms_error / rms_reference) * 100.0
    return float(np.clip(evm_percent, 0.0, 100.0))


def measure_crosstalk(rx_block: np.ndarray, leak_reference: np.ndarray) -> float:
    """
    Measures crosstalk by finding the leakage correlation with the opposite channel's PRBS sequence.
    
    Returns leakage ratio in dB.
    """
    N = len(rx_block)
    M = len(leak_reference)
    
    # Sub-segment correlation
    sub_len = min(N, M)
    rx_seg = rx_block[:sub_len]
    leak_seg = leak_reference[:sub_len]
    
    rx_ac = rx_seg - np.mean(rx_seg)
    leak_ac = leak_seg - np.mean(leak_seg)
    
    norm_rx = np.linalg.norm(rx_ac)
    norm_leak = np.linalg.norm(leak_ac)
    
    if norm_rx < 1e-6 or norm_leak < 1e-6:
        return -120.0
        
    rx_ac /= norm_rx
    leak_ac /= norm_leak
    
    # Calculate scalar projection of leak onto rx
    # Represents the leakage coefficient
    c_coeff = np.dot(rx_seg, leak_seg) / np.dot(leak_seg, leak_seg)
    c_coeff_abs = abs(c_coeff)
    
    if c_coeff_abs < 1e-6:
        return -120.0
        
    crosstalk_db = 20 * np.log10(c_coeff_abs + 1e-12)
    return float(np.clip(crosstalk_db, -120.0, 0.0))


def diagnose_bit_perfection(rx: np.ndarray, ref: np.ndarray) -> dict:
    """
    Analyzes rx and ref to determine exact digital transmission path bit-perfection.
    """
    N = len(rx)
    epsilon = 1e-12

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
            "active_bits": 24,
            "dsp_detected": "None (Transparent)"
        }

    dot_ref_ref = np.dot(ref, ref)
    if dot_ref_ref > epsilon:
        K = np.dot(rx, ref) / dot_ref_ref
    else:
        K = 1.0

    gain_db = 20 * np.log10(abs(K) + epsilon)

    if abs(K - 1.0) < 1e-6:
        K = 1.0
        gain_db = 0.0

    scaled_diff = rx - K * ref
    scaled_rms = np.sqrt(np.mean(scaled_diff ** 2))
    ref_rms = np.sqrt(np.mean(ref ** 2))
    rel_error = scaled_rms / (ref_rms + epsilon)

    tol = 1e-6
    errors = np.sum(np.abs(rx - K * ref) > tol)
    error_rate = errors / N

    # Analyze error structure for DSP heuristics
    rx_scaled = rx / (K + epsilon)
    
    # 1. Check if 16-bit truncated
    rx_scaled_16 = np.round(rx_scaled * 32768.0) / 32768.0
    if np.max(np.abs(rx_scaled - rx_scaled_16)) < 1e-6:
        reason = "Volume altered, bit depth reduced to 16-bit." if abs(gain_db) > 0.01 else "Bit depth reduced to 16-bit."
        return {
            "bit_perfect": False,
            "reason": reason,
            "gain_db": gain_db,
            "bit_depth": 16,
            "bit_errors": errors,
            "error_rate": error_rate,
            "active_bits": 16,
            "dsp_detected": "Bit Truncation (16-bit)"
        }

    # 2. Check if 24-bit with gain only
    rx_scaled_24 = np.round(rx_scaled * 8388608.0) / 8388608.0
    if np.max(np.abs(rx_scaled - rx_scaled_24)) < 1e-8:
        if abs(gain_db) > 0.01:
            return {
                "bit_perfect": False,
                "reason": "Volume altered by {:.2f} dB (Not Bit-Perfect).".format(gain_db),
                "gain_db": gain_db,
                "bit_depth": 24,
                "bit_errors": errors,
                "error_rate": error_rate,
                "active_bits": 24,
                "dsp_detected": "Volume/Gain Scaler"
            }

    # 3. Check if 8-bit truncated
    rx_scaled_8 = np.round(rx_scaled * 128.0) / 128.0
    if np.max(np.abs(rx_scaled - rx_scaled_8)) < 1e-4:
        reason = "Volume altered, bit depth reduced to 8-bit." if abs(gain_db) > 0.01 else "Bit depth reduced to 8-bit."
        return {
            "bit_perfect": False,
            "reason": reason,
            "gain_db": gain_db,
            "bit_depth": 8,
            "bit_errors": errors,
            "error_rate": error_rate,
            "active_bits": 8,
            "dsp_detected": "Bit Truncation (8-bit)"
        }

    # 4. Check for Dither (LSB toggle error only)
    # LSB 24 errors represent extremely tiny deviations
    err_vals = np.abs(rx_scaled - ref)
    if np.max(err_vals) < 5e-7:
        return {
            "bit_perfect": False,
            "reason": "Bit integrity modified at LSB level (Dither or minor EQ).",
            "gain_db": gain_db,
            "bit_depth": 24,
            "bit_errors": errors,
            "error_rate": error_rate,
            "active_bits": 24,
            "dsp_detected": "Dither / Noise Shaping"
        }

    # 5. Heavy modification (Resampling, EQ, non-linear)
    if rel_error > 0.005:
        return {
            "bit_perfect": False,
            "reason": "Signal altered (Resampling, EQ, or compression detected).",
            "gain_db": gain_db,
            "bit_depth": 0,
            "bit_errors": N,
            "error_rate": 1.0,
            "active_bits": 0,
            "dsp_detected": "Resampling / Heavy DSP / Compressor"
        }

    return {
        "bit_perfect": False,
        "reason": "Data modified (unknown DSP processing).",
        "gain_db": gain_db,
        "bit_depth": 24,
        "bit_errors": errors,
        "error_rate": error_rate,
        "active_bits": 24,
        "dsp_detected": "Active EQ/Filter/DSP"
    }
