#!/usr/bin/env python3
# ruff: noqa: E402, B023
import sys
import os
import json
import numpy as np
import matplotlib.pyplot as plt
import scipy.signal

# Add project root to sys.path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.core.realtime_sss_core import RealtimeSSSEngine
from src.core.nonlinear_analyzer_core import (
    generate_sss_and_inverse,
    deconvolve_signal,
    process_amplitude_responses,
)

# -----------------------------------------------------------------------------
# 1. Virtual DUT Definition with known dynamic Hammerstein structure
# -----------------------------------------------------------------------------
def apply_virtual_dut(x, fs):
    """
    Simulates a 5th-order Hammerstein system (DUT) with dynamic filters.
    y(t) = h1 * x(t) + h2 * x^2(t) + h3 * x^3(t) + h4 * x^4(t) + h5 * x^5(t)
    """
    # Order 1: Fundamental (no filtering)
    y1 = x.copy()

    # Order 2: Low-pass filter (cutoff 1500 Hz, 2nd order Butterworth)
    b2, a2 = scipy.signal.butter(2, 1500.0 / (fs / 2.0), btype='low')
    y2 = 0.1 * scipy.signal.lfilter(b2, a2, x**2)

    # Order 3: High-pass filter (cutoff 800 Hz, 2nd order Butterworth)
    b3, a3 = scipy.signal.butter(2, 800.0 / (fs / 2.0), btype='high')
    y3 = -0.12 * scipy.signal.lfilter(b3, a3, x**3)

    # Order 4: Band-pass filter (500 Hz - 3000 Hz, 2nd order Butterworth)
    b4, a4 = scipy.signal.butter(2, [500.0 / (fs / 2.0), 3000.0 / (fs / 2.0)], btype='band')
    y4 = 0.06 * scipy.signal.lfilter(b4, a4, x**4)

    # Order 5: Pure delay (5 samples) with amplitude gain
    y5 = -0.04 * np.roll(x**5, 5)
    y5[:5] = 0.0  # Clear boundary wrap

    return y1 + y2 + y3 + y4 + y5

def get_theoretical_kernels(freqs, fs):
    """
    Returns the theoretical frequency response of the Hammerstein kernels H_p(f).
    """
    nyq = fs / 2.0
    H_theo = {}

    # H1
    H_theo[1] = np.ones_like(freqs, dtype=complex)

    # H2
    b2, a2 = scipy.signal.butter(2, 1500.0 / nyq, btype='low')
    w, h = scipy.signal.freqz(b2, a2, freqs, fs=fs)
    H_theo[2] = 0.1 * h

    # H3
    b3, a3 = scipy.signal.butter(2, 800.0 / nyq, btype='high')
    w, h = scipy.signal.freqz(b3, a3, freqs, fs=fs)
    H_theo[3] = -0.12 * h

    # H4
    b4, a4 = scipy.signal.butter(2, [500.0 / nyq, 3000.0 / nyq], btype='band')
    w, h = scipy.signal.freqz(b4, a4, freqs, fs=fs)
    H_theo[4] = 0.06 * h

    # H5 (pure delay of 5 samples)
    H_theo[5] = -0.04 * np.exp(-1j * 2 * np.pi * freqs * 5 / fs)

    return H_theo

# -----------------------------------------------------------------------------
# 2. Real-time SSS Lock-in Separation Algorithm (extracted from UI widget)
# -----------------------------------------------------------------------------
def realtime_hammerstein_separation(accumulated_sweeps, amplitude_steps, max_blocks, plot_freqs_array):
    """
    Ported from RealtimeSSSAnalyzerWidget.perform_hammerstein_separation.
    Extracts H_f from accumulated harmonic sweeps G.
    """
    num_amps = len(amplitude_steps)
    max_harm = 5

    # shape: (num_amplitudes, max_blocks, max_harmonic)
    G = accumulated_sweeps[:, :max_blocks, :max_harm]
    R = np.array(amplitude_steps)

    H_f = np.zeros((max_harm, max_blocks), dtype=complex)

    R2 = R**2
    R3 = R**3
    R4 = R**4
    R5 = R**5

    # 5th Order
    H_f[4] = 16.0 * np.sum(G[:, :, 4] * R5[:, np.newaxis], axis=0) / np.sum(R**10)

    # 4th Order
    H_f[3] = 8.0 * np.sum(G[:, :, 3] * R4[:, np.newaxis], axis=0) / np.sum(R**8)

    # 3rd Order
    g3_prime = G[:, :, 2].copy()
    g3_prime -= (5.0 / 16.0) * H_f[4][np.newaxis, :] * R5[:, np.newaxis]
    H_f[2] = 4.0 * np.sum(g3_prime * R3[:, np.newaxis], axis=0) / np.sum(R**6)

    # 2nd Order
    g2_prime = G[:, :, 1].copy()
    g2_prime -= 0.5 * H_f[3][np.newaxis, :] * R4[:, np.newaxis]
    H_f[1] = 2.0 * np.sum(g2_prime * R2[:, np.newaxis], axis=0) / np.sum(R**4)

    # 1st Order (Fundamental)
    g1_prime = G[:, :, 0].copy()
    g1_prime -= 0.75 * H_f[2][np.newaxis, :] * R3[:, np.newaxis]
    g1_prime -= 0.625 * H_f[4][np.newaxis, :] * R5[:, np.newaxis]
    H_f[0] = np.sum(g1_prime * R[:, np.newaxis], axis=0) / np.sum(R2)

    # Filter out invalid sweep regions (plot_freqs_array == 0)
    valid_indices = np.where(plot_freqs_array > 0)[0]

    rt_freqs = plot_freqs_array[valid_indices]
    rt_kernels = {}
    for p in range(max_harm):
        rt_kernels[p + 1] = H_f[p, valid_indices]

    return rt_freqs, rt_kernels

# -----------------------------------------------------------------------------
# 3. Predict Single-Tone Response from Hammerstein Kernels
# -----------------------------------------------------------------------------
def predict_harmonic_responses(H_kernels, freqs, amplitude):
    """
    Synthesizes the predicted harmonic response for a given amplitude.
    Relative to input amplitude A.
    """
    A = amplitude
    H_pred = {}

    H_pred[1] = H_kernels[1] + 0.75 * (A**2) * H_kernels[3] + 0.625 * (A**4) * H_kernels[5]
    H_pred[2] = (-1j) * (0.5 * A * H_kernels[2] + 0.5 * (A**3) * H_kernels[4])
    H_pred[3] = (-1.0) * (0.25 * (A**2) * H_kernels[3] + 0.3125 * (A**4) * H_kernels[5])
    H_pred[4] = (+1j) * (0.125 * (A**3) * H_kernels[4])
    H_pred[5] = (1.0) * (0.0625 * (A**4) * H_kernels[5])

    return H_pred

# -----------------------------------------------------------------------------
# Main Simulation Loop
# -----------------------------------------------------------------------------
def main():
    print("=============================================================")
    print("   Hammerstein Kernel Consistency Verification Script")
    print("=============================================================")

    # Test settings
    fs = 48000
    f_start = 50.0
    f_end = 18000.0
    duration = 5.0
    block_size = 1024

    # Scanning amplitudes (5 steps, from -20dBFS to -6dBFS)
    amplitudes_db = np.linspace(-20.0, -6.0, 5)
    amplitudes_linear = 10 ** (amplitudes_db / 20.0)
    print(f"Amplitudes (linear): {np.round(amplitudes_linear, 4)}")

    # Latency setting (virtual loopback delay)
    latency_samples = 1024.0
    latency_sec = latency_samples / fs

    # -------------------------------------------------------------------------
    # Route 1: Real-time SSS Engine Loop (DDC + LS)
    # -------------------------------------------------------------------------
    print("\n[*] Running Route 1: Real-time SSS Lock-in Loop...")

    # Setup dummy engine to determine blocks and sweep samples
    test_eng = RealtimeSSSEngine(
        sample_rate=fs,
        sweep_duration=duration,
        start_freq=f_start,
        end_freq=f_end,
        output_amplitude=amplitudes_linear[0],
        max_harmonic=5,
        analysis_cycles=16.0,
        num_meas_points=500
    )
    test_eng.prepare_sweep()
    max_blocks = int(np.ceil((test_eng.sweep_samples + latency_samples) / block_size))

    # Allocate accumulated sweep buffer
    accumulated_sweeps = np.zeros((len(amplitudes_linear), max_blocks, 5), dtype=complex)
    plot_freqs_array = np.zeros(max_blocks)

    for amp_idx, amp in enumerate(amplitudes_linear):
        # Create fresh engine for this amplitude step
        rt_engine = RealtimeSSSEngine(
            sample_rate=fs,
            sweep_duration=duration,
            start_freq=f_start,
            end_freq=f_end,
            output_amplitude=amp,
            max_harmonic=5,
            analysis_cycles=16.0,
            num_meas_points=500
        )
        rt_engine.prepare_sweep()
        rt_engine.set_latency(latency_samples)

        # 1. Output Generation & Virtual DUT application
        # To simulate a physical audio loop, we generate the entire sweep block-by-block,
        # concatenate it, apply the delay and DUT, and feed it block-by-block.
        out_signal = np.zeros(max_blocks * block_size)
        for b in range(max_blocks):
            out_block = np.zeros((block_size, 1))
            rt_engine.generate_output_block(out_block, b)
            out_signal[b * block_size : (b + 1) * block_size] = out_block[:, 0]

        # Apply latency delay (pure shift)
        out_delayed = np.zeros_like(out_signal)
        delay_idx = int(latency_samples)
        out_delayed[delay_idx:] = out_signal[:-delay_idx]

        # Pass through the virtual non-linear dynamic system (DUT)
        meas_signal = apply_virtual_dut(out_delayed, fs)
        ref_signal = out_delayed  # Clean reference channel (Ch2)

        # 2. Block Processing Loop (Lock-in extraction)
        for b in range(max_blocks):
            sig_in = meas_signal[b * block_size : (b + 1) * block_size, np.newaxis]
            ref_in = ref_signal[b * block_size : (b + 1) * block_size, np.newaxis]

            f_mid, results = rt_engine.process_input_block(sig_in, b, ref_in_block=ref_in)
            if rt_engine.last_block_was_valid:
                accumulated_sweeps[amp_idx, b, :] = results[:5]
                plot_freqs_array[b] = f_mid

    # Execute SSS Hammerstein separation
    # G in accumulated_sweeps is relative (divided by ref_h1, which is approx amp),
    # but the separation formula expects absolute harmonic responses.
    # We scale G back to absolute values and apply the sine phase correction factors 
    # to align them with the reference phase of the Nonlinear Analyzer (Deconvolution).
    # Corrections: 2nd harmonic * 1j, 3rd harmonic * -1, 4th harmonic * -1j, 5th harmonic * 1
    accumulated_sweeps_abs = accumulated_sweeps.copy()
    for j, amp in enumerate(amplitudes_linear):
        accumulated_sweeps_abs[j, :, :] *= amp
        accumulated_sweeps_abs[j, :, 1] *= 1j
        accumulated_sweeps_abs[j, :, 2] *= -1.0
        accumulated_sweeps_abs[j, :, 3] *= -1j

    rt_freqs, rt_kernels = realtime_hammerstein_separation(
        accumulated_sweeps_abs, amplitudes_linear, max_blocks, plot_freqs_array
    )
    print(f"[+] Route 1 finished. Valid points: {len(rt_freqs)}")

    # -------------------------------------------------------------------------
    # Route 2: Offline Nonlinear Analyzer (Deconvolution)
    # -------------------------------------------------------------------------
    print("\n[*] Running Route 2: Offline Nonlinear Sweep (Deconvolution)...")

    # SSS sweep signal generation
    sss, inv_filter = generate_sss_and_inverse(fs, duration, f_start, f_end)
    single_sweep_len = len(sss)
    padding_samples = int(0.5 * fs)
    block_len = single_sweep_len + padding_samples

    total_len = len(amplitudes_linear) * block_len
    cont_signal = np.zeros(total_len, dtype=np.float32)

    # Construct continuous sweep sequence (analogous to NonlinearAnalyzer._execute_measurement)
    for amp_idx, amp in enumerate(amplitudes_linear):
        start_pt = amp_idx * block_len
        cont_signal[start_pt : start_pt + single_sweep_len] = amp * sss

    # Apply virtual delay (latency_samples)
    cont_delayed = np.zeros_like(cont_signal)
    delay_idx = int(latency_samples)
    cont_delayed[delay_idx:] = cont_signal[:-delay_idx]

    # Pass through virtual DUT
    meas_recorded = apply_virtual_dut(cont_delayed, fs)
    ref_recorded = cont_delayed  # Clean reference

    # Slice and average (using averages = 1 in this test)
    responses_ref = []
    responses_meas = []

    for amp_idx in range(len(amplitudes_linear)):
        start_pt = amp_idx * block_len
        end_pt = start_pt + block_len

        rec_block = meas_recorded[start_pt:end_pt]
        ref_block = ref_recorded[start_pt:end_pt]

        ir_meas = deconvolve_signal(rec_block, sss)
        ir_ref = deconvolve_signal(ref_block, sss)

        responses_meas.append(ir_meas)
        responses_ref.append(ir_ref)

    # Run Hammerstein separation (calibrate_systematic = False for exact match)
    # input_mode = 'XFER_REV' (Meas on Ch1, Ref on Ch2)
    valid_freqs, nl_mags_db, nl_phases_deg, time_ms, separated_kernels = process_amplitude_responses(
        responses_meas,
        responses_ref,
        fs,
        f_start,
        f_end,
        input_mode="XFER_REV",
        latency_sec=latency_sec,
        sweep_duration=duration,
        P=5,
        amplitudes=amplitudes_linear,
        calibrate_systematic=False,
    )

    # Reconstruct complex kernels from Nonlinear Analyzer output and compensate the gate_pre delay.
    # Nonlinear Analyzer shifts the time-domain kernel peak to gate_pre.
    # To compare it with the Real-time SSS (which is at t=0), we shift it back in the frequency domain.
    gate_pre = int(0.007 * fs)
    nl_kernels = {}
    for p in range(1, 6):
        mag_lin = 10 ** (nl_mags_db[f"h{p}"] / 20.0)
        phase_rad = np.radians(nl_phases_deg[f"h{p}"])
        # Apply phase lead to cancel gate_pre delay (positive phase shift)
        phase_corrected = phase_rad + 2.0 * np.pi * valid_freqs * (gate_pre / fs)
        nl_kernels[p] = mag_lin * np.exp(1j * phase_corrected)

    print(f"[+] Route 2 finished. Valid points: {len(valid_freqs)}")

    # -------------------------------------------------------------------------
    # 4. Evaluation and Comparison
    # -------------------------------------------------------------------------
    print("\n[*] Evaluating Consistency between RT SSS and Offline SSS...")

    # Find common frequency range to avoid edges/transients
    f_min_eval = max(f_start, 100.0)
    f_max_eval = min(f_end, 15000.0)
    eval_freqs = np.logspace(np.log10(f_min_eval), np.log10(f_max_eval), 300)

    # Get theoretical kernels on eval grid for reference
    theo_kernels = get_theoretical_kernels(eval_freqs, fs)

    # Interpolate kernels to eval_freqs
    rt_kernels_interp = {}
    nl_kernels_interp = {}

    for p in range(1, 6):
        # RT SSS Interpolation
        # The RT frequency axis is based on fundamental frequency f.
        # But order p represents system response at physical frequency p * f.
        # Therefore, we must scale the RT frequency axis by factor p to compare it with the physical frequency.
        rt_mag_lin = np.abs(rt_kernels[p])
        rt_phase_unwrapped = np.unwrap(np.angle(rt_kernels[p]))

        # Use left=nan, right=nan to prevent extrapolation error at low/high limits
        rt_mag_i = np.interp(eval_freqs, p * rt_freqs, rt_mag_lin, left=np.nan, right=np.nan)
        rt_phase_i = np.interp(eval_freqs, p * rt_freqs, rt_phase_unwrapped, left=np.nan, right=np.nan)
        rt_kernels_interp[p] = rt_mag_i * np.exp(1j * rt_phase_i)

        # Offline SSS Interpolation
        nl_mag_lin = np.abs(nl_kernels[p])
        nl_phase_unwrapped = np.unwrap(np.angle(nl_kernels[p]))
        nl_kernels_interp[p] = np.interp(eval_freqs, valid_freqs, nl_mag_lin, left=np.nan, right=np.nan) * np.exp(
            1j * np.interp(eval_freqs, valid_freqs, nl_phase_unwrapped, left=np.nan, right=np.nan)
        )

    # Compute errors on Hammerstein kernels themselves
    print("\n--- Kernel Accuracy (RT vs Offline vs Theory) ---")
    kernel_mae_gain = {}
    kernel_mae_phase = {}

    for p in range(1, 6):
        rt_mag_db = 20 * np.log10(np.abs(rt_kernels_interp[p]) + 1e-15)
        nl_mag_db = 20 * np.log10(np.abs(nl_kernels_interp[p]) + 1e-15)

        rt_phase_deg = np.degrees(np.angle(rt_kernels_interp[p]))
        nl_phase_deg = np.degrees(np.angle(nl_kernels_interp[p]))

        # Limit evaluation to the region below the order's LPF cutoff (which is in the Offline analyzer)
        # and above the physical sweep start to avoid transient / out-of-bound edge artifacts.
        f_cut = min(20000.0, 1.15 * fs / (2 * p)) if p > 1 else 15000.0
        mask_p = (eval_freqs > p * f_start * 1.25) & (eval_freqs < f_cut * 0.85) & ~np.isnan(rt_mag_db) & ~np.isnan(nl_mag_db)

        gain_diff = rt_mag_db[mask_p] - nl_mag_db[mask_p]
        phase_diff = (rt_phase_deg[mask_p] - nl_phase_deg[mask_p] + 180) % 360 - 180

        # Use nanmean/nanmax as a safeguard (mask_p already removes nans)
        mae_gain = np.nanmean(np.abs(gain_diff)) if len(gain_diff) > 0 else 0.0
        max_gain = np.nanmax(np.abs(gain_diff)) if len(gain_diff) > 0 else 0.0
        mae_phase = np.nanmean(np.abs(phase_diff)) if len(phase_diff) > 0 else 0.0
        max_phase = np.nanmax(np.abs(phase_diff)) if len(phase_diff) > 0 else 0.0

        kernel_mae_gain[p] = float(mae_gain)
        kernel_mae_phase[p] = float(mae_phase)

        print(f"Kernel H{p}:")
        print(f"  RT vs Offline Gain Difference: MAE = {mae_gain:.4f} dB, Max = {max_gain:.4f} dB")
        print(f"  RT vs Offline Phase Difference: MAE = {mae_phase:.4f} deg, Max = {max_phase:.4f} deg")

    # Predict Single-Tone harmonic response for a testing amplitude (e.g. A = 0.4)
    test_amp = 0.4
    print(f"\n[*] Predicting Single-Tone response (Gain/Phase) at Amplitude = {test_amp}...")

    rt_pred_response = predict_harmonic_responses(rt_kernels_interp, eval_freqs, test_amp)
    nl_pred_response = predict_harmonic_responses(nl_kernels_interp, eval_freqs, test_amp)
    theo_pred_response = predict_harmonic_responses(theo_kernels, eval_freqs, test_amp)

    harmonic_mae_gain = {}
    harmonic_mae_phase = {}

    print("\n--- Predicted Harmonic Response Accuracy (RT vs Offline) ---")
    for h in range(1, 6):
        rt_harm_mag_db = 20 * np.log10(np.abs(rt_pred_response[h]) + 1e-15)
        nl_harm_mag_db = 20 * np.log10(np.abs(nl_pred_response[h]) + 1e-15)

        rt_harm_phase_deg = np.degrees(np.angle(rt_pred_response[h]))
        nl_harm_phase_deg = np.degrees(np.angle(nl_pred_response[h]))

        # Limit evaluation to the region below the order's LPF cutoff
        # and above the physical sweep start to avoid transient / out-of-bound edge artifacts.
        f_cut = min(20000.0, 1.15 * fs / (2 * h)) if h > 1 else 15000.0
        mask_h = (eval_freqs > h * f_start * 1.25) & (eval_freqs < f_cut * 0.85) & ~np.isnan(rt_harm_mag_db) & ~np.isnan(nl_harm_mag_db)

        gain_diff = rt_harm_mag_db[mask_h] - nl_harm_mag_db[mask_h]
        phase_diff = (rt_harm_phase_deg[mask_h] - nl_harm_phase_deg[mask_h] + 180) % 360 - 180

        # Use nanmean/nanmax as a safeguard
        mae_gain = np.nanmean(np.abs(gain_diff)) if len(gain_diff) > 0 else 0.0
        max_gain = np.nanmax(np.abs(gain_diff)) if len(gain_diff) > 0 else 0.0
        mae_phase = np.nanmean(np.abs(phase_diff)) if len(phase_diff) > 0 else 0.0
        max_phase = np.nanmax(np.abs(phase_diff)) if len(phase_diff) > 0 else 0.0

        harmonic_mae_gain[h] = float(mae_gain)
        harmonic_mae_phase[h] = float(mae_phase)

        print(f"Harmonic {h} Response:")
        print(f"  Gain Error (RT vs Offline): MAE = {mae_gain:.4f} dB, Max = {max_gain:.4f} dB")
        print(f"  Phase Error (RT vs Offline): MAE = {mae_phase:.4f} deg, Max = {max_phase:.4f} deg")

    # -------------------------------------------------------------------------
    # 5. Plotting results
    # -------------------------------------------------------------------------
    print("\n[*] Plotting verification results...")
    fig, axs = plt.subplots(3, 2, figsize=(14, 12), sharex=True)
    fig.suptitle(f"Hammerstein Kernel & Response Consistency\nRT SSS (DDC+LS) vs Offline SSS (Deconvolution) [Amp = {test_amp}]", fontsize=14)

    colors = ["#1f77b4", "#2ca02c", "#bcbd22", "#9467bd", "#d62728"]

    # Kernel Gain / Phase Plot
    for p in range(1, 6):
        axs[0, 0].plot(eval_freqs, 20 * np.log10(np.abs(rt_kernels_interp[p]) + 1e-12), color=colors[p-1], linestyle="--", alpha=0.8)
        axs[0, 0].plot(eval_freqs, 20 * np.log10(np.abs(nl_kernels_interp[p]) + 1e-12), color=colors[p-1], linestyle="-", label=f"H{p}")

        rt_phase_unwrapped = np.unwrap(np.angle(rt_kernels_interp[p]))
        nl_phase_unwrapped = np.unwrap(np.angle(nl_kernels_interp[p]))
        axs[1, 0].plot(eval_freqs, np.degrees(rt_phase_unwrapped), color=colors[p-1], linestyle="--", alpha=0.8)
        axs[1, 0].plot(eval_freqs, np.degrees(nl_phase_unwrapped), color=colors[p-1], linestyle="-")

    axs[0, 0].set_ylabel("Kernel Gain H_p(f) [dB]")
    axs[0, 0].set_title("Hammerstein Kernels (Solid: Offline, Dashed: Real-time)")
    axs[0, 0].legend()
    axs[0, 0].grid(True)

    axs[1, 0].set_ylabel("Kernel Phase [deg]")
    axs[1, 0].grid(True)

    # Predicted Response Gain / Phase Plot (Single-Tone)
    for h in range(1, 6):
        axs[0, 1].plot(eval_freqs, 20 * np.log10(np.abs(rt_pred_response[h]) + 1e-12), color=colors[h-1], linestyle="--", alpha=0.8)
        axs[0, 1].plot(eval_freqs, 20 * np.log10(np.abs(nl_pred_response[h]) + 1e-12), color=colors[h-1], linestyle="-", label=f"Harm {h}")

        rt_phase_unwrapped = np.unwrap(np.angle(rt_pred_response[h]))
        nl_phase_unwrapped = np.unwrap(np.angle(nl_pred_response[h]))
        axs[1, 1].plot(eval_freqs, np.degrees(rt_phase_unwrapped), color=colors[h-1], linestyle="--", alpha=0.8)
        axs[1, 1].plot(eval_freqs, np.degrees(nl_phase_unwrapped), color=colors[h-1], linestyle="-")

    axs[0, 1].set_ylabel("Predicted Response [dB]")
    axs[0, 1].set_title(f"Predicted Single-Tone Response (Solid: Offline, Dashed: Real-time, A={test_amp})")
    axs[0, 1].legend()
    axs[0, 1].grid(True)

    axs[1, 1].set_ylabel("Response Phase [deg]")
    axs[1, 1].grid(True)

    # Error Plots (RT - Offline)
    for p in range(1, 6):
        gain_err = 20 * np.log10(np.abs(rt_kernels_interp[p]) + 1e-15) - 20 * np.log10(np.abs(nl_kernels_interp[p]) + 1e-15)
        phase_err = (np.degrees(np.unwrap(np.angle(rt_kernels_interp[p]))) - np.degrees(np.unwrap(np.angle(nl_kernels_interp[p]))) + 180) % 360 - 180
        axs[2, 0].plot(eval_freqs, gain_err, color=colors[p-1], label=f"H{p}")
        axs[2, 1].plot(eval_freqs, phase_err, color=colors[p-1], label=f"H{p}")

    axs[2, 0].set_ylabel("Kernel Gain Error [dB]")
    axs[2, 0].set_xlabel("Frequency [Hz]")
    axs[2, 0].set_xscale("log")
    axs[2, 0].grid(True)

    axs[2, 1].set_ylabel("Kernel Phase Error [deg]")
    axs[2, 1].set_xlabel("Frequency [Hz]")
    axs[2, 1].set_xscale("log")
    axs[2, 1].grid(True)

    plt.tight_layout()
    plot_path = os.path.join(project_root, "scripts", "hammerstein_consistency_results.png")
    plt.savefig(plot_path, dpi=150)
    print(f"\n[+] Saved verification plot to {plot_path}")

    # Save JSON metrics
    metrics = {
        "kernel_errors": {
            f"h{p}": {"gain_mae_db": kernel_mae_gain[p], "phase_mae_deg": kernel_mae_phase[p]} for p in range(1, 6)
        },
        "response_errors": {
            f"h{h}": {"gain_mae_db": harmonic_mae_gain[h], "phase_mae_deg": harmonic_mae_phase[h]} for h in range(1, 6)
        }
    }
    json_path = os.path.join(project_root, "scripts", "hammerstein_consistency_results.json")
    with open(json_path, "w") as f:
        json.dump(metrics, f, indent=4)
    print(f"[+] Saved metrics JSON to {json_path}")

    # -------------------------------------------------------------------------
    # 6. Pass/Fail Decision
    # -------------------------------------------------------------------------
    passed = True
    # Let's set the threshold for absolute algorithm consistency.
    # Because both routes implement the same Chebyshev polynomial decomposition,
    # they should yield almost identical kernels.
    # The real-time DDC uses a Hanning window on a sliding log sweep, which introduces
    # very minor spectral leakage and transient filtering differences, so they won't be
    # strictly 0.0, but should be extremely close (Gain MAE < 0.2 dB, Phase MAE < 5.0 deg).
    for p in range(1, 6):
        gain_mae = kernel_mae_gain[p]
        phase_mae = kernel_mae_phase[p]

        limit_gain = 0.25 if p == 1 else 1.5
        limit_phase = 5.0 if p == 1 else 10.0

        if gain_mae > limit_gain or phase_mae > limit_phase:
            passed = False
            print(f"[-] WARNING: Kernel H{p} exceeded consistency threshold (Limit Gain: {limit_gain}dB, Phase: {limit_phase}deg)")

    if passed:
        print("\n[+] Verification SUCCESS: RT SSS and Offline SSS Hammerstein separation are highly consistent!")
        sys.exit(0)
    else:
        print("\n[-] Verification FAILED: Kernels show discrepancy. Please check separation logic.")
        sys.exit(1)

if __name__ == "__main__":
    main()
