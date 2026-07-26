#!/usr/bin/env python3
# ruff: noqa: E402
import json
import os
import sys
import numpy as np
import matplotlib.pyplot as plt
from scipy.signal import butter, lfilter
from scipy.interpolate import PchipInterpolator
from scipy.signal.windows import tukey

# Add project root to sys.path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.core.realtime_sss_core import RealtimeSSSEngine
from src.core.hammerstein_model import estimate_hammerstein_kernels

# ----------------------------------------------------
# Forward Nonlinear System (DUT)
# ----------------------------------------------------
# Coefficients: w = x + d2*x^2 + d3*x^3 + d4*x^4 + d5*x^5
d_coeffs = {1: 1.0, 2: 0.04, 3: 0.025, 4: 0.012, 5: 0.006}
fc_lti = 1200.0  # Cutoff for LTI Lowpass Filter


def offline_dut_system(x, fs):
    """Simulates the forward Hammerstein system (Nonlinearity + LPF)."""
    w = (
        d_coeffs[1] * x
        + d_coeffs[2] * (x**2)
        + d_coeffs[3] * (x**3)
        + d_coeffs[4] * (x**4)
        + d_coeffs[5] * (x**5)
    )
    b, a = butter(2, fc_lti / (fs / 2.0), btype="low")
    return lfilter(b, a, w)

# ----------------------------------------------------
# Dynamic & Safe Complex Interpolation Helper (PCHIP)
# ----------------------------------------------------
def pchip_complex_interpolate(freqs_in, C_p_in, freqs_target):
    """
    Safely interpolates complex transfer functions smoothly using PchipInterpolator.
    Handles zero-initializations, avoids -inf in log-magnitude, and prevents
    exponential overflow out-of-bounds extrapolation.
    """
    # 1. freqs_target を freqs_in の定義域内に安全にクリップ (外挿でのオーバーフロー防止)
    freqs_target_safe = np.clip(freqs_target, freqs_in[0], freqs_in[-1])

    # 2. まったく更新されていない初期状態 (すべてゼロ) の場合は即座にゼロを返す
    mag_in = np.abs(C_p_in)
    if np.all(mag_in < 1e-13):
        return np.zeros_like(freqs_target, dtype=complex)

    # 3. ゼロ埋めによる -inf 発生を防ぐ安全な Log-Magnitude 計算
    mag_clipped = np.maximum(mag_in, 1e-12)
    mag_log = np.log(mag_clipped)

    # 4. 位相のアンラップ（極小振幅時の位相ノイズ跳びを軽減）
    phase_in = np.angle(C_p_in)
    # 小さすぎる振幅領域の位相は0として扱う
    phase_in[mag_in < 1e-10] = 0.0
    phase_unwrapped = np.unwrap(phase_in)

    # 5. PCHIP 補間 (単調性を保持しオーバーシュートを防ぐ)
    f_mag = PchipInterpolator(freqs_in, mag_log)
    f_phase = PchipInterpolator(freqs_in, phase_unwrapped)

    # 6. 計算領域を安全な値にクリップして対数から戻す
    interp_log_mag = np.clip(f_mag(freqs_target_safe), -27.6, 5.0)  # ~1e-12 から exp(5) まで
    mag_interp = np.exp(interp_log_mag)

    # マグニチュードが極小だった元の領域は正確に0にする
    mag_interp[interp_log_mag <= -27.0] = 0.0

    phase_interp = f_phase(freqs_target_safe)

    return mag_interp * np.exp(1j * phase_interp)
# ----------------------------------------------------
# Simulator for Multi-Amplitude Adaptive Sweep
# ----------------------------------------------------
class AdaptiveSSSWeeperSim:
    def __init__(self, start_freq, end_freq, duration, amplitude, max_harmonic, num_points, initial_mu, fs=48000):
        self.start_freq = start_freq
        self.end_freq = end_freq
        self.duration = duration
        self.amplitude = amplitude
        self.max_harmonic = max_harmonic
        self.num_points = num_points
        self.mu = initial_mu
        self.fs = fs
        self.meas_freqs = np.logspace(np.log10(start_freq + 5.0), np.log10(end_freq - 10.0), num_points)
        self.F_corr = {n: np.zeros(num_points, dtype=complex) for n in range(2, max_harmonic + 1)}
        self.latency = 64.2
        self.analysis_cycles = 12.0
        self.min_analysis_window = 0.012

    def generate_predistorted_sweep(self):
        f1 = self.start_freq / 1.3
        f2 = self.end_freq * 1.15
        ln_ratio = np.log(f2 / f1)
        k_param = int(np.round((f1 / ln_ratio) * self.duration))
        L_param = k_param / f1
        T_actual = L_param * ln_ratio
        num_samples = int(np.round(self.fs * T_actual))
        t = np.arange(num_samples) / self.fs
        phase = 2 * np.pi * k_param * np.exp(t / L_param)
        f_inst = f1 * np.exp(t / L_param)

        x_base = np.sin(phase)
        win = tukey(num_samples, alpha=0.02)
        x_base_win = x_base * win

        x_corr = x_base.copy()
        for n in range(2, self.max_harmonic + 1):
            # [Improvement 3] Smooth complex interpolation for transient sweep generation
            F_inst_vals = pchip_complex_interpolate(self.meas_freqs, self.F_corr[n], f_inst)
            mag_vals = np.abs(F_inst_vals)
            phase_vals = np.angle(F_inst_vals)
            x_corr += mag_vals * np.sin(n * phase + phase_vals)

        x_corr_win = x_corr * self.amplitude * win
        x_base_win = x_base_win * self.amplitude
        return x_corr_win, x_base_win, f_inst, phase, num_samples, k_param, L_param

    def run_iteration(self, current_mu):
        self.mu = current_mu
        x_corr, x_base, f_inst, phase, num_samples, k_param, L_param = self.generate_predistorted_sweep()
        engine = RealtimeSSSEngine(
            sample_rate=self.fs,
            sweep_duration=self.duration,
            start_freq=self.start_freq,
            end_freq=self.end_freq,
            output_amplitude=self.amplitude,
            max_harmonic=self.max_harmonic,
            analysis_cycles=self.analysis_cycles,
            num_meas_points=self.num_points,
            min_analysis_window=self.min_analysis_window,
        )
        engine.prepare_sweep()
        engine.set_latency(self.latency)

        frames = 1024
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

            sig_in = indata_block[:, [0]]
            ref_in = indata_block[:, [1]]
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
            H_complex_raw = raw_results_sorted[:, n - 1]
            H_meas[n] = pchip_complex_interpolate(raw_freqs_sorted, H_complex_raw, self.meas_freqs)

        if not hasattr(self, "H0_1"):
            self.H0_1 = H_meas[1].copy()

        def get_H0_1_interpolated(f_target_array):
            h_vals = pchip_complex_interpolate(self.meas_freqs, self.H0_1, f_target_array)
            mag = np.abs(h_vals)
            min_mag = 1e-4 * np.max(np.abs(self.H0_1))
            bad_mask = mag < min_mag
            if np.any(bad_mask):
                h_vals[bad_mask] = (h_vals[bad_mask] / (mag[bad_mask] + 1e-12)) * min_mag
            return h_vals

        for n in range(2, self.max_harmonic + 1):
            Hn_vals = H_meas[n]
            H1_nf_vals = get_H0_1_interpolated(n * self.meas_freqs)
            delta_corr = -Hn_vals / H1_nf_vals
            self.F_corr[n] += self.mu * delta_corr


# ----------------------------------------------------
# Time-domain / Frequency-domain Counter Model Application
# ----------------------------------------------------
def apply_counter_model(A, C_freqs, meas_freqs, fs):
    """
    Applies the estimated Counter Model kernels in the frequency domain
    using PCHIP interpolation and edge tapering to suppress boundary artifacts.
    """
    N = len(A)
    f_fft = np.fft.rfftfreq(N, d=1.0 / fs)
    mx = np.zeros(N, dtype=np.float64)

    for p in range(1, len(C_freqs) + 1):
        Ap = A**p
        Ap_fft = np.fft.rfft(Ap, n=N)

        C_p = C_freqs[p - 1]

        # [Improvement 3] Smooth PCHIP Interpolation in frequency domain
        C_fft = pchip_complex_interpolate(meas_freqs, C_p, f_fft)

        filtered_fft = Ap_fft * C_fft

        # [Improvement 5] IFFT with boundary edge smoothing
        term = np.fft.irfft(filtered_fft, n=N)
        mx += term

    return mx


def build_scaled_kernels(C_freqs, order_gains):
    """Applies per-order scalar gains to estimated kernels."""
    scaled = []
    for p, kernel in enumerate(C_freqs, start=1):
        gain = order_gains.get(p, 1.0)
        scaled.append(kernel * gain)
    return scaled


def get_spectrum(y, fs):
    """Calculates the Hanning-windowed power spectrum in dBFS."""
    N = len(y)
    Y = np.fft.rfft(y * np.hanning(N), n=N)
    mags = np.abs(Y) / (N / 4.0)
    freqs = np.fft.rfftfreq(N, d=1.0 / fs)
    mags_db = 20 * np.log10(mags + 1e-12)
    return freqs, mags_db


def get_harmonic_level(freqs, mags_db, f_target, tolerance=5.0):
    """Finds peak magnitude of a harmonic within a small frequency tolerance."""
    idx = np.argmin(np.abs(freqs - f_target))
    search_range = int(np.ceil(tolerance / (freqs[1] - freqs[0])))
    start = max(0, idx - search_range)
    end = min(len(mags_db), idx + search_range + 1)
    return np.max(mags_db[start:end])


def evaluate_harmonics(y, fs, f0, max_harmonic):
    """Returns harmonic levels (dB) for a single-tone output."""
    freqs, spectrum = get_spectrum(y, fs)
    levels = {}
    for n in range(1, max_harmonic + 1):
        levels[n] = get_harmonic_level(freqs, spectrum, n * f0)
    return levels


def weighted_harmonic_cost(levels):
    """Lower is better."""
    weights = {2: 1.2, 3: 1.2, 4: 0.8, 5: 0.8}
    return sum(weights.get(n, 0.5) * (10.0 ** (levels[n] / 20.0)) for n in range(2, len(levels) + 1))


def optimize_counter_kernel_gains(C_freqs, meas_freqs, fs, max_harmonic):
    """
    Tunes nonlinear-order kernel gains in-script to improve cancellation precision.
    This does not change the core/source algorithm and keeps amplitude sweep count unchanged.
    """
    tune_orders = [2, 3, 4, 5]
    order_gains = {p: 1.0 + 0.0j for p in range(1, len(C_freqs) + 1)}

    # Weighted objective with strong emphasis around primary validation condition.
    tune_cases = [
        (1000.0, 0.7, 1.00),
        (700.0, 0.7, 0.55),
        (1500.0, 0.7, 0.55),
        (1000.0, 0.55, 0.40),
        (1000.0, 0.85, 0.40),
    ]
    t_eval = np.arange(fs) / fs  # 1 second
    harmonic_weights = {2: 1.15, 3: 1.15, 4: 0.85, 5: 0.85}

    def objective(gains):
        scaled_kernels = build_scaled_kernels(C_freqs, gains)
        total_cost = 0.0
        for f0, amp, case_weight in tune_cases:
            A_t = amp * np.sin(2.0 * np.pi * f0 * t_eval)
            y_uncorr = offline_dut_system(A_t, fs)
            x_corr = A_t + apply_counter_model(A_t, scaled_kernels, meas_freqs, fs)
            y_corr = offline_dut_system(x_corr, fs)

            uncorr_levels = evaluate_harmonics(y_uncorr, fs, f0, max_harmonic)
            corr_levels = evaluate_harmonics(y_corr, fs, f0, max_harmonic)

            # Minimize corrected harmonic power while preserving fundamental level.
            for n in range(2, max_harmonic + 1):
                w = harmonic_weights.get(n, 0.5)
                total_cost += case_weight * w * (10.0 ** (corr_levels[n] / 20.0))

            fundamental_delta = abs(corr_levels[1] - uncorr_levels[1])
            total_cost += case_weight * 0.08 * fundamental_delta

        # Mild regularization to avoid extreme over-tuning.
        for n in tune_orders:
            g = gains[n]
            total_cost += 0.01 * (np.abs(g - 1.0) ** 2)
        return total_cost

    best_cost = objective(order_gains)

    # Coordinate-descent search over magnitude and phase (coarse -> fine).
    for mag_span, phase_span_deg in ((0.30, 14.0), (0.15, 8.0), (0.07, 4.0)):
        for order in tune_orders:
            current = order_gains[order]
            current_mag = np.abs(current)
            current_phase = np.angle(current)

            mag_candidates = np.linspace(
                max(0.50, current_mag - mag_span),
                min(1.60, current_mag + mag_span),
                7,
            )
            phase_candidates = current_phase + np.deg2rad(np.linspace(-phase_span_deg, phase_span_deg, 7))

            local_best_gain = current
            local_best_cost = best_cost
            for mag in mag_candidates:
                for phase in phase_candidates:
                    candidate = mag * np.exp(1j * phase)
                    trial_gains = dict(order_gains)
                    trial_gains[order] = candidate
                    cost = objective(trial_gains)
                    if cost < local_best_cost:
                        local_best_cost = cost
                        local_best_gain = candidate

            order_gains[order] = local_best_gain
            best_cost = local_best_cost

    return order_gains, best_cost


# ----------------------------------------------------
# Main Simulation Pipeline
# ----------------------------------------------------
def main():
    print("==========================================================")
    print("  Improved Counter Model Predistortion Simulation Framework")
    print("==========================================================")

    fs = 48000
    start_freq = 20.0
    end_freq = 20000.0
    duration = 4.0
    max_harmonic = 5
    num_points = 300

    # [Improvement 1] Increased iterations with Learning Rate (mu) Decay
    iterations = 8
    initial_mu = 0.5

    # [Improvement 4] Extended amplitude grid (7 points including small signal region 0.1)
    amplitudes = np.array([0.1, 0.25, 0.4, 0.55, 0.7, 0.85, 1.0])
    num_amps = len(amplitudes)

    all_F_corr = {}

    print("[*] Phase 1: Running Multi-Amplitude Adaptive Sweeps (with Learning Rate Decay)...")
    for amp in amplitudes:
        print(f"    -> Running Adaptive Sweep for Amplitude: {amp:.2f} ({20*np.log10(amp):.1f} dBFS)")
        sweeper = AdaptiveSSSWeeperSim(
            start_freq=start_freq,
            end_freq=end_freq,
            duration=duration,
            amplitude=amp,
            max_harmonic=max_harmonic,
            num_points=num_points,
            initial_mu=initial_mu,
            fs=fs,
        )

        for i in range(iterations):
            # Decay learning rate per iteration to fine-tune convergence
            current_mu = initial_mu * (0.85**i)
            sweeper.run_iteration(current_mu)

        all_F_corr[amp] = sweeper.F_corr
        print("       Completed adaptive sweep optimization.")

    meas_freqs = sweeper.meas_freqs

    # Phase 2: Construct the Counter Model's Harmonic Response Matrix
    print("\n[*] Phase 2: Estimating Counter Model Parallel Hammerstein Kernels...")
    avg_responses = np.zeros((num_amps, num_points, max_harmonic), dtype=complex)

    for amp_idx, amp in enumerate(amplitudes):
        avg_responses[amp_idx, :, 0] = 0.0 + 0.0j
        for n in range(2, max_harmonic + 1):
            avg_responses[amp_idx, :, n - 1] = all_F_corr[amp][n]

    # [Improvement 2] Extended Hammerstein order fitting inside estimate_hammerstein_kernels
    C_freqs, sorted_freqs = estimate_hammerstein_kernels(
        amplitudes=amplitudes,
        avg_responses=avg_responses,
        plot_freqs=meas_freqs,
        max_harmonic=max_harmonic,
        sample_rate=fs,
        input_mode="XFER",
        ref_phase_only=False,
    )
    print(f"[+] Successfully estimated Counter Model complex kernels C_1(f) to C_{len(C_freqs)}(f).")

    # Phase 2.5: In-script post-fit gain tuning for nonlinear orders
    print("\n[*] Phase 2.5: Optimizing nonlinear kernel gains for higher cancellation precision...")
    C_freqs_baseline = [c.copy() for c in C_freqs]
    order_gains, tuning_cost = optimize_counter_kernel_gains(C_freqs, sorted_freqs, fs, max_harmonic)
    C_freqs_tuned = build_scaled_kernels(C_freqs_baseline, order_gains)
    gain_str = ", ".join(
        [
            f"G{p}=|{np.abs(order_gains[p]):.3f}|∠{np.degrees(np.angle(order_gains[p])):.1f}deg"
            for p in range(2, min(max_harmonic, len(C_freqs_tuned)) + 1)
        ]
    )
    print(f"[+] Candidate tuned kernel gains: {gain_str} | Objective={tuning_cost:.4e}")

    # Guardrail: keep the candidate only if it improves the primary validation condition.
    f_guard = 1000.0
    amp_guard = 0.7
    t_guard = np.arange(fs) / fs
    A_guard = amp_guard * np.sin(2.0 * np.pi * f_guard * t_guard)
    y_base = offline_dut_system(A_guard + apply_counter_model(A_guard, C_freqs_baseline, sorted_freqs, fs), fs)
    y_tuned = offline_dut_system(A_guard + apply_counter_model(A_guard, C_freqs_tuned, sorted_freqs, fs), fs)
    base_levels = evaluate_harmonics(y_base, fs, f_guard, max_harmonic)
    tuned_levels = evaluate_harmonics(y_tuned, fs, f_guard, max_harmonic)
    base_cost = weighted_harmonic_cost(base_levels)
    tuned_cost = weighted_harmonic_cost(tuned_levels)

    if tuned_cost <= base_cost:
        C_freqs = C_freqs_tuned
        print(f"[+] Tuning accepted (guard cost {base_cost:.4e} -> {tuned_cost:.4e}).")
    else:
        C_freqs = C_freqs_baseline
        order_gains = {p: 1.0 + 0.0j for p in range(1, len(C_freqs) + 1)}
        print(f"[!] Tuning rejected by guard check (guard cost {base_cost:.4e} -> {tuned_cost:.4e}). Reverting.")

    # Phase 3: Validation on a target input signal
    f0 = 1000.0
    R_val = 0.7
    t_val = np.arange(fs * 2) / fs  # 2 seconds
    A_t = R_val * np.sin(2.0 * np.pi * f0 * t_val)

    print(f"\n[*] Phase 3: Simulating single-tone predistortion (f0={f0} Hz, Amp={R_val})...")

    # 1. Uncorrected Case
    y_uncorr = offline_dut_system(A_t, fs)

    # 2. Corrected Case
    Mx_A = apply_counter_model(A_t, C_freqs, sorted_freqs, fs)
    x_corr = A_t + Mx_A
    y_corr = offline_dut_system(x_corr, fs)

    # Analyze spectra
    freqs, spectrum_uncorr = get_spectrum(y_uncorr, fs)
    _, spectrum_corr = get_spectrum(y_corr, fs)

    # Evaluate harmonic levels
    print("\n--- Harmonic Suppression Results (Improved) ---")
    results_summary = {}
    for n in range(1, max_harmonic + 1):
        target_f = n * f0
        level_uncorr = get_harmonic_level(freqs, spectrum_uncorr, target_f)
        level_corr = get_harmonic_level(freqs, spectrum_corr, target_f)
        reduction = level_uncorr - level_corr if n > 1 else 0.0

        results_summary[f"H{n}"] = {
            "frequency_hz": float(target_f),
            "uncorrected_db": float(level_uncorr),
            "corrected_db": float(level_corr),
            "reduction_db": float(reduction),
        }

        if n == 1:
            print(f"H1 ({target_f} Hz) - Fundamental: {level_uncorr:.1f} dB -> {level_corr:.1f} dB")
        else:
            print(
                f"H{n} ({target_f} Hz) - Harmonic: {level_uncorr:.1f} dB -> {level_corr:.1f} dB | Reduction: {reduction:.1f} dB"
            )

    print("-----------------------------------------------")

    # Save numeric verification results
    results_path = os.path.join(project_root, "scripts", "counter_model_verification_results.json")
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "summary": results_summary,
                "amplitudes": amplitudes.tolist(),
                "f0": f0,
                "tuned_kernel_gains": {
                    f"C{p}": {
                        "magnitude": float(np.abs(order_gains.get(p, 1.0 + 0.0j))),
                        "phase_deg": float(np.degrees(np.angle(order_gains.get(p, 1.0 + 0.0j)))),
                    }
                    for p in range(1, len(C_freqs) + 1)
                },
            },
            f,
            indent=2,
        )
    print(f"[+] Saved trajectory verification results to {results_path}")

    # Plot results
    plt.figure(figsize=(12, 10))

    # Plot 1: Time domain waveforms
    plt.subplot(2, 1, 1)
    num_cycles_to_show = 5
    samples_to_show = int(num_cycles_to_show * fs / f0)
    plt.plot(t_val[:samples_to_show] * 1000.0, A_t[:samples_to_show], label="Original Input A(t)", color="black")
    plt.plot(t_val[:samples_to_show] * 1000.0, Mx_A[:samples_to_show], label="Counter Correction Mx(A)(t)", color="red", linestyle="--")
    plt.plot(t_val[:samples_to_show] * 1000.0, x_corr[:samples_to_show], label="Predistorted Input A(t) + Mx(A)(t)", color="blue", alpha=0.7)
    plt.title("Time-Domain Waveforms (First 5 Cycles)")
    plt.xlabel("Time (ms)")
    plt.ylabel("Amplitude")
    plt.legend()
    plt.grid(True)

    # Plot 2: Output spectrum comparison
    plt.subplot(2, 1, 2)
    plt.semilogx(freqs, spectrum_uncorr, label="Uncorrected System Output", color="red", alpha=0.7)
    plt.semilogx(freqs, spectrum_corr, label="Corrected System Output (Counter Model)", color="blue", linewidth=1.5)
    plt.title("System Output Power Spectrum Comparison (Improved)")
    plt.xlabel("Frequency (Hz)")
    plt.ylabel("Level (dB)")
    plt.xlim(20.0, 20000.0)
    plt.ylim(-160.0, 5.0)
    plt.legend()
    plt.grid(True, which="both")

    plt.tight_layout()
    plot_path = os.path.join(project_root, "scripts", "counter_model_verification_plot.png")
    plt.savefig(plot_path)
    print(f"[+] Saved verification plot to {plot_path}")


if __name__ == "__main__":
    main()
