#!/usr/bin/env python3
import sys
import time
import json
import numpy as np
from PyQt6.QtWidgets import QApplication

from src.core.audio_engine import AudioEngine
from src.gui.widgets.nonlinear_system_analyzer import NonlinearSystemAnalyzer
from src.gui.widgets.lockin_harmonic_analyzer import LockInHarmonicAnalyzer

def main():
    # Initialize Qt Application
    QApplication(sys.argv)

    # 1. Initialize Audio Engine
    engine = AudioEngine()

    # 2. Find ZOOM UAC-232 Device Index
    devices = engine.list_devices()
    uac_idx = None
    for idx, dev in enumerate(devices):
        name = dev.get("name", "")
        if "uac-232" in name.lower() and dev.get("max_input_channels", 0) >= 2 and dev.get("max_output_channels", 0) >= 2:
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

    # 3. Phase A: Nonlinear System Sweep & Model Building
    print("\n=== Phase A: Nonlinear System Analyzer (SSS Sweep) ===")
    nonlin_analyzer = NonlinearSystemAnalyzer(engine)
    nonlin_analyzer.amplitude_db = -6.0
    nonlin_analyzer.num_amplitudes = 5
    nonlin_analyzer.averages = 2
    nonlin_analyzer.sweep_duration = 5.0
    nonlin_analyzer.start_freq = 20.0
    nonlin_analyzer.end_freq = 20000.0
    nonlin_analyzer.input_mode = "XFER_REV"  # Ref = Ch2 (R), Meas = Ch1 (L)
    nonlin_analyzer.meas_channel_index = 0
    nonlin_analyzer.ref_channel_index = 1
    nonlin_analyzer.output_channel = "STEREO"

    sweep_results = {}

    def on_update_plot(freqs, mags, phases):
        sweep_results['freqs'] = freqs
        sweep_results['mags'] = mags
        sweep_results['phases'] = phases

    nonlin_analyzer.signals.update_plot.connect(on_update_plot)

    class DummyWorker:
        def __init__(self):
            self.is_running = True

    worker = DummyWorker()

    # Wrap run_play_rec to log raw levels
    orig_run_play_rec = nonlin_analyzer.run_play_rec

    def debug_run_play_rec(output_data, input_channels=2):
        rec_data = orig_run_play_rec(output_data, input_channels)
        meas_rms = np.sqrt(np.mean(rec_data[:, 0]**2))
        ref_rms = np.sqrt(np.mean(rec_data[:, 1]**2))
        meas_db = 20 * np.log10(meas_rms * np.sqrt(2) + 1e-12)
        ref_db = 20 * np.log10(ref_rms * np.sqrt(2) + 1e-12)
        print(f"    [SSS PlayRec Step] Raw Meas(Ch1): {meas_db:.2f} dBFS, Raw Ref(Ch2): {ref_db:.2f} dBFS")
        return rec_data

    nonlin_analyzer.run_play_rec = debug_run_play_rec

    try:
        print("[*] Running SSS sweep measurements...")
        nonlin_analyzer._execute_measurement(worker)
        print("[+] SSS sweep completed.")
    except Exception as e:
        print(f"[-] SSS Sweep failed: {e}")
        engine.stop_stream()
        sys.exit(1)

    if not sweep_results:
        print("[-] Error: SSS sweep did not return any measurement results.")
        engine.stop_stream()
        sys.exit(1)

    # 4. Phase B: Lock-in Harmonic Analyzer Measurements (with Monkey Patches)
    print("\n=== Phase B: Lock-in Harmonic Analyzer (Single-Tone) ===")
    lockin = LockInHarmonicAnalyzer(engine)
    lockin.signal_channel = 0  # Ch 1 (L)
    lockin.ref_channel = 1     # Ch 2 (R)
    lockin.max_harmonic = 5
    lockin.buffer_size = 262144
    lockin.output_enabled = True
    lockin.output_channel = 2  # Stereo output (Ch1 & Ch2)

    # Apply DSP Monkey Patches to Lock-in for physical hardware
    orig_extract = lockin._extract_coherent_segment

    def patched_estimate(ref, fs):
        # 1. Remove DC offset
        ref_clean = ref - np.mean(ref)
        # 2. Lock frequency to the generator frequency
        omega = 2.0 * np.pi * lockin.gen_frequency
        # 3. Estimate starting phase angle theta_0 via single-bin correlation
        n_samples = len(ref_clean)
        t = np.arange(n_samples) / fs
        ref_i = (2.0 / n_samples) * np.dot(ref_clean, np.cos(omega * t))
        ref_q = (2.0 / n_samples) * np.dot(ref_clean, np.sin(omega * t))
        theta_0 = np.arctan2(ref_i, ref_q)
        return omega, theta_0

    def patched_extract(sig, ref, fs):
        # Remove DC offset
        sig_clean = sig - np.mean(sig)
        ref_clean = ref - np.mean(ref)
        # Run original extraction to get the segmented slice boundaries
        sig_seg, ref_seg, phase_seed = orig_extract(sig_clean, ref_clean, fs)
        if phase_seed is not None:
            # Overwrite estimated frequency with the exact generator frequency
            omega = 2.0 * np.pi * lockin.gen_frequency
            _, theta_0 = phase_seed
            phase_seed = (omega, theta_0)
        return sig_seg, ref_seg, phase_seed

    lockin._estimate_ref_phase_params = patched_estimate
    lockin._extract_coherent_segment = patched_extract

    lockin_results = {}
    target_freqs = [100.0, 1000.0, 10000.0]

    for f0 in target_freqs:
        print(f"\n[*] Starting Lock-in measurement at {f0} Hz...")
        lockin.gen_frequency = f0
        lockin.gen_amplitude = 10 ** (-6.0 / 20.0)  # -6 dBFS

        # Start analysis stream and wait for the initial buffer to fill
        # (This flushes out initial device startup transients and allows filters/clocks to settle)
        lockin.start_analysis()

        timeout = 12.0
        start_time = time.time()
        while True:
            with lockin.lock:
                filled = lockin.buffer_filled_samples
            print(f"    Stabilizing transient buffer: {filled}/{lockin.buffer_size} samples", end="\r")
            if filled >= lockin.buffer_size:
                break
            if time.time() - start_time > timeout:
                print(f"\n    [-] Timeout during stabilization at {f0} Hz")
                break
            time.sleep(0.2)

        # Add 1.0 second delay for full settling
        time.sleep(1.0)

        # Clear the buffer while the stream is still running to start a clean capture of steady-state data
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
                print(f"\n    [-] Timeout waiting for steady-state buffer to fill at {f0} Hz")
                break
            time.sleep(0.2)

        print("\n    [+] Buffer filled. Processing Lock-in DSP...")

        with lockin.lock:
            data_copy = lockin.input_data.copy()
        raw_sig_rms = np.sqrt(np.mean(data_copy[:, lockin.signal_channel]**2))
        raw_ref_rms = np.sqrt(np.mean(data_copy[:, lockin.ref_channel]**2))
        raw_sig_db = 20 * np.log10(raw_sig_rms * np.sqrt(2) + 1e-12)
        raw_ref_db = 20 * np.log10(raw_ref_rms * np.sqrt(2) + 1e-12)
        print(f"    [Lock-in Raw Check] Sig(Ch1): {raw_sig_db:.2f} dBFS, Ref(Ch2): {raw_ref_db:.2f} dBFS")

        if engine.last_callback_error:
            print(f"    [-] AudioEngine Callback Error detected: {engine.last_callback_error} (count: {engine.callback_error_count})")

        lockin.process()

        lockin_results[f0] = {
            'measured_freq': lockin.measured_freq,
            'amps': lockin.harmonics_amp.copy(),
            'phases': lockin.harmonics_phase_deg.copy()
        }

        lockin.stop_analysis()
        print(f"    [+] Finished Lock-in at {f0} Hz.")

    engine.stop_stream()

    # 5. Phase C: Compare SSS Model Predictions vs Lock-in Measurements
    print("\n=== Phase C: Consistency Analysis ===")
    freqs = sweep_results['freqs']
    mags = sweep_results['mags']
    phases = sweep_results['phases']

    H_dict = {}
    for p in range(1, 6):
        h_key = f"h{p}"
        mag_linear = 10 ** (mags[h_key] / 20.0)
        phase_rad = np.radians(phases[h_key])
        H_dict[p] = mag_linear * np.exp(1j * phase_rad)

    comparison_report = {}
    nyquist = engine.sample_rate / 2.0
    A_in = 10 ** (-6.0 / 20.0)

    for f0 in target_freqs:
        H_interp = {}
        for n in range(1, 6):
            f_n = n * f0
            H_interp[n] = {}
            if f_n > nyquist:
                for p in range(1, 6):
                    H_interp[n][p] = 0.0 + 0.0j
                continue

            for p in range(1, 6):
                real_val = np.interp(f_n, freqs, np.real(H_dict[p]))
                imag_val = np.interp(f_n, freqs, np.imag(H_dict[p]))
                H_interp[n][p] = real_val + 1j * imag_val

        Y = {}
        Y[1] = (1.0) * (
            A_in * H_interp[1][1] + (0.75 * (A_in**3)) * H_interp[1][3] + (0.625 * (A_in**5)) * H_interp[1][5]
        )
        Y[2] = (-1j) * ((0.5 * (A_in**2)) * H_interp[2][2] + (0.5 * (A_in**4)) * H_interp[2][4])
        Y[3] = (-1.0) * ((0.25 * (A_in**3)) * H_interp[3][3] + (0.3125 * (A_in**5)) * H_interp[3][5])
        Y[4] = (+1j) * ((0.125 * (A_in**4)) * H_interp[4][4])
        Y[5] = (1.0) * ((0.0625 * (A_in**5)) * H_interp[5][5])

        pred_fund_phase_rad = np.angle(Y[1])

        lockin_data = lockin_results.get(f0)
        if not lockin_data:
            print(f"[-] No Lock-in data for {f0} Hz")
            continue

        meas_amps = lockin_data['amps']
        meas_phases = lockin_data['phases']
        meas_fund_phase_deg = meas_phases[0]

        # Interpolate reference loopback phase at fundamental frequency f0
        ref_phase_f0 = np.interp(f0, freqs, phases.get("ref_phase", np.zeros_like(freqs)))

        print(f"\n--- Comparative Verification at {f0} Hz (Measured Freq: {lockin_data['measured_freq']:.2f} Hz) ---")
        print(f"{'Harmonic':<10} | {'Pred Amp':<10} | {'Meas Amp':<10} | {'Amp Diff':<10} | {'Pred Ph':<10} | {'Corr Pred':<10} | {'Meas Ph':<10} | {'Ph Diff':<10} | {'Corr PhDiff':<12}")
        print("-" * 115)

        harmonic_comparison = []

        for n in range(1, 6):
            f_n = n * f0
            if f_n > nyquist:
                print(f"{n:<10} | {'N/A (Nyquist)':>10} | {'N/A':>10} | {'N/A':>10} | {'N/A':>10} | {'N/A':>10} | {'N/A':>10} | {'N/A':>10} | {'N/A':>12}")
                continue

            y_val = Y[n]
            pred_amp_db = 20 * np.log10(np.abs(y_val) + 1e-12)

            pred_rel_phase_rad = np.angle(y_val) - n * pred_fund_phase_rad
            pred_rel_phase_deg = np.degrees(pred_rel_phase_rad)
            pred_rel_phase_deg = (pred_rel_phase_deg + 180) % 360 - 180

            # Apply loopback correction: ref_phase(f_n) - n * ref_phase(f_0)
            ref_phase_fn = np.interp(f_n, freqs, phases.get("ref_phase", np.zeros_like(freqs)))
            loopback_corr_deg = ref_phase_fn - n * ref_phase_f0
            pred_rel_phase_corr_deg = pred_rel_phase_deg + loopback_corr_deg
            pred_rel_phase_corr_deg = (pred_rel_phase_corr_deg + 180) % 360 - 180

            meas_amp_db = 20 * np.log10(meas_amps[n-1] + 1e-12)
            meas_rel_phase_deg = meas_phases[n-1] - n * meas_fund_phase_deg
            meas_rel_phase_deg = (meas_rel_phase_deg + 180) % 360 - 180

            amp_diff = meas_amp_db - pred_amp_db

            phase_diff = meas_rel_phase_deg - pred_rel_phase_deg
            phase_diff = (phase_diff + 180) % 360 - 180

            phase_diff_corr = meas_rel_phase_deg - pred_rel_phase_corr_deg
            phase_diff_corr = (phase_diff_corr + 180) % 360 - 180

            print(f"{n:<10} | {pred_amp_db:>10.2f} | {meas_amp_db:>10.2f} | {amp_diff:>10.2f} | {pred_rel_phase_deg:>10.2f} | {pred_rel_phase_corr_deg:>10.2f} | {meas_rel_phase_deg:>10.2f} | {phase_diff:>10.2f} | {phase_diff_corr:>12.2f}")

            harmonic_comparison.append({
                'order': n,
                'freq_hz': f_n,
                'pred_amp_db': pred_amp_db,
                'meas_amp_db': meas_amp_db,
                'amp_diff_db': amp_diff,
                'pred_phase_deg': pred_rel_phase_deg,
                'pred_phase_corr_deg': pred_rel_phase_corr_deg,
                'meas_phase_deg': meas_rel_phase_deg,
                'phase_diff_deg': phase_diff,
                'phase_diff_corr_deg': phase_diff_corr
            })

        comparison_report[int(f0)] = harmonic_comparison

    report_path = "/Users/vach/MeasureLab/scripts/verification_results.json"
    with open(report_path, "w") as f:
        json.dump({
            "target_freqs": target_freqs,
            "sample_rate": engine.sample_rate,
            "amplitude_db": -6.0,
            "comparison": comparison_report
        }, f, indent=4)
    print(f"\n[+] Saved verification report to {report_path}")

if __name__ == "__main__":
    main()
