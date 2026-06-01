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
            self.mask = 0x7F  # 7 bits
            self.seed = seed & self.mask
            if self.seed == 0:
                self.seed = 0x7F
            self.tap1 = 6  # x^7 + x^6 + 1 => index 6, 5 (0-based)
            self.tap2 = 5
            self.period = 127
        elif mode == "PRBS-9":
            self.mask = 0x01FF  # 9 bits
            self.seed = seed & self.mask
            if self.seed == 0:
                self.seed = 0x01FF
            self.tap1 = 8  # x^9 + x^5 + 1 => index 8, 4 (0-based)
            self.tap2 = 4
            self.period = 511
        elif mode == "PRBS-15":
            self.mask = 0x7FFF  # 15 bits
            self.seed = seed & self.mask
            if self.seed == 0:
                self.seed = 0x7FFF
            self.tap1 = 14  # x^15 + x^14 + 1 => index 14, 13 (0-based)
            self.tap2 = 13
            self.period = 32767
        elif mode == "PRBS-23":
            self.mask = 0x7FFFFF  # 23 bits
            self.seed = seed & self.mask
            if self.seed == 0:
                self.seed = 0x7FFFFF
            self.tap1 = 22  # x^23 + x^18 + 1 => index 22, 17 (0-based)
            self.tap2 = 17
            self.period = 8388607
        elif mode == "PRBS-31":
            self.mask = 0x7FFFFFFF  # 31 bits
            self.seed = seed & self.mask
            if self.seed == 0:
                self.seed = 0x7FFFFFFF
            self.tap1 = 30  # x^31 + x^28 + 1 => index 30, 27 (0-based)
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
        rx_segment = rx_segment[: M // 2]
        N = len(rx_segment)

    rx_ac = rx_segment - np.mean(rx_segment)
    rx_norm_l2 = np.linalg.norm(rx_ac)
    if rx_norm_l2 < 1e-6:
        return 0, 0.0
    rx_norm = rx_ac / rx_norm_l2

    ref_double = np.concatenate((ref_cycle, ref_cycle[:N]))

    corr = scipy.signal.correlate(ref_double, rx_norm, mode="valid")

    ones_window = np.ones(N)
    sum_ref_sq = scipy.signal.convolve(ref_double**2, ones_window, mode="valid")
    sum_ref = scipy.signal.convolve(ref_double, ones_window, mode="valid")

    ref_var = sum_ref_sq - (sum_ref**2) / N
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


def extract_frequency_response(
    rx_block: np.ndarray, tx_block: np.ndarray, sr: float, regularization=1e-4
) -> tuple[np.ndarray, np.ndarray]:
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
    rms_error = np.sqrt(np.mean(error_vector**2))
    rms_reference = np.sqrt(np.mean(tx_block**2))

    if rms_reference < 1e-12:
        return 100.0

    evm_percent = (rms_error / rms_reference) * 100.0
    return float(np.clip(evm_percent, 0.0, 100.0))


def calculate_equalized_evm(rx_block: np.ndarray, tx_block: np.ndarray, regularization=1e-3) -> float:
    """
    Calculates Equalized Error Vector Magnitude (EVM) in % for analog channels.
    Estimates the linear channel frequency response H(f) and applies it to the
    transmitted reference signal tx_block, removing linear distortions (frequency
    response amplitude ripples and group delay phase variations) before EVM calculation.
    """
    N = len(rx_block)
    if N < 128:
        return calculate_evm(rx_block, tx_block)

    # Adaptive Equalization Bypass:
    # If unequalized EVM is already extremely low (e.g. < 0.5%), the channel is transparent
    # (lossless digital loopback). We bypass equalization to guarantee perfect 0.0% EVM
    # without regularization-induced spectral attenuation, while keeping high regularization (1e-3)
    # for physical analog channels to robustly suppress noise overfitting.
    evm_unequalized = calculate_evm(rx_block, tx_block)
    if evm_unequalized < 0.5:
        return evm_unequalized

    X = np.fft.fft(tx_block)
    Y = np.fft.fft(rx_block)

    # Regularized deconvolution to estimate linear channel transfer function H(f)
    denom = np.abs(X) ** 2
    max_denom = np.max(denom)
    if max_denom < 1e-12:
        return 100.0

    # H(f) = Y(f) * X*(f) / (|X(f)|^2 + reg * max(|X(f)|^2))
    H = (Y * np.conj(X)) / (denom + regularization * max_denom)

    # Apply estimated transfer function H to the transmitter reference signal spectrum
    TX_equalized = np.fft.ifft(X * H)
    tx_eq = np.real(TX_equalized).astype(np.float32)

    # Calculate EVM between received block and equalized reference
    dot_tx_eq = np.dot(tx_eq, tx_eq)
    if dot_tx_eq < 1e-12:
        return 100.0

    # Least squares gain scaling alignment
    scale = np.dot(rx_block, tx_eq) / dot_tx_eq
    error_vector = rx_block - scale * tx_eq
    rms_error = np.sqrt(np.mean(error_vector**2))
    rms_reference = np.sqrt(np.mean(rx_block**2))

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
            "dsp_detected": "None (Transparent)",
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
    scaled_rms = np.sqrt(np.mean(scaled_diff**2))
    ref_rms = np.sqrt(np.mean(ref**2))
    rel_error = scaled_rms / (ref_rms + epsilon)

    tol = 1e-6
    errors = np.sum(np.abs(rx - K * ref) > tol)
    error_rate = errors / N

    # Analyze error structure for DSP heuristics
    rx_scaled = rx / (K + epsilon)

    # 1. Check if 16-bit truncated
    rx_scaled_16 = np.round(rx_scaled * 32768.0) / 32768.0
    if np.max(np.abs(rx_scaled - rx_scaled_16)) < 1e-6:
        reason = (
            "Volume altered, bit depth reduced to 16-bit." if abs(gain_db) > 0.01 else "Bit depth reduced to 16-bit."
        )
        return {
            "bit_perfect": False,
            "reason": reason,
            "gain_db": gain_db,
            "bit_depth": 16,
            "bit_errors": errors,
            "error_rate": error_rate,
            "active_bits": 16,
            "dsp_detected": "Bit Truncation (16-bit)",
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
                "dsp_detected": "Volume/Gain Scaler",
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
            "dsp_detected": "Bit Truncation (8-bit)",
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
            "dsp_detected": "Dither / Noise Shaping",
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
            "dsp_detected": "Resampling / Heavy DSP / Compressor",
        }

    return {
        "bit_perfect": False,
        "reason": "Data modified (unknown DSP processing).",
        "gain_db": gain_db,
        "bit_depth": 24,
        "bit_errors": errors,
        "error_rate": error_rate,
        "active_bits": 24,
        "dsp_detected": "Active EQ/Filter/DSP",
    }


def estimate_fractional_delay(rx_segment: np.ndarray, ref_segment: np.ndarray) -> float:
    """
    Estimates the fractional sample delay between rx and ref using FFT phase slope.
    Assumes they are already roughly aligned to the nearest integer sample.

    Returns: Estimated fractional delay in samples (typically in range [-1.5, 1.5]).
    """
    N = len(rx_segment)
    # Apply Hanning window to mitigate boundary artifacts
    win = np.hanning(N)
    X = np.fft.rfft(ref_segment * win)
    Y = np.fft.rfft(rx_segment * win)

    # Compute cross-spectrum
    Gxy = Y * np.conj(X)
    phases = np.angle(Gxy)

    # Phase shift: phi_k = -2 * pi * k * d / N where d is fractional delay.
    # Linear phase fit over lower 25% of the spectrum (highest SNR, linear phase region)
    max_bin = max(4, len(phases) // 4)
    bins = np.arange(max_bin)

    # Unwrap phases to resolve 2*pi jumps
    unwrapped_phases = np.unwrap(phases[:max_bin])

    # Fit line: phase = slope * bin + intercept
    A = np.vstack([bins, np.ones_like(bins)]).T
    slope, _ = np.linalg.lstsq(A, unwrapped_phases, rcond=None)[0]

    fractional_delay = -slope * N / (2.0 * np.pi)
    return float(np.clip(fractional_delay, -1.5, 1.5))


def shift_signal_fractional(sig: np.ndarray, delay_samples: float) -> np.ndarray:
    """
    Shifts a signal by a fractional number of samples in the frequency domain.
    Acts as a perfect all-pass filter (flat magnitude, linear phase shift).
    """
    N = len(sig)
    X = np.fft.fft(sig)
    freqs = np.fft.fftfreq(N)

    # Phase shift operator: exp(-2 * pi * j * f * d)
    shift_operator = np.exp(-2j * np.pi * freqs * delay_samples)
    sig_shifted = np.fft.ifft(X * shift_operator)
    return np.real(sig_shifted).astype(np.float32)


def track_jitter_fractional(
    rx_block: np.ndarray, tx_history: np.ndarray, last_offset: int, max_search=8
) -> tuple[int, float, float]:
    """
    Refines and tracks synchronization offset changes block-by-block with sub-sample precision.
    Uses a hybrid approach for efficiency:
    1. Standard integer-precision coarse search (time domain).
    2. FFT-based fractional delay estimation and shift on the best candidate.

    Returns: (best_offset, fractional_correlation, fractional_delay)
    """
    # 1. Coarse standard integer search
    best_integer_offset, _ = track_jitter(rx_block, tx_history, last_offset, max_search)

    # 2. Extract corresponding reference segment from history
    N = len(rx_block)
    H = len(tx_history)
    if best_integer_offset + N <= H:
        tx_seg = tx_history[best_integer_offset : best_integer_offset + N]
    else:
        part = H - best_integer_offset
        tx_seg = np.concatenate((tx_history[best_integer_offset:], tx_history[: N - part]))

    # 3. Estimate sub-sample fractional delay
    est_delay = estimate_fractional_delay(rx_block, tx_seg)

    # 4. Shift the reference to physically align phases
    tx_shifted = shift_signal_fractional(tx_seg, est_delay)

    # 5. Compute high-precision pearson correlation
    rx_ac = rx_block - np.mean(rx_block)
    tx_shifted_ac = tx_shifted - np.mean(tx_shifted)

    norm_rx = np.linalg.norm(rx_ac)
    norm_tx = np.linalg.norm(tx_shifted_ac)

    if norm_rx > 1e-6 and norm_tx > 1e-6:
        fractional_corr = np.dot(rx_ac, tx_shifted_ac) / (norm_rx * norm_tx)
    else:
        fractional_corr = 0.0

    return best_integer_offset, float(fractional_corr), float(est_delay)


def apply_octave_smoothing(freqs: np.ndarray, mag_db: np.ndarray, fraction: float) -> np.ndarray:
    """
    Applies fractional octave smoothing (e.g., 1/3, 1/12, 1/24) to a magnitude spectrum in dB.
    Uses variable-width moving average along the frequency axis.
    """
    if fraction <= 0:
        return mag_db

    smoothed = np.zeros_like(mag_db)
    num_points = len(freqs)

    # Octave bandwidth factor: 2^(1 / (2 * fraction))
    factor = 2.0 ** (1.0 / (2.0 * fraction))

    for i in range(num_points):
        f = freqs[i]
        if f <= 0:
            smoothed[i] = mag_db[i]
            continue

        f_min = f / factor
        f_max = f * factor

        # Find indices within [f_min, f_max]
        indices = np.where((freqs >= f_min) & (freqs <= f_max))[0]

        if len(indices) > 0:
            smoothed[i] = np.mean(mag_db[indices])
        else:
            smoothed[i] = mag_db[i]

    return smoothed



def calculate_step_response(impulse_response: np.ndarray) -> np.ndarray:
    """
    インパルス応答 h[t] からステップ応答 (Step Response) を累積積分により高速に算出します。
    """
    if len(impulse_response) == 0:
        return np.array([], dtype=np.float32)

    # np.cumsum は極めて高速（ベクトル化）
    step_resp = np.cumsum(impulse_response)

    # 正規化もしくはスケーリングを行い、インパルス応答と同様のレンジで安定表示できるようにする
    # 直流オフセット（初期値のズレ）を防ぐため、最初の数サンプルの平均値を引いてゼロ基点にする
    warmup = min(10, len(step_resp))
    if warmup > 0:
        step_resp -= np.mean(step_resp[:warmup])

    return step_resp.astype(np.float32)


def analyze_step_transient(step_y: np.ndarray, sr: float) -> dict:
    """
    ステップ応答波形から、オーバーシュート率 (OS%)、セトリングタイム、およびドループ特性を頑健に算出します。
    """
    results = {
        "overshoot_pct": 0.0,
        "settling_samples": 0,
        "settling_ms": 0.0,
        "droop_pct": 0.0,
        "step_gain": 0.0,
        "valid": False
    }

    N = len(step_y)
    if N < 256:
        return results

    # 1. 各種基準値の特定
    # ベースライン V_base: ピーク（128）より前（0〜100）の平均
    v_base = float(np.mean(step_y[:100]))

    # 最終収束値 V_final: 後半（350〜500サンプル）の平均
    v_final = float(np.mean(step_y[350:500]))

    # ステップ全体の高さ
    v_step = v_final - v_base
    v_step_abs = abs(v_step)

    # 閾値保護: ステップ信号が十分に大きくない（または無音）場合は解析不可とする
    if v_step_abs < 0.005:
        return results

    # 2. 立ち上がり開始位置の特定 (v_base + 10% 閾値を超える最初のインデックス)
    v_10 = v_base + 0.10 * v_step
    start_idx = 128
    for idx in range(100, 200):
        if (v_step > 0 and step_y[idx] >= v_10) or (v_step < 0 and step_y[idx] <= v_10):
            start_idx = idx
            break

    # 3. オーバーシュート率 (Overshoot %) の算出
    # 立ち上がり後の最大変位を特定 (極性を考慮)
    if v_step > 0:
        v_max = float(np.max(step_y[start_idx:300]))
        overshoot_val = max(0.0, v_max - v_final)
    else:
        v_min = float(np.min(step_y[start_idx:300]))
        overshoot_val = max(0.0, v_final - v_min)

    overshoot_pct = (overshoot_val / v_step_abs) * 100.0

    # 4. セトリングタイム (Settling Time) の算出
    # 最終値の ±2% 誤差バンドを定義
    tolerance = 0.02 * v_step_abs
    v_upper = v_final + tolerance
    v_lower = v_final - tolerance

    # 末尾から逆向きにスキャンし、許容差バンド外に飛び出している最後の要素を探索
    settling_idx = start_idx
    for idx in range(N - 1, start_idx, -1):
        val = step_y[idx]
        if val > v_upper or val < v_lower:
            settling_idx = idx
            break

    settling_samples = max(0, settling_idx - start_idx)
    settling_ms = (settling_samples / sr) * 1000.0

    # 5. ドループ (Droop %) の算出
    # 立ち上がり直後の安定期 (200) と末尾 (500) の差分から、低域カットオフによる減衰を評価
    v_early = float(np.mean(step_y[200:230]))
    v_late = float(np.mean(step_y[480:510]))

    if v_step > 0:
        droop_val = v_early - v_late
    else:
        droop_val = v_late - v_early

    droop_pct = (droop_val / v_step_abs) * 100.0

    # 負のドループ（極端な上昇など）は測定ノイズとみなして 0.0 以下はクリップ
    droop_pct = max(0.0, droop_pct)

    results.update({
        "overshoot_pct": float(np.clip(overshoot_pct, 0.0, 200.0)),
        "settling_samples": int(settling_samples),
        "settling_ms": float(settling_ms),
        "droop_pct": float(np.clip(droop_pct, 0.0, 100.0)),
        "step_gain": float(v_step),
        "valid": True
    })

    return results


