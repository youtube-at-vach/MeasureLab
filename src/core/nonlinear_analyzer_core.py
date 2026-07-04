import logging
import numpy as np
from scipy.signal import windows, fftconvolve
from src.core.fft_manager import fft_manager

logger = logging.getLogger(__name__)


def find_subsample_peak(ir):
    """
    Finds the peak index of the impulse response with sub-sample precision
    using FFT-based upsampling (interpolation) around the integer peak.
    Handles circular boundary wrap-around gracefully.
    """
    idx_int = np.argmax(np.abs(ir))
    N_total = len(ir)
    win_size = 32  # Use 32 samples window for high accuracy

    if N_total < win_size:
        return float(idx_int)

    # Shift the signal temporarily so that the peak is far away from boundaries (to N_total // 2)
    shift_amount = N_total // 2 - idx_int
    ir_shifted = np.roll(ir, shift_amount)

    idx_int_sh = N_total // 2
    half = win_size // 2
    start = idx_int_sh - half
    end = idx_int_sh + half

    ir_crop = ir_shifted[start:end].copy()
    win = windows.tukey(len(ir_crop), alpha=0.25)
    ir_crop *= win
    N = len(ir_crop)

    # Standard DFT upsampling by a factor of 100
    upsample_factor = 100
    X = np.fft.fft(ir_crop)

    N_up = N * upsample_factor
    X_up = np.zeros(N_up, dtype=complex)

    # Copy frequencies correctly to center the Nyquist component
    X_up[: N // 2] = X[: N // 2]
    X_up[N // 2] = X[N // 2] / 2.0
    X_up[N_up - N // 2] = X[N // 2] / 2.0
    X_up[N_up - N // 2 + 1 :] = X[N // 2 + 1 :]

    ir_up = np.fft.ifft(X_up) * upsample_factor
    idx_up = np.argmax(np.abs(ir_up))

    peak_shifted = start + (idx_up / upsample_factor)
    peak_original = peak_shifted - shift_amount

    return peak_original % N_total


def apply_fractional_delay(signal, delay_samples):
    """
    Shifts the signal by delay_samples (can be float) in the frequency domain.
    """
    if np.abs(delay_samples) < 1e-9:
        return signal.copy()
    N = len(signal)
    S = fft_manager.rfft(signal)
    freqs = fft_manager.rfftfreq(N, d=1.0)
    phase_shift = np.exp(-1j * 2 * np.pi * freqs * delay_samples)
    S_shifted = S * phase_shift
    return fft_manager.irfft(S_shifted, n=N)


def sinc_resample(signal, drift_factor, win_size=8):
    """
    Resamples a signal to compensate for clock drift using chunked windowed sinc interpolation.
    drift_factor: float (factor > 1 means recorded signal is longer/slower than output)
    """
    N = len(signal)
    t_target = np.arange(N) / drift_factor

    # Process in chunks to limit memory footprint
    chunk_size = 250000
    resampled = np.zeros_like(signal)

    shifts = np.arange(-win_size, win_size)
    kaiser_beta = 5.0

    for start in range(0, N, chunk_size):
        end = min(N, start + chunk_size)
        t_chunk = t_target[start:end]

        idx_nearest = np.round(t_chunk).astype(np.int32)
        idx_nearest = np.clip(idx_nearest, win_size, N - 1 - win_size)

        indices = idx_nearest[np.newaxis, :] + shifts[:, np.newaxis]
        x_subset = signal[indices]

        t_diff = t_chunk[np.newaxis, :] - indices

        # Kaiser-windowed sinc weights
        weights = (
            np.sinc(t_diff)
            * np.i0(kaiser_beta * np.sqrt(np.maximum(0.0, 1.0 - (t_diff / win_size) ** 2)))
            / np.i0(kaiser_beta)
        )

        resampled[start:end] = np.sum(x_subset * weights, axis=0)

    return resampled


def generate_sss_and_inverse(sample_rate, sweep_duration, start_freq, end_freq):
    """
    Generates Synchronized Sine Sweep (SSS) signal and its matching analytical inverse filter
    according to Novak et al. (2015) phase synchronization constraints.
    Includes frequency guard bands (margins) to suppress finite-length Gibbs ripples.
    Normalized such that the peak of their direct convolution is exactly 1.0.
    """
    if sample_rate <= 0:
        raise ValueError("Sample rate must be positive.")
    if sweep_duration <= 0:
        raise ValueError("Sweep duration must be positive.")
    nyquist = sample_rate / 2.0
    if start_freq <= end_freq:
        start_margin = max(2.0, start_freq / 1.3)
        end_margin = min(nyquist * 0.95, end_freq * 1.15)
    else:
        start_margin = min(nyquist * 0.95, start_freq * 1.15)
        end_margin = max(2.0, end_freq / 1.3)

    f1 = float(start_margin)
    f2 = float(end_margin)
    T_tilde = float(sweep_duration)

    if np.abs(f2 - f1) < 1e-3:
        raise ValueError("Start and end frequencies must be different for sweep generation.")

    ln_ratio = np.log(f2 / f1)
    k = int(np.round((f1 / ln_ratio) * T_tilde))
    if k == 0:
        k = -1 if ln_ratio < 0 else 1

    L = k / f1
    T = L * ln_ratio

    num_samples = int(np.round(sample_rate * T))
    t = np.arange(num_samples) / sample_rate

    # Novak's 2015 Phase Design (without the -1 offset term in exp for perfect phase sync)
    phase = 2 * np.pi * k * np.exp(t / L)
    sss_signal = np.sin(phase)

    # Tukey window to minimize transient clicks at start and end (alpha=0.02 exactly as before)
    window = windows.tukey(num_samples, alpha=0.02)
    sss_signal *= window

    # Analytical inverse filter with +3 dB/octave slope (exp(t / 2L))
    inv_envelope = np.exp(t / (2 * L))
    inverse_filter = inv_envelope * np.sin(phase)
    inverse_filter *= window
    inverse_filter = np.flip(inverse_filter)

    # Normalize the inverse filter so that the peak of the direct convolution is exactly 1.0
    direct_conv = fftconvolve(sss_signal, inverse_filter, mode="full")
    peak = np.max(np.abs(direct_conv))
    if peak > 1e-12:
        inverse_filter /= peak

    return sss_signal, inverse_filter


def deconvolve_signal(recorded_signal, sss_signal, regularization=1e-4):
    """
    Performs frequency-domain deconvolution: Y(f) / S(f) with regularization.
    Uses fft_manager.rfft and irfft. This cancels the finite-length sweep spectral ripples.
    """
    N_rec = len(recorded_signal)
    N_sss = len(sss_signal)
    N_fft = int(2 ** np.ceil(np.log2(N_rec + N_sss)))

    S = fft_manager.rfft(np.pad(sss_signal, (0, N_fft - N_sss)))
    Y = fft_manager.rfft(np.pad(recorded_signal, (0, N_fft - N_rec)))

    # Regularization
    S_power = np.abs(S) ** 2
    epsilon = regularization * np.max(S_power) + 1e-12

    # H(f) = Y(f) * S*(f) / (|S(f)|^2 + epsilon)
    H = (Y * np.conj(S)) / (S_power + epsilon)

    g = fft_manager.irfft(H, n=N_fft)
    return g


def process_amplitude_responses(
    responses_meas,
    responses_ref,
    sample_rate,
    start_freq,
    end_freq,
    input_mode,
    latency_sec,
    sweep_duration=1.0,
    P=5,
    M_pinv=None,
    amplitudes=None,
    calibrate_systematic=True,
    is_cal_recursive=False,
    unwrap_phase=False,
):
    """
    Extracts isolated Hammerstein kernels (h_1 to h_5) from deconvolved raw measured and reference
    impulse responses using Chebyshev inversion.

    responses_meas: List of deconvolved impulse responses (time-domain) for each amplitude step.
    responses_ref: List of deconvolved reference impulse responses (time-domain) for each amplitude step.
    amplitudes: Explicit excitation amplitude values (peak linear scaling, e.g. R_j).
    calibrate_systematic: If True, recursively calibrates out systematic sweep phase offsets.
    """
    num_amplitudes = len(responses_meas)
    if amplitudes is None:
        amplitudes = np.linspace(0.2, 1.0, num_amplitudes)

    # 0. Systematic Sweep Calibration (Phase & Amplitude)
    systematic_cal_factors = None
    if calibrate_systematic:
        # Generate baseline zero-delay responses using simulated polynomial system
        a_cal = {1: 1.0, 2: 0.1, 3: 0.08, 4: 0.04, 5: 0.02}
        sss_cal, inv_cal = generate_sss_and_inverse(sample_rate, sweep_duration, start_freq, end_freq)

        responses_meas_cal = []
        responses_ref_cal = []

        # Build signals for each scanning amplitude
        coeffs = [a_cal[p] for p in range(P, 0, -1)] + [0.0]
        for amp in amplitudes:
            x_sig = amp * sss_cal
            y_sig_cal = np.polyval(coeffs, x_sig)

            padding = np.zeros(int(0.2 * sample_rate))
            x_sig_padded = np.concatenate([x_sig, padding])
            y_sig_padded = np.concatenate([y_sig_cal, padding])

            ir_ref = deconvolve_signal(x_sig_padded, sss_cal)
            ir_meas = deconvolve_signal(y_sig_padded, sss_cal)

            responses_ref_cal.append(ir_ref)
            responses_meas_cal.append(ir_meas)

        # Call recursively with calibrate_systematic=False
        _, mags_cal, phases_cal, _, _ = process_amplitude_responses(
            responses_meas_cal,
            responses_ref_cal,
            sample_rate,
            start_freq,
            end_freq,
            input_mode,
            latency_sec,
            sweep_duration=sweep_duration,
            P=P,
            M_pinv=M_pinv,
            amplitudes=amplitudes,
            calibrate_systematic=False,
            is_cal_recursive=True,
        )

        systematic_cal_factors = {}
        for p in range(1, P + 1):
            h_key = f"h{p}"
            if h_key in mags_cal:
                # Reconstruct measured complex response
                mag_meas = 10 ** (mags_cal[h_key] / 20.0)
                phase_meas = np.radians(phases_cal[h_key])
                H_meas_cal = mag_meas * np.exp(1j * phase_meas)

                # Ideal response (pure real number matching the coefficients)
                H_ideal = a_cal[p]

                # Compensation factor
                systematic_cal_factors[h_key] = H_ideal / (H_meas_cal + 1e-12)

        if "ref_phase" in phases_cal:
            systematic_cal_factors["ref_phase"] = phases_cal["ref_phase"]

    # 0.5. Align all amplitude steps to the baseline step (maximum amplitude) using sub-sample alignment
    aligned_ref = []
    aligned_meas = []
    ref_step_idx = num_amplitudes - 1

    # Choose alignment signal source: Ref channel in XFER mode, Meas channel otherwise
    if input_mode in {"XFER", "XFER_REV"}:
        base_align_sig = responses_ref[ref_step_idx]
        t_ref_base = find_subsample_peak(base_align_sig)
    else:
        # For single channel mode, do not align individual steps to prevent
        # non-linear distortion components from affecting peak detection and causing leakage.
        # However, we still find the base peak to know the absolute timing.
        base_align_sig = responses_meas[ref_step_idx]
        t_ref_base = find_subsample_peak(base_align_sig)

    for j in range(num_amplitudes):
        if input_mode in {"XFER", "XFER_REV"}:
            align_sig = responses_ref[j]
            t_ref_j = find_subsample_peak(align_sig)
            delay_j = t_ref_j - t_ref_base
        else:
            delay_j = 0.0

        # Apply fractional delay shift in frequency domain (shift back by -delay_j)
        ref_aligned = apply_fractional_delay(responses_ref[j], -delay_j)
        meas_aligned = apply_fractional_delay(responses_meas[j], -delay_j)

        aligned_ref.append(ref_aligned)
        aligned_meas.append(meas_aligned)

    responses_ref = aligned_ref
    responses_meas = aligned_meas

    # 1. Detect Linear IR Peak using the maximum amplitude measurement
    max_amp_idx = num_amplitudes - 1
    ir_max_meas = responses_meas[max_amp_idx]
    ir_max_ref = responses_ref[max_amp_idx]

    t1_sub_meas = find_subsample_peak(ir_max_meas)
    t1_sub_ref = find_subsample_peak(ir_max_ref)

    # Choose the base peak to align both channels (common slicing)
    if input_mode in {"XFER", "XFER_REV"}:
        t1_base = t1_sub_ref
    else:
        t1_base = t1_sub_meas

    # 2. Compute Sweep Parameters for delay estimation
    nyquist = sample_rate / 2.0
    if start_freq <= end_freq:
        start_margin = max(2.0, start_freq / 1.3)
        end_margin = min(nyquist * 0.95, end_freq * 1.15)
    else:
        start_margin = min(nyquist * 0.95, start_freq * 1.15)
        end_margin = max(2.0, end_freq / 1.3)

    f1 = float(start_margin)
    f2 = float(end_margin)
    T_tilde = float(sweep_duration)

    ln_ratio = np.log(f2 / f1)
    k_param = int(np.round((f1 / ln_ratio) * T_tilde))
    if k_param == 0:
        k_param = -1 if ln_ratio < 0 else 1
    L = k_param / f1

    # 3. Define Gating window length
    gate_pre = int(0.007 * sample_rate)
    gate_post = int(0.013 * sample_rate)
    N_kernel = gate_pre + gate_post

    # 4. Phase and Fractional Delay correction helper
    def apply_phase_correction_and_frac_delay(g_k, k, frac_delay):
        N = len(g_k)
        G = fft_manager.rfft(g_k)

        # 1. Sweep-specific Phase Correction (conjugated for L < 0)
        if L < 0:
            if k == 2:
                G = G * (-1j)
            elif k == 3:
                G = -G
            elif k == 4:
                G = G * 1j
        else:
            if k == 2:
                G = G * 1j
            elif k == 3:
                G = -G
            elif k == 4:
                G = G * (-1j)

        # 2. Fractional Sample Delay Correction (frequency domain shift)
        if np.abs(frac_delay) > 1e-9:
            freqs = fft_manager.rfftfreq(N, d=1.0 / sample_rate)
            # Peak was shifted by frac_delay samples, so multiply by conjugate to shift back
            phase_shift = np.exp(1j * 2 * np.pi * freqs * frac_delay / sample_rate)
            G = G * phase_shift

        return fft_manager.irfft(G, n=N)

    # 5. Extraction of harmonic IRs (g_k) for each excitation amplitude (theoretical gating)
    N_total = len(ir_max_meas)
    g_meas_all = np.empty((num_amplitudes, P, N_kernel))
    g_ref_all = np.empty((num_amplitudes, P, N_kernel))

    for j in range(num_amplitudes):
        ir_meas_raw = responses_meas[j]
        ir_ref_raw = responses_ref[j]

        for k in range(1, P + 1):
            # Calculate peak prediction index based on COMMON baseline
            t_k_exact = t1_base - L * np.log(k) * sample_rate
            t_k = int(np.round(t_k_exact))
            frac_delay = t_k_exact - t_k

            # Slice both channels with identical index (common slicing)
            idx = (np.arange(t_k - gate_pre, t_k + gate_post)) % N_total

            g_k_meas = ir_meas_raw[idx]
            g_k_ref = ir_ref_raw[idx]

            # Phase and fractional delay correction using common frac_delay
            g_k_meas_corr = apply_phase_correction_and_frac_delay(g_k_meas, k, frac_delay)
            g_k_ref_corr = apply_phase_correction_and_frac_delay(g_k_ref, k, frac_delay)

            # Apply Tukey window AFTER fractional delay correction
            win = windows.tukey(N_kernel, alpha=0.1)
            g_meas_all[j, k - 1] = g_k_meas_corr * win
            g_ref_all[j, k - 1] = g_k_ref_corr * win

    # 6. Apply Chebyshev transform in the FREQUENCY domain
    R_array = np.array(amplitudes)
    R2 = R_array**2
    R3 = R_array**3
    R4 = R_array**4
    R5 = R_array**5

    # First, FFT all g_meas and g_ref to the frequency domain
    N_fft_half = N_kernel // 2 + 1

    G_meas_k = {}
    G_ref_k = {}
    for k in range(1, P + 1):
        g_m_k_fft = np.empty((num_amplitudes, N_fft_half), dtype=complex)
        g_r_k_fft = np.empty((num_amplitudes, N_fft_half), dtype=complex)

        for j in range(num_amplitudes):
            g_m_k_fft[j] = fft_manager.rfft(g_meas_all[j, k - 1])
            g_r_k_fft[j] = fft_manager.rfft(g_ref_all[j, k - 1])

        G_meas_k[k] = g_m_k_fft
        G_ref_k[k] = g_r_k_fft

    # Initialize complex H lists
    H_meas_list = np.zeros((P, N_fft_half), dtype=complex)
    H_ref_list = np.zeros((P, N_fft_half), dtype=complex)

    # Meas Channel Least-Squares Estimation in Frequency Domain
    g5_m = G_meas_k.get(5, np.zeros((num_amplitudes, N_fft_half), dtype=complex))
    H_meas_list[4] = 16 * np.sum(g5_m * R5[:, np.newaxis], axis=0) / np.sum(R_array**10)

    g4_m = G_meas_k.get(4, np.zeros((num_amplitudes, N_fft_half), dtype=complex))
    H_meas_list[3] = 8 * np.sum(g4_m * R4[:, np.newaxis], axis=0) / np.sum(R_array**8)

    g3_m = G_meas_k.get(3, np.zeros((num_amplitudes, N_fft_half), dtype=complex))
    g3_prime_m = g3_m - (5 / 16) * H_meas_list[4][np.newaxis, :] * R5[:, np.newaxis]
    H_meas_list[2] = 4 * np.sum(g3_prime_m * R3[:, np.newaxis], axis=0) / np.sum(R_array**6)

    g2_m = G_meas_k.get(2, np.zeros((num_amplitudes, N_fft_half), dtype=complex))
    g2_prime_m = g2_m - 0.5 * H_meas_list[3][np.newaxis, :] * R4[:, np.newaxis]
    H_meas_list[1] = 2 * np.sum(g2_prime_m * R2[:, np.newaxis], axis=0) / np.sum(R_array**4)

    g1_m = G_meas_k.get(1, np.zeros((num_amplitudes, N_fft_half), dtype=complex))
    g1_prime_m = (
        g1_m
        - 0.75 * H_meas_list[2][np.newaxis, :] * R3[:, np.newaxis]
        - 0.625 * H_meas_list[4][np.newaxis, :] * R5[:, np.newaxis]
    )
    H_meas_list[0] = np.sum(g1_prime_m * R_array[:, np.newaxis], axis=0) / np.sum(R2)

    # Ref Channel Least-Squares Estimation in Frequency Domain
    g5_r = G_ref_k.get(5, np.zeros((num_amplitudes, N_fft_half), dtype=complex))
    H_ref_list[4] = 16 * np.sum(g5_r * R5[:, np.newaxis], axis=0) / np.sum(R_array**10)

    g4_r = G_ref_k.get(4, np.zeros((num_amplitudes, N_fft_half), dtype=complex))
    H_ref_list[3] = 8 * np.sum(g4_r * R4[:, np.newaxis], axis=0) / np.sum(R_array**8)

    g3_r = G_ref_k.get(3, np.zeros((num_amplitudes, N_fft_half), dtype=complex))
    g3_prime_r = g3_r - (5 / 16) * H_ref_list[4][np.newaxis, :] * R5[:, np.newaxis]
    H_ref_list[2] = 4 * np.sum(g3_prime_r * R3[:, np.newaxis], axis=0) / np.sum(R_array**6)

    g2_r = G_ref_k.get(2, np.zeros((num_amplitudes, N_fft_half), dtype=complex))
    g2_prime_r = g2_r - 0.5 * H_ref_list[3][np.newaxis, :] * R4[:, np.newaxis]
    H_ref_list[1] = 2 * np.sum(g2_prime_r * R2[:, np.newaxis], axis=0) / np.sum(R_array**4)

    g1_r = G_ref_k.get(1, np.zeros((num_amplitudes, N_fft_half), dtype=complex))
    g1_prime_r = (
        g1_r
        - 0.75 * H_ref_list[2][np.newaxis, :] * R3[:, np.newaxis]
        - 0.625 * H_ref_list[4][np.newaxis, :] * R5[:, np.newaxis]
    )
    H_ref_list[0] = np.sum(g1_prime_r * R_array[:, np.newaxis], axis=0) / np.sum(R2)

    # Reconstruct Time-Domain Kernels by IFFT after calibration
    freqs = fft_manager.rfftfreq(N_kernel, d=1 / sample_rate)
    mask = (freqs >= min(start_freq, end_freq)) & (freqs <= max(start_freq, end_freq))
    valid_freqs = freqs[mask]

    magnitudes_db_dict = {}
    phases_deg_dict = {}

    # Extract the Linear Fundamental Reference for relative XFER calibration
    H_ref_1 = H_ref_list[0]
    ref_power = np.abs(H_ref_1) ** 2
    peak_ref_power = np.max(ref_power)
    alpha = peak_ref_power * 1e-7 + 1e-12

    h_kernels_calibrated = []

    for p in range(P):
        h_key = f"h{p + 1}"
        H_meas_p = H_meas_list[p]

        if input_mode in {"XFER", "XFER_REV"}:
            # Relative 2-Channel XFER transfer function calibration over all frequency bins
            with np.errstate(divide="ignore", invalid="ignore"):
                H_xfer_all = (H_meas_p * np.conj(H_ref_1)) / (ref_power + alpha)
                H_xfer_all = np.nan_to_num(H_xfer_all)

            # Apply gate_pre delay to restore the peak position at t=0 (gate_pre) for display and test alignment
            delay_samples = gate_pre
            phase_shift_gate = np.exp(-1j * 2 * np.pi * freqs * (delay_samples / sample_rate))
            H_xfer_all = H_xfer_all * phase_shift_gate

            # Apply LPF only for time domain kernel (and only for top-level call to prevent recursion issues)
            H_xfer_lpf = H_xfer_all.copy()
            if p >= 1 and not is_cal_recursive:
                f_cut = min(20000.0, 1.15 * sample_rate / (2 * (p + 1)))
                with np.errstate(divide="ignore", invalid="ignore"):
                    H_lpf = 1.0 / np.sqrt(1.0 + (freqs / f_cut) ** 16)
                    H_lpf = np.nan_to_num(H_lpf, nan=0.0, posinf=0.0, neginf=0.0)
                H_xfer_lpf = H_xfer_lpf * H_lpf

            # Keep systematic calibration isolated from h_kernels_calibrated (to preserve physical delays in time-domain)
            h_kernels_calibrated.append(fft_manager.irfft(H_xfer_lpf, n=N_kernel))

            valid_H = H_xfer_all[mask]

            # Apply systematic phase and gain calibration to the frequency response
            if systematic_cal_factors is not None and h_key in systematic_cal_factors:
                valid_H = valid_H * systematic_cal_factors[h_key]

            # Apply LPF to frequency response (only for top-level call)
            if p >= 1 and not is_cal_recursive:
                valid_freqs = freqs[mask]
                f_cut = min(20000.0, 1.15 * sample_rate / (2 * (p + 1)))
                with np.errstate(divide="ignore", invalid="ignore"):
                    valid_H_lpf = 1.0 / np.sqrt(1.0 + (valid_freqs / f_cut) ** 16)
                    valid_H_lpf = np.nan_to_num(valid_H_lpf, nan=0.0, posinf=0.0, neginf=0.0)
                valid_H = valid_H * valid_H_lpf

        else:
            # Single Channel Mode: Apply latency correction to all frequency bins with float precision
            delay_samples = latency_sec * sample_rate
            phase_correction_all = 2 * np.pi * freqs * (delay_samples / sample_rate)
            H_corr_all = H_meas_p * np.exp(1j * phase_correction_all)

            # Apply LPF only for time domain kernel (and only for top-level call)
            H_corr_lpf = H_corr_all.copy()
            if p >= 1 and not is_cal_recursive:
                f_cut = min(20000.0, 1.15 * sample_rate / (2 * (p + 1)))
                with np.errstate(divide="ignore", invalid="ignore"):
                    H_lpf = 1.0 / np.sqrt(1.0 + (freqs / f_cut) ** 16)
                    H_lpf = np.nan_to_num(H_lpf, nan=0.0, posinf=0.0, neginf=0.0)
                H_corr_lpf = H_corr_lpf * H_lpf

            # Keep systematic calibration isolated from h_kernels_calibrated (to preserve physical delays in time-domain)
            h_kernels_calibrated.append(fft_manager.irfft(H_corr_lpf, n=N_kernel))

            valid_H = H_corr_all[mask]

            # Apply systematic phase and gain calibration to the frequency response
            if systematic_cal_factors is not None and h_key in systematic_cal_factors:
                valid_H = valid_H * systematic_cal_factors[h_key]

            # Apply LPF to frequency response (only for top-level call)
            if p >= 1 and not is_cal_recursive:
                valid_freqs = freqs[mask]
                f_cut = min(20000.0, 1.15 * sample_rate / (2 * (p + 1)))
                with np.errstate(divide="ignore", invalid="ignore"):
                    valid_H_lpf = 1.0 / np.sqrt(1.0 + (valid_freqs / f_cut) ** 16)
                    valid_H_lpf = np.nan_to_num(valid_H_lpf, nan=0.0, posinf=0.0, neginf=0.0)
                valid_H = valid_H * valid_H_lpf

        # Compute Gain (dB) and Phase (degrees)
        mag_db = 20 * np.log10(np.abs(valid_H) + 1e-12)
        phase_rad = np.unwrap(np.angle(valid_H))
        phase_deg = np.degrees(phase_rad)
        if not unwrap_phase:
            phase_deg = (phase_deg + 180) % 360 - 180

        magnitudes_db_dict[h_key] = mag_db
        phases_deg_dict[h_key] = phase_deg

    # Also save the reference fundamental phase for loopback phase calibration
    ref_phase_rad = np.unwrap(np.angle(H_ref_1))
    ref_phase_deg = np.degrees(ref_phase_rad)
    if not unwrap_phase:
        ref_phase_deg = (ref_phase_deg + 180) % 360 - 180
    ref_phase_deg_masked = ref_phase_deg[mask]
    if systematic_cal_factors is not None and "ref_phase" in systematic_cal_factors:
        ref_phase_deg_masked = ref_phase_deg_masked - systematic_cal_factors["ref_phase"]
        if not unwrap_phase:
            ref_phase_deg_masked = (ref_phase_deg_masked + 180) % 360 - 180
    phases_deg_dict["ref_phase"] = ref_phase_deg_masked

    # 8. Prepare Time-Domain Kernel Display
    # Peak is at gate_pre because we aligned all g_k at that point
    t_indices = np.arange(0, N_kernel)
    time_ms = (t_indices - gate_pre) / sample_rate * 1000.0

    separated_kernels_data = h_kernels_calibrated

    return (
        valid_freqs,
        magnitudes_db_dict,
        phases_deg_dict,
        time_ms,
        separated_kernels_data,
    )
