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
    ):
        self.sample_rate = float(sample_rate)
        self.sweep_duration = float(sweep_duration)
        self.start_freq = float(start_freq)
        self.end_freq = float(end_freq)
        self.output_amplitude = float(output_amplitude)
        self.lpf_factor = float(lpf_factor)
        self.max_harmonic = int(max_harmonic)

        self.latency_samples = 0.0

        # Novak SSS Sweep Design parameters
        self.k_param = 0
        self.L_param = 0.0
        self.sweep_samples = 0
        self.t_arr = None
        self.phase_arr = None
        self.out_sig = None

        # Filter states for each harmonic order (1 to max_harmonic)
        # We need 2 cascade sections for a 4th-order filter: zi1, zi2 for each harmonic
        self.zi1 = []
        self.zi2 = []

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

    def set_latency(self, latency_samples: float):
        """Sets the physical latency correction value."""
        self.latency_samples = float(latency_samples)

    def process_block(self, indata_block: np.ndarray, outdata_block: np.ndarray, block_index: int, ref_in_block: np.ndarray = None):
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
                    results[p - 1] = val_sig / (ref_res + 1e-12)
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
        self.sss, self.inv = generate_sss_and_inverse(
            self.sample_rate, self.duration, start_freq, end_freq
        )

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
                    self.recorded_data[self.read_pos : self.read_pos + in_samples] = indata[
                        :in_samples, self.in_ch
                    ]
                else:
                    self.recorded_data[self.read_pos : self.read_pos + in_samples] = indata[
                        :in_samples, 0
                    ]
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

    return peak_sample
