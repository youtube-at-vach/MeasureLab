#!/usr/bin/env python3
import os
import sys
import subprocess
import json
import numpy as np

def run_trial(virtual=False, tsa=1, sweep_duration=80.0, num_amplitudes=5, 
              analysis_cycles=256.0, num_meas_points=500, min_analysis_window=1.0):
    cmd = [
        sys.executable,
        "scripts/verify_lock_in_modeler_hammerstein_real_device.py",
        "--tsa", str(tsa),
        "--sweep-duration", f"{sweep_duration:.2f}",
        "--num-amplitudes", str(num_amplitudes),
        "--analysis-cycles", f"{analysis_cycles:.2f}",
        "--num-meas-points", str(num_meas_points),
        "--min-analysis-window", f"{min_analysis_window:.2f}",
        "--runs", "5"
    ]
    if virtual:
        cmd.append("--virtual")
        cmd.append("--fast")
        
    print(f"\n=======================================================")
    print(f"[Trial] Running with parameters:")
    print(f"  TSA: {tsa}, Sweep Duration: {sweep_duration}s (Total: {tsa * sweep_duration}s)")
    print(f"  Analysis Cycles: {analysis_cycles}")
    print(f"  Num Meas Points: {num_meas_points}")
    print(f"  Min Analysis Window: {min_analysis_window}s")
    print(f"=======================================================")
    
    # Run subprocess
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"[-] Trial failed with error code {result.returncode}")
        print(result.stderr)
        return None
        
    # Read the JSON results
    output_report_path = "/Users/vach/MeasureLab/scripts/lock_in_modeler_hammerstein_verification_results.json"
    if not os.path.exists(output_report_path):
        print("[-] Results JSON file not found!")
        return None
        
    with open(output_report_path, "r") as f:
        data = json.load(f)
        
    return data

def calculate_metrics(trial_data):
    if not trial_data or "results" not in trial_data:
        return None
        
    # Results is a list of dictionary for H1..H5
    results = trial_data["results"]
    
    # Extraction of amp diff and phase diff
    amp_diffs = []
    phase_diffs = []
    
    for r in results:
        amp_diffs.append(r["diff"]["amp_db"])
        phase_diffs.append(r["diff"]["phase_deg"])
        
    # H1 is fundamental. H2..H5 are distortion harmonics.
    # Distortion accuracy is key.
    # Compute RMS of H2..H5 amp diff
    h2_h5_amp_diffs = amp_diffs[1:5]
    h2_h5_rms = np.sqrt(np.mean(np.square(h2_h5_amp_diffs)))
    
    # Compute average absolute error for H2..H3 (lower, usually stronger/more robust harmonics)
    h2_h3_amp_diffs = amp_diffs[1:3]
    h2_h3_avg_abs = np.mean(h2_h3_amp_diffs)
    
    # Fundamental error
    h1_amp_err = amp_diffs[0]
    h1_phase_err = phase_diffs[0]
    
    return {
        "h1_amp_err": h1_amp_err,
        "h1_phase_err": h1_phase_err,
        "h2_h5_rms": h2_h5_rms,
        "h2_h3_avg_abs": h2_h3_avg_abs,
        "raw_results": results
    }

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Optimize Hammerstein parameters on ZOOM UAC-232")
    parser.add_argument("--virtual", action="store_true", help="Run in virtual fast simulation mode")
    args = parser.parse_args()

    # Total Sweep Time = num_amplitudes * tsa * sweep_duration = 40.0s (across all amplitudes)
    ratios = [
        {"num_amplitudes": 5, "tsa": 1, "sweep_duration": 8.0},
        {"num_amplitudes": 5, "tsa": 2, "sweep_duration": 4.0},
        {"num_amplitudes": 4, "tsa": 1, "sweep_duration": 10.0},
        {"num_amplitudes": 4, "tsa": 2, "sweep_duration": 5.0},
        {"num_amplitudes": 3, "tsa": 1, "sweep_duration": 13.33},
        {"num_amplitudes": 3, "tsa": 2, "sweep_duration": 6.67},
    ]
    
    phase1_results = []
    
    print("[+] Starting Phase 1: Ratio Optimization...")
    for config in ratios:
        num_amp = config["num_amplitudes"]
        tsa = config["tsa"]
        dur = config["sweep_duration"]
        
        raw_data = run_trial(
            virtual=args.virtual,
            tsa=tsa,
            sweep_duration=dur,
            num_amplitudes=num_amp,
            analysis_cycles=256.0,
            num_meas_points=500,
            min_analysis_window=1.0
        )
        
        if raw_data:
            metrics = calculate_metrics(raw_data)
            phase1_results.append({
                "num_amplitudes": num_amp,
                "tsa": tsa,
                "sweep_duration": dur,
                "metrics": metrics
            })
            print(f"    [Result] Amplitudes={num_amp}, TSA={tsa}, Sweep Duration={dur:.2f}s -> H2-H5 RMS Amp Err: {metrics['h2_h5_rms']:.3f} dB, H2-H3 Avg Abs: {metrics['h2_h3_avg_abs']:.3f} dB")
            
    # Find best ratio from Phase 1 (based on H2-H5 RMS amp error)
    valid_phase1 = [r for r in phase1_results if r["metrics"] is not None]
    if not valid_phase1:
        print("[-] No valid trials in Phase 1. Exiting.")
        sys.exit(1)
        
    best_phase1 = min(valid_phase1, key=lambda x: x["metrics"]["h2_h5_rms"])
    best_num_amp = best_phase1["num_amplitudes"]
    best_tsa = best_phase1["tsa"]
    best_dur = best_phase1["sweep_duration"]
    
    print(f"\n[+] Best Ratio found: NumAmplitudes={best_num_amp}, TSA={best_tsa}, Sweep Duration={best_dur:.2f}s with H2-H5 RMS Amp Err = {best_phase1['metrics']['h2_h5_rms']:.3f} dB")
    
    # 2. Phase 2: Explore other SSS engine parameters using the best ratio
    print("\n[+] Starting Phase 2: Parameter Tuning...")
    
    # We will test variations of analysis_cycles, num_meas_points, min_analysis_window
    phase2_configs = [
        # cycles, points, min_window
        {"cycles": 128.0, "points": 500, "min_window": 1.0},
        {"cycles": 512.0, "points": 500, "min_window": 1.0},
        {"cycles": 256.0, "points": 250, "min_window": 1.0},
        {"cycles": 256.0, "points": 500, "min_window": 0.5},
        {"cycles": 256.0, "points": 500, "min_window": 2.0},
    ]
    
    phase2_results = [
        # Include best phase 1 result as the default configuration baseline
        {
            "cycles": 256.0,
            "points": 500,
            "min_window": 1.0,
            "metrics": best_phase1["metrics"]
        }
    ]
    
    for cfg in phase2_configs:
        raw_data = run_trial(
            virtual=args.virtual,
            tsa=best_tsa,
            sweep_duration=best_dur,
            num_amplitudes=best_num_amp,
            analysis_cycles=cfg["cycles"],
            num_meas_points=cfg["points"],
            min_analysis_window=cfg["min_window"]
        )
        
        if raw_data:
            metrics = calculate_metrics(raw_data)
            phase2_results.append({
                "cycles": cfg["cycles"],
                "points": cfg["points"],
                "min_window": cfg["min_window"],
                "metrics": metrics
            })
            print(f"    [Result] Cycles={cfg['cycles']}, Points={cfg['points']}, MinWindow={cfg['min_window']}s -> H2-H5 RMS: {metrics['h2_h5_rms']:.3f} dB")
            
    # Find absolute best configuration
    valid_phase2 = [r for r in phase2_results if r["metrics"] is not None]
    best_overall = min(valid_phase2, key=lambda x: x["metrics"]["h2_h5_rms"])
    
    print("\n=======================================================")
    print("[+] Optimization Completed!")
    print(f"Best configuration:")
    print(f"  Num Amplitudes: {best_num_amp}")
    print(f"  TSA: {best_tsa}")
    print(f"  Sweep Duration: {best_dur:.2f} s")
    print(f"  Analysis Cycles: {best_overall['cycles']}")
    print(f"  Num Meas Points: {best_overall['points']}")
    print(f"  Min Analysis Window: {best_overall['min_window']} s")
    print(f"  Best H2-H5 RMS Amp Err: {best_overall['metrics']['h2_h5_rms']:.4f} dB")
    print(f"  Best H2-H3 Avg Abs Err: {best_overall['metrics']['h2_h3_avg_abs']:.4f} dB")
    print(f"  Fundamental Amp Err: {best_overall['metrics']['h1_amp_err']:.4f} dB, Phase Err: {best_overall['metrics']['h1_phase_err']:.4f} deg")
    print("=======================================================")
    
    # Save optimization summary to JSON
    summary_path = "/Users/vach/MeasureLab/scripts/hammerstein_optimization_summary.json"
    summary_data = {
        "best_config": {
            "num_amplitudes": best_num_amp,
            "tsa": best_tsa,
            "sweep_duration": best_dur,
            "analysis_cycles": best_overall["cycles"],
            "num_meas_points": best_overall["points"],
            "min_analysis_window": best_overall["min_window"],
            "h2_h5_rms": best_overall["metrics"]["h2_h5_rms"],
            "h2_h3_avg_abs": best_overall["metrics"]["h2_h3_avg_abs"]
        },
        "phase1_trials": [
            {
                "num_amplitudes": p["num_amplitudes"],
                "tsa": p["tsa"],
                "sweep_duration": p["sweep_duration"],
                "h2_h5_rms": p["metrics"]["h2_h5_rms"] if p["metrics"] else None,
                "h2_h3_avg_abs": p["metrics"]["h2_h3_avg_abs"] if p["metrics"] else None,
            } for p in phase1_results
        ],
        "phase2_trials": [
            {
                "cycles": p["cycles"],
                "points": p["points"],
                "min_window": p["min_window"],
                "h2_h5_rms": p["metrics"]["h2_h5_rms"] if p["metrics"] else None,
                "h2_h3_avg_abs": p["metrics"]["h2_h3_avg_abs"] if p["metrics"] else None,
            } for p in phase2_results
        ]
    }
    
    with open(summary_path, "w") as f:
        json.dump(summary_data, f, indent=4)
    print(f"[+] Saved optimization summary to {summary_path}")

if __name__ == "__main__":
    main()
