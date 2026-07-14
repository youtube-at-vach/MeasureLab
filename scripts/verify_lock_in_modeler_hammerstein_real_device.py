#!/usr/bin/env python3
# ruff: noqa: E402, B023
import sys
import os
import time
import json
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


def run_sss_sweep(
    audio_engine,
    start_freq,
    end_freq,
    sweep_duration,
    amplitude,
    averages,
    max_harmonic=5,
    fast_mode=False,
    input_mode="XFER",
    signal_channel=0,
    ref_channel=1,
    analysis_cycles=256.0,
    num_meas_points=500,
    min_analysis_window=1.0,
    ref_phase_only=False,
):
    """
    Runs an SSS sweep at a specific amplitude and returns the averaged harmonic responses.
    """
    sss_engine = RealtimeSSSEngine(
        sample_rate=audio_engine.sample_rate,
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

    # Latency calibration
    if not fast_mode:
        print(f"    [SSS - Amp={amplitude:.4f}] Measuring system latency...")
        latency = measure_system_latency(audio_engine, start_freq, end_freq, in_ch=signal_channel, out_ch=0)
        print(f"    [SSS - Amp={amplitude:.4f}] Measured latency: {latency:.2f} samples")
    else:
        latency = 0.0

    sss_engine.set_latency(latency)
    frames = audio_engine.block_size
    max_blocks = int(np.ceil((sss_engine.sweep_samples + latency) / frames))

    accumulated_results = np.zeros((max_blocks, max_harmonic), dtype=complex)
    block_counts = np.zeros(max_blocks, dtype=int)
    plot_freqs = np.zeros(max_blocks)

    for _avg in range(averages):
        sss_engine.reset_filter_states()

        if fast_mode:
            # Bypass play-rec loop and compute directly
            out_sig = sss_engine.out_sig
            total_len = len(out_sig) + int(np.ceil(latency))

            # Directly simulate the loopback signal with nonlinear distortion
            indata = np.zeros((total_len, 2), dtype=np.float32)
            if audio_engine.offline_mode:
                # Ch2(R, index 1) is reference (undistorted)
                indata[: len(out_sig), 1] = out_sig
                # Ch1(L, index 0) is measurement (distorted)
                sig = out_sig
                simulated_meas = sig - 0.08 * (sig**2) + 0.12 * (sig**3) - 0.04 * (sig**4) + 0.06 * (sig**5)
                indata[: len(out_sig), 0] = simulated_meas
            else:
                # Linear ideal case if offline_mode is not active for some reason
                indata[: len(out_sig), 0] = out_sig
                indata[: len(out_sig), 1] = out_sig

            for b in range(max_blocks):
                start_idx = b * frames
                end_idx = min(start_idx + frames, total_len)

                indata_block = np.zeros((frames, 2), dtype=np.float32)
                chunk_len = end_idx - start_idx
                if chunk_len > 0:
                    indata_block[:chunk_len, :] = indata[start_idx:end_idx, :]

                sig_in = indata_block[:, [signal_channel]]
                ref_in = indata_block[:, [ref_channel]] if input_mode == "XFER" else None

                f_mid, results = sss_engine.process_input_block(sig_in, b, ref_in_block=ref_in)
                if sss_engine.last_block_was_valid:
                    accumulated_results[b, :] += results[:max_harmonic]
                    block_counts[b] += 1
                    plot_freqs[b] = f_mid
        else:
            # Standard real-time callback sweep
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

            # Process queue items in main thread
            timeout = sweep_duration + 5.0
            start_time = time.time()
            while not sweep_done.is_set() or not data_queue.empty():
                try:
                    item = data_queue.get(timeout=0.1)
                    b_idx, sig_in, ref_in = item
                    f_mid, results = sss_engine.process_input_block(sig_in, b_idx, ref_in_block=ref_in)
                    if sss_engine.last_block_was_valid:
                        accumulated_results[b_idx, :] += results[:max_harmonic]
                        block_counts[b_idx] += 1
                        plot_freqs[b_idx] = f_mid
                    data_queue.task_done()
                except queue.Empty:
                    if time.time() - start_time > timeout:
                        print("    [-] Timeout waiting for SSS sweep callback")
                        break
                    continue

            audio_engine.unregister_callback(cb_id)

    # Compute averages
    averaged_results = np.zeros_like(accumulated_results)
    for b in range(max_blocks):
        if block_counts[b] > 0:
            averaged_results[b, :] = accumulated_results[b, :] / block_counts[b]

    return plot_freqs, averaged_results, block_counts, max_blocks




def run_lockin_measurement(
    audio_engine, f0, A_in, num_runs=5, max_harmonic=5, fast_mode=False, signal_channel=0, ref_channel=1
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
        print(f"    [*] Starting Lock-in Run {run + 1}/{num_runs}...")
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
                    print("        [-] Lock-in stabilization timeout")
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
                    print("        [-] Lock-in capture timeout")
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
        description="Verify Lock-in Modeler Hammerstein Model vs Lock-in on Real/Virtual Device"
    )
    parser.add_argument(
        "--virtual", action="store_true", help="Run in virtual simulation loop mode instead of real device"
    )
    parser.add_argument("--fast", action="store_true", help="Run fast simulation without time delays")
    parser.add_argument("--runs", type=int, default=5, help="Number of runs for statistics and stability")
    parser.add_argument("--f0", type=float, default=1000.0, help="Test frequency for lock-in vs prediction comparison")
    parser.add_argument(
        "--amplitude", type=float, default=-6.0, help="Test amplitude in dBFS for single tone response comparison"
    )
    parser.add_argument("--tsa", type=int, default=1, help="Number of TSA (Time Synchronous Averaging) sweep averages")
    parser.add_argument("--sweep-duration", type=float, default=30.0, help="Duration of SSS sweep in seconds")
    parser.add_argument("--num-amplitudes", type=int, default=5, help="Number of excitation amplitudes")
    parser.add_argument(
        "--analysis-cycles", type=float, default=256.0, help="Lock-in integration window size in cycles"
    )
    parser.add_argument("--num-meas-points", type=int, default=500, help="Number of measurement points")
    parser.add_argument("--min-analysis-window", type=float, default=1.0, help="Minimum analysis window in seconds")
    parser.add_argument(
        "--model", type=str, choices=["chebyshev"], default="chebyshev", help="Model domain mode (only 'chebyshev' is supported now)"
    )
    parser.add_argument(
        "--no-ref-phase-only", action="store_true", help="Disable ref-phase-only mode (use full XFER scaling)"
    )

    cli_args = parser.parse_args()

    ref_phase_only = not cli_args.no_ref_phase_only

    if cli_args.fast:
        cli_args.virtual = True

    # Initialize Qt app
    QApplication(sys.argv)

    # Initialize Audio Engine
    engine = AudioEngine()

    if cli_args.virtual:
        print("[+] Running in Virtual Simulation Mode")
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
            print("[-] Error: ZOOM UAC-232 not found. Run with --virtual if no real hardware is connected.")
            sys.exit(1)

        print(f"[+] Found ZOOM UAC-232 at index {uac_idx}")
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
            # Check signal levels to handle single-channel calibration sweeps properly
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

    # ----------------------------------------------------
    # Phase A: SSS Sweep at Multiple Amplitudes
    # ----------------------------------------------------
    print("\n=== Phase A: Lock-in Modeler Sweeps for Hammerstein Kernel Estimation ===")

    # Sweep configuration
    start_freq = 20.0
    end_freq = 20000.0
    sweep_duration = cli_args.sweep_duration  # seconds
    max_harmonic = 5

    # Range of amplitudes for least-squares kernel separation
    num_amplitudes = cli_args.num_amplitudes
    max_amp_db = -6.0
    max_amp_linear = 10 ** (max_amp_db / 20.0)
    amplitudes = np.linspace(0.2, 1.0, num_amplitudes) * max_amp_linear

    raw_responses_list = []

    # Dummy stream callback to prevent audio engine from shutting down/startup latency between sweeps
    dummy_cb_id = engine.register_callback(lambda *args, **kwargs: None)

    # Run SSS sweep at each amplitude
    for amp_idx, amp in enumerate(amplitudes):
        amp_db = 20 * np.log10(amp)
        print(f"\n[*] Running SSS sweep {amp_idx + 1}/{num_amplitudes} (Amplitude: {amp_db:.2f} dBFS)...")

        plot_freqs, averaged_results, block_counts, max_blocks = run_sss_sweep(
            engine,
            start_freq=start_freq,
            end_freq=end_freq,
            sweep_duration=sweep_duration,
            amplitude=amp,
            averages=cli_args.tsa,
            max_harmonic=max_harmonic,
            fast_mode=cli_args.fast,
            input_mode="XFER",
            signal_channel=0,  # Ch1 (L)
            ref_channel=1,  # Ch2 (R)
            analysis_cycles=cli_args.analysis_cycles,
            num_meas_points=cli_args.num_meas_points,
            min_analysis_window=cli_args.min_analysis_window,
            ref_phase_only=ref_phase_only,
        )

        raw_responses_list.append(averaged_results)

    engine.unregister_callback(dummy_cb_id)
    raw_responses = np.array(raw_responses_list)  # (num_amplitudes, max_blocks, max_harmonic)

    print("\n=== Phase B: Estimating Hammerstein Kernels ===")
    H_freqs, sorted_freqs = estimate_hammerstein_kernels(
        amplitudes=amplitudes,
        avg_responses=raw_responses,
        plot_freqs=plot_freqs,
        max_harmonic=max_harmonic,
        sample_rate=engine.sample_rate,
        input_mode="XFER",
        ref_phase_only=ref_phase_only,
    )
    print("[+] Estimated Hammerstein kernels (Chebyshev Parallel Complex method).")

    # ----------------------------------------------------
    # Phase C: Measuring Single Tone Response via Parallel Lock-in
    # ----------------------------------------------------
    f0 = cli_args.f0
    A_in = 10 ** (cli_args.amplitude / 20.0)
    print("\n=== Phase C: Measuring Single Tone Response via Parallel Lock-in ===")
    lockin_results, lockin_measured_freq = run_lockin_measurement(
        engine,
        f0=f0,
        A_in=A_in,
        num_runs=cli_args.runs,
        max_harmonic=max_harmonic,
        fast_mode=cli_args.fast,
        signal_channel=0,
        ref_channel=1,
    )

    # ----------------------------------------------------
    # Phase D: Predict Harmonic Response for target single-tone
    # ----------------------------------------------------
    print(
        f"\n=== Phase D: Predicting Single Tone Response (f0={lockin_measured_freq:.2f} Hz, Amp={cli_args.amplitude:.2f} dBFS) ==="
    )
    predictions = predict_harmonic_response(
        lockin_measured_freq, A_in, H_freqs, sorted_freqs, engine.sample_rate, max_harmonic
    )

    # Statistical averaging of lockin runs
    lockin_avg = []
    for idx_n in range(max_harmonic):
        amps = [run[idx_n]["amp_db"] for run in lockin_results]
        phases = [run[idx_n]["phase_deg"] for run in lockin_results]

        # Align phases to avoid wrap-around averaging issues
        phases_aligned = np.array(phases)
        for idx in range(1, len(phases_aligned)):
            diff = phases_aligned[idx] - phases_aligned[0]
            diff = (diff + 180) % 360 - 180
            phases_aligned[idx] = phases_aligned[0] + diff

        lockin_avg.append(
            {
                "amp_db": np.mean(amps),
                "phase_deg": (np.mean(phases_aligned) + 180) % 360 - 180,
                "amp_std": np.std(amps),
                "phase_std": np.std(phases_aligned),
            }
        )

    # ----------------------------------------------------
    # Phase E: Comparison and Validation
    # ----------------------------------------------------
    print("\n=== Phase E: Comparison Results ===")

    amp_diffs = []
    phase_diffs = []

    print("\n--- Model: Parallel Complex Hammerstein (Chebyshev) ---")
    print(
        f"{'Harmonic':<10} | {'Predicted Amp (dB)':<20} | {'Measured Amp (dB)':<20} | {'Amp Diff (dB)':<15} | {'Predicted Phase':<18} | {'Measured Phase':<18} | {'Phase Diff':<12}"
    )
    print("-" * 115)

    comp_list = []
    for n in range(1, max_harmonic + 1):
        pred_amp = predictions[n - 1]["amp_db"]
        pred_phase = predictions[n - 1]["phase_deg"]

        meas_amp = lockin_avg[n - 1]["amp_db"]
        meas_phase = lockin_avg[n - 1]["phase_deg"]

        amp_diff = np.abs(pred_amp - meas_amp)
        phase_diff_raw = pred_phase - meas_phase
        phase_diff = np.abs((phase_diff_raw + 180) % 360 - 180)

        # Skip validation checking for higher harmonics if the level is extremely low (near noise floor)
        level_too_low = (pred_amp < -90.0) and (meas_amp < -90.0)
        if not level_too_low:
            amp_diffs.append(amp_diff)
            phase_diffs.append(phase_diff)

        print(
            f"H{n} ({n * f0 / 1000.0:.1f} kHz) | {pred_amp:>18.2f} | {meas_amp:>18.2f} (std={lockin_avg[n - 1]['amp_std']:.3f}) | {amp_diff:>13.2f} | {pred_phase:>14.1f} deg | {meas_phase:>14.1f} deg (std={lockin_avg[n - 1]['phase_std']:.2f}) | {phase_diff:>10.1f} deg"
        )

        comp_list.append(
            {
                "harmonic": n,
                "frequency_hz": n * f0,
                "predicted": {"amp_db": pred_amp, "phase_deg": pred_phase},
                "measured": {
                    "amp_db": meas_amp,
                    "phase_deg": meas_phase,
                    "amp_std": lockin_avg[n - 1]["amp_std"],
                    "phase_std": lockin_avg[n - 1]["phase_std"],
                },
                "diff": {"amp_db": amp_diff, "phase_deg": phase_diff},
            }
        )

    mae_amp = np.mean(amp_diffs) if amp_diffs else 0.0
    mae_phase = np.mean(phase_diffs) if phase_diffs else 0.0
    max_amp_err = np.max(amp_diffs) if amp_diffs else 0.0
    max_phase_err = np.max(phase_diffs) if phase_diffs else 0.0

    print("\n" + "=" * 90)
    print("=== MODEL ACCURACY SUMMARY ===")
    print("=" * 90)
    print(f"MAE Amp: {mae_amp:.4f} dB")
    print(f"MAE Phase: {mae_phase:.4f} deg")
    print(f"Max Amp Error: {max_amp_err:.4f} dB")
    print(f"Max Phase Error: {max_phase_err:.4f} deg")
    print("=" * 90)

    amp_tolerance = 0.5  # dB
    phase_tolerance = 1.0  # degrees

    failed = False
    for item in comp_list:
        n = item["harmonic"]
        amp_diff = item["diff"]["amp_db"]
        phase_diff = item["diff"]["phase_deg"]
        pred_amp = item["predicted"]["amp_db"]
        meas_amp = item["measured"]["amp_db"]
        level_too_low = (pred_amp < -90.0) and (meas_amp < -90.0)

        if cli_args.virtual and not level_too_low:
            if amp_diff > amp_tolerance:
                print(
                    f"    [-] FAIL: H{n} amplitude difference exceeds threshold ({amp_diff:.2f} > {amp_tolerance} dB)"
                )
                failed = True
            if phase_diff > phase_tolerance:
                print(
                    f"    [-] FAIL: H{n} phase difference exceeds threshold ({phase_diff:.2f} > {phase_tolerance} deg)"
                )
                failed = True

    # Save results to JSON
    output_report_path = "/Users/vach/MeasureLab/scripts/lock_in_modeler_hammerstein_verification_results.json"
    report_data = {
        "f0": f0,
        "test_amplitude_dbfs": cli_args.amplitude,
        "is_virtual": cli_args.virtual,
        "is_fast": cli_args.fast,
        "runs": cli_args.runs,
        "target_model": cli_args.model,
        "mae_amp": mae_amp,
        "mae_phase": mae_phase,
        "max_amp_err": max_amp_err,
        "max_phase_err": max_phase_err,
        "results": comp_list,
        "success": not failed,
    }

    with open(output_report_path, "w") as f:
        json.dump(report_data, f, indent=4)
    print(f"\n[+] Saved verification report to {output_report_path}")

    if cli_args.virtual:
        if failed:
            print(f"\n[-] Lock-in Modeler Hammerstein Verification FAILED for target model '{cli_args.model}'.")
            sys.exit(1)
        else:
            print(f"\n[+] Lock-in Modeler Hammerstein Verification PASSED for target model '{cli_args.model}'.")
            sys.exit(0)


if __name__ == "__main__":
    main()
