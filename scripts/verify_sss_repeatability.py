#!/usr/bin/env python3
# ruff: noqa: E402, B023
import sys
import os
import json
import argparse
import threading
import numpy as np

# Add project root to sys.path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Set headless Matplotlib backend to avoid GUI window opening
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from PyQt6.QtWidgets import QApplication

from src.core.audio_engine import AudioEngine
from src.core.realtime_sss_core import RealtimeSSSEngine, measure_system_latency


class PlayRecSession:
    """Helper to run a synchronous play/record session via AudioEngine."""

    def __init__(self, audio_engine, output_data, input_channels=2):
        self.audio_engine = audio_engine
        self.output_data = output_data
        self.total_frames = len(output_data)
        self.input_channels = input_channels
        self.input_data = np.zeros((self.total_frames, input_channels), dtype=np.float32)
        self.current_frame = 0
        self.is_complete = False
        self.callback_id = None
        self.lock = threading.Lock()
        self.completion_event = threading.Event()
        self.error = None

    def start(self):
        self.callback_id = self.audio_engine.register_callback(self._callback)
        if self.audio_engine.stream is None and not getattr(self.audio_engine, "offline_mode", False):
            self.error = "Audio stream failed to start. Please check audio device settings."
            self.is_complete = True
            self.completion_event.set()

    def stop(self):
        if self.callback_id is not None:
            self.audio_engine.unregister_callback(self.callback_id)
            self.callback_id = None

    def wait(self, timeout=None):
        completed = self.completion_event.wait(timeout)
        if not completed:
            self.error = "Audio playback timed out. Audio device may have stopped responding."
        if self.error:
            raise RuntimeError(str(self.error))

    def _callback(self, indata, outdata, frames, time_info, status):
        with self.lock:
            if self.is_complete:
                outdata.fill(0)
                return

            try:
                remaining = self.total_frames - self.current_frame
                chunk = min(frames, remaining)

                # Playback
                ch_out = min(outdata.shape[1], self.output_data.shape[1])
                outdata[:chunk, :ch_out] = self.output_data[self.current_frame : self.current_frame + chunk, :ch_out]
                if ch_out < outdata.shape[1]:
                    outdata[:chunk, ch_out:] = 0
                if chunk < frames:
                    outdata[chunk:, :] = 0

                # Record
                if indata.shape[1] > 0:
                    ch_to_copy = min(self.input_channels, indata.shape[1])
                    self.input_data[self.current_frame : self.current_frame + chunk, :ch_to_copy] = indata[
                        :chunk, :ch_to_copy
                    ]

                self.current_frame += chunk

                if self.current_frame >= self.total_frames:
                    self.is_complete = True
                    self.completion_event.set()
            except Exception as e:
                self.error = f"Audio Callback Error: {e}"
                self.is_complete = True
                self.completion_event.set()


def run_play_rec(audio_engine, output_data, input_channels=2):
    session = PlayRecSession(audio_engine, output_data, input_channels)
    session.start()
    expected_duration = len(output_data) / audio_engine.sample_rate
    session.wait(timeout=expected_duration + 5.0)
    session.stop()
    return session.input_data


def align_phases(phases, ref_phase=None):
    """
    Align phases to avoid wrap-around artifacts during statistical computations (mean/std).
    """
    phases = np.array(phases)
    if ref_phase is None:
        ref_phase = phases[0]
    for idx in range(len(phases)):
        diff = phases[idx] - ref_phase
        diff = (diff + 180) % 360 - 180
        phases[idx] = ref_phase + diff
    return phases


def main():
    parser = argparse.ArgumentParser(description="Verify SSS Repeatability / Phase Variation")
    parser.add_argument("--virtual", action="store_true", help="Run in virtual simulation loop mode")
    parser.add_argument("--no-noise", action="store_true", help="Disable random noise in virtual simulation mode")
    parser.add_argument("--no-jitter", action="store_true", help="Disable random jitter in virtual simulation mode")
    parser.add_argument("--harmonic-jitter-comp", action="store_true", help="Enable harmonic-order jitter compensation in relative mode")
    parser.add_argument("--runs", type=int, default=5, help="Number of sweep runs to execute")
    parser.add_argument("--cycles", type=float, default=512.0, help="Number of analysis cycles")
    parser.add_argument("--duration", type=float, default=20.0, help="Sweep duration in seconds")
    parser.add_argument("--amplitude", type=float, default=-6.0, help="Sweep amplitude in dBFS")
    parser.add_argument(
        "--mode",
        choices=["Single_L", "Single_R", "XFER", "XFER_REV"],
        default="XFER_REV",
        help="Input routing mode",
    )
    cli_args = parser.parse_args()

    # Required for AudioEngine initialization in PyQt environment
    QApplication(sys.argv)

    engine = AudioEngine()

    if cli_args.virtual:
        print("[+] Running in Virtual Simulation Mode")
        engine.set_offline_mode(True)
        engine.set_loopback(True)
        engine.set_sample_rate(48000)
        engine.set_block_size(1024)
    else:
        # Detect ZOOM UAC-232 device
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

        if uac_idx is not None:
            print(f"[+] ZOOM UAC-232 found at index {uac_idx}. Using it.")
            engine.set_devices(uac_idx, uac_idx)
        else:
            print("[-] Warning: ZOOM UAC-232 not found. Using default audio device.")
            # Do not force set_devices to let sounddevice pick defaults

        engine.set_offline_mode(False)
        engine.set_loopback(False)
        engine.set_sample_rate(48000)
        engine.set_block_size(1024)

    # Route configuration mapping
    if cli_args.mode == "Single_L":
        input_mode = "Single"
        sig_ch = 0
        ref_ch = 1
    elif cli_args.mode == "Single_R":
        input_mode = "Single"
        sig_ch = 1
        ref_ch = 0
    elif cli_args.mode == "XFER":
        input_mode = "XFER"
        sig_ch = 1
        ref_ch = 0
    else:  # XFER_REV
        input_mode = "XFER"
        sig_ch = 0
        ref_ch = 1

    print(f"[+] Route config: Mode={cli_args.mode} (Sig={sig_ch}, Ref={ref_ch})")

    # 1. Latency Calibration
    print("[*] Calibrating system latency...")
    if cli_args.virtual:
        # Simulate static latency for virtual mode
        latency_samples = 1024.0
        print(f"[+] Simulated Latency: {latency_samples} samples")
    else:
        try:
            latency_samples = measure_system_latency(
                engine,
                start_freq=20.0,
                end_freq=20000.0,
                duration=0.25,
                in_ch=sig_ch,
                out_ch=2,  # Stereo out
            )
            print(f"[+] Measured Latency: {latency_samples:.2f} samples")
        except Exception as e:
            print(f"[-] Latency calibration failed: {e}. Falling back to 1024 samples.")
            latency_samples = 1024.0

    # 2. Setup SSS Sweep Parameters
    sample_rate = engine.sample_rate
    sweep_duration = cli_args.duration
    start_freq = 20.0
    end_freq = 20000.0
    output_amplitude = 10 ** (cli_args.amplitude / 20.0)
    max_harmonic = 5
    analysis_cycles = cli_args.cycles
    num_meas_points = 500

    # Determine maximum blocks for analysis
    # We construct a temporary engine to know the sweep_samples beforehand
    temp_engine = RealtimeSSSEngine(
        sample_rate=sample_rate,
        sweep_duration=sweep_duration,
        start_freq=start_freq,
        end_freq=end_freq,
        output_amplitude=output_amplitude,
        max_harmonic=max_harmonic,
        analysis_cycles=analysis_cycles,
        num_meas_points=num_meas_points,
    )
    temp_engine.prepare_sweep()
    frames_per_block = engine.block_size
    max_blocks = int(np.ceil((temp_engine.sweep_samples + latency_samples) / frames_per_block))
    del temp_engine

    print(f"[+] Sweep details: {sweep_duration}s, max_blocks={max_blocks}, cycles={analysis_cycles}")

    # Results container: shape (runs, max_blocks, max_harmonic) of complex response
    raw_runs_results = np.zeros((cli_args.runs, max_blocks, max_harmonic), dtype=complex)
    block_freqs = np.zeros(max_blocks)

    # 3. Measurement Loop
    for run_idx in range(cli_args.runs):
        print(f"\n[*] Starting Run {run_idx + 1}/{cli_args.runs}...")

        # Setup new engine(s) for each run
        run_engine_sig = RealtimeSSSEngine(
            sample_rate=sample_rate,
            sweep_duration=sweep_duration,
            start_freq=start_freq,
            end_freq=end_freq,
            output_amplitude=output_amplitude,
            max_harmonic=max_harmonic,
            analysis_cycles=analysis_cycles,
            num_meas_points=num_meas_points,
        )
        run_engine_sig.prepare_sweep()
        run_engine_sig.set_latency(latency_samples)

        if cli_args.harmonic_jitter_comp and input_mode == "XFER":
            run_engine_ref = RealtimeSSSEngine(
                sample_rate=sample_rate,
                sweep_duration=sweep_duration,
                start_freq=start_freq,
                end_freq=end_freq,
                output_amplitude=output_amplitude,
                max_harmonic=max_harmonic,
                analysis_cycles=analysis_cycles,
                num_meas_points=num_meas_points,
            )
            run_engine_ref.prepare_sweep()
            run_engine_ref.set_latency(latency_samples)
        else:
            run_engine_ref = None

        # Get target sweep signal
        out_sig = run_engine_sig.out_sig
        if out_sig is None:
            print("[-] Error: Failed to generate output sweep signal.")
            sys.exit(1)

        # Pad the output signal to allow latency and trailing recording window
        margin_samples = int(0.5 * sample_rate)
        total_playback_samples = len(out_sig) + int(latency_samples) + margin_samples
        out_data = np.zeros((total_playback_samples, 2), dtype=np.float32)
        out_data[:len(out_sig), 0] = out_sig
        out_data[:len(out_sig), 1] = out_sig

        # Playback and record
        rec_data = run_play_rec(engine, out_data, input_channels=2)

        if cli_args.virtual:
            meas_ch = rec_data[:, sig_ch]
            ref_sig = rec_data[:, ref_ch]
            N = len(meas_ch)

            # Jitter: Random fractional delay in range [-0.2, 0.2] samples
            # This simulates microscopic timing drift/fluctuations (common to both channels)
            if cli_args.no_jitter:
                jitter = 0.0
            else:
                jitter = np.random.uniform(-0.2, 0.2)

            if jitter != 0.0:
                freqs = np.fft.rfftfreq(N)
                phase_shift = np.exp(-2j * np.pi * freqs * jitter)
                meas_fft = np.fft.rfft(meas_ch)
                meas_delayed = np.fft.irfft(meas_fft * phase_shift, n=N)
                ref_fft = np.fft.rfft(ref_sig)
                ref_delayed = np.fft.irfft(ref_fft * phase_shift, n=N)
            else:
                meas_delayed = meas_ch.copy()
                ref_delayed = ref_sig.copy()

            # Nonlinear distortion (Hammerstein style)
            # y(t) = x(t) - 0.08*x(t)^2 + 0.12*x(t)^3 - 0.04*x(t)^4 + 0.06*x(t)^5
            distorted = (
                meas_delayed
                - 0.08 * (meas_delayed ** 2)
                + 0.12 * (meas_delayed ** 3)
                - 0.04 * (meas_delayed ** 4)
                + 0.06 * (meas_delayed ** 5)
            )

            # Noise addition (-85 dBFS for measurement, -100 dBFS for reference)
            if cli_args.no_noise:
                noise_meas = np.zeros(N)
                noise_ref = np.zeros(N)
            else:
                noise_meas = np.random.normal(scale=5e-5, size=N)
                noise_ref = np.random.normal(scale=1e-5, size=N)

            rec_data[:, sig_ch] = distorted + noise_meas
            rec_data[:, ref_ch] = ref_delayed + noise_ref

        # Process the recording block-by-block
        for block_idx in range(max_blocks):
            start_samp = block_idx * frames_per_block

            # Slice block
            sig_block = np.zeros((frames_per_block, 1))
            ref_block = None

            if start_samp < len(rec_data):
                chunk = min(frames_per_block, len(rec_data) - start_samp)
                sig_block[:chunk, 0] = rec_data[start_samp : start_samp + chunk, sig_ch]

                if input_mode == "XFER":
                    ref_block = np.zeros((frames_per_block, 1))
                    ref_block[:chunk, 0] = rec_data[start_samp : start_samp + chunk, ref_ch]

            # Demodulate
            if run_engine_ref is not None:
                # Process signal and reference separately to apply advanced harmonic-order jitter compensation
                # Pass ref_in_block=None to prevent the engine from applying standard 1st-order compensation internally
                f_mid, sig_res = run_engine_sig.process_input_block(sig_block, block_idx, ref_in_block=None)
                _, ref_res = run_engine_ref.process_input_block(ref_block, block_idx, ref_in_block=None)

                # Apply harmonic-order compensation
                # H_k = S_k * conj(R_1 / |R_1|)^k / |R_1|
                ref_h1 = ref_res[0] if ref_res else 0.0j
                ref_mag = np.abs(ref_h1)
                if ref_mag > 1e-24:
                    ref_u = ref_h1 / ref_mag
                    results = []
                    for h_idx in range(max_harmonic):
                        k = h_idx + 1  # harmonic order
                        ref_u_k = ref_u ** k
                        corrected = sig_res[h_idx] * np.conj(ref_u_k) / ref_mag
                        results.append(corrected)
                else:
                    results = [0.0j] * max_harmonic
            else:
                f_mid, results = run_engine_sig.process_input_block(sig_block, block_idx, ref_in_block=ref_block)

            # Save results
            raw_runs_results[run_idx, block_idx, :] = results[:max_harmonic]
            if run_idx == 0:
                block_freqs[block_idx] = f_mid

        print(f"[+] Run {run_idx + 1} analysis complete.")

    engine.stop_stream()

    # 4. Statistical Analysis
    print("\n[*] Processing statistical analysis...")
    # Filters out invalid frequency regions (where f_mid is outside sweep start/end range)
    valid_mask = (block_freqs >= min(start_freq, end_freq)) & (block_freqs <= max(start_freq, end_freq))
    valid_indices = np.where(valid_mask)[0]

    if len(valid_indices) == 0:
        print("[-] Error: No valid frequency blocks recorded.")
        sys.exit(1)

    freqs_valid = block_freqs[valid_indices]
    n_valid = len(valid_indices)

    # Containers for stats
    # Shape: (valid_blocks, max_harmonic)
    gain_mean = np.zeros((n_valid, max_harmonic))
    gain_std = np.zeros((n_valid, max_harmonic))
    phase_mean = np.zeros((n_valid, max_harmonic))
    phase_std = np.zeros((n_valid, max_harmonic))

    for h_idx in range(max_harmonic):
        for idx, block_idx in enumerate(valid_indices):
            # Extract complex values across runs for this block and harmonic
            complex_vals = raw_runs_results[:, block_idx, h_idx]

            # Calculate individual gains (dB) and phases (deg)
            gains = 20 * np.log10(np.abs(complex_vals) + 1e-15)
            phases = np.degrees(np.angle(complex_vals))

            # Phase Alignment to prevent wrap-around artifact
            phases_aligned = align_phases(phases)

            gain_mean[idx, h_idx] = np.mean(gains)
            gain_std[idx, h_idx] = np.std(gains)
            phase_mean[idx, h_idx] = (np.mean(phases_aligned) + 180) % 360 - 180
            phase_std[idx, h_idx] = np.std(phases_aligned)

    # Compute overall statistics summary
    print("\n" + "=" * 60)
    print(f" SSS MEASUREMENT REPEATABILITY SUMMARY ({cli_args.runs} Runs)")
    print(f" Sweep Duration: {sweep_duration}s | Cycles: {analysis_cycles}")
    print("=" * 60)

    stats_report = {}
    for h in range(max_harmonic):
        h_name = "Fundamental" if h == 0 else f"{h+1}th Harmonic"

        max_g_std = np.max(gain_std[:, h])
        mean_g_std = np.mean(gain_std[:, h])
        max_p_std = np.max(phase_std[:, h])
        mean_p_std = np.mean(phase_std[:, h])

        stats_report[h_name] = {
            "max_gain_std_db": float(max_g_std),
            "mean_gain_std_db": float(mean_g_std),
            "max_phase_std_deg": float(max_p_std),
            "mean_phase_std_deg": float(mean_p_std),
        }

        print(f"\n--- {h_name} ---")
        print(f"  Gain Std Dev  : Mean = {mean_g_std:.4f} dB,  Max = {max_g_std:.4f} dB")
        print(f"  Phase Std Dev : Mean = {mean_p_std:.4f} deg, Max = {max_p_std:.4f} deg")

    # Phase accuracy verification (only relevant in virtual mode since we know the ground truth)
    phase_accuracy_report = {}
    if cli_args.virtual:
        # Theoretical phases (based on sine-excitation mathematical derivation)
        # 1st (Fundamental): 0 deg
        # 2nd Harmonic: 90 deg
        # 3rd Harmonic: 180 deg
        # 4th Harmonic: -90 deg
        # 5th Harmonic: 0 deg
        theoretical_phases = [0.0, 90.0, 180.0, -90.0, 0.0]
        phase_errors = np.zeros((n_valid, max_harmonic))

        print("\n" + "=" * 60)
        print(" SSS PHASE MEASUREMENT ACCURACY (Compared to Ground Truth)")
        print("=" * 60)

        # Mask for inner frequency range (100 Hz to 10 kHz) to avoid Tukey window edge transients
        inner_mask = (freqs_valid >= 100.0) & (freqs_valid <= 10000.0)

        for h in range(max_harmonic):
            h_name = "Fundamental" if h == 0 else f"{h+1}th Harmonic"
            target = theoretical_phases[h]

            # Calculate wrapped phase error in range [-180, 180]
            diff = phase_mean[:, h] - target
            diff = (diff + 180) % 360 - 180
            phase_errors[:, h] = diff

            abs_diff = np.abs(diff)
            mean_error = np.mean(abs_diff)
            max_error = np.max(abs_diff)

            # Inner range stats
            if np.any(inner_mask):
                abs_diff_inner = abs_diff[inner_mask]
                mean_error_inner = np.mean(abs_diff_inner)
                max_error_inner = np.max(abs_diff_inner)
            else:
                mean_error_inner = mean_error
                max_error_inner = max_error

            phase_accuracy_report[h_name] = {
                "theoretical_phase_deg": target,
                "mean_abs_error_deg": float(mean_error),
                "max_abs_error_deg": float(max_error),
                "inner_mean_abs_error_deg": float(mean_error_inner),
                "inner_max_abs_error_deg": float(max_error_inner),
            }

            print(f"\n--- {h_name} (Expected: {target:.1f} deg) ---")
            print(f"  Full Sweep (20Hz-20kHz): Mean Abs = {mean_error:.6f} deg, Max Abs = {max_error:.6f} deg")
            print(f"  Inner Band (100Hz-10kHz): Mean Abs = {mean_error_inner:.6f} deg, Max Abs = {max_error_inner:.6f} deg")

    # 5. Plotting results
    print("\n[*] Plotting repeatability graphs...")
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8), sharex=True)

    colors = ["#1f77b4", "#2ca02c", "#ff7f0e", "#9467bd", "#d62728"]
    labels = ["Fundamental", "2nd Harmonic", "3rd Harmonic", "4th Harmonic", "5th Harmonic"]

    for h in range(max_harmonic):
        ax1.semilogx(freqs_valid, gain_std[:, h], color=colors[h], label=labels[h])
        ax2.semilogx(freqs_valid, phase_std[:, h], color=colors[h], label=labels[h])

    ax1.set_title(f"SSS Repeatability: Standard Deviation over {cli_args.runs} Runs (Cycles={analysis_cycles})")
    ax1.set_ylabel("Gain Standard Deviation (dB)")
    ax1.grid(True, which="both", ls="-", alpha=0.5)
    ax1.legend()

    ax2.set_xlabel("Frequency (Hz)")
    ax2.set_ylabel("Phase Standard Deviation (degrees)")
    ax2.grid(True, which="both", ls="-", alpha=0.5)

    plt.tight_layout()
    plot_path = os.path.join(project_root, "scripts", "sss_repeatability_plot.png")
    plt.savefig(plot_path, dpi=150)
    plt.close()
    print(f"[+] Saved repeatability plot to {plot_path}")

    # Generate phase accuracy plot if in virtual mode
    if cli_args.virtual:
        print("[*] Plotting phase accuracy graphs...")
        fig, ax = plt.subplots(figsize=(10, 5))
        for h in range(max_harmonic):
            ax.semilogx(freqs_valid, phase_errors[:, h], color=colors[h], label=labels[h])
        ax.set_title(f"SSS Demodulator Phase Error vs Ground Truth (Virtual, Noise={not cli_args.no_noise}, Jitter={not cli_args.no_jitter})")
        ax.set_xlabel("Frequency (Hz)")
        ax.set_ylabel("Phase Error (degrees)")
        ax.grid(True, which="both", ls="-", alpha=0.5)
        ax.legend()
        plt.tight_layout()
        acc_plot_path = os.path.join(project_root, "scripts", "sss_phase_accuracy_plot.png")
        plt.savefig(acc_plot_path, dpi=150)
        plt.close()
        print(f"[+] Saved phase accuracy plot to {acc_plot_path}")

    # 6. Save JSON Data
    report_data = {
        "metadata": {
            "runs": cli_args.runs,
            "cycles": cli_args.cycles,
            "duration": cli_args.duration,
            "amplitude_db": cli_args.amplitude,
            "mode": cli_args.mode,
            "sample_rate": sample_rate,
            "latency_samples": latency_samples,
            "virtual": cli_args.virtual,
            "no_noise": cli_args.no_noise if cli_args.virtual else None,
            "no_jitter": cli_args.no_jitter if cli_args.virtual else None,
        },
        "summary": stats_report,
        "frequencies": freqs_valid.tolist(),
        "harmonics": {},
    }

    if cli_args.virtual:
        report_data["phase_accuracy"] = phase_accuracy_report

    for h in range(max_harmonic):
        h_name = f"h{h+1}"
        report_data["harmonics"][h_name] = {
            "gain_mean": gain_mean[:, h].tolist(),
            "gain_std": gain_std[:, h].tolist(),
            "phase_mean": phase_mean[:, h].tolist(),
            "phase_std": phase_std[:, h].tolist(),
        }
        if cli_args.virtual:
            report_data["harmonics"][h_name]["phase_error"] = phase_errors[:, h].tolist()

    json_path = os.path.join(project_root, "scripts", "sss_repeatability_results.json")
    with open(json_path, "w") as f:
        json.dump(report_data, f, indent=4)
    print(f"[+] Saved raw metrics to {json_path}")


if __name__ == "__main__":
    main()
