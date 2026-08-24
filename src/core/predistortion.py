import logging
from typing import Optional
import numpy as np
from scipy.interpolate import PchipInterpolator
from scipy.signal.windows import tukey

logger = logging.getLogger(__name__)


def pchip_complex_interpolate(freqs_in: np.ndarray, C_p_in: np.ndarray, freqs_target: np.ndarray) -> np.ndarray:
    """
    Safely interpolates complex transfer functions smoothly using PchipInterpolator.
    Handles zero-initializations, avoids -inf in log-magnitude, and prevents
    exponential overflow out-of-bounds extrapolation.
    """
    freqs_target_safe = np.clip(freqs_target, freqs_in[0], freqs_in[-1])

    mag_in = np.abs(C_p_in)
    if np.all(mag_in < 1e-13):
        return np.zeros_like(freqs_target, dtype=complex)

    mag_clipped = np.maximum(mag_in, 1e-12)
    mag_log = np.log(mag_clipped)

    phase_in = np.angle(C_p_in)
    phase_in[mag_in < 1e-10] = 0.0
    phase_unwrapped = np.unwrap(phase_in)

    f_mag = PchipInterpolator(freqs_in, mag_log)
    f_phase = PchipInterpolator(freqs_in, phase_unwrapped)

    interp_log_mag = np.clip(f_mag(freqs_target_safe), -27.6, 5.0)
    mag_interp = np.exp(interp_log_mag)
    mag_interp[interp_log_mag <= -27.0] = 0.0

    phase_interp = f_phase(freqs_target_safe)

    return mag_interp * np.exp(1j * phase_interp)


def smooth_complex_vector(vec: np.ndarray, window_size: int = 5) -> np.ndarray:
    """Smooths a complex vector using a Hanning window along the frequency axis."""
    if len(vec) < window_size or window_size < 2:
        return vec
    win = np.hanning(window_size)
    win /= np.sum(win)

    pad_len = window_size // 2
    padded_real = np.pad(vec.real, pad_len, mode="edge")
    padded_imag = np.pad(vec.imag, pad_len, mode="edge")

    smooth_real = np.convolve(padded_real, win, mode="valid")
    smooth_imag = np.convolve(padded_imag, win, mode="valid")

    return smooth_real[: len(vec)] + 1j * smooth_imag[: len(vec)]


class PredistortionManager:
    def __init__(
        self,
        start_freq: float,
        end_freq: float,
        meas_freqs: np.ndarray,
        max_harmonic: int = 5,
        algorithm: str = "secant",
        mu_decay: float = 0.92,
    ):
        self.start_freq = float(start_freq)
        self.end_freq = float(end_freq)
        self.meas_freqs = np.asarray(meas_freqs, dtype=float)
        self.max_harmonic = int(max_harmonic)
        self.algorithm = algorithm
        self.mu_decay = float(mu_decay)

        # Initialize correction envelopes F_corr for each harmonic (2 to max_harmonic)
        self.F_corr = {n: np.zeros(len(self.meas_freqs), dtype=complex) for n in range(2, self.max_harmonic + 1)}
        self.H0_1: Optional[np.ndarray] = None  # Initial fundamental linear response

        # History tracking for Secant / Quasi-Newton algorithms
        self.F_history: dict[int, list] = {n: [] for n in range(2, self.max_harmonic + 1)}
        self.H_history: dict[int, list] = {n: [] for n in range(2, self.max_harmonic + 1)}

    def reset(self):
        """Resets correction envelopes and history."""
        self.F_corr = {n: np.zeros(len(self.meas_freqs), dtype=complex) for n in range(2, self.max_harmonic + 1)}
        self.H0_1 = None
        self.F_history = {n: [] for n in range(2, self.max_harmonic + 1)}
        self.H_history = {n: [] for n in range(2, self.max_harmonic + 1)}

    def generate_predistorted_block(
        self,
        block_idx: int,
        frames: int,
        sample_rate: float,
        sweep_samples: int,
        k_param: float,
        L_param: float,
        amplitude: float,
        generate_ref: bool = False,
    ) -> tuple[np.ndarray, Optional[np.ndarray]]:
        """
        Generates a single block of the predistorted excitation sweep signal on-the-fly.
        Optionally returns the clean fundamental reference sweep block as well.
        """
        start_samp = block_idx * frames
        if start_samp >= sweep_samples:
            empty = np.zeros(frames)
            return empty, (empty.copy() if generate_ref else None)

        chunk = min(frames, sweep_samples - start_samp)
        t_chunk = np.arange(start_samp, start_samp + chunk) / sample_rate
        phase_chunk = 2.0 * np.pi * k_param * np.exp(t_chunk / L_param)

        # Instantaneous frequency trajectory for this block
        if self.start_freq <= self.end_freq:
            f1 = self.start_freq / 1.3
        else:
            f1 = self.start_freq * 1.15
        f_inst = f1 * np.exp(t_chunk / L_param)

        x_base = np.sin(phase_chunk)

        # On-the-fly Tukey window chunk calculation matching Novak SSS design
        alpha = 0.02
        width = int(np.floor(alpha * (sweep_samples - 1) / 2.0))
        win_chunk = np.ones(chunk)
        if width > 0:
            n_global = np.arange(start_samp, start_samp + chunk)
            fade_in_mask = n_global < width
            if np.any(fade_in_mask):
                win_chunk[fade_in_mask] = 0.5 * (1.0 - np.cos(np.pi * n_global[fade_in_mask] / width))
            fade_out_mask = n_global >= (sweep_samples - width)
            if np.any(fade_out_mask):
                n_fade_out = np.clip(n_global[fade_out_mask], 0, sweep_samples - 1)
                win_chunk[fade_out_mask] = 0.5 * (1.0 - np.cos(np.pi * (sweep_samples - 1 - n_fade_out) / width))

        x_corr = x_base.copy()

        for n in range(2, self.max_harmonic + 1):
            if n not in self.F_corr:
                continue
            F_inst_vals = pchip_complex_interpolate(self.meas_freqs, self.F_corr[n], f_inst)

            mag_vals = np.abs(F_inst_vals)
            phase_vals = np.angle(F_inst_vals)
            x_corr += mag_vals * np.sin(n * phase_chunk + phase_vals)

        sig_chunk = x_corr * amplitude * win_chunk
        ref_chunk = x_base * amplitude * win_chunk if generate_ref else None

        if chunk < frames:
            res_sig = np.zeros(frames)
            res_sig[:chunk] = sig_chunk
            if generate_ref and ref_chunk is not None:
                res_ref = np.zeros(frames)
                res_ref[:chunk] = ref_chunk
                return res_sig, res_ref
            return res_sig, None
        return sig_chunk, ref_chunk

    def generate_predistorted_sweep(
        self, sample_rate: float, sweep_samples: int, k_param: float, L_param: float, amplitude: float
    ) -> tuple[np.ndarray, np.ndarray]:
        """
        Generates the full predistorted excitation sweep signal and base reference signal.
        For offline testing and verification.
        """
        t = np.arange(sweep_samples) / sample_rate
        phase = 2.0 * np.pi * k_param * np.exp(t / L_param)

        if self.start_freq <= self.end_freq:
            f1 = self.start_freq / 1.3
        else:
            f1 = self.start_freq * 1.15
        f_inst = f1 * np.exp(t / L_param)

        x_base = np.sin(phase)
        win = tukey(sweep_samples, alpha=0.02)

        x_corr = x_base.copy()

        for n in range(2, self.max_harmonic + 1):
            if n not in self.F_corr:
                continue
            F_inst_vals = pchip_complex_interpolate(self.meas_freqs, self.F_corr[n], f_inst)
            mag_vals = np.abs(F_inst_vals)
            phase_vals = np.angle(F_inst_vals)
            x_corr += mag_vals * np.sin(n * phase + phase_vals)

        return x_corr * amplitude * win, x_base * amplitude * win

    def update_correction(
        self,
        iteration: int,
        x_data: np.ndarray,
        raw_results: np.ndarray,
        block_counts: np.ndarray,
        mu: float,
        algorithm: Optional[str] = None,
        quality_data: Optional[np.ndarray] = None,
        min_quality: float = 0.3,
    ) -> dict[int, np.ndarray]:
        """
        Updates the predistortion correction envelopes F_corr based on measurement results.

        raw_results: shape (num_blocks, max_harmonic), complex values
        block_counts: shape (num_blocks,), int values
        quality_data: optional shape (num_blocks,), float values (e.g. R² per block).
            When provided, only blocks with quality >= min_quality are used.
        min_quality: minimum quality threshold for including a block (default 0.3).
        Returns: H_meas dict mapping harmonic order n -> complex response array
        """
        algo = algorithm or self.algorithm
        valid_indices = np.where(block_counts > 0)[0]
        if quality_data is not None and len(valid_indices) > 0:
            quality_mask = quality_data[valid_indices] >= min_quality
            valid_indices = valid_indices[quality_mask]
        if len(valid_indices) < 2:
            logger.warning("Too few valid measurement points for predistortion update.")
            return {}

        x_data_valid = x_data[valid_indices]
        sort_idx = np.argsort(x_data_valid)
        x_data_sorted = x_data_valid[sort_idx]

        H_meas = {}
        for n in range(1, self.max_harmonic + 1):
            raw_n = raw_results[valid_indices, n - 1] / block_counts[valid_indices]
            raw_n_sorted = raw_n[sort_idx]
            H_meas[n] = pchip_complex_interpolate(x_data_sorted, raw_n_sorted, self.meas_freqs)

        if iteration == 0:
            self.H0_1 = H_meas[1].copy()

        if self.H0_1 is None:
            logger.warning("Base linear response H0_1 is not initialized.")
            return H_meas

        assert self.H0_1 is not None  # checked above
        H0_1 = self.H0_1

        def get_H0_1_interpolated(f_target_array: np.ndarray) -> np.ndarray:
            h_vals = pchip_complex_interpolate(self.meas_freqs, H0_1, f_target_array)
            mag = np.abs(h_vals)
            min_mag = 1e-4 * np.max(np.abs(H0_1))
            bad_mask = mag < min_mag
            if np.any(bad_mask):
                h_vals[bad_mask] = (h_vals[bad_mask] / (mag[bad_mask] + 1e-12)) * min_mag
            return h_vals

        # Fade-out factor for low frequencies to prevent low-frequency measurement leakage divergence
        fade_factors = np.ones_like(self.meas_freqs)
        low_cutoff = 40.0
        low_transition = 200.0
        fade_mask = self.meas_freqs < low_transition
        if np.any(fade_mask):
            fade_factors[fade_mask] = np.clip(
                (self.meas_freqs[fade_mask] - low_cutoff) / (low_transition - low_cutoff), 0.0, 1.0
            )

        current_mu = mu * (self.mu_decay**iteration) if algo == "baseline" else mu
        logger.info(
            "Updating predistortion correction for iteration %d (algo='%s', learning rate mu=%.4f):",
            iteration,
            algo,
            current_mu,
        )

        for n in range(2, self.max_harmonic + 1):
            Hn_vals = H_meas[n]
            F_prev = self.F_corr[n].copy()

            self.F_history[n].append(F_prev)
            self.H_history[n].append(Hn_vals.copy())

            H1_nf_vals = get_H0_1_interpolated(n * self.meas_freqs)

            if algo == "baseline":
                delta_corr = -Hn_vals / H1_nf_vals
                delta_corr = smooth_complex_vector(delta_corr, window_size=5)
                self.F_corr[n] += current_mu * delta_corr * fade_factors

            elif algo in ["newton", "newton_lm"]:
                h1_mag_sq = np.abs(H1_nf_vals) ** 2
                lambda_lm = 1e-4 * np.max(h1_mag_sq) + 1e-12
                delta_corr = -(Hn_vals * np.conj(H1_nf_vals)) / (h1_mag_sq + lambda_lm)
                delta_corr = smooth_complex_vector(delta_corr, window_size=5)
                self.F_corr[n] += current_mu * delta_corr * fade_factors

            elif algo in ["secant", "quasi_newton"]:
                if iteration == 0 or len(self.F_history[n]) < 2:
                    h1_mag_sq = np.abs(H1_nf_vals) ** 2
                    lambda_lm = 1e-4 * np.max(h1_mag_sq) + 1e-12
                    delta_corr = -(Hn_vals * np.conj(H1_nf_vals)) / (h1_mag_sq + lambda_lm)
                else:
                    dF = self.F_history[n][-1] - self.F_history[n][-2]
                    dH = self.H_history[n][-1] - self.H_history[n][-2]

                    dF_mag = np.abs(dF)
                    valid_mask = dF_mag > 1e-10
                    J_emp = np.where(valid_mask, dH / np.where(valid_mask, dF, 1.0), H1_nf_vals)

                    j_mag = np.abs(J_emp)
                    bad_j = (j_mag < 1e-4 * np.max(np.abs(H1_nf_vals))) | np.isnan(j_mag)
                    J_emp[bad_j] = H1_nf_vals[bad_j]

                    j_mag_sq = np.abs(J_emp) ** 2
                    lambda_lm = 1e-4 * np.max(j_mag_sq) + 1e-12
                    delta_corr = -(Hn_vals * np.conj(J_emp)) / (j_mag_sq + lambda_lm)

                delta_corr = smooth_complex_vector(delta_corr, window_size=5)
                self.F_corr[n] += current_mu * delta_corr * fade_factors

            avg_dist = 20 * np.log10(np.mean(np.abs(Hn_vals)) + 1e-12)
            logger.info("  - H%d average distortion level: %.1f dB", n, avg_dist)

        return H_meas

    def restore_true_response(
        self,
        harmonic_order: int,
        target_freqs: np.ndarray,
        measured_complex: np.ndarray,
        H1_base: np.ndarray,
        freq_base: np.ndarray,
    ) -> np.ndarray:
        """Subtracts the predistortion filter contribution from the measured response to restore the device's true nonlinear response."""
        n = harmonic_order
        if n < 2 or n not in self.F_corr:
            return measured_complex

        F_corr_x = pchip_complex_interpolate(self.meas_freqs, self.F_corr[n], target_freqs)

        if len(freq_base) >= 2:
            H1_nf = pchip_complex_interpolate(freq_base, H1_base, n * target_freqs)
        else:
            H1_nf = np.zeros_like(target_freqs, dtype=complex)

        return measured_complex - F_corr_x * H1_nf

    def get_counter_models(self) -> dict:
        """
        Returns the counter-distortion models (complex correction envelopes F_corr and frequency grid)
        for downstream counter model construction.
        """
        return {
            "meas_freqs": self.meas_freqs.copy(),
            "max_harmonic": self.max_harmonic,
            "F_corr": {n: vec.copy() for n, vec in self.F_corr.items()},
            "H0_1": self.H0_1.copy() if self.H0_1 is not None else None,
        }
