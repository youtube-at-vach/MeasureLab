import os
import json
import numpy as np
import matplotlib.pyplot as plt
from scipy.signal import windows, fftconvolve


def run_closed_loop_training():
    # 1. Load measured kernels and metadata
    json_path = "/Users/vach/MeasureLab/hammerstein_kernel_sample_soft_condition.json"
    if not os.path.exists(json_path):
        raise FileNotFoundError(f"Kernel file not found at {json_path}")

    with open(json_path, "r") as f:
        raw_data = json.load(f)

    metadata = raw_data["metadata"]
    sample_rate = metadata["sample_rate"]
    kernels = {k: np.array(v) for k, v in raw_data["time_domain"]["kernels"].items()}
    time_ms = np.array(raw_data["time_domain"]["time_ms"])

    h1 = kernels["h1"]
    h2 = kernels["h2"]
    h3 = kernels["h3"]
    h4 = kernels["h4"]
    h5 = kernels["h5"]
    N = len(h1)

    print("=== Loaded Target Nonlinear System (F) ===")
    print(f"Sample Rate: {sample_rate} Hz")
    print(f"Kernel Length: {N} samples ({N / sample_rate * 1000.0:.2f} ms)")

    # 2. Chebyshev to Power Series Conversion for the Forward Simulator F
    q0 = -h2 + h4
    q1 = h1 - 3 * h3 + 5 * h5  # True linear dynamic response
    q2 = 2 * h2 - 8 * h4
    q3 = 4 * h3 - 20 * h5
    q4 = 8 * h4
    q5 = 16 * h5

    # Scale the system using the peak frequency response of q1
    Q1_fft_raw = np.fft.rfft(q1)
    G_scale = np.max(np.abs(Q1_fft_raw))
    print(f"Linear system scale factor: {G_scale:.6e}")

    # Scaled Forward Power Series Kernels
    q0_sc = q0 / G_scale
    q1_sc = q1 / G_scale
    q2_sc = q2 / G_scale
    q3_sc = q3 / G_scale
    q4_sc = q4 / G_scale
    q5_sc = q5 / G_scale

    Q0_fft = np.fft.rfft(q0_sc)
    Q1_fft = np.fft.rfft(q1_sc)
    Q2_fft = np.fft.rfft(q2_sc)
    Q3_fft = np.fft.rfft(q3_sc)
    Q4_fft = np.fft.rfft(q4_sc)
    Q5_fft = np.fft.rfft(q5_sc)

    # 3. Define the active band filter (60 Hz to 17 kHz)
    freqs = np.fft.rfftfreq(N, d=1.0 / sample_rate)
    passband = (freqs >= 60.0) & (freqs <= 17000.0)
    bp_filter = np.zeros_like(freqs)
    bp_filter[passband] = 1.0
    for i in range(len(freqs)):
        f = freqs[i]
        if f < 60.0:
            # Smooth cosine fade-in
            bp_filter[i] = np.clip(0.5 * (1.0 - np.cos(np.pi * (f - 10.0) / 50.0)) if f >= 10.0 else 0.0, 0, 1)
        elif f > 17000.0:
            if f < 22000.0:
                # Smooth cosine roll-off to minimize edge ripples (Gibbs phenomenon)
                bp_filter[i] = np.clip(0.5 * (1.0 + np.cos(np.pi * (f - 17000.0) / 5000.0)), 0, 1)
            else:
                bp_filter[i] = 0.0

    # Anti-aliasing oversampled power evaluation in frequency domain
    def power_oversampled_fft(x, p, L=8):
        if p == 1:
            return np.fft.rfft(x)
        N_x = len(x)
        X = np.fft.rfft(x)
        N_up = L * N_x
        X_up = np.zeros(N_up // 2 + 1, dtype=complex)
        X_up[: len(X)] = X * L
        x_up = np.fft.irfft(X_up, n=N_up)

        xp_up = x_up**p

        Xp_up = np.fft.rfft(xp_up)
        Xp = Xp_up[: N_x // 2 + 1] / L
        return Xp

    # Forward model F simulator
    def forward_model(x):
        y = np.zeros_like(x)
        # Power series summation in frequency domain with oversampling
        y += np.fft.irfft(np.fft.rfft(np.ones_like(x)) * Q0_fft, n=len(x))
        y += np.fft.irfft(power_oversampled_fft(x, 1) * Q1_fft, n=len(x))
        y += np.fft.irfft(power_oversampled_fft(x, 2) * Q2_fft, n=len(x))
        y += np.fft.irfft(power_oversampled_fft(x, 3) * Q3_fft, n=len(x))
        y += np.fft.irfft(power_oversampled_fft(x, 4) * Q4_fft, n=len(x))
        y += np.fft.irfft(power_oversampled_fft(x, 5) * Q5_fft, n=len(x))
        return y

    # 4. SSS Generation
    sweep_duration = N / sample_rate
    start_freq = 60.0
    end_freq = 17000.0

    # Tukey window to minimize transient clicks
    tukey_win = windows.tukey(N, alpha=0.02)

    # Generate log sweep
    t = np.linspace(0, sweep_duration, N, endpoint=False)
    start_margin = max(2.0, start_freq / 1.3)
    nyquist = sample_rate / 2.0
    end_margin = min(nyquist * 0.95, end_freq * 1.15)
    w1 = 2 * np.pi * start_margin
    T = sweep_duration
    L_param = np.log(end_margin / start_margin)

    phase = (w1 * T / L_param) * (np.exp(t * L_param / T) - 1)
    sss_signal = np.sin(phase) * tukey_win

    # Analytical inverse filter
    inv_envelope = np.exp(t * L_param / T)
    inverse_filter = inv_envelope * np.sin(phase) * tukey_win
    inverse_filter = np.flip(inverse_filter)

    # Normalize inverse filter
    direct_conv = fftconvolve(sss_signal, inverse_filter, mode="full")
    peak = np.max(np.abs(direct_conv))
    if peak > 1e-12:
        inverse_filter /= peak

    # Regularized deconvolution helper
    def deconvolve_signal(recorded, regularization=1e-4):
        # Circular deconvolution of length N (since simulation uses circular convolution)
        S = np.fft.rfft(sss_signal)
        Y = np.fft.rfft(recorded)
        S_power = np.abs(S) ** 2
        epsilon = regularization * np.max(S_power) + 1e-12
        H = (Y * np.conj(S)) / (S_power + epsilon)
        return np.fft.irfft(H, n=N)

    # 5. Cascade SSS Measurement
    # Measure the parallel kernels T_1 to T_5 of the cascade T = F o G
    gate_pre = int(0.01 * sample_rate)
    gate_post = int(0.02 * sample_rate)
    N_kernel = gate_pre + gate_post
    L_sweep = sweep_duration / np.log(end_margin / start_margin)

    # Track total sweep counts to compare efficiency
    global total_measured_sweeps
    total_measured_sweeps = 0

    def apply_phase_correction_and_frac_delay(g_k, k, frac_delay):
        N_k = len(g_k)
        G = np.fft.rfft(g_k)
        if k == 2:
            G = G * 1j
        elif k == 3:
            G = -G
        elif k == 4:
            G = G * (-1j)
        if np.abs(frac_delay) > 1e-9:
            freqs_k = np.fft.rfftfreq(N_k, d=1.0 / sample_rate)
            phase_shift = np.exp(1j * 2 * np.pi * freqs_k * frac_delay / sample_rate)
            G = G * phase_shift
        return np.fft.irfft(G, n=N_k)

    def measure_cascade_kernels(G_fft, amplitudes):
        global total_measured_sweeps
        num_amps = len(amplitudes)
        responses_meas = []
        clip_triggered = False

        # Run measurement sweeps for each amplitude
        for amp in amplitudes:
            s_A = amp * sss_signal
            total_measured_sweeps += 1

            # Generate predistorted signal in frequency domain with oversampling
            u_A = np.zeros(N)
            for p in range(1, 6):
                S_A_p_fft = power_oversampled_fft(s_A, p)
                U_p_fft = S_A_p_fft * G_fft[p - 1]
                u_A += np.fft.irfft(U_p_fft, n=N)

            # Check for safety clipping threshold
            if np.any(np.abs(u_A) >= 1.49):
                clip_triggered = True

            # Clip input to prevent damage/explosion (protection limit)
            u_A = np.clip(u_A, -1.5, 1.5)

            # Feed into F
            y_A = forward_model(u_A)

            # Deconvolve y_A using flat inverse filter
            ir_A = deconvolve_signal(y_A)
            responses_meas.append(ir_A)

        # 0. Find the peak of the fundamental response using the maximum amplitude step
        ref_step_idx = num_amps - 1
        base_align_sig = responses_meas[ref_step_idx]
        t1_idx = np.argmax(np.abs(base_align_sig))
        aligned_meas = responses_meas

        # 1. Slice harmonic impulse responses
        N_total = len(base_align_sig)
        g_meas_all = np.zeros((num_amps, 5, N_kernel))
        for j in range(num_amps):
            ir_meas_raw = aligned_meas[j]
            for k in range(1, 6):
                t_k_exact = t1_idx - L_sweep * np.log(k) * sample_rate
                t_k = int(np.round(t_k_exact))
                frac_delay = t_k_exact - t_k
                idx = (np.arange(t_k - gate_pre, t_k + gate_post)) % N_total
                win = windows.tukey(N_kernel, alpha=0.1)
                g_k_meas = ir_meas_raw[idx] * win
                g_k_meas_corr = apply_phase_correction_and_frac_delay(g_k_meas, k, frac_delay)
                g_meas_all[j, k - 1] = g_k_meas_corr

        # 2. Chebyshev least-squares in frequency domain
        N_fft_half = N_kernel // 2 + 1
        G_meas_k = {}
        for k in range(1, 6):
            g_m_k_fft = np.empty((num_amps, N_fft_half), dtype=complex)
            for j in range(num_amps):
                g_m_k_fft[j] = np.fft.rfft(g_meas_all[j, k - 1])
            G_meas_k[k] = g_m_k_fft

        # Solve power series cascade kernels T_p(f)
        R_array = np.array(amplitudes)
        R2 = R_array**2
        R3 = R_array**3
        R4 = R_array**4
        R5 = R_array**5

        T_list = np.zeros((5, N_fft_half), dtype=complex)

        g5_m = G_meas_k.get(5, np.zeros((num_amps, N_fft_half), dtype=complex))
        T_list[4] = 16 * np.sum(g5_m * R5[:, np.newaxis], axis=0) / np.sum(R_array**10)

        g4_m = G_meas_k.get(4, np.zeros((num_amps, N_fft_half), dtype=complex))
        T_list[3] = 8 * np.sum(g4_m * R4[:, np.newaxis], axis=0) / np.sum(R_array**8)

        g3_m = G_meas_k.get(3, np.zeros((num_amps, N_fft_half), dtype=complex))
        g3_prime_m = g3_m - (5 / 16) * T_list[4][np.newaxis, :] * R5[:, np.newaxis]
        T_list[2] = 4 * np.sum(g3_prime_m * R3[:, np.newaxis], axis=0) / np.sum(R_array**6)

        g2_m = G_meas_k.get(2, np.zeros((num_amps, N_fft_half), dtype=complex))
        g2_prime_m = g2_m - 0.5 * T_list[3][np.newaxis, :] * R4[:, np.newaxis]
        T_list[1] = 2 * np.sum(g2_prime_m * R2[:, np.newaxis], axis=0) / np.sum(R_array**4)

        g1_m = G_meas_k.get(1, np.zeros((num_amps, N_fft_half), dtype=complex))
        g1_prime_m = (
            g1_m
            - 0.75 * T_list[2][np.newaxis, :] * R3[:, np.newaxis]
            - 0.625 * T_list[4][np.newaxis, :] * R5[:, np.newaxis]
        )
        T_list[0] = np.sum(g1_prime_m * R_array[:, np.newaxis], axis=0) / np.sum(R2)

        # Convert back to time-domain to pad to length N
        T_time = []
        for p in range(5):
            t_p = np.fft.irfft(T_list[p], n=N_kernel)
            t_p_aligned = np.roll(t_p, -gate_pre)
            if len(t_p_aligned) < N:
                t_p_full = np.pad(t_p_aligned, (0, N - len(t_p_aligned)))
            else:
                t_p_full = t_p_aligned[:N]
            T_time.append(t_p_full)

        return T_time, clip_triggered

    # [NEW] Single-Amplitude Algebraic Kernel Extraction (SAAKE)
    def measure_single_amplitude_kernels(G_fft, amp):
        global total_measured_sweeps
        s_A = amp * sss_signal
        total_measured_sweeps += 1

        # Generate predistorted signal in frequency domain with oversampling
        u_A = np.zeros(N)
        for p in range(1, 6):
            S_A_p_fft = power_oversampled_fft(s_A, p)
            U_p_fft = S_A_p_fft * G_fft[p - 1]
            u_A += np.fft.irfft(U_p_fft, n=N)

        # Check for safety clipping threshold
        clip_triggered = np.any(np.abs(u_A) >= 1.49)
        u_A = np.clip(u_A, -1.5, 1.5)

        # Feed into F
        y_A = forward_model(u_A)

        # Deconvolve using flat inverse filter
        ir_A = deconvolve_signal(y_A)

        # Slice harmonic impulse responses
        t1_idx = np.argmax(np.abs(ir_A))
        N_total = len(ir_A)
        g_meas = np.zeros((5, N_kernel))

        for k in range(1, 6):
            t_k_exact = t1_idx - L_sweep * np.log(k) * sample_rate
            t_k = int(np.round(t_k_exact))
            frac_delay = t_k_exact - t_k
            idx = (np.arange(t_k - gate_pre, t_k + gate_post)) % N_total
            win = windows.tukey(N_kernel, alpha=0.1)
            g_k_meas = ir_A[idx] * win
            g_k_meas_corr = apply_phase_correction_and_frac_delay(g_k_meas, k, frac_delay)
            g_meas[k - 1] = g_k_meas_corr

        # RFFT of the sliced responses
        N_fft_half = N_kernel // 2 + 1
        Y = np.zeros((5, N_fft_half), dtype=complex)
        for p in range(5):
            Y[p] = np.fft.rfft(g_meas[p])

        # Solve power series cascade kernels T_p(f) algebraically from single amplitude
        # Formula derived from Chebyshev decomposition relationships:
        T_list = np.zeros((5, N_fft_half), dtype=complex)

        # T5 = 16 * Y5 / A^5
        T_list[4] = 16 * Y[4] / (amp**5)
        # T4 = 8 * Y4 / A^4
        T_list[3] = 8 * Y[3] / (amp**4)
        # T3 = 4 * (Y3 - 5/16 * T5 * A^5) / A^3 = 4 * (Y3 - 5 * Y5) / A^3
        T_list[2] = 4 * (Y[2] - 5 * Y[4]) / (amp**3)
        # T2 = 2 * (Y2 - 1/2 * T4 * A^4) / A^2 = 2 * (Y2 - 4 * Y4) / A^2
        T_list[1] = 2 * (Y[1] - 4 * Y[3]) / (amp**2)
        # T1 = (Y1 - 3/4 * T3 * A^3 - 5/8 * T5 * A^5) / A = (Y1 - 3 * Y3 + 5 * Y5) / A
        T_list[0] = (Y[0] - 3 * Y[2] + 5 * Y[4]) / amp

        # Convert back to time-domain to pad to length N
        T_time = []
        for p in range(5):
            t_p = np.fft.irfft(T_list[p], n=N_kernel)
            t_p_aligned = np.roll(t_p, -gate_pre)
            if len(t_p_aligned) < N:
                t_p_full = np.pad(t_p_aligned, (0, N - len(t_p_aligned)))
            else:
                t_p_full = t_p_aligned[:N]
            T_time.append(t_p_full)

        return T_time, clip_triggered

    # 6. Initialize G kernels
    N_fft_half_full = N // 2 + 1
    Q1_sc_power = np.abs(Q1_fft) ** 2
    beta = 0.005
    # Define delay parameters
    delay_tau = gate_pre / sample_rate  # 10 ms = 0.01 s
    delay_2tau = 2.0 * delay_tau  # 20 ms = 0.02 s

    # Initial G1 is the linear inverse with 2*tau delay for causality
    phase_shift_2tau = np.exp(-1j * 2 * np.pi * freqs * delay_2tau)
    G1_init_fft = (np.conj(Q1_fft) / (Q1_sc_power + beta)) * bp_filter * phase_shift_2tau

    G_fft = np.zeros((5, N_fft_half_full), dtype=complex)
    G_fft[0] = G1_init_fft  # G1

    # 7. Hybrid Optimization Loop
    # Amplitudes for the Chebyshev decomposition measurement
    a_amp, b_amp = 0.03, 0.30
    K_amp = 10
    k_arr = np.arange(1, K_amp + 1)
    cheb_nodes = 0.5 * (a_amp + b_amp) + 0.5 * (b_amp - a_amp) * np.cos((2 * k_arr - 1) / (2 * K_amp) * np.pi)
    measurement_amplitudes = np.sort(cheb_nodes)

    # Keep track of error suppression
    history_err_db = []

    # Target system linear response (Q1_fft within passband)
    H_target = Q1_fft * bp_filter

    # Precompute denominator for stability
    F_lin_abs = np.abs(Q1_fft)
    eps_in = 1e-6
    eps_out = 0.5
    eps_f = eps_in + (eps_out - eps_in) * (1.0 - bp_filter)
    F_inv = np.conj(Q1_fft) / (F_lin_abs**2 + eps_f)

    # Window for predistorter time-domain regularization
    center_idx = gate_pre  # Fixed: center at gate_pre (1920 samples) instead of 2 * gate_pre to align with predistorter peak
    N_keep = N // 3
    N_fade = N // 6

    win_centered = np.zeros(N)
    # Causal part
    win_centered[:N_keep] = 1.0
    fade_shape = 0.5 * (1.0 + np.cos(np.pi * np.arange(N_fade) / N_fade))
    win_centered[N_keep : N_keep + N_fade] = fade_shape
    # Anti-causal part
    win_centered[-N_keep:] = 1.0
    win_centered[-N_keep - N_fade : -N_keep] = np.flip(fade_shape)

    g_win = np.roll(win_centered, center_idx)

    # Initial calibration measurement
    print("\n--- Running Initial Calibration Measurement (Using 10-sweep SSS) ---")
    T_time_init, _ = measure_cascade_kernels(G_fft, measurement_amplitudes)
    T_fft_init = [np.fft.rfft(T_time_init[p]) for p in range(5)]

    C_fft = []
    # C1 calibration
    C1 = np.ones_like(Q1_fft)
    idx_cal = np.abs(T_fft_init[0]) > 1e-4
    C1[idx_cal] = Q1_fft[idx_cal] / T_fft_init[0][idx_cal]
    C_fft.append(C1)

    # C2 to C5 calibration
    Q_ffts = [Q1_fft, Q2_fft, Q3_fft, Q4_fft, Q5_fft]
    for p in range(1, 5):
        Cp = np.ones_like(Q_ffts[p])
        idx_p = np.abs(T_fft_init[p]) > 1e-6
        Cp[idx_p] = Q_ffts[p][idx_p] / T_fft_init[p][idx_p]
        # Cp = Cp * bp_filter + (1.0 - bp_filter)  # Fixed: Commented out to prevent Cp from transitioning to 1.0 (0 dB) in the transition band
        C_fft.append(Cp)

    # Evaluate Initial State Error
    T_time = T_time_init
    T_fft = [np.fft.rfft(T_time[p]) for p in range(5)]
    E_fft = []
    T1_cal = T_fft[0] * C_fft[0]
    E_fft.append((T1_cal - Q1_fft) * bp_filter)  # Fixed: target Q1_fft directly instead of H_target

    for p in range(1, 5):
        Tp_cal = T_fft[p] * C_fft[p]
        E_fft.append(Tp_cal * bp_filter)

    harmonic_power = sum(np.sum(np.abs(E_fft[p]) ** 2) for p in range(1, 5))
    fundamental_error = np.sum(np.abs(E_fft[0]) ** 2)
    total_error = harmonic_power  # Fixed: optimize THD only since G1 is frozen
    ref_power = np.sum(np.abs(H_target) ** 2)
    thd_db = 10 * np.log10(harmonic_power / ref_power)
    total_err_db = 10 * np.log10(total_error / ref_power)

    best_total_err_db = total_err_db
    best_thd_db = thd_db
    history_err_db.append((total_err_db, thd_db))
    print(f"Initial State | Total Error: {total_err_db:6.2f} dB | THD: {thd_db:6.2f} dB")

    # ==========================================
    # PHASE 1: Pre-training (SAAKE)
    # ==========================================
    pre_train_iter = 0
    pre_train_amp = 0.30  # Peak calibration amplitude (Chebyshev max)

    print("\n--- Phase 1: Pre-training using Single-Amplitude Farina Sweep (SAAKE) ---")

    # We use a conservative learning rate for Phase 1 to prevent unstable dynamics
    mu_pt = [0.00, 0.12, 0.10, 0.08, 0.05]  # G1 frozen

    for iteration in range(pre_train_iter):
        T_time_pt, clip_triggered = measure_single_amplitude_kernels(G_fft, pre_train_amp)

        if clip_triggered:
            print(f"  [Pre-training] Iteration {iteration + 1:2d}: Clipping detected! Reducing amplitude.")
            pre_train_amp *= 0.8
            continue

        T_fft_pt = [np.fft.rfft(T_time_pt[p]) for p in range(5)]
        E_fft_pt = []
        T1_cal_pt = T_fft_pt[0] * C_fft[0]
        E_fft_pt.append((T1_cal_pt - Q1_fft) * bp_filter)  # Fixed: target Q1_fft directly instead of H_target
        for p in range(1, 5):
            Tp_cal_pt = T_fft_pt[p] * C_fft[p]
            E_fft_pt.append(Tp_cal_pt * bp_filter)

        harmonic_power_pt = sum(np.sum(np.abs(E_fft_pt[p]) ** 2) for p in range(1, 5))
        fundamental_error_pt = np.sum(np.abs(E_fft_pt[0]) ** 2)
        total_error_pt = harmonic_power_pt  # Fixed: optimize THD only
        thd_db_pt = 10 * np.log10(harmonic_power_pt / ref_power)
        total_err_db_pt = 10 * np.log10(total_error_pt / ref_power)

        # Record history
        history_err_db.append((total_err_db_pt, thd_db_pt))
        print(
            f"Pre-train Iter {iteration + 1:2d}/{pre_train_iter} | Total Error: {total_err_db_pt:6.2f} dB | THD: {thd_db_pt:6.2f} dB (1 sweep)"
        )

        # Apply direct algebraic update
        for p in range(5):
            phase_corr = np.exp(-1j * 2 * np.pi * freqs * 0.0)  # Set delay to 0.0 (no phase correction needed)
            update = mu_pt[p] * E_fft_pt[p] * F_inv * phase_corr
            G_fft[p] = G_fft[p] - update
            G_fft[p] = G_fft[p] * bp_filter
            g_t = np.fft.irfft(G_fft[p], n=N)
            g_t_win = g_t * g_win
            G_fft[p] = np.fft.rfft(g_t_win) * bp_filter  # Re-apply filter to suppress leakage from time windowing

    # ==========================================
    # PHASE 2: SSS Fine-tuning (Chebyshev LS)
    # ==========================================
    max_iter_fine = 15  # Extended Chebyshev LS fine-tuning

    print("\n--- Phase 2: Fine-tuning using Multi-Amplitude SSS (Chebyshev LS) ---")

    # Re-evaluate with Cascade SSS to align before the fine-tuning loops
    print("--- Running Transition Calibration Measurement (Using 10-sweep SSS) ---")
    T_time, _ = measure_cascade_kernels(G_fft, measurement_amplitudes)
    T_fft = [np.fft.rfft(T_time[p]) for p in range(5)]
    E_fft = []
    T1_cal = T_fft[0] * C_fft[0]
    E_fft.append((T1_cal - Q1_fft) * bp_filter)  # Fixed: target Q1_fft directly instead of H_target
    for p in range(1, 5):
        Tp_cal = T_fft[p] * C_fft[p]
        E_fft.append(Tp_cal * bp_filter)

    harmonic_power = sum(np.sum(np.abs(E_fft[p]) ** 2) for p in range(1, 5))
    fundamental_error = np.sum(np.abs(E_fft[0]) ** 2)
    total_error = harmonic_power  # Fixed: optimize THD only
    thd_db = 10 * np.log10(harmonic_power / ref_power)
    total_err_db = 10 * np.log10(total_error / ref_power)

    best_total_err_db = total_err_db
    best_thd_db = thd_db
    history_err_db.append((total_err_db, thd_db))
    print(f"Fine-tune Init  | Total Error: {total_err_db:6.2f} dB | THD: {thd_db:6.2f} dB")

    # Learning rates base for fine-tuning
    mu_base = [0.00, 0.20, 0.15, 0.10, 0.05]  # G1 frozen, others increased for convergence

    for iteration in range(max_iter_fine):
        # Update mu_base (annealing)
        mu_base = [m * 0.9 for m in mu_base]

        # Backtracking Line Search
        success = False
        max_search_steps = 4
        for search_step in range(max_search_steps):
            factor = 0.5**search_step
            mu_step = [m * factor for m in mu_base]

            # Candidate G_fft
            G_fft_cand = G_fft.copy()
            for p in range(5):
                phase_corr = np.exp(-1j * 2 * np.pi * freqs * 0.0)  # Set delay to 0.0 (no phase correction needed)
                update = mu_step[p] * E_fft[p] * F_inv * phase_corr
                G_fft_cand[p] = G_fft_cand[p] - update
                G_fft_cand[p] = G_fft_cand[p] * bp_filter
                g_t = np.fft.irfft(G_fft_cand[p], n=N)
                g_t_win = g_t * g_win
                G_fft_cand[p] = np.fft.rfft(g_t_win) * bp_filter  # Re-apply filter to suppress leakage from time windowing

            # Simulate measurement
            T_time_cand, clip_triggered = measure_cascade_kernels(G_fft_cand, measurement_amplitudes)

            if clip_triggered:
                print(
                    f"  [Line Search] Iteration {iteration + 1:2d} | Step {search_step + 1}: Clipping detected. Reducing step size."
                )
                continue

            # Calculate errors for candidate
            T_fft_cand = [np.fft.rfft(T_time_cand[p]) for p in range(5)]
            E_fft_cand = []
            T1_cal_cand = T_fft_cand[0] * C_fft[0]
            E_fft_cand.append((T1_cal_cand - Q1_fft) * bp_filter)
            for p in range(1, 5):
                Tp_cal_cand = T_fft_cand[p] * C_fft[p]
                E_fft_cand.append(Tp_cal_cand * bp_filter)

            harmonic_power_cand = sum(np.sum(np.abs(E_fft_cand[p]) ** 2) for p in range(1, 5))
            fundamental_error_cand = np.sum(np.abs(E_fft_cand[0]) ** 2)
            total_error_cand = harmonic_power_cand  # Fixed: optimize THD only
            thd_db_cand = 10 * np.log10(harmonic_power_cand / ref_power)
            total_err_db_cand = 10 * np.log10(total_error_cand / ref_power)

            if total_err_db_cand < best_total_err_db:
                # Accept candidate
                G_fft = G_fft_cand
                T_time = T_time_cand
                T_fft = T_fft_cand
                E_fft = E_fft_cand
                best_total_err_db = total_err_db_cand
                best_thd_db = thd_db_cand
                success = True
                print(
                    f"Fine-tune Iter {iteration + 1:2d}/{max_iter_fine} | Step {search_step + 1} Accepted | Total Error: {best_total_err_db:6.2f} dB | THD: {best_thd_db:6.2f} dB"
                )
                break
            else:
                print(
                    f"  [Line Search] Iteration {iteration + 1:2d} | Step {search_step + 1}: Error worsened ({total_err_db_cand:.2f} dB vs {best_total_err_db:.2f} dB). Reducing step size."
                )

        if not success:
            print(
                f"Fine-tune Iter {iteration + 1:2d}/{max_iter_fine} | Line search failed to improve error. Stopping optimization."
            )
            break

        history_err_db.append((best_total_err_db, best_thd_db))

        if np.isnan(best_total_err_db) or best_total_err_db > 80.0:
            print("WARNING: Divergence detected! Stopping optimization.")
            break

    # 8. Post-Optimization Verification and Validation on Untrained Signals
    print("\n--- Verifying and Validating Linearization on Untrained Signals ---")
    t_verify = np.arange(N) / sample_rate
    g_final_time = [np.fft.irfft(G_fft[p], n=N) for p in range(5)]

    def evaluate_test_signal(u_in, label):
        U_in_fft = np.fft.rfft(u_in)
        u_in_filt = np.fft.irfft(U_in_fft * bp_filter, n=N)
        y_target = u_in_filt.copy()
        y_raw = forward_model(u_in_filt)

        u_comp = np.zeros_like(u_in_filt)
        for p in range(1, 6):
            U_p_fft = power_oversampled_fft(u_in_filt, p) * G_fft[p - 1]
            u_comp += np.fft.irfft(U_p_fft, n=N)

        y_comp = forward_model(u_comp)

        # Circular cross-correlation via FFT
        C_raw = np.fft.irfft(np.fft.rfft(y_raw) * np.conj(np.fft.rfft(y_target)), n=N)
        delay_raw = np.argmax(np.abs(C_raw))
        if delay_raw > N // 2:
            delay_raw -= N
        y_raw_aligned = np.roll(y_raw, -delay_raw)

        C_comp = np.fft.irfft(np.fft.rfft(y_comp) * np.conj(np.fft.rfft(y_target)), n=N)
        delay_comp = np.argmax(np.abs(C_comp))
        if delay_comp > N // 2:
            delay_comp -= N
        y_comp_aligned = np.roll(y_comp, -delay_comp)

        rms_target = np.sqrt(np.mean(y_target**2))

        y_raw_scaled = y_raw_aligned * (rms_target / (np.sqrt(np.mean(y_raw_aligned**2)) + 1e-12))
        y_comp_scaled = y_comp_aligned * (rms_target / (np.sqrt(np.mean(y_comp_aligned**2)) + 1e-12))

        err_raw = y_raw_scaled - y_target
        err_comp = y_comp_scaled - y_target

        rms_raw_err = np.sqrt(np.mean(err_raw**2))
        rms_comp_err = np.sqrt(np.mean(err_comp**2))

        print(
            f"[{label}] RMS target: {rms_target:.6f}, RMS raw: {np.sqrt(np.mean(y_raw**2)):.6f}, RMS comp: {np.sqrt(np.mean(y_comp**2)):.6f}"
        )
        print(f"[{label}] delay_raw: {delay_raw}, delay_comp: {delay_comp}")
        print(
            f"[{label}] RMS raw err (gain-normalized): {rms_raw_err:.6f}, RMS comp err (gain-normalized): {rms_comp_err:.6f}"
        )

        sdr_raw = 20 * np.log10(rms_target / (rms_raw_err + 1e-12))
        sdr_comp = 20 * np.log10(rms_target / (rms_comp_err + 1e-12))
        improvement = sdr_comp - sdr_raw

        return {
            "label": label,
            "u_in": u_in_filt,
            "y_target": y_target,
            "y_raw": y_raw_aligned,
            "y_comp": y_comp_aligned,
            "sdr_raw": sdr_raw,
            "sdr_comp": sdr_comp,
            "improvement": improvement,
        }

    def compute_thd(y_sig, f_test):
        N_fft = len(y_sig)
        Y_fft = np.fft.rfft(y_sig)
        freqs_fft = np.fft.rfftfreq(N_fft, d=1.0 / sample_rate)

        idx_fund = np.argmin(np.abs(freqs_fft - f_test))
        w_bin = 3
        fund_search_range = range(max(0, idx_fund - w_bin), min(len(freqs_fft), idx_fund + w_bin + 1))
        idx_fund_peak = max(fund_search_range, key=lambda i: np.abs(Y_fft[i]))
        fund_power = np.abs(Y_fft[idx_fund_peak]) ** 2

        harmonic_powers = []
        for h in [2, 3, 4, 5]:
            f_h = h * f_test
            if f_h > sample_rate / 2:
                break
            idx_h = np.argmin(np.abs(freqs_fft - f_h))
            h_search_range = range(max(0, idx_h - w_bin), min(len(freqs_fft), idx_h + w_bin + 1))
            idx_h_peak = max(h_search_range, key=lambda i: np.abs(Y_fft[i]))
            harmonic_powers.append(np.abs(Y_fft[idx_h_peak]) ** 2)

        thd_val = np.sqrt(sum(harmonic_powers)) / (np.sqrt(fund_power) + 1e-12)
        return 20 * np.log10(thd_val + 1e-12)

    # 1. 1 kHz Tone (Original)
    u_1k = b_amp * np.sin(2 * np.pi * 1000.0 * t_verify)
    res_1k = evaluate_test_signal(u_1k, "1kHz Tone")
    res_1k["thd_raw"] = compute_thd(res_1k["y_raw"], 1000.0)
    res_1k["thd_comp"] = compute_thd(res_1k["y_comp"], 1000.0)

    # 2. 3 kHz Tone (Validation: Untrained Frequency)
    u_3k = b_amp * np.sin(2 * np.pi * 3000.0 * t_verify)
    res_3k = evaluate_test_signal(u_3k, "3kHz Tone (Untrained)")
    res_3k["thd_raw"] = compute_thd(res_3k["y_raw"], 3000.0)
    res_3k["thd_comp"] = compute_thd(res_3k["y_comp"], 3000.0)

    # 3. Two-Tone Signal (Validation: Untrained Intermodulation)
    u_2tone = (b_amp / 2) * (np.sin(2 * np.pi * 1000.0 * t_verify) + np.sin(2 * np.pi * 1500.0 * t_verify))
    res_2tone = evaluate_test_signal(u_2tone, "Two-Tone (1.0k + 1.5k)")

    # 4. Multi-Tone Signal (Validation: 5 untrained frequencies)
    freqs_multi = [300.0, 700.0, 1300.0, 2700.0, 5500.0]
    u_multi = np.zeros_like(t_verify)
    for f_m in freqs_multi:
        u_multi += np.sin(2 * np.pi * f_m * t_verify)
    u_multi = u_multi / np.max(np.abs(u_multi)) * b_amp
    res_multi = evaluate_test_signal(u_multi, "Multi-Tone (5 freqs)")

    # 5. Broadband Noise Signal (Validation: Untrained Noise)
    rng_val = np.random.default_rng(99)
    # Generate in frequency domain with random phases to ensure circular continuity
    noise_fft = np.exp(1j * rng_val.uniform(0, 2 * np.pi, N // 2 + 1))
    noise_fft[0] = 0.0  # Zero DC
    noise_fft[-1] = 0.0  # Zero Nyquist
    u_noise_filt = np.fft.irfft(noise_fft * bp_filter, n=N)
    u_noise_filt = u_noise_filt / np.max(np.abs(u_noise_filt)) * b_amp
    res_noise = evaluate_test_signal(u_noise_filt, "Broadband Noise")

    # Print Validation Report
    print("\n" + "=" * 55)
    print("         GENERALIZATION VALIDATION REPORT (HYBRID)")
    print("=" * 55)
    print(f"1. {res_1k['label']} (Original Verification):")
    print(
        f"   - SDR: {res_1k['sdr_raw']:6.2f} dB -> {res_1k['sdr_comp']:6.2f} dB (Improvement: {res_1k['improvement']:6.2f} dB)"
    )
    print(
        f"   - THD: {res_1k['thd_raw']:6.2f} dB -> {res_1k['thd_comp']:6.2f} dB (Improvement: {res_1k['thd_raw'] - res_1k['thd_comp']:6.2f} dB)"
    )
    print(f"\n2. {res_3k['label']}:")
    print(
        f"   - SDR: {res_3k['sdr_raw']:6.2f} dB -> {res_3k['sdr_comp']:6.2f} dB (Improvement: {res_3k['improvement']:6.2f} dB)"
    )
    print(
        f"   - THD: {res_3k['thd_raw']:6.2f} dB -> {res_3k['thd_comp']:6.2f} dB (Improvement: {res_3k['thd_raw'] - res_3k['thd_comp']:6.2f} dB)"
    )
    print(f"\n3. {res_2tone['label']}:")
    print(
        f"   - SDR: {res_2tone['sdr_raw']:6.2f} dB -> {res_2tone['sdr_comp']:6.2f} dB (Improvement: {res_2tone['improvement']:6.2f} dB)"
    )
    print(f"\n4. {res_multi['label']}:")
    print(
        f"   - SDR: {res_multi['sdr_raw']:6.2f} dB -> {res_multi['sdr_comp']:6.2f} dB (Improvement: {res_multi['improvement']:6.2f} dB)"
    )
    print(f"\n5. {res_noise['label']}:")
    print(
        f"   - SDR: {res_noise['sdr_raw']:6.2f} dB -> {res_noise['sdr_comp']:6.2f} dB (Improvement: {res_noise['improvement']:6.2f} dB)"
    )
    print("=" * 55)

    # Plotting and Saving Results
    plt.figure(figsize=(15, 10))

    # Subplot 1: Convergence History
    plt.subplot(2, 2, 1)
    history_err_db = np.array(history_err_db)

    # Adjust indexing for Phase 1 vs Phase 2 plotting
    plt.plot(
        range(0, len(history_err_db)), history_err_db[:, 0], "o-", color="#1f77b4", linewidth=2.5, label="Total Error"
    )
    plt.plot(
        range(0, len(history_err_db)), history_err_db[:, 1], "s--", color="#ff7f0e", linewidth=2.5, label="THD Error"
    )
    plt.axvline(x=pre_train_iter, color="purple", linestyle=":", label="Transition to SSS")
    plt.title("Hybrid Optimization Convergence (SAAKE + SSS)", fontsize=12, fontweight="bold")
    plt.xlabel("Measurement Iterations", fontsize=10)
    plt.ylabel("Error Level (dB relative to Fundamental)", fontsize=10)
    plt.grid(True, which="both", linestyle="--", alpha=0.5)
    plt.legend()

    # Subplot 2: Spectrum comparison for 1kHz Tone
    f_axis = np.fft.rfftfreq(N, d=1.0 / sample_rate)
    Y_target_mag = 20 * np.log10(np.abs(np.fft.rfft(res_1k["y_target"])) + 1e-12)
    Y_raw_mag = 20 * np.log10(np.abs(np.fft.rfft(res_1k["y_raw"])) + 1e-12)
    Y_comp_mag = 20 * np.log10(np.abs(np.fft.rfft(res_1k["y_comp"])) + 1e-12)

    plt.subplot(2, 2, 2)
    plt.plot(f_axis, Y_raw_mag, color="#d62728", alpha=0.7, label="Raw Output")
    plt.plot(f_axis, Y_comp_mag, color="#1f77b4", linewidth=1.5, label="Linearized Output")
    plt.plot(f_axis, Y_target_mag, color="black", linestyle=":", label="Target Linear")
    plt.xlim(100, 12000)
    plt.ylim(-110, -20)
    plt.title("Output Spectrum (Hybrid, 1kHz Sine Zoom)", fontsize=12, fontweight="bold")
    plt.xlabel("Frequency (Hz)", fontsize=10)
    plt.ylabel("Magnitude (dBFS)", fontsize=10)
    plt.grid(True, which="both", linestyle="--", alpha=0.5)
    plt.legend()

    # Subplot 3: Time Domain Residual Error comparison (1kHz Tone)
    plt.subplot(2, 2, 3)
    t_ms = t * 1000.0
    err_raw = res_1k["y_raw"] - res_1k["y_target"]
    err_comp = res_1k["y_comp"] - res_1k["y_target"]
    plt.plot(t_ms, err_raw, color="#d62728", alpha=0.7, label="Raw Error")
    plt.plot(t_ms, err_comp, color="#1f77b4", label="Compensated Error")
    plt.xlim(10, 15)
    plt.title("Time Domain Residual Error (1kHz)", fontsize=12, fontweight="bold")
    plt.xlabel("Time (ms)", fontsize=10)
    plt.ylabel("Error Amplitude", fontsize=10)
    plt.grid(True, which="both", linestyle="--", alpha=0.5)
    plt.legend()

    # Subplot 4: Trained Inverse Kernels in Time Domain
    plt.subplot(2, 2, 4)
    time_display_ms = (np.arange(N) - N // 2) / sample_rate * 1000.0
    plt.plot(time_display_ms, np.roll(g_final_time[0], N // 2), label="g1 (fundamental)")
    plt.plot(time_display_ms, np.roll(g_final_time[1], N // 2) * 10, label="g2 * 10")
    plt.plot(time_display_ms, np.roll(g_final_time[2], N // 2) * 10, label="g3 * 10")
    plt.plot(time_display_ms, np.roll(g_final_time[4], N // 2) * 10, label="g5 * 10")
    plt.xlim(-10, 30)
    plt.title("Trained Inverse Kernels (g_p)", fontsize=12, fontweight="bold")
    plt.xlabel("Time Offset (ms)", fontsize=10)
    plt.ylabel("Kernel Amplitude", fontsize=10)
    plt.grid(True, which="both", linestyle="--", alpha=0.5)
    plt.legend()

    plt.tight_layout()

    output_dir = "/Users/vach/.gemini/antigravity/brain/5b83a14d-faba-4824-a4ce-68af49af74f3"
    os.makedirs(output_dir, exist_ok=True)
    output_img_path = os.path.join(output_dir, "hybrid_linearization_results.png")
    plt.savefig(output_img_path, dpi=150)
    plt.close()

    print(f"\nSuccessfully generated hybrid training comparison plot at: {output_img_path}")

    # Generate Second Plot: Validation Signals
    plt.figure(figsize=(15, 10))

    # Subplot 1: 3kHz Tone Spectrum
    plt.subplot(2, 2, 1)
    Y_target_3k = 20 * np.log10(np.abs(np.fft.rfft(res_3k["y_target"])) + 1e-12)
    Y_raw_3k = 20 * np.log10(np.abs(np.fft.rfft(res_3k["y_raw"])) + 1e-12)
    Y_comp_3k = 20 * np.log10(np.abs(np.fft.rfft(res_3k["y_comp"])) + 1e-12)
    plt.plot(f_axis, Y_raw_3k, color="#d62728", alpha=0.7, label="Raw Output")
    plt.plot(f_axis, Y_comp_3k, color="#1f77b4", linewidth=1.5, label="Linearized Output")
    plt.plot(f_axis, Y_target_3k, color="black", linestyle=":", label="Target Output")
    plt.xlim(200, 16000)
    plt.ylim(-110, -20)
    plt.title(
        f"Validation: 3kHz Tone Spectrum (SDR Imp: {res_3k['improvement']:.1f}dB)", fontsize=12, fontweight="bold"
    )
    plt.xlabel("Frequency (Hz)", fontsize=10)
    plt.ylabel("Magnitude (dBFS)", fontsize=10)
    plt.grid(True, which="both", linestyle="--", alpha=0.5)
    plt.legend()

    # Subplot 2: Two-Tone Spectrum
    plt.subplot(2, 2, 2)
    Y_target_2t = 20 * np.log10(np.abs(np.fft.rfft(res_2tone["y_target"])) + 1e-12)
    Y_raw_2t = 20 * np.log10(np.abs(np.fft.rfft(res_2tone["y_raw"])) + 1e-12)
    Y_comp_2t = 20 * np.log10(np.abs(np.fft.rfft(res_2tone["y_comp"])) + 1e-12)
    plt.plot(f_axis, Y_raw_2t, color="#d62728", alpha=0.7, label="Raw Output")
    plt.plot(f_axis, Y_comp_2t, color="#1f77b4", linewidth=1.5, label="Linearized Output")
    plt.plot(f_axis, Y_target_2t, color="black", linestyle=":", label="Target Output")
    plt.xlim(200, 10000)
    plt.ylim(-110, -20)
    plt.title(
        f"Validation: Two-Tone Spectrum (SDR Imp: {res_2tone['improvement']:.1f}dB)", fontsize=12, fontweight="bold"
    )
    plt.xlabel("Frequency (Hz)", fontsize=10)
    plt.ylabel("Magnitude (dBFS)", fontsize=10)
    plt.grid(True, which="both", linestyle="--", alpha=0.5)
    plt.legend()

    # Subplot 3: Multi-Tone Spectrum
    plt.subplot(2, 2, 3)
    Y_target_mt = 20 * np.log10(np.abs(np.fft.rfft(res_multi["y_target"])) + 1e-12)
    Y_raw_mt = 20 * np.log10(np.abs(np.fft.rfft(res_multi["y_raw"])) + 1e-12)
    Y_comp_mt = 20 * np.log10(np.abs(np.fft.rfft(res_multi["y_comp"])) + 1e-12)
    plt.plot(f_axis, Y_raw_mt, color="#d62728", alpha=0.7, label="Raw Output")
    plt.plot(f_axis, Y_comp_mt, color="#1f77b4", linewidth=1.5, label="Linearized Output")
    plt.plot(f_axis, Y_target_mt, color="black", linestyle=":", label="Target Output")
    plt.xlim(100, 15000)
    plt.ylim(-110, -20)
    plt.title(
        f"Validation: Multi-Tone Spectrum (SDR Imp: {res_multi['improvement']:.1f}dB)", fontsize=12, fontweight="bold"
    )
    plt.xlabel("Frequency (Hz)", fontsize=10)
    plt.ylabel("Magnitude (dBFS)", fontsize=10)
    plt.grid(True, which="both", linestyle="--", alpha=0.5)
    plt.legend()

    # Subplot 4: Broadband Noise Spectrum
    plt.subplot(2, 2, 4)
    Y_target_ns = 20 * np.log10(np.abs(np.fft.rfft(res_noise["y_target"])) + 1e-12)
    Y_raw_ns = 20 * np.log10(np.abs(np.fft.rfft(res_noise["y_raw"])) + 1e-12)
    Y_comp_ns = 20 * np.log10(np.abs(np.fft.rfft(res_noise["y_comp"])) + 1e-12)
    plt.plot(f_axis, Y_raw_ns, color="#d62728", alpha=0.7, label="Raw Output")
    plt.plot(f_axis, Y_comp_ns, color="#1f77b4", linewidth=1.5, label="Linearized Output")
    plt.plot(f_axis, Y_target_ns, color="black", linestyle=":", label="Target Output")
    plt.xlim(50, 20000)
    plt.ylim(-110, -20)
    plt.title(
        f"Validation: Broadband Noise Spectrum (SDR Imp: {res_noise['improvement']:.1f}dB)",
        fontsize=12,
        fontweight="bold",
    )
    plt.xlabel("Frequency (Hz)", fontsize=10)
    plt.ylabel("Magnitude (dBFS)", fontsize=10)
    plt.grid(True, which="both", linestyle="--", alpha=0.5)
    plt.legend()

    plt.tight_layout()
    output_val_img_path = os.path.join(output_dir, "hybrid_validation_results.png")
    plt.savefig(output_val_img_path, dpi=150)
    plt.close()

    print(f"Successfully generated hybrid validation comparison plot at: {output_val_img_path}")

    # Results Summary
    final_thd_db = history_err_db[-1, 1]
    initial_thd_db = history_err_db[0, 1]
    improvement = initial_thd_db - final_thd_db
    print("\nOptimization Result Summary (HYBRID):")
    print(f"  Initial Kernel THD Error: {initial_thd_db:.2f} dB")
    print(f"  Final Kernel THD Error:   {final_thd_db:.2f} dB")
    print(f"  Suppression Improvement:  {improvement:.2f} dB")
    print(f"  Total Measured Sweeps:    {total_measured_sweeps} sweeps (compared to ~300 in original)")

    # 9. Save Inverse Hammerstein Model to JSON (loadable by HammersteinAnalyzer)
    from datetime import datetime

    inv_mags = {}
    inv_phases = {}
    for p in range(5):
        h_key = f"h{p + 1}"
        inv_mags[h_key] = 20 * np.log10(np.abs(G_fft[p]) + 1e-12)
        
        # Compensate for the causal delay_2tau (20ms) to clean up Bode phase response
        total_delay = delay_2tau
        phase_correction = 2 * np.pi * freqs * total_delay
        G_corrected = G_fft[p] * np.exp(1j * phase_correction)
        
        phase_rad = np.unwrap(np.angle(G_corrected))
        phase_deg = phase_rad * 180.0 / np.pi
        phase_deg = (phase_deg + 180) % 360 - 180
        inv_phases[h_key] = phase_deg

    inv_phases["ref_phase"] = inv_phases["h1"]

    inv_metadata = {
        "format_version": "1.0",
        "export_timestamp": datetime.now().isoformat(),
        "module": "Inverse Hammerstein Predistorter",
        "sample_rate": float(sample_rate),
        "num_amplitudes": int(K_amp),
        "sweep_duration": float(sweep_duration),
        "start_freq": float(start_freq),
        "end_freq": float(end_freq),
        "input_mode": "L",
        "latency_sec": 0.0,
        "ref_max": float(np.max(np.abs(g_final_time[0]))),
        "P": 5,
        "noise_floor_dbfs": float(metadata.get("noise_floor_dbfs", -100.0)),
    }

    inverse_model_data = {
        "metadata": inv_metadata,
        "time_domain": {
            "time_ms": [float(val) for val in time_ms],
            "kernels": {f"h{p + 1}": [float(val) for val in g_final_time[p]] for p in range(5)},
        },
        "frequency_domain": {
            "freqs": [float(val) for val in freqs],
            "magnitudes_db": {k: [float(val) for val in v] for k, v in inv_mags.items()},
            "phases_deg": {k: [float(val) for val in v] for k, v in inv_phases.items()},
        },
    }

    # Save to the project root directory
    workspace_json_path = os.path.join("/Users/vach/MeasureLab", "inverse_hammerstein_model.json")
    try:
        with open(workspace_json_path, "w", encoding="utf-8") as f:
            json.dump(inverse_model_data, f, indent=2, ensure_ascii=False)
        print(f"Successfully saved inverse model JSON to: {workspace_json_path}")
    except Exception as e:
        print(f"Failed to save inverse model to {workspace_json_path}: {e}")

    # Also save to the output directory if it exists
    if output_dir:
        output_json_path = os.path.join(output_dir, "inverse_hammerstein_model.json")
        try:
            with open(output_json_path, "w", encoding="utf-8") as f:
                json.dump(inverse_model_data, f, indent=2, ensure_ascii=False)
            print(f"Successfully saved copy of inverse model JSON to: {output_json_path}")
        except Exception as e:
            print(f"Failed to save copy of inverse model to {output_json_path}: {e}")


if __name__ == "__main__":
    run_closed_loop_training()
