import os
import json
import numpy as np
import matplotlib.pyplot as plt
from scipy.signal import windows, fftconvolve

def run_closed_loop_training():
    # 1. Load measured kernels and metadata
    json_path = '/Users/vach/MeasureLab/hammerstein_kernel_sample_soft_condition.json'
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

    print("=== Loaded Target Nonlinear System (F) ===")
    print(f"Sample Rate: {sample_rate} Hz")
    print(f"Kernel Length: {N} samples ({N/sample_rate*1000.0:.2f} ms)")

    # 2. Chebyshev to Power Series Conversion for the Forward Simulator F
    q0 = -h2 + h4
    q1 = h1 - 3*h3 + 5*h5  # True linear dynamic response
    q2 = 2*h2 - 8*h4
    q3 = 4*h3 - 20*h5
    q4 = 8*h4
    q5 = 16*h5

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
    freqs = np.fft.rfftfreq(N, d=1.0/sample_rate)
    passband = (freqs >= 60.0) & (freqs <= 17000.0)
    bp_filter = np.zeros_like(freqs)
    bp_filter[passband] = 1.0
    for i in range(len(freqs)):
        f = freqs[i]
        if f < 60.0:
            bp_filter[i] = np.clip((f - 10.0) / 50.0, 0, 1)
        elif f > 17000.0 and f < 22000.0:
            bp_filter[i] = np.clip(1.0 - (f - 17000.0) / 5000.0, 0, 1)

    # Anti-aliasing oversampled power evaluation in frequency domain
    def power_oversampled_fft(x, p, L=8):
        if p == 1:
            return np.fft.rfft(x)
        N_x = len(x)
        X = np.fft.rfft(x)
        N_up = L * N_x
        X_up = np.zeros(N_up // 2 + 1, dtype=complex)
        X_up[:len(X)] = X * L
        x_up = np.fft.irfft(X_up, n=N_up)
        
        xp_up = x_up ** p
        
        Xp_up = np.fft.rfft(xp_up)
        Xp = Xp_up[:N_x // 2 + 1] / L
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

    def apply_phase_correction_and_frac_delay(g_k, k, frac_delay):
        N_k = len(g_k)
        G = np.fft.rfft(g_k)
        if k == 2: G = G * 1j
        elif k == 3: G = -G
        elif k == 4: G = G * (-1j)
        if np.abs(frac_delay) > 1e-9:
            freqs_k = np.fft.rfftfreq(N_k, d=1.0/sample_rate)
            phase_shift = np.exp(1j * 2 * np.pi * freqs_k * frac_delay / sample_rate)
            G = G * phase_shift
        return np.fft.irfft(G, n=N_k)

    def measure_cascade_kernels(G_fft, amplitudes):
        # G_fft is a list/array of 5 frequency-domain kernels representing the predistorter G
        num_amps = len(amplitudes)
        responses_meas = []
        clip_triggered = False

        # Run measurement sweeps for each amplitude
        for amp in amplitudes:
            s_A = amp * sss_signal
            
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

    # 6. Initialize G kernels
    N_fft_half_full = N // 2 + 1
    Q1_sc_power = np.abs(Q1_fft) ** 2
    beta = 0.005
    # Define delay parameters
    delay_tau = gate_pre / sample_rate # 10 ms = 0.01 s
    delay_2tau = 2.0 * delay_tau       # 20 ms = 0.02 s
    
    # Initial G1 is the linear inverse with 2*tau delay for causality
    phase_shift_2tau = np.exp(-1j * 2 * np.pi * freqs * delay_2tau)
    G1_init_fft = (np.conj(Q1_fft) / (Q1_sc_power + beta)) * bp_filter * phase_shift_2tau

    G_fft = np.zeros((5, N_fft_half_full), dtype=complex)
    G_fft[0] = G1_init_fft # G1

    # 7. Closed-loop Optimization loop
    max_iter = 72
    
    # Amplitudes for the Chebyshev decomposition measurement (using Chebyshev Nodes)
    a_amp, b_amp = 0.03, 0.30
    K_amp = 10
    k_arr = np.arange(1, K_amp + 1)
    cheb_nodes = 0.5 * (a_amp + b_amp) + 0.5 * (b_amp - a_amp) * np.cos((2 * k_arr - 1) / (2 * K_amp) * np.pi)
    measurement_amplitudes = np.sort(cheb_nodes)
    
    # Keep track of error suppression
    history_err_db = []

    # Target system linear response (Q1_fft within passband)
    H_target = Q1_fft * bp_filter

    print("\n--- Starting Closed-Loop Kernel Training ---")
    
    # Precompute denominator for stability using Kirkeby regularization (frequency-dependent epsilon)
    F_lin_abs = np.abs(Q1_fft)
    eps_in = 1e-6
    eps_out = 0.5
    eps_f = eps_in + (eps_out - eps_in) * (1.0 - bp_filter)
    F_inv = np.conj(Q1_fft) / (F_lin_abs**2 + eps_f)

    # Window for predistorter time-domain regularization (symmetric around the delay peak)
    center_idx = 2 * gate_pre
    N_keep = N // 4
    N_fade = N // 8
    
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
    print("\n--- Running Initial Calibration Measurement ---")
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
        Cp = Cp * bp_filter + (1.0 - bp_filter)
        C_fft.append(Cp)

    # Evaluate Initial State Error
    T_time = T_time_init
    T_fft = [np.fft.rfft(T_time[p]) for p in range(5)]
    E_fft = []
    T1_cal = T_fft[0] * C_fft[0]
    E_fft.append((T1_cal - H_target) * bp_filter)
    
    for p in range(1, 5):
        Tp_cal = T_fft[p] * C_fft[p]
        E_fft.append(Tp_cal * bp_filter)

    harmonic_power = sum(np.sum(np.abs(E_fft[p])**2) for p in range(1, 5))
    fundamental_error = np.sum(np.abs(E_fft[0])**2)
    total_error = fundamental_error + harmonic_power
    ref_power = np.sum(np.abs(H_target)**2)
    thd_db = 10 * np.log10(harmonic_power / ref_power)
    total_err_db = 10 * np.log10(total_error / ref_power)
    
    best_total_err_db = total_err_db
    best_thd_db = thd_db
    history_err_db.append((total_err_db, thd_db))
    print(f"Initial State | Total Error: {total_err_db:6.2f} dB | THD: {thd_db:6.2f} dB")

    # Learning rates base
    mu_base = [0.15, 0.12, 0.1, 0.08, 0.04]

    for iteration in range(max_iter):
        # Update mu_base (annealing)
        mu_base = [m * 0.9 for m in mu_base]
        
        # Backtracking Line Search
        success = False
        max_search_steps = 4
        for search_step in range(max_search_steps):
            factor = 0.5 ** search_step
            mu_step = [m * factor for m in mu_base]
            
            # Candidate G_fft
            G_fft_cand = G_fft.copy()
            for p in range(5):
                n_harmonic = p + 1
                # Apply delay_2tau correction (no redundant sweep shift, as it's already deconvolved/aligned)
                phase_corr = np.exp(-1j * 2 * np.pi * freqs * delay_2tau)
                update = mu_step[p] * E_fft[p] * F_inv * phase_corr
                G_fft_cand[p] = G_fft_cand[p] - update
                G_fft_cand[p] = G_fft_cand[p] * bp_filter
                g_t = np.fft.irfft(G_fft_cand[p], n=N)
                g_t_win = g_t * g_win
                G_fft_cand[p] = np.fft.rfft(g_t_win)
                
            # Simulate measurement
            T_time_cand, clip_triggered = measure_cascade_kernels(G_fft_cand, measurement_amplitudes)
            
            if clip_triggered:
                print(f"  [Line Search] Iteration {iteration+1:2d} | Step {search_step+1}: Clipping detected. Reducing step size.")
                continue
                
            # Calculate errors for candidate
            T_fft_cand = [np.fft.rfft(T_time_cand[p]) for p in range(5)]
            E_fft_cand = []
            T1_cal_cand = T_fft_cand[0] * C_fft[0]
            E_fft_cand.append((T1_cal_cand - H_target) * bp_filter)
            for p in range(1, 5):
                Tp_cal_cand = T_fft_cand[p] * C_fft[p]
                E_fft_cand.append(Tp_cal_cand * bp_filter)
                
            harmonic_power_cand = sum(np.sum(np.abs(E_fft_cand[p])**2) for p in range(1, 5))
            fundamental_error_cand = np.sum(np.abs(E_fft_cand[0])**2)
            total_error_cand = fundamental_error_cand + harmonic_power_cand
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
                print(f"Iteration {iteration+1:2d}/{max_iter} | Step {search_step+1} Accepted | Total Error: {best_total_err_db:6.2f} dB | THD: {best_thd_db:6.2f} dB")
                break
            else:
                print(f"  [Line Search] Iteration {iteration+1:2d} | Step {search_step+1}: Error worsened ({total_err_db_cand:.2f} dB vs {best_total_err_db:.2f} dB). Reducing step size.")
                
        if not success:
            print(f"Iteration {iteration+1:2d}/{max_iter} | Line search failed to improve error. Stopping optimization.")
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
        # Apply bandpass filter
        U_in_fft = np.fft.rfft(u_in)
        u_in_filt = np.fft.irfft(U_in_fft * bp_filter, n=N)
        
        # Target Linear Output is now the equalized flat input signal (since G1 acts as Q1 inverse)
        y_target = u_in_filt.copy()
        
        # Uncompensated Output
        y_raw = forward_model(u_in_filt)
        
        # Compensated Output (circular convolution in frequency domain to match training)
        u_comp = np.zeros_like(u_in_filt)
        for p in range(1, 6):
            U_p_fft = power_oversampled_fft(u_in_filt, p) * G_fft[p - 1]
            u_comp += np.fft.irfft(U_p_fft, n=N)
            
        y_comp = forward_model(u_comp)
        
        # Align
        corr_raw = np.correlate(y_raw, y_target, mode='full')
        delay_raw = np.argmax(np.abs(corr_raw)) - (len(y_target) - 1)
        y_raw_aligned = np.roll(y_raw, -delay_raw)
        
        corr_comp = np.correlate(y_comp, y_target, mode='full')
        delay_comp = np.argmax(np.abs(corr_comp)) - (len(y_target) - 1)
        y_comp_aligned = np.roll(y_comp, -delay_comp)
        
        rms_target = np.sqrt(np.mean(y_target**2))
        
        # Gain normalization to isolate shape/distortion from gain difference
        y_raw_scaled = y_raw_aligned * (rms_target / (np.sqrt(np.mean(y_raw_aligned**2)) + 1e-12))
        y_comp_scaled = y_comp_aligned * (rms_target / (np.sqrt(np.mean(y_comp_aligned**2)) + 1e-12))
        
        err_raw = y_raw_scaled - y_target
        err_comp = y_comp_scaled - y_target
        
        rms_raw_err = np.sqrt(np.mean(err_raw**2))
        rms_comp_err = np.sqrt(np.mean(err_comp**2))
        
        print(f"[{label}] RMS target: {rms_target:.6f}, RMS raw: {np.sqrt(np.mean(y_raw**2)):.6f}, RMS comp: {np.sqrt(np.mean(y_comp**2)):.6f}")
        print(f"[{label}] delay_raw: {delay_raw}, delay_comp: {delay_comp}")
        print(f"[{label}] RMS raw err (gain-normalized): {rms_raw_err:.6f}, RMS comp err (gain-normalized): {rms_comp_err:.6f}")
        
        sdr_raw = 20 * np.log10(rms_target / (rms_raw_err + 1e-12))
        sdr_comp = 20 * np.log10(rms_target / (rms_comp_err + 1e-12))
        improvement = sdr_comp - sdr_raw
        
        return {
            'label': label,
            'u_in': u_in_filt,
            'y_target': y_target,
            'y_raw': y_raw_aligned,
            'y_comp': y_comp_aligned,
            'sdr_raw': sdr_raw,
            'sdr_comp': sdr_comp,
            'improvement': improvement
        }

    def compute_thd(y_sig, f_test):
        N_fft = len(y_sig)
        Y_fft = np.fft.rfft(y_sig)
        freqs_fft = np.fft.rfftfreq(N_fft, d=1.0/sample_rate)
        
        idx_fund = np.argmin(np.abs(freqs_fft - f_test))
        w_bin = 3
        fund_search_range = range(max(0, idx_fund - w_bin), min(len(freqs_fft), idx_fund + w_bin + 1))
        idx_fund_peak = max(fund_search_range, key=lambda i: np.abs(Y_fft[i]))
        fund_power = np.abs(Y_fft[idx_fund_peak])**2
        
        harmonic_powers = []
        for h in [2, 3, 4, 5]:
            f_h = h * f_test
            if f_h > sample_rate / 2:
                break
            idx_h = np.argmin(np.abs(freqs_fft - f_h))
            h_search_range = range(max(0, idx_h - w_bin), min(len(freqs_fft), idx_h + w_bin + 1))
            idx_h_peak = max(h_search_range, key=lambda i: np.abs(Y_fft[i]))
            harmonic_powers.append(np.abs(Y_fft[idx_h_peak])**2)
            
        thd_val = np.sqrt(sum(harmonic_powers)) / (np.sqrt(fund_power) + 1e-12)
        return 20 * np.log10(thd_val + 1e-12)

    # 1. 1 kHz Tone (Original)
    u_1k = b_amp * np.sin(2 * np.pi * 1000.0 * t_verify)
    res_1k = evaluate_test_signal(u_1k, "1kHz Tone")
    res_1k['thd_raw'] = compute_thd(res_1k['y_raw'], 1000.0)
    res_1k['thd_comp'] = compute_thd(res_1k['y_comp'], 1000.0)

    # 2. 3 kHz Tone (Validation: Untrained Frequency)
    u_3k = b_amp * np.sin(2 * np.pi * 3000.0 * t_verify)
    res_3k = evaluate_test_signal(u_3k, "3kHz Tone (Untrained)")
    res_3k['thd_raw'] = compute_thd(res_3k['y_raw'], 3000.0)
    res_3k['thd_comp'] = compute_thd(res_3k['y_comp'], 3000.0)

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
    u_noise = rng_val.normal(0.0, 1.0, N)
    U_noise_fft = np.fft.rfft(u_noise)
    u_noise_filt = np.fft.irfft(U_noise_fft * bp_filter, n=N)
    u_noise_filt = u_noise_filt / np.max(np.abs(u_noise_filt)) * b_amp
    res_noise = evaluate_test_signal(u_noise_filt, "Broadband Noise")

    # 8.4. Print Verification and Validation Report
    print("\n" + "="*55)
    print("         GENERALIZATION VALIDATION REPORT")
    print("="*55)
    print(f"1. {res_1k['label']} (Original Verification):")
    print(f"   - SDR: {res_1k['sdr_raw']:6.2f} dB -> {res_1k['sdr_comp']:6.2f} dB (Improvement: {res_1k['improvement']:6.2f} dB)")
    print(f"   - THD: {res_1k['thd_raw']:6.2f} dB -> {res_1k['thd_comp']:6.2f} dB (Improvement: {res_1k['thd_raw'] - res_1k['thd_comp']:6.2f} dB)")
    print(f"\n2. {res_3k['label']}:")
    print(f"   - SDR: {res_3k['sdr_raw']:6.2f} dB -> {res_3k['sdr_comp']:6.2f} dB (Improvement: {res_3k['improvement']:6.2f} dB)")
    print(f"   - THD: {res_3k['thd_raw']:6.2f} dB -> {res_3k['thd_comp']:6.2f} dB (Improvement: {res_3k['thd_raw'] - res_3k['thd_comp']:6.2f} dB)")
    print(f"\n3. {res_2tone['label']}:")
    print(f"   - SDR: {res_2tone['sdr_raw']:6.2f} dB -> {res_2tone['sdr_comp']:6.2f} dB (Improvement: {res_2tone['improvement']:6.2f} dB)")
    print(f"\n4. {res_multi['label']}:")
    print(f"   - SDR: {res_multi['sdr_raw']:6.2f} dB -> {res_multi['sdr_comp']:6.2f} dB (Improvement: {res_multi['improvement']:6.2f} dB)")
    print(f"\n5. {res_noise['label']}:")
    print(f"   - SDR: {res_noise['sdr_raw']:6.2f} dB -> {res_noise['sdr_comp']:6.2f} dB (Improvement: {res_noise['improvement']:6.2f} dB)")
    print("="*55)

    # 9. Plotting and Saving Results
    plt.figure(figsize=(15, 10))

    # Subplot 1: Convergence History
    plt.subplot(2, 2, 1)
    history_err_db = np.array(history_err_db)
    plt.plot(range(0, len(history_err_db)), history_err_db[:, 0], 'o-', color='#1f77b4', linewidth=2.5, label='Total Error (Linear + Nonlinear)')
    plt.plot(range(0, len(history_err_db)), history_err_db[:, 1], 's--', color='#ff7f0e', linewidth=2.5, label='Total Harmonic Distortion (THD)')
    plt.title('Closed-Loop Optimization Convergence', fontsize=12, fontweight='bold')
    plt.xlabel('Iteration Step (0=Initial)', fontsize=10)
    plt.ylabel('Error Level (dB relative to Fundamental)', fontsize=10)
    plt.grid(True, which='both', linestyle='--', alpha=0.5)
    plt.legend()

    # Subplot 2: Spectrum comparison for 1kHz Tone
    f_axis = np.fft.rfftfreq(N, d=1.0/sample_rate)
    Y_target_mag = 20 * np.log10(np.abs(np.fft.rfft(res_1k['y_target'])) + 1e-12)
    Y_raw_mag = 20 * np.log10(np.abs(np.fft.rfft(res_1k['y_raw'])) + 1e-12)
    Y_comp_mag = 20 * np.log10(np.abs(np.fft.rfft(res_1k['y_comp'])) + 1e-12)

    plt.subplot(2, 2, 2)
    plt.plot(f_axis, Y_raw_mag, color='#d62728', alpha=0.7, label='Raw Output (Uncompensated)')
    plt.plot(f_axis, Y_comp_mag, color='#1f77b4', linewidth=1.5, label='Linearized Output (Trained G)')
    plt.plot(f_axis, Y_target_mag, color='black', linestyle=':', label='Target Linear Output')
    plt.xlim(100, 12000)
    plt.ylim(-110, -20)
    plt.title('Output Spectrum Comparison (1kHz Sine, Zoomed)', fontsize=12, fontweight='bold')
    plt.xlabel('Frequency (Hz)', fontsize=10)
    plt.ylabel('Magnitude (dBFS)', fontsize=10)
    plt.grid(True, which='both', linestyle='--', alpha=0.5)
    plt.legend()

    # Subplot 3: Time Domain Residual Error comparison (1kHz Tone)
    plt.subplot(2, 2, 3)
    t_ms = t * 1000.0
    err_raw = res_1k['y_raw'] - res_1k['y_target']
    err_comp = res_1k['y_comp'] - res_1k['y_target']
    plt.plot(t_ms, err_raw, color='#d62728', alpha=0.7, label='Raw Error')
    plt.plot(t_ms, err_comp, color='#1f77b4', label='Compensated Error')
    plt.xlim(10, 15)
    plt.title('Time Domain Residual Error (1kHz Tone, Output - Linear Target)', fontsize=12, fontweight='bold')
    plt.xlabel('Time (ms)', fontsize=10)
    plt.ylabel('Error Amplitude', fontsize=10)
    plt.grid(True, which='both', linestyle='--', alpha=0.5)
    plt.legend()

    # Subplot 4: Trained Inverse Kernels in Time Domain
    plt.subplot(2, 2, 4)
    time_display_ms = (np.arange(N) - N//2) / sample_rate * 1000.0
    plt.plot(time_display_ms, np.roll(g_final_time[0], N//2), label='g1 (fundamental)')
    plt.plot(time_display_ms, np.roll(g_final_time[1], N//2) * 10, label='g2 * 10')
    plt.plot(time_display_ms, np.roll(g_final_time[2], N//2) * 10, label='g3 * 10')
    plt.plot(time_display_ms, np.roll(g_final_time[4], N//2) * 10, label='g5 * 10')
    plt.xlim(-10, 30)
    plt.title('Trained Inverse Hammerstein Kernels (g_p)', fontsize=12, fontweight='bold')
    plt.xlabel('Time Offset (ms)', fontsize=10)
    plt.ylabel('Kernel Amplitude', fontsize=10)
    plt.grid(True, which='both', linestyle='--', alpha=0.5)
    plt.legend()

    plt.tight_layout()

    output_dir = '/Users/vach/.gemini/antigravity/brain/35c1d5e0-9c7b-4f2e-b3af-a1ff4e66f731'
    os.makedirs(output_dir, exist_ok=True)
    output_img_path = os.path.join(output_dir, 'closed_loop_linearization_results.png')
    plt.savefig(output_img_path, dpi=150)
    plt.close()

    print(f"\nSuccessfully generated training comparison plot at: {output_img_path}")

    # Generate Second Plot: Validation Signals
    plt.figure(figsize=(15, 10))

    # Subplot 1: 3kHz Tone Spectrum
    plt.subplot(2, 2, 1)
    Y_target_3k = 20 * np.log10(np.abs(np.fft.rfft(res_3k['y_target'])) + 1e-12)
    Y_raw_3k = 20 * np.log10(np.abs(np.fft.rfft(res_3k['y_raw'])) + 1e-12)
    Y_comp_3k = 20 * np.log10(np.abs(np.fft.rfft(res_3k['y_comp'])) + 1e-12)
    plt.plot(f_axis, Y_raw_3k, color='#d62728', alpha=0.7, label='Raw Output')
    plt.plot(f_axis, Y_comp_3k, color='#1f77b4', linewidth=1.5, label='Linearized Output')
    plt.plot(f_axis, Y_target_3k, color='black', linestyle=':', label='Target Output')
    plt.xlim(200, 16000)
    plt.ylim(-110, -20)
    plt.title(f"Validation: 3kHz Tone Spectrum (SDR Imp: {res_3k['improvement']:.1f}dB)", fontsize=12, fontweight='bold')
    plt.xlabel('Frequency (Hz)', fontsize=10)
    plt.ylabel('Magnitude (dBFS)', fontsize=10)
    plt.grid(True, which='both', linestyle='--', alpha=0.5)
    plt.legend()

    # Subplot 2: Two-Tone Spectrum
    plt.subplot(2, 2, 2)
    Y_target_2t = 20 * np.log10(np.abs(np.fft.rfft(res_2tone['y_target'])) + 1e-12)
    Y_raw_2t = 20 * np.log10(np.abs(np.fft.rfft(res_2tone['y_raw'])) + 1e-12)
    Y_comp_2t = 20 * np.log10(np.abs(np.fft.rfft(res_2tone['y_comp'])) + 1e-12)
    plt.plot(f_axis, Y_raw_2t, color='#d62728', alpha=0.7, label='Raw Output')
    plt.plot(f_axis, Y_comp_2t, color='#1f77b4', linewidth=1.5, label='Linearized Output')
    plt.plot(f_axis, Y_target_2t, color='black', linestyle=':', label='Target Output')
    plt.xlim(200, 10000)
    plt.ylim(-110, -20)
    plt.title(f"Validation: Two-Tone (1.0k+1.5k) Spectrum (SDR Imp: {res_2tone['improvement']:.1f}dB)", fontsize=12, fontweight='bold')
    plt.xlabel('Frequency (Hz)', fontsize=10)
    plt.ylabel('Magnitude (dBFS)', fontsize=10)
    plt.grid(True, which='both', linestyle='--', alpha=0.5)
    plt.legend()

    # Subplot 3: Multi-Tone Spectrum
    plt.subplot(2, 2, 3)
    Y_target_mt = 20 * np.log10(np.abs(np.fft.rfft(res_multi['y_target'])) + 1e-12)
    Y_raw_mt = 20 * np.log10(np.abs(np.fft.rfft(res_multi['y_raw'])) + 1e-12)
    Y_comp_mt = 20 * np.log10(np.abs(np.fft.rfft(res_multi['y_comp'])) + 1e-12)
    plt.plot(f_axis, Y_raw_mt, color='#d62728', alpha=0.7, label='Raw Output')
    plt.plot(f_axis, Y_comp_mt, color='#1f77b4', linewidth=1.5, label='Linearized Output')
    plt.plot(f_axis, Y_target_mt, color='black', linestyle=':', label='Target Output')
    plt.xlim(100, 15000)
    plt.ylim(-110, -20)
    plt.title(f"Validation: Multi-Tone (5 freqs) Spectrum (SDR Imp: {res_multi['improvement']:.1f}dB)", fontsize=12, fontweight='bold')
    plt.xlabel('Frequency (Hz)', fontsize=10)
    plt.ylabel('Magnitude (dBFS)', fontsize=10)
    plt.grid(True, which='both', linestyle='--', alpha=0.5)
    plt.legend()

    # Subplot 4: Broadband Noise Spectrum
    plt.subplot(2, 2, 4)
    Y_target_ns = 20 * np.log10(np.abs(np.fft.rfft(res_noise['y_target'])) + 1e-12)
    Y_raw_ns = 20 * np.log10(np.abs(np.fft.rfft(res_noise['y_raw'])) + 1e-12)
    Y_comp_ns = 20 * np.log10(np.abs(np.fft.rfft(res_noise['y_comp'])) + 1e-12)
    plt.plot(f_axis, Y_raw_ns, color='#d62728', alpha=0.7, label='Raw Output')
    plt.plot(f_axis, Y_comp_ns, color='#1f77b4', linewidth=1.5, label='Linearized Output')
    plt.plot(f_axis, Y_target_ns, color='black', linestyle=':', label='Target Output')
    plt.xlim(50, 20000)
    plt.ylim(-110, -20)
    plt.title(f"Validation: Broadband Noise Spectrum (SDR Imp: {res_noise['improvement']:.1f}dB)", fontsize=12, fontweight='bold')
    plt.xlabel('Frequency (Hz)', fontsize=10)
    plt.ylabel('Magnitude (dBFS)', fontsize=10)
    plt.grid(True, which='both', linestyle='--', alpha=0.5)
    plt.legend()

    plt.tight_layout()
    output_val_img_path = os.path.join(output_dir, 'closed_loop_validation_results.png')
    plt.savefig(output_val_img_path, dpi=150)
    plt.close()

    print(f"Successfully generated validation comparison plot at: {output_val_img_path}")

    # Check if the suppression was successful on validation
    final_thd_db = history_err_db[-1, 1]
    initial_thd_db = history_err_db[0, 1]
    improvement = initial_thd_db - final_thd_db
    print(f"\nOptimization Result Summary:")
    print(f"  Initial Kernel THD Error: {initial_thd_db:.2f} dB")
    print(f"  Final Kernel THD Error:   {final_thd_db:.2f} dB")
    print(f"  Suppression Improvement:  {improvement:.2f} dB")

if __name__ == '__main__':
    run_closed_loop_training()
