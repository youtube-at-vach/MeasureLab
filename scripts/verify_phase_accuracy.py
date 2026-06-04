#!/usr/bin/env python3
import os
import sys
import numpy as np

# Ensure src is on python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.core.nonlinear_analyzer_core import (
    generate_sss_and_inverse,
    deconvolve_signal,
    process_amplitude_responses,
)

def apply_frequency_domain_filter(x, fs, filter_func):
    """Applies a frequency domain transfer function H(f) to signal x."""
    N = len(x)
    X = np.fft.rfft(x)
    freqs = np.fft.rfftfreq(N, 1.0 / fs)
    H = filter_func(freqs)
    Y = X * H
    return np.fft.irfft(Y, n=N)

def run_measurement_simulation(sample_rate, sweep_duration, start_freq, end_freq, amplitudes, a, filters, delays, P=5):
    """Simulates loopback measurement and returns separated phase/magnitude."""
    sss, _ = generate_sss_and_inverse(sample_rate, sweep_duration, start_freq, end_freq)

    responses_meas = []
    responses_ref = []
    padding_samples = int(0.5 * sample_rate)

    for amp in amplitudes:
        x_sig = amp * sss
        y_sig = np.zeros_like(x_sig)

        for p in range(1, P + 1):
            x_p = a[p] * (x_sig ** p)

            # Combine filter and individual delay
            def sim_filter_p(f, order=p):
                h_filter = filters[order](f)
                delay = np.exp(-1j * 2 * np.pi * f * delays[order] / sample_rate)
                return h_filter * delay

            y_sig += apply_frequency_domain_filter(x_p, sample_rate, sim_filter_p)

        x_sig_padded = np.concatenate([x_sig, np.zeros(padding_samples)])
        y_sig_padded = np.concatenate([y_sig, np.zeros(padding_samples)])

        ir_ref = deconvolve_signal(x_sig_padded, sss)
        ir_meas = deconvolve_signal(y_sig_padded, sss)

        responses_ref.append(ir_ref)
        responses_meas.append(ir_meas)

    return process_amplitude_responses(
        responses_meas,
        responses_ref,
        sample_rate,
        start_freq,
        end_freq,
        input_mode="XFER",
        latency_sec=0.0,
        sweep_duration=sweep_duration,
        P=P,
        amplitudes=amplitudes,
    )

def run_phase_verification():
    print("====================================================")
    print("  Nonlinear System Analyzer Phase Accuracy Test     ")
    print("  (Baseline Calibration Phase Evaluation)            ")
    print("====================================================")

    sample_rate = 44100
    sweep_duration = 3.0
    start_freq = 20.0
    end_freq = 20000.0
    P = 5

    # 1. Setup Polynomial Weights
    a = {1: 1.0, 2: 0.1, 3: 0.08, 4: 0.04, 5: 0.02}

    # Define pure filters (without delays)
    def H1_func(f):
        fc = 4000.0
        return 1.0 / (1.0 + 1j * (f / fc))

    def H2_func(f):
        fc = 1000.0
        with np.errstate(divide='ignore', invalid='ignore'):
            hpf = (1j * (f / fc)) / (1.0 + 1j * (f / fc))
            hpf = np.nan_to_num(hpf)
        return hpf

    def H3_func(f):
        return np.ones_like(f, dtype=complex)

    def H4_func(f):
        return np.ones_like(f, dtype=complex)

    def H5_func(f):
        return np.ones_like(f, dtype=complex)

    filters = {1: H1_func, 2: H2_func, 3: H3_func, 4: H4_func, 5: H5_func}

    max_amp = 0.5
    num_amplitudes = 6
    amplitudes = np.linspace(0.2, 1.0, num_amplitudes) * max_amp

    # --- Step 1: Run Baseline (delays = 0) ---
    print("Running baseline simulation (delays = 0) for calibration...")
    zero_delays = {1: 0.0, 2: 0.0, 3: 0.0, 4: 0.0, 5: 0.0}
    valid_freqs, mags_zero, phases_zero, _, _ = run_measurement_simulation(
        sample_rate, sweep_duration, start_freq, end_freq, amplitudes, a, filters, zero_delays, P
    )

    # Record systematic phase offset curves
    stable_mask = (valid_freqs >= 100.0) & (valid_freqs <= 15000.0)
    eval_freqs = valid_freqs[stable_mask]

    systematic_phase_curves = {}
    for p in range(1, P + 1):
        h_key = f"h{p}"
        # Theoretical filter phase at p * f
        H_theory_filter = filters[p](p * eval_freqs)
        phase_theory_rad = np.unwrap(np.angle(H_theory_filter))
        phase_theory_deg = np.degrees(phase_theory_rad)
        phase_theory_deg = (phase_theory_deg + 180) % 360 - 180

        # Systematic offset = measured baseline phase - theoretical filter phase
        meas_baseline = phases_zero[h_key][stable_mask]
        diff = meas_baseline - phase_theory_deg
        diff = (diff + 180) % 360 - 180
        systematic_phase_curves[p] = diff

    # --- Step 2: Run Actual Test (with delay values) ---
    test_delays = {
        1: 5.0,
        2: 8.0,
        3: 12.0,
        4: 15.0,
        5: 20.0
    }
    print(f"\nRunning test simulation with delays {test_delays} samples...")
    valid_freqs, mags_meas, phases_meas, time_ms, separated_kernels_data = run_measurement_simulation(
        sample_rate, sweep_duration, start_freq, end_freq, amplitudes, a, filters, test_delays, P
    )

    # --- Step 3: Evaluate Accuracy ---
    print("\nEvaluating phase and magnitude reconstruction accuracy (stable band: 100 Hz to 15 kHz):")
    errors = {}

    for p in range(1, P + 1):
        h_key = f"h{p}"

        # Theoretical delay: rel_delay = D_p (delay of the harmonic component itself)
        rel_delay = test_delays[p]
        H_theory_filter = filters[p](p * eval_freqs)
        H_theory_delay = np.exp(-1j * 2 * np.pi * eval_freqs * rel_delay / sample_rate)
        H_theory = a[p] * H_theory_filter * H_theory_delay

        mag_theory_db = 20 * np.log10(np.abs(H_theory) + 1e-12)
        phase_theory_rad = np.unwrap(np.angle(H_theory))
        phase_theory_deg = np.degrees(phase_theory_rad)
        phase_theory_deg = (phase_theory_deg + 180) % 360 - 180

        # Compensate measured phase using baseline systematic offsets
        meas_raw = phases_meas[h_key][stable_mask]
        phase_meas_compensated = meas_raw - systematic_phase_curves[p]
        phase_meas_compensated = (phase_meas_compensated + 180) % 360 - 180

        # Compute errors
        mag_meas_db = mags_meas[h_key][stable_mask]
        mag_diff = np.abs(mag_meas_db - mag_theory_db)

        phase_diff = np.abs(phase_meas_compensated - phase_theory_deg)
        phase_diff = np.minimum(phase_diff, 360.0 - phase_diff)

        mae_mag = np.mean(mag_diff)
        max_mag = np.max(mag_diff)
        mae_phase = np.mean(phase_diff)
        max_phase = np.max(phase_diff)

        errors[p] = {
            "mae_mag": mae_mag,
            "mae_phase": mae_phase
        }

        print(f"\nOrder {p} ({h_key}):")
        print(f"  Magnitude Error: MAE = {mae_mag:.4f} dB, Max = {max_mag:.4f} dB")
        print(f"  Phase Error:     MAE = {mae_phase:.4f} deg, Max = {max_phase:.4f} deg")

        for test_f in [1000.0, 5000.0, 10000.0]:
            f_idx = np.argmin(np.abs(eval_freqs - test_f))
            actual_f = eval_freqs[f_idx]
            print(f"    At {actual_f:.1f} Hz -> Theory Phase: {phase_theory_deg[f_idx]:+.2f}°, Meas (Compensated): {phase_meas_compensated[f_idx]:+.2f}°, Diff: {phase_diff[f_idx]:+.2f}°")

    # Save visualization if matplotlib is available
    try:
        import matplotlib.pyplot as plt
        print("\nMatplotlib found. Saving plot to 'scripts/phase_accuracy_report.png'...")

        fig, axes = plt.subplots(5, 2, figsize=(14, 18), sharex='col')
        colors = ['#4ba3e3', '#2b8c56', '#e68c14', '#c832a0', '#d9534f']

        # Interpolate systematic offsets for all valid_freqs (for plotting)
        for idx in range(P):
            p = idx + 1
            h_key = f"h{p}"

            # Recalculate theory for full plotting range
            rel_delay = test_delays[p]
            H_theory_filter = filters[p](p * valid_freqs)
            H_theory_delay = np.exp(-1j * 2 * np.pi * valid_freqs * rel_delay / sample_rate)
            H_theory = a[p] * H_theory_filter * H_theory_delay
            mag_theory_db = 20 * np.log10(np.abs(H_theory) + 1e-12)
            phase_theory_rad = np.unwrap(np.angle(H_theory))
            phase_theory_deg = np.degrees(phase_theory_rad)
            phase_theory_deg = (phase_theory_deg + 180) % 360 - 180

            # Left Plot: Magnitude
            ax_mag = axes[idx, 0]
            ax_mag.semilogx(valid_freqs, mag_theory_db, 'k--', label='Theoretical', alpha=0.7)
            ax_mag.semilogx(valid_freqs, mags_meas[h_key], color=colors[idx], label='Measured')
            ax_mag.set_title(f"Harmonic {p} Magnitude Response")
            ax_mag.set_ylabel("Gain (dB)")
            ax_mag.grid(True, which="both", ls="-", alpha=0.3)
            if idx == 0:
                ax_mag.legend()

            # Right Plot: Phase (Compensated using interpolated baseline offsets)
            # Find closest matching indices in stable eval_freqs
            baseline_offset_full = np.interp(valid_freqs, eval_freqs, systematic_phase_curves[p])
            plt_phase_comp = phases_meas[h_key] - baseline_offset_full
            plt_phase_comp = (plt_phase_comp + 180) % 360 - 180

            ax_phase = axes[idx, 1]
            ax_phase.semilogx(valid_freqs, phase_theory_deg, 'k--', label='Theoretical', alpha=0.7)
            ax_phase.semilogx(valid_freqs, plt_phase_comp, color=colors[idx], label='Measured (Compensated)')
            ax_phase.set_title(f"Harmonic {p} Phase Response")
            ax_phase.set_ylabel("Phase (deg)")
            ax_phase.grid(True, which="both", ls="-", alpha=0.3)
            if idx == 0:
                ax_phase.legend()

        axes[-1, 0].set_xlabel("Frequency (Hz)")
        axes[-1, 1].set_xlabel("Frequency (Hz)")
        plt.tight_layout()
        plt.savefig(os.path.join(os.path.dirname(__file__), "phase_accuracy_report.png"), dpi=150)
        print("Plot successfully saved.")
    except ImportError:
        print("\nMatplotlib not found. Skipping plot generation (report data only).")

    print("\nVerification process completed.")

if __name__ == "__main__":
    run_phase_verification()
