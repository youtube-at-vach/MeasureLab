#!/usr/bin/env python3
# ruff: noqa: E402
import os
import sys
import json
import numpy as np
import matplotlib.pyplot as plt
from scipy.interpolate import interp1d

# Add project root to sys.path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Set up matplotlib style for premium look
plt.style.use('seaborn-v0_8-whitegrid' if 'seaborn-v0_8-whitegrid' in plt.style.available else 'default')
plt.rcParams.update({
    'font.size': 11,
    'axes.labelsize': 12,
    'axes.titlesize': 13,
    'xtick.labelsize': 10,
    'ytick.labelsize': 10,
    'figure.titlesize': 14,
    'grid.alpha': 0.4
})

# True nonlinear coefficients of the system
# v(t) = c1*x(t) + c2*x(t)^2 + c3*x(t)^3 + c4*x(t)^4 + c5*x(t)^5
c_true = np.array([1.0, -0.08, 0.12, -0.04, 0.06])

def get_true_H(f, use_filter=True):
    """
    Computes the true complex frequency response of the system's linear dynamic part.
    Includes a 2nd-order lowpass filter and a group delay.
    """
    if not use_filter:
        return np.ones_like(f, dtype=complex)

    fc = 15000.0   # cutoff frequency (Hz)
    Q = 0.707      # Butterworth response
    tau = 0.0012   # 1.2 ms physical delay

    w = 2.0 * np.pi * f
    wc = 2.0 * np.pi * fc
    s = 1j * w

    H_lpf = 1.0 / (1.0 + s / (Q * wc) + (s**2) / (wc**2))
    H_delay = np.exp(-1j * w * tau)
    return H_lpf * H_delay

def get_true_H_p(f, p, use_filter=True):
    """
    Computes the true complex frequency response for path p (1-indexed) in Parallel Hammerstein.
    Each nonlinear order has a distinct cutoff frequency, Q-factor, and group delay.
    """
    if not use_filter:
        return np.ones_like(f, dtype=complex)

    # Distinct physical characteristics for each order to simulate parallel path differences
    params = {
        1: {"fc": 15000.0, "Q": 0.707, "tau": 0.0012},  # 1st order (fundamental)
        2: {"fc": 10000.0, "Q": 0.5,   "tau": 0.0015},  # 2nd order
        3: {"fc": 18000.0, "Q": 1.0,   "tau": 0.0008},  # 3rd order
        4: {"fc": 8000.0,  "Q": 0.707, "tau": 0.0020},  # 4th order
        5: {"fc": 22000.0, "Q": 0.707, "tau": 0.0005}   # 5th order
    }

    cfg = params.get(p, {"fc": 15000.0, "Q": 0.707, "tau": 0.0012})
    fc = cfg["fc"]
    Q = cfg["Q"]
    tau = cfg["tau"]

    w = 2.0 * np.pi * f
    wc = 2.0 * np.pi * fc
    s = 1j * w

    H_lpf = 1.0 / (1.0 + s / (Q * wc) + (s**2) / (wc**2))
    H_delay = np.exp(-1j * w * tau)
    return H_lpf * H_delay

def generate_simulation_data(amplitudes, freqs, use_filter=True, snr_db=None, use_parallel=False):
    """
    Simulates the harmonic complex responses (Y1..Y5) under multiple excitation amplitudes.
    Can simulate either Classical Hammerstein (same filter on all paths) or
    Parallel Complex Hammerstein (distinct filters on each path).
    """
    K = len(amplitudes)
    J = len(freqs)
    P = 5

    raw_responses = np.zeros((K, J, P), dtype=complex)

    # Phase corrections corresponding to sine sweep excitation
    phase_corrections = [1.0, -1j, -1.0, 1j, 1.0]

    for k, A in enumerate(amplitudes):
        if not use_parallel:
            # Classical Hammerstein: Static nonlinearity then single shared filter H(f)
            # Calculate static nonlinear components based on Chebyshev formula
            f1_nl = c_true[0]*A + 0.75*c_true[2]*(A**3) + 0.625*c_true[4]*(A**5)
            f2_nl = 0.5*c_true[1]*(A**2) + 0.5*c_true[3]*(A**4)
            f3_nl = 0.25*c_true[2]*(A**3) + (5.0/16.0)*c_true[4]*(A**5)
            f4_nl = 0.125*c_true[3]*(A**4)
            f5_nl = (1.0/16.0)*c_true[4]*(A**5)

            # Apply the linear filter H(m*f)
            raw_responses[k, :, 0] = phase_corrections[0] * f1_nl * get_true_H(freqs, use_filter)
            raw_responses[k, :, 1] = phase_corrections[1] * f2_nl * get_true_H(2.0 * freqs, use_filter)
            raw_responses[k, :, 2] = phase_corrections[2] * f3_nl * get_true_H(3.0 * freqs, use_filter)
            raw_responses[k, :, 3] = phase_corrections[3] * f4_nl * get_true_H(4.0 * freqs, use_filter)
            raw_responses[k, :, 4] = phase_corrections[4] * f5_nl * get_true_H(5.0 * freqs, use_filter)
        else:
            # Parallel Complex Hammerstein:
            # Each power term p is filtered by a path-specific dynamic filter H_p(f).
            # The output harmonic components Y_m(f) sum the contributing dynamic terms.
            # Fundamental: H1, H3, H5
            raw_responses[k, :, 0] = phase_corrections[0] * (
                c_true[0]*A * get_true_H_p(freqs, 1, use_filter) +
                0.75*c_true[2]*(A**3) * get_true_H_p(freqs, 3, use_filter) +
                0.625*c_true[4]*(A**5) * get_true_H_p(freqs, 5, use_filter)
            )
            # 2nd Harmonic: H2, H4
            raw_responses[k, :, 1] = phase_corrections[1] * (
                0.5*c_true[1]*(A**2) * get_true_H_p(2.0 * freqs, 2, use_filter) +
                0.5*c_true[3]*(A**4) * get_true_H_p(2.0 * freqs, 4, use_filter)
            )
            # 3rd Harmonic: H3, H5
            raw_responses[k, :, 2] = phase_corrections[2] * (
                0.25*c_true[2]*(A**3) * get_true_H_p(3.0 * freqs, 3, use_filter) +
                0.3125*c_true[4]*(A**5) * get_true_H_p(3.0 * freqs, 5, use_filter)
            )
            # 4th Harmonic: H4
            raw_responses[k, :, 3] = phase_corrections[3] * (
                0.125*c_true[3]*(A**4) * get_true_H_p(4.0 * freqs, 4, use_filter)
            )
            # 5th Harmonic: H5
            raw_responses[k, :, 4] = phase_corrections[4] * (
                0.0625*c_true[4]*(A**5) * get_true_H_p(5.0 * freqs, 5, use_filter)
            )

    if snr_db is not None:
        # Add complex Gaussian noise to raw responses
        for p in range(P):
            sig_power = np.mean(np.abs(raw_responses[:, :, p])**2)
            noise_power = sig_power / (10.0**(snr_db / 10.0))
            noise_std = np.sqrt(noise_power / 2.0)

            noise = (np.random.normal(0, noise_std, size=raw_responses[:, :, p].shape) +
                     1j * np.random.normal(0, noise_std, size=raw_responses[:, :, p].shape))
            raw_responses[:, :, p] += noise

    return raw_responses

def estimate_power_kernels(amplitudes, raw_responses, freqs, max_harmonic=5):
    """
    Estimates Generalized Hammerstein power kernels H1..Hp (from original script).
    """
    P = max_harmonic
    num_amplitudes = len(amplitudes)

    # Phase corrections matching the original verification script
    phase_corrections = [1.0, 1j, -1.0, -1j, 1.0][:P]
    R_array = amplitudes
    g_scaled = np.zeros_like(raw_responses)

    for amp_idx in range(num_amplitudes):
        for p in range(P):
            val = raw_responses[amp_idx, :, p]
            g_scaled[amp_idx, :, p] = val * phase_corrections[p]

    g1 = g_scaled[:, :, 0]
    g2 = g_scaled[:, :, 1] if P >= 2 else np.zeros_like(g1)
    g3 = g_scaled[:, :, 2] if P >= 3 else np.zeros_like(g1)
    g4 = g_scaled[:, :, 3] if P >= 4 else np.zeros_like(g1)
    g5 = g_scaled[:, :, 4] if P >= 5 else np.zeros_like(g1)

    R2 = R_array**2
    R3 = R_array**3
    R4 = R_array**4
    R5 = R_array**5

    H5 = 16.0 * np.sum(g5 * R5[:, np.newaxis], axis=0) / np.sum(R_array**10) if P >= 5 else np.zeros(len(freqs), dtype=complex)
    H4 = 8.0 * np.sum(g4 * R4[:, np.newaxis], axis=0) / np.sum(R_array**8) if P >= 4 else np.zeros(len(freqs), dtype=complex)

    if P >= 5:
        g3_prime = g3 - (5.0/16.0) * H5[np.newaxis, :] * R5[:, np.newaxis]
    else:
        g3_prime = g3
    H3 = 4.0 * np.sum(g3_prime * R3[:, np.newaxis], axis=0) / np.sum(R_array**6) if P >= 3 else np.zeros(len(freqs), dtype=complex)

    if P >= 4:
        g2_prime = g2 - 0.5 * H4[np.newaxis, :] * R4[:, np.newaxis]
    else:
        g2_prime = g2
    H2 = 2.0 * np.sum(g2_prime * R2[:, np.newaxis], axis=0) / np.sum(R_array**4) if P >= 2 else np.zeros(len(freqs), dtype=complex)

    g1_prime = g1.copy()
    if P >= 3:
        g1_prime -= 0.75 * H3[np.newaxis, :] * R3[:, np.newaxis]
    if P >= 5:
        g1_prime -= 0.625 * H5[np.newaxis, :] * R5[:, np.newaxis]
    H1 = np.sum(g1_prime * R_array[:, np.newaxis], axis=0) / np.sum(R_array**2)

    H_freqs = [H1, H2, H3, H4, H5][:P]
    return H_freqs

def estimate_complex_hammerstein(amplitudes, raw_responses, freqs, max_harmonic=5):
    """
    Estimates Classical Hammerstein model with static real nonlinearity c_n and single complex filter H(f).
    Uses Alternating Least Squares (ALS) and overlap-based scaling factor estimation.
    """
    K = len(amplitudes)
    J = len(freqs)
    P = max_harmonic

    # 1. Align phase offsets to make static nonlinear functions purely real
    phase_corrections = [1.0, -1j, -1.0, 1j, 1.0][:P]
    Y_tilde = np.zeros_like(raw_responses, dtype=complex)
    for p in range(P):
        Y_tilde[:, :, p] = raw_responses[:, :, p] / phase_corrections[p]

    # 2. Extract unscaled F_m(A) and H_m(f) using Alternating Least Squares (ALS)
    F_est = np.zeros((K, P))
    H_est = np.zeros((J, P), dtype=complex)

    for p in range(P):
        m = p + 1
        # Initial guess for F_m(A) = A^m
        F_m = amplitudes ** m

        # ALS Iterations
        for _ in range(15):
            # Update H(m*omega)
            H_m = np.zeros(J, dtype=complex)
            for j in range(J):
                H_m[j] = np.sum(F_m * Y_tilde[:, j, p]) / np.sum(F_m ** 2)

            # Update F_m(A) (forcing real-value constraint)
            F_m = np.zeros(K)
            for k in range(K):
                F_m[k] = np.real(np.sum(Y_tilde[k, :, p] * np.conj(H_m))) / np.sum(np.abs(H_m)**2)

            # Normalize to avoid numerical drift
            norm = np.sqrt(np.sum(F_m ** 2))
            if norm > 1e-12:
                F_m = F_m / norm
                H_m = H_m * norm

        F_est[:, p] = F_m
        H_est[:, p] = H_m

    # 3. Align scales (alpha_m) of different harmonics by matching overlapping frequencies
    alphas = np.ones(P)
    alphas[0] = 1.0 # reference scale (fundamental H1)

    # Create polar interpolation for fundamental H1_ALS(f)
    h1_mags = np.abs(H_est[:, 0])
    h1_phases = np.unwrap(np.angle(H_est[:, 0]))

    sort_idx = np.argsort(freqs)
    f_sorted = freqs[sort_idx]
    h1_mags_sorted = h1_mags[sort_idx]
    h1_phases_sorted = h1_phases[sort_idx]

    interp_mag = interp1d(f_sorted, h1_mags_sorted, bounds_error=False, fill_value=np.nan)
    interp_phase = interp1d(f_sorted, h1_phases_sorted, bounds_error=False, fill_value=np.nan)

    def eval_h1(f):
        m_val = interp_mag(f)
        p_val = interp_phase(f)
        return m_val * np.exp(1j * p_val)

    for p in range(1, P):
        m = p + 1
        # H_est[:, p] represents H(m*f)
        # Match with fundamental H1_ALS(m*f)
        valid_freq_mask = (freqs * m <= np.max(freqs)) & (freqs * m >= np.min(freqs))
        if np.any(valid_freq_mask):
            f_eval = freqs[valid_freq_mask]
            h_m_vals = H_est[valid_freq_mask, p]
            h1_ref_vals = eval_h1(f_eval * m)

            mask = ~np.isnan(h1_ref_vals) & (np.abs(h1_ref_vals) > 1e-10)
            if np.any(mask):
                ratios = h_m_vals[mask] / h1_ref_vals[mask]
                alphas[p] = np.median(np.real(ratios))

    # Scale adjustment
    F_scaled = np.zeros_like(F_est)
    H_scaled = np.zeros_like(H_est, dtype=complex)
    for p in range(P):
        F_scaled[:, p] = F_est[:, p] * alphas[p]
        H_scaled[:, p] = H_est[:, p] / alphas[p]

    # 4. Extract polynomial coefficients c_n via Chebyshev relation inversion
    c = np.zeros(P + 1)

    # 5th harmonic
    if P >= 5:
        c[5] = 16.0 * np.sum(F_scaled[:, 4] * (amplitudes**5)) / np.sum(amplitudes**10)
    # 4th harmonic
    if P >= 4:
        c[4] = 8.0 * np.sum(F_scaled[:, 3] * (amplitudes**4)) / np.sum(amplitudes**8)
    # 3rd harmonic
    if P >= 3:
        F3_prime = F_scaled[:, 2] - (5.0/16.0) * c[5] * (amplitudes**5) if P >= 5 else F_scaled[:, 2]
        c[3] = 4.0 * np.sum(F3_prime * (amplitudes**3)) / np.sum(amplitudes**6)
    # 2nd harmonic
    if P >= 2:
        F2_prime = F_scaled[:, 1] - 0.5 * c[4] * (amplitudes**4) if P >= 4 else F_scaled[:, 1]
        c[2] = 2.0 * np.sum(F2_prime * (amplitudes**2)) / np.sum(amplitudes**4)
    # Fundamental harmonic
    F1_prime = F_scaled[:, 0]
    if P >= 3:
        F1_prime = F1_prime - 0.75 * c[3] * (amplitudes**3)
    if P >= 5:
        F1_prime = F1_prime - 0.625 * c[5] * (amplitudes**5)
    c[1] = np.sum(F1_prime * amplitudes) / np.sum(amplitudes**2)

    # Normalize such that c1 = 1.0
    c_1 = c[1]
    c_norm = c.copy()
    if np.abs(c_1) > 1e-12:
        c_norm = c / c_1

    # 5. Synthesize single unified H(f) by merging mapped frequencies of all harmonics
    all_freqs = []
    all_H_vals = []
    for p in range(P):
        m = p + 1
        all_freqs.extend(freqs * m)
        all_H_vals.extend(H_scaled[:, p] * c_1)

    all_freqs = np.array(all_freqs)
    all_H_vals = np.array(all_H_vals)

    sort_all = np.argsort(all_freqs)
    sorted_all_freqs = all_freqs[sort_all]
    sorted_all_H_vals = all_H_vals[sort_all]

    return c_norm[1:], sorted_all_freqs, sorted_all_H_vals

def predict_power_model(f0, A_in, H_freqs, sorted_freqs):
    """
    Predicts harmonic complex responses for the Generalized Hammerstein model.
    """
    H_interp = {}
    for n in range(1, 6):
        f_n = n * f0
        H_interp[n] = {}
        for p in range(1, 6):
            if p <= len(H_freqs):
                H_raw = H_freqs[p - 1]
                mask = ~np.isnan(H_raw)
                if np.sum(mask) > 1:
                    # The physical frequency axis for power term p is sorted_freqs * p
                    phys_freqs = sorted_freqs * p
                    mags = np.abs(H_raw[mask])
                    phases = np.unwrap(np.angle(H_raw[mask]))
                    mag_val = np.interp(f_n, phys_freqs[mask], mags, left=0.0, right=0.0)
                    phase_val = np.interp(f_n, phys_freqs[mask], phases, left=0.0, right=0.0)
                    H_interp[n][p] = mag_val * np.exp(1j * phase_val)
                else:
                    H_interp[n][p] = 0.0 + 0.0j
            else:
                H_interp[n][p] = 0.0 + 0.0j

    Y = {}
    Y[1] = (1.0) * (A_in * H_interp[1][1] + (0.75 * (A_in**3)) * H_interp[1][3] + (0.625 * (A_in**5)) * H_interp[1][5])
    Y[2] = (-1j) * ((0.5 * (A_in**2)) * H_interp[2][2] + (0.5 * (A_in**4)) * H_interp[2][4])
    Y[3] = (-1.0) * ((0.25 * (A_in**3)) * H_interp[3][3] + (0.3125 * (A_in**5)) * H_interp[3][5])
    Y[4] = (+1j) * ((0.125 * (A_in**4)) * H_interp[4][4])
    Y[5] = (1.0) * ((0.0625 * (A_in**5)) * H_interp[5][5])

    return [Y[1], Y[2], Y[3], Y[4], Y[5]]

def predict_complex_hammerstein(f0, A_in, c, H_synth_freqs, H_synth_vals):
    """
    Predicts harmonic complex responses for the Classical Hammerstein model.
    """
    H_interp = {}
    mags = np.abs(H_synth_vals)
    phases = np.unwrap(np.angle(H_synth_vals))

    for n in range(1, 6):
        f_n = n * f0
        mag_val = np.interp(f_n, H_synth_freqs, mags, left=0.0, right=0.0)
        phase_val = np.interp(f_n, H_synth_freqs, phases, left=0.0, right=0.0)
        H_interp[n] = mag_val * np.exp(1j * phase_val)

    Y = {}
    c1 = c[0] # which is 1.0
    c2 = c[1]
    c3 = c[2]
    c4 = c[3]
    c5 = c[4]

    Y[1] = (1.0) * (c1 * A_in + 0.75 * c3 * (A_in**3) + 0.625 * c5 * (A_in**5)) * H_interp[1]
    Y[2] = (-1j) * (0.5 * c2 * (A_in**2) + 0.5 * c4 * (A_in**4)) * H_interp[2]
    Y[3] = (-1.0) * (0.25 * c3 * (A_in**3) + (5.0/16.0) * c5 * (A_in**5)) * H_interp[3]
    Y[4] = (+1j) * (0.125 * c4 * (A_in**4)) * H_interp[4]
    Y[5] = (1.0) * ((1.0/16.0) * c5 * (A_in**5)) * H_interp[5]

    return [Y[1], Y[2], Y[3], Y[4], Y[5]]

def run_simulation_scenario(use_filter=True, snr_db=None, name="Scenario", use_parallel=False):
    print("\n==================================================")
    print(f" Running {name} ")
    print("==================================================")

    # 1. Sweep Configuration
    freqs = np.logspace(np.log10(20), np.log10(20000), 200) # 200 log-spaced points from 20Hz to 20kHz
    amplitudes = np.linspace(0.2, 0.8, 5) # 5 excitation amplitudes

    # Generate ground-truth measurement responses
    raw_responses = generate_simulation_data(amplitudes, freqs, use_filter=use_filter, snr_db=snr_db, use_parallel=use_parallel)

    # 2. Estimate Models
    # A) Power Model (Generalized Hammerstein)
    power_kernels = estimate_power_kernels(amplitudes, raw_responses, freqs, max_harmonic=5)

    # B) Complex Hammerstein Model
    c_est, H_synth_freqs, H_synth_vals = estimate_complex_hammerstein(amplitudes, raw_responses, freqs, max_harmonic=5)

    # 3. Print Non-linear Parameter Estimation Results
    print("\n[+] Nonlinear Coefficient c_n Estimation Results:")
    print(f"      True c:  {c_true[1:]}")
    print(f"      Est c:   {c_est[1:]}")
    c_err_pct = np.abs(c_est[1:] - c_true[1:]) / (np.abs(c_true[1:]) + 1e-12) * 100.0
    print(f"      Error %: {c_err_pct}")

    # 4. Predict Single Tone Response at f0 = 1000 Hz, A_in = -6 dBFS (approx 0.501)
    f0 = 1000.0
    A_in = 10.0 ** (-6.0 / 20.0)

    # Get ground-truth single tone response
    Y_true = generate_simulation_data([A_in], np.array([f0]), use_filter=use_filter, snr_db=None, use_parallel=use_parallel)[0, 0, :]

    # Predictions
    Y_pred_power = predict_power_model(f0, A_in, power_kernels, freqs)
    Y_pred_comp = predict_complex_hammerstein(f0, A_in, c_est, H_synth_freqs, H_synth_vals)

    # Compare predictions
    print(f"\n[+] Single Tone Response Prediction Error (at f0={f0}Hz, Amp={A_in:.3f}):")
    print(f"{'Harmonic':<10} | {'True Amp(dB)':<13} | {'Power Err(dB)':<13} | {'Power Err(deg)':<14} | {'Proposed Err(dB)':<16} | {'Proposed Err(deg)':<17}")
    print("-" * 90)

    metrics = []
    for h in range(5):
        m = h + 1
        true_amp_db = 20 * np.log10(np.abs(Y_true[h]) + 1e-12)

        # Power Model error
        power_amp_err = 20 * np.log10(np.abs(Y_pred_power[h]) + 1e-12) - true_amp_db
        power_phase_err = np.degrees(np.angle(Y_pred_power[h]) - np.angle(Y_true[h]))
        power_phase_err = (power_phase_err + 180) % 360 - 180

        # Proposed Model error
        comp_amp_err = 20 * np.log10(np.abs(Y_pred_comp[h]) + 1e-12) - true_amp_db
        comp_phase_err = np.degrees(np.angle(Y_pred_comp[h]) - np.angle(Y_true[h]))
        comp_phase_err = (comp_phase_err + 180) % 360 - 180

        print(f"H{m} ({m * f0 / 1000.0:.1f} kHz) | {true_amp_db:>13.2f} | {np.abs(power_amp_err):>13.4f} | {np.abs(power_phase_err):>14.3f} | {np.abs(comp_amp_err):>16.4f} | {np.abs(comp_phase_err):>17.3f}")

        metrics.append({
            "harmonic": m,
            "power_amp_err_db": np.abs(power_amp_err),
            "power_phase_err_deg": np.abs(power_phase_err),
            "comp_amp_err_db": np.abs(comp_amp_err),
            "comp_phase_err_deg": np.abs(comp_phase_err)
        })

    # Generate Plot
    fig, axes = plt.subplots(2, 1, figsize=(10, 8), sharex=True)

    # Ground Truth H(f) (Fundamental H1)
    f_plot = np.logspace(np.log10(20), np.log10(100000), 500)
    if use_parallel:
        H_true_plot = get_true_H_p(f_plot, 1, use_filter=use_filter)
        true_label = 'True $H_1(f)$'
    else:
        H_true_plot = get_true_H(f_plot, use_filter=use_filter)
        true_label = 'True $H(f)$'

    # 1. Magnitude Plot
    axes[0].plot(f_plot, 20*np.log10(np.abs(H_true_plot) + 1e-12), 'k-', label=true_label, linewidth=2)
    # Proposed synthesized H(f)
    axes[0].plot(H_synth_freqs, 20*np.log10(np.abs(H_synth_vals) + 1e-12), 'r--', label='Proposed $H(f)$ (Synthesized)', linewidth=1.5)
    # Power model H1
    axes[0].plot(freqs, 20*np.log10(np.abs(power_kernels[0]) + 1e-12), 'b:', label='Power Model $H_1(f)$', linewidth=1.5)

    if use_parallel:
        # Also plot True H3 and H5 for comparison
        H_true_3 = get_true_H_p(f_plot, 3, use_filter=use_filter)
        H_true_5 = get_true_H_p(f_plot, 5, use_filter=use_filter)
        axes[0].plot(f_plot, 20*np.log10(np.abs(H_true_3) + 1e-12), 'g--', label='True $H_3(f)$', alpha=0.5)
        axes[0].plot(f_plot, 20*np.log10(np.abs(H_true_5) + 1e-12), 'm--', label='True $H_5(f)$', alpha=0.5)

    axes[0].set_ylabel('Magnitude (dB)')
    axes[0].set_title(f'Linear Dynamic Response $H(f)$ Estimation - {name}')
    axes[0].legend(loc='lower left')
    axes[0].set_ylim([-60, 10])

    # 2. Phase Plot
    axes[1].plot(f_plot, np.degrees(np.unwrap(np.angle(H_true_plot))), 'k-', label=true_label, linewidth=2)
    axes[1].plot(H_synth_freqs, np.degrees(np.unwrap(np.angle(H_synth_vals))), 'r--', label='Proposed $H(f)$ (Synthesized)', linewidth=1.5)
    axes[1].plot(freqs, np.degrees(np.unwrap(np.angle(power_kernels[0]))), 'b:', label='Power Model $H_1(f)$', linewidth=1.5)

    if use_parallel:
        axes[1].plot(f_plot, np.degrees(np.unwrap(np.angle(H_true_3))), 'g--', label='True $H_3(f)$', alpha=0.5)
        axes[1].plot(f_plot, np.degrees(np.unwrap(np.angle(H_true_5))), 'm--', label='True $H_5(f)$', alpha=0.5)

    axes[1].set_xlabel('Frequency (Hz)')
    axes[1].set_ylabel('Phase (deg)')
    axes[1].set_xscale('log')
    axes[1].legend(loc='lower left')

    plt.tight_layout()

    # Save Plot
    artifacts_dir = os.environ.get("MEASURELAB_ARTIFACTS_DIR", "/Users/vach/.gemini/antigravity/brain/9a107ac1-c973-4185-9f83-34b1927a5ad8")
    os.makedirs(artifacts_dir, exist_ok=True)
    plot_path = os.path.join(artifacts_dir, f"hammerstein_estimation_{name.lower().replace(' ', '_')}.png")
    plt.savefig(plot_path, dpi=150)
    plt.close()

    print(f"\n[+] Saved estimation plot to {plot_path}")

    return {
        "name": name,
        "c_err_pct": c_err_pct,
        "metrics": metrics,
        "plot_path": plot_path
    }

def main():
    print("[+] Starting Complex Hammerstein Modeler Simulation...")

    # Scenario 1: Ideal Flat System, No Noise
    results_ideal = run_simulation_scenario(use_filter=False, snr_db=None, name="Ideal Flat System")

    # Scenario 2: Complex LPF and Delay System, No Noise
    results_complex = run_simulation_scenario(use_filter=True, snr_db=None, name="Complex Filter System")

    # Scenario 3: Complex LPF and Delay System with Noise (SNR = 60dB)
    results_noise = run_simulation_scenario(use_filter=True, snr_db=60.0, name="Complex Filter with Noise 60dB")

    # Scenario 4: Complex LPF and Delay System with Heavy Noise (SNR = 40dB)
    results_heavy_noise = run_simulation_scenario(use_filter=True, snr_db=40.0, name="Complex Filter with Noise 40dB")

    # Scenario 5: Parallel Complex Hammerstein System (No Noise)
    results_parallel = run_simulation_scenario(use_filter=True, snr_db=None, name="Parallel Filter System", use_parallel=True)

    # Scenario 6: Parallel Complex Hammerstein System with Noise (SNR = 60dB)
    results_parallel_noise = run_simulation_scenario(use_filter=True, snr_db=60.0, name="Parallel Filter with Noise 60dB", use_parallel=True)

    # Save summary report to JSON
    artifacts_dir = os.environ.get("MEASURELAB_ARTIFACTS_DIR", "/Users/vach/.gemini/antigravity/brain/9a107ac1-c973-4185-9f83-34b1927a5ad8")
    os.makedirs(artifacts_dir, exist_ok=True)
    report_path = os.path.join(artifacts_dir, "simulation_report.json")

    summary_report = {
        "ideal_flat": {
            "c_est_error_pct": results_ideal["c_err_pct"].tolist(),
            "pred_metrics": results_ideal["metrics"]
        },
        "complex_filter": {
            "c_est_error_pct": results_complex["c_err_pct"].tolist(),
            "pred_metrics": results_complex["metrics"]
        },
        "complex_filter_noise_60db": {
            "c_est_error_pct": results_noise["c_err_pct"].tolist(),
            "pred_metrics": results_noise["metrics"]
        },
        "complex_filter_noise_40db": {
            "c_est_error_pct": results_heavy_noise["c_err_pct"].tolist(),
            "pred_metrics": results_heavy_noise["metrics"]
        },
        "parallel_filter": {
            "c_est_error_pct": results_parallel["c_err_pct"].tolist(),
            "pred_metrics": results_parallel["metrics"]
        },
        "parallel_filter_noise_60db": {
            "c_est_error_pct": results_parallel_noise["c_err_pct"].tolist(),
            "pred_metrics": results_parallel_noise["metrics"]
        }
    }
    with open(report_path, 'w') as f:
        json.dump(summary_report, f, indent=4)
    print(f"\n[+] Saved summary report to {report_path}")

if __name__ == "__main__":
    main()
