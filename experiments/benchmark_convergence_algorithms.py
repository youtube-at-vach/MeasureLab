#!/usr/bin/env python3
# ruff: noqa: E402
"""
Benchmark script comparing convergence speed across different adaptive predistortion algorithms.
"""

import sys
import os
import numpy as np

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from PyQt6.QtWidgets import QApplication
from src.core.audio_engine import AudioEngine
from scripts.verify_lockin_adaptive_sweep import AdaptiveSSSWeeper


def run_benchmark():
    algorithms = ["baseline", "newton_lm", "secant", "anderson"]
    num_iterations = 6

    _app = QApplication(sys.argv)
    audio_engine = AudioEngine()
    audio_engine.set_offline_mode(True)
    audio_engine.set_loopback(True)
    audio_engine.set_sample_rate(48000)
    audio_engine.set_block_size(1024)

    results = {}

    for algo in algorithms:
        print("\n==========================================")
        print(f" Running Benchmark for Algorithm: {algo}")
        print("==========================================")

        class Args:
            start_freq = 100.0
            end_freq = 2000.0
            duration = 4.0
            amplitude_db = -12.0
            max_harmonic = 5
            iterations = num_iterations
            algorithm = algo
            mu = 1.0 if algo != "baseline" else 0.7
            mu_decay = 0.92
            analysis_cycles = 12.0
            min_window = 0.012
            meas_points = 300
            profile = None
            sweep_mode = "forward"
            offline = True
            ch_sig = 0
            ch_ref = 1

        args = Args()
        sweeper = AdaptiveSSSWeeper(args, audio_engine)
        sweeper.calibrate_latency()

        for i in range(num_iterations + 1):
            sweeper.run_sweep_iteration(i)

        # Collect THD trajectory
        thd_db_traj = []
        for iter_res in sweeper.iteration_results:
            H_data = iter_res["H"]
            H1_mag = np.abs(H_data[1]) + 1e-12
            harmonic_sq_sum = np.zeros_like(H1_mag)
            for n in range(2, args.max_harmonic + 1):
                if n in H_data:
                    harmonic_sq_sum += np.abs(H_data[n]) ** 2
            thd_ratio = np.sqrt(harmonic_sq_sum) / H1_mag
            thd_db = 20.0 * np.log10(np.mean(thd_ratio) + 1e-12)
            thd_db_traj.append(thd_db)

        results[algo] = thd_db_traj

    # Print Summary Comparison Table
    print("\n\n" + "=" * 80)
    print("                 ALGORITHM CONVERGENCE SPEED COMPARISON TABLE")
    print("=" * 80)
    header = f"| {'Iteration':<10} | {'Baseline (mu=0.7)':<18} | {'Newton-LM (mu=1.0)':<18} | {'Secant Method':<18} | {'Anderson Accel.':<18} |"
    print(header)
    print("|" + "-" * 12 + "|" + "-" * 20 + "|" + "-" * 20 + "|" + "-" * 20 + "|" + "-" * 20 + "|")

    for i in range(num_iterations + 1):
        row = f"| Iter {i:<5} | {results['baseline'][i]:>15.1f} dB | {results['newton_lm'][i]:>15.1f} dB | {results['secant'][i]:>15.1f} dB | {results['anderson'][i]:>15.1f} dB |"
        print(row)

    print("=" * 80)

    # Calculate iterations to reach target cancellation levels
    targets = [-70.0, -80.0, -90.0, -100.0, -110.0]
    print("\nIterations required to reach target THD level:")
    for target in targets:
        print(f"\nTarget THD <= {target:.0f} dB:")
        for algo in algorithms:
            iters_needed = None
            for idx, thd_val in enumerate(results[algo]):
                if thd_val <= target:
                    iters_needed = idx
                    break
            status_str = f"{iters_needed} iteration(s)" if iters_needed is not None else "Not reached within test"
            print(f"  - {algo:<12}: {status_str}")


if __name__ == "__main__":
    run_benchmark()
