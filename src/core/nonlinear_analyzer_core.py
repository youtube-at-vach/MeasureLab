import logging
import numpy as np
from scipy.signal import windows, fftconvolve
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
    direct_conv = fftconvolve(sss_signal, inverse_filter, mode="full")
    peak = np.max(np.abs(direct_conv))
    if peak > 1e-12:
        inverse_filter /= peak

    return sss_signal, inverse_filter


def calculate_chebyshev_matrix(num_amplitudes, norm_v, P=5):
    """
    Constructs the Power Series separation matrix M and computes its pseudo-inverse M_pinv.
    norm_v represents normalized excitation amplitudes (v_k in range [0.0, 1.0]).
    Using standard Power Series basis (v^p) ensures mathematically perfect, alias-free
    separation of linear, quadratic, cubic, and higher-order Hammerstein branches.
    """
    M = np.zeros((num_amplitudes, P))
    for k in range(num_amplitudes):
        v = norm_v[k]
        for p in range(P):
            M[k, p] = v ** (p + 1)

    # Compute Pseudo-Inverse
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
):
    """
    Extracts isolated Hammerstein kernels (h_1 to h_5) from raw measured and reference
    impulse responses using Chebyshev inversion.
    """
    num_amplitudes = len(responses_meas)
    if M_pinv is None:
        # Fallback to linear spacing v_k
        norm_v = np.linspace(0.2, 1.0, num_amplitudes)
        _, M_pinv = calculate_chebyshev_matrix(num_amplitudes, norm_v, P)

    # 1. Global Peak-Aligned Gating
    # Use the maximum amplitude measurement channel response to locate the global peak.
    max_amp_idx = num_amplitudes - 1
    ir_max_amp = responses_meas[max_amp_idx]
    global_peak = np.argmax(np.abs(ir_max_amp))

    # Dynamically compute gate_pre to include negative latency peaks for all harmonics.
    # The maximum negative delay is for the P-th harmonic: delay = -L * ln(P)
    # L = sweep_duration / ln(end_freq / start_freq)
    # We add 20% margin to ensure full capture.
    nyquist = sample_rate / 2.0
    end_margin = min(nyquist * 0.95, end_freq * 1.15)
    start_margin = max(2.0, start_freq / 1.3)
    L = sweep_duration / np.log(end_margin / start_margin)
    max_lead_sec = L * np.log(P) if P > 1 else 0.0

    gate_pre = int(max(0.01, max_lead_sec * 1.1) * sample_rate)  # at least 10ms pre-gate
    gate_post = int(0.4 * sample_rate)  # 400ms post-gate (to capture decay)

    raw_len = len(ir_max_amp)
    start_gate = max(0, global_peak - gate_pre)
    end_gate = min(raw_len, global_peak + gate_post)
    gate_length = end_gate - start_gate

    # Tukey window to smoothly taper the gated response
    win = windows.tukey(gate_length, alpha=0.05)

    gated_meas = []
    gated_ref = []

    for k in range(num_amplitudes):
        # Slice both channels at the EXACT same time interval
        meas_slice = responses_meas[k][start_gate:end_gate] * win
        ref_slice = responses_ref[k][start_gate:end_gate] * win
        gated_meas.append(meas_slice)
        gated_ref.append(ref_slice)

    # 2. Chebyshev Matrix Separation
    # Solve h_p(t) = M_pinv * g_k(t) at each time step
    h_kernels_meas = np.zeros((P, gate_length))
    h_kernels_ref = np.zeros((P, gate_length))

    for t in range(gate_length):
        g_t_meas = np.array([gated_meas[k][t] for k in range(num_amplitudes)])
        g_t_ref = np.array([gated_ref[k][t] for k in range(num_amplitudes)])

        h_kernels_meas[:, t] = np.dot(M_pinv, g_t_meas)
        h_kernels_ref[:, t] = np.dot(M_pinv, g_t_ref)

    # 3. Frequency Analysis and Relative Normalization
    H_meas_list = [fft_manager.rfft(h_kernels_meas[p]) for p in range(P)]
    H_ref_list = [fft_manager.rfft(h_kernels_ref[p]) for p in range(P)]

    freqs = fft_manager.rfftfreq(gate_length, d=1 / sample_rate)
    mask = (freqs >= start_freq) & (freqs <= end_freq)
    valid_freqs = freqs[mask]

    magnitudes_db_dict = {}
    phases_deg_dict = {}

    # Extract the Linear Fundamental Reference for relative XFER calibration
    H_ref_1 = H_ref_list[0]
    ref_power = np.abs(H_ref_1) ** 2
    peak_ref_power = np.max(ref_power)
    alpha = peak_ref_power * 1e-6 + 1e-12

    for p in range(P):
        h_key = f"h{p + 1}"
        H_meas_p = H_meas_list[p]

        if input_mode == "XFER":
            # Relative 2-Channel XFER transfer function calibration
            # Normalize ALL kernels by the LINEAR reference kernel H_ref_1
            with np.errstate(divide="ignore", invalid="ignore"):
                H_xfer = (H_meas_p * np.conj(H_ref_1)) / (ref_power + alpha)
                H_xfer = np.nan_to_num(H_xfer)
            valid_H = H_xfer[mask]
        else:
            # Single Channel Mode: 1-channel response
            valid_H = H_meas_p[mask]
            # Compensation for physical latency (avoid wrapped phase)
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

    # 4. Prepare Time-Domain Kernel Display
    # Center the display around the linear kernel peak in gated range
    p1_peak = np.argmax(np.abs(h_kernels_meas[0]))
    # For time domain display, we want to show the pre-trigger range capturing the negative latency peaks
    disp_pre = min(p1_peak, int(max(0.01, max_lead_sec * 1.15) * sample_rate))  # covers negative latencies
    disp_post = min(gate_length - p1_peak, int(0.09 * sample_rate))  # 90ms post-peak

    t_indices = np.arange(p1_peak - disp_pre, p1_peak + disp_post)
    time_ms = (t_indices - p1_peak) / sample_rate * 1000.0

    separated_kernels_data = []
    ref_max = np.max(np.abs(h_kernels_meas[0]))

    for p in range(P):
        kernel_slice = h_kernels_meas[p][t_indices]
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
