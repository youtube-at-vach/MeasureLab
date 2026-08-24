#!/usr/bin/env python3
# ruff: noqa: E402, B023
import sys
import os
import time
import json
import csv
import argparse
import queue
import threading
import numpy as np

# Add project root to sys.path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from PyQt6.QtWidgets import QApplication

from src.core.audio_engine import AudioEngine
from src.core.realtime_sss_core import RealtimeSSSEngine, measure_system_latency
from src.gui.widgets.lockin_harmonic_analyzer import LockInHarmonicAnalyzer
from src.core.hammerstein_model import estimate_hammerstein_kernels, predict_harmonic_response


def run_sss_sweep_capture(
    audio_engine,
    start_freq,
    end_freq,
    sweep_duration,
    amplitude,
    averages=1,
    max_harmonic=5,
    fast_mode=False,
    input_mode="XFER",
    signal_channel=0,
    ref_channel=1,
):
    """
    Runs an SSS sweep at a specific amplitude and returns the raw input audio blocks
    and system latency, without processing.
    """
    # Create a temp engine to determine sweep parameters and outputs
    sss_engine = RealtimeSSSEngine(
        sample_rate=audio_engine.sample_rate,
        sweep_duration=sweep_duration,
        start_freq=start_freq,
        end_freq=end_freq,
        output_amplitude=amplitude,
        max_harmonic=max_harmonic,
        analysis_cycles=256.0,
        num_meas_points=500,
        min_analysis_window=1.0,
        ref_phase_only=False,
    )
    sss_engine.prepare_sweep()

    # Latency calibration
    if not fast_mode:
        print(f"    [SSS Capture - Amp={amplitude:.4f}] Measuring system latency...", flush=True)
        latency = measure_system_latency(audio_engine, start_freq, end_freq, in_ch=signal_channel, out_ch=0)
        print(f"    [SSS Capture - Amp={amplitude:.4f}] Measured latency: {latency:.2f} samples", flush=True)
    else:
        latency = 0.0

    sss_engine.set_latency(latency)
    frames = audio_engine.block_size
    max_blocks = int(np.ceil((sss_engine.sweep_samples + latency) / frames))

    sig_blocks = []
    ref_blocks = []

    for _avg in range(averages):
        if fast_mode:
            # Bypass play-rec loop and compute directly
            out_sig = sss_engine.out_sig
            total_len = len(out_sig) + int(np.ceil(latency))

            indata = np.zeros((total_len, 2), dtype=np.float32)
            if audio_engine.offline_mode:
                # Ch2(R, index 1) is reference (undistorted)
                indata[: len(out_sig), 1] = out_sig
                # Ch1(L, index 0) is measurement (distorted)
                sig = out_sig
                simulated_meas = sig - 0.08 * (sig**2) + 0.12 * (sig**3) - 0.04 * (sig**4) + 0.06 * (sig**5)
                indata[: len(out_sig), 0] = simulated_meas
            else:
                indata[: len(out_sig), 0] = out_sig
                indata[: len(out_sig), 1] = out_sig

            for b in range(max_blocks):
                start_idx = b * frames
                end_idx = min(start_idx + frames, total_len)

                indata_block = np.zeros((frames, 2), dtype=np.float32)
                chunk_len = end_idx - start_idx
                if chunk_len > 0:
                    indata_block[:chunk_len, :] = indata[start_idx:end_idx, :]

                sig_in = indata_block[:, [signal_channel]].copy()
                ref_in = indata_block[:, [ref_channel]].copy() if input_mode == "XFER" else None
                sig_blocks.append(sig_in)
                ref_blocks.append(ref_in)
        else:
            sweep_done = threading.Event()
            current_block = [0]
            data_queue = queue.Queue()

            def sss_callback(indata_buf, outdata_buf, frames_cb, time_cb, status):
                if current_block[0] >= max_blocks:
                    outdata_buf.fill(0)
                    sweep_done.set()
                    return

                sig_in = np.zeros((frames_cb, 1))
                if indata_buf.shape[1] > signal_channel:
                    sig_in[:, 0] = indata_buf[:, signal_channel]

                ref_in = None
                if input_mode == "XFER":
                    ref_in = np.zeros((frames_cb, 1))
                    if indata_buf.shape[1] > ref_channel:
                        ref_in[:, 0] = indata_buf[:, ref_channel]

                sss_engine.generate_output_block(outdata_buf, current_block[0])
                data_queue.put((current_block[0], sig_in, ref_in))
                current_block[0] += 1

            cb_id = audio_engine.register_callback(sss_callback)

            # Process queue items in main thread and collect blocks
            timeout = sweep_duration + 5.0
            start_time = time.time()
            temp_blocks = [None] * max_blocks
            while not sweep_done.is_set() or not data_queue.empty():
                try:
                    item = data_queue.get(timeout=0.1)
                    b_idx, sig_in, ref_in = item
                    temp_blocks[b_idx] = (sig_in, ref_in)
                    data_queue.task_done()
                except queue.Empty:
                    if time.time() - start_time > timeout:
                        print("    [-] Timeout waiting for SSS sweep callback", flush=True)
                        break
                    continue

            audio_engine.unregister_callback(cb_id)

            for b_idx in range(max_blocks):
                block = temp_blocks[b_idx]
                if block is not None:
                    sig_blocks.append(block[0])
                    ref_blocks.append(block[1])
                else:
                    sig_blocks.append(np.zeros((frames, 1)))
                    ref_blocks.append(np.zeros((frames, 1)) if input_mode == "XFER" else None)

    return sig_blocks, ref_blocks, latency


def analyze_captured_sss(
    sample_rate,
    start_freq,
    end_freq,
    sweep_duration,
    amplitude,
    max_harmonic,
    analysis_cycles,
    num_meas_points,
    min_analysis_window,
    ref_phase_only,
    sig_blocks,
    ref_blocks,
    latency,
):
    """
    Offline analysis of recorded sweep signal blocks using specified analysis settings.
    """
    sss_engine = RealtimeSSSEngine(
        sample_rate=sample_rate,
        sweep_duration=sweep_duration,
        start_freq=start_freq,
        end_freq=end_freq,
        output_amplitude=amplitude,
        max_harmonic=max_harmonic,
        analysis_cycles=analysis_cycles,
        num_meas_points=num_meas_points,
        min_analysis_window=min_analysis_window,
        ref_phase_only=ref_phase_only,
    )
    sss_engine.prepare_sweep()
    sss_engine.set_latency(latency)
    sss_engine.reset_filter_states()

    max_blocks = len(sig_blocks)
    accumulated_results = np.zeros((max_blocks, max_harmonic), dtype=complex)
    block_counts = np.zeros(max_blocks, dtype=int)
    plot_freqs = np.zeros(max_blocks)

    for b_idx in range(max_blocks):
        sig_in = sig_blocks[b_idx]
        ref_in = ref_blocks[b_idx]

        f_mid, results, _ = sss_engine.process_input_block(sig_in, b_idx, ref_in_block=ref_in)
        if sss_engine.last_block_was_valid:
            accumulated_results[b_idx, :] += results[:max_harmonic]
            block_counts[b_idx] += 1
            plot_freqs[b_idx] = f_mid

    averaged_results = np.zeros_like(accumulated_results)
    for b in range(max_blocks):
        if block_counts[b] > 0:
            averaged_results[b, :] = accumulated_results[b, :] / block_counts[b]

    return plot_freqs, averaged_results


def run_lockin_measurement(
    audio_engine, f0, A_in, num_runs=20, max_harmonic=5, fast_mode=False, signal_channel=0, ref_channel=1
):
    """
    Measures the harmonic components under a single-tone excitation using the LockInHarmonicAnalyzer.
    """
    lockin = LockInHarmonicAnalyzer(audio_engine)
    lockin.signal_channel = signal_channel
    lockin.ref_channel = ref_channel
    lockin.set_max_harmonic(max_harmonic)
    lockin.buffer_size = 131072
    lockin.output_enabled = True
    lockin.output_channel = 2  # Stereo output (Ch1 & Ch2)

    lockin_runs_results = []

    for run in range(num_runs):
        print(f"    [*] Starting Lock-in Run {run + 1}/{num_runs}...", flush=True)
        lockin.gen_frequency = f0
        lockin.gen_amplitude = A_in

        if fast_mode:
            fs = audio_engine.sample_rate
            N = lockin.buffer_size
            t = np.arange(N) / fs
            ref_sig = A_in * np.sin(2 * np.pi * f0 * t)

            with lockin.lock:
                lockin.input_data = np.zeros((N, 2))
                lockin.input_data[:, signal_channel] = ref_sig
                lockin.input_data[:, ref_channel] = ref_sig

                # Apply nonlinear distortion on loopback in offline mode
                if audio_engine.offline_mode:
                    sig = lockin.input_data[:, ref_channel]
                    simulated_meas = sig - 0.08 * (sig**2) + 0.12 * (sig**3) - 0.04 * (sig**4) + 0.06 * (sig**5)
                    lockin.input_data[:, signal_channel] = simulated_meas

                lockin.input_buffer_pos = 0
                lockin.buffer_filled_samples = N
                lockin.is_running = True
        else:
            lockin.start_analysis()

            # Wait for stabilization (transient)
            timeout = 12.0
            start_time = time.time()
            while True:
                with lockin.lock:
                    filled = lockin.buffer_filled_samples
                if filled >= lockin.buffer_size:
                    break
                if time.time() - start_time > timeout:
                    print("        [-] Lock-in stabilization timeout", flush=True)
                    break
                time.sleep(0.2)

            time.sleep(1.0)
            lockin.clear_buffer()

            start_time = time.time()
            while True:
                with lockin.lock:
                    filled = lockin.buffer_filled_samples
                if filled >= lockin.buffer_size:
                    break
                if time.time() - start_time > timeout:
                    print("        [-] Lock-in capture timeout", flush=True)
                    break
                time.sleep(0.2)

        lockin.process()

        meas_amps = lockin.harmonics_amp.copy()
        meas_phases = lockin.harmonics_phase_deg.copy()
        meas_fund_phase_deg = meas_phases[0]

        run_data = []
        for n in range(1, max_harmonic + 1):
            meas_amp_db = 20 * np.log10(meas_amps[n - 1] + 1e-12)
            meas_rel_phase_deg = meas_phases[n - 1] - n * meas_fund_phase_deg
            meas_rel_phase_deg = (meas_rel_phase_deg + 180) % 360 - 180
            run_data.append({"amp_db": meas_amp_db, "phase_deg": meas_rel_phase_deg})

        lockin_runs_results.append(run_data)
        lockin.stop_analysis()

    return lockin_runs_results, lockin.measured_freq


def main():
    parser = argparse.ArgumentParser(
        description="Grid-search Param Region Matrix Verification for Lock-in Modeler Hammerstein Model"
    )
    parser.add_argument(
        "--virtual", action="store_true", help="Run in virtual simulation loop mode instead of real device"
    )
    parser.add_argument("--fast", action="store_true", help="Run fast simulation without time delays")
    parser.add_argument("--runs", type=int, default=20, help="Number of runs for reference steady-tone measurement")
    parser.add_argument("--f0", type=float, default=1000.0, help="Test frequency for lock-in vs prediction comparison")
    parser.add_argument(
        "--amplitude", type=float, default=-6.0, help="Test amplitude in dBFS for single tone response comparison"
    )
    parser.add_argument("--num-amplitudes", type=int, default=5, help="Number of excitation amplitudes for sweep")
    parser.add_argument("--num-meas-points", type=int, default=500, help="Number of measurement points")
    parser.add_argument("--model", type=str, choices=["chebyshev"], default="chebyshev", help="Model domain mode")
    parser.add_argument(
        "--no-ref-phase-only", action="store_true", help="Disable ref-phase-only mode (use full XFER scaling)"
    )
    parser.add_argument(
        "--test-run", action="store_true", help="Run a quick end-to-end check with minimized parameter grid size"
    )

    cli_args = parser.parse_args()

    ref_phase_only = not cli_args.no_ref_phase_only

    if cli_args.test_run:
        cli_args.fast = True
        cli_args.virtual = True

    if cli_args.fast:
        cli_args.virtual = True

    # Parameter grid definition
    if cli_args.test_run:
        duration_list = [5.0]
        analysis_cycle_list = [8.0, 16.0]
        min_window_list = [0.01, 0.02]
        num_runs = 2
        num_amplitudes = 3
    else:
        duration_list = [5.0, 15.0, 30.0, 60.0, 120.0, 180.0, 300.0]
        analysis_cycle_list = [8.0, 16.0, 32.0, 64.0, 128.0, 256.0, 512.0, 1024.0]
        min_window_list = [0.01, 0.02, 0.03, 0.1, 0.25, 0.5, 1.0, 2.0]
        num_runs = cli_args.runs
        num_amplitudes = cli_args.num_amplitudes

    # Initialize Qt app
    QApplication(sys.argv)

    # Initialize Audio Engine
    engine = AudioEngine()

    if cli_args.virtual:
        print("[+] Running in Virtual Simulation Mode", flush=True)
        engine.set_offline_mode(True)
        engine.set_loopback(True)
        engine.set_sample_rate(48000)
        engine.set_block_size(1024)
    else:
        # Find ZOOM UAC-232 Device Index
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
            print(
                "[-] Error: ZOOM UAC-232 not found. Run with --virtual or --test-run if no real hardware is connected.",
                flush=True,
            )
            sys.exit(1)

        print(f"[+] Found ZOOM UAC-232 at index {uac_idx}", flush=True)
        engine.set_devices(uac_idx, uac_idx)
        engine.set_sample_rate(48000)
        engine.set_block_size(1024)
        engine.set_loopback(False)
        engine.offline_mode = False

    # Apply global nonlinear distortion simulation in offline/virtual loopback mode
    orig_prepare = engine._prepare_logical_input

    def patched_prepare(indata, frames, use_loopback):
        logical_in = orig_prepare(indata, frames, use_loopback).copy()
        if engine.offline_mode:
            rms0 = np.sqrt(np.mean(logical_in[:, 0] ** 2))
            rms1 = np.sqrt(np.mean(logical_in[:, 1] ** 2))

            if rms1 < 1e-6 and rms0 > 1e-6:
                # Left channel only (e.g. latency calibrator sweep)
                sig = logical_in[:, 0]
                simulated_meas = sig - 0.08 * (sig**2) + 0.12 * (sig**3) - 0.04 * (sig**4) + 0.06 * (sig**5)
                logical_in[:, 0] = simulated_meas
            else:
                # Stereo sweep or default case
                sig = logical_in[:, 1]
                simulated_meas = sig - 0.08 * (sig**2) + 0.12 * (sig**3) - 0.04 * (sig**4) + 0.06 * (sig**5)
                logical_in[:, 0] = simulated_meas
        return logical_in

    engine._prepare_logical_input = patched_prepare

    start_freq = 20.0
    end_freq = 20000.0
    max_harmonic = 5

    # ----------------------------------------------------
    # Phase A: Measuring Single Tone Reference via Parallel Lock-in
    # ----------------------------------------------------
    f0 = cli_args.f0
    A_in = 10 ** (cli_args.amplitude / 20.0)
    print("\n=== Phase A: Measuring Steady Single Tone Reference ===", flush=True)
    lockin_results, lockin_measured_freq = run_lockin_measurement(
        engine,
        f0=f0,
        A_in=A_in,
        num_runs=num_runs,
        max_harmonic=max_harmonic,
        fast_mode=cli_args.fast,
        signal_channel=0,
        ref_channel=1,
    )

    # Statistical averaging of lockin runs
    lockin_ref_avg = []
    for idx_n in range(max_harmonic):
        amps = [run[idx_n]["amp_db"] for run in lockin_results]
        phases = [run[idx_n]["phase_deg"] for run in lockin_results]

        # Align phases to avoid wrap-around averaging issues
        phases_aligned = np.array(phases)
        for idx in range(1, len(phases_aligned)):
            diff = phases_aligned[idx] - phases_aligned[0]
            diff = (diff + 180) % 360 - 180
            phases_aligned[idx] = phases_aligned[0] + diff

        lockin_ref_avg.append(
            {
                "amp_db": np.mean(amps),
                "phase_deg": (np.mean(phases_aligned) + 180) % 360 - 180,
                "amp_std": np.std(amps),
                "phase_std": np.std(phases_aligned),
            }
        )

    print("\n[+] Determined Reference Single-Tone Response:", flush=True)
    for n in range(1, max_harmonic + 1):
        print(
            f"  H{n}: Amp = {lockin_ref_avg[n - 1]['amp_db']:.2f} dB (std={lockin_ref_avg[n - 1]['amp_std']:.3f}), Phase = {lockin_ref_avg[n - 1]['phase_deg']:.1f} deg (std={lockin_ref_avg[n - 1]['phase_std']:.2f})",
            flush=True,
        )

    # ----------------------------------------------------
    # Phase B: SSS Sweep Captures (Once per Duration/Amplitude)
    # ----------------------------------------------------
    print("\n=== Phase B: Capturing SSS Sweep Raw Data ===", flush=True)
    max_amp_db = -6.0
    max_amp_linear = 10 ** (max_amp_db / 20.0)
    amplitudes = np.linspace(0.2, 1.0, num_amplitudes) * max_amp_linear

    captured_sweeps = {}

    dummy_cb_id = engine.register_callback(lambda *args, **kwargs: None)

    for dur in duration_list:
        captured_sweeps[dur] = []
        print(f"\n[*] Starting SSS Sweeps for Duration: {dur}s (TSA=1, Amplitude sweep)...", flush=True)
        for amp_idx, amp in enumerate(amplitudes):
            amp_db = 20 * np.log10(amp)
            print(f"  [{amp_idx + 1}/{num_amplitudes}] Recording sweep at Amp = {amp_db:.2f} dBFS...", flush=True)

            sig_blocks, ref_blocks, latency = run_sss_sweep_capture(
                engine,
                start_freq=start_freq,
                end_freq=end_freq,
                sweep_duration=dur,
                amplitude=amp,
                averages=1,  # TSA is fixed to 1 run
                max_harmonic=max_harmonic,
                fast_mode=cli_args.fast,
                input_mode="XFER",
                signal_channel=0,
                ref_channel=1,
            )

            captured_sweeps[dur].append(
                {
                    "amplitude": amp,
                    "sig_blocks": sig_blocks,
                    "ref_blocks": ref_blocks,
                    "latency": latency,
                }
            )

    engine.unregister_callback(dummy_cb_id)
    print("\n[+] SSS Sweep capturing completed.", flush=True)

    # ----------------------------------------------------
    # Phase C: Offline Param Grid-Search Analysis
    # ----------------------------------------------------
    print("\n=== Phase C: Starting Matrix Re-Analysis & Evaluation ===", flush=True)
    results_matrix = []

    for dur in duration_list:
        print(f"\n--- Re-analyzing Duration: {dur}s ---", flush=True)
        for cyc in analysis_cycle_list:
            for win in min_window_list:
                # Re-analyze all captured sweeps for this duration under current settings (cyc, win)
                raw_responses_list = []
                plot_freqs = None

                for item in captured_sweeps[dur]:
                    freqs, avg_res = analyze_captured_sss(
                        sample_rate=engine.sample_rate,
                        start_freq=start_freq,
                        end_freq=end_freq,
                        sweep_duration=dur,
                        amplitude=item["amplitude"],
                        max_harmonic=max_harmonic,
                        analysis_cycles=cyc,
                        num_meas_points=cli_args.num_meas_points,
                        min_analysis_window=win,
                        ref_phase_only=ref_phase_only,
                        sig_blocks=item["sig_blocks"],
                        ref_blocks=item["ref_blocks"],
                        latency=item["latency"],
                    )
                    raw_responses_list.append(avg_res)
                    plot_freqs = freqs

                raw_responses = np.array(raw_responses_list)

                # Fit Hammerstein kernels
                H_freqs, sorted_freqs = estimate_hammerstein_kernels(
                    amplitudes=amplitudes,
                    avg_responses=raw_responses,
                    plot_freqs=plot_freqs,
                    max_harmonic=max_harmonic,
                    sample_rate=engine.sample_rate,
                    input_mode="XFER",
                    ref_phase_only=ref_phase_only,
                )

                # Predict single tone response
                predictions = predict_harmonic_response(
                    lockin_measured_freq, A_in, H_freqs, sorted_freqs, engine.sample_rate, max_harmonic
                )

                # Calculate errors
                amp_diffs = []
                phase_diffs = []
                for n in range(1, max_harmonic + 1):
                    pred_amp = predictions[n - 1]["amp_db"]
                    pred_phase = predictions[n - 1]["phase_deg"]
                    meas_amp = lockin_ref_avg[n - 1]["amp_db"]
                    meas_phase = lockin_ref_avg[n - 1]["phase_deg"]

                    # Skip evaluation if components are close to the noise floor
                    level_too_low = (pred_amp < -90.0) and (meas_amp < -90.0)
                    if not level_too_low:
                        amp_diff = np.abs(pred_amp - meas_amp)
                        phase_diff_raw = pred_phase - meas_phase
                        phase_diff = np.abs((phase_diff_raw + 180) % 360 - 180)
                        amp_diffs.append(amp_diff)
                        phase_diffs.append(phase_diff)

                mae_amp = np.mean(amp_diffs) if amp_diffs else 0.0
                mae_phase = np.mean(phase_diffs) if phase_diffs else 0.0
                max_amp_err = np.max(amp_diffs) if amp_diffs else 0.0
                max_phase_err = np.max(phase_diffs) if phase_diffs else 0.0

                results_matrix.append(
                    {
                        "duration_s": dur,
                        "analysis_cycle": cyc,
                        "min_window_ms": int(win * 1000),
                        "mae_amp_db": mae_amp,
                        "mae_phase_deg": mae_phase,
                        "max_amp_err_db": max_amp_err,
                        "max_phase_err_deg": max_phase_err,
                    }
                )

        # Print results table for this duration
        print("\n=========================================================================================", flush=True)
        print(f" MATRIX EVALUATION SUMMARY: Duration = {dur}s", flush=True)
        print("=========================================================================================", flush=True)
        print(
            " Cycles     | Min Window   | MAE Amp (dB)   | MAE Phase (deg)  | Max Amp Err (dB)  | Max Phase Err (deg)",
            flush=True,
        )
        print("-" * 105, flush=True)
        dur_results = [r for r in results_matrix if r["duration_s"] == dur]
        for r in dur_results:
            win_str = f"{r['min_window_ms']} ms"
            print(
                f" {r['analysis_cycle']:<10.1f} | {win_str:<12} | {r['mae_amp_db']:>14.4f} | {r['mae_phase_deg']:>16.4f} | {r['max_amp_err_db']:>17.4f} | {r['max_phase_err_deg']:>20.4f}",
                flush=True,
            )
        print("=========================================================================================", flush=True)

    # ----------------------------------------------------
    # Exporting Results
    # ----------------------------------------------------
    output_json_path = "/Users/vach/MeasureLab/scripts/lock_in_modeler_hammerstein_matrix_results.json"
    output_csv_path = "/Users/vach/MeasureLab/scripts/lock_in_modeler_hammerstein_matrix_results.csv"

    # Export to JSON
    with open(output_json_path, "w", encoding="utf-8") as f:
        json.dump(results_matrix, f, indent=4)
    print(f"\n[+] Saved matrix JSON results to {output_json_path}", flush=True)

    # Export to CSV
    with open(output_csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "duration_s",
                "analysis_cycle",
                "min_window_ms",
                "mae_amp_db",
                "mae_phase_deg",
                "max_amp_err_db",
                "max_phase_err_deg",
            ]
        )
        for r in results_matrix:
            writer.writerow(
                [
                    r["duration_s"],
                    r["analysis_cycle"],
                    r["min_window_ms"],
                    r["mae_amp_db"],
                    r["mae_phase_deg"],
                    r["max_amp_err_db"],
                    r["max_phase_err_deg"],
                ]
            )
    print(f"[+] Saved matrix CSV results to {output_csv_path}", flush=True)
    print("\n[+] Verification run completed successfully.", flush=True)


if __name__ == "__main__":
    main()
