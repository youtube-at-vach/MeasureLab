import logging
from typing import Optional
import numpy as np
from scipy.interpolate import interp1d
from scipy.signal.windows import tukey

logger = logging.getLogger(__name__)


class PredistortionManager:
    def __init__(self, start_freq: float, end_freq: float, meas_freqs: np.ndarray, max_harmonic: int = 5):
        self.start_freq = start_freq
        self.end_freq = end_freq
        self.meas_freqs = meas_freqs
        self.max_harmonic = max_harmonic

        # Initialize correction envelopes F_corr for each harmonic (2 to max_harmonic)
        # Key: harmonic order (int), Value: complex array of size len(meas_freqs)
        self.F_corr = {n: np.zeros(len(meas_freqs), dtype=complex) for n in range(2, max_harmonic + 1)}
        self.H0_1: Optional[np.ndarray] = None  # To store the initial fundamental linear response

    def generate_predistorted_sweep(
        self, sample_rate: float, sweep_samples: int, k_param: float, L_param: float, amplitude: float
    ) -> np.ndarray:
        """Generates the predistorted excitation sweep signal.

        x_corr(t) = x_base(t) + sum |F_corr_n| * sin(n*phase + angle(F_corr_n))
        """
        t = np.arange(sweep_samples) / sample_rate
        phase = 2.0 * np.pi * k_param * np.exp(t / L_param)

        # Calculate instantaneous frequency trajectory
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
            F_func_real = interp1d(self.meas_freqs, self.F_corr[n].real, kind="linear", fill_value="extrapolate")
            F_func_imag = interp1d(self.meas_freqs, self.F_corr[n].imag, kind="linear", fill_value="extrapolate")
            F_inst_vals = F_func_real(f_inst) + 1j * F_func_imag(f_inst)

            mag_vals = np.abs(F_inst_vals)
            phase_vals = np.angle(F_inst_vals)
            x_corr += mag_vals * np.sin(n * phase + phase_vals)

        return x_corr * amplitude * win

    def update_correction(
        self, iteration: int, x_data: np.ndarray, raw_results: np.ndarray, block_counts: np.ndarray, mu: float
    ):
        """Updates the predistortion correction envelopes F_corr based on measurement results.

        raw_results: shape (num_blocks, max_harmonic), complex values
        block_counts: shape (num_blocks,), int values
        """
        valid_indices = np.where(block_counts > 0)[0]
        if len(valid_indices) < 2:
            logger.warning("Too few valid measurement points for predistortion update.")
            return

        x_data_valid = x_data[valid_indices]
        sort_idx = np.argsort(x_data_valid)
        x_data_sorted = x_data_valid[sort_idx]

        H_meas = {}
        for n in range(1, self.max_harmonic + 1):
            raw_n = raw_results[valid_indices, n - 1] / block_counts[valid_indices]
            raw_n_sorted = raw_n[sort_idx]

            real_func = interp1d(x_data_sorted, raw_n_sorted.real, kind="linear", fill_value="extrapolate")
            imag_func = interp1d(x_data_sorted, raw_n_sorted.imag, kind="linear", fill_value="extrapolate")
            H_meas[n] = real_func(self.meas_freqs) + 1j * imag_func(self.meas_freqs)

        if iteration == 0:
            self.H0_1 = H_meas[1].copy()

        if self.H0_1 is None:
            logger.warning("Base linear response H0_1 is not initialized.")
            return

        def get_H0_1_interpolated(f_target_array):
            H_func_real = interp1d(self.meas_freqs, self.H0_1.real, kind="linear", fill_value="extrapolate")
            H_func_imag = interp1d(self.meas_freqs, self.H0_1.imag, kind="linear", fill_value="extrapolate")
            h_vals = H_func_real(f_target_array) + 1j * H_func_imag(f_target_array)
            mag = np.abs(h_vals)
            min_mag = 1e-4 * np.max(np.abs(self.H0_1))
            bad_mask = mag < min_mag
            if np.any(bad_mask):
                h_vals[bad_mask] = (h_vals[bad_mask] / (mag[bad_mask] + 1e-12)) * min_mag
            return h_vals

        # Create low-frequency fade-out factor to prevent instability/divergence from low-frequency measurement leakage
        fade_factors = np.ones_like(self.meas_freqs)
        low_cutoff = 40.0
        low_transition = 80.0
        fade_mask = self.meas_freqs < low_transition
        if np.any(fade_mask):
            fade_factors[fade_mask] = np.clip(
                (self.meas_freqs[fade_mask] - low_cutoff) / (low_transition - low_cutoff), 0.0, 1.0
            )

        logger.info("Updating predistortion correction for iteration %d (learning rate mu=%.2f):", iteration, mu)
        for n in range(2, self.max_harmonic + 1):
            Hn_vals = H_meas[n]
            H1_nf_vals = get_H0_1_interpolated(n * self.meas_freqs)
            delta_corr = -Hn_vals / H1_nf_vals
            self.F_corr[n] += mu * delta_corr * fade_factors
            avg_dist = 20 * np.log10(np.mean(np.abs(Hn_vals)) + 1e-12)
            avg_residual = 20 * np.log10(np.mean(np.abs(delta_corr)) + 1e-12)
            logger.info(
                "  - H%d average distortion level: %.1f dB, residual: %.1f dB",
                n,
                avg_dist,
                avg_residual,
            )

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

        # Interpolate F_corr[n] at target_freqs
        F_func_real = interp1d(self.meas_freqs, self.F_corr[n].real, kind="linear", fill_value="extrapolate")
        F_func_imag = interp1d(self.meas_freqs, self.F_corr[n].imag, kind="linear", fill_value="extrapolate")
        F_corr_x = F_func_real(target_freqs) + 1j * F_func_imag(target_freqs)

        # Interpolate H1_base at n * target_freqs
        if len(freq_base) >= 2:
            H1_func_real = interp1d(freq_base, H1_base.real, kind="linear", fill_value="extrapolate")
            H1_func_imag = interp1d(freq_base, H1_base.imag, kind="linear", fill_value="extrapolate")
            H1_nf = H1_func_real(n * target_freqs) + 1j * H1_func_imag(n * target_freqs)
        else:
            H1_nf = np.zeros_like(target_freqs, dtype=complex)

        return measured_complex - F_corr_x * H1_nf
