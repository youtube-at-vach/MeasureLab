#!/usr/bin/env python3
# ruff: noqa: E402, B023
import sys
import os
import time
import json
import argparse
import numpy as np

# Add project root to sys.path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from PyQt6.QtWidgets import QApplication

from src.core.audio_engine import AudioEngine
from src.gui.widgets.nonlinear_analyzer import NonlinearAnalyzer
from src.gui.widgets.lockin_harmonic_analyzer import LockInHarmonicAnalyzer


def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Verify Lock-in vs Nonlinear Analyzer")
    parser.add_argument(
        "--virtual", action="store_true", help="Run in virtual simulation loop mode instead of real device mode"
    )
    parser.add_argument(
        "--fast", action="store_true", help="Run fast virtual simulation mode without audio device delays or sleeps"
    )
    parser.add_argument("--runs", type=int, default=5, help="Number of runs for variability analysis (default: 5)")
    cli_args = parser.parse_args()

    if cli_args.fast:
        cli_args.virtual = True

    # Initialize Qt Application
    QApplication(sys.argv)

    # 1. Initialize Audio Engine
    engine = AudioEngine()

    if cli_args.virtual:
        print("[+] Running in Virtual Simulation Mode")
        engine.set_offline_mode(True)
        engine.set_loopback(True)
        engine.set_sample_rate(48000)
        engine.set_block_size(1024)
    else:
        # 2. Find ZOOM UAC-232 Device Index
        devices = engine.list_devices()
        uac_idx = None
        for idx, dev in enumerate(devices):
            name = dev.get("name", "")
            if (
                "uac-232" in name.lower()
                and dev.get("max_input_channels", 0) >= 2
                and dev.get("max_output_channels", 0) >= 2
            ):
                uac_idx = idx
                break

        if uac_idx is None:
            print("[-] Error: ZOOM UAC-232 not found.")
            sys.exit(1)

        print(f"[+] Found ZOOM UAC-232 at index {uac_idx}")
        engine.set_devices(uac_idx, uac_idx)
        engine.set_sample_rate(48000)
        engine.set_block_size(1024)
        engine.set_loopback(False)
        engine.offline_mode = False

    num_runs = cli_args.runs
    f0 = 1000.0
    A_in = 10 ** (-6.0 / 20.0)  # -6 dBFS
    nyquist = engine.sample_rate / 2.0

    # ----------------------------------------------------
    # Phase A: Nonlinear System Sweep (SSS) - Multiple Runs
    # ----------------------------------------------------
    print(f"\n=== Phase A: SSS Sweep (1 kHz Target, {num_runs} Runs) ===")

    nonlin_analyzer = NonlinearAnalyzer(engine)
    nonlin_analyzer.amplitude_db = -6.0
    nonlin_analyzer.num_amplitudes = 5
    nonlin_analyzer.averages = 5
    nonlin_analyzer.sweep_duration = 5
    nonlin_analyzer.start_freq = 20.0
    nonlin_analyzer.end_freq = 20000.0
    nonlin_analyzer.input_mode = "XFER_REV"  # Ref = Ch2 (R), Meas = Ch1 (L)
    nonlin_analyzer.meas_channel_index = 0
    nonlin_analyzer.ref_channel_index = 1
    nonlin_analyzer.output_channel = "STEREO"

    # Wrap run_play_rec to log raw levels
    orig_run_play_rec = nonlin_analyzer.run_play_rec

    def debug_run_play_rec(output_data, input_channels=2, *args, **kwargs):
        if cli_args.fast:
            # In fast mode, bypass time-consuming play/rec and return empty buffer immediately.
            # The offline simulation loopback emulation logic below will fill this with simulated signal.
            rec_data = np.zeros((len(output_data), input_channels), dtype=np.float32)
            progress_callback = kwargs.get("progress_callback")
            if progress_callback:
                progress_callback(100)
        else:
            rec_data = orig_run_play_rec(output_data, input_channels, *args, **kwargs)
        meas_rms = np.sqrt(np.mean(rec_data[:, 0] ** 2))
        ref_rms = np.sqrt(np.mean(rec_data[:, 1] ** 2))
        meas_db = 20 * np.log10(meas_rms * np.sqrt(2) + 1e-12)
        ref_db = 20 * np.log10(ref_rms * np.sqrt(2) + 1e-12)
        print(f"    [SSS PlayRec Step] Raw Meas(Ch1): {meas_db:.2f} dBFS, Raw Ref(Ch2): {ref_db:.2f} dBFS")
        return rec_data

    nonlin_analyzer.run_play_rec = debug_run_play_rec

    class DummyWorker:
        def __init__(self):
            self.is_running = True

    worker = DummyWorker()

    # Register a dummy callback to keep the audio stream active across all SSS runs,
    # preventing startup latency jitter from closing and reopening the stream.
    dummy_cb_id = engine.register_callback(lambda *args, **kwargs: None)

    sss_runs_results = []

    for run in range(num_runs):
        print(f"\n[*] Starting SSS Run {run + 1}/{num_runs}...")
        sweep_results = {}

        def on_update_plot(freqs, mags, phases):
            sweep_results["freqs"] = freqs
            sweep_results["mags"] = mags
            sweep_results["phases"] = phases

        try:
            nonlin_analyzer.signals.update_plot.connect(on_update_plot)
            nonlin_analyzer._execute_measurement(worker)
            nonlin_analyzer.signals.update_plot.disconnect(on_update_plot)
            print(f"[+] SSS Run {run + 1} completed.")
        except Exception as e:
            print(f"[-] SSS Run {run + 1} failed: {e}")
            engine.unregister_callback(dummy_cb_id)
            engine.stop_stream()
            sys.exit(1)

        if not sweep_results:
            print(f"[-] Error: SSS Run {run + 1} did not return any measurement results.")
            engine.unregister_callback(dummy_cb_id)
            engine.stop_stream()
            sys.exit(1)

        # Process SSS model predictions for 1kHz
        freqs = sweep_results["freqs"]
        mags = sweep_results["mags"]
        phases = sweep_results["phases"]

        # Interpolate H for 1kHz harmonics in polar coordinates to avoid magnitude attenuation during interpolation
        H_interp = {}
        for n in range(1, 6):
            f_n = n * f0
            H_interp[n] = {}
            if f_n > nyquist:
                for p in range(1, 6):
                    H_interp[n][p] = 0.0 + 0.0j
                continue
            for p in range(1, 6):
                h_key = f"h{p}"
                mag_db = np.interp(f_n, freqs, mags[h_key])
                # Unwrap phase to handle phase wrapping smoothly during linear interpolation
                phases_rad = np.unwrap(np.radians(phases[h_key]))
                phase_rad_interp = np.interp(f_n, freqs, phases_rad)

                # Apply Inverse LPF Correction to cancel LPF attenuation applied in SSS core
                f_cut = min(20000.0, 1.15 * engine.sample_rate / (2 * p))
                lpf_gain = 1.0
                if p > 1:  # LPF is applied for 2nd harmonic and above
                    lpf_gain = 1.0 / np.sqrt(1.0 + (f_n / f_cut) ** 16)

                mag_db_corrected = mag_db - 20 * np.log10(lpf_gain + 1e-12)
                mag_linear = 10 ** (mag_db_corrected / 20.0)
                H_interp[n][p] = mag_linear * np.exp(1j * phase_rad_interp)

        # Compute Y prediction
        Y = {}
        Y[1] = (1.0) * (
            A_in * H_interp[1][1] + (0.75 * (A_in**3)) * H_interp[1][3] + (0.625 * (A_in**5)) * H_interp[1][5]
        )
        Y[2] = (-1j) * ((0.5 * (A_in**2)) * H_interp[2][2] + (0.5 * (A_in**4)) * H_interp[2][4])
        Y[3] = (-1.0) * ((0.25 * (A_in**3)) * H_interp[3][3] + (0.3125 * (A_in**5)) * H_interp[3][5])
        Y[4] = (+1j) * ((0.125 * (A_in**4)) * H_interp[4][4])
        Y[5] = (1.0) * ((0.0625 * (A_in**5)) * H_interp[5][5])

        pred_fund_phase_rad = np.angle(Y[1])
        run_data = []

        for n in range(1, 6):
            y_val = Y[n]
            pred_amp_db = 20 * np.log10(np.abs(y_val) + 1e-12)
            pred_rel_phase_rad = np.angle(y_val) - n * pred_fund_phase_rad
            pred_rel_phase_deg = np.degrees(pred_rel_phase_rad)
            pred_rel_phase_deg = (pred_rel_phase_deg + 180) % 360 - 180
            run_data.append({"amp_db": pred_amp_db, "phase_deg": pred_rel_phase_deg})
        sss_runs_results.append(run_data)

    # Unregister the dummy callback to allow the stream to stop if needed
    engine.unregister_callback(dummy_cb_id)

    # ----------------------------------------------------
    # Phase B: Lock-in Harmonic Analyzer - Multiple Runs
    # ----------------------------------------------------
    print(f"\n=== Phase B: Lock-in Harmonic Analyzer (1 kHz, {num_runs} Runs) ===")
    lockin = LockInHarmonicAnalyzer(engine)
    lockin.signal_channel = 0  # Ch 1 (L)
    lockin.ref_channel = 1  # Ch 2 (R)
    lockin.max_harmonic = 5
    lockin.buffer_size = 262144
    lockin.output_enabled = True
    lockin.output_channel = 2  # Stereo output (Ch1 & Ch2)

    # Apply DSP Monkey Patches to Lock-in for physical hardware
    orig_extract = lockin._extract_coherent_segment

    def patched_estimate(ref, fs):
        ref_clean = ref - np.mean(ref)
        omega = 2.0 * np.pi * lockin.gen_frequency
        n_samples = len(ref_clean)
        t = np.arange(n_samples) / fs
        ref_i = (2.0 / n_samples) * np.dot(ref_clean, np.cos(omega * t))
        ref_q = (2.0 / n_samples) * np.dot(ref_clean, np.sin(omega * t))
        theta_0 = np.arctan2(ref_i, ref_q)
        return omega, theta_0

    def patched_extract(sig, ref, fs):
        sig_clean = sig - np.mean(sig)
        ref_clean = ref - np.mean(ref)
        sig_seg, ref_seg, phase_seed = orig_extract(sig_clean, ref_clean, fs)
        if phase_seed is not None:
            omega = 2.0 * np.pi * lockin.gen_frequency
            _, theta_0 = phase_seed
            phase_seed = (omega, theta_0)
        return sig_seg, ref_seg, phase_seed

    lockin._estimate_ref_phase_params = patched_estimate
    lockin._extract_coherent_segment = patched_extract

    # Add patch for offline simulation loopback mode if active
    orig_get_ordered = lockin._get_ordered_input_data

    def patched_get_ordered():
        data = orig_get_ordered().copy()
        if engine.offline_mode:
            # Apply typical nonlinear distortion to the signal channel (Ch1 / Left)
            sig = data[:, lockin.signal_channel]
            # y(t) = x(t) - 0.08*x(t)^2 + 0.12*x(t)^3 - 0.04*x(t)^4 + 0.06*x(t)^5
            simulated_meas = sig - 0.08 * (sig**2) + 0.12 * (sig**3) - 0.04 * (sig**4) + 0.06 * (sig**5)
            data[:, lockin.signal_channel] = simulated_meas
        return data

    lockin._get_ordered_input_data = patched_get_ordered

    lockin_runs_results = []

    for run in range(num_runs):
        print(f"\n[*] Starting Lock-in Run {run + 1}/{num_runs}...")
        lockin.gen_frequency = f0
        lockin.gen_amplitude = A_in

        if cli_args.fast:
            # Direct buffer synthesis in fast mode
            print("    [Fast Mode] Direct buffer synthesis...")
            fs = engine.sample_rate
            N = lockin.buffer_size
            t = np.arange(N) / fs
            ref_sig = A_in * np.sin(2 * np.pi * f0 * t)

            with lockin.lock:
                lockin.input_data = np.zeros((N, 2))
                # Note: patched_get_ordered will apply typical nonlinear distortion on the fly,
                # but it expects the clean generator signal in both input channels first.
                lockin.input_data[:, lockin.signal_channel] = ref_sig
                lockin.input_data[:, lockin.ref_channel] = ref_sig
                lockin.input_buffer_pos = 0
                lockin.buffer_filled_samples = N
                lockin.is_running = True
            print("    [Fast Mode] Processing Lock-in DSP directly...")
        else:
            lockin.start_analysis()

            # Stabilize transient buffer
            timeout = 12.0
            start_time = time.time()
            while True:
                with lockin.lock:
                    filled = lockin.buffer_filled_samples
                print(f"    Stabilizing transient buffer: {filled}/{lockin.buffer_size} samples", end="\r")
                if filled >= lockin.buffer_size:
                    break
                if time.time() - start_time > timeout:
                    print("\n    [-] Timeout during stabilization")
                    break
                time.sleep(0.2)

            time.sleep(1.0)
            print("\n    [+] Stabilization complete. Discarding transient data and starting clean capture...")
            lockin.clear_buffer()

            start_time = time.time()
            while True:
                with lockin.lock:
                    filled = lockin.buffer_filled_samples
                print(f"    Steady-state buffer progress: {filled}/{lockin.buffer_size} samples", end="\r")
                if filled >= lockin.buffer_size:
                    break
                if time.time() - start_time > timeout:
                    print("\n    [-] Timeout waiting for steady-state buffer to fill")
                    break
                time.sleep(0.2)

            print("\n    [+] Buffer filled. Processing Lock-in DSP...")
        with lockin.lock:
            data_copy = lockin.input_data.copy()
        raw_sig_rms = np.sqrt(np.mean(data_copy[:, lockin.signal_channel] ** 2))
        raw_ref_rms = np.sqrt(np.mean(data_copy[:, lockin.ref_channel] ** 2))
        raw_sig_db = 20 * np.log10(raw_sig_rms * np.sqrt(2) + 1e-12)
        raw_ref_db = 20 * np.log10(raw_ref_rms * np.sqrt(2) + 1e-12)
        print(f"    [Lock-in Raw Check] Sig(Ch1): {raw_sig_db:.2f} dBFS, Ref(Ch2): {raw_ref_db:.2f} dBFS")

        if engine.last_callback_error:
            print(f"    [-] AudioEngine Callback Error: {engine.last_callback_error}")

        lockin.process()

        meas_amps = lockin.harmonics_amp.copy()
        meas_phases = lockin.harmonics_phase_deg.copy()
        meas_fund_phase_deg = meas_phases[0]

        run_data = []
        for n in range(1, 6):
            meas_amp_db = 20 * np.log10(meas_amps[n - 1] + 1e-12)
            meas_rel_phase_deg = meas_phases[n - 1] - n * meas_fund_phase_deg
            meas_rel_phase_deg = (meas_rel_phase_deg + 180) % 360 - 180
            run_data.append({"amp_db": meas_amp_db, "phase_deg": meas_rel_phase_deg})
        lockin_runs_results.append(run_data)
        lockin.stop_analysis()
        print(f"    [+] Finished Lock-in Run {run + 1}.")

    engine.stop_stream()

    # ----------------------------------------------------
    # Phase C: Statistical Analysis and Comparison
    # ----------------------------------------------------
    print("\n=== Phase C: Statistical Variability Analysis (1 kHz) ===")
    print(f"Comparing SSS ({num_runs} runs) vs Lock-in ({num_runs} runs) at 1 kHz fundamental")

    # Organize data by harmonic order (0 to 4 corresponding to n=1 to 5)
    for idx_n, n in enumerate(range(1, 6)):
        sss_amps = [run[idx_n]["amp_db"] for run in sss_runs_results]
        sss_phases = [run[idx_n]["phase_deg"] for run in sss_runs_results]

        lockin_amps = [run[idx_n]["amp_db"] for run in lockin_runs_results]
        lockin_phases = [run[idx_n]["phase_deg"] for run in lockin_runs_results]

        # Phase unwrapping/alignment to avoid wrap-around artifact in statistics
        def align_phases(phase_list):
            phases = np.array(phase_list)
            # Align phases relative to the first element
            for idx in range(1, len(phases)):
                diff = phases[idx] - phases[0]
                diff = (diff + 180) % 360 - 180
                phases[idx] = phases[0] + diff
            return phases

        sss_phases_aligned = align_phases(sss_phases)
        lockin_phases_aligned = align_phases(lockin_phases)

        print(f"\n--- Harmonic Order {n} ({n * f0:.0f} Hz) ---")
        print(f"{'Metric':<15} | {'SSS Sweep':<30} | {'Lock-in Harmonic':<30}")
        print("-" * 81)

        # Amplitude stats
        sss_amp_mean = np.mean(sss_amps)
        sss_amp_std = np.std(sss_amps)
        lockin_amp_mean = np.mean(lockin_amps)
        lockin_amp_std = np.std(lockin_amps)
        print(f"{'Amp Mean (dB)':<15} | {sss_amp_mean:>12.2f} dB                    | {lockin_amp_mean:>12.2f} dB")
        print(f"{'Amp Std (dB)':<15} | {sss_amp_std:>12.4f} dB                    | {lockin_amp_std:>12.4f} dB")

        # Phase stats
        sss_phase_mean = (np.mean(sss_phases_aligned) + 180) % 360 - 180
        sss_phase_std = np.std(sss_phases_aligned)
        lockin_phase_mean = (np.mean(lockin_phases_aligned) + 180) % 360 - 180
        lockin_phase_std = np.std(lockin_phases_aligned)
        print(
            f"{'Phase Mean (deg)':<15} | {sss_phase_mean:>12.2f} deg                   | {lockin_phase_mean:>12.2f} deg"
        )
        print(f"{'Phase Std (deg)':<15} | {sss_phase_std:>12.4f} deg                   | {lockin_phase_std:>12.4f} deg")

        print("Raw Amplitudes:")
        print(f"  SSS:     {', '.join(f'{v:.2f}' for v in sss_amps)}")
        print(f"  Lock-in: {', '.join(f'{v:.2f}' for v in lockin_amps)}")
        print("Raw Phases (Aligned):")
        print(f"  SSS:     {', '.join(f'{v:.2f}' for v in sss_phases_aligned)}")
        print(f"  Lock-in: {', '.join(f'{v:.2f}' for v in lockin_phases_aligned)}")

    # Save summary report
    report_path = "/Users/vach/MeasureLab/scripts/variability_results.json"
    report_data = {"f0": f0, "num_runs": num_runs, "sss": sss_runs_results, "lockin": lockin_runs_results}
    with open(report_path, "w") as f:
        json.dump(report_data, f, indent=4)
    print(f"\n[+] Saved variability analysis report to {report_path}")


if __name__ == "__main__":
    main()
