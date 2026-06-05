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

    # Shift the signal temporarily so that the peak is far away from boundaries (to N_total // 2)
    shift_amount = N_total // 2 - idx_int
    ir_shifted = np.roll(ir, shift_amount)

    idx_int_sh = N_total // 2
    win_size = 32  # Use 32 samples window for high accuracy
    half = win_size // 2
    start = idx_int_sh - half
    end = idx_int_sh + half

    ir_crop = ir_shifted[start:end]
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



def generate_sss_and_inverse(sample_rate, sweep_duration, start_freq, end_freq):
    """
    Generates Synchronized Sine Sweep (SSS) signal at a flat reference amplitude (1.0)
    and its matching analytical inverse filter.
    Normalized such that the peak of their direct convolution is exactly 1.0.
    """
    num_samples = int(sample_rate * sweep_duration)
    t = np.linspace(0, sweep_duration, num_samples, endpoint=False)

    # Add frequency guard bands (margins) to keep the target band flat
    start_margin = max(2.0, start_freq / 1.3)
    nyquist = sample_rate / 2.0
    end_margin = min(nyquist * 0.95, end_freq * 1.15)

    w1 = 2 * np.pi * start_margin
    T = sweep_duration
    L = np.log(end_margin / start_margin)

    # SSS Phase Design
    phase = (w1 * T / L) * (np.exp(t * L / T) - 1)
    sss_signal = 1.0 * np.sin(phase)

    # Tukey window to minimize transient clicks at start and end
    window = windows.tukey(num_samples, alpha=0.02)
    sss_signal *= window

    # Analytical inverse filter (amplitude correction +6dB/octave slope)
    inv_envelope = np.exp(t * L / T)
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
    Uses fft_manager.rfft and irfft.
    """
    N_rec = len(recorded_signal)
    N_sss = len(sss_signal)
    # Next power of 2 for FFT speed
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


def calculate_chebyshev_matrix(num_amplitudes, norm_v, P=5):
    """
    Deprecated/Legacy compatibility method.
    Previously constructed separation matrix M and computed its pseudo-inverse M_pinv.
    Now we implement Chebyshev transform directly using algebraic equations.
    """
    M = np.zeros((num_amplitudes, P))
    for k in range(num_amplitudes):
        v = norm_v[k]
        for p in range(P):
            M[k, p] = v ** (p + 1)
    M_pinv = np.linalg.pinv(M)
    return M, M_pinv


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

    # 0. Systematic Sweep Phase Calibration
    phases_cal_dict = None
    if calibrate_systematic:
        # Generate baseline zero-delay responses using simulated polynomial system
        a_cal = {1: 1.0, 2: 0.1, 3: 0.08, 4: 0.04, 5: 0.02}
        sss_cal, _ = generate_sss_and_inverse(sample_rate, sweep_duration, start_freq, end_freq)

        responses_meas_cal = []
        responses_ref_cal = []

        # Build signals for each scanning amplitude
        for amp in amplitudes:
            x_sig = amp * sss_cal
            y_sig_cal = np.zeros_like(x_sig)
            for p in range(1, P + 1):
                y_sig_cal += a_cal[p] * (x_sig ** p)

            padding = np.zeros(int(0.2 * sample_rate))
            x_sig_padded = np.concatenate([x_sig, padding])
            y_sig_padded = np.concatenate([y_sig_cal, padding])

            ir_ref = deconvolve_signal(x_sig_padded, sss_cal)
            ir_meas = deconvolve_signal(y_sig_padded, sss_cal)

            responses_ref_cal.append(ir_ref)
            responses_meas_cal.append(ir_meas)

        # Call recursively with calibrate_systematic=False
        _, _, phases_cal_dict, _, _ = process_amplitude_responses(
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
        )

    # 0.5. Align all amplitude steps to the baseline step (maximum amplitude) using sub-sample alignment
    aligned_ref = []
    aligned_meas = []
    ref_step_idx = num_amplitudes - 1

    # Choose alignment signal source: Ref channel in XFER mode, Meas channel otherwise
    if input_mode in {"XFER", "XFER_REV"}:
        base_align_sig = responses_ref[ref_step_idx]
    else:
        base_align_sig = responses_meas[ref_step_idx]

    t_ref_base = find_subsample_peak(base_align_sig)

    for j in range(num_amplitudes):
        if input_mode in {"XFER", "XFER_REV"}:
            align_sig = responses_ref[j]
        else:
            align_sig = responses_meas[j]

        t_ref_j = find_subsample_peak(align_sig)
        delay_j = t_ref_j - t_ref_base

        # Apply fractional delay shift in frequency domain (shift back by -delay_j)
        ref_aligned = apply_fractional_delay(responses_ref[j], -delay_j)
        meas_aligned = apply_fractional_delay(responses_meas[j], -delay_j)

        aligned_ref.append(ref_aligned)
        aligned_meas.append(meas_aligned)

    responses_ref = aligned_ref
    responses_meas = aligned_meas

    # 1. Detect Linear IR Peak (t1) using the maximum amplitude measurement
    max_amp_idx = num_amplitudes - 1
    ir_max_meas = responses_meas[max_amp_idx]
    t1 = np.argmax(np.abs(ir_max_meas))


    # 2. Compute Sweep Parameters for delay estimation
    nyquist = sample_rate / 2.0
    end_margin = min(nyquist * 0.95, end_freq * 1.15)
    start_margin = max(2.0, start_freq / 1.3)
    L = sweep_duration / np.log(end_margin / start_margin)

    # 3. Define Gating window length (e.g. 30ms total: 10ms pre, 20ms post to avoid leakage)
    gate_pre = int(0.01 * sample_rate)
    gate_post = int(0.02 * sample_rate)
    N_kernel = gate_pre + gate_post

    # 4. Phase and Fractional Delay correction helper
    def apply_phase_correction_and_frac_delay(g_k, k, frac_delay):
        N = len(g_k)
        G = fft_manager.rfft(g_k)

        # 1. Sweep-specific Phase Correction
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

    # 5. Extraction of harmonic IRs (g_k) for each excitation amplitude
    N_total = len(ir_max_meas)
    g_meas_all = []
    g_ref_all = []

    for j in range(num_amplitudes):
        ir_meas_raw = responses_meas[j]
        ir_ref_raw = responses_ref[j]

        g_meas_j = {}
        g_ref_j = {}

        for k in range(1, P + 1):
            # Calculate peak prediction index with sub-sample precision
            t_k_exact = t1 - L * np.log(k) * sample_rate
            t_k = int(np.round(t_k_exact))
            frac_delay = t_k_exact - t_k

            # Slice with modular wrap around to protect bounds
            idx = (np.arange(t_k - gate_pre, t_k + gate_post)) % N_total

            # Apply cosine taper window to smooth sliced edges
            win = windows.tukey(N_kernel, alpha=0.1)

            g_k_meas = ir_meas_raw[idx] * win
            g_k_ref = ir_ref_raw[idx] * win

            # Phase and fractional delay correction
            g_k_meas_corr = apply_phase_correction_and_frac_delay(g_k_meas, k, frac_delay)
            g_k_ref_corr = apply_phase_correction_and_frac_delay(g_k_ref, k, frac_delay)

            g_meas_j[k] = g_k_meas_corr
            g_ref_j[k] = g_k_ref_corr

        g_meas_all.append(g_meas_j)
        g_ref_all.append(g_ref_j)

    # 6. Apply Chebyshev transform in the FREQUENCY domain
    R_array = np.array(amplitudes)
    R2 = R_array ** 2
    R3 = R_array ** 3
    R4 = R_array ** 4
    R5 = R_array ** 5

    # First, FFT all g_meas and g_ref to the frequency domain.
    # g_meas_all[j][k] has shape (N_kernel,)
    # We compute G_meas[k] of shape (num_amplitudes, N_fft_half)
    N_fft_half = N_kernel // 2 + 1

    G_meas_k = {}
    G_ref_k = {}
    for k in range(1, P + 1):
        G_meas_k[k] = np.array([fft_manager.rfft(g_meas_all[j][k]) for j in range(num_amplitudes)])
        G_ref_k[k] = np.array([fft_manager.rfft(g_ref_all[j][k]) for j in range(num_amplitudes)])

    # Initialize complex H lists
    H_meas_list = np.zeros((P, N_fft_half), dtype=complex)
    H_ref_list = np.zeros((P, N_fft_half), dtype=complex)

    # Meas Channel Least-Squares Estimation in Frequency Domain
    g5_m = G_meas_k.get(5, np.zeros((num_amplitudes, N_fft_half), dtype=complex))
    H_meas_list[4] = 16 * np.sum(g5_m * R5[:, np.newaxis], axis=0) / np.sum(R_array ** 10)

    g4_m = G_meas_k.get(4, np.zeros((num_amplitudes, N_fft_half), dtype=complex))
    H_meas_list[3] = 8 * np.sum(g4_m * R4[:, np.newaxis], axis=0) / np.sum(R_array ** 8)

    g3_m = G_meas_k.get(3, np.zeros((num_amplitudes, N_fft_half), dtype=complex))
    g3_prime_m = g3_m - (5/16) * H_meas_list[4][np.newaxis, :] * R5[:, np.newaxis]
    H_meas_list[2] = 4 * np.sum(g3_prime_m * R3[:, np.newaxis], axis=0) / np.sum(R_array ** 6)

    g2_m = G_meas_k.get(2, np.zeros((num_amplitudes, N_fft_half), dtype=complex))
    g2_prime_m = g2_m - 0.5 * H_meas_list[3][np.newaxis, :] * R4[:, np.newaxis]
    H_meas_list[1] = 2 * np.sum(g2_prime_m * R2[:, np.newaxis], axis=0) / np.sum(R_array ** 4)

    g1_m = G_meas_k.get(1, np.zeros((num_amplitudes, N_fft_half), dtype=complex))
    g1_prime_m = g1_m - 0.75 * H_meas_list[2][np.newaxis, :] * R3[:, np.newaxis] - 0.625 * H_meas_list[4][np.newaxis, :] * R5[:, np.newaxis]
    H_meas_list[0] = np.sum(g1_prime_m * R_array[:, np.newaxis], axis=0) / np.sum(R2)

    # Ref Channel Least-Squares Estimation in Frequency Domain
    g5_r = G_ref_k.get(5, np.zeros((num_amplitudes, N_fft_half), dtype=complex))
    H_ref_list[4] = 16 * np.sum(g5_r * R5[:, np.newaxis], axis=0) / np.sum(R_array ** 10)

    g4_r = G_ref_k.get(4, np.zeros((num_amplitudes, N_fft_half), dtype=complex))
    H_ref_list[3] = 8 * np.sum(g4_r * R4[:, np.newaxis], axis=0) / np.sum(R_array ** 8)

    g3_r = G_ref_k.get(3, np.zeros((num_amplitudes, N_fft_half), dtype=complex))
    g3_prime_r = g3_r - (5/16) * H_ref_list[4][np.newaxis, :] * R5[:, np.newaxis]
    H_ref_list[2] = 4 * np.sum(g3_prime_r * R3[:, np.newaxis], axis=0) / np.sum(R_array ** 6)

    g2_r = G_ref_k.get(2, np.zeros((num_amplitudes, N_fft_half), dtype=complex))
    g2_prime_r = g2_r - 0.5 * H_ref_list[3][np.newaxis, :] * R4[:, np.newaxis]
    H_ref_list[1] = 2 * np.sum(g2_prime_r * R2[:, np.newaxis], axis=0) / np.sum(R_array ** 4)

    g1_r = G_ref_k.get(1, np.zeros((num_amplitudes, N_fft_half), dtype=complex))
    g1_prime_r = g1_r - 0.75 * H_ref_list[2][np.newaxis, :] * R3[:, np.newaxis] - 0.625 * H_ref_list[4][np.newaxis, :] * R5[:, np.newaxis]
    H_ref_list[0] = np.sum(g1_prime_r * R_array[:, np.newaxis], axis=0) / np.sum(R2)

    # Reconstruct Time-Domain Kernels by IFFT for display
    h_kernels_meas = np.array([fft_manager.irfft(H_meas_list[p], n=N_kernel) for p in range(P)])
    h_kernels_ref = np.array([fft_manager.irfft(H_ref_list[p], n=N_kernel) for p in range(P)])

    freqs = fft_manager.rfftfreq(N_kernel, d=1 / sample_rate)
    mask = (freqs >= start_freq) & (freqs <= end_freq)
    valid_freqs = freqs[mask]

    magnitudes_db_dict = {}
    phases_deg_dict = {}

    # Extract the Linear Fundamental Reference for relative XFER calibration
    H_ref_1 = H_ref_list[0]
    ref_power = np.abs(H_ref_1) ** 2
    peak_ref_power = np.max(ref_power)
    alpha = peak_ref_power * 1e-3 + 1e-12

    for p in range(P):
        h_key = f"h{p + 1}"
        H_meas_p = H_meas_list[p]

        if input_mode in {"XFER", "XFER_REV"}:
            # Relative 2-Channel XFER transfer function calibration
            with np.errstate(divide="ignore", invalid="ignore"):
                H_xfer = (H_meas_p * np.conj(H_ref_1)) / (ref_power + alpha)
                H_xfer = np.nan_to_num(H_xfer)
            valid_H = H_xfer[mask]
        else:
            # Single Channel Mode: 1-channel response with latency correction
            valid_H = H_meas_p[mask]
            delay_samples = int(latency_sec * sample_rate)
            phase_correction = 2 * np.pi * valid_freqs * (delay_samples / sample_rate)
            valid_H = valid_H * np.exp(1j * phase_correction)

        # Compute Gain (dB) and Phase (degrees)
        mag_db = 20 * np.log10(np.abs(valid_H) + 1e-12)
        phase_rad = np.unwrap(np.angle(valid_H))
        phase_deg = np.degrees(phase_rad)
        phase_deg = (phase_deg + 180) % 360 - 180

        # Apply systematic sweep phase calibration to remove windowing/FFT latency artifacts
        if phases_cal_dict is not None and h_key in phases_cal_dict:
            phase_deg = phase_deg - phases_cal_dict[h_key]
            phase_deg = (phase_deg + 180) % 360 - 180

        magnitudes_db_dict[h_key] = mag_db
        phases_deg_dict[h_key] = phase_deg

    # 8. Prepare Time-Domain Kernel Display
    # Peak is at gate_pre because we aligned all g_k at that point
    t_indices = np.arange(0, N_kernel)
    time_ms = (t_indices - gate_pre) / sample_rate * 1000.0

    # Return normalized display kernels (referenced to maximum amplitude of linear kernel)
    separated_kernels_data = []
    ref_max = np.max(np.abs(h_kernels_meas[0]))
    for p in range(P):
        kernel_slice = h_kernels_meas[p]
        if ref_max > 1e-12:
            kernel_slice = kernel_slice / ref_max
        separated_kernels_data.append(kernel_slice)

    return (
        valid_freqs,
        magnitudes_db_dict,
        phases_deg_dict,
        time_ms,
        separated_kernels_data,
    )

