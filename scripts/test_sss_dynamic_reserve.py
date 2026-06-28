#!/usr/bin/env python3
"""Sweep-Sine SSS Analyzer SNR Tolerance & Dynamic Reserve Test.

This script estimates the dynamic reserve and SNR tolerance of the Sweep-Sine
SSS Analyzer (RealtimeSSSEngine) under varying noise and interference conditions.
It compares the Least Squares (LS) and LPF (Butterworth biquad) modes and diagnoses
how parameters like duration, LPF factor, and block size affect SNR performance.
"""

import argparse
import math
import os
import sys
from typing import Any

import matplotlib.pyplot as plt
import numpy as np

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.core.realtime_sss_core import RealtimeSSSEngine


def _wrap_deg_180(angle_deg: float) -> float:
    """Map angle in degrees to (-180, 180]."""
    x = (angle_deg + 180.0) % 360.0 - 180.0
    if x <= -180.0:
        x += 360.0
    return x


def run_sss_sweep(
    *,
    fs: float,
    start_freq: float,
    end_freq: float,
    duration: float,
    amplitude: float,
    max_harmonic: int,
    block_size: int,
    latency_samples: float,
    noise_rms: float,
    f_int: float,
    a_int: float,
    phi_int: float,
    clip: bool,
    seed: int | None,
) -> dict[str, Any]:
    """Run a single simulated SSS sweep through the RealtimeSSSEngine.

    Simulates the clean swept signal, adds noise and interference,
    processes it block-by-block, and returns the result.
    """
    rng = np.random.default_rng(seed)

    # Initialize SSS Engine
    engine = RealtimeSSSEngine(
        sample_rate=fs,
        sweep_duration=duration,
        start_freq=start_freq,
        end_freq=end_freq,
        output_amplitude=amplitude,
        max_harmonic=max_harmonic,
    )
    engine.prepare_sweep()
    engine.set_latency(latency_samples)

    frames = block_size
    max_blocks = int(np.ceil((engine.sweep_samples + latency_samples) / frames))
    total_samples = max_blocks * frames

    # Generate reference and signal arrays
    y_clean = np.zeros(total_samples)
    d_int = int(np.round(latency_samples))

    # Apply physical delay/latency
    valid_range = (np.arange(total_samples) - d_int >= 0) & (
        np.arange(total_samples) - d_int < engine.sweep_samples
    )
    assert engine.out_sig is not None
    y_clean[valid_range] = engine.out_sig[
        (np.arange(total_samples) - d_int)[valid_range]
    ]

    t_all = np.arange(total_samples) / fs

    # Build simulated loopback signal (with interferer and noise)
    interferer = (
        a_int * np.cos(2.0 * np.pi * f_int * t_all + phi_int)
        if a_int > 0
        else np.zeros(total_samples)
    )
    noise = (
        rng.normal(0.0, noise_rms, size=total_samples)
        if noise_rms > 0
        else np.zeros(total_samples)
    )

    y_meas = y_clean + interferer + noise
    if clip:
        y_meas = np.clip(y_meas, -1.0, 1.0)

    # Reference channel remains clean for relative XFER measurement
    y_ref = y_clean

    freqs = []
    results_list = []

    # Run block-by-block analysis
    for block_idx in range(max_blocks):
        start_idx = block_idx * frames
        end_idx = start_idx + frames

        indata_block = y_meas[start_idx:end_idx, None]
        outdata_block = np.zeros((frames, 1))
        ref_in_block = y_ref[start_idx:end_idx, None]

        f_mid, results = engine.process_block(
            indata_block, outdata_block, block_idx, ref_in_block=ref_in_block
        )
        freqs.append(f_mid)
        results_list.append(results)

    # Convert results list to complex numpy array of shape (max_blocks, max_harmonic)
    results_arr = np.array(results_list, dtype=complex)
    freqs_arr = np.array(freqs)

    # Compute magnitude and phase
    h1_complex = results_arr[:, 0]
    h1_mag_db = 20 * np.log10(np.abs(h1_complex) + 1e-15)
    h1_phase_deg = np.degrees(np.angle(h1_complex))

    # Real-time SSS measurement in XFER mode evaluates relative to clean ref.
    # Therefore, ideal output is H1 = 1.0 (0 dB gain, 0 deg phase).
    h1_mag_err_db = h1_mag_db
    h1_phase_err_deg = np.array([_wrap_deg_180(p) for p in h1_phase_deg])

    # Extract harmonics (H2..max_harmonic)
    harmonics_mag_db = []
    for h_idx in range(1, max_harmonic):
        h_complex = results_arr[:, h_idx]
        h_mag_db = 20 * np.log10(np.abs(h_complex) + 1e-15)
        harmonics_mag_db.append(h_mag_db)

    return {
        "freqs": freqs_arr,
        "h1_mag_err_db": h1_mag_err_db,
        "h1_phase_err_deg": h1_phase_err_deg,
        "harmonics_mag_db": harmonics_mag_db,
    }


def evaluate_sweep_errors(
    sweep_res: dict[str, Any],
    start_freq: float,
    end_freq: float,
    mag_tol_db: float,
    phase_tol_deg: float | None,
    harmonic_leakage_tol_db: float,
) -> tuple[bool, dict[str, float]]:
    """Check if the sweep measurement results are within tolerances.

    Excludes starting/ending transients (outer 10% of freq sweep limits) to focus
    on stabilized dynamic response.
    """
    freqs = sweep_res["freqs"]
    h1_mag_err = sweep_res["h1_mag_err_db"]
    h1_phase_err = sweep_res["h1_phase_err_deg"]
    harmonics = sweep_res["harmonics_mag_db"]

    f_min = min(start_freq, end_freq)
    f_max = max(start_freq, end_freq)

    # Transient exclusion margins (10% inward)
    f_min_eval = f_min * 1.10
    f_max_eval = f_max * 0.90

    eval_mask = (freqs >= f_min_eval) & (freqs <= f_max_eval)

    if not np.any(eval_mask):
        # Fallback if range is extremely narrow
        eval_mask = np.ones_like(freqs, dtype=bool)

    # H1 fundamental evaluation
    max_h1_mag_err = float(np.max(np.abs(h1_mag_err[eval_mask])))
    max_h1_phase_err = float(np.max(np.abs(h1_phase_err[eval_mask])))

    h1_pass = max_h1_mag_err <= mag_tol_db
    if phase_tol_deg is not None:
        h1_pass = h1_pass and (max_h1_phase_err <= phase_tol_deg)

    # Harmonics leakage evaluation (H2..H5)
    max_leakage_db = -150.0
    harmonics_pass = True
    for h_db in harmonics:
        max_h_leak = float(np.max(h_db[eval_mask]))
        max_leakage_db = max(max_leakage_db, max_h_leak)
        if max_h_leak > harmonic_leakage_tol_db:
            harmonics_pass = False

    passes = h1_pass and harmonics_pass

    metrics = {
        "max_h1_mag_err": max_h1_mag_err,
        "max_h1_phase_err": max_h1_phase_err,
        "max_leakage_db": max_leakage_db,
    }

    return passes, metrics


def run_dynamic_reserve_sweep(
    *,
    fs: float,
    start_freq: float,
    end_freq: float,
    duration: float,
    amplitude: float,
    max_harmonic: int,
    block_size: int,
    latency_samples: float,
    noise_rms: float,
    f_int: float,
    a_int_values: np.ndarray,
    clip: bool,
    mag_tol_db: float,
    phase_tol_deg: float | None,
    harmonic_leakage_tol_db: float,
    seed: int | None,
) -> dict[str, Any]:
    """Sweeps interferer amplitudes to evaluate when the system fails tolerance."""
    rng = np.random.default_rng(seed)

    rows = []
    last_pass_a_int = None
    limited_by_sweep = True

    # 1. Base measurement at a_int = 0.0 (no interferer)
    base_res = run_sss_sweep(
        fs=fs,
        start_freq=start_freq,
        end_freq=end_freq,
        duration=duration,
        amplitude=amplitude,
        max_harmonic=max_harmonic,
        block_size=block_size,
        latency_samples=latency_samples,
        noise_rms=noise_rms,
        f_int=f_int,
        a_int=0.0,
        phi_int=0.0,
        clip=clip,
        seed=seed,
    )
    passes, metrics = evaluate_sweep_errors(
        base_res,
        start_freq,
        end_freq,
        mag_tol_db,
        phase_tol_deg,
        harmonic_leakage_tol_db,
    )
    rows.append(
        {
            "a_int": 0.0,
            "pass": passes,
            "max_h1_mag_err": metrics["max_h1_mag_err"],
            "max_h1_phase_err": metrics["max_h1_phase_err"],
            "max_leakage_db": metrics["max_leakage_db"],
        }
    )
    if passes:
        last_pass_a_int = 0.0

    # 2. Sweep over non-zero interferer amplitudes
    for a_int in a_int_values:
        if a_int == 0.0:
            continue

        phi_int = rng.uniform(0.0, 2 * np.pi)
        sweep_res = run_sss_sweep(
            fs=fs,
            start_freq=start_freq,
            end_freq=end_freq,
            duration=duration,
            amplitude=amplitude,
            max_harmonic=max_harmonic,
            block_size=block_size,
            latency_samples=latency_samples,
            noise_rms=noise_rms,
            f_int=f_int,
            a_int=a_int,
            phi_int=phi_int,
            clip=clip,
            seed=seed,
        )

        passes, metrics = evaluate_sweep_errors(
            sweep_res,
            start_freq,
            end_freq,
            mag_tol_db,
            phase_tol_deg,
            harmonic_leakage_tol_db,
        )

        rows.append(
            {
                "a_int": float(a_int),
                "pass": passes,
                "max_h1_mag_err": metrics["max_h1_mag_err"],
                "max_h1_phase_err": metrics["max_h1_phase_err"],
                "max_leakage_db": metrics["max_leakage_db"],
            }
        )

        if passes:
            last_pass_a_int = float(a_int)
        elif last_pass_a_int is not None:
            # First fail after a success means we found the boundary
            limited_by_sweep = False
            break

    # Dynamic Reserve (DR) in dB
    # DR = 20 * log10(max_passing_interferer / sweep_signal_amplitude)
    if last_pass_a_int is None:
        dr_db = float("nan")
    elif last_pass_a_int == 0.0:
        dr_db = float("-inf")
    else:
        dr_db = (
            20.0 * math.log10(last_pass_a_int / amplitude)
            if amplitude > 0
            else float("inf")
        )

    return {
        "rows": rows,
        "dynamic_reserve_db": dr_db,
        "a_int_max_pass": last_pass_a_int,
        "limited_by_sweep": limited_by_sweep,
    }


def run_diagnose(args: argparse.Namespace) -> int:
    """Run a diagnostic comparison over different modes and parameters.

    Outputs results in a clean table format.
    """
    print("\n=======================================================")
    print("           SSS DYNAMIC RESERVE DIAGNOSTICS")
    print("=======================================================")
    print(f"Sweep range:  {args.start_freq} Hz -> {args.end_freq} Hz")
    print(f"Sweep Signal: {args.amplitude} dBFS")
    print(f"Interferer:   Freq = {args.interferer_freq} Hz")
    print(f"Noise level:  {args.noise_dbfs} dBFS")
    print(
        f"Tolerances:   H1 gain err <= {args.mag_tol_db} dB, H1 phase err <= {args.phase_tol_deg} deg"
    )
    print(f"              Harmonic leak limit <= {args.harmonic_leakage_tol_db} dBFS")
    print("=======================================================\n")

    # Fixed base parameters
    fs = float(args.fs)
    start_freq = float(args.start_freq)
    end_freq = float(args.end_freq)
    amplitude_linear = 10.0 ** (float(args.amplitude) / 20.0)
    latency_samples = float(args.block_size)  # Assumed system latency
    noise_rms = (
        10.0 ** (float(args.noise_dbfs) / 20.0)
        if args.noise_dbfs > -199
        else 0.0
    )
    f_int = float(args.interferer_freq)
    clip = bool(args.clip)
    seed = int(args.seed) if args.seed is not None else None

    # Define sweep points for diagnostic sweeps (use a compact sweep to keep it fast)
    a_int_stop = float(args.interferer_amp_stop)
    diag_a_int = np.logspace(-5, np.log10(a_int_stop), 15)

    base_kwargs = {
        "fs": fs,
        "start_freq": start_freq,
        "end_freq": end_freq,
        "duration": float(args.duration),
        "amplitude": amplitude_linear,
        "max_harmonic": int(args.max_harmonic),
        "block_size": int(args.block_size),
        "latency_samples": latency_samples,
        "noise_rms": noise_rms,
        "f_int": f_int,
        "a_int_values": diag_a_int,
        "clip": clip,
        "mag_tol_db": float(args.mag_tol_db),
        "phase_tol_deg": float(args.phase_tol_deg),
        "harmonic_leakage_tol_db": float(args.harmonic_leakage_tol_db),
        "seed": seed,
    }

    results = []

    def format_dr_row(label: str, res: dict[str, Any]) -> str:
        dr = res["dynamic_reserve_db"]
        amax = res["a_int_max_pass"]
        limited = res["limited_by_sweep"]
        if amax is None or not math.isfinite(dr):
            return f"{label:<32} | DR: n/a"
        prefix = ">= " if limited else "   "
        return f"{label:<32} | DR: {prefix}{dr:7.2f} dB (amax={amax:.3g})"

    # Test 1: Base LS Mode Run
    print("[*] Running Base LS Mode...")
    res_ls = run_dynamic_reserve_sweep(**base_kwargs)
    results.append(("Mode: LS (Base)", res_ls))

    # Test 2: Sweep Duration Impact (LS Mode)
    print("[*] Running Duration Sensitivity (LS Mode)...")
    for dur in [2.0, 5.0, 10.0, 20.0]:
        res = run_dynamic_reserve_sweep(**{**base_kwargs, "duration": dur})
        results.append((f"Duration={dur}s (LS)", res))

    # Test 4: Block Size Impact (LS Mode)
    print("[*] Running Block Size Sensitivity (LS Mode)...")
    for bs in [256, 512, 1024]:
        res = run_dynamic_reserve_sweep(**{**base_kwargs, "block_size": bs, "latency_samples": float(bs)})
        results.append((f"Block Size={bs} (LS)", res))

    # Print Report
    print("\n=======================================================")
    print("           DIAGNOSTIC REPORT SUMMARY")
    print("=======================================================")
    hdr = f"{'Configuration':<32} | {'Dynamic Reserve Result':<30}"
    print(hdr)
    print("-" * len(hdr))
    for label, res in results:
        print(format_dr_row(label, res))
    print("=======================================================\n")

    return 0


def generate_plot(
    args: argparse.Namespace,
    freqs: np.ndarray,
    sweep_res: dict[str, Any],
    a_int: float,
) -> None:
    """Generate and save matplotlib charts showing sweep performance metrics."""
    h1_mag_err = sweep_res["h1_mag_err_db"]
    h1_phase_err = sweep_res["h1_phase_err_deg"]
    harmonics = sweep_res["harmonics_mag_db"]

    fig, axs = plt.subplots(3, 1, figsize=(10, 12), sharex=True)
    fig.suptitle(
        f"SSS Sweep Performance (Interferer={a_int:.3g} @ {args.interferer_freq} Hz, Noise={args.noise_dbfs} dBFS)",
        fontsize=14,
    )

    # 1. Fundamental Gain Error
    axs[0].plot(freqs, h1_mag_err, label="H1 (Fundamental) Gain Error", color="blue")
    axs[0].axhline(args.mag_tol_db, color="red", linestyle="--", alpha=0.7, label="Tolerance")
    axs[0].axhline(-args.mag_tol_db, color="red", linestyle="--", alpha=0.7)
    axs[0].set_ylabel("Gain Error (dB)")
    axs[0].grid(True, which="both")
    axs[0].legend()
    axs[0].set_title("H1 Magnitude Response Error")

    # 2. Fundamental Phase Error
    axs[1].plot(freqs, h1_phase_err, label="H1 (Fundamental) Phase Error", color="green")
    axs[1].axhline(args.phase_tol_deg, color="red", linestyle="--", alpha=0.7, label="Tolerance")
    axs[1].axhline(-args.phase_tol_deg, color="red", linestyle="--", alpha=0.7)
    axs[1].set_ylabel("Phase Error (deg)")
    axs[1].grid(True, which="both")
    axs[1].legend()
    axs[1].set_title("H1 Phase Response Error")

    # 3. Harmonic Leakage Floor (H2..H5)
    colors = ["#ff7f0e", "#2ca02c", "#d62728", "#9467bd"]
    for idx, h_db in enumerate(harmonics):
        h_order = idx + 2
        axs[2].plot(freqs, h_db, label=f"H{h_order} Leakage Floor", color=colors[idx % len(colors)])
    axs[2].axhline(args.harmonic_leakage_tol_db, color="red", linestyle="--", alpha=0.7, label="Leakage Limit")
    axs[2].set_ylabel("Leakage Level (dBFS)")
    axs[2].set_xlabel("Sweep Frequency (Hz)")
    axs[2].set_xscale("log")
    axs[2].grid(True, which="both")
    axs[2].legend()
    axs[2].set_title("Harmonic Noise/Leakage Floor (Linear System)")

    plt.tight_layout()
    plot_path = os.path.join(
        os.path.dirname(__file__), "sss_dr_results.png"
    )
    plt.savefig(plot_path, dpi=150)
    print(f"\n[+] Saved visualization plot to {plot_path}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Estimate Sweep-Sine SSS Dynamic Reserve (simulation)."
    )


    parser.add_argument("--fs", type=float, default=48000.0, help="Sample rate (Hz)")
    parser.add_argument(
        "--duration",
        type=float,
        default=10.0,
        help="Sweep duration (seconds)",
    )
    parser.add_argument(
        "--start-freq",
        type=float,
        default=20.0,
        help="Sweep start frequency (Hz)",
    )
    parser.add_argument(
        "--end-freq",
        type=float,
        default=20000.0,
        help="Sweep end frequency (Hz)",
    )
    parser.add_argument(
        "--amplitude",
        type=float,
        default=-6.0,
        help="Sweep signal amplitude in dBFS (e.g. -6)",
    )

    parser.add_argument(
        "--block-size",
        type=int,
        default=512,
        help="Audio block size (samples)",
    )
    parser.add_argument(
        "--max-harmonic",
        type=int,
        default=5,
        help="Max harmonic order to calculate (1..)",
    )

    # Disturbances
    parser.add_argument(
        "--noise-dbfs",
        type=float,
        default=-120.0,
        help="Additive white noise level RMS dBFS (e.g. -120, use -200 to disable)",
    )
    parser.add_argument(
        "--interferer-freq",
        type=float,
        default=1000.0,
        help="Interferer tone frequency (Hz)",
    )
    parser.add_argument(
        "--interferer-amp-start",
        type=float,
        default=0.0,
        help="Interferer sweep start amplitude (linear peak)",
    )
    parser.add_argument(
        "--interferer-amp-stop",
        type=float,
        default=1.0,
        help="Interferer sweep stop amplitude (linear peak)",
    )
    parser.add_argument(
        "--points",
        type=int,
        default=21,
        help="Interferer sweep points",
    )
    parser.add_argument(
        "--log",
        action="store_true",
        help="Log sweep for interferer amplitude",
    )
    parser.add_argument(
        "--clip",
        action="store_true",
        help="Hard clip signals to [-1, 1]",
    )

    # Tolerances
    parser.add_argument(
        "--mag-tol-db",
        type=float,
        default=0.5,
        help="Magnitude error tolerance (dB)",
    )
    parser.add_argument(
        "--phase-tol-deg",
        type=float,
        default=10.0,
        help="Phase error tolerance (degrees)",
    )
    parser.add_argument(
        "--harmonic-leakage-tol-db",
        type=float,
        default=-60.0,
        help="Max tolerated leakage levels for harmonics H2..H5 (dBFS)",
    )

    # Output Options
    parser.add_argument(
        "--diagnose",
        action="store_true",
        help="Run comprehensive parameter and mode diagnostics comparisons",
    )
    parser.add_argument(
        "--plot",
        action="store_true",
        help="Plot final sweep performance results under worst-case interference",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=1,
        help="RNG seed for noise",
    )

    args = parser.parse_args()

    if args.diagnose:
        return run_diagnose(args)

    # Basic setup for a single Dynamic Reserve Sweep run
    fs = float(args.fs)
    start_freq = float(args.start_freq)
    end_freq = float(args.end_freq)
    amplitude_linear = 10.0 ** (float(args.amplitude) / 20.0)
    latency_samples = float(args.block_size)
    noise_rms = (
        10.0 ** (float(args.noise_dbfs) / 20.0)
        if args.noise_dbfs > -199
        else 0.0
    )
    f_int = float(args.interferer_freq)
    clip = bool(args.clip)
    seed = int(args.seed) if args.seed is not None else None

    # Setup interferer sweep values
    if args.log:
        start = max(float(args.interferer_amp_start), 1e-6)
        stop = max(float(args.interferer_amp_stop), start)
        a_int_values = np.logspace(np.log10(start), np.log10(stop), int(args.points))
        if float(args.interferer_amp_start) == 0.0:
            a_int_values = np.concatenate(([0.0], a_int_values))
    else:
        a_int_values = np.linspace(
            float(args.interferer_amp_start),
            float(args.interferer_amp_stop),
            int(args.points),
        )

    print("Running Sweep-Sine SSS Dynamic Reserve Simulation...")
    print(f"Signal amplitude: {args.amplitude} dBFS ({amplitude_linear:.4f} linear peak)")
    print(f"Interferer Freq:  {f_int} Hz")
    print(f"Noise level:      {args.noise_dbfs} dBFS")
    print(f"Extraction Mode:  {args.mode.upper()}")
    print("")

    result = run_dynamic_reserve_sweep(
        fs=fs,
        start_freq=start_freq,
        end_freq=end_freq,
        duration=float(args.duration),
        amplitude=amplitude_linear,
        max_harmonic=int(args.max_harmonic),
        block_size=int(args.block_size),
        latency_samples=latency_samples,
        noise_rms=noise_rms,
        f_int=f_int,
        a_int_values=a_int_values,
        clip=clip,
        mag_tol_db=float(args.mag_tol_db),
        phase_tol_deg=float(args.phase_tol_deg),
        harmonic_leakage_tol_db=float(args.harmonic_leakage_tol_db),
        seed=seed,
    )

    hdr = f"{'a_int':>10} | {'Max H1 MagErr (dB)':>19} | {'Max H1 PhaseErr (deg)':>22} | {'Max Leakage (dBFS)':>18} | {'Pass':>5}"
    print(hdr)
    print("-" * len(hdr))

    for r in result["rows"]:
        print(
            f"{r['a_int']:10.3e} | {r['max_h1_mag_err']:19.3f} | {r['max_h1_phase_err']:22.3f} | {r['max_leakage_db']:18.3f} | {str(r['pass']):>5}"
        )

    print("")
    dr = result["dynamic_reserve_db"]
    amax = result["a_int_max_pass"]

    if amax is None or not math.isfinite(dr):
        print("Dynamic reserve: could not be determined (no passing point).")
        return 2

    if bool(result.get("limited_by_sweep", False)):
        print(f"Max passing interferer amplitude: {amax:.6f} (peak) (no failure within sweep)")
        print(f"Dynamic reserve: >= {dr:.2f} dB")
    else:
        print(f"Max passing interferer amplitude: {amax:.6f} (peak)")
        print(f"Dynamic reserve: {dr:.2f} dB")

    # Generate visual plot if requested
    if args.plot:
        # Run a final sweep at the maximum passing interferer amplitude to plot
        plot_sweep_res = run_sss_sweep(
            fs=fs,
            start_freq=start_freq,
            end_freq=end_freq,
            duration=float(args.duration),
            amplitude=amplitude_linear,
            max_harmonic=int(args.max_harmonic),
            block_size=int(args.block_size),
            latency_samples=latency_samples,
            noise_rms=noise_rms,
            f_int=f_int,
            a_int=amax,
            phi_int=0.0,
            clip=clip,
            seed=seed,
        )
        generate_plot(args, plot_sweep_res["freqs"], plot_sweep_res, amax)

    return 0


if __name__ == "__main__":
    sys.exit(main())
