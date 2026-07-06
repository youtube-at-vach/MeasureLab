#!/usr/bin/env python3
import os
import sys
import json
import numpy as np
import matplotlib.pyplot as plt
from scipy.interpolate import interp1d

# Add project root to sys.path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from PyQt6.QtWidgets import QApplication

from src.core.audio_engine import AudioEngine
from scripts.verify_lockin_adaptive_sweep import (
    AdaptiveSSSWeeper,
    offline_dut_system,
    get_analytical_H1
)

# ----------------------------------------------------
# Helper class to mock argparse arguments
# ----------------------------------------------------
class MockArgs:
    def __init__(self, **kwargs):
        self.start_freq = 100.0
        self.end_freq = 2000.0
        self.duration = 20.0
        self.amplitude_db = -12.0
        self.max_harmonic = 5
        self.iterations = 6
        self.mu = 0.5
        self.analysis_cycles = 256.0
        self.min_window = 0.5
        self.meas_points = 500
        self.profile = "normal"
        self.sweep_mode = "forward"
        self.offline = True
        self.device_in = None
        self.device_out = None
        self.ch_sig = 0
        self.ch_ref = 1
        for k, v in kwargs.items():
            setattr(self, k, v)


# ----------------------------------------------------
# Static state evaluation logic
# ----------------------------------------------------
def analyze_harmonics_ls(y, t, f, max_harmonic, fs):
    """Fits harmonics of f to the steady-state signal y(t)."""
    N = len(t)
    p_vals = np.arange(1, max_harmonic + 1)
    p_theta = 2 * np.pi * f * t[:, None] * p_vals
    
    design = np.empty((N, 1 + 2 * max_harmonic))
    design[:, 0] = 1.0
    design[:, 1::2] = np.cos(p_theta)
    design[:, 2::2] = np.sin(p_theta)
    
    coeffs, *_ = np.linalg.lstsq(design, y, rcond=None)
    results = [complex(coeffs[1 + 2 * p], -coeffs[2 + 2 * p]) for p in range(max_harmonic)]
    return results


def evaluate_static_performance(F_corr, meas_freqs, fs, max_harmonic=5):
    """
    Simulates steady-state response at each frequency in meas_freqs.
    Returns H_meas_static[n] as relative complex amplitude of each harmonic.
    """
    results_static = {n: np.zeros(len(meas_freqs), dtype=complex) for n in range(1, max_harmonic + 1)}
    
    for idx, f in enumerate(meas_freqs):
        # We need enough cycles to decay transients (especially for LPF near 1.2 kHz)
        # 10 cycles or 0.1 seconds, whichever is longer.
        T_sig = max(0.1, 20.0 / f)
        num_samples = int(np.round(fs * T_sig))
        t = np.arange(num_samples) / fs
        
        # Base excitation phase
        phase = 2 * np.pi * f * t
        x = np.sin(phase)
        
        # Apply predistortion if correction is available
        if F_corr is not None:
            x_pre = x.copy()
            for n in range(2, max_harmonic + 1):
                # Interpolate F_corr[n] at current fundamental frequency f
                F_func = interp1d(meas_freqs, F_corr[n], kind='linear', fill_value='extrapolate')
                F_val = F_func(f)
                mag = np.abs(F_val)
                phase_val = np.angle(F_val)
                x_pre += mag * np.sin(n * phase + phase_val)
        else:
            x_pre = x
            
        # Scale to match sweep excitation amplitude
        amplitude = 10 ** (-12.0 / 20.0) # -12 dBFS
        x_pre_scaled = x_pre * amplitude
        
        # Simulate physical output through simulated non-linear system
        y = offline_dut_system(x_pre_scaled, fs)
        
        # Analyze steady-state portion (last 8 cycles or 0.04s)
        T_steady = max(0.04, 8.0 / f)
        steady_samples = int(np.round(fs * T_steady))
        if steady_samples >= num_samples:
            steady_samples = num_samples // 2
            
        y_steady = y[-steady_samples:]
        t_steady = t[-steady_samples:]
        
        harmonics = analyze_harmonics_ls(y_steady, t_steady, f, max_harmonic, fs)
        
        # Normalize relative to the fundamental component magnitude
        fund_mag = np.abs(harmonics[0])
        for n in range(1, max_harmonic + 1):
            if n == 1:
                results_static[1][idx] = harmonics[0]
            else:
                results_static[n][idx] = harmonics[n-1] / (fund_mag + 1e-12)
                
    return results_static


# ----------------------------------------------------
# Main evaluation script
# ----------------------------------------------------
def main():
    print("[*] Starting Bidirectional vs Unidirectional Adaptive Sweep Evaluation...")
    app = QApplication(sys.argv)
    
    audio_engine = AudioEngine()
    audio_engine.set_offline_mode(True)
    audio_engine.set_loopback(True)
    audio_engine.set_sample_rate(48000)
    audio_engine.set_block_size(1024)
    
    fs = audio_engine.sample_rate
    iterations = 6
    
    # Modes to evaluate
    modes = ["forward", "reverse", "bidirectional"]
    sweepers = {}
    
    # 1. Run learning iterations for each mode
    for mode in modes:
        print(f"\n==========================================")
        print(f" Running Adaptive Sweep: {mode.upper()} Mode")
        print(f"==========================================")
        
        args = MockArgs(sweep_mode=mode, iterations=iterations)
        sweeper = AdaptiveSSSWeeper(args, audio_engine)
        sweeper.calibrate_latency()
        
        for i in range(iterations + 1):
            sweeper.run_sweep_iteration(i)
            
        sweepers[mode] = sweeper
        
    # Standard log-grid of frequencies (same as in sweeper)
    meas_freqs = sweepers["forward"].meas_freqs
    max_harmonic = sweepers["forward"].max_harmonic
    
    # 2. Evaluate steady-state (static) performance (No dynamic sweep error)
    print("\n[+] Evaluating static (steady-state) distortion reduction...")
    static_results = {}
    
    # Baseline (Uncorrected)
    print("  - Simulating uncorrected baseline...")
    static_results["baseline"] = evaluate_static_performance(None, meas_freqs, fs, max_harmonic)
    
    for mode in modes:
        print(f"  - Simulating corrected state for {mode.upper()}...")
        static_results[mode] = evaluate_static_performance(sweepers[mode].F_corr, meas_freqs, fs, max_harmonic)
        
    # 3. Evaluate dynamic sweep performance in both directions (Forward vs Reverse)
    print("\n[+] Evaluating dynamic sweep cross-performances...")
    sweep_eval = {}
    for mode in modes:
        sweep_eval[mode] = {
            "forward_sweep": sweepers[mode].measure_sweep_only(is_ascending=True),
            "reverse_sweep": sweepers[mode].measure_sweep_only(is_ascending=False)
        }
        
    # 4. Generate report tables and JSON
    evaluation_report = {
        "metadata": {
            "profile": "normal",
            "iterations": iterations,
            "fs": fs,
            "start_freq": 100.0,
            "end_freq": 2000.0
        },
        "static_avg_levels": {},
        "sweep_avg_levels": {}
    }
    
    print("\n====================================================================")
    print("                   EVALUATION RESULT SUMMARY")
    print("====================================================================")
    print("1. Static Steady-State Distortion Levels (Average dB relative to fundamental):")
    print("--------------------------------------------------------------------")
    print(f"{'Mode':<15} | {'H2 (dB)':<10} | {'H3 (dB)':<10} | {'H4 (dB)':<10} | {'H5 (dB)':<10}")
    print("--------------------------------------------------------------------")
    
    for key in ["baseline"] + modes:
        lvl = {}
        for n in range(2, max_harmonic + 1):
            avg_val = 20 * np.log10(np.mean(np.abs(static_results[key][n])) + 1e-12)
            lvl[f"H{n}"] = float(avg_val)
        evaluation_report["static_avg_levels"][key] = lvl
        print(f"{key.upper():<15} | {lvl['H2']:<10.1f} | {lvl['H3']:<10.1f} | {lvl['H4']:<10.1f} | {lvl['H5']:<10.1f}")
    print("--------------------------------------------------------------------")
    
    print("\n2. Dynamic Sweep Distortion Levels (Average dB relative to fundamental):")
    print("--------------------------------------------------------------------")
    print(f"{'Mode':<15} | {'Forward Sweep (H2)':<20} | {'Reverse Sweep (H2)':<20}")
    print("--------------------------------------------------------------------")
    
    for mode in modes:
        f_h2 = 20 * np.log10(np.mean(np.abs(sweep_eval[mode]["forward_sweep"][2])) + 1e-12)
        r_h2 = 20 * np.log10(np.mean(np.abs(sweep_eval[mode]["reverse_sweep"][2])) + 1e-12)
        evaluation_report["sweep_avg_levels"][mode] = {
            "forward_sweep_H2": float(f_h2),
            "reverse_sweep_H2": float(r_h2)
        }
        print(f"{mode.upper():<15} | {f_h2:<20.1f} | {r_h2:<20.1f}")
    print("--------------------------------------------------------------------")
    
    # Save JSON results
    json_path = os.path.join(project_root, "scripts", "bidirectional_evaluation_results.json")
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(evaluation_report, f, indent=2)
    print(f"[+] Saved evaluation JSON data to {json_path}")
    
    # 5. Generate comparative plots
    plt.figure(figsize=(15, 12))
    
    colors = {"baseline": "gray", "forward": "blue", "reverse": "orange", "bidirectional": "green"}
    linestyles = {"baseline": ":", "forward": "-", "reverse": "--", "bidirectional": "-."}
    
    # Plot 1: Steady-state H2 distortion vs Frequency
    plt.subplot(2, 2, 1)
    for key in ["baseline"] + modes:
        plt.semilogx(
            meas_freqs, 
            20 * np.log10(np.abs(static_results[key][2]) + 1e-12),
            label=key.upper(),
            color=colors[key],
            linestyle=linestyles[key],
            linewidth=2 if key == "bidirectional" else 1.5
        )
    plt.title("Static Steady-State H2 Distortion vs Frequency")
    plt.xlabel("Frequency (Hz)")
    plt.ylabel("H2 Level (dB relative to fundamental)")
    plt.grid(True, which="both")
    plt.ylim(-110, -20)
    plt.legend()
    
    # Plot 2: Steady-state H3 distortion vs Frequency
    plt.subplot(2, 2, 2)
    for key in ["baseline"] + modes:
        plt.semilogx(
            meas_freqs, 
            20 * np.log10(np.abs(static_results[key][3]) + 1e-12),
            label=key.upper(),
            color=colors[key],
            linestyle=linestyles[key],
            linewidth=2 if key == "bidirectional" else 1.5
        )
    plt.title("Static Steady-State H3 Distortion vs Frequency")
    plt.xlabel("Frequency (Hz)")
    plt.ylabel("H3 Level (dB relative to fundamental)")
    plt.grid(True, which="both")
    plt.ylim(-130, -40)
    plt.legend()
    
    # Plot 3: Dynamic Forward Sweep H2 vs Frequency
    plt.subplot(2, 2, 3)
    for mode in modes:
        plt.semilogx(
            meas_freqs,
            20 * np.log10(np.abs(sweep_eval[mode]["forward_sweep"][2]) + 1e-12),
            label=f"{mode.upper()} mode",
            color=colors[mode],
            linestyle=linestyles[mode]
        )
    plt.title("Dynamic Forward Sweep H2 response")
    plt.xlabel("Frequency (Hz)")
    plt.ylabel("H2 Level (dB)")
    plt.grid(True, which="both")
    plt.ylim(-110, -20)
    plt.legend()
    
    # Plot 4: Dynamic Reverse Sweep H2 vs Frequency
    plt.subplot(2, 2, 4)
    for mode in modes:
        plt.semilogx(
            meas_freqs,
            20 * np.log10(np.abs(sweep_eval[mode]["reverse_sweep"][2]) + 1e-12),
            label=f"{mode.upper()} mode",
            color=colors[mode],
            linestyle=linestyles[mode]
        )
    plt.title("Dynamic Reverse Sweep H2 response")
    plt.xlabel("Frequency (Hz)")
    plt.ylabel("H2 Level (dB)")
    plt.grid(True, which="both")
    plt.ylim(-110, -20)
    plt.legend()
    
    plt.tight_layout()
    plot_path = os.path.join(project_root, "scripts", "bidirectional_evaluation_plots.png")
    plt.savefig(plot_path)
    print(f"[+] Saved comparative evaluation plots to {plot_path}")


if __name__ == "__main__":
    main()
