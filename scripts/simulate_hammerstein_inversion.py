#!/usr/bin/env python
import os
import sys
import argparse
import logging
import numpy as np
import scipy.signal
import matplotlib.pyplot as plt

# Add project root to python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.core.realtime_sss_core import RealtimeSSSEngine
from src.core.predistortion import PredistortionManager
from src.core.predistortion_applicator import PredistortionApplicator


class VirtualDUT:
    """
    Simulates a 5th-order parallel Hammerstein system as the Device Under Test (DUT).
    Uses pure delay and constant gains (no phase dispersion) to simplify single-channel phase alignment.
    y(t) = sum_{p=1}^5 h_p_true(t) * [x(t)]^p
    """

    def __init__(self, sample_rate=48000):
        self.fs = sample_rate
        self.N_kernel = 960
        delay_offset = 240  # 5ms delay

        # h1_true (Linear response): Pure delay with 0.8 gain
        self.h1_true = np.zeros(self.N_kernel)
        self.h1_true[delay_offset] = 0.8

        # h2_true (2nd order): Pure delay with 0.05 gain
        self.h2_true = np.zeros(self.N_kernel)
        self.h2_true[delay_offset] = 0.05

        # h3_true (3rd order): Pure delay with -0.03 gain
        self.h3_true = np.zeros(self.N_kernel)
        self.h3_true[delay_offset] = -0.03

        # h4_true (4th order): Pure delay with 0.015 gain
        self.h4_true = np.zeros(self.N_kernel)
        self.h4_true[delay_offset] = 0.015

        # h5_true (5th order): Pure delay with -0.01 gain
        self.h5_true = np.zeros(self.N_kernel)
        self.h5_true[delay_offset] = -0.01

        self.true_kernels = [self.h1_true, self.h2_true, self.h3_true, self.h4_true, self.h5_true]

    def process(self, x):
        """Processes the input signal x(t) through the parallel Hammerstein system.
        Applies a DC cut filter (5Hz Highpass) to simulate AC coupling of real audio interfaces.
        """
        y = np.zeros_like(x)
        for p, hp in enumerate(self.true_kernels):
            order = p + 1
            x_p = x**order
            y += scipy.signal.lfilter(hp, [1.0], x_p)

        # 1st order IIR DC block filter (HPF at ~5 Hz)
        alpha = np.exp(-2.0 * np.pi * 5.0 / self.fs)
        y = scipy.signal.lfilter([1.0, -1.0], [1.0, -alpha], y)
        return y


def calculate_fitted_mse(x_steady, z_steady, fs, f0):
    """
    Fits the fundamental components (sine and cosine at f0) and DC offset of z_steady to x_steady,
    and returns the MSE of the remaining residual (harmonics and noise).
    """
    N = len(x_steady)
    t = np.arange(N) / fs

    # Design matrix for fundamental sine, cosine, and DC offset (constant)
    A = np.column_stack((np.sin(2 * np.pi * f0 * t), np.cos(2 * np.pi * f0 * t), np.ones(N)))

    # Solve for fundamental + DC coefficients in z_steady
    coefs, _, _, _ = np.linalg.lstsq(A, z_steady, rcond=None)
    z_fundamental = A @ coefs

    # The residual is the non-linear distortion (harmonics + noise)
    z_distortion = z_steady - z_fundamental

    # For x_steady, get the reference residual (should be 0, but to match scaling)
    coefs_x, _, _, _ = np.linalg.lstsq(A, x_steady, rcond=None)
    x_fundamental = A @ coefs_x
    x_distortion = x_steady - x_fundamental

    # Print DC offset values
    print(f"[DEBUG] DC offset: target={coefs_x[2]:.6f}, actual={coefs[2]:.6f}")

    return np.mean((x_distortion - z_distortion) ** 2)


def estimate_thd_and_spectrum(sig, fs, f0):
    """Estimates the spectrum and THD (up to 5th harmonic) of a sine-wave signal."""
    N = len(sig)
    # Apply Hanning window
    window = np.hanning(N)
    sig_win = sig * window

    # Compute FFT
    fft_vals = np.fft.rfft(sig_win)
    freqs = np.fft.rfftfreq(N, 1.0 / fs)

    # Normalize magnitude
    mags = np.abs(fft_vals) / (np.sum(window) / 2.0)
    mags_db = 20 * np.log10(mags + 1e-12)

    # Locate fundamental and harmonics
    harmonics = []
    for h in range(1, 6):
        target_f = h * f0
        idx = np.argmin(np.abs(freqs - target_f))
        # Find peak in local window
        search_win = 5
        local_idx = idx - search_win + np.argmax(mags[idx - search_win : idx + search_win + 1])
        harmonics.append(mags[local_idx])

    fundamental_mag = harmonics[0]
    harmonic_mags = harmonics[1:]

    # THD calculation
    thd = np.sqrt(np.sum(np.array(harmonic_mags) ** 2)) / fundamental_mag if fundamental_mag > 1e-12 else 0.0
    return thd, freqs, mags_db, harmonics


def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description="Hammerstein Identification and Predistortion Simulation")
    parser.add_argument("--output_dir", type=str, default=".", help="Directory to save plot results")
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)

    fs = 48000
    P = 5
    sweep_duration = 10.0
    start_freq = 20.0
    end_freq = 20000.0

    print("--- 1. Initializing Virtual DUT ---")
    dut = VirtualDUT(sample_rate=fs)

    # ---------------------------------------------------------
    # 2. Forward Hammerstein Model F Identification
    # ---------------------------------------------------------
    print("--- 2. Measuring Forward Hammerstein Model F ---")

    # Establish measurement amplitude steps
    num_amplitudes = 5
    max_amp_db = -6.0  # -6 dBFS
    max_amp = 10 ** (max_amp_db / 20.0)
    amplitudes = np.linspace(0.2, 1.0, num_amplitudes) * max_amp

    engine = RealtimeSSSEngine(
        sample_rate=fs,
        sweep_duration=sweep_duration,
        start_freq=start_freq,
        end_freq=end_freq,
        output_amplitude=max_amp,
        max_harmonic=P,
        analysis_cycles=250.0,
        num_meas_points=200,
    )
    # Measure latency of the DUT automatically
    print("--- 1.5. Calibrating Latency of Virtual DUT ---")
    impulse = np.zeros(2048)
    impulse[0] = 1.0
    dut_ir = dut.process(impulse)
    from src.core.nonlinear_analyzer_core import find_subsample_peak

    measured_latency = find_subsample_peak(dut_ir)
    print(f"  - Measured Latency: {measured_latency:.3f} samples (approx. {measured_latency / fs * 1000.0:.2f} ms)")

    engine.prepare_sweep()
    engine.set_latency(measured_latency)

    frames = 512
    max_blocks = int(np.ceil(engine.sweep_samples / frames))

    raw_responses = np.zeros((num_amplitudes, max_blocks, P), dtype=complex)
    plot_freqs_array = np.zeros(max_blocks)

    # Loop over all testing amplitudes for forward estimation
    for amp_idx, amp in enumerate(amplitudes):
        print(
            f"  - Sweep at amplitude step {amp_idx + 1}/{num_amplitudes}: {amp:.3f} (approx. {20 * np.log10(amp):.1f} dBFS)"
        )
        engine.output_amplitude = amp
        engine.reset_filter_states()

        # Generate the full SSS excitation signal first
        x_full = np.zeros(engine.sweep_samples)
        for b in range(max_blocks):
            outdata = np.zeros((frames, 1))
            engine.generate_output_block(outdata, b)
            start_samp = b * frames
            chunk = min(frames, engine.sweep_samples - start_samp)
            x_full[start_samp : start_samp + chunk] = outdata[:chunk, 0]

        # Process the full signal through the DUT to maintain filter states and continuity
        y_full = dut.process(x_full)

        # Lock-in analysis block-by-block
        for b in range(max_blocks):
            start_samp = b * frames
            indata = np.zeros((frames, 1))
            if start_samp < len(y_full):
                chunk = min(frames, len(y_full) - start_samp)
                indata[:chunk, 0] = y_full[start_samp : start_samp + chunk]

            f_mid, results = engine.process_input_block(indata, b)

            raw_responses[amp_idx, b, :] = results[:P]
            if amp_idx == 0:
                plot_freqs_array[b] = f_mid

    # Direct solving of forward parallel Hammerstein kernels
    phase_corrections = [(1j) ** p for p in range(P)]
    g_scaled = np.zeros_like(raw_responses)
    for amp_idx in range(num_amplitudes):
        amp = amplitudes[amp_idx]
        for p in range(P):
            val = raw_responses[amp_idx, :, p]
            # Phase correction for sine excitation phase offsets
            g_scaled[amp_idx, :, p] = val * phase_corrections[p]

    g1 = g_scaled[:, :, 0]
    g2 = g_scaled[:, :, 1]
    g3 = g_scaled[:, :, 2]
    g4 = g_scaled[:, :, 3]
    g5 = g_scaled[:, :, 4]

    R_array = amplitudes
    R2 = R_array**2
    R3 = R_array**3
    R4 = R_array**4
    R5 = R_array**5

    # Chebyshev/power inversion matrices
    H5 = 16 * np.sum(g5 * R5[:, np.newaxis], axis=0) / np.sum(R_array**10)
    H4 = 8 * np.sum(g4 * R4[:, np.newaxis], axis=0) / np.sum(R_array**8)

    g3_prime = g3 - (5 / 16) * H5[np.newaxis, :] * R5[:, np.newaxis]
    H3 = 4 * np.sum(g3_prime * R3[:, np.newaxis], axis=0) / np.sum(R_array**6)

    g2_prime = g2 - 0.5 * H4[np.newaxis, :] * R4[:, np.newaxis]
    H2 = 2 * np.sum(g2_prime * R2[:, np.newaxis], axis=0) / np.sum(R_array**4)

    g1_prime = g1 - 0.75 * H3[np.newaxis, :] * R3[:, np.newaxis] - 0.625 * H5[np.newaxis, :] * R5[:, np.newaxis]
    H1 = np.sum(g1_prime * R_array[:, np.newaxis], axis=0) / np.sum(R_array**2)

    # Map frequency responses back to time domain impulse responses (kernels)
    gate_pre = int(0.007 * fs)
    N_kernel = int(0.02 * fs)
    N_fft = max(2048, int(2 ** np.ceil(np.log2(N_kernel))))
    freqs_lin = np.linspace(0, fs / 2.0, N_fft // 2 + 1)
    sorted_freqs = plot_freqs_array

    H_freqs_F = [H1, H2, H3, H4, H5]
    kernels_time_F = []

    for p in range(P):
        H_p = H_freqs_F[p]
        # Clean NaNs
        mask_nan = np.isnan(H_p)
        H_p_clean = H_p.copy()
        H_p_clean[mask_nan] = 0.0

        mags = np.abs(H_p_clean)
        phases = np.unwrap(np.angle(H_p_clean))

        mag_lin = np.interp(freqs_lin, sorted_freqs, mags, left=0.0, right=0.0)
        phase_lin = np.interp(freqs_lin, sorted_freqs, phases, left=0.0, right=0.0)
        H_lin = mag_lin * np.exp(1j * phase_lin)

        # Apply smooth frequency rolloff to avoid Gibbs phenomenon
        f_hi = 20000.0
        f_fade_out_start = 17000.0
        fade_mask_in = (freqs_lin >= 10.0) & (freqs_lin < 20.0)
        fade_mask_out = (freqs_lin >= f_fade_out_start) & (freqs_lin < f_hi)

        H_lin_smooth = H_lin.copy()
        if np.any(fade_mask_in):
            progress_in = (freqs_lin[fade_mask_in] - 10.0) / 10.0
            H_lin_smooth[fade_mask_in] *= 0.5 * (1.0 - np.cos(np.pi * progress_in))
        H_lin_smooth[freqs_lin < 10.0] = 0.0

        if np.any(fade_mask_out) and f_hi > f_fade_out_start:
            progress_out = (freqs_lin[fade_mask_out] - f_fade_out_start) / (f_hi - f_fade_out_start)
            H_lin_smooth[fade_mask_out] *= 0.5 * (1.0 + np.cos(np.pi * progress_out))
        H_lin_smooth[freqs_lin >= f_hi] = 0.0

        # Shift back by gate_pre to construct a causal FIR kernel centered around gate_pre
        phase_shift = np.exp(-1j * 2 * np.pi * freqs_lin * (gate_pre / fs))
        H_lin_shifted = H_lin_smooth * phase_shift

        h_full = np.fft.irfft(H_lin_shifted, n=N_fft)
        h_cropped = h_full[:N_kernel]
        win = scipy.signal.windows.tukey(N_kernel, alpha=0.1)
        kernels_time_F.append(h_cropped * win)

    # ---------------------------------------------------------
    # 3. Adaptive Predistortion Sweep to Build Inverse Model G
    # ---------------------------------------------------------
    print("--- 3. Measuring Inverse Hammerstein Model G (Adaptive Sweep) ---")

    N_adapt = 4
    mu = 0.5

    predistortion_managers = []
    F_corr_mapped = np.zeros((num_amplitudes, max_blocks, P), dtype=complex)

    # Keep track of final iteration's linear response to compute baseline H1_base
    raw_responses_inv = np.zeros((num_amplitudes, max_blocks, P), dtype=complex)

    for amp_idx, amp in enumerate(amplitudes):
        print(f"  - Adaptive predistortion at amplitude step {amp_idx + 1}/{num_amplitudes}: {amp:.3f}")

        # Instantiate a fresh manager for this amplitude
        predist_mgr = PredistortionManager(
            start_freq=start_freq, end_freq=end_freq, meas_freqs=engine.meas_freqs, max_harmonic=P
        )

        for iter_idx in range(N_adapt + 1):
            # Generate predistorted sweep signal using current correction terms
            x_corr = predist_mgr.generate_predistorted_sweep(
                sample_rate=fs,
                sweep_samples=engine.sweep_samples,
                k_param=engine.k_param,
                L_param=engine.L_param,
                amplitude=amp,
            )

            # Process the full signal through the DUT first to maintain filter states and continuity
            y_full = dut.process(x_corr)

            # Execute physical-simulated sweep measurement
            engine.reset_filter_states()
            accumulated_results = np.zeros((max_blocks, P), dtype=complex)
            block_counts = np.zeros(max_blocks, dtype=int)

            for b in range(max_blocks):
                # Copy block chunk from y_full
                start_samp = b * frames
                indata = np.zeros((frames, 1))
                if start_samp < len(y_full):
                    chunk = min(frames, len(y_full) - start_samp)
                    indata[:chunk, 0] = y_full[start_samp : start_samp + chunk]

                # Lock-in extraction
                f_mid, results = engine.process_input_block(indata, b)

                accumulated_results[b, :] = results[:P]
                block_counts[b] = 1

            # Perform iterative predistortion update
            if iter_idx < N_adapt:
                predist_mgr.update_correction(
                    iteration=iter_idx,
                    x_data=plot_freqs_array,
                    raw_results=accumulated_results,
                    block_counts=block_counts,
                    mu=mu,
                )
            else:
                # Save the final iteration's measured responses to raw_responses_inv
                raw_responses_inv[amp_idx, :, :] = accumulated_results

        # Store the manager and map the final accumulated correction filters F_corr
        predistortion_managers.append(predist_mgr)

        # Map F_corr to the common physical frequency axis
        for p in range(1, P):
            n = p + 1
            F_raw = predist_mgr.F_corr[n]
            mag_raw = np.abs(F_raw)
            phase_raw = np.unwrap(np.angle(F_raw))

            f_lookups = plot_freqs_array / n
            mag_interp = np.interp(f_lookups, predist_mgr.meas_freqs, mag_raw, left=0.0, right=0.0)
            phase_interp = np.interp(f_lookups, predist_mgr.meas_freqs, phase_raw, left=0.0, right=0.0)

            F_corr_mapped[amp_idx, :, p] = mag_interp * np.exp(1j * phase_interp)

    # Phase correction to compensate for sine expansion phase offsets for G estimation
    phase_corrections = [(1j) ** p for p in range(P)]
    for p in range(1, P):
        F_corr_mapped[:, :, p] *= phase_corrections[p]

    # Solve the inverse Hammerstein kernels on physical frequency axis
    R_array = amplitudes
    R2 = R_array**2
    R3 = R_array**3
    R4 = R_array**4
    R5 = R_array**5
    R6 = R_array**6
    R8 = R_array**8

    f5 = 16 * np.sum(F_corr_mapped[:, :, 4] * R4[:, np.newaxis], axis=0) / np.sum(R8)
    f4 = 8 * np.sum(F_corr_mapped[:, :, 3] * R3[:, np.newaxis], axis=0) / np.sum(R6)

    F3_prime = F_corr_mapped[:, :, 2] - (5 / 16) * f5[np.newaxis, :] * R4[:, np.newaxis]
    f3 = 4 * np.sum(F3_prime * R2[:, np.newaxis], axis=0) / np.sum(R4)

    F2_prime = F_corr_mapped[:, :, 1] - 0.5 * f4[np.newaxis, :] * R3[:, np.newaxis]
    f2 = 2 * np.sum(F2_prime * R_array[:, np.newaxis], axis=0) / np.sum(R2)

    # For the fundamental, F_corr = 0 (since x_corr = 1.0 * x_base + harmonics).
    # So the target fundamental for the predistortion polynomial is 1.0!
    F1_target = 1.0 * R_array[:, np.newaxis]
    F1_prime = F1_target - 0.75 * f3[np.newaxis, :] * R3[:, np.newaxis] - 0.625 * f5[np.newaxis, :] * R5[:, np.newaxis]
    f1 = np.sum(F1_prime * R_array[:, np.newaxis], axis=0) / np.sum(R_array**2)

    # The inverse Hammerstein model G(x) needs to satisfy DUT(G(x)) = x.
    # Since we found f(x) such that DUT(f(x)) = H1(x),
    # we can construct G(x) = f( G1_ideal * x ).
    # Let H1_base be the uncompensated H1 derived from the forward pass.
    eps_inv = 1e-3 * np.max(np.abs(H1))
    G1_ideal = np.conj(H1) / (np.abs(H1) ** 2 + eps_inv**2)

    # G(x) = sum f_p * (G1_ideal * x)^p = sum (f_p * G1_ideal^p) x^p.
    G1 = f1 * G1_ideal
    G2 = f2 * (G1_ideal**2)
    G3 = f3 * (G1_ideal**3)
    G4 = f4 * (G1_ideal**4)
    G5 = f5 * (G1_ideal**5)

    G_freqs = [G1, G2, G3, G4, G5]
    kernels_time_G = []

    for p in range(P):
        G_p = G_freqs[p]
        mask_nan = np.isnan(G_p)
        G_p_clean = G_p.copy()
        G_p_clean[mask_nan] = 0.0

        import scipy.interpolate as interp
        G_func_real = interp.interp1d(sorted_freqs, G_p_clean.real, kind="linear", bounds_error=False, fill_value=(G_p_clean.real[0], 0.0))
        G_func_imag = interp.interp1d(sorted_freqs, G_p_clean.imag, kind="linear", bounds_error=False, fill_value=(0.0, 0.0))

        G_lin = G_func_real(freqs_lin) + 1j * G_func_imag(freqs_lin)
        G_lin[0] = G_lin[0].real

        # G1 low-frequency gain limiting (clamping) to prevent extreme low-frequency boost
        if p == 0:
            mag_g1 = np.abs(G_lin)
            idx_1k = np.argmin(np.abs(freqs_lin - 1000.0))
            ref_gain = mag_g1[idx_1k]
            max_allowed_gain = ref_gain * 3.16  # Limit to approx +10 dB above 1kHz gain
            over_mask = mag_g1 > max_allowed_gain
            if np.any(over_mask):
                G_lin[over_mask] = (G_lin[over_mask] / (mag_g1[over_mask] + 1e-12)) * max_allowed_gain

        # Apply smooth frequency rolloff to avoid Gibbs phenomenon
        n = p + 1
        f_lo = 20.0 * n
        f_fade_in_end = f_lo * 1.5

        f_hi = 20000.0
        f_fade_out_start = 17000.0

        # For fundamental g1, use a fixed lower fade-in to cover very low frequencies
        if n == 1:
            f_lo = 10.0
            f_fade_in_end = 20.0

        fade_mask_in = (freqs_lin >= f_lo) & (freqs_lin < f_fade_in_end)
        fade_mask_out = (freqs_lin >= f_fade_out_start) & (freqs_lin < f_hi)

        G_lin_smooth = G_lin.copy()
        if np.any(fade_mask_in) and f_fade_in_end > f_lo:
            progress_in = (freqs_lin[fade_mask_in] - f_lo) / (f_fade_in_end - f_lo)
            G_lin_smooth[fade_mask_in] *= 0.5 * (1.0 - np.cos(np.pi * progress_in))
        G_lin_smooth[freqs_lin < f_lo] = 0.0

        if np.any(fade_mask_out) and f_hi > f_fade_out_start:
            progress_out = (freqs_lin[fade_mask_out] - f_fade_out_start) / (f_hi - f_fade_out_start)
            G_lin_smooth[fade_mask_out] *= 0.5 * (1.0 + np.cos(np.pi * progress_out))
        G_lin_smooth[freqs_lin >= f_hi] = 0.0

        # Apply gate_pre delay to keep inverse kernels causal
        phase_shift = np.exp(-1j * 2 * np.pi * freqs_lin * (gate_pre / fs))
        G_lin_shifted = G_lin_smooth * phase_shift

        g_full = np.fft.irfft(G_lin_shifted, n=N_fft)
        g_cropped = g_full[:N_kernel]
        win = scipy.signal.windows.tukey(N_kernel, alpha=0.1)
        kernels_time_G.append(g_cropped * win)

    # Plot time-domain inverse kernels to check for truncation issues
    plt.figure(figsize=(10, 8))
    for p in range(P):
        plt.plot(kernels_time_G[p], label=f"g{p+1}")
    plt.title("Time Domain Impulse Response of Inverse Kernels g(t)")
    plt.xlabel("Samples")
    plt.ylabel("Amplitude")
    plt.grid(True)
    plt.legend()
    plt.tight_layout()
    plt.savefig(os.path.join(args.output_dir, "g_kernels_time_domain.png"), dpi=150)
    plt.close()

    # ---------------------------------------------------------
    # 4. Simulation Verification of F(G(x(t)))
    # ---------------------------------------------------------
    print("--- 4. Verification Simulation ---")

    # Test Signal: Sine wave at 1.0 kHz, amplitude 0.4 (within bounds)
    f0 = 1000.0
    amp_test = 0.4
    N_eval = 32768
    t_eval = np.arange(N_eval) / fs
    x_eval = amp_test * np.sin(2.0 * np.pi * f0 * t_eval)

    # Load inverse model G into PredistortionApplicator
    applicator_G = PredistortionApplicator()
    model_data_G = {
        "metadata": {
            "sample_rate": fs,
            "model_direction": "inverse",
        },
        "time_domain": {"kernels": {f"h{p + 1}": kernels_time_G[p].tolist() for p in range(P)}},
    }
    applicator_G.load_model(model_data_G)
    applicator_G.os_factor = 1  # Bypass oversampling to eliminate resample_poly transients

    # Apply predistortion filter G to test signal: y_predist(t) = G(x(t))
    applicator_G.reset_states()
    y_predist = applicator_G.apply_predistortion_block(x_eval)

    # 1. Output from uncompensated DUT: z_raw(t) = DUT(x(t))
    z_raw = dut.process(x_eval)

    # 2. Output from compensated DUT: z_comp(t) = DUT(y_predist(t)) = DUT(G(x(t)))
    z_comp = dut.process(y_predist)

    # Total delay should be around: gate_pre + measured_latency
    delay_total = gate_pre + int(np.round(measured_latency))

    # Linear gain of DUT fundamental at 1 kHz
    h1_fft = np.fft.rfft(dut.h1_true, n=N_fft)
    h1_freqs = np.fft.rfftfreq(N_fft, 1.0 / fs)
    gain_idx = np.argmin(np.abs(h1_freqs - f0))
    linear_gain = np.abs(h1_fft[gain_idx])

    # Align and normalize
    # For compensated, the target is the original input signal (flat gain 1.0)
    x_comp_target = x_eval[:-delay_total]
    # For uncompensated, the target is scaled by the DUT's linear gain
    x_raw_target = x_eval[:-delay_total] * linear_gain

    z_comp_aligned = z_comp[delay_total:]
    z_raw_aligned = z_raw[delay_total - gate_pre :]  # Uncompensated only has DUT delay
    z_raw_aligned = z_raw_aligned[: len(x_raw_target)]

    # Use only the steady-state region (excluding initial and final transient samples) to evaluate MSE & THD
    transient_margin = 2000
    x_comp_steady = x_comp_target[transient_margin:-transient_margin]
    x_raw_steady = x_raw_target[transient_margin:-transient_margin]
    z_comp_steady = z_comp_aligned[transient_margin:-transient_margin]
    z_raw_steady = z_raw_aligned[transient_margin:-transient_margin]

    mse_raw = np.mean((x_raw_steady - z_raw_steady) ** 2)
    mse_comp = np.mean((x_comp_steady - z_comp_steady) ** 2)

    # Estimate THD and obtain spectrum
    thd_raw, freqs_fft, fft_raw, harm_raw = estimate_thd_and_spectrum(z_raw_steady, fs, f0)
    thd_comp, _, fft_comp, harm_comp = estimate_thd_and_spectrum(z_comp_steady, fs, f0)

    # Debug: Check predistorted signal y_predist spectrum
    y_predist_aligned = y_predist[gate_pre:]
    y_predist_steady = y_predist_aligned[transient_margin:-transient_margin]
    thd_predist, freqs_predist, fft_predist, _ = estimate_thd_and_spectrum(y_predist_steady, fs, f0)
    print(f"[DEBUG] Predistorted signal y_predist THD (steady): {thd_predist * 100:.4f}%")
    idx_900 = np.argmin(np.abs(freqs_predist - 900.0))
    idx_1100 = np.argmin(np.abs(freqs_predist - 1100.0))
    print(f"[DEBUG] y_predist (steady) level at 900Hz: {fft_predist[idx_900]:.1f} dB, 1100Hz: {fft_predist[idx_1100]:.1f} dB")

    # Also check z_comp and z_raw level at 900Hz/1100Hz
    idx_z_900 = np.argmin(np.abs(freqs_fft - 900.0))
    idx_z_1100 = np.argmin(np.abs(freqs_fft - 1100.0))
    print(f"[DEBUG] z_comp (steady) level at 900Hz: {fft_comp[idx_z_900]:.1f} dB, 1100Hz: {fft_comp[idx_z_1100]:.1f} dB")
    print(f"[DEBUG] z_raw (steady) level at 900Hz: {fft_raw[idx_z_900]:.1f} dB, 1100Hz: {fft_raw[idx_z_1100]:.1f} dB")

    print("\nSimulation Performance Results:")
    print(f"  - Fundamental Frequency: {f0:.1f} Hz, Input Amplitude: {amp_test:.2f}")
    print(f"  - THD (Uncompensated DUT): {thd_raw * 100:.4f}%")
    print(f"  - THD (Compensated DUT):   {thd_comp * 100:.4f}%")
    thd_improvement_db = 20 * np.log10(thd_raw / thd_comp)
    print(f"  - Distortion Reduction:    {thd_improvement_db:.2f} dB")

    print(f"  - Time Domain Waveform MSE (Uncompensated): {mse_raw:.6f}")
    print(f"  - Time Domain Waveform MSE (Compensated):   {mse_comp:.6f}")
    mse_improvement_db = 10 * np.log10(mse_raw / mse_comp)
    print(f"  - Waveform Error Reduction:                 {mse_improvement_db:.2f} dB")

    # Compute fitted MSE (removing fundamental gain/phase mismatch)
    mse_raw_fit = calculate_fitted_mse(x_raw_steady, z_raw_steady, fs, f0)
    mse_comp_fit = calculate_fitted_mse(x_comp_steady, z_comp_steady, fs, f0)
    print(f"  - Distortion Waveform MSE (Uncompensated, Fitted): {mse_raw_fit:.8f}")
    print(f"  - Distortion Waveform MSE (Compensated, Fitted):   {mse_comp_fit:.8f}")
    mse_fit_improvement_db = 10 * np.log10(mse_raw_fit / mse_comp_fit)
    print(f"  - Distortion Waveform Error Reduction (Fitted):    {mse_fit_improvement_db:.2f} dB")

    # ---------------------------------------------------------
    # 5. Generate Verification Plots
    # ---------------------------------------------------------
    plt.style.use("dark_background")

    # Fig 1: Frequency response curves (Forward identified vs True)
    fig, axes = plt.subplots(2, 1, figsize=(10, 8))
    fig.suptitle("Parallel Hammerstein Forward Kernels: True vs. Identified (F)", fontsize=14, color="white")

    colors = ["#4fc3f7", "#81c784", "#ffd54f", "#ba68c8", "#e57373"]
    for p in range(P):
        # True kernel frequency response
        H_true_fft = np.fft.rfft(dut.true_kernels[p], n=N_fft)
        freqs_eval = np.fft.rfftfreq(N_fft, 1.0 / fs)

        # Mapped identified frequency response (fundamental axis)
        H_est_p = H_freqs_F[p]

        axes[0].semilogx(
            freqs_eval, 20 * np.log10(np.abs(H_true_fft) + 1e-12), linestyle="--", color=colors[p], alpha=0.6
        )
        axes[0].semilogx(sorted_freqs, 20 * np.log10(np.abs(H_est_p) + 1e-12), label=f"h{p + 1}", color=colors[p])

        axes[1].semilogx(
            freqs_eval, np.degrees(np.unwrap(np.angle(H_true_fft))), linestyle="--", color=colors[p], alpha=0.6
        )
        axes[1].semilogx(sorted_freqs, np.degrees(np.unwrap(np.angle(H_est_p))), color=colors[p])

    axes[0].set_ylabel("Magnitude (dB)")
    axes[0].set_ylim([-120, 10])
    axes[0].grid(True, which="both", alpha=0.3)
    axes[0].legend(loc="lower left")
    axes[0].set_title("Magnitude Responses (Solid: Identified, Dashed: True)")

    axes[1].set_xlabel("Frequency (Hz)")
    axes[1].set_ylabel("Phase (degrees)")
    axes[1].grid(True, which="both", alpha=0.3)
    axes[1].set_title("Phase Responses")

    plt.tight_layout()
    plt.savefig(os.path.join(args.output_dir, "forward_kernels_comparison.png"), dpi=150)
    plt.close()

    # Fig 2: Spectrum comparison at DUT output (Uncompensated vs Compensated)
    plt.figure(figsize=(10, 5))
    plt.plot(freqs_fft, fft_raw, label=f"Uncompensated DUT (THD={thd_raw * 100:.3f}%)", color="#ff7043", alpha=0.8)
    plt.plot(freqs_fft, fft_comp, label=f"Compensated DUT (THD={thd_comp * 100:.4f}%)", color="#26a69a", alpha=0.9)
    plt.xscale("log")
    plt.xlim([100, 20000])
    plt.ylim([-130, 0])
    plt.grid(True, which="both", alpha=0.3)
    plt.xlabel("Frequency (Hz)")
    plt.ylabel("Magnitude (dBFS)")
    plt.title("Output Spectrum Comparison (F(G(x))) at 1 kHz (Predistortion G Applied)")
    plt.legend(loc="upper right")
    plt.tight_layout()
    plt.savefig(os.path.join(args.output_dir, "compensated_spectrum_comparison.png"), dpi=150)
    plt.close()

    # Fig 3: Inverse kernels G_1 ~ G_5 frequency response
    plt.figure(figsize=(10, 5))
    for p in range(P):
        G_p = G_freqs[p]
        plt.semilogx(sorted_freqs, 20 * np.log10(np.abs(G_p) + 1e-12), label=f"g{p + 1} (inverse)", color=colors[p])
    plt.ylabel("Magnitude (dB)")
    plt.xlabel("Frequency (Hz)")
    plt.ylim([-120, 40])
    plt.grid(True, which="both", alpha=0.3)
    plt.title("Estimated Inverse Hammerstein Kernels (G)")
    plt.legend(loc="lower left")
    plt.tight_layout()
    plt.savefig(os.path.join(args.output_dir, "inverse_kernels_response.png"), dpi=150)
    plt.close()

    # Output raw results to standard output so that we can fetch metrics programmatically
    print("METRICS_SUMMARY:")
    print(f"  THD_RAW={thd_raw * 100:.6f}")
    print(f"  THD_COMP={thd_comp * 100:.6f}")
    print(f"  THD_IMPROVEMENT_DB={thd_improvement_db:.2f}")
    print(f"  MSE_RAW={mse_raw:.8f}")
    print(f"  MSE_COMP={mse_comp:.8f}")
    print(f"  MSE_IMPROVEMENT_DB={mse_improvement_db:.2f}")
    print(f"  MSE_RAW_FIT={mse_raw_fit:.8f}")
    print(f"  MSE_COMP_FIT={mse_comp_fit:.8f}")
    print(f"  MSE_FIT_IMPROVEMENT_DB={mse_fit_improvement_db:.2f}")


if __name__ == "__main__":
    main()
