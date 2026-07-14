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
from scipy.interpolate import interp1d

# Add project root to sys.path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from PyQt6.QtWidgets import QApplication

from src.core.audio_engine import AudioEngine
from src.core.realtime_sss_core import RealtimeSSSEngine, measure_system_latency
from src.gui.widgets.lockin_harmonic_analyzer import LockInHarmonicAnalyzer


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


def estimate_hammerstein_kernels(
    amplitudes, raw_responses, plot_freqs_array, block_counts, max_blocks, max_harmonic, sample_rate
):
    """
    Estimates the Hammerstein frequency-domain kernels H1..Hp using Parallel Complex Hammerstein method
    with Chebyshev-based subtraction (matching the GUI's Parallel Complex Hammerstein model).
    """
    P = max_harmonic
    num_amplitudes = len(amplitudes)

    valid_idx = np.where(plot_freqs_array > 0)[0]
    if len(valid_idx) < 2:
        raise ValueError("No valid frequency measurement points found.")

    sort_idx = np.argsort(plot_freqs_array[valid_idx])
    sorted_freqs = plot_freqs_array[valid_idx][sort_idx]

    K = num_amplitudes
    J = len(valid_idx)
    g_scaled = np.zeros((K, J, P), dtype=complex)
    phase_corrections = [1.0, 1j, -1.0, -1j, 1.0][:P]
    R_array = amplitudes

    for amp_idx in range(K):
        for p in range(P):
            val = raw_responses[amp_idx, valid_idx, p]
            # Since verify script runs in XFER mode, we multiply by amplitude
            g_scaled[amp_idx, :, p] = val * R_array[amp_idx] * phase_corrections[p]

    g1 = g_scaled[:, :, 0]
    g2 = g_scaled[:, :, 1] if P >= 2 else np.zeros_like(g1)
    g3 = g_scaled[:, :, 2] if P >= 3 else np.zeros_like(g1)
    g4 = g_scaled[:, :, 3] if P >= 4 else np.zeros_like(g1)
    g5 = g_scaled[:, :, 4] if P >= 5 else np.zeros_like(g1)

    R2 = R_array**2
    R3 = R_array**3
    R4 = R_array**4
    R5 = R_array**5

    sum_R10 = np.sum(R_array**10)
    sum_R8 = np.sum(R_array**8)
    sum_R6 = np.sum(R_array**6)
    sum_R4 = np.sum(R_array**4)
    sum_R2 = np.sum(R_array**2)

    H5 = 16.0 * np.sum(g5 * R5[:, np.newaxis], axis=0) / sum_R10 if P >= 5 and sum_R10 > 1e-12 else np.zeros(J, dtype=complex)
    H4 = 8.0 * np.sum(g4 * R4[:, np.newaxis], axis=0) / sum_R8 if P >= 4 and sum_R8 > 1e-12 else np.zeros(J, dtype=complex)

    if P >= 5:
        g3_prime = g3 - (5.0/16.0) * H5[np.newaxis, :] * R5[:, np.newaxis]
    else:
        g3_prime = g3
    H3 = 4.0 * np.sum(g3_prime * R3[:, np.newaxis], axis=0) / sum_R6 if P >= 3 and sum_R6 > 1e-12 else np.zeros(J, dtype=complex)

    if P >= 4:
        g2_prime = g2 - 0.5 * H4[np.newaxis, :] * R4[:, np.newaxis]
    else:
        g2_prime = g2
    H2 = 2.0 * np.sum(g2_prime * R2[:, np.newaxis], axis=0) / sum_R4 if P >= 2 and sum_R4 > 1e-12 else np.zeros(J, dtype=complex)

    g1_prime = g1.copy()
    if P >= 3:
        g1_prime -= 0.75 * H3[np.newaxis, :] * R3[:, np.newaxis]
    if P >= 5:
        g1_prime -= 0.625 * H5[np.newaxis, :] * R5[:, np.newaxis]
    H1 = np.sum(g1_prime * R_array[:, np.newaxis], axis=0) / sum_R2 if sum_R2 > 1e-12 else np.zeros(J, dtype=complex)

    H_est_list = [H1, H2, H3, H4, H5][:P]

    # Frequency mapping to physical harmonic frequency
    H_mapped_list = []
    for p in range(P):
        H_raw = H_est_list[p]
        f_lookups = sorted_freqs / (p + 1)

        mags = np.abs(H_raw)
        phases = np.unwrap(np.angle(H_raw))

        mag_mapped = np.interp(f_lookups, sorted_freqs, mags, left=np.nan, right=np.nan)
        phase_mapped = np.interp(f_lookups, sorted_freqs, phases, left=np.nan, right=np.nan)

        H_mapped = mag_mapped * np.exp(1j * phase_mapped)
        H_mapped_list.append(H_mapped)

    # Apply Butterworth LPF
    H_freqs_res = []
    for p in range(P):
        H_p = H_mapped_list[p]
        if p >= 1:
            f_cut = min(20000.0, 1.15 * sample_rate / 2)
            lpf = 1.0 / np.sqrt(1.0 + (sorted_freqs / f_cut) ** 16)
            H_p = H_p * lpf
        H_freqs_res.append(H_p)

    return H_freqs_res, sorted_freqs


def predict_harmonic_response(f0, A_in, H_freqs, sorted_freqs, sample_rate, max_harmonic=5):
    """
    Predicts the harmonic complex responses (Y1..Y5) under the Hammerstein model for a single tone of frequency f0 and amplitude A_in.
    """
    nyquist = sample_rate / 2.0
    H_interp = {}

    for n in range(1, 6):
        f_n = n * f0
        H_interp[n] = {}
        if f_n > nyquist:
            for p in range(1, 6):
                H_interp[n][p] = 0.0 + 0.0j
            continue

        for p in range(1, 6):
            if p <= len(H_freqs):
                H_raw = H_freqs[p - 1]
                mask = ~np.isnan(H_raw)
                if np.sum(mask) > 1:
                    # Polar Interpolation to prevent phase distortion
                    mags = np.abs(H_raw[mask])
                    phases = np.unwrap(np.angle(H_raw[mask]))

                    mag_val = np.interp(f_n, sorted_freqs[mask], mags, left=0.0, right=0.0)
                    phase_val = np.interp(f_n, sorted_freqs[mask], phases, left=0.0, right=0.0)

                    H_interp[n][p] = mag_val * np.exp(1j * phase_val)
                else:
                    H_interp[n][p] = 0.0 + 0.0j
            else:
                H_interp[n][p] = 0.0 + 0.0j

    # Predict complex harmonic responses (Y)
    Y = {}
    Y[1] = (1.0) * (A_in * H_interp[1][1] + (0.75 * (A_in**3)) * H_interp[1][3] + (0.625 * (A_in**5)) * H_interp[1][5])
    Y[2] = (-1j) * ((0.5 * (A_in**2)) * H_interp[2][2] + (0.5 * (A_in**4)) * H_interp[2][4])
    Y[3] = (-1.0) * ((0.25 * (A_in**3)) * H_interp[3][3] + (0.3125 * (A_in**5)) * H_interp[3][5])
    Y[4] = (+1j) * ((0.125 * (A_in**4)) * H_interp[4][4])
    Y[5] = (1.0) * ((0.0625 * (A_in**5)) * H_interp[5][5])

    # Convert to relative amplitudes (dBFS) and relative phases (deg) relative to fundamental phase
    pred_fund_phase_rad = np.angle(Y[1])
    predictions = []

    for n in range(1, 6):
        y_val = Y[n]
        pred_amp_db = 20 * np.log10(np.abs(y_val) + 1e-12)
        pred_rel_phase_rad = np.angle(y_val) - n * pred_fund_phase_rad
        pred_rel_phase_deg = np.degrees(pred_rel_phase_rad)
        pred_rel_phase_deg = (pred_rel_phase_deg + 180) % 360 - 180
        predictions.append({"amp_db": pred_amp_db, "phase_deg": pred_rel_phase_deg, "complex": y_val})

    return predictions


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

    cli_args = parser.parse_args()

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
        )

        raw_responses_list.append(averaged_results)

    engine.unregister_callback(dummy_cb_id)
    raw_responses = np.array(raw_responses_list)  # (num_amplitudes, max_blocks, max_harmonic)

    # ----------------------------------------------------
    # Phase B: Hammerstein Kernel Estimation & Verification
    # ----------------------------------------------------
    print("\n=== Phase B: Estimating Hammerstein Kernels ===")
    H_freqs, sorted_freqs = estimate_hammerstein_kernels(
        amplitudes=amplitudes,
        raw_responses=raw_responses,
        plot_freqs_array=plot_freqs,
        block_counts=block_counts,
        max_blocks=max_blocks,
        max_harmonic=max_harmonic,
        sample_rate=engine.sample_rate,
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

    print(f"\n--- Model: Parallel Complex Hammerstein (Chebyshev) ---")
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
