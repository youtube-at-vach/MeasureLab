#!/usr/bin/env python3
# ruff: noqa: E402
import os
import sys
import json
import argparse
import threading
import logging
import numpy as np
from scipy.signal import hilbert

# Add project root to sys.path to resolve src imports
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_root)

from src.core.config_manager import ConfigManager
from src.core.audio_engine import AudioEngine
from src.core.hammerstein_model import save_hammerstein_model
from src.gui.widgets.feedforward_compensator import LICFFEngine
from src.core.nonlinear_analyzer_core import (
    generate_sss_and_inverse,
    process_amplitude_responses,
    deconvolve_signal,
)

# Set up logging to stdout
logging_format = "%(asctime)s - %(levelname)s - %(message)s"
logging.basicConfig(level=logging.INFO, format=logging_format)
logger = logging.getLogger("verify_distortion")


class SimplePlayRecSession:
    """PyQt-free synchronous play/record session via AudioEngine."""
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
        # Check if master stream actually opened
        if self.audio_engine.stream is None and not getattr(self.audio_engine, "offline_mode", False):
            self.error = "Audio stream failed to start. Check your device configuration."
            self.is_complete = True
            self.completion_event.set()

    def stop(self):
        if self.callback_id is not None:
            self.audio_engine.unregister_callback(self.callback_id)
            self.callback_id = None

    def wait(self, timeout=None):
        completed = self.completion_event.wait(timeout)
        if not completed:
            self.error = "Audio playback timed out. Device might have stopped responding."
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

                # Playback mapping
                ch_out = min(outdata.shape[1], self.output_data.shape[1])
                outdata[:chunk, :ch_out] = self.output_data[self.current_frame : self.current_frame + chunk, :ch_out]
                if ch_out < outdata.shape[1]:
                    outdata[:chunk, ch_out:] = 0
                if chunk < frames:
                    outdata[chunk:, :] = 0

                # Recording mapping
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
    """Synchronously plays output_data and records input_channels."""
    # Temporarily stop active stream to ensure exclusive hardware lock
    if audio_engine.stream and audio_engine.stream.active:
        audio_engine.stop_stream()

    session = SimplePlayRecSession(audio_engine, output_data, input_channels)
    session.start()
    expected_duration = len(output_data) / audio_engine.sample_rate
    session.wait(timeout=expected_duration + 3.0)
    session.stop()
    return session.input_data


def analyze_harmonics_lockin(sig_full, ref_full, fs, max_harmonic=5, min_analysis_samples=2048):
    """
    Precision lock-in matrix projection algorithm adapted from LockInHarmonicAnalyzer.
    Estimates fundamental frequency, extracts a coherent cycle segment,
    projects onto cosine/sine basis functions, and computes amplitude & phase.
    """
    ref_rms = np.sqrt(np.mean(ref_full**2))
    if ref_rms < 0.0001:
        raise ValueError("Reference signal level is too low. Check input connection or levels.")

    # 1. Instanteous phase & frequency estimation using Hilbert Transform
    max_samples = 8192
    ref_est = ref_full[-max_samples:] if len(ref_full) > max_samples else ref_full
    n_samples = len(ref_est)
    if n_samples < 100:
        raise ValueError("Signal too short for lock-in analysis.")

    t_est = np.arange(n_samples) / fs
    ref_analytic = hilbert(ref_est)
    trim = int(n_samples * 0.05)
    if trim > 0 and (n_samples - 2 * trim) >= 100:
        ref_analytic = ref_analytic[trim:-trim]
        t_est = t_est[trim:-trim]

    ref_phase = np.unwrap(np.angle(ref_analytic))
    omega_pre, _ = np.polyfit(t_est, ref_phase, 1)

    # 2. Extract a coherent segment containing integer cycles using zero-crossings
    rising_idx = np.flatnonzero((ref_full[:-1] <= 0.0) & (ref_full[1:] > 0.0))
    num_cycles = len(rising_idx) - 1
    if num_cycles < 1:
        raise ValueError("No complete cycles found in reference signal.")

    def get_crossing(idx):
        y0 = ref_full[idx]
        y1 = ref_full[idx + 1]
        dy = y1 - y0
        frac = 0.0 if abs(dy) < 1e-18 else (-y0 / dy)
        return idx + np.clip(frac, 0.0, 1.0)

    start_cross = get_crossing(rising_idx[0])
    end_cross = get_crossing(rising_idx[-1])

    start_idx = max(0, int(np.floor(start_cross)))
    end_idx = min(len(ref_full), int(np.ceil(end_cross)) + 1)
    if (end_idx - start_idx) < min_analysis_samples:
        raise ValueError(f"Coherent segment ({end_idx - start_idx}) too short. Minimum is {min_analysis_samples}.")

    sig = sig_full[start_idx:end_idx]
    ref = ref_full[start_idx:end_idx]

    duration_sec = (end_cross - start_cross) / fs
    omega = 2.0 * np.pi * (num_cycles / duration_sec)

    # 3. Fit phase anchor to lock-in references
    N = len(sig)
    t = np.arange(N) / fs
    ref_i = (2.0 / N) * np.dot(ref, np.cos(omega * t))
    ref_q = (2.0 / N) * np.dot(ref, np.sin(omega * t))
    theta_0 = np.arctan2(ref_i, ref_q)

    f0 = omega / (2 * np.pi)

    # 4. Construct Basis Matrix
    phase_ideal = omega * t + theta_0
    num_bases = 1 + max_harmonic * 2
    B = np.zeros((N, num_bases))
    B[:, 0] = 1.0

    for n in range(1, max_harmonic + 1):
        idx = 1 + (n - 1) * 2
        B[:, idx] = np.cos(n * phase_ideal)
        B[:, idx + 1] = np.sin(n * phase_ideal)

    # Solve projection
    gram = np.dot(B.T, B)
    rhs = np.dot(B.T, sig)
    try:
        coeff = np.linalg.solve(gram, rhs)
    except np.linalg.LinAlgError:
        coeff = np.linalg.lstsq(B, sig, rcond=None)[0]
    X = coeff[1:]

    # 5. Extract harmonics
    harmonics_amp = np.zeros(max_harmonic)
    harmonics_phase_deg = np.zeros(max_harmonic)
    sum_sq_harmonics = 0.0
    reconstructed_sig = np.full(N, coeff[0])

    for n in range(1, max_harmonic + 1):
        idx = (n - 1) * 2
        I_comp = X[idx]
        Q_comp = X[idx + 1]
        amp = np.sqrt(I_comp**2 + Q_comp**2)
        phase = np.arctan2(I_comp, Q_comp)
        phase_deg = np.degrees(phase)
        phase_deg = (phase_deg + 180) % 360 - 180

        harmonics_amp[n - 1] = amp
        harmonics_phase_deg[n - 1] = phase_deg

        if n > 1:
            sum_sq_harmonics += (amp / np.sqrt(2)) ** 2

        b_idx = 1 + idx
        reconstructed_sig += I_comp * B[:, b_idx] + Q_comp * B[:, b_idx + 1]

    # Calculate THD/THD+N
    fund_rms_sq = (harmonics_amp[0] / np.sqrt(2)) ** 2
    thd_value = 0.0
    thd_db = -300.0
    thdn_value = 0.0
    thdn_db = -300.0

    if fund_rms_sq > 1e-15:
        thd_sq = sum_sq_harmonics / fund_rms_sq
        thd_value = np.sqrt(thd_sq) * 100
        thd_db = 10 * np.log10(thd_sq + 1e-30)

        residual = sig - reconstructed_sig
        residual_rms = np.sqrt(np.mean(residual**2))
        noise_rms_sq = residual_rms**2
        num_sq = sum_sq_harmonics + noise_rms_sq
        thdn_sq = num_sq / fund_rms_sq
        thdn_value = np.sqrt(thdn_sq) * 100
        thdn_db = 10 * np.log10(thdn_sq + 1e-30)

    return {
        "f0": f0,
        "fund_amp_dbfs": 20 * np.log10(harmonics_amp[0] * np.sqrt(2) + 1e-12),
        "harmonics_amp": harmonics_amp,
        "harmonics_phase_deg": harmonics_phase_deg,
        "thd_pct": thd_value,
        "thd_db": thd_db,
        "thdn_pct": thdn_value,
        "thdn_db": thdn_db,
    }


def main():
    parser = argparse.ArgumentParser(description="Distortion Compensation (LICFF) Verification Script")
    parser.add_argument("--freq", type=float, default=1000.0, help="Test frequency in Hz (default: 1000.0)")
    parser.add_argument("--amp", type=float, default=-6.0, help="Signal amplitude in dBFS (default: -6.0)")
    parser.add_argument("--duration", type=float, default=2.0, help="Tone play/record duration in seconds (default: 2.0)")
    parser.add_argument("--sweep-dur", type=float, default=5.0, help="Sweep duration in seconds (default: 5.0)")
    parser.add_argument("--meas-ch", type=int, default=0, help="Measurement channel index (0: Left, 1: Right) (default: 0)")
    parser.add_argument("--ref-ch", type=int, default=1, help="Reference channel index (0: Left, 1: Right) (default: 1)")
    parser.add_argument("--input-mode", type=str, default="XFER_REV", choices=["L", "R", "XFER", "XFER_REV"], 
                        help="Deconvolution input mode (default: XFER_REV)")
    parser.add_argument("--out-ch", type=str, default="STEREO", choices=["L", "R", "STEREO"],
                        help="Output channel mapping (default: STEREO)")
    parser.add_argument("--iters", type=int, default=3, help="Number of compensation iterations (default: 3)")
    parser.add_argument("--clip", type=float, default=1.5, help="Compensation clipping limit (default: 1.5)")
    parser.add_argument("--fmin", type=float, default=60.0, help="Active band fmin in Hz (default: 60.0)")
    parser.add_argument("--fmax", type=float, default=17000.0, help="Active band fmax in Hz (default: 17000.0)")
    parser.add_argument("--num-amps", type=int, default=5, help="Number of scan amplitudes (default: 5)")
    parser.add_argument("--tsa", type=int, default=2, help="TSA averages (default: 2)")
    parser.add_argument("--virtual", action="store_true", help="Run in offline virtual mode (no real device)")
    args = parser.parse_args()

    # Load configuration
    logger.info("Loading system audio configuration...")
    config_manager = ConfigManager()
    audio_config = config_manager.get_audio_config()

    # Create & configure AudioEngine
    audio_engine = AudioEngine()
    
    # Overwrite configuration for reliable macOS hardware streaming (float32 fallback and disable strict CoreAudio conversion checks)
    logger.info("Enforcing float32 precision and disabling CoreAudio conversion constraints for hardware stability...")
    audio_engine.set_audio_engine_64bit(False)
    audio_engine.set_coreaudio_fail_if_conversion_required(False)

    if args.virtual or audio_config.get("offline_mode", False):
        logger.info("Setting AudioEngine to OFFLINE (VIRTUAL) mode.")
        audio_engine.set_offline_mode(True)
    else:
        # Resolve exact physical ZOOM UAC-232 device index for PortAudio streaming stability
        import sounddevice as sd
        devices = sd.query_devices()
        uac_idx = None
        for idx, d in enumerate(devices):
            if "uac-232" in d["name"].lower() and d["max_input_channels"] >= 2 and d["max_output_channels"] >= 2:
                uac_idx = idx
                break
        
        if uac_idx is not None:
            logger.info(f"Setting AudioEngine devices directly to ZOOM UAC-232 index: {uac_idx}")
            audio_engine.set_devices(uac_idx, uac_idx)
        else:
            in_device = audio_config.get("input_device")
            out_device = audio_config.get("output_device")
            logger.info(f"Configured devices (fallback): Input='{in_device}', Output='{out_device}'")
            audio_engine.set_devices(in_device, out_device)
        audio_engine.set_offline_mode(False)

    sample_rate = audio_config.get("sample_rate", 48000)
    audio_engine.set_sample_rate(sample_rate)
    logger.info("Enforcing block size to 1024 for macOS hardware streaming stability...")
    audio_engine.set_block_size(1024)
    audio_engine.set_channel_mode(
        audio_config.get("input_channels", "stereo"),
        audio_config.get("output_channels", "stereo")
    )

    # Print device info
    import sounddevice as sd
    logger.info("Available audio devices list:")
    for idx, d in enumerate(sd.query_devices()):
        logger.info(f"  [{idx}] {d['name']} (In: {d['max_input_channels']}, Out: {d['max_output_channels']})")

    logger.info("Selected parameters:")
    logger.info(f"  Sample Rate: {sample_rate} Hz")
    logger.info(f"  Block Size: {audio_engine.block_size}")
    logger.info(f"  Input Mode: {args.input_mode} (Meas Channel: {args.meas_ch}, Ref Channel: {args.ref_ch})")
    logger.info(f"  Output Mode: {args.out_ch}")

    # Physical Loopback Check Prompt
    if not audio_engine.offline_mode:
        print("\n" + "="*70)
        print("IMPORTANT PHYSICAL SETUP CHECK:")
        print("Please ensure that a loopback cable is connected between:")
        print(f"  Output (mapping: {args.out_ch}) -> Input (Channel {args.meas_ch} AND Channel {args.ref_ch})")
        print("  - Typically: Left Output -> Left Input (Meas, Channel 0) and Right Input (Ref, Channel 1)")
        print("="*70)
        input("Press ENTER when the hardware is ready to start measurement...")

    # =========================================================================
    # STEP 1: SSS sweep measurement and Hammerstein kernel extraction
    # =========================================================================
    logger.info("\n=== STEP 1: Swept-Sine / Parallel Hammerstein Measurement ===")

    # Define amplitude scanning range (linear)
    max_amp_lin = 10 ** (args.amp / 20.0)
    amplitudes = np.linspace(0.2, 1.0, args.num_amps) * max_amp_lin
    logger.info(f"Scan amplitudes: {amplitudes} (peak linear values)")

    padding_samples = int(0.5 * sample_rate)
    sss, inv_filter = generate_sss_and_inverse(sample_rate, args.sweep_dur, args.fmin, args.fmax)

    responses_meas = []
    responses_ref = []

    for idx, amp in enumerate(amplitudes):
        logger.info(f"Scanning amplitude step {idx+1}/{args.num_amps} (Amp = {amp:.4f} linear)...")
        out_signal = np.concatenate([amp * sss, np.zeros(padding_samples)])

        # Construct 2-channel output signal
        out_data = np.zeros((len(out_signal), 2), dtype=np.float32)
        if args.out_ch in {"L", "STEREO"}:
            out_data[:, 0] = out_signal
        if args.out_ch in {"R", "STEREO"}:
            out_data[:, 1] = out_signal

        accum_data = None
        ref_peak_sub = None

        for avg in range(args.tsa):
            logger.info(f"  Sweep average {avg+1}/{args.tsa}...")

            # play & record
            rec_data = run_play_rec(audio_engine, out_data, input_channels=2)

            if audio_engine.offline_mode:
                # Simulate a nonlinear loopback system
                simulated_meas = amp * sss
                # Nonlinear system output with typical harmonics
                # y(t) = x(t) - 0.08*x(t)^2 + 0.12*x(t)^3 - 0.04*x(t)^4 + 0.06*x(t)^5
                simulated_meas = (
                    simulated_meas
                    - 0.08 * (simulated_meas**2)
                    + 0.12 * (simulated_meas**3)
                    - 0.04 * (simulated_meas**4)
                    + 0.06 * (simulated_meas**5)
                )
                simulated_meas = np.concatenate([simulated_meas, np.zeros(padding_samples)])
                clean_ref = np.concatenate([amp * sss, np.zeros(padding_samples)])

                # Mock channels
                rec_data = np.zeros((len(simulated_meas), 2), dtype=np.float32)
                rec_data[:, args.meas_ch] = simulated_meas
                rec_data[:, args.ref_ch] = clean_ref

            # Find peak to align TSA sweeps
            align_ch = args.ref_ch if args.input_mode in {"XFER", "XFER_REV"} else args.meas_ch
            align_sig = rec_data[:, align_ch]

            from scipy.signal import fftconvolve
            from src.core.nonlinear_analyzer_core import find_subsample_peak, apply_fractional_delay
            temp_ir = fftconvolve(align_sig, inv_filter, mode="full")
            t_peak = find_subsample_peak(temp_ir)

            if accum_data is None:
                accum_data = rec_data.copy()
                ref_peak_sub = t_peak
            else:
                delay = t_peak - ref_peak_sub
                shifted = np.zeros_like(rec_data)
                for ch in range(rec_data.shape[1]):
                    shifted[:, ch] = apply_fractional_delay(rec_data[:, ch], -delay)
                accum_data += shifted

        averaged_data = accum_data / args.tsa

        # Deconvolution
        sig_ref = averaged_data[:, args.ref_ch]
        sig_meas = averaged_data[:, args.meas_ch]

        ir_ref_raw = deconvolve_signal(sig_ref, sss)
        ir_meas_raw = deconvolve_signal(sig_meas, sss)

        responses_ref.append(ir_ref_raw)
        responses_meas.append(ir_meas_raw)

    # Process and separate Hammerstein kernels
    logger.info("Extracting Hammerstein kernels...")
    (
        valid_freqs,
        magnitudes_db_dict,
        phases_deg_dict,
        time_ms,
        separated_kernels_data,
    ) = process_amplitude_responses(
        responses_meas,
        responses_ref,
        sample_rate,
        args.fmin,
        args.fmax,
        args.input_mode,
        latency_sec=0.0, # Handled by relative XFER
        sweep_duration=args.sweep_dur,
        P=5,
        amplitudes=amplitudes,
    )

    # Save to a temporary JSON file
    temp_json_path = os.path.join(project_root, "temp_measured_hammerstein.json")
    logger.info(f"Saving measured Hammerstein model to {temp_json_path}...")

    ref_max = np.max(np.abs(separated_kernels_data[0])) if len(separated_kernels_data) > 0 else 1.0
    model_data = {
        "metadata": {
            "module": "Verify Distortion Script",
            "sample_rate": sample_rate,
            "num_amplitudes": args.num_amps,
            "sweep_duration": args.sweep_dur,
            "start_freq": args.fmin,
            "end_freq": args.fmax,
            "input_mode": args.input_mode,
            "latency_sec": 0.0,
            "ref_max": float(ref_max),
            "P": len(separated_kernels_data),
        },
        "time_domain": {
            "time_ms": time_ms,
            "kernels": {
                f"h{p+1}": separated_kernels_data[p] for p in range(len(separated_kernels_data))
            },
        },
        "frequency_domain": {
            "freqs": valid_freqs,
            "magnitudes_db": {
                k: v for k, v in magnitudes_db_dict.items() if k.startswith("h")
            },
            "phases_deg": {
                k: v for k, v in phases_deg_dict.items() if k.startswith("h") or k == "ref_phase"
            },
        },
    }
    save_hammerstein_model(temp_json_path, model_data)

    # =========================================================================
    # STEP 2: Generate Pure Tone & Perform Feedforward Compensation
    # =========================================================================
    logger.info("\n=== STEP 2: Generate Pure Tone & Feedforward Compensation ===")

    # 1. Pure Tone Generation
    N_tone = int(sample_rate * args.duration)
    t = np.arange(N_tone) / sample_rate

    # Pure tone input u(t) at configured amplitude
    u_in = max_amp_lin * np.sin(2 * np.pi * args.freq * t)

    # 2. Setup LICFF Engine
    with open(temp_json_path, "r") as f:
        loaded_model_json = json.load(f)

    logger.info("Initializing LICFFEngine for compensation...")
    engine = LICFFEngine(loaded_model_json, f_min=args.fmin, f_max=args.fmax)

    # Verify linear scaling factor and scaled kernels
    logger.info(f"LICFF Linear scaling G_scale: {engine.G_scale:.6f}")
    logger.info(f"LICFF Scaled kernel sums: h1_sc={np.sum(engine.q1_sc):.4f}, h2_sc={np.sum(engine.q2_sc):.4f}, h3_sc={np.sum(engine.q3_sc):.4f}")

    # 3. Create compensated signal
    logger.info(f"Applying compensation (Iterative={args.iters > 1}, Iters={args.iters})...")
    u_comp = engine.compensate(u_in, iterative=(args.iters > 1), iters=args.iters, clip_limit=args.clip)

    # Check phase and amplitude changes due to linear inverse filter
    u_in_fft = np.fft.rfft(u_in)
    u_comp_fft = np.fft.rfft(u_comp)
    freqs_tone = np.fft.rfftfreq(N_tone, d=1.0/sample_rate)

    # Find bin for fundamental frequency
    bin_idx = np.argmin(np.abs(freqs_tone - args.freq))

    phi_in = np.angle(u_in_fft[bin_idx])
    phi_comp = np.angle(u_comp_fft[bin_idx])
    phi_diff_deg = np.degrees(np.unwrap([phi_in, phi_comp])[1] - phi_in)

    amp_in_db = 20 * np.log10(np.abs(u_in_fft[bin_idx]) / (N_tone / 2.0) + 1e-12)
    amp_comp_db = 20 * np.log10(np.abs(u_comp_fft[bin_idx]) / (N_tone / 2.0) + 1e-12)

    logger.info(f"Digital Signal Comparison (At {args.freq} Hz):")
    logger.info(f"  Input Amplitude:       {amp_in_db:.2f} dBFS")
    logger.info(f"  Compensated Amplitude: {amp_comp_db:.2f} dBFS (Change: {amp_comp_db - amp_in_db:+.2f} dB)")
    logger.info(f"  Phase Shift Applied:   {phi_diff_deg:+.2f} degrees")

    # =========================================================================
    # STEP 3: Real Playback and Recording of Uncompensated vs Compensated
    # =========================================================================
    logger.info("\n=== STEP 3: Real Playback & Recording ===")

    # Pattern A: Uncompensated
    logger.info("Pattern A: Playing & Recording UNCOMPENSATED pure tone...")
    out_uncomp = np.zeros((N_tone, 2), dtype=np.float32)
    if args.out_ch in {"L", "STEREO"}:
        out_uncomp[:, 0] = u_in
    if args.out_ch in {"R", "STEREO"}:
        out_uncomp[:, 1] = u_in

    rec_uncomp = run_play_rec(audio_engine, out_uncomp, input_channels=2)

    # Pattern B: Compensated
    logger.info("Pattern B: Playing & Recording COMPENSATED pure tone...")
    out_comp = np.zeros((N_tone, 2), dtype=np.float32)
    if args.out_ch in {"L", "STEREO"}:
        out_comp[:, 0] = u_comp
    if args.out_ch in {"R", "STEREO"}:
        out_comp[:, 1] = u_comp

    rec_comp = run_play_rec(audio_engine, out_comp, input_channels=2)

    if audio_engine.offline_mode:
        # Mock nonlinear recording output
        # Pattern A (Uncompensated): system adds normal harmonics
        rec_uncomp = np.zeros((N_tone, 2), dtype=np.float32)
        # linear + nonlinear simulation
        y_uncomp = u_in - 0.08*(u_in**2) + 0.12*(u_in**3) - 0.04*(u_in**4) + 0.06*(u_in**5)
        # Add tiny delay and gain scale
        y_uncomp_delay = np.roll(y_uncomp, 10) * 0.95
        rec_uncomp[:, args.meas_ch] = y_uncomp_delay
        rec_uncomp[:, args.ref_ch] = np.roll(u_in, 10) # Clean reference

        # Pattern B (Compensated): loopback system processes u_comp
        # Y_comp = f(u_comp) should result in harmonics being canceled out, leaving mostly pure tone
        rec_comp = np.zeros((N_tone, 2), dtype=np.float32)
        y_comp_raw = engine.forward_model(u_comp) # Ideally cancels harmonics in virtual simulation!
        y_comp_delay = np.roll(y_comp_raw, 10) * 0.95
        rec_comp[:, args.meas_ch] = y_comp_delay
        rec_comp[:, args.ref_ch] = np.roll(u_in, 10) # Clean reference

    # =========================================================================
    # STEP 4: Lock-In Analysis of Rec Signals
    # =========================================================================
    logger.info("\n=== STEP 4: Lock-In Harmonic Analysis ===")

    logger.info("Analyzing Pattern A (Uncompensated)...")
    analysis_uncomp = analyze_harmonics_lockin(
        rec_uncomp[:, args.meas_ch], 
        rec_uncomp[:, args.ref_ch], 
        sample_rate, 
        max_harmonic=5
    )

    logger.info("Analyzing Pattern B (Compensated)...")
    analysis_comp = analyze_harmonics_lockin(
        rec_comp[:, args.meas_ch], 
        rec_comp[:, args.ref_ch], 
        sample_rate, 
        max_harmonic=5
    )

    # =========================================================================
    # STEP 5: Comparison and Diagnostic Output
    # =========================================================================
    print("\n" + "="*80)
    print("                      DISTORTION COMPENSATION COMPARISON REPORT")
    print("="*80)
    print(f"Test Frequency: {args.freq:.1f} Hz  |  Excitation Amplitude: {args.amp:.1f} dBFS")
    print(f"Sample Rate:    {sample_rate} Hz  |  Compensation Iterations: {args.iters}")
    print("-"*80)

    print(f"{'Metric':<25} | {'Uncompensated':<18} | {'Compensated':<18} | {'Suppression (dB)':<18}")
    print("-"*80)

    print(f"{'Measured Frequency':<25} | {analysis_uncomp['f0']:<15.2f} Hz | {analysis_comp['f0']:<15.2f} Hz | {'-':<18}")
    print(f"{'Fundamental Level (dBFS)':<25} | {analysis_uncomp['fund_amp_dbfs']:<18.2f} | {analysis_comp['fund_amp_dbfs']:<18.2f} | {analysis_comp['fund_amp_dbfs'] - analysis_uncomp['fund_amp_dbfs']:+18.2f}")
    print(f"{'Total Harmonic Dist (THD)':<25} | {analysis_uncomp['thd_db']:<18.2f} ({analysis_uncomp['thd_pct']:.4f}%) | {analysis_comp['thd_db']:<18.2f} ({analysis_comp['thd_pct']:.4f}%) | {analysis_uncomp['thd_db'] - analysis_comp['thd_db']:+18.2f}")
    print(f"{'THD + Noise (THD+N)':<25} | {analysis_uncomp['thdn_db']:<18.2f} ({analysis_uncomp['thdn_pct']:.4f}%) | {analysis_comp['thdn_db']:<18.2f} ({analysis_comp['thdn_pct']:.4f}%) | {analysis_uncomp['thdn_db'] - analysis_comp['thdn_db']:+18.2f}")

    print("-"*80)
    print("HARMONIC DETAILS:")
    print(f"{'Harmonic Order':<15} | {'Uncomp Level (dBc)':<18} | {'Comp Level (dBc)':<18} | {'Suppression (dB)':<18}")
    print("-"*80)

    for h in range(2, 6):
        amp_uncomp_dbc = 20 * np.log10(analysis_uncomp['harmonics_amp'][h-1] / analysis_uncomp['harmonics_amp'][0] + 1e-12)
        amp_comp_dbc = 20 * np.log10(analysis_comp['harmonics_amp'][h-1] / analysis_comp['harmonics_amp'][0] + 1e-12)
        suppression = amp_uncomp_dbc - amp_comp_dbc

        phase_uncomp = analysis_uncomp['harmonics_phase_deg'][h-1]
        phase_comp = analysis_comp['harmonics_phase_deg'][h-1]

        print(f"{h:<14}d | {amp_uncomp_dbc:<10.1f} (ph:{phase_uncomp:+.1f}°) | {amp_comp_dbc:<10.1f} (ph:{phase_comp:+.1f}°) | {suppression:+.1f} dB")

    print("="*80)
    print("DIAGNOSTIC HINTS:")
    print("1. If THD suppression is negative or 0 dB:")
    print("   - check if the loopback system has excessive phase drift or latency jitter between measurements.")
    print("   - check if the input channels (Meas vs Ref) are correctly assigned or physically swapped.")
    print("2. If THD suppression is positive but low (e.g. < 5 dB):")
    print("   - check if the analog loopback system is operating near digital full-scale clipping.")
    print("   - check if the system nonlinearity is time-variant or thermal-dependent (soft/warm state differences).")
    print("   - inspect the phase angle of the remaining harmonics in Compensated mode: if they are shifted by ~180°")
    print("     relative to the Uncompensated harmonics, the compensation might be slightly over-correcting or scaling.")
    print("="*80)

    # Stop AudioEngine
    audio_engine.stop_stream()
    logger.info("Verification script execution completed.")


if __name__ == "__main__":
    main()
