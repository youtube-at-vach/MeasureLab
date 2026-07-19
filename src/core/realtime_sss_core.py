import logging
import threading
import numpy as np
from scipy.signal import butter, filtfilt
from scipy.signal.windows import tukey

from src.core.nonlinear_analyzer_core import (
    generate_sss_and_inverse,
    deconvolve_signal,
    find_subsample_peak,
)

logger = logging.getLogger(__name__)


class RealtimeSSSEngine:
    def __init__(
        self,
        sample_rate: float,
        sweep_duration: float,
        start_freq: float,
        end_freq: float,
        output_amplitude: float,
        max_harmonic: int = 5,
        analysis_cycles: float = 12.0,
        num_meas_points: int = 500,
        max_analysis_window: float | None = None,
        max_fitting_samples: int | None = None,
        min_analysis_window: float = 0.012,
        ref_phase_only: bool = False,
    ):
        self.sample_rate = float(sample_rate)
        self.sweep_duration = float(sweep_duration)
        self.start_freq = float(start_freq)
        self.end_freq = float(end_freq)
        self.output_amplitude = float(output_amplitude)
        self.max_harmonic = int(max_harmonic)
        self.analysis_cycles = float(analysis_cycles)
        self.num_meas_points = int(num_meas_points)
        self.min_analysis_window = float(min_analysis_window)
        self.ref_phase_only = bool(ref_phase_only)

        # Derive legacy settings dynamically from analysis_cycles if not provided
        min_freq = min(self.start_freq, self.end_freq)
        if max_analysis_window is not None:
            self.max_analysis_window = float(max_analysis_window)
        else:
            self.max_analysis_window = self.analysis_cycles / (4.0 * max(1.0, min_freq))

        if max_fitting_samples is not None:
            self.max_fitting_samples = int(max_fitting_samples)
        else:
            self.max_fitting_samples = int(np.clip(self.analysis_cycles * 170, 256, 65536))

        self.latency_samples = 0.0

        # Novak SSS Sweep Design parameters
        self.k_param = 0
        self.L_param = 0.0
        self.sweep_samples = 0
        self._out_sig_cached: np.ndarray | None = None

        # Cache for decimation optimization
        self.last_results = [0.0j] * self.max_harmonic
        self.last_quality = 0.0
        self.meas_freqs = np.zeros(0)
        self.next_meas_idx = 0
        self.is_ascending = True

        # Reset engine variables
        self.reset_filter_states()

    def prepare_sweep(self):
        """
        Pre-calculates SSS phase trajectory and output signal using Novak's constraints.
        Using sine excitation (sin(phi(t))) as it is consistent with the offline NonlinearAnalyzer.
        """
        nyquist = self.sample_rate / 2.0
        if self.start_freq <= self.end_freq:
            start_margin = max(2.0, self.start_freq / 1.3)
            end_margin = min(nyquist * 0.95, self.end_freq * 1.15)
            self.is_ascending = True
        else:
            start_margin = min(nyquist * 0.95, self.start_freq * 1.15)
            end_margin = max(2.0, self.end_freq / 1.3)
            self.is_ascending = False

        f1 = float(start_margin)
        f2 = float(end_margin)
        T_tilde = float(self.sweep_duration)

        if np.abs(f2 - f1) < 1e-3:
            raise ValueError("Start and end frequencies must be different.")

        ln_ratio = np.log(f2 / f1)
        k = int(np.round((f1 / ln_ratio) * T_tilde))
        if k == 0:
            k = -1 if ln_ratio < 0 else 1

        self.k_param = k
        self.L_param = k / f1
        T_actual = self.L_param * ln_ratio

        self.sweep_samples = int(np.round(self.sample_rate * T_actual))

        self._out_sig_cached = None

        # Generate logarithmic frequency grid for measurement points
        self.meas_freqs = np.logspace(np.log10(self.start_freq), np.log10(self.end_freq), self.num_meas_points)

        self.reset_filter_states()

    @property
    def out_sig(self) -> np.ndarray | None:
        """
        Returns the full pre-calculated sweep signal.
        For backward compatibility (mostly for tests). Evaluated lazily and cached.
        """
        if self._out_sig_cached is None and self.sweep_samples > 0:
            t = np.arange(self.sweep_samples) / self.sample_rate
            phase = 2.0 * np.pi * self.k_param * np.exp(t / self.L_param)
            sig = self.output_amplitude * np.sin(phase)
            window = tukey(self.sweep_samples, alpha=0.02)
            self._out_sig_cached = sig * window
        return self._out_sig_cached

    def reset_filter_states(self):
        """Resets the state of the analysis history."""
        self.reset_analysis_history()
        self.next_meas_idx = 0
        self.last_results = [0.0j] * self.max_harmonic
        self.last_quality = 0.0
        self.last_block_was_valid = False

    def reset_analysis_history(self):
        """Resets the sample history used by the local least-squares extractor."""
        self._hist_n: list[np.ndarray] = []
        self._hist_theta: list[np.ndarray] = []
        self._hist_signal: list[np.ndarray] = []
        self._hist_ref: list[np.ndarray] = []

    def set_latency(self, latency_samples: float):
        """Sets the physical latency correction value."""
        self.latency_samples = max(0.0, float(latency_samples))

    def _frequency_at_sample(self, sample_index: float) -> float:
        if self.L_param == 0:
            return self.start_freq

        n_eval = float(np.clip(sample_index, 0.0, max(0, self.sweep_samples - 1)))
        if self.start_freq <= self.end_freq:
            f1 = self.start_freq / 1.3
        else:
            f1 = self.start_freq * 1.15
        return float(f1 * np.exp((n_eval / self.sample_rate) / self.L_param))

    def _append_analysis_history(
        self,
        n_comp: np.ndarray,
        theta_comp: np.ndarray,
        signal: np.ndarray,
        ref: np.ndarray | None,
        valid_mask: np.ndarray,
    ):
        valid_indices = np.flatnonzero(valid_mask)
        if len(valid_indices) == 0:
            return

        self._hist_n.append(n_comp[valid_indices].astype(float, copy=True))
        self._hist_theta.append(theta_comp[valid_indices].astype(float, copy=True))
        self._hist_signal.append(signal[valid_indices].astype(float, copy=True))
        if ref is not None:
            self._hist_ref.append(ref[valid_indices].astype(float, copy=True))
        else:
            self._hist_ref.append(np.zeros(len(valid_indices), dtype=float))

        keep_samples = int(
            max(
                self.sample_rate * self.max_analysis_window,
                self.sample_rate * 40.0 / max(1.0, min(self.start_freq, self.end_freq)),
            )
        )
        last_valid_n = self._hist_n[-1][-1]
        while self._hist_n and self._hist_n[0][-1] < last_valid_n - keep_samples:
            self._hist_n.pop(0)
            self._hist_theta.pop(0)
            self._hist_signal.pop(0)
            self._hist_ref.pop(0)

    def _fit_harmonics(
        self, theta: np.ndarray, y: np.ndarray, weights: np.ndarray, active_max_harmonic: int | None = None
    ) -> tuple[list[complex], float]:
        if active_max_harmonic is None:
            active_max_harmonic = self.max_harmonic

        if len(y) < max(8, 3 * (2 * active_max_harmonic + 1)):
            return [0.0j] * self.max_harmonic, 0.0

        N = len(theta)
        p_vals = np.arange(1, active_max_harmonic + 1)
        p_theta = theta[:, None] * p_vals

        design = np.empty((N, 1 + 2 * active_max_harmonic))
        design[:, 0] = 1.0
        design[:, 1::2] = np.cos(p_theta)
        design[:, 2::2] = np.sin(p_theta)

        weighted_design = design * weights[:, None]
        weighted_y = y * weights

        try:
            coeffs, residuals, rank, s = np.linalg.lstsq(weighted_design, weighted_y, rcond=None)
        except np.linalg.LinAlgError:
            return [0.0j] * self.max_harmonic, 0.0

        if residuals.size > 0:
            ss_res = residuals[0]
        else:
            fitted = weighted_design @ coeffs
            ss_res = np.sum((weighted_y - fitted) ** 2)

        ss_tot = np.sum(weighted_y ** 2)
        quality = 1.0 - (ss_res / ss_tot) if ss_tot > 1e-12 else 0.0

        results = [complex(coeffs[1 + 2 * p], -coeffs[2 + 2 * p]) for p in range(active_max_harmonic)]
        if len(results) < self.max_harmonic:
            results.extend([0.0j] * (self.max_harmonic - len(results)))
        return results, quality

    def _execute_ls_fit(self, f_mid: float, has_ref: bool) -> tuple[float, list[complex], float]:
        if not self._hist_n:
            return f_mid, [0.0j] * self.max_harmonic, 0.0

        hist_n = np.concatenate(self._hist_n)
        hist_theta = np.concatenate(self._hist_theta)
        hist_signal = np.concatenate(self._hist_signal)
        hist_ref = np.concatenate(self._hist_ref) if self._hist_ref else None

        last_valid_n = hist_n[-1]
        local_freq = self._frequency_at_sample(last_valid_n)
        window_seconds = np.clip(
            self.analysis_cycles / max(local_freq, 1.0), self.min_analysis_window, self.max_analysis_window
        )
        window_samples = max(256.0, window_seconds * self.sample_rate)
        start_n = last_valid_n - window_samples
        mask = hist_n >= start_n
        if np.count_nonzero(mask) < max(64, 4 * (2 * self.max_harmonic + 1)):
            return f_mid, [0.0j] * self.max_harmonic, 0.0

        theta_win = hist_theta[mask]
        sig_win = hist_signal[mask]
        ref_win = hist_ref[mask] if hist_ref is not None else None

        # Determine decimation factor dynamically
        P = self.max_harmonic
        fs = self.sample_rate
        max_d = int(np.floor(fs / (5.0 * P * max(1.0, local_freq))))

        # Limit fitting sample size to prevent CPU exhaustion on large windows
        needed_d = len(sig_win) // self.max_fitting_samples
        D = int(np.clip(max(needed_d, 1), 1, max(1, max_d)))

        # 1. Bounded check to prevent sample starvation for LS fitting
        min_samples = max(8, 3 * (2 * P + 1))
        if D > 1 and len(sig_win) < D * min_samples:
            D = max(1, len(sig_win) // min_samples)

        if D > 1 and len(sig_win) >= 15:
            # 2. Smooth cutoff frequency independent of discrete step D
            fc = 2.2 * P * max(1.0, local_freq)
            # Cap at 0.45 * fs to prevent Butterworth design errors near Nyquist limit
            fc = min(fc, 0.45 * fs)
            nyq = fs / 2.0

            # Design 4th-order Butterworth LPF
            b, a = butter(4, fc / nyq, btype="low")

            # Apply zero-phase filtering
            sig_win = filtfilt(b, a, sig_win)
            sig_win = sig_win[::D]
            theta_win = theta_win[::D]
            if ref_win is not None:
                ref_win = filtfilt(b, a, ref_win)
                ref_win = ref_win[::D]
        elif D > 1:
            # Fallback if window is too short
            sig_win = sig_win[::D]
            theta_win = theta_win[::D]
            if ref_win is not None:
                ref_win = ref_win[::D]

        # Determine active harmonics to fit below Nyquist margin
        nyquist = fs / 2.0
        limit_freq = 0.9 * nyquist
        active_max_harmonic = P
        for k in range(1, P + 1):
            if k * local_freq > limit_freq:
                active_max_harmonic = k - 1
                break
        active_max_harmonic = max(1, active_max_harmonic)

        weights = np.hanning(len(sig_win))
        if not np.any(weights > 0):
            return f_mid, [0.0j] * self.max_harmonic, 0.0

        sig_results, quality = self._fit_harmonics(theta_win, sig_win, weights, active_max_harmonic)
        result_freq = self._frequency_at_sample(float(np.mean(hist_n[mask])))

        # Apply 90-degree phase correction (multiply by 1j) to match sine excitation
        # and maintain consistency with the IIR DDC demodulator.
        sig_results = [val * 1j for val in sig_results]

        if not has_ref or ref_win is None or len(ref_win) != len(sig_win):
            return result_freq, sig_results, quality

        ref_results, _ = self._fit_harmonics(theta_win, ref_win, weights, active_max_harmonic)
        ref_h1 = ref_results[0] if ref_results else 0.0j
        # Also apply 90-degree phase correction to the reference fundamental
        ref_h1 = ref_h1 * 1j
        ref_mag = np.abs(ref_h1)
        if ref_mag <= 1e-24:
            return result_freq, [0.0j] * self.max_harmonic, 0.0

        ref_u = ref_h1 / ref_mag

        corrected_results = []
        ref_phase_only = getattr(self, "ref_phase_only", False)
        for p, value in enumerate(sig_results):
            k = p + 1
            ref_u_k = ref_u**k
            # Correct the phase rotation of order k using ref_u_k
            # and scale amplitude relative to the fundamental magnitude if not ref_phase_only
            if ref_phase_only:
                corrected = value * np.conj(ref_u_k)
            else:
                corrected = value * np.conj(ref_u_k) / ref_mag
            corrected_results.append(corrected)

        return result_freq, corrected_results, quality

    def _process_block_ls(
        self,
        n_comp: np.ndarray,
        theta_comp: np.ndarray,
        y_raw: np.ndarray,
        f_mid: float,
        valid_mask: np.ndarray,
        ref_in_block: np.ndarray | None,
    ) -> tuple[float, list[complex], float]:
        r_raw = None
        if ref_in_block is not None:
            if ref_in_block.shape[1] >= 1:
                r_raw = ref_in_block[:, 0]
            else:
                r_raw = np.zeros_like(y_raw)

        self._append_analysis_history(n_comp, theta_comp, y_raw, r_raw, valid_mask)
        return self._execute_ls_fit(f_mid, ref_in_block is not None)

    def generate_output_block(self, outdata_block: np.ndarray, block_index: int):
        """
        Generates output sweep signal block and writes it to outdata_block.
        This is a lightweight operation meant to be called directly in the audio callback.
        """
        frames = len(outdata_block)
        fs = self.sample_rate
        start_samp = block_index * frames

        out_samples_written = 0
        if start_samp < self.sweep_samples:
            chunk = min(frames, self.sweep_samples - start_samp)

            # Generate chunk on-the-fly
            t_chunk = np.arange(start_samp, start_samp + chunk) / fs
            phase_chunk = 2.0 * np.pi * self.k_param * np.exp(t_chunk / self.L_param)
            sig_chunk = self.output_amplitude * np.sin(phase_chunk)

            # Apply Tukey window (fade-in / fade-out) on the fly
            alpha = 0.02
            width = int(np.floor(alpha * (self.sweep_samples - 1) / 2.0))
            if width > 0:
                n_global = np.arange(start_samp, start_samp + chunk)
                win_chunk = np.ones(chunk)

                # Fade-in region
                fade_in_mask = n_global < width
                if np.any(fade_in_mask):
                    win_chunk[fade_in_mask] = 0.5 * (1.0 - np.cos(np.pi * n_global[fade_in_mask] / width))

                # Fade-out region
                fade_out_mask = n_global >= (self.sweep_samples - width)
                if np.any(fade_out_mask):
                    n_fade_out = np.clip(n_global[fade_out_mask], 0, self.sweep_samples - 1)
                    win_chunk[fade_out_mask] = 0.5 * (
                        1.0 - np.cos(np.pi * (self.sweep_samples - 1 - n_fade_out) / width)
                    )

                sig_chunk *= win_chunk

            # Copy to all channels
            for ch in range(outdata_block.shape[1]):
                outdata_block[:chunk, ch] = sig_chunk
            out_samples_written = chunk

        # Fill the rest with silence
        if out_samples_written < frames:
            outdata_block[out_samples_written:, :] = 0.0

    def process_input_block(
        self,
        indata_block: np.ndarray,
        block_index: int,
        ref_in_block: np.ndarray | None = None,
    ) -> tuple[float, list[complex], float]:
        """
        Buffers recorded loops and runs lock-in Least-Squares demodulation.
        This can be computationally heavy and is safe to be called in a background thread.
        """
        frames = len(indata_block)
        fs = self.sample_rate
        start_samp = block_index * frames
        end_samp = start_samp + frames

        # Retrieve delay in samples
        d = self.latency_samples

        # Calculate time index for input block (accounting for latency)
        # sample range for this input block is [start_samp, end_samp)
        n_block = np.arange(start_samp, end_samp)
        n_comp = n_block - d  # delay compensated samples

        # Prepare mask for valid sweep samples
        valid_mask = (n_comp >= 0) & (n_comp < self.sweep_samples)

        # Average instantaneous frequency of the block
        n_mid = start_samp + frames / 2.0 - d
        if 0 <= n_mid < self.sweep_samples:
            # f(t) = f1 * exp(t / L)
            f1 = self.start_freq / 1.3 if self.start_freq <= self.end_freq else self.start_freq * 1.15
            f_mid = f1 * np.exp((n_mid / fs) / self.L_param)
        else:
            # Out of bounds fallback
            f_mid = self.start_freq if n_mid < 0 else self.end_freq

        # We demodulate the signal if there is at least one valid sample in this block
        if not np.any(valid_mask):
            self.last_block_was_valid = False
            return f_mid, [0.0j] * self.max_harmonic, 0.0

        # Construct input signal
        if indata_block.shape[1] >= 1:
            y_raw = indata_block[:, 0]
        else:
            y_raw = np.zeros(frames)

        # Calculate phase for delayed time indices
        t_comp = n_comp / fs
        t_eval = np.clip(t_comp, 0.0, (self.sweep_samples - 1.0) / fs)
        theta_comp = 2.0 * np.pi * self.k_param * np.exp(t_eval / self.L_param)

        # Zero out phase for invalid regions
        theta_comp[~valid_mask] = 0.0

        r_raw = None
        if ref_in_block is not None:
            if ref_in_block.shape[1] >= 1:
                r_raw = ref_in_block[:, 0]
            else:
                r_raw = np.zeros_like(y_raw)

        # 1. Append history block-by-block
        self._append_analysis_history(n_comp, theta_comp, y_raw, r_raw, valid_mask)

        # 2. Check if we need to perform LS calculation based on the log grid
        should_calc = False
        if self.next_meas_idx == 0:
            should_calc = True

        while self.next_meas_idx < self.num_meas_points:
            target_f = self.meas_freqs[self.next_meas_idx]
            if (self.is_ascending and f_mid >= target_f) or (not self.is_ascending and f_mid <= target_f):
                should_calc = True
                self.next_meas_idx += 1
            else:
                break

        if should_calc:
            _, results, quality = self._execute_ls_fit(f_mid, ref_in_block is not None)
            self.last_results = results
            self.last_quality = quality

        self.last_block_was_valid = True
        return f_mid, self.last_results, self.last_quality

    def process_block(
        self,
        indata_block: np.ndarray,
        outdata_block: np.ndarray,
        block_index: int,
        ref_in_block: np.ndarray | None = None,
    ):
        """
        Processes a single block of audio (both playing the sweep and analyzing loopback).
        indata_block: Input recorded samples of shape (frames, 1) or (frames, 2)
        outdata_block: Output generator block of shape (frames, ch)
        block_index: Index of the current block in the sweep sequence.
        ref_in_block: Optional reference input block of shape (frames, 1) or (frames, 2)

        Returns:
            f_mid (float): The center instantaneous frequency analyzed in this block.
            results (list of complex): The demodulated response values for orders 1..max_harmonic.
        """
        self.generate_output_block(outdata_block, block_index)
        return self.process_input_block(indata_block, block_index, ref_in_block=ref_in_block)


class LatencyCalibrator:
    def __init__(
        self,
        audio_engine,
        start_freq: float,
        end_freq: float,
        duration: float = 0.25,
        in_ch: int = 0,
        out_ch: int = 0,
    ):
        self.audio_engine = audio_engine
        self.sample_rate = audio_engine.sample_rate
        self.duration = duration
        self.in_ch = in_ch
        self.out_ch = out_ch

        # Generate SSS and inverse filter for delay estimation
        self.sss, self.inv = generate_sss_and_inverse(self.sample_rate, self.duration, start_freq, end_freq)

        # Allocate buffer for recording (add 0.3s margin)
        self.margin_samples = int(0.3 * self.sample_rate)
        self.total_samples = len(self.sss) + self.margin_samples
        self.recorded_data = np.zeros(self.total_samples)

        self.write_pos = 0
        self.read_pos = 0
        self.finished = threading.Event()
        self.callback_id = None
        self.error = None

    def callback(self, indata, outdata, frames, time, status):
        try:
            # Zero out output buffer first to avoid playing back garbage memory/clicks
            outdata.fill(0.0)
            if self.finished.is_set():
                return

            # 1. Playback sweep pulse
            out_samples = min(frames, len(self.sss) - self.write_pos)
            if out_samples > 0:
                sig = self.sss[self.write_pos : self.write_pos + out_samples]
                if self.out_ch == 2:  # Stereo output
                    if outdata.shape[1] >= 2:
                        outdata[:out_samples, 0] = sig
                        outdata[:out_samples, 1] = sig
                elif outdata.shape[1] > self.out_ch:
                    outdata[:out_samples, self.out_ch] = sig
                self.write_pos += out_samples

            # 2. Record loopback input
            in_samples = min(frames, self.total_samples - self.read_pos)
            if in_samples > 0:
                if indata.shape[1] > self.in_ch:
                    self.recorded_data[self.read_pos : self.read_pos + in_samples] = indata[:in_samples, self.in_ch]
                else:
                    self.recorded_data[self.read_pos : self.read_pos + in_samples] = indata[:in_samples, 0]
                self.read_pos += in_samples
                if self.read_pos >= self.total_samples:
                    self.finished.set()
            else:
                self.finished.set()

        except Exception as e:
            self.error = e
            self.finished.set()


def measure_system_latency(
    audio_engine,
    start_freq: float,
    end_freq: float,
    duration: float = 0.25,
    in_ch: int = 0,
    out_ch: int = 0,
) -> float:
    """
    Executes a brief Novak SSS chirp and computes physical round-trip latency via deconvolution and cross-correlation.
    """
    # Clamp start/end frequencies to reasonable limits for calibration sweep duration stability
    calib_start_freq = max(20.0, float(start_freq))
    calib_end_freq = max(100.0, float(end_freq))

    calibrator = LatencyCalibrator(audio_engine, calib_start_freq, calib_end_freq, duration, in_ch, out_ch)

    # Register the ephemeral audio callback
    calibrator.callback_id = audio_engine.register_callback(calibrator.callback)

    # Wait for execution to finish (with 1.5s margin) based on actual sweep length
    actual_duration = calibrator.total_samples / calibrator.sample_rate
    success = calibrator.finished.wait(timeout=actual_duration + 1.5)

    # Unregister callback instantly to free resources
    audio_engine.unregister_callback(calibrator.callback_id)

    if calibrator.error:
        raise calibrator.error

    if not success:
        raise TimeoutError("Latency calibration timed out.")

    # Process recording to find latency
    ir = deconvolve_signal(calibrator.recorded_data, calibrator.sss)
    peak_sample = find_subsample_peak(ir)

    # Ensure the detected peak is physically meaningful (non-negative)
    if peak_sample < 0:
        logger.warning(f"Detected negative latency peak ({peak_sample:.2f} samples). Clamping to 0.")
        peak_sample = 0.0

    return peak_sample
