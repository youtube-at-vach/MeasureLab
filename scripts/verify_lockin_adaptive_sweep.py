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
from scipy.interpolate import interp1d
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
    w = (d_coeffs[1] * x + 
         d_coeffs[2] * x**2 + 
         d_coeffs[3] * x**3 + 
         d_coeffs[4] * x**4 + 
         d_coeffs[5] * x**5)
    # 2. Linear dynamics: 2nd order Butterworth LPF
    b, a = butter(2, fc_lti / (fs / 2.0), btype='low')
    y = lfilter(b, a, w)
    return y

def get_analytical_H1(f, fs):
    """Returns the analytical linear transfer function value at frequency f."""
    b, a = butter(2, fc_lti / (fs / 2.0), btype='low')
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
                self.audio_engine, 
                self.start_freq, 
                self.end_freq, 
                in_ch=self.args.ch_sig, 
                out_ch=0
            )
            print(f"[+] Latency calibrated: {self.latency:.2f} samples ({self.latency/self.fs*1000.0:.2f} ms)")
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
            # Interpolate correction envelope over the sweep instantaneous frequency trajectory
            # Use linear interpolation and extrapolate with nearest value
            F_func = interp1d(
                self.meas_freqs, 
                self.F_corr[n], 
                kind='linear', 
                fill_value='extrapolate'
            )
            F_inst_vals = F_func(f_inst)

            # Apply term
            mag_vals = np.abs(F_inst_vals)
            phase_vals = np.angle(F_inst_vals)

            x_corr += mag_vals * np.sin(n * phase + phase_vals)

        # Scale to target amplitude and apply window
        x_corr_win = x_corr * self.amplitude * win
        x_base_win = x_base_win * self.amplitude # matching amplitude for reference channel

        return x_corr_win, x_base_win, f_inst, phase, num_samples

    def run_sweep_iteration(self, iter_idx):
        """Runs a single sweep playback/recording and processes results."""
        print(f"\n--- Running Sweep Iteration {iter_idx} ---")

        # Determine sweep direction based on mode
        is_ascending = True
        if hasattr(self.args, 'sweep_mode'):
            if self.args.sweep_mode == "reverse":
                is_ascending = False
            elif self.args.sweep_mode == "bidirectional":
                is_ascending = (iter_idx % 2 == 0)

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
            min_analysis_window=self.min_analysis_window
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
            recorded_data[:len(x_corr), 1] = x_base # Reference is pure fundamental
            recorded_data[:len(x_corr), 0] = offline_dut_system(x_corr, self.fs) # Measure through non-linear LPF

            for b in range(max_blocks):
                start_idx = b * frames
                end_idx = min(start_idx + frames, total_len)

                indata_block = np.zeros((frames, 2), dtype=np.float32)
                chunk_len = end_idx - start_idx
                if chunk_len > 0:
                    indata_block[:chunk_len, :] = recorded_data[start_idx:end_idx, :]

                sig_in = indata_block[:, [self.args.ch_sig]]
                ref_in = indata_block[:, [self.args.ch_ref]]

                f_mid, results = engine.process_input_block(sig_in, b, ref_in_block=ref_in)
                if engine.last_block_was_valid:
                    accumulated_results[b, :] = results[:self.max_harmonic]
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
                        outdata_buf[:chunk, 0] = x_corr[start_samp:start_samp+chunk]
                        outdata_buf[:chunk, 1] = x_base[start_samp:start_samp+chunk]
                    else:
                        outdata_buf[:chunk, 0] = x_corr[start_samp:start_samp+chunk]

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
                    f_mid, results = engine.process_input_block(sig_in, b_idx, ref_in_block=ref_in)
                    if engine.last_block_was_valid:
                        accumulated_results[b_idx, :] = results[:self.max_harmonic]
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
            # Interpolate real and imaginary parts separately to avoid wrapping issues
            real_func = interp1d(raw_freqs_sorted, raw_results_sorted[:, n-1].real, kind='linear', fill_value='extrapolate')
            imag_func = interp1d(raw_freqs_sorted, raw_results_sorted[:, n-1].imag, kind='linear', fill_value='extrapolate')

            H_meas[n] = real_func(self.meas_freqs) + 1j * imag_func(self.meas_freqs)

        # Save measurement result
        self.iteration_results.append({
            'iter': iter_idx,
            'H': H_meas
        })

        # 4. Calculate adaptive correction for next iteration
        # Update equation: F_corr[n] = F_corr[n] - mu * Hn(f) / H1(n * f)
        if iter_idx == 0:
            # Store initial linear transfer function H0_1
            self.H0_1 = H_meas[1].copy()

        # Helper to interpolate linear transfer function H1(f) at higher frequencies (up to max_harmonic * f_end)
        # In offline mode, we use analytical. In real-hardware, we extrapolate from H0_1.
        def get_H0_1_interpolated(f_target_array):
            if self.args.offline:
                return get_analytical_H1(f_target_array, self.fs)
            else:
                # Extrapolate linear H1 using nearest values or linear logic
                # To prevent division by zero, clamp minimum magnitude
                H_func_real = interp1d(self.meas_freqs, self.H0_1.real, kind='linear', fill_value='extrapolate')
                H_func_imag = interp1d(self.meas_freqs, self.H0_1.imag, kind='linear', fill_value='extrapolate')
                h_vals = H_func_real(f_target_array) + 1j * H_func_imag(f_target_array)
                # Safeguard magnitude
                mag = np.abs(h_vals)
                min_mag = 1e-4 * np.max(np.abs(self.H0_1))
                bad_mask = mag < min_mag
                if np.any(bad_mask):
                    h_vals[bad_mask] = (h_vals[bad_mask] / (mag[bad_mask] + 1e-12)) * min_mag
                return h_vals

        print(f"[*] Calculating adaptive updates (learning rate mu = {self.mu})...")
        for n in range(2, self.max_harmonic + 1):
            Hn_vals = H_meas[n]

            # We need the linear response at the harmonic frequency: n * f
            H1_nf_vals = get_H0_1_interpolated(n * self.meas_freqs)

            # Delta correction: - Hn(f) / H1(n * f)
            delta_corr = - Hn_vals / H1_nf_vals

            # Apply update with learning rate mu: F = F + mu * delta_corr
            self.F_corr[n] += self.mu * delta_corr

            # Print average distortion level
            avg_dist = 20 * np.log10(np.mean(np.abs(Hn_vals)) + 1e-12)
            print(f"    - H{n} Average Level: {avg_dist:.1f} dB")

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
            min_analysis_window=self.min_analysis_window
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
        recorded_data[:len(x_corr), 1] = x_base
        recorded_data[:len(x_corr), 0] = offline_dut_system(x_corr, self.fs)

        for b in range(max_blocks):
            start_idx = b * frames
            end_idx = min(start_idx + frames, total_len)

            indata_block = np.zeros((frames, 2), dtype=np.float32)
            chunk_len = end_idx - start_idx
            if chunk_len > 0:
                indata_block[:chunk_len, :] = recorded_data[start_idx:end_idx, :]

            sig_in = indata_block[:, [self.args.ch_sig]]
            ref_in = indata_block[:, [self.args.ch_ref]]

            f_mid, results = engine.process_input_block(sig_in, b, ref_in_block=ref_in)
            if engine.last_block_was_valid:
                accumulated_results[b, :] = results[:self.max_harmonic]
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
            real_func = interp1d(raw_freqs_sorted, raw_results_sorted[:, n-1].real, kind='linear', fill_value='extrapolate')
            imag_func = interp1d(raw_freqs_sorted, raw_results_sorted[:, n-1].imag, kind='linear', fill_value='extrapolate')
            H_meas[n] = real_func(self.meas_freqs) + 1j * imag_func(self.meas_freqs)

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

        initial = self.iteration_results[0]['H']
        final = self.iteration_results[-1]['H']

        for n in range(2, self.max_harmonic + 1):
            db_init = 20 * np.log10(np.mean(np.abs(initial[n])) + 1e-12)
            db_final = 20 * np.log10(np.mean(np.abs(final[n])) + 1e-12)
            reduction = db_final - db_init
            print(f"H{n} Distortion: Iteration 0: {db_init:.1f} dB -> Final Iteration: {db_final:.1f} dB | Reduction: {reduction:.1f} dB")

        print("====================================================")

        # Save plots
        plt.figure(figsize=(12, 10))

        # Plot Magnitude vs Frequency for each iteration
        plt.subplot(2, 1, 1)
        colors = ['blue', 'orange', 'green', 'red', 'purple', 'brown']

        # Plot fundamental from iteration 0
        plt.semilogx(self.meas_freqs, 20*np.log10(np.abs(initial[1])), label="H1 (Linear)", color='black', linewidth=2)

        # Plot harmonics for each iteration
        for iter_idx in range(self.args.iterations + 1):
            H_data = self.iteration_results[iter_idx]['H']
            alpha_val = 0.3 if iter_idx < self.args.iterations else 1.0
            line_style = ':' if iter_idx == 0 else '-'
            linewidth = 1.0 if iter_idx < self.args.iterations else 1.5

            for n in range(2, min(4, self.max_harmonic + 1)): # Plot H2 and H3 for clarity
                lbl = f"H{n} Iter {iter_idx}" if iter_idx in [0, self.args.iterations] else None
                c_idx = (n - 2) * 2 + (0 if iter_idx == 0 else 1)
                color = colors[c_idx % len(colors)]
                plt.semilogx(
                    self.meas_freqs, 
                    20*np.log10(np.abs(H_data[n]) + 1e-12), 
                    label=lbl, 
                    color=color, 
                    alpha=alpha_val, 
                    linestyle=line_style,
                    linewidth=linewidth
                )

        plt.title("Adaptive Predistortion Sweep: Harmonic Level per Iteration")
        plt.xlabel("Frequency (Hz)")
        plt.ylabel("Response Level (dB)")
        plt.grid(True, which="both")
        plt.legend()
        plt.ylim(-120, 5)

        # Plot Distortion reduction trajectory across iterations
        plt.subplot(2, 1, 2)
        iters = np.arange(self.args.iterations + 1)
        for n in range(2, self.max_harmonic + 1):
            traj = []
            for iter_idx in iters:
                H_data = self.iteration_results[iter_idx]['H']
                traj.append(20*np.log10(np.mean(np.abs(H_data[n])) + 1e-12))
            plt.plot(iters, traj, 'o-', label=f"H{n} average level")

        plt.title("Harmonic Distortion Trajectory")
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
            'metadata': {
                'start_freq': self.start_freq,
                'end_freq': self.end_freq,
                'duration': self.duration,
                'amplitude_db': self.args.amplitude_db,
                'iterations': self.args.iterations,
                'mu': self.mu,
                'offline': self.args.offline,
                'sweep_mode': getattr(self.args, 'sweep_mode', 'forward')
            },
            'trajectories': {
                f"H{n}": [float(20*np.log10(np.mean(np.abs(self.iteration_results[iter_idx]['H'][n])) + 1e-12))
                         for iter_idx in range(self.args.iterations + 1)]
                for n in range(2, self.max_harmonic + 1)
            }
        }
        json_path = os.path.join(project_root, "scripts", "adaptive_sweep_verification_results.json")
        with open(json_path, 'w', encoding='utf-8') as f:
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
    parser.add_argument("--iterations", type=int, default=3, help="Number of adaptive correction iterations")
    parser.add_argument("--mu", type=float, default=0.5, help="Learning rate (0 < mu <= 1.0) to prevent overshoot")
    parser.add_argument("--analysis-cycles", type=float, default=12.0, help="Analysis cycles for lock-in tracking")
    parser.add_argument("--min-window", type=float, default=0.012, help="Minimum analysis window in seconds")
    parser.add_argument("--meas-points", type=int, default=300, help="Number of measurement points")
    parser.add_argument("--profile", type=str, choices=["quick", "normal", "high"], default=None, help="Use preset optimization profile")
    parser.add_argument("--sweep-mode", type=str, choices=["forward", "reverse", "bidirectional"], default="forward", help="Sweep direction mode (forward, reverse, bidirectional)")
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
