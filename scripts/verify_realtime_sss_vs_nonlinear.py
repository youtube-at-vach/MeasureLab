#!/usr/bin/env python3
# ruff: noqa: E402, B023
import sys
import os
import time
import json
import numpy as np
import matplotlib.pyplot as plt

# Add project root to sys.path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from PyQt6.QtWidgets import QApplication

from src.core.audio_engine import AudioEngine
from src.gui.widgets.nonlinear_analyzer import NonlinearAnalyzer
from src.gui.widgets.realtime_sss_analyzer import RealtimeSSSAnalyzer
from src.core.realtime_sss_core import measure_system_latency

def main():
    # Initialize Qt Application (required for signals and components)
    _app = QApplication(sys.argv)

    # 1. Initialize Audio Engine in virtual/offline mode
    engine = AudioEngine()
    engine.set_offline_mode(True)
    engine.set_loopback(True)
    engine.set_sample_rate(48000)
    engine.set_block_size(1024)

    # 2. Monkey patch AudioEngine to apply nonlinear distortion in offline mode.
    # y(t) = x(t) - 0.08*x(t)^2 + 0.12*x(t)^3 - 0.04*x(t)^4 + 0.06*x(t)^5
    orig_prepare_logical_input = engine._prepare_logical_input

    def patched_prepare_logical_input(indata, frames, use_loopback):
        logical_in = orig_prepare_logical_input(indata, frames, use_loopback)
        if use_loopback and engine.offline_mode:
            # We apply distortion to Ch 0 (Left / Measurement)
            # R channel Ch 1 (Right / Reference) remains clean
            sig = logical_in[:, 0].copy()
            simulated_meas = sig - 0.08 * (sig**2) + 0.12 * (sig**3) - 0.04 * (sig**4) + 0.06 * (sig**5)
            logical_in[:, 0] = simulated_meas
        return logical_in

    engine._prepare_logical_input = patched_prepare_logical_input

    # Common sweep parameters
    f_start = 50.0
    f_end = 15000.0
    duration = 8.0
    amplitude_db = -6.0
    amplitude_linear = 10 ** (amplitude_db / 20.0)

    # ----------------------------------------------------
    # Phase A: Offline Nonlinear Analyzer (Deconvolution)
    # ----------------------------------------------------
    print("\n=== Phase A: Offline Nonlinear SSS Sweep ===")
    nonlin = NonlinearAnalyzer(engine)
    nonlin.amplitude_db = amplitude_db
    nonlin.num_amplitudes = 5
    nonlin.averages = 1
    nonlin.sweep_duration = duration
    nonlin.start_freq = f_start
    nonlin.end_freq = f_end
    nonlin.input_mode = "XFER_REV"  # Ref = Ch 2 (Right), Meas = Ch 1 (Left)
    nonlin.meas_channel_index = 0
    nonlin.ref_channel_index = 1
    nonlin.output_channel = "STEREO"
    # Disable noise floor check to avoid extra silence block in comparison
    nonlin.measure_noise_floor = False

    class DummyWorker:
        def __init__(self):
            self.is_running = True

    nonlin_results = {}
    def on_nonlin_update(freqs, mags, phases):
        nonlin_results["freqs"] = freqs
        nonlin_results["mags"] = mags
        nonlin_results["phases"] = phases

    nonlin.signals.update_plot.connect(on_nonlin_update)

    print("[*] Running Offline Sweep...")
    nonlin._execute_measurement(DummyWorker())

    if not nonlin_results:
        print("[-] Error: Offline Nonlinear Analyzer sweep failed.")
        sys.exit(1)
    print("[+] Offline Sweep completed.")

    # ----------------------------------------------------
    # Phase B: Real-time SSS Lock-in Analyzer (DDC + LPF)
    # ----------------------------------------------------
    print("\n=== Phase B: Real-time SSS Lock-in Sweep ===")
    rt_sss = RealtimeSSSAnalyzer(engine)
    rt_sss.start_freq = f_start
    rt_sss.end_freq = f_end
    rt_sss.sweep_duration = duration
    rt_sss.output_amplitude = amplitude_linear
    rt_sss.lpf_factor = 0.08
    rt_sss.max_harmonic = 5
    rt_sss.input_mode = "XFER"
    rt_sss.signal_channel = 0  # Meas = Ch 1 (Left)
    rt_sss.ref_channel = 1     # Ref = Ch 2 (Right)
    rt_sss.output_channel = 2  # Stereo

    # Measure latency for real-time SSS (required for phase synchronization)
    print("[*] Measuring virtual loopback latency...")
    try:
        latency = measure_system_latency(
            engine,
            start_freq=f_start,
            end_freq=f_end,
            duration=0.25,
            in_ch=0,
            out_ch=2
        )
        print(f"[+] Virtual loopback latency: {latency:.2f} samples")
    except Exception as e:
        print(f"[-] Latency measurement failed: {e}. Defaulting to block size.")
        latency = float(engine.block_size)

    rt_sss.latency_samples = latency

    # Run analysis
    print("[*] Starting Real-time Sweep...")
    rt_sss.start_analysis()

    # Collect data from measurement queue
    rt_freqs = []
    rt_gains = [[] for _ in range(5)]
    rt_phases = [[] for _ in range(5)]

    timeout = duration + 3.0
    start_t = time.time()

    # Process queue in a loop to simulate UI timer update
    while rt_sss.is_running:
        # Retrieve pending blocks
        items = []
        with rt_sss.lock:
            while rt_sss.measurement_queue:
                items.append(rt_sss.measurement_queue.popleft())

        for f_mid, results in items:
            rt_freqs.append(f_mid)
            for idx in range(5):
                if idx < len(results):
                    c_val = results[idx]
                    amp = np.abs(c_val)
                    db = 20 * np.log10(amp + 1e-15)
                    rt_gains[idx].append(db)

                    phase_deg = np.degrees(np.angle(c_val))
                    rt_phases[idx].append(phase_deg)
                else:
                    rt_gains[idx].append(np.nan)
                    rt_phases[idx].append(np.nan)

        if rt_sss.current_block_idx >= rt_sss.max_blocks:
            break

        time.sleep(0.05)
        if time.time() - start_t > timeout:
            print("[-] Real-time sweep timed out!")
            break

    rt_sss.stop_analysis()
    print("[+] Real-time Sweep completed.")

    # ----------------------------------------------------
    # Phase C: Interpolation, Re-synthesis & Comparison
    # ----------------------------------------------------
    print("\n=== Phase C: Comparison & Verification ===")

    # Define common frequency limits
    f_min = max(f_start, 60.0)  # Avoid transients at start limit
    f_max = min(f_end, 14000.0) # Avoid transients at end limit
    fs = engine.sample_rate
    nonlin_mags = nonlin_results["mags"]
    nonlin_phases = nonlin_results["phases"]
    nonlin_freqs = nonlin_results["freqs"]

    # 1. Reconstruct clean, un-attenuated Hammerstein Kernels (H_q) in complex domain
    H_clean_raw = {}
    for q in range(1, 6):
        h_key = f"h{q}"
        nl_mag_db = nonlin_mags[h_key]
        nl_phase_deg = nonlin_phases[h_key]

        # Unwrap phase
        nl_phase_unwrapped = np.unwrap(np.radians(nl_phase_deg))

        # LPF Inverse correction (only for 2nd harmonic and above)
        lpf_gain = 1.0
        if q > 1:
            f_cut = min(20000.0, 1.15 * fs / (2 * q))
            lpf_gain = 1.0 / np.sqrt(1.0 + (nonlin_freqs / f_cut) ** 16)

        mag_db_corrected = nl_mag_db - 20 * np.log10(lpf_gain + 1e-12)
        mag_linear = 10 ** (mag_db_corrected / 20.0)
        H_clean_raw[q] = mag_linear * np.exp(1j * nl_phase_unwrapped)

    harmonics_to_compare = 5

    fig, axs = plt.subplots(3, 2, figsize=(14, 12), sharex=True)
    fig.suptitle("Algorithm Verification: Real-time SSS (DDC+LPF) vs Offline SSS (Deconvolution)", fontsize=14)

    colors = ["#1f77b4", "#2ca02c", "#bcbd22", "#9467bd", "#d62728"]
    summary_metrics = {}

    # For THD calculations (restricted to max 4500Hz basic sweep frequency)
    f_eval_thd = np.logspace(np.log10(f_min), np.log10(4500.0), 300)
    nl_amps_thd = []
    rt_amps_thd = []

    for h in range(1, harmonics_to_compare + 1):
        h_key = f"h{h}"

        # Calculate LPF cutoff for this harmonic as used in NonlinearAnalyzer
        f_cut_h = min(20000.0, 1.15 * fs / (2 * h)) if h > 1 else f_max
        # Define evaluation grid for this specific harmonic to avoid Nyquist aliasing
        # and regions where the offline analyzer's LPF has already completely suppressed the signal.
        # We limit the fundamental frequency such that the harmonic frequency is below 0.95 * f_cut_h.
        f_max_h = min(f_max, 0.95 * f_cut_h / h)
        f_min_h = max(150.0, f_min)
        f_eval_h = np.logspace(np.log10(f_min_h), np.log10(f_max_h), 300)

        # Interpolate H_clean_raw to f_eval_h
        H_clean_interp = {}
        for q in range(1, 6):
            mag_linear = np.abs(H_clean_raw[q])
            phase_unwrapped = np.unwrap(np.angle(H_clean_raw[q]))

            mag_i = np.interp(f_eval_h, nonlin_freqs, mag_linear)
            phase_i = np.interp(f_eval_h, nonlin_freqs, phase_unwrapped)
            H_clean_interp[q] = mag_i * np.exp(1j * phase_i)

        # Synthesize predicted physical harmonic output Y_pred at f_eval_h
        A = amplitude_linear
        if h == 1:
            y_val = (A * H_clean_interp[1] + 0.75 * (A**3) * H_clean_interp[3] + 0.625 * (A**5) * H_clean_interp[5]) / A
        elif h == 2:
            y_val = (0.5 * (A**2) * H_clean_interp[2] + 0.5 * (A**4) * H_clean_interp[4]) / A
        elif h == 3:
            y_val = (0.25 * (A**3) * H_clean_interp[3] + 0.3125 * (A**5) * H_clean_interp[5]) / A
        elif h == 4:
            y_val = (0.125 * (A**4) * H_clean_interp[4]) / A
        elif h == 5:
            y_val = (0.0625 * (A**5) * H_clean_interp[5]) / A

        nl_mag_interp = 20 * np.log10(np.abs(y_val) + 1e-15)
        nl_phase_interp = np.degrees(np.unwrap(np.angle(y_val)))
        nl_phase_interp = (nl_phase_interp + 180) % 360 - 180

        # Real-time SSS Interpolation on f_eval_h
        rt_mag_db = np.array(rt_gains[h - 1])
        rt_phase_deg = np.array(rt_phases[h - 1])

        valid = np.isfinite(rt_mag_db) & np.isfinite(rt_phase_deg)
        if not np.any(valid):
            print(f"[-] No valid real-time SSS data for Harmonic {h}")
            continue

        rt_phase_unwrapped = np.unwrap(np.radians(rt_phase_deg[valid]))
        rt_mag_interp = np.interp(f_eval_h, np.array(rt_freqs)[valid], rt_mag_db[valid])
        rt_phase_interp = np.degrees(np.interp(f_eval_h, np.array(rt_freqs)[valid], rt_phase_unwrapped))
        rt_phase_interp = (rt_phase_interp + 180) % 360 - 180

        # Calculate errors
        mag_diff = rt_mag_interp - nl_mag_interp
        phase_diff = rt_phase_interp - nl_phase_interp
        phase_diff = (phase_diff + 180) % 360 - 180

        mae_mag = np.mean(np.abs(mag_diff))
        max_mag = np.max(np.abs(mag_diff))
        mae_phase = np.mean(np.abs(phase_diff))
        max_phase = np.max(np.abs(phase_diff))

        summary_metrics[h_key] = {
            "gain_mae_db": float(mae_mag),
            "gain_max_db": float(max_mag),
            "phase_mae_deg": float(mae_phase),
            "phase_max_deg": float(max_phase),
        }

        print(f"Harmonic {h} ({'Fundamental' if h==1 else f'{h}th Harmonic'}):")
        print(f"  Evaluation Range: {f_min:.1f} - {f_max_h:.1f} Hz")
        print(f"  Gain Error:  MAE = {mae_mag:.3f} dB, Max = {max_mag:.3f} dB")
        print(f"  Phase Error: MAE = {mae_phase:.3f} deg, Max = {max_phase:.3f} deg")

        # Plot predicted vs real-time
        axs[0, 0].plot(f_eval_h, nl_mag_interp, label=f"H{h} Predicted", color=colors[h-1], linestyle="-")
        axs[0, 0].plot(rt_freqs, rt_gains[h-1], label=f"H{h} Real-time", color=colors[h-1], linestyle="--")

        axs[1, 0].plot(f_eval_h, nl_phase_interp, color=colors[h-1], linestyle="-")
        axs[1, 0].plot(rt_freqs, rt_phases[h-1], color=colors[h-1], linestyle="--")

        axs[0, 1].plot(f_eval_h, mag_diff, label=f"H{h} Error", color=colors[h-1])
        axs[1, 1].plot(f_eval_h, phase_diff, color=colors[h-1])

        # Interpolate for THD calculation on common f_eval_thd grid
        H_clean_thd = {}
        for q in range(1, 6):
            mag_linear = np.abs(H_clean_raw[q])
            mag_i = np.interp(f_eval_thd, nonlin_freqs, mag_linear)
            phase_unwrapped = np.unwrap(np.angle(H_clean_raw[q]))
            phase_i = np.interp(f_eval_thd, nonlin_freqs, phase_unwrapped)
            H_clean_thd[q] = mag_i * np.exp(1j * phase_i)

        if h == 1:
            y_val_thd = (A * H_clean_thd[1] + 0.75 * (A**3) * H_clean_thd[3] + 0.625 * (A**5) * H_clean_thd[5]) / A
        elif h == 2:
            y_val_thd = (0.5 * (A**2) * H_clean_thd[2] + 0.5 * (A**4) * H_clean_thd[4]) / A
        elif h == 3:
            y_val_thd = (0.25 * (A**3) * H_clean_thd[3] + 0.3125 * (A**5) * H_clean_thd[5]) / A
        elif h == 4:
            y_val_thd = (0.125 * (A**4) * H_clean_thd[4]) / A
        elif h == 5:
            y_val_thd = (0.0625 * (A**5) * H_clean_thd[5]) / A

        nl_amps_thd.append(20 * np.log10(np.abs(y_val_thd) + 1e-15))

        rt_mag_thd = np.interp(f_eval_thd, np.array(rt_freqs)[valid], rt_mag_db[valid])
        rt_amps_thd.append(rt_mag_thd)

    # 3. Plot Total Harmonic Distortion (THD)
    # THD = sqrt(sum(H2^2..H5^2)) / H1
    # We will compute THD for both offline and real-time models and compare them.
    def compute_thd_db(mags_db_list):
        # Convert dB to linear amplitude
        amps = [10 ** (m / 20.0) for m in mags_db_list]
        h1 = amps[0]
        harmonics_sq = sum(a**2 for a in amps[1:])
        thd = np.sqrt(harmonics_sq) / (h1 + 1e-12)
        return 20 * np.log10(thd + 1e-12)

    nl_thd_db = compute_thd_db(nl_amps_thd)
    rt_thd_db = compute_thd_db(rt_amps_thd)
    thd_diff = rt_thd_db - nl_thd_db

    axs[2, 0].plot(f_eval_thd, nl_thd_db, label="Offline THD", color="black", linestyle="-")
    axs[2, 0].plot(f_eval_thd, rt_thd_db, label="Real-time THD", color="red", linestyle="--")
    axs[2, 0].set_ylabel("THD (dB)")
    axs[2, 0].legend()
    axs[2, 0].grid(True)

    axs[2, 1].plot(f_eval_thd, thd_diff, label="THD Error (RT - Offline)", color="purple")
    axs[2, 1].set_ylabel("THD Error (dB)")
    axs[2, 1].legend()
    axs[2, 1].grid(True)

    # Format plots
    axs[0, 0].set_ylabel("Gain / Amplitude (dB)")
    axs[0, 0].legend(loc="lower left")
    axs[0, 0].grid(True)
    axs[0, 0].set_title("Response Characteristics")

    axs[1, 0].set_ylabel("Phase (degrees)")
    axs[1, 0].grid(True)

    axs[0, 1].set_ylabel("Gain Error (dB)")
    axs[0, 1].legend(loc="lower left")
    axs[0, 1].grid(True)
    axs[0, 1].set_title("Absolute Errors (Real-time - Offline)")

    axs[1, 1].set_ylabel("Phase Error (degrees)")
    axs[1, 1].grid(True)

    for col in range(2):
        axs[2, col].set_xlabel("Frequency (Hz)")
        axs[2, col].set_xscale("log")

    plt.tight_layout()
    plot_path = os.path.join(project_root, "scripts", "verification_results.png")
    plt.savefig(plot_path, dpi=150)
    print(f"\n[+] Saved verification plot to {plot_path}")

    # Save JSON metrics
    json_path = os.path.join(project_root, "scripts", "verification_results.json")
    with open(json_path, "w") as f:
        json.dump(summary_metrics, f, indent=4)
    print(f"[+] Saved metrics JSON to {json_path}")

    # Evaluate overall check criteria
    # Criteria: Fundamental gain MAE < 0.25 dB, Harmonic gain MAE < 1.2 dB.
    passed = True
    for h in range(1, 6):
        h_key = f"h{h}"
        gain_mae = summary_metrics[h_key]["gain_mae_db"]
        phase_mae = summary_metrics[h_key]["phase_mae_deg"]

        limit_gain = 0.25 if h == 1 else 1.2
        limit_phase = 5.0 if h == 1 else 15.0

        if gain_mae > limit_gain or phase_mae > limit_phase:
            passed = False
            print(f"[-] WARNING: Harmonic {h} exceeded error thresholds (Limit Gain: {limit_gain}dB, Phase: {limit_phase}deg)")

    if passed:
        print("\n[+] Verification PASSED! Algorithm level correctness confirmed.")
        sys.exit(0)
    else:
        print("\n[-] Verification FAILED or thresholds exceeded. Please inspect errors.")
        sys.exit(1)

if __name__ == "__main__":
    main()
