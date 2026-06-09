import os
import json
import numpy as np
import matplotlib.pyplot as plt

def run_challenge():
    # 1. Load measured kernels and metadata
    json_path = '/Users/vach/MeasureLab/hammerstein_kernel_sample_hard_condition.json'
    if not os.path.exists(json_path):
        raise FileNotFoundError(f"Kernel file not found at {json_path}")

    with open(json_path, 'r') as f:
        raw_data = json.load(f)

    metadata = raw_data['metadata']
    sample_rate = metadata['sample_rate']
    kernels = {k: np.array(v) for k, v in raw_data['time_domain']['kernels'].items()}
    time_ms = np.array(raw_data['time_domain']['time_ms'])

    h1 = kernels['h1']
    h2 = kernels['h2']
    h3 = kernels['h3']
    h4 = kernels['h4']
    h5 = kernels['h5']
    N = len(h1)

    print("=== Loaded Hammerstein Model ===")
    print(f"Sample Rate: {sample_rate} Hz, Number of kernels: {len(kernels)}")
    print(f"Kernel Length: {N} samples ({N/sample_rate*1000.0:.2f} ms)")

    # 2. Chebyshev to Power Series Conversion
    q0 = -h2 + h4
    q1 = h1 - 3*h3 + 5*h5  # True linear dynamic response
    q2 = 2*h2 - 8*h4
    q3 = 4*h3 - 20*h5
    q4 = 8*h4
    q5 = 16*h5

    print(f"Raw kernels max abs: h1={np.max(np.abs(h1)):.2e}, h2={np.max(np.abs(h2)):.2e}, h3={np.max(np.abs(h3)):.2e}, h4={np.max(np.abs(h4)):.2e}, h5={np.max(np.abs(h5)):.2e}")
    print(f"Raw power series max abs: q1={np.max(np.abs(q1)):.2e}, q2={np.max(np.abs(q2)):.2e}, q3={np.max(np.abs(q3)):.2e}, q4={np.max(np.abs(q4)):.2e}, q5={np.max(np.abs(q5)):.2e}")

    # Normalize the system using the peak frequency response of q1
    Q1_fft = np.fft.rfft(q1)
    freqs = np.fft.rfftfreq(N, d=1.0/sample_rate)
    G_scale = np.max(np.abs(Q1_fft))
    print(f"\nLinear system normalization scale: {G_scale:.6e} ({20*np.log10(G_scale):.2f} dB)")

    # Scale all power series kernels
    q0_sc = q0 / G_scale
    q1_sc = q1 / G_scale
    q2_sc = q2 / G_scale
    q3_sc = q3 / G_scale
    q4_sc = q4 / G_scale
    q5_sc = q5 / G_scale

    # Scale original kernels for plotting
    kernels_scaled = {k: v / G_scale for k, v in kernels.items()}

    # Precompute scaled kernel FFTs
    Q0_fft = np.fft.rfft(q0_sc)
    Q1_fft = np.fft.rfft(q1_sc)
    Q2_fft = np.fft.rfft(q2_sc)
    Q3_fft = np.fft.rfft(q3_sc)
    Q4_fft = np.fft.rfft(q4_sc)
    Q5_fft = np.fft.rfft(q5_sc)

    # Define active band (60 Hz to 17 kHz)
    passband = (freqs >= 60.0) & (freqs <= 17000.0)
    bp_filter = np.zeros_like(freqs)
    bp_filter[passband] = 1.0
    # Smooth roll-off to prevent time-domain ringing
    for i in range(len(freqs)):
        f = freqs[i]
        if f < 60.0:
            bp_filter[i] = np.clip((f - 10.0) / 50.0, 0, 1)
        elif f > 17000.0 and f < 22000.0:
            bp_filter[i] = np.clip(1.0 - (f - 17000.0) / 5000.0, 0, 1)

    # 3. Design Inverse Wiener Filter for true linear response q1
    Q1_sc_power = np.abs(Q1_fft) ** 2
    beta = 0.005  # Regularization parameter
    Q1_inv = (np.conj(Q1_fft) / (Q1_sc_power + beta)) * bp_filter

    # 4. Helper functions for forward model
    def forward_model(x):
        # Output of normalized system
        y = np.zeros_like(x)
        y += np.fft.irfft(np.fft.rfft(np.ones_like(x)) * Q0_fft, n=len(x))
        y += np.fft.irfft(np.fft.rfft(x) * Q1_fft, n=len(x))
        y += np.fft.irfft(np.fft.rfft(x**2) * Q2_fft, n=len(x))
        y += np.fft.irfft(np.fft.rfft(x**3) * Q3_fft, n=len(x))
        y += np.fft.irfft(np.fft.rfft(x**4) * Q4_fft, n=len(x))
        y += np.fft.irfft(np.fft.rfft(x**5) * Q5_fft, n=len(x))
        return y

    def get_nonlinear_part(x):
        N_part = np.zeros_like(x)
        N_part += np.fft.irfft(np.fft.rfft(np.ones_like(x)) * Q0_fft, n=len(x))
        N_part += np.fft.irfft(np.fft.rfft(x**2) * Q2_fft, n=len(x))
        N_part += np.fft.irfft(np.fft.rfft(x**3) * Q3_fft, n=len(x))
        N_part += np.fft.irfft(np.fft.rfft(x**4) * Q4_fft, n=len(x))
        N_part += np.fft.irfft(np.fft.rfft(x**5) * Q5_fft, n=len(x))
        return N_part

    # 5. Method A: Contraction Mapping Predistortion
    def run_contraction_mapping(u_filt, max_iter=40, alpha=0.15):
        x_k = u_filt.copy()
        converged = False
        for _k in range(max_iter):
            N_x = get_nonlinear_part(x_k)
            # Filter feedback to avoid out-of-band noise growth
            N_x_filt = np.fft.irfft(np.fft.rfft(N_x) * bp_filter, n=N)
            corr = np.fft.irfft(np.fft.rfft(N_x_filt) * Q1_inv, n=N)

            x_k_next = (1.0 - alpha) * x_k + alpha * (u_filt - corr)
            x_k_next = np.clip(x_k_next, -1.05, 1.05) # Bound protection

            diff = np.max(np.abs(x_k_next - x_k))
            x_k = x_k_next
            if diff < 1e-6:
                converged = True
                break
        return x_k, converged, _k+1

    # 6. Method B: Indirect Learning Architecture (ILA)
    # To identify W_p(f) robustly, we use band-limited WHITE NOISE as training signals
    # this ensures all frequencies in the passband are excited.
    print("\n--- Training ILA Inverse Model ---")
    training_amps = np.linspace(0.01, 0.5, 15)

    N_fft_half = N // 2 + 1
    X_train_fft = []
    Y_powers_fft = {p: [] for p in [1, 2, 3, 4, 5]}

    # Seed generator for reproducibility
    rng = np.random.default_rng(42)

    for amp in training_amps:
        # Generate white noise
        raw_noise = rng.normal(0.0, 1.0, N)
        # Band-limit to passband
        noise_filt = np.fft.irfft(np.fft.rfft(raw_noise) * bp_filter, n=N)
        # Normalize peak amplitude to amp
        peak = np.max(np.abs(noise_filt))
        if peak > 1e-12:
            noise_filt = (noise_filt / peak) * amp

        x_in = noise_filt
        y_out = forward_model(x_in)

        X_train_fft.append(np.fft.rfft(x_in))
        for p in [1, 2, 3, 4, 5]:
            Y_powers_fft[p].append(np.fft.rfft(y_out**p))

    X_train_fft = np.array(X_train_fft)
    for p in [1, 2, 3, 4, 5]:
        Y_powers_fft[p] = np.array(Y_powers_fft[p])

    W_filters = np.zeros((5, N_fft_half), dtype=complex)

    for fi in range(N_fft_half):
        if not passband[fi]:
            W_filters[:, fi] = 0.0
            continue

        # Fix linear inverse filter to the robustly designed Q1_inv
        W_filters[0, fi] = Q1_inv[fi]

        # Build matrix A_high for higher orders 2 to 5 (shape: len(training_amps), 4)
        A_high = np.zeros((len(training_amps), 4), dtype=complex)
        for p_idx, p in enumerate([2, 3, 4, 5]):
            A_high[:, p_idx] = Y_powers_fft[p][:, fi]

        # target is the residual: b - A_linear * Q1_inv
        A_linear = Y_powers_fft[1][:, fi]
        b = X_train_fft[:, fi]
        b_res = b - A_linear * Q1_inv[fi]

        # Weighted Least Squares (WLS) for the high-order residual system
        weights = 1.0 / training_amps
        A_weighted = A_high * weights[:, np.newaxis]
        b_weighted = b_res * weights

        # Form normal equations for weighted residual system
        AH_A = np.conj(A_weighted.T) @ A_weighted
        AH_b = np.conj(A_weighted.T) @ b_weighted

        # Regularization for high orders (2 to 5) to prevent explosion
        # Heavily penalize even orders (2, 4) to 1e2 because the system is strongly odd-order dominant,
        # preventing collinear over-fitting of tiny even-order terms.
        lambdas = np.array([1e2, 1e-1, 1e2, 1e-1])

        # Solve normal equations: (A^H * A + diag(lambdas)) * W_high = A^H * b
        try:
            W_high = np.linalg.solve(AH_A + np.diag(lambdas), AH_b)
        except np.linalg.LinAlgError:
            W_high = np.linalg.lstsq(AH_A + np.diag(lambdas), AH_b, rcond=1e-4)[0]

        W_filters[1:, fi] = W_high

    # Apply Time-Domain Windowing to smooth identified high-order filters (Order 2 to 5)
    # This prevents time-domain aliasing caused by bin-independent numerical fluctuations.
    win = np.ones(N)
    N_keep = N // 4
    N_fade = N // 4
    fade = 0.5 * (1.0 + np.cos(np.pi * np.arange(N_fade) / N_fade))
    win[N_keep : N_keep + N_fade] = fade
    win[N_keep + N_fade :] = 0.0

    for p_idx in range(1, 5):
        w_time = np.fft.irfft(W_filters[p_idx], n=N)
        w_time_win = w_time * win
        W_filters[p_idx] = np.fft.rfft(w_time_win)

    print(f"Q1_inv max abs: {np.max(np.abs(Q1_inv)):.2e}")
    print("\nILA W_filters max abs per order:")
    for p_idx in range(5):
        print(f"  Order {p_idx+1}: max={np.max(np.abs(W_filters[p_idx])):.2e}, mean={np.mean(np.abs(W_filters[p_idx])):.2e}")

    def apply_ila_predistortion(u_val):
        x_pred = np.zeros_like(u_val)

        # Linear inverse (Order 1) is always applied
        u_pow_fft = np.fft.rfft(u_val)
        x_pred += np.fft.irfft(u_pow_fft * W_filters[0], n=len(u_val))

        # High-order non-linear terms (Order 2 to 5) with smooth fade-in
        amp_peak = np.max(np.abs(u_val))
        if amp_peak > 0.05:
            # Smooth fade factor from 0.0 to 1.0 between amp 0.05 and 0.15
            fade = np.clip((amp_peak - 0.05) / 0.10, 0.0, 1.0)

            x_high = np.zeros_like(u_val)
            for p_idx, p in enumerate([2, 3, 4, 5], start=1):
                up_val = u_val**p
                W_p = W_filters[p_idx]
                x_high += np.fft.irfft(np.fft.rfft(up_val) * W_p, n=len(u_val))

            x_pred += fade * x_high

        return np.clip(x_pred, -1.05, 1.05)

    # 7. Verification Sweeps
    test_amplitudes = np.linspace(0.01, 0.6, 20)
    cm_reductions = []
    ila_reductions = []
    cm_converged = []

    t = np.arange(N) / sample_rate
    u_test = np.sin(2 * np.pi * 1000.0 * t)

    print("\n--- Verification Sweep ---")
    for amp in test_amplitudes:
        u_amp = amp * u_test
        u_amp_filt = np.fft.irfft(np.fft.rfft(u_amp) * bp_filter, n=N)

        # Raw Output
        y_raw = forward_model(u_amp_filt)

        # Target linear response regularized by beta (so both raw and ila have matching LTI constraints)
        Q1_fft_reg = Q1_fft * (np.conj(Q1_fft) / (Q1_sc_power + beta))
        y_target = np.fft.irfft(np.fft.rfft(u_amp_filt) * Q1_fft_reg, n=N)

        # Filter both to active band to compute distortion
        y_raw_bp = np.fft.irfft(np.fft.rfft(y_raw) * bp_filter, n=N)
        y_target_bp = np.fft.irfft(np.fft.rfft(y_target) * bp_filter, n=N)
        dist_raw = y_raw_bp - y_target_bp
        power_raw = np.sum(dist_raw**2)

        # Method A: Contraction Mapping
        x_cm, converged_cm, iters = run_contraction_mapping(u_amp_filt)
        cm_converged.append(converged_cm)
        if converged_cm and not np.isnan(x_cm).any():
            y_cm = forward_model(x_cm)
            y_cm_bp = np.fft.irfft(np.fft.rfft(y_cm) * bp_filter, n=N)
            dist_cm = y_cm_bp - y_target_bp
            power_cm = np.sum(dist_cm**2)
            red_cm = 10 * np.log10(power_raw / (power_cm + 1e-20))
            cm_reductions.append(max(0.0, red_cm))
        else:
            cm_reductions.append(0.0)

        # Method B: ILA
        x_ila = apply_ila_predistortion(y_target)
        red_ila = -999.0
        if not np.isnan(x_ila).any():
            y_ila = forward_model(x_ila)
            y_ila_bp = np.fft.irfft(np.fft.rfft(y_ila) * bp_filter, n=N)
            dist_ila = y_ila_bp - y_target_bp
            power_ila = np.sum(dist_ila**2)
            red_ila = 10 * np.log10(power_raw / (power_ila + 1e-20))
            ila_reductions.append(max(0.0, red_ila))
        else:
            ila_reductions.append(0.0)

        print(f"Amp {amp:.2f} | CM: {'OK' if converged_cm else 'FAIL'} ({cm_reductions[-1]:.2f} dB) | ILA: {red_ila:.2f} dB (x_ila min/max: {np.min(x_ila):.3f}/{np.max(x_ila):.3f})")

    # 8. Detailed Waveform and Spectrum Analysis at Amp 0.08
    target_amp = 0.08
    u_amp = target_amp * u_test
    u_amp_filt = np.fft.irfft(np.fft.rfft(u_amp) * bp_filter, n=N)

    y_raw = forward_model(u_amp_filt)
    y_target = np.fft.irfft(np.fft.rfft(u_amp_filt) * Q1_fft, n=N)

    x_cm, _, _ = run_contraction_mapping(u_amp_filt)
    y_cm = forward_model(x_cm)

    x_ila = apply_ila_predistortion(y_target)
    y_ila = forward_model(x_ila)

    # FFT for Spectrum Comparison
    fft_len = N
    f_axis = np.fft.rfftfreq(fft_len, d=1.0/sample_rate)

    Y_target_mag = 20 * np.log10(np.abs(np.fft.rfft(y_target, n=fft_len)) + 1e-12)
    Y_raw_mag = 20 * np.log10(np.abs(np.fft.rfft(y_raw, n=fft_len)) + 1e-12)
    Y_cm_mag = 20 * np.log10(np.abs(np.fft.rfft(y_cm, n=fft_len)) + 1e-12)
    Y_ila_mag = 20 * np.log10(np.abs(np.fft.rfft(y_ila, n=fft_len)) + 1e-12)

    # 9. Plot Results and Save
    plt.figure(figsize=(15, 10))

    # Subplot 1: Distortion Reduction Comparison Curve
    plt.subplot(2, 2, 1)
    plt.plot(test_amplitudes, cm_reductions, 'o-', color='#1f77b4', linewidth=2.5, label='Contraction Mapping (Fixed Point)')
    plt.plot(test_amplitudes, ila_reductions, 's--', color='#ff7f0e', linewidth=2.5, label='ILA Inverse Filter')
    plt.axvline(0.1, color='red', linestyle=':', label='Contraction Mapping Convergence Limit (~0.1)')
    plt.title('Distortion Reduction vs. Input Amplitude', fontsize=12, fontweight='bold')
    plt.xlabel('Input Amplitude (Peak)', fontsize=10)
    plt.ylabel('Distortion Suppression (dB)', fontsize=10)
    plt.grid(True, which='both', linestyle='--', alpha=0.5)
    plt.legend()

    # Subplot 2: Spectrum comparison at target_amp
    plt.subplot(2, 2, 2)
    plt.plot(f_axis, Y_raw_mag, color='#d62728', alpha=0.7, label='Raw Output (Uncompensated)')
    plt.plot(f_axis, Y_cm_mag, color='#1f77b4', linewidth=1.5, label='Linearized Output (Contraction Mapping)')
    plt.plot(f_axis, Y_ila_mag, color='#ff7f0e', linewidth=1.5, label='Linearized Output (ILA)')
    plt.plot(f_axis, Y_target_mag, color='black', linestyle=':', label='Target Linear Output')
    plt.xlim(200, 10000) # zoom around harmonics
    plt.ylim(-110, -20)
    plt.title(f'Output Spectrum Zoom at Amp = {target_amp} (1kHz Sinusoid)', fontsize=12, fontweight='bold')
    plt.xlabel('Frequency (Hz)', fontsize=10)
    plt.ylabel('Magnitude (dBFS)', fontsize=10)
    plt.grid(True, which='both', linestyle='--', alpha=0.5)
    plt.legend()

    # Subplot 3: Time Domain Residual Error comparison
    plt.subplot(2, 2, 3)
    t_ms = t * 1000.0
    err_raw = y_raw - y_target
    err_cm = y_cm - y_target
    err_ila = y_ila - y_target
    plt.plot(t_ms, err_raw, color='#d62728', alpha=0.7, label='Raw Error')
    plt.plot(t_ms, err_cm, color='#1f77b4', label='CM Residual Error')
    plt.plot(t_ms, err_ila, color='#ff7f0e', label='ILA Residual Error')
    plt.xlim(10, 15) # Show a few cycles
    plt.title('Time Domain Residual Error (Output - Linear Target)', fontsize=12, fontweight='bold')
    plt.xlabel('Time (ms)', fontsize=10)
    plt.ylabel('Amplitude Error', fontsize=10)
    plt.grid(True, which='both', linestyle='--', alpha=0.5)
    plt.legend()

    # Subplot 4: High Order Kernel Shapes
    plt.subplot(2, 2, 4)
    plt.plot(time_ms, kernels_scaled['h1'], label='Linear h1 (scaled)')
    plt.plot(time_ms, kernels_scaled['h3'] * 10, label='h3 * 10 (scaled)')
    plt.plot(time_ms, kernels_scaled['h5'] * 10, label='h5 * 10 (scaled)')
    plt.title('System Impulse Response Kernels (Scaled)', fontsize=12, fontweight='bold')
    plt.xlabel('Time (ms)', fontsize=10)
    plt.ylabel('Amplitude', fontsize=10)
    plt.grid(True, which='both', linestyle='--', alpha=0.5)
    plt.legend()

    plt.tight_layout()

    # Output path
    output_dir = '/Users/vach/.gemini/antigravity/brain/ff99426b-f8d0-4184-aa91-50d5a4924d04'
    os.makedirs(output_dir, exist_ok=True)
    output_img_path = os.path.join(output_dir, 'linearization_results.png')

    plt.savefig(output_img_path, dpi=150)
    plt.close()
    print(f"\nSuccessfully generated comparison plot at: {output_img_path}")

if __name__ == '__main__':
    run_challenge()
