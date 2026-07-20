import json
import logging
from datetime import datetime
import numpy as np

logger = logging.getLogger(__name__)


def save_hammerstein_model(filepath, data):
    """
    Saves a Hammerstein model to a JSON file.

    data dict structure:
        - metadata (dict): setup parameters
        - time_domain (dict):
            - time_ms (np.ndarray or list)
            - kernels (dict of np.ndarray/list): h1 to h5
        - frequency_domain (dict):
            - freqs (np.ndarray or list)
            - magnitudes_db (dict of np.ndarray/list)
            - phases_deg (dict of np.ndarray/list)
    """
    try:
        # Construct JSON-serializable structure
        serializable_data = {
            "metadata": {
                "format_version": "1.0",
                "export_timestamp": datetime.now().isoformat(),
                **data.get("metadata", {}),
            },
            "time_domain": {
                "time_ms": list(data["time_domain"]["time_ms"]),
                "kernels": {k: list(v) for k, v in data["time_domain"]["kernels"].items()},
            },
            "frequency_domain": {
                "freqs": list(data["frequency_domain"]["freqs"]),
                "magnitudes_db": {k: list(v) for k, v in data["frequency_domain"]["magnitudes_db"].items()},
                "phases_deg": {k: list(v) for k, v in data["frequency_domain"]["phases_deg"].items()},
            },
        }

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(serializable_data, f, indent=2, ensure_ascii=False)
        logger.info("Successfully saved Hammerstein model to %s", filepath)
    except Exception as e:
        logger.error("Failed to save Hammerstein model: %s", e, exc_info=True)
        raise


def load_hammerstein_model(filepath):
    """
    Loads a Hammerstein model from a JSON file and restores arrays to numpy ndarrays.

    Returns:
        dict: The model data structure with np.ndarray objects.
    """
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            raw_data = json.load(f)

        restored_data = {
            "metadata": raw_data.get("metadata", {}),
            "time_domain": {
                "time_ms": np.array(raw_data["time_domain"]["time_ms"], dtype=np.float32),
                "kernels": {k: np.array(v, dtype=np.float32) for k, v in raw_data["time_domain"]["kernels"].items()},
            },
            "frequency_domain": {
                "freqs": np.array(raw_data["frequency_domain"]["freqs"], dtype=np.float32),
                "magnitudes_db": {
                    k: np.array(v, dtype=np.float32) for k, v in raw_data["frequency_domain"]["magnitudes_db"].items()
                },
                "phases_deg": {
                    k: np.array(v, dtype=np.float32) for k, v in raw_data["frequency_domain"]["phases_deg"].items()
                },
            },
        }
        logger.info("Successfully loaded Hammerstein model from %s", filepath)
        return restored_data
    except Exception as e:
        logger.error("Failed to load Hammerstein model: %s", e, exc_info=True)
        raise


# Decoupled active model cache for inter-module communication
class _ActiveModelCache:
    data = None


def set_active_model(data):
    """
    Caches the active Hammerstein model in memory.
    data: dict containing model structure (metadata, time_domain, frequency_domain).
    """
    _ActiveModelCache.data = data


def get_active_model():
    """
    Retrieves the cached active Hammerstein model.
    Returns:
        dict: The model data, or None if no model is cached.
    """
    return _ActiveModelCache.data


def has_active_model():
    """
    Checks if an active Hammerstein model is cached.
    Returns:
        bool: True if cached, False otherwise.
    """
    return _ActiveModelCache.data is not None


def _interpolate_complex_kernel(target_freqs, source_phys_freqs, source_values):
    """
    Interpolates complex values along a logarithmic frequency axis.
    source_phys_freqs and source_values must be sorted by frequency.
    """
    mask = ~np.isnan(source_values)
    if np.sum(mask) < 2:
        return np.zeros_like(target_freqs, dtype=complex)

    xp = source_phys_freqs[mask]
    vals = source_values[mask]

    mags = np.abs(vals)
    phases = np.unwrap(np.angle(vals))

    # Logarithmic frequency interpolation
    log_xp = np.log10(np.maximum(1e-3, xp))
    log_target = np.log10(np.maximum(1e-3, target_freqs))

    # Edge clamping for extrapolation safety
    mag_interp = np.interp(log_target, log_xp, mags, left=mags[0], right=mags[-1])
    phase_interp = np.interp(log_target, log_xp, phases, left=phases[0], right=phases[-1])

    return mag_interp * np.exp(1j * phase_interp)


def estimate_hammerstein_kernels(
    amplitudes,
    avg_responses,
    plot_freqs,
    max_harmonic,
    sample_rate,
    input_mode="XFER",
    ref_phase_only=False,
):
    """
    Estimates the Hammerstein frequency-domain kernels H1..Hp using Parallel Complex Hammerstein method.
    """
    P = max_harmonic
    num_amplitudes = len(amplitudes)
    max_blocks = avg_responses.shape[1]

    valid_idx = np.where(plot_freqs > 0)[0]
    if len(valid_idx) < 2:
        return [np.zeros(max_blocks, dtype=complex) for _ in range(P)], np.zeros(0)

    sort_idx = np.argsort(plot_freqs[valid_idx])
    sorted_freqs = plot_freqs[valid_idx][sort_idx]

    K = num_amplitudes
    J = len(valid_idx)
    g_scaled = np.zeros((K, J, P), dtype=complex)
    phase_corrections = [1.0, 1j, -1.0, -1j, 1.0][:P]
    R_array = amplitudes

    for amp_idx in range(K):
        for p in range(P):
            val = avg_responses[amp_idx, valid_idx, p]
            if input_mode == "XFER" and not ref_phase_only:
                g_scaled[amp_idx, :, p] = val * R_array[amp_idx] * phase_corrections[p]
            else:
                g_scaled[amp_idx, :, p] = val * phase_corrections[p]

    # Pre-sort responses to align with sorted_freqs
    g1 = g_scaled[:, sort_idx, 0]
    g2 = g_scaled[:, sort_idx, 1] if P >= 2 else np.zeros_like(g1)
    g3 = g_scaled[:, sort_idx, 2] if P >= 3 else np.zeros_like(g1)
    g4 = g_scaled[:, sort_idx, 3] if P >= 4 else np.zeros_like(g1)
    g5 = g_scaled[:, sort_idx, 4] if P >= 5 else np.zeros_like(g1)

    R2 = R_array**2
    R3 = R_array**3
    R4 = R_array**4
    R5 = R_array**5

    sum_R10 = np.sum(R_array**10)
    sum_R8 = np.sum(R_array**8)
    sum_R6 = np.sum(R_array**6)
    sum_R4 = np.sum(R_array**4)
    sum_R2 = np.sum(R_array**2)

    # 5th Harmonic -> H5 (measured at 5 * sorted_freqs)
    H5_phys_val = 16.0 * np.sum(g5 * R5[:, np.newaxis], axis=0) / sum_R10 if P >= 5 and sum_R10 > 1e-12 else np.zeros(J, dtype=complex)
    
    # 4th Harmonic -> H4 (measured at 4 * sorted_freqs)
    H4_phys_val = 8.0 * np.sum(g4 * R4[:, np.newaxis], axis=0) / sum_R8 if P >= 4 and sum_R8 > 1e-12 else np.zeros(J, dtype=complex)

    # 3rd Harmonic -> H3 (measured at 3 * sorted_freqs)
    if P >= 5:
        # Interpolate H5(5f) to 3f to subtract from g3(f)
        H5_at_3f = _interpolate_complex_kernel(3.0 * sorted_freqs, 5.0 * sorted_freqs, H5_phys_val)
        g3_prime = g3 - (5.0/16.0) * H5_at_3f[np.newaxis, :] * R5[:, np.newaxis]
    else:
        g3_prime = g3
    H3_phys_val = 4.0 * np.sum(g3_prime * R3[:, np.newaxis], axis=0) / sum_R6 if P >= 3 and sum_R6 > 1e-12 else np.zeros(J, dtype=complex)

    # 2nd Harmonic -> H2 (measured at 2 * sorted_freqs)
    if P >= 4:
        # Interpolate H4(4f) to 2f to subtract from g2(f)
        H4_at_2f = _interpolate_complex_kernel(2.0 * sorted_freqs, 4.0 * sorted_freqs, H4_phys_val)
        g2_prime = g2 - 0.5 * H4_at_2f[np.newaxis, :] * R4[:, np.newaxis]
    else:
        g2_prime = g2
    H2_phys_val = 2.0 * np.sum(g2_prime * R2[:, np.newaxis], axis=0) / sum_R4 if P >= 2 and sum_R4 > 1e-12 else np.zeros(J, dtype=complex)

    # 1st Harmonic -> H1 (measured at sorted_freqs)
    g1_prime = g1.copy()
    if P >= 3:
        # Interpolate H3(3f) to f to subtract from g1(f)
        H3_at_f = _interpolate_complex_kernel(sorted_freqs, 3.0 * sorted_freqs, H3_phys_val)
        g1_prime -= 0.75 * H3_at_f[np.newaxis, :] * R3[:, np.newaxis]
    if P >= 5:
        # Interpolate H5(5f) to f to subtract from g1(f)
        H5_at_f = _interpolate_complex_kernel(sorted_freqs, 5.0 * sorted_freqs, H5_phys_val)
        g1_prime -= 0.625 * H5_at_f[np.newaxis, :] * R5[:, np.newaxis]
    H1_phys_val = np.sum(g1_prime * R_array[:, np.newaxis], axis=0) / sum_R2 if sum_R2 > 1e-12 else np.zeros(J, dtype=complex)

    H_est_list = [H1_phys_val, H2_phys_val, H3_phys_val, H4_phys_val, H5_phys_val][:P]

    # Frequency mapping to target physical grid (sorted_freqs)
    H_mapped_list = []
    for p in range(P):
        H_raw = H_est_list[p]
        # H_raw is estimated at physical frequencies (p+1) * sorted_freqs.
        # We need to map it to target physical frequencies sorted_freqs.
        H_mapped = _interpolate_complex_kernel(
            target_freqs=sorted_freqs,
            source_phys_freqs=(p + 1) * sorted_freqs,
            source_values=H_raw
        )
        H_mapped_list.append(H_mapped)

    # Apply Butterworth LPF
    H_freqs = []
    for p in range(P):
        H_p = H_mapped_list[p]
        if p >= 1:
            f_cut = min(20000.0, 1.15 * sample_rate / 2)
            lpf = 1.0 / np.sqrt(1.0 + (sorted_freqs / f_cut) ** 16)
            H_p = H_p * lpf

        H_freqs.append(H_p)

    return H_freqs, sorted_freqs


def predict_harmonic_response(f0, A_in, H_freqs, sorted_freqs, sample_rate, max_harmonic=5):
    """
    Predicts the harmonic complex responses (Y1..Y5) under the Hammerstein model for a single tone of frequency f0 and amplitude A_in.
    """
    nyquist = sample_rate / 2.0
    H_interp = {}

    for n in range(1, 6):
        f_n = n * f0
        H_interp[n] = {}
        if f_n > nyquist:
            for p in range(1, 6):
                H_interp[n][p] = 0.0 + 0.0j
            continue

        for p in range(1, 6):
            if p <= len(H_freqs):
                H_raw = H_freqs[p - 1]
                mask = ~np.isnan(H_raw)
                if np.sum(mask) > 1:
                    mags = np.abs(H_raw[mask])
                    phases = np.unwrap(np.angle(H_raw[mask]))

                    f_n_clamped = max(1e-3, f_n)
                    sf_clamped = np.maximum(1e-3, sorted_freqs[mask])

                    mag_val = np.interp(np.log10(f_n_clamped), np.log10(sf_clamped), mags, left=0.0, right=0.0)
                    phase_val = np.interp(np.log10(f_n_clamped), np.log10(sf_clamped), phases, left=0.0, right=0.0)

                    H_interp[n][p] = mag_val * np.exp(1j * phase_val)
                else:
                    H_interp[n][p] = 0.0 + 0.0j
            else:
                H_interp[n][p] = 0.0 + 0.0j

    # Predict complex harmonic responses (Y)
    Y = {}
    Y[1] = (1.0) * (A_in * H_interp[1][1] + (0.75 * (A_in**3)) * H_interp[1][3] + (0.625 * (A_in**5)) * H_interp[1][5])
    Y[2] = (-1j) * ((0.5 * (A_in**2)) * H_interp[2][2] + (0.5 * (A_in**4)) * H_interp[2][4])
    Y[3] = (-1.0) * ((0.25 * (A_in**3)) * H_interp[3][3] + (0.3125 * (A_in**5)) * H_interp[3][5])
    Y[4] = (+1j) * ((0.125 * (A_in**4)) * H_interp[4][4])
    Y[5] = (1.0) * ((0.0625 * (A_in**5)) * H_interp[5][5])

    # Convert to relative amplitudes (dBFS) and relative phases (deg) relative to fundamental phase
    pred_fund_phase_rad = np.angle(Y[1])
    predictions = []

    for n in range(1, 6):
        y_val = Y[n]
        pred_amp_db = 20 * np.log10(np.abs(y_val) + 1e-12)
        pred_rel_phase_rad = np.angle(y_val) - n * pred_fund_phase_rad
        pred_rel_phase_deg = np.degrees(pred_rel_phase_rad)
        pred_rel_phase_deg = (pred_rel_phase_deg + 180) % 360 - 180
        predictions.append({"amp_db": pred_amp_db, "phase_deg": pred_rel_phase_deg, "complex": y_val})

    return predictions[:max_harmonic]
