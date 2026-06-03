import logging
import numpy as np
from scipy.signal import windows
from src.core.fft_manager import fft_manager

logger = logging.getLogger(__name__)


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
    direct_conv = np.convolve(sss_signal, inverse_filter, mode="full")
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
):
    """
    Extracts isolated Hammerstein kernels (h_1 to h_5) from deconvolved raw measured and reference
    impulse responses using Chebyshev inversion.

    responses_meas: List of deconvolved impulse responses (time-domain) for each amplitude step.
    responses_ref: List of deconvolved reference impulse responses (time-domain) for each amplitude step.
    amplitudes: Explicit excitation amplitude values (peak linear scaling, e.g. R_j).
    """
    num_amplitudes = len(responses_meas)
    if amplitudes is None:
        amplitudes = np.linspace(0.2, 1.0, num_amplitudes)

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

    # 4. Phase correction helper for sin sweep phase alignment
    def apply_phase_correction(g_k, k):
        N = len(g_k)
        G = fft_manager.rfft(g_k)
        # Apply shift to make physical impulse responses real and symmetric
        if k == 2:
            G = G * 1j
        elif k == 3:
            G = -G
        elif k == 4:
            G = G * (-1j)
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
            # Calculate peak prediction index for the k-th harmonic
            t_k = int(t1 - L * np.log(k) * sample_rate)

            # Slice with modular wrap around to protect bounds
            idx = (np.arange(t_k - gate_pre, t_k + gate_post)) % N_total

            # Apply cosine taper window to smooth sliced edges
            win = windows.tukey(N_kernel, alpha=0.1)

            g_k_meas = ir_meas_raw[idx] * win
            g_k_ref = ir_ref_raw[idx] * win

            # Phase correction
            g_k_meas_corr = apply_phase_correction(g_k_meas, k)
            g_k_ref_corr = apply_phase_correction(g_k_ref, k)

            g_meas_j[k] = g_k_meas_corr
            g_ref_j[k] = g_k_ref_corr

        g_meas_all.append(g_meas_j)
        g_ref_all.append(g_ref_j)

    # 6. Apply Chebyshev transform to reconstruct Hammerstein kernels h_p using weighted least-squares
    h_kernels_meas = np.zeros((P, N_kernel))
    h_kernels_ref = np.zeros((P, N_kernel))

    R_array = np.array(amplitudes)
    R2 = R_array ** 2
    R3 = R_array ** 3
    R4 = R_array ** 4
    R5 = R_array ** 5

    # Meas Channel Least-Squares Estimation
    g_meas_k = {k: np.array([g_meas_all[j][k] for j in range(num_amplitudes)]) for k in range(1, P + 1)}

    g5_m = g_meas_k.get(5, np.zeros((num_amplitudes, N_kernel)))
    h5_meas = 16 * np.sum(g5_m * R5[:, np.newaxis], axis=0) / np.sum(R_array ** 10)

    g4_m = g_meas_k.get(4, np.zeros((num_amplitudes, N_kernel)))
    h4_meas = 8 * np.sum(g4_m * R4[:, np.newaxis], axis=0) / np.sum(R_array ** 8)

    g3_m = g_meas_k.get(3, np.zeros((num_amplitudes, N_kernel)))
    g3_prime_m = g3_m - (5/16) * h5_meas[np.newaxis, :] * R5[:, np.newaxis]
    h3_meas = 4 * np.sum(g3_prime_m * R3[:, np.newaxis], axis=0) / np.sum(R_array ** 6)

    g2_m = g_meas_k.get(2, np.zeros((num_amplitudes, N_kernel)))
    g2_prime_m = g2_m - 0.5 * h4_meas[np.newaxis, :] * R4[:, np.newaxis]
    h2_meas = 2 * np.sum(g2_prime_m * R2[:, np.newaxis], axis=0) / np.sum(R_array ** 4)

    g1_m = g_meas_k.get(1, np.zeros((num_amplitudes, N_kernel)))
    g1_prime_m = g1_m - 0.75 * h3_meas[np.newaxis, :] * R3[:, np.newaxis] - 0.625 * h5_meas[np.newaxis, :] * R5[:, np.newaxis]
    h1_meas = np.sum(g1_prime_m * R_array[:, np.newaxis], axis=0) / np.sum(R2)

    h_kernels_meas[0] = h1_meas
    h_kernels_meas[1] = h2_meas
    h_kernels_meas[2] = h3_meas
    h_kernels_meas[3] = h4_meas
    h_kernels_meas[4] = h5_meas

    # Ref Channel Least-Squares Estimation
    g_ref_k = {k: np.array([g_ref_all[j][k] for j in range(num_amplitudes)]) for k in range(1, P + 1)}

    g5_r = g_ref_k.get(5, np.zeros((num_amplitudes, N_kernel)))
    h5_ref = 16 * np.sum(g5_r * R5[:, np.newaxis], axis=0) / np.sum(R_array ** 10)

    g4_r = g_ref_k.get(4, np.zeros((num_amplitudes, N_kernel)))
    h4_ref = 8 * np.sum(g4_r * R4[:, np.newaxis], axis=0) / np.sum(R_array ** 8)

    g3_r = g_ref_k.get(3, np.zeros((num_amplitudes, N_kernel)))
    g3_prime_r = g3_r - (5/16) * h5_ref[np.newaxis, :] * R5[:, np.newaxis]
    h3_ref = 4 * np.sum(g3_prime_r * R3[:, np.newaxis], axis=0) / np.sum(R_array ** 6)

    g2_r = g_ref_k.get(2, np.zeros((num_amplitudes, N_kernel)))
    g2_prime_r = g2_r - 0.5 * h4_ref[np.newaxis, :] * R4[:, np.newaxis]
    h2_ref = 2 * np.sum(g2_prime_r * R2[:, np.newaxis], axis=0) / np.sum(R_array ** 4)

    g1_r = g_ref_k.get(1, np.zeros((num_amplitudes, N_kernel)))
    g1_prime_r = g1_r - 0.75 * h3_ref[np.newaxis, :] * R3[:, np.newaxis] - 0.625 * h5_ref[np.newaxis, :] * R5[:, np.newaxis]
    h1_ref = np.sum(g1_prime_r * R_array[:, np.newaxis], axis=0) / np.sum(R2)

    h_kernels_ref[0] = h1_ref
    h_kernels_ref[1] = h2_ref
    h_kernels_ref[2] = h3_ref
    h_kernels_ref[3] = h4_ref
    h_kernels_ref[4] = h5_ref

    # 7. Frequency Analysis and Relative Normalization
    H_meas_list = [fft_manager.rfft(h_kernels_meas[p]) for p in range(P)]
    H_ref_list = [fft_manager.rfft(h_kernels_ref[p]) for p in range(P)]

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

        if input_mode == "XFER":
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

