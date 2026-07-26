#!/usr/bin/env python3
# ruff: noqa: E402, B023
import sys
import os
import time
import json
import argparse
import queue
import threading
import numpy as np
import matplotlib.pyplot as plt
from scipy.interpolate import PchipInterpolator
from scipy.signal import butter, lfilter, freqz
from scipy.signal.windows import tukey

# Add project root to sys.path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from PyQt6.QtWidgets import QApplication

from src.core.audio_engine import AudioEngine
from src.core.realtime_sss_core import RealtimeSSSEngine, measure_system_latency

# ----------------------------------------------------
# Dummy Non-linear DUT System (For Offline Mode)
# ----------------------------------------------------
# Static non-linearity coeffs: w = x + d2*x^2 + d3*x^3 + d4*x^4 + d5*x^5
d_coeffs = {1: 1.0, 2: 0.04, 3: 0.025, 4: 0.012, 5: 0.006}
fc_lti = 1200.0  # Cutoff for 2nd order LPF


def offline_dut_system(x, fs):
    """Simulates a Hammerstein model system (Nonlinearity + LTI LPF)."""
    # 1. Static non-linearity
    w = d_coeffs[1] * x + d_coeffs[2] * x**2 + d_coeffs[3] * x**3 + d_coeffs[4] * x**4 + d_coeffs[5] * x**5
    # 2. Linear dynamics: 2nd order Butterworth LPF
    b, a = butter(2, fc_lti / (fs / 2.0), btype="low")
    y = lfilter(b, a, w)
    return y


def pchip_complex_interpolate(freqs_in, C_p_in, freqs_target):
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


def smooth_complex_vector(vec, window_size=5):
    """Smooths a complex vector using a moving average window along the frequency axis."""
    if len(vec) < window_size or window_size < 2:
        return vec
    win = np.hanning(window_size)
    win /= np.sum(win)

    # Pad vector at boundaries
    pad_len = window_size // 2
    padded_real = np.pad(vec.real, pad_len, mode="edge")
    padded_imag = np.pad(vec.imag, pad_len, mode="edge")

    smooth_real = np.convolve(padded_real, win, mode="valid")
    smooth_imag = np.convolve(padded_imag, win, mode="valid")

    return smooth_real[: len(vec)] + 1j * smooth_imag[: len(vec)]


def calculate_thd_from_H(H_dict, max_harmonic):
    """
    Calculates THD array across frequencies and average THD values.

    H_dict: dict mapping harmonic order n (1..max_harmonic) to complex response array across frequencies.
    Returns:
        thd_ratio: array of THD values (linear ratio) at each frequency
        thd_percent_mean: float mean THD in percent (%)
        thd_db_mean: float mean THD in dB (20*log10(THD))
    """
    H1_mag = np.abs(H_dict[1]) + 1e-12
    harmonic_sq_sum = np.zeros_like(H1_mag)

    for n in range(2, max_harmonic + 1):
        if n in H_dict:
            harmonic_sq_sum += np.abs(H_dict[n]) ** 2

    thd_ratio = np.sqrt(harmonic_sq_sum) / H1_mag
    thd_percent_mean = float(np.mean(thd_ratio) * 100.0)
    thd_db_mean = float(20.0 * np.log10(np.mean(thd_ratio) + 1e-12))

    return thd_ratio, thd_percent_mean, thd_db_mean


def get_analytical_H1(f, fs):
    """Returns the analytical linear transfer function value at frequency f."""
    b, a = butter(2, fc_lti / (fs / 2.0), btype="low")
    _, h = freqz(b, a, np.atleast_1d(f), fs=fs)
    return h * d_coeffs[1]


# ----------------------------------------------------
# Adaptive Sweep Sweeper Class
# ----------------------------------------------------
class AdaptiveSSSWeeper:
    def __init__(self, args, audio_engine):
        self.args = args
        self.audio_engine = audio_engine
        self.fs = audio_engine.sample_rate

        # SSS Design parameters
        self.start_freq = args.start_freq
        self.end_freq = args.end_freq
        self.duration = args.duration
        self.amplitude = 10 ** (args.amplitude_db / 20.0)
        self.max_harmonic = args.max_harmonic
        self.mu = args.mu

        # Dynamic frequency grid for interpolation
        self.num_points = args.meas_points
        self.analysis_cycles = args.analysis_cycles
        self.min_analysis_window = args.min_window
        self.meas_freqs = np.logspace(np.log10(self.start_freq + 5.0), np.log10(self.end_freq - 10.0), self.num_points)

        # State variables
        self.latency = 0.0

        # Correction complex envelope for each harmonic (initialized to zero)
        # F[n] is an array of complex values mapped to self.meas_freqs
        self.F_corr = {n: np.zeros(self.num_points, dtype=complex) for n in range(2, self.max_harmonic + 1)}

        # Store results for each iteration to plot/save
        self.iteration_results = []
        # History tracking for Quasi-Newton / Anderson acceleration algorithms
        self.F_history = {n: [] for n in range(2, self.max_harmonic + 1)}
        self.H_history = {n: [] for n in range(2, self.max_harmonic + 1)}

    def calibrate_latency(self):
        """Measures system loopback latency."""
        if self.args.offline:
            # Simulated latency
            self.latency = 64.2  # samples
            print(f"[+] Offline mode: simulated latency = {self.latency:.1f} samples")
            return

        print("[*] Calibrating latency...")
        try:
            self.latency = measure_system_latency(
                self.audio_engine, self.start_freq, self.end_freq, in_ch=self.args.ch_sig, out_ch=0
            )
            print(f"[+] Latency calibrated: {self.latency:.2f} samples ({self.latency / self.fs * 1000.0:.2f} ms)")
        except Exception as e:
            print(f"[-] Latency calibration failed: {e}. Defaulting to 0.")
            self.latency = 0.0

    def generate_predistorted_sweep(self, f_start, f_end):
        """
        Generates the predistorted input signal x_corr(t) based on current correction envelopes.
        Also returns the reference signal (pure fundamental sweep) for synchronization.
        """
        # 1. Setup baseline sweep
        if f_start <= f_end:
            f1 = f_start / 1.3
            f2 = f_end * 1.15
        else:
            f1 = f_start * 1.15
            f2 = f_end / 1.3

        ln_ratio = np.log(f2 / f1)
        k_param = int(np.round((f1 / ln_ratio) * self.duration))
        L_param = k_param / f1
        T_actual = L_param * ln_ratio

        num_samples = int(np.round(self.fs * T_actual))
        t = np.arange(num_samples) / self.fs

        # Instantenous phase and frequency
        phase = 2 * np.pi * k_param * np.exp(t / L_param)
        f_inst = f1 * np.exp(t / L_param)

        # Generate base signal
        x_base = np.sin(phase)
        win = tukey(num_samples, alpha=0.02)
        x_base_win = x_base * win

        # Build corrected signal: x_corr(t) = sin(phase) + sum |F_n| * sin(n*phase + angle(F_n))
        x_corr = x_base.copy()

        for n in range(2, self.max_harmonic + 1):
            # Interpolate correction envelope over the sweep instantaneous frequency trajectory using PCHIP
            F_inst_vals = pchip_complex_interpolate(self.meas_freqs, self.F_corr[n], f_inst)

            # Apply term
            mag_vals = np.abs(F_inst_vals)
            phase_vals = np.angle(F_inst_vals)

            x_corr += mag_vals * np.sin(n * phase + phase_vals)

        # Scale to target amplitude and apply window
        x_corr_win = x_corr * self.amplitude * win
        x_base_win = x_base_win * self.amplitude  # matching amplitude for reference channel

        return x_corr_win, x_base_win, f_inst, phase, num_samples

    def run_sweep_iteration(self, iter_idx):
        """Runs a single sweep playback/recording and processes results."""
        print(f"\n--- Running Sweep Iteration {iter_idx} ---")

        # Determine sweep direction based on mode
        is_ascending = True
        if hasattr(self.args, "sweep_mode"):
            if self.args.sweep_mode == "reverse":
                is_ascending = False
            elif self.args.sweep_mode == "bidirectional":
                is_ascending = iter_idx % 2 == 0

        if is_ascending:
            f_start, f_end = self.start_freq, self.end_freq
            print("[*] Direction: Forward (Ascending)")
        else:
            f_start, f_end = self.end_freq, self.start_freq
            print("[*] Direction: Reverse (Descending)")

        # 1. Generate excitation signal and ideal fundamental reference
        x_corr, x_base, f_inst, phase, num_samples = self.generate_predistorted_sweep(f_start, f_end)

        # Setup SSS engine
        engine = RealtimeSSSEngine(
            sample_rate=self.fs,
            sweep_duration=self.duration,
            start_freq=f_start,
            end_freq=f_end,
            output_amplitude=self.amplitude,
            max_harmonic=self.max_harmonic,
            analysis_cycles=self.analysis_cycles,
            num_meas_points=self.num_points,
            min_analysis_window=self.min_analysis_window,
        )
        engine.prepare_sweep()
        engine.set_latency(self.latency)

        frames = self.audio_engine.block_size
        max_blocks = int(np.ceil((engine.sweep_samples + self.latency) / frames))

        # Accumulated result arrays
        accumulated_results = np.zeros((max_blocks, self.max_harmonic), dtype=complex)
        block_counts = np.zeros(max_blocks, dtype=int)
        plot_freqs = np.zeros(max_blocks)

        # 2. Playback / Recording Loop
        if self.args.offline:
            # --- OFFLINE SIMULATION MODE ---
            # Simulate physical loopback with dummy non-linear system
            # Right input is reference (clean fundamental), Left input is measured (distorted LPF)
            total_len = len(x_corr) + int(np.ceil(self.latency))
            recorded_data = np.zeros((total_len, 2), dtype=np.float32)

            # Measure: Ch0 (Left), Ref: Ch1 (Right)
            recorded_data[: len(x_corr), 1] = x_base  # Reference is pure fundamental
            recorded_data[: len(x_corr), 0] = offline_dut_system(x_corr, self.fs)  # Measure through non-linear LPF

            for b in range(max_blocks):
                start_idx = b * frames
                end_idx = min(start_idx + frames, total_len)

                indata_block = np.zeros((frames, 2), dtype=np.float32)
                chunk_len = end_idx - start_idx
                if chunk_len > 0:
                    indata_block[:chunk_len, :] = recorded_data[start_idx:end_idx, :]

                sig_in = indata_block[:, [self.args.ch_sig]]
                ref_in = indata_block[:, [self.args.ch_ref]]

                f_mid, results, _ = engine.process_input_block(sig_in, b, ref_in_block=ref_in)
                if engine.last_block_was_valid:
                    accumulated_results[b, :] = results[: self.max_harmonic]
                    block_counts[b] += 1
                    plot_freqs[b] = f_mid
        else:
            # --- REALHARDWARE MODE ---
            sweep_done = threading.Event()
            current_block = [0]
            data_queue = queue.Queue()

            # Lock for synchronizing queue operations
            q_lock = threading.Lock()

            def sss_callback(indata_buf, outdata_buf, frames_cb, time_cb, status):
                b_idx = current_block[0]
                if b_idx >= max_blocks:
                    outdata_buf.fill(0.0)
                    sweep_done.set()
                    return

                # Write to hardware output
                # Out Ch1 (L): Predistorted signal
                # Out Ch2 (R): Base clean reference sweep (for relative phase ref)
                start_samp = b_idx * frames_cb
                chunk = min(frames_cb, num_samples - start_samp)

                outdata_buf.fill(0.0)
                if chunk > 0:
                    if outdata_buf.shape[1] >= 2:
                        outdata_buf[:chunk, 0] = x_corr[start_samp : start_samp + chunk]
                        outdata_buf[:chunk, 1] = x_base[start_samp : start_samp + chunk]
                    else:
                        outdata_buf[:chunk, 0] = x_corr[start_samp : start_samp + chunk]

                # Extract hardware inputs
                sig_in = np.zeros((frames_cb, 1))
                if indata_buf.shape[1] > self.args.ch_sig:
                    sig_in[:, 0] = indata_buf[:, self.args.ch_sig]

                ref_in = np.zeros((frames_cb, 1))
                if indata_buf.shape[1] > self.args.ch_ref:
                    ref_in[:, 0] = indata_buf[:, self.args.ch_ref]

                with q_lock:
                    data_queue.put((b_idx, sig_in, ref_in))
                current_block[0] += 1

            # Register callback and wait
            cb_id = self.audio_engine.register_callback(sss_callback)

            timeout = self.duration + 5.0
            start_time = time.time()
            while not sweep_done.is_set() or not data_queue.empty():
                try:
                    with q_lock:
                        if data_queue.empty():
                            item = None
                        else:
                            item = data_queue.get_nowait()

                    if item is None:
                        time.sleep(0.01)
                        if time.time() - start_time > timeout:
                            print("[-] Timeout waiting for audio block queue.")
                            break
                        continue

                    b_idx, sig_in, ref_in = item
                    f_mid, results, _ = engine.process_input_block(sig_in, b_idx, ref_in_block=ref_in)
                    if engine.last_block_was_valid:
                        accumulated_results[b_idx, :] = results[: self.max_harmonic]
                        block_counts[b_idx] += 1
                        plot_freqs[b_idx] = f_mid
                    data_queue.task_done()
                except queue.Empty:
                    continue

            self.audio_engine.unregister_callback(cb_id)

        # 3. Post-Process Sweep Block Measurements to self.meas_freqs grid
        # Average results for each block
        valid_mask = block_counts > 0
        raw_freqs = plot_freqs[valid_mask]
        raw_results = accumulated_results[valid_mask, :]

        # Sort raw_freqs to make sure they are strictly increasing for interp1d
        sort_idx = np.argsort(raw_freqs)
        raw_freqs_sorted = raw_freqs[sort_idx]
        raw_results_sorted = raw_results[sort_idx, :]

        # Interpolate results to standard log-grid meas_freqs
        H_meas = {}
        for n in range(1, self.max_harmonic + 1):
            H_meas[n] = pchip_complex_interpolate(raw_freqs_sorted, raw_results_sorted[:, n - 1], self.meas_freqs)

        # Save measurement result
        self.iteration_results.append({"iter": iter_idx, "H": H_meas})

        # 4. Calculate adaptive correction for next iteration
        # Update equation: F_corr[n] = F_corr[n] - mu * Hn(f) / H1(n * f)
        if iter_idx == 0:
            # Store initial linear transfer function H0_1
            self.H0_1 = H_meas[1].copy()

        # Helper to interpolate linear transfer function H1(f) at higher frequencies (up to max_harmonic * f_end)
        def get_H0_1_interpolated(f_target_array):
            if self.args.offline:
                return get_analytical_H1(f_target_array, self.fs)
            else:
                h_vals = pchip_complex_interpolate(self.meas_freqs, self.H0_1, f_target_array)
                mag = np.abs(h_vals)
                min_mag = 1e-4 * np.max(np.abs(self.H0_1))
                bad_mask = mag < min_mag
                if np.any(bad_mask):
                    h_vals[bad_mask] = (h_vals[bad_mask] / (mag[bad_mask] + 1e-12)) * min_mag
                return h_vals

        # Learning rate decay per iteration to ensure convergence without oscillation
        algo = getattr(self.args, "algorithm", "newton_lm")
        decay_factor = getattr(self.args, "mu_decay", 0.92)
        current_mu = self.mu * (decay_factor**iter_idx) if algo == "baseline" else self.mu
        print(f"[*] Calculating adaptive updates (algorithm = '{algo}', step size mu = {current_mu:.4f})...")
        for n in range(2, self.max_harmonic + 1):
            Hn_vals = H_meas[n]

            # Record history of F_corr and H_meas for history-based updates
            F_prev = self.F_corr[n].copy()
            self.F_history[n].append(F_prev)
            self.H_history[n].append(Hn_vals.copy())

            # We need the linear response at the harmonic frequency: n * f
            H1_nf_vals = get_H0_1_interpolated(n * self.meas_freqs)

            if algo == "baseline":
                # Baseline gradient update with decaying step size
                delta_corr = -Hn_vals / H1_nf_vals
                delta_corr = smooth_complex_vector(delta_corr, window_size=5)
                self.F_corr[n] += current_mu * delta_corr

            elif algo in ["newton_lm", "newton"]:
                # Normalized Newton step with Levenberg-Marquardt regularization
                # Allows mu = 1.0 (full Newton step) safely
                h1_mag_sq = np.abs(H1_nf_vals) ** 2
                lambda_lm = 1e-4 * np.max(h1_mag_sq) + 1e-12
                delta_corr = -(Hn_vals * np.conj(H1_nf_vals)) / (h1_mag_sq + lambda_lm)
                delta_corr = smooth_complex_vector(delta_corr, window_size=5)
                self.F_corr[n] += current_mu * delta_corr

            elif algo in ["secant", "quasi_newton"]:
                # Secant / Empirical Jacobian method
                # At iter 0: use Newton-LM step.
                # At iter >= 1: estimate empirical Jacobian J_n(f) = dH_n / dF_n from previous 2 iterations.
                if iter_idx == 0 or len(self.F_history[n]) < 2:
                    h1_mag_sq = np.abs(H1_nf_vals) ** 2
                    lambda_lm = 1e-4 * np.max(h1_mag_sq) + 1e-12
                    delta_corr = -(Hn_vals * np.conj(H1_nf_vals)) / (h1_mag_sq + lambda_lm)
                else:
                    dF = self.F_history[n][-1] - self.F_history[n][-2]
                    dH = self.H_history[n][-1] - self.H_history[n][-2]

                    # Empirical derivative J_n = dH / dF
                    dF_mag = np.abs(dF)
                    valid_mask = dF_mag > 1e-10
                    J_emp = np.where(valid_mask, dH / np.where(valid_mask, dF, 1.0), H1_nf_vals)

                    # Fallback to model H1_nf_vals where J_emp is noisy or near zero
                    j_mag = np.abs(J_emp)
                    bad_j = (j_mag < 1e-4 * np.max(np.abs(H1_nf_vals))) | np.isnan(j_mag)
                    J_emp[bad_j] = H1_nf_vals[bad_j]

                    j_mag_sq = np.abs(J_emp) ** 2
                    lambda_lm = 1e-4 * np.max(j_mag_sq) + 1e-12
                    delta_corr = -(Hn_vals * np.conj(J_emp)) / (j_mag_sq + lambda_lm)

                delta_corr = smooth_complex_vector(delta_corr, window_size=5)
                self.F_corr[n] += current_mu * delta_corr

            elif algo == "anderson":
                # Anderson Acceleration
                if iter_idx == 0 or len(self.F_history[n]) < 2:
                    h1_mag_sq = np.abs(H1_nf_vals) ** 2
                    lambda_lm = 1e-4 * np.max(h1_mag_sq) + 1e-12
                    delta_corr = -(Hn_vals * np.conj(H1_nf_vals)) / (h1_mag_sq + lambda_lm)
                    delta_corr = smooth_complex_vector(delta_corr, window_size=5)
                    self.F_corr[n] += current_mu * delta_corr
                else:
                    g_curr = self.F_history[n][-1] - Hn_vals / H1_nf_vals
                    g_prev = self.F_history[n][-2] - self.H_history[n][-2] / H1_nf_vals

                    dg = g_curr - g_prev
                    dg_dot_g = np.real(np.sum(np.conj(dg) * g_curr))
                    dg_norm_sq = np.real(np.sum(np.conj(dg) * dg)) + 1e-12
                    gamma = np.clip(dg_dot_g / dg_norm_sq, -0.5, 0.5)

                    F_anderson = (1 - gamma) * g_curr + gamma * g_prev
                    self.F_corr[n] = smooth_complex_vector(F_anderson, window_size=5)

            # Print average distortion level
            avg_dist = 20 * np.log10(np.mean(np.abs(Hn_vals)) + 1e-12)
            print(f"    - H{n} Average Level: {avg_dist:.1f} dB")

        _, thd_pct, thd_db = calculate_thd_from_H(H_meas, self.max_harmonic)
        print(f"    - Overall Mean THD: {thd_pct:.3f}% ({thd_db:.1f} dB)")

    def measure_sweep_only(self, is_ascending):
        """Runs a single sweep playback/recording and processes results WITHOUT updating F_corr (offline simulation only)."""
        if is_ascending:
            f_start, f_end = self.start_freq, self.end_freq
        else:
            f_start, f_end = self.end_freq, self.start_freq

        x_corr, x_base, f_inst, phase, num_samples = self.generate_predistorted_sweep(f_start, f_end)

        # Setup SSS engine
        engine = RealtimeSSSEngine(
            sample_rate=self.fs,
            sweep_duration=self.duration,
            start_freq=f_start,
            end_freq=f_end,
            output_amplitude=self.amplitude,
            max_harmonic=self.max_harmonic,
            analysis_cycles=self.analysis_cycles,
            num_meas_points=self.num_points,
            min_analysis_window=self.min_analysis_window,
        )
        engine.prepare_sweep()
        engine.set_latency(self.latency)

        frames = self.audio_engine.block_size
        max_blocks = int(np.ceil((engine.sweep_samples + self.latency) / frames))

        accumulated_results = np.zeros((max_blocks, self.max_harmonic), dtype=complex)
        block_counts = np.zeros(max_blocks, dtype=int)
        plot_freqs = np.zeros(max_blocks)

        total_len = len(x_corr) + int(np.ceil(self.latency))
        recorded_data = np.zeros((total_len, 2), dtype=np.float32)
        recorded_data[: len(x_corr), 1] = x_base
        recorded_data[: len(x_corr), 0] = offline_dut_system(x_corr, self.fs)

        for b in range(max_blocks):
            start_idx = b * frames
            end_idx = min(start_idx + frames, total_len)

            indata_block = np.zeros((frames, 2), dtype=np.float32)
            chunk_len = end_idx - start_idx
            if chunk_len > 0:
                indata_block[:chunk_len, :] = recorded_data[start_idx:end_idx, :]

            sig_in = indata_block[:, [self.args.ch_sig]]
            ref_in = indata_block[:, [self.args.ch_ref]]

            f_mid, results, _ = engine.process_input_block(sig_in, b, ref_in_block=ref_in)
            if engine.last_block_was_valid:
                accumulated_results[b, :] = results[: self.max_harmonic]
                block_counts[b] += 1
                plot_freqs[b] = f_mid

        valid_mask = block_counts > 0
        raw_freqs = plot_freqs[valid_mask]
        raw_results = accumulated_results[valid_mask, :]

        sort_idx = np.argsort(raw_freqs)
        raw_freqs_sorted = raw_freqs[sort_idx]
        raw_results_sorted = raw_results[sort_idx, :]

        H_meas = {}
        for n in range(1, self.max_harmonic + 1):
            H_meas[n] = pchip_complex_interpolate(raw_freqs_sorted, raw_results_sorted[:, n - 1], self.meas_freqs)

        return H_meas

    def run(self):
        """Executes the full adaptive sweep iterations."""
        self.calibrate_latency()

        # Execute sweeps
        for i in range(self.args.iterations + 1):
            self.run_sweep_iteration(i)

        # Summary analysis and export
        self.generate_report()

    def generate_report(self):
        """Generates plots and text summary of the adaptive sweep performance."""
        # Print summary table
        print("\n====================================================")
        print("          Adaptive Sweep Summary (dB)")
        print("====================================================")

        initial = self.iteration_results[0]["H"]
        final = self.iteration_results[-1]["H"]

        for n in range(2, self.max_harmonic + 1):
            db_init = 20 * np.log10(np.mean(np.abs(initial[n])) + 1e-12)
            db_final = 20 * np.log10(np.mean(np.abs(final[n])) + 1e-12)
            reduction = db_final - db_init
            print(
                f"H{n} Distortion: Iteration 0: {db_init:.1f} dB -> Final Iteration: {db_final:.1f} dB | Reduction: {reduction:.1f} dB"
            )

        _, thd_pct_init, thd_db_init = calculate_thd_from_H(initial, self.max_harmonic)
        _, thd_pct_final, thd_db_final = calculate_thd_from_H(final, self.max_harmonic)
        thd_reduction_db = thd_db_final - thd_db_init
        print("----------------------------------------------------")
        print(
            f"Overall Mean THD: Iteration 0: {thd_pct_init:.3f}% ({thd_db_init:.1f} dB) -> Final: {thd_pct_final:.3f}% ({thd_db_final:.1f} dB) | Reduction: {thd_reduction_db:.1f} dB"
        )
        print("====================================================")

        # Save plots
        plt.figure(figsize=(12, 10))

        # Plot Magnitude vs Frequency for each iteration
        plt.subplot(2, 1, 1)
        colors = ["blue", "orange", "green", "red", "purple", "brown"]

        # Plot fundamental from iteration 0
        plt.semilogx(
            self.meas_freqs, 20 * np.log10(np.abs(initial[1])), label="H1 (Linear)", color="black", linewidth=2
        )

        # Plot harmonics for each iteration
        for iter_idx in range(self.args.iterations + 1):
            H_data = self.iteration_results[iter_idx]["H"]
            alpha_val = 0.3 if iter_idx < self.args.iterations else 1.0
            line_style = ":" if iter_idx == 0 else "-"
            linewidth = 1.0 if iter_idx < self.args.iterations else 1.5

            for n in range(2, min(4, self.max_harmonic + 1)):  # Plot H2 and H3 for clarity
                lbl = f"H{n} Iter {iter_idx}" if iter_idx in [0, self.args.iterations] else None
                c_idx = (n - 2) * 2 + (0 if iter_idx == 0 else 1)
                color = colors[c_idx % len(colors)]
                plt.semilogx(
                    self.meas_freqs,
                    20 * np.log10(np.abs(H_data[n]) + 1e-12),
                    label=lbl,
                    color=color,
                    alpha=alpha_val,
                    linestyle=line_style,
                    linewidth=linewidth,
                )

        plt.title("Adaptive Predistortion Sweep: Harmonic Level per Iteration")
        plt.xlabel("Frequency (Hz)")
        plt.ylabel("Response Level (dB)")
        plt.grid(True, which="both")
        plt.legend()
        plt.ylim(-120, 5)

        # Plot Distortion & THD reduction trajectory across iterations
        plt.subplot(2, 1, 2)
        iters = np.arange(self.args.iterations + 1)
        for n in range(2, self.max_harmonic + 1):
            traj = []
            for iter_idx in iters:
                H_data = self.iteration_results[iter_idx]["H"]
                traj.append(20 * np.log10(np.mean(np.abs(H_data[n])) + 1e-12))
            plt.plot(iters, traj, "o-", label=f"H{n} average level (dB)")

        # Plot Overall THD Trajectory
        thd_traj_db = []
        thd_traj_pct = []
        for iter_idx in iters:
            H_data = self.iteration_results[iter_idx]["H"]
            _, pct, db = calculate_thd_from_H(H_data, self.max_harmonic)
            thd_traj_pct.append(pct)
            thd_traj_db.append(db)

        plt.plot(iters, thd_traj_db, "k^-", linewidth=2.5, label="Overall THD (dB)")

        plt.title("Harmonic Distortion & Overall THD Trajectory")
        plt.xlabel("Iteration Index")
        plt.ylabel("Average Level (dB)")
        plt.grid(True)
        plt.legend()

        plt.tight_layout()
        plot_path = os.path.join(project_root, "scripts", "adaptive_sweep_verification_plot.png")
        plt.savefig(plot_path)
        print(f"[+] Saved trajectory verification plot to {plot_path}")

        # Save JSON results
        json_results = {
            "metadata": {
                "algorithm": getattr(self.args, "algorithm", "baseline"),
                "start_freq": self.start_freq,
                "end_freq": self.end_freq,
                "duration": self.duration,
                "amplitude_db": self.args.amplitude_db,
                "iterations": self.args.iterations,
                "mu": self.mu,
                "offline": self.args.offline,
                "sweep_mode": getattr(self.args, "sweep_mode", "forward"),
            },
            "trajectories": {
                f"H{n}": [
                    float(20 * np.log10(np.mean(np.abs(self.iteration_results[iter_idx]["H"][n])) + 1e-12))
                    for iter_idx in range(self.args.iterations + 1)
                ]
                for n in range(2, self.max_harmonic + 1)
            },
            "thd_trajectory": {
                "thd_percent": thd_traj_pct,
                "thd_db": thd_traj_db,
            },
        }
        json_path = os.path.join(project_root, "scripts", "adaptive_sweep_verification_results.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(json_results, f, indent=2)
        print(f"[+] Saved numeric trajectory data to {json_path}")


# ----------------------------------------------------
# Main entry point
# ----------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Adaptive Predistortion Sweeper Verification Prototype")
    parser.add_argument("--start-freq", type=float, default=100.0, help="Start frequency (Hz)")
    parser.add_argument("--end-freq", type=float, default=2000.0, help="End frequency (Hz)")
    parser.add_argument("--duration", type=float, default=4.0, help="Sweep duration (seconds)")
    parser.add_argument("--amplitude-db", type=float, default=-12.0, help="Sweep amplitude in dBFS")
    parser.add_argument("--max-harmonic", type=int, default=5, help="Maximum harmonic order to correct (up to 5)")
    parser.add_argument("--iterations", type=int, default=10, help="Number of adaptive correction iterations")
    parser.add_argument(
        "--algorithm",
        type=str,
        choices=["baseline", "newton_lm", "secant", "anderson"],
        default="newton_lm",
        help="Fast convergence algorithm (baseline, newton_lm, secant, anderson)",
    )
    parser.add_argument("--mu", type=float, default=1.0, help="Learning rate (0 < mu <= 1.0) to prevent overshoot")
    parser.add_argument("--mu-decay", type=float, default=0.92, help="Learning rate decay factor per iteration (e.g. 0.85 - 0.95)")
    parser.add_argument("--analysis-cycles", type=float, default=12.0, help="Analysis cycles for lock-in tracking")
    parser.add_argument("--min-window", type=float, default=0.012, help="Minimum analysis window in seconds")
    parser.add_argument("--meas-points", type=int, default=300, help="Number of measurement points")
    parser.add_argument(
        "--profile", type=str, choices=["quick", "normal", "high"], default=None, help="Use preset optimization profile"
    )
    parser.add_argument(
        "--sweep-mode",
        type=str,
        choices=["forward", "reverse", "bidirectional"],
        default="forward",
        help="Sweep direction mode (forward, reverse, bidirectional)",
    )
    parser.add_argument("--offline", action="store_true", default=False, help="Enable offline simulated DUT mode")
    parser.add_argument("--device-in", type=int, default=None, help="Input device ID (for real-hardware mode)")
    parser.add_argument("--device-out", type=int, default=None, help="Output device ID (for real-hardware mode)")
    parser.add_argument("--ch-sig", type=int, default=0, help="Signal channel index (usually 0: Left)")
    parser.add_argument("--ch-ref", type=int, default=1, help="Reference channel index (usually 1: Right)")

    args = parser.parse_args()

    # Profile overrides
    if args.profile == "quick":
        args.duration = 13.33
        args.analysis_cycles = 256.0
        args.meas_points = 500
        args.min_window = 1.0
    elif args.profile == "normal":
        args.duration = 20.0
        args.analysis_cycles = 256.0
        args.meas_points = 500
        args.min_window = 0.5
    elif args.profile == "high":
        args.duration = 80.0
        args.analysis_cycles = 256.0
        args.meas_points = 500
        args.min_window = 2.0

    if args.profile:
        print(f"[*] Profile selected: {args.profile}")
        print(f"    - Sweep Duration: {args.duration} s")
        print(f"    - Analysis Cycles: {args.analysis_cycles}")
        print(f"    - Meas Points: {args.meas_points}")
        print(f"    - Min Window: {args.min_window} s")

    # Initialize QApplication if running real device sweep (PyQt components may be active)
    # Sounddevice callbacks inside AudioEngine require thread safety, PyQt is recommended but not mandatory for CLI.
    # We initialize QApplication to ensure any Qt-dependent logic runs correctly.
    _app = QApplication(sys.argv)

    # Initialize AudioEngine
    audio_engine = AudioEngine()

    # Configure device
    if args.offline:
        audio_engine.set_offline_mode(True)
        # In offline mode, loopback must be active to simulate playback-to-record
        audio_engine.set_loopback(True)
    else:
        # Real hardware device setup
        audio_engine.list_devices()
        in_dev = args.device_in if args.device_in is not None else audio_engine.input_device
        out_dev = args.device_out if args.device_out is not None else audio_engine.output_device
        audio_engine.set_devices(in_dev, out_dev)
        audio_engine.set_loopback(False)

    audio_engine.set_sample_rate(48000)
    audio_engine.set_block_size(1024)

    sweeper = AdaptiveSSSWeeper(args, audio_engine)
    sweeper.run()

    # Clean up audio stream
    audio_engine.stop_stream()


if __name__ == "__main__":
    main()
