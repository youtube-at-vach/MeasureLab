import logging
import threading
import numpy as np
import scipy.signal

from src.core.nonlinear_analyzer_core import (
    generate_sss_and_inverse,
    deconvolve_signal,
    find_subsample_peak,
)

logger = logging.getLogger(__name__)


def design_biquad_lpf(fc, fs, Q):
    """
    Computes normalized Biquad LPF coefficients using Robert Bristow-Johnson's EQ Cookbook formula.
    """
    w0 = 2 * np.pi * fc / fs
    alpha = np.sin(w0) / (2 * Q)
    cos_w0 = np.cos(w0)

    b0 = (1.0 - cos_w0) / 2.0
    b1 = 1.0 - cos_w0
    b2 = (1.0 - cos_w0) / 2.0

    a0 = 1.0 + alpha
    a1 = -2.0 * cos_w0
    a2 = 1.0 - alpha

    b = np.array([b0, b1, b2]) / a0
    a = np.array([a0, a1, a2]) / a0
    return b, a


class RealtimeSSSEngine:
    def __init__(
        self,
        sample_rate: float,
        sweep_duration: float,
        start_freq: float,
        end_freq: float,
        output_amplitude: float,
        lpf_factor: float,
        max_harmonic: int = 5,
        extraction_mode: str = "ls",
    ):
        self.sample_rate = float(sample_rate)
        self.sweep_duration = float(sweep_duration)
        self.start_freq = float(start_freq)
        self.end_freq = float(end_freq)
        self.output_amplitude = float(output_amplitude)
        self.lpf_factor = float(lpf_factor)
        self.max_harmonic = int(max_harmonic)
        self.extraction_mode = str(extraction_mode)

        self.latency_samples = 0.0

        # Novak SSS Sweep Design parameters
        self.k_param = 0
        self.L_param = 0.0
        self.sweep_samples = 0
        self.t_arr: np.ndarray | None = None
        self.phase_arr: np.ndarray | None = None
        self.out_sig: np.ndarray | None = None

        # Filter states for each harmonic order (1 to max_harmonic)
        # We need 2 cascade sections for a 4th-order filter: zi1, zi2 for each harmonic
        self.zi1: list[np.ndarray] = []
        self.zi2: list[np.ndarray] = []

        # Reset engine variables
        self.reset_filter_states()

    def prepare_sweep(self):
        """
        Pre-calculates SSS phase trajectory and output signal using Novak's constraints.
        Using cosine excitation (cos(phi(t))) as it maps directly to Chebyshev polynomials.
        """
        nyquist = self.sample_rate / 2.0
        if self.start_freq <= self.end_freq:
            start_margin = max(2.0, self.start_freq / 1.3)
            end_margin = min(nyquist * 0.95, self.end_freq * 1.15)
        else:
            start_margin = min(nyquist * 0.95, self.start_freq * 1.15)
            end_margin = max(2.0, self.end_freq / 1.3)

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
        self.t_arr = np.arange(self.sweep_samples) / self.sample_rate

        # Phase trajectory
        self.phase_arr = 2.0 * np.pi * self.k_param * np.exp(self.t_arr / self.L_param)

        # Output signal: Cosine sweep
        self.out_sig = self.output_amplitude * np.cos(self.phase_arr)

        # Apply Tukey window (fade-in / fade-out) to minimize transient clicks
        window = scipy.signal.windows.tukey(self.sweep_samples, alpha=0.02)
        self.out_sig *= window

        self.reset_filter_states()

    def reset_filter_states(self):
        """Resets the state of the cascade Biquad filters."""
        self.zi1 = [np.zeros(2, dtype=complex) for _ in range(self.max_harmonic)]
        self.zi2 = [np.zeros(2, dtype=complex) for _ in range(self.max_harmonic)]
        self.ref_zi1 = np.zeros(2, dtype=complex)
        self.ref_zi2 = np.zeros(2, dtype=complex)
        self.dec_y_zi1 = np.zeros(2, dtype=float)
        self.dec_y_zi2 = np.zeros(2, dtype=float)
        self.dec_r_zi1 = np.zeros(2, dtype=float)
        self.dec_r_zi2 = np.zeros(2, dtype=float)
        self.reset_analysis_history()

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
            self._hist_ref.append(np.empty(0, dtype=float))

        keep_samples = int(
            max(
                self.sample_rate * 0.5,
                self.sample_rate * 40.0 / max(1.0, min(self.start_freq, self.end_freq)),
            )
        )
        last_valid_n = self._hist_n[-1][-1]
        while self._hist_n and self._hist_n[0][-1] < last_valid_n - keep_samples:
            self._hist_n.pop(0)
            self._hist_theta.pop(0)
            self._hist_signal.pop(0)
            self._hist_ref.pop(0)

    def _fit_harmonics(self, theta: np.ndarray, y: np.ndarray, weights: np.ndarray) -> list[complex]:
        if len(y) < max(8, 3 * (2 * self.max_harmonic + 1)):
            return [0.0j] * self.max_harmonic

        design = np.empty((len(theta), 2 * self.max_harmonic + 1))
        design[:, 0] = 1.0
        for p in range(1, self.max_harmonic + 1):
            phase = p * theta
            design[:, 2 * p - 1] = np.cos(phase)
            design[:, 2 * p] = np.sin(phase)
        weighted_design = design * weights[:, None]
        weighted_y = y * weights

        try:
            coeffs, *_ = np.linalg.lstsq(weighted_design, weighted_y, rcond=None)
        except np.linalg.LinAlgError:
            return [0.0j] * self.max_harmonic

        results = []
        for p in range(self.max_harmonic):
            cos_coef = coeffs[1 + 2 * p]
            sin_coef = coeffs[2 + 2 * p]
            results.append(complex(cos_coef, -sin_coef))
        return results

    def _process_block_ls(
        self,
        n_comp: np.ndarray,
        theta_comp: np.ndarray,
        y_raw: np.ndarray,
        f_mid: float,
        valid_mask: np.ndarray,
        ref_in_block: np.ndarray | None,
    ) -> tuple[float, list[complex]]:
        r_raw = None
        if ref_in_block is not None:
            if ref_in_block.shape[1] >= 1:
                r_raw = ref_in_block[:, 0]
            else:
                r_raw = np.zeros_like(y_raw)

        # 1. Append at original rate (48 kHz)
        self._append_analysis_history(n_comp, theta_comp, y_raw, r_raw, valid_mask)
        if not self._hist_n:
            return f_mid, [0.0j] * self.max_harmonic

        hist_n = np.concatenate(self._hist_n)
        hist_theta = np.concatenate(self._hist_theta)
        hist_signal = np.concatenate(self._hist_signal)
        hist_ref_chunks = [chunk for chunk in self._hist_ref if len(chunk) > 0]
        hist_ref = np.concatenate(hist_ref_chunks) if hist_ref_chunks else None

        last_valid_n = hist_n[-1]
        local_freq = self._frequency_at_sample(last_valid_n)
        window_seconds = np.clip(12.0 / max(local_freq, 1.0), 0.012, 0.15)
        window_samples = max(256.0, window_seconds * self.sample_rate)
        start_n = last_valid_n - window_samples
        mask = hist_n >= start_n
        if np.count_nonzero(mask) < max(64, 4 * (2 * self.max_harmonic + 1)):
            return f_mid, [0.0j] * self.max_harmonic

        theta_win = hist_theta[mask]
        sig_win = hist_signal[mask]
        ref_win = hist_ref[mask] if hist_ref is not None else None

        # Determine decimation factor dynamically
        P = self.max_harmonic
        fs = self.sample_rate
        max_d = int(np.floor(fs / (5.0 * P * max(1.0, local_freq))))
        D = int(np.clip(max_d, 1, 10))

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
            b, a = scipy.signal.butter(4, fc / nyq, btype="low")

            # Apply zero-phase filtering
            sig_win = scipy.signal.filtfilt(b, a, sig_win)
            sig_win = sig_win[::D]
            theta_win = theta_win[::D]
            if ref_win is not None:
                ref_win = scipy.signal.filtfilt(b, a, ref_win)
                ref_win = ref_win[::D]
        elif D > 1:
            # Fallback if window is too short
            sig_win = sig_win[::D]
            theta_win = theta_win[::D]
            if ref_win is not None:
                ref_win = ref_win[::D]

        weights = np.hanning(len(sig_win))
        if not np.any(weights > 0):
            return f_mid, [0.0j] * self.max_harmonic

        sig_results = self._fit_harmonics(theta_win, sig_win, weights)
        result_freq = self._frequency_at_sample(float(np.mean(hist_n[mask])))

        if ref_win is None or len(ref_win) != len(sig_win):
            return result_freq, sig_results

        ref_results = self._fit_harmonics(theta_win, ref_win, weights)
        ref_h1 = ref_results[0] if ref_results else 0.0j
        ref_conj = np.conj(ref_h1)
        ref_mag2 = float(np.real(ref_h1 * ref_conj))
        if ref_mag2 <= 1e-24:
            return result_freq, [0.0j] * self.max_harmonic

        return result_freq, [(value * ref_conj) / (ref_mag2 + 1e-24) for value in sig_results]

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
        frames = len(outdata_block)
        fs = self.sample_rate

        # 1. Output Generation
        start_samp = block_index * frames
        end_samp = start_samp + frames

        # Write sweep signal if inside sweep limits
        out_samples_written = 0
        if start_samp < self.sweep_samples:
            chunk = min(frames, self.sweep_samples - start_samp)
            assert self.out_sig is not None
            sig_chunk = self.out_sig[start_samp : start_samp + chunk]

            # Copy to all channels
            for ch in range(outdata_block.shape[1]):
                outdata_block[:chunk, ch] = sig_chunk
            out_samples_written = chunk

        # Fill the rest with silence
        if out_samples_written < frames:
            outdata_block[out_samples_written:, :] = 0.0

        # 2. Input Capture & Demodulation
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
        results = [0.0j] * self.max_harmonic

        if not np.any(valid_mask):
            return f_mid, results

        # Construct input signal
        # For simplicity, if stereo input is provided, we default to Ch 0
        if indata_block.shape[1] >= 1:
            y_raw = indata_block[:, 0]
        else:
            y_raw = np.zeros(frames)

        # Calculate phase for delayed time indices
        t_comp = n_comp / fs
        # To avoid exp overflow or math errors on negative or out-of-bound indices,
        # we clip the evaluation of exponent to [0, sweep_samples) time range
        t_eval = np.clip(t_comp, 0.0, (self.sweep_samples - 1.0) / fs)
        theta_comp = 2.0 * np.pi * self.k_param * np.exp(t_eval / self.L_param)

        # Zero out phase for invalid regions (before sweep reached microphone or after sweep ended)
        theta_comp[~valid_mask] = 0.0

        if self.extraction_mode == "ls":
            return self._process_block_ls(n_comp, theta_comp, y_raw, f_mid, valid_mask, ref_in_block)

        # Prepare LPF cutoff: fc = factor * f_mid
        fc = self.lpf_factor * f_mid
        # Clamp fc to safe Nyquist limits
        fc = np.clip(fc, 10.0, 0.48 * fs)

        # Butterworth 4th-order LPF Biquad design: Q1 = 0.541196 (low Q), Q2 = 1.306563 (high Q)
        b1, a1 = design_biquad_lpf(fc, fs, 0.541196)
        b2, a2 = design_biquad_lpf(fc, fs, 1.306563)

        # Process REF channel if provided
        ref_res = 1.0
        has_ref = False
        if ref_in_block is not None:
            if ref_in_block.shape[1] >= 1:
                r_raw = ref_in_block[:, 0]
            else:
                r_raw = np.zeros(frames)

            # Demodulate reference signal at fundamental (p=1)
            lo_r = np.exp(-1j * theta_comp)
            lo_r[~valid_mask] = 0.0
            z_r = 2.0 * r_raw * lo_r

            # Cascade IIR filtering for REF
            out_r1, self.ref_zi1 = scipy.signal.lfilter(b1, a1, z_r, zi=self.ref_zi1)
            out_r2, self.ref_zi2 = scipy.signal.lfilter(b2, a2, out_r1, zi=self.ref_zi2)

            valid_indices = np.flatnonzero(valid_mask)
            if len(valid_indices) > 0:
                last_valid_idx = valid_indices[-1]
                ref_res = out_r2[last_valid_idx]
                has_ref = True

        for p in range(1, self.max_harmonic + 1):
            # DDC mixing: z(t) = 2 * y(t) * exp(-j * p * theta)
            lo = np.exp(-1j * p * theta_comp)
            # Mask out local oscillator outside the valid sweep region to prevent transient noise leakage
            lo[~valid_mask] = 0.0

            z_p = 2.0 * y_raw * lo

            # Cascade IIR filtering
            out1, self.zi1[p - 1] = scipy.signal.lfilter(b1, a1, z_p, zi=self.zi1[p - 1])
            out2, self.zi2[p - 1] = scipy.signal.lfilter(b2, a2, out1, zi=self.zi2[p - 1])

            # Extract the final filtered state representing the current instantaneous response
            # We take the last valid sample's output inside the block
            valid_indices = np.flatnonzero(valid_mask)
            if len(valid_indices) > 0:
                last_valid_idx = valid_indices[-1]
                val_sig = out2[last_valid_idx]
                if has_ref:
                    # Regularized division to avoid division by zero/near-zero complex values
                    # and suppress noise-induced gain spikes when the reference signal is extremely weak.
                    ref_conj = np.conj(ref_res)
                    ref_mag2 = np.real(ref_res * ref_conj)
                    results[p - 1] = (val_sig * ref_conj) / (ref_mag2 + 1e-12)
                else:
                    results[p - 1] = val_sig

        return f_mid, results


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
    calibrator = LatencyCalibrator(audio_engine, start_freq, end_freq, duration, in_ch, out_ch)

    # Register the ephemeral audio callback
    calibrator.callback_id = audio_engine.register_callback(calibrator.callback)

    # Wait for execution to finish (with 1.5s margin)
    success = calibrator.finished.wait(timeout=duration + 1.5)

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
