#!/usr/bin/env python3
# ruff: noqa: E402
import sys
import os
import time
import json
import numpy as np
from scipy.signal import fftconvolve

# Add project root to sys.path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from PyQt6.QtWidgets import QApplication
from src.core.audio_engine import AudioEngine
from src.core.nonlinear_analyzer_core import (
    generate_sss_and_inverse,
    find_subsample_peak,
)

def run_alignment_drift_measurement():
    # Initialize Qt Application (required for AudioEngine config/events)
    QApplication(sys.argv)

    # 1. Initialize Audio Engine
    engine = AudioEngine()

    # 2. Find ZOOM UAC-232 Device Index, fallback to default if not found
    devices = engine.list_devices()
    uac_idx = None
    for idx, dev in enumerate(devices):
        name = dev.get("name", "")
        if "uac-232" in name.lower() and dev.get("max_input_channels", 0) >= 2 and dev.get("max_output_channels", 0) >= 2:
            uac_idx = idx
            break

    if uac_idx is None:
        print("[!] Warning: ZOOM UAC-232 not found. Trying to fallback to default duplex device...")
        # Fallback to default duplex device
        try:
            import sounddevice as sd
            default_devices = sd.default.device
            uac_idx = default_devices[0] # Try default input
            print(f"[+] Using default device index: {uac_idx}")
        except Exception as e:
            print(f"[-] Error: Could not determine default device: {e}")
            sys.exit(1)

    print(f"[+] Setting audio device to index {uac_idx}")
    engine.set_devices(uac_idx, uac_idx)
    engine.set_sample_rate(48000)
    engine.set_block_size(1024)
    engine.set_loopback(False)
    engine.offline_mode = False

    sample_rate = engine.sample_rate
    num_runs = 20
    sweep_duration = 2.0
    padding_samples = int(0.5 * sample_rate)  # 500ms tail padding
    ref_channel = 1   # Ref = Ch2 (R)
    meas_channel = 0  # Meas = Ch1 (L)

    print(f"\n=== SSS Alignment Drift Measurement ===")
    print(f"Sample Rate: {sample_rate} Hz")
    print(f"Sweep Duration: {sweep_duration} seconds")
    print(f"Number of Sweeps: {num_runs}")

    # Generate the SSS and its matching inverse filter
    print("[*] Generating SSS and inverse filter...")
    sss, inv_filter = generate_sss_and_inverse(sample_rate, sweep_duration, 20.0, 20000.0)

    # ----------------------------------------------------
    # Scenario A: Stream ON/OFF for each sweep
    # ----------------------------------------------------
    print("\n--- Running Scenario A: Stream ON/OFF for each sweep ---")
    
    out_signal = np.concatenate([sss, np.zeros(padding_samples)])
    out_data = np.zeros((len(out_signal), 2), dtype=np.float32)
    out_data[:, 0] = out_signal
    out_data[:, 1] = out_signal

    scen_a_ref_peaks = []
    scen_a_meas_peaks = []
    scen_a_relative_delays = []

    # Ensure main stream is stopped before beginning
    engine.stop_stream()

    for run in range(num_runs):
        print(f"  Run {run+1}/{num_runs}...", end="\r")
        try:
            # Recreate PlayRecSession (starts and stops stream)
            rec_data = run_play_rec(engine, out_data)
            
            sig_ref = rec_data[:, ref_channel]
            sig_meas = rec_data[:, meas_channel]

            # Find peaks
            temp_ir_ref = fftconvolve(sig_ref, inv_filter, mode="full")
            t_peak_ref = find_subsample_peak(temp_ir_ref)

            temp_ir_meas = fftconvolve(sig_meas, inv_filter, mode="full")
            t_peak_meas = find_subsample_peak(temp_ir_meas)

            scen_a_ref_peaks.append(t_peak_ref)
            scen_a_meas_peaks.append(t_peak_meas)
            scen_a_relative_delays.append(t_peak_meas - t_peak_ref)

            time.sleep(0.1)  # small gap between runs
        except Exception as e:
            print(f"\n  [-] Run {run+1} failed: {e}")
            engine.stop_stream()
            sys.exit(1)

    print("\n  [+] Scenario A Completed.")

    # ----------------------------------------------------
    # Scenario B: Stream Keep-Open (Continuous playback)
    # ----------------------------------------------------
    print("\n--- Running Scenario B: Stream Keep-Open (Continuous playback) ---")

    single_sweep_len = len(sss)
    sweep_block_len = single_sweep_len + padding_samples
    
    # Construct a continuous signal with 20 back-to-back sweeps
    cont_signal = np.zeros(num_runs * sweep_block_len)
    for run in range(num_runs):
        start_pt = run * sweep_block_len
        cont_signal[start_pt : start_pt + single_sweep_len] = sss

    cont_out_data = np.zeros((len(cont_signal), 2), dtype=np.float32)
    cont_out_data[:, 0] = cont_signal
    cont_out_data[:, 1] = cont_signal

    scen_b_ref_peaks = []
    scen_b_meas_peaks = []
    scen_b_relative_delays = []

    try:
        print(f"  Playing {num_runs} sweeps continuously (Total duration: {len(cont_signal)/sample_rate:.1f}s)...")
        rec_cont_data = run_play_rec(engine, cont_out_data)
        
        # Analyze each sweep block
        for run in range(num_runs):
            print(f"  Analyzing Sweep {run+1}/{num_runs}...", end="\r")
            start_pt = run * sweep_block_len
            end_pt = start_pt + sweep_block_len
            
            sig_ref = rec_cont_data[start_pt:end_pt, ref_channel]
            sig_meas = rec_cont_data[start_pt:end_pt, meas_channel]

            temp_ir_ref = fftconvolve(sig_ref, inv_filter, mode="full")
            t_peak_ref = find_subsample_peak(temp_ir_ref)

            temp_ir_meas = fftconvolve(sig_meas, inv_filter, mode="full")
            t_peak_meas = find_subsample_peak(temp_ir_meas)

            scen_b_ref_peaks.append(t_peak_ref)
            scen_b_meas_peaks.append(t_peak_meas)
            scen_b_relative_delays.append(t_peak_meas - t_peak_ref)
            
    except Exception as e:
        print(f"\n  [-] Scenario B failed: {e}")
        engine.stop_stream()
        sys.exit(1)

    print("\n  [+] Scenario B Completed.")
    engine.stop_stream()

    # ----------------------------------------------------
    # Analysis & Statistics
    # ----------------------------------------------------
    def compute_stats(peaks, rel_delays, name):
        # Convert peaks to relative shift compared to the first run/sweep
        shifts_samples = np.array(peaks) - peaks[0]
        # Convert to microseconds
        shifts_us = (shifts_samples / sample_rate) * 1e6
        
        rel_delays_samples = np.array(rel_delays)
        rel_delays_us = (rel_delays_samples / sample_rate) * 1e6

        stats = {
            "jitter_std_samples": float(np.std(shifts_samples)),
            "jitter_std_us": float(np.std(shifts_us)),
            "jitter_range_samples": float(np.max(shifts_samples) - np.min(shifts_samples)),
            "jitter_range_us": float(np.max(shifts_us) - np.min(shifts_us)),
            "relative_skew_mean_samples": float(np.mean(rel_delays_samples)),
            "relative_skew_mean_us": float(np.mean(rel_delays_us)),
            "relative_skew_std_samples": float(np.std(rel_delays_samples)),
            "relative_skew_std_us": float(np.std(rel_delays_us)),
            "raw_peaks": [float(p) for p in peaks],
            "raw_rel_delays": [float(d) for d in rel_delays]
        }
        return stats

    stats_a = compute_stats(scen_a_ref_peaks, scen_a_relative_delays, "Scenario A (ON/OFF)")
    stats_b = compute_stats(scen_b_ref_peaks, scen_b_relative_delays, "Scenario B (Keep-Open)")

    # Output to console
    print("\n" + "="*60)
    print(" RESULTS COMPARISON")
    print("="*60)
    print(f"{'Metric':<35} | {'Scenario A (ON/OFF)':<20} | {'Scenario B (Keep-Open)':<20}")
    print("-"*81)
    print(f"{'Ref Peak Jitter Std (Samples)':<35} | {stats_a['jitter_std_samples']:>20.4f} | {stats_b['jitter_std_samples']:>20.4f}")
    print(f"{'Ref Peak Jitter Std (us)':<35} | {stats_a['jitter_std_us']:>20.2f} | {stats_b['jitter_std_us']:>20.2f}")
    print(f"{'Ref Peak Jitter Range (Samples)':<35} | {stats_a['jitter_range_samples']:>20.4f} | {stats_b['jitter_range_samples']:>20.4f}")
    print(f"{'Ref Peak Jitter Range (us)':<35} | {stats_a['jitter_range_us']:>20.2f} | {stats_b['jitter_range_us']:>20.2f}")
    print("-"*81)
    print(f"{'L/R relative skew mean (Samples)':<35} | {stats_a['relative_skew_mean_samples']:>20.4f} | {stats_b['relative_skew_mean_samples']:>20.4f}")
    print(f"{'L/R relative skew mean (us)':<35} | {stats_a['relative_skew_mean_us']:>20.2f} | {stats_b['relative_skew_mean_us']:>20.2f}")
    print(f"{'L/R relative skew std (Samples)':<35} | {stats_a['relative_skew_std_samples']:>20.4f} | {stats_b['relative_skew_std_samples']:>20.4f}")
    print(f"{'L/R relative skew std (us)':<35} | {stats_a['relative_skew_std_us']:>20.2f} | {stats_b['relative_skew_std_us']:>20.2f}")
    print("="*60)

    # Save details to JSON report
    report_path = os.path.join(project_root, "scripts", "alignment_drift_results.json")
    report_data = {
        "metadata": {
            "sample_rate": sample_rate,
            "num_runs": num_runs,
            "sweep_duration": sweep_duration,
            "device_name": devices[uac_idx].get("name", "Unknown") if uac_idx is not None else "Default"
        },
        "scenario_a": stats_a,
        "scenario_b": stats_b
    }
    with open(report_path, "w") as f:
        json.dump(report_data, f, indent=4)
    print(f"\n[+] Saved alignment drift analysis report to {report_path}")

def run_play_rec(audio_engine, output_data, input_channels=2):
    """Helper to run a synchronous play/record session via AudioEngine."""
    from src.gui.widgets.nonlinear_analyzer import PlayRecSession
    session = PlayRecSession(audio_engine, output_data, input_channels)
    session.start()
    expected_duration = len(output_data) / audio_engine.sample_rate
    session.wait(timeout=expected_duration + 5.0)
    session.stop()
    return session.input_data

if __name__ == "__main__":
    run_alignment_drift_measurement()
