import os
import json
import numpy as np

def run_wiener_simulation(condition_name, json_path, sigma_dbfs_list=[-20.0, -12.0, -6.0, 0.0]):
    if not os.path.exists(json_path):
        raise FileNotFoundError(f"Kernel file not found at {json_path}")

    with open(json_path, "r") as f:
        raw_data = json.load(f)

    metadata = raw_data["metadata"]
    sample_rate = metadata["sample_rate"]
    kernels = {k: np.array(v) for k, v in raw_data["time_domain"]["kernels"].items()}
    h1 = kernels["h1"]
    h2 = kernels["h2"]
    h3 = kernels["h3"]
    h4 = kernels["h4"]
    h5 = kernels["h5"]
    N = len(h1)

    print("\n======================================================================")
    print(f" Simulating Wiener (Hermite) Feedforward for: {condition_name.upper()}")
    print("======================================================================")
    print(f"Sample Rate: {sample_rate} Hz")
    print(f"Kernel Length: {N} samples ({N / sample_rate * 1000.0:.2f} ms)")

    # 1. Chebyshev to Power Series Conversion
    q0 = -0.5 * h2 + 0.125 * h4
    q1 = h1 - 0.75 * h3 + 0.3125 * h5  # True linear dynamic response
    q2 = h2 - h4
    q3 = h3 - 1.25 * h5
    q4 = h4
    q5 = h5

    # Scale the system using peak frequency response of q1
    Q1_fft_raw = np.fft.rfft(q1)
    G_scale = np.max(np.abs(Q1_fft_raw))
    print(f"Linear system scale factor (G_scale): {G_scale:.6e}")

    # Scaled Forward Power Series Kernels
    q_sc = [
        q0 / G_scale,
        q1 / G_scale,
        q2 / G_scale,
        q3 / G_scale,
        q4 / G_scale,
        q5 / G_scale
    ]
    Q_fft = [np.fft.rfft(q) for q in q_sc]

    # Define the active band filter (60 Hz to 17 kHz)
    freqs = np.fft.rfftfreq(N, d=1.0 / sample_rate)
    passband = (freqs >= 60.0) & (freqs <= 17000.0)
    bp_filter = np.zeros_like(freqs)
    bp_filter[passband] = 1.0
    for i in range(len(freqs)):
        f = freqs[i]
        if f < 60.0:
            bp_filter[i] = np.clip(0.5 * (1.0 - np.cos(np.pi * (f - 10.0) / 50.0)) if f >= 10.0 else 0.0, 0, 1)
        elif f > 17000.0:
            if f < 22000.0:
                bp_filter[i] = np.clip(0.5 * (1.0 + np.cos(np.pi * (f - 17000.0) / 5000.0)), 0, 1)
            else:
                bp_filter[i] = 0.0

    # Oversampled power evaluation (Power Series)
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

    # Power Series Forward Model (True simulation target)
    def power_series_forward(x):
        y = np.zeros_like(x)
        y += np.fft.irfft(np.fft.rfft(np.ones_like(x)) * Q_fft[0], n=len(x))
        for p in range(1, 6):
            y += np.fft.irfft(power_oversampled_fft(x, p) * Q_fft[p], n=len(x))
        return y

    def power_series_linear(x):
        return np.fft.irfft(power_oversampled_fft(x, 1) * Q_fft[1], n=len(x))

    def power_series_nonlinear(x):
        y = np.zeros_like(x)
        y += np.fft.irfft(np.fft.rfft(np.ones_like(x)) * Q_fft[0], n=len(x))
        for p in range(2, 6):
            y += np.fft.irfft(power_oversampled_fft(x, p) * Q_fft[p], n=len(x))
        return y

    # Design the linear inverse filter for Power Series (LICFF)
    F_lin_abs = np.abs(Q_fft[1])
    eps_in = 1e-6
    eps_out = 0.5
    eps_f = eps_in + (eps_out - eps_in) * (1.0 - bp_filter)
    F_inv_ps = np.conj(Q_fft[1]) / (F_lin_abs**2 + eps_f)
    F_inv_ps = F_inv_ps * bp_filter

    # Hermite oversampled evaluation
    def hermite_oversampled_fft(x, p, sigma_sq, L=8):
        N_x = len(x)
        X = np.fft.rfft(x)
        N_up = L * N_x
        X_up = np.zeros(N_up // 2 + 1, dtype=complex)
        X_up[: len(X)] = X * L
        x_up = np.fft.irfft(X_up, n=N_up)

        if p == 0:
            hep_up = np.ones_like(x_up)
        elif p == 1:
            hep_up = x_up
        elif p == 2:
            hep_up = x_up**2 - sigma_sq
        elif p == 3:
            hep_up = x_up**3 - 3.0 * sigma_sq * x_up
        elif p == 4:
            hep_up = x_up**4 - 6.0 * sigma_sq * x_up**2 + 3.0 * (sigma_sq**2)
        elif p == 5:
            hep_up = x_up**5 - 10.0 * sigma_sq * x_up**3 + 15.0 * (sigma_sq**2) * x_up
        else:
            raise ValueError(f"Order {p} not supported")

        Hep_up = np.fft.rfft(hep_up)
        Hep = Hep_up[: N_x // 2 + 1] / L
        return Hep

    # Evaluate THD helper
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

    # Evaluate SDR helper (relative to a reference signal)
    def compute_sdr(y_sig, y_ref):
        y_sig_ac = y_sig - np.mean(y_sig)
        y_ref_ac = y_ref - np.mean(y_ref)

        C = np.fft.irfft(np.fft.rfft(y_sig_ac) * np.conj(np.fft.rfft(y_ref_ac)), n=len(y_sig_ac))
        delay = np.argmax(np.abs(C))
        if delay > len(y_sig_ac) // 2:
            delay -= len(y_sig_ac)
        y_sig_aligned = np.roll(y_sig_ac, -delay)

        corr_val = C[delay]
        sign = np.sign(corr_val) if np.abs(corr_val) > 1e-12 else 1.0

        rms_ref = np.sqrt(np.mean(y_ref_ac**2))
        rms_sig = np.sqrt(np.mean(y_sig_aligned**2))
        y_sig_scaled = y_sig_aligned * sign * (rms_ref / (rms_sig + 1e-12))

        err = y_sig_scaled - y_ref_ac
        rms_err = np.sqrt(np.mean(err**2))
        sdr = 20 * np.log10(rms_ref / (rms_err + 1e-12))
        return sdr, delay

    # Define test signal: 1 kHz tone, amp = 0.30
    t = np.arange(N) / sample_rate
    f_test = 1000.0
    amp = 0.30
    u_tone = amp * np.sin(2 * np.pi * f_test * t)
    U_tone_fft = np.fft.rfft(u_tone)
    u_tone_filt = np.fft.irfft(U_tone_fft * bp_filter, n=N)

    # True target linear output
    y_ref_true = power_series_linear(u_tone_filt)

    # 2. Baseline Power Series Iterative LICFF (For comparison)
    u_comp_ps = u_tone_filt.copy()
    for _ in range(3):
        y_nl = power_series_nonlinear(u_comp_ps)
        Y_nl = np.fft.rfft(y_nl)
        y_comp_nl = np.fft.irfft(Y_nl * F_inv_ps, n=N)
        u_comp_ps = u_tone_filt - y_comp_nl
    y_out_ps = power_series_forward(u_comp_ps)
    thd_ps = compute_thd(y_out_ps, f_test)
    sdr_ps, _ = compute_sdr(y_out_ps, y_ref_true)

    print("\n--- Baseline Power Series LICFF ---")
    print(f"THD: {thd_ps:6.2f} dB | SDR (against True Linear): {sdr_ps:6.2f} dB")

    # 3. Wiener kernel simulations for different sigma values
    for sigma_dbfs in sigma_dbfs_list:
        sigma_linear = 10 ** (sigma_dbfs / 20.0)
        sigma_sq = sigma_linear ** 2

        # Convert scaled power series kernels to Hermite-Wiener kernels
        # Using analytical relations:
        g5_sc = q_sc[5].copy()
        g4_sc = q_sc[4].copy()
        g3_sc = q_sc[3] + 10.0 * sigma_sq * q_sc[5]
        g2_sc = q_sc[2] + 6.0 * sigma_sq * q_sc[4]
        g1_sc = q_sc[1] + 3.0 * sigma_sq * q_sc[3] + 15.0 * (sigma_sq**2) * q_sc[5]
        g0_sc = q_sc[0] + sigma_sq * q_sc[2] + 3.0 * (sigma_sq**2) * q_sc[4]

        G_fft = [
            np.fft.rfft(g0_sc),
            np.fft.rfft(g1_sc),
            np.fft.rfft(g2_sc),
            np.fft.rfft(g3_sc),
            np.fft.rfft(g4_sc),
            np.fft.rfft(g5_sc)
        ]

        # Hermite-Wiener Forward Model
        def wiener_forward(x):
            y = np.zeros_like(x)
            # p=0
            y += np.fft.irfft(hermite_oversampled_fft(x, 0, sigma_sq) * G_fft[0], n=len(x))
            # p=1 to 5
            for p in range(1, 6):
                y += np.fft.irfft(hermite_oversampled_fft(x, p, sigma_sq) * G_fft[p], n=len(x))
            return y

        def wiener_linear(x):
            return np.fft.irfft(hermite_oversampled_fft(x, 1, sigma_sq) * G_fft[1], n=len(x))

        def wiener_nonlinear(x):
            y = np.zeros_like(x)
            y += np.fft.irfft(hermite_oversampled_fft(x, 0, sigma_sq) * G_fft[0], n=len(x))
            for p in range(2, 6):
                y += np.fft.irfft(hermite_oversampled_fft(x, p, sigma_sq) * G_fft[p], n=len(x))
            return y

        # Verify Mathematical Equivalence of the Forward Models
        y_ps_test = power_series_forward(u_tone_filt)
        y_wie_test = wiener_forward(u_tone_filt)
        diff_rms = np.sqrt(np.mean((y_ps_test - y_wie_test)**2))
        print(f"\n--- Wiener Representation (σ = {sigma_dbfs} dBFS, σ² = {sigma_sq:.6e}) ---")
        print(f"Forward Model Equivalence Error (RMS Diff): {diff_rms:.6e}")
        assert diff_rms < 1e-10, f"Error: Forward models are not equivalent! RMS diff = {diff_rms}"

        # Design the inverse filter for the Wiener linear kernel
        G_lin_abs = np.abs(G_fft[1])
        eps_f_wie = eps_in + (eps_out - eps_in) * (1.0 - bp_filter)
        F_inv_wie = np.conj(G_fft[1]) / (G_lin_abs**2 + eps_f_wie)
        F_inv_wie = F_inv_wie * bp_filter

        # --- Method 1: Wiener Target Compensation ---
        # y_target = g1 * u_filt
        # We try to cancel y_nl_wie = g0*He0 + sum_{p=2..5} gp * He_p
        u_comp_wie_t1 = u_tone_filt.copy()
        for _ in range(3):
            y_nl = wiener_nonlinear(u_comp_wie_t1)
            Y_nl = np.fft.rfft(y_nl)
            y_comp_nl = np.fft.irfft(Y_nl * F_inv_wie, n=N)
            u_comp_wie_t1 = u_tone_filt - y_comp_nl
            
        y_out_wie_t1 = wiener_forward(u_comp_wie_t1)
        thd_t1 = compute_thd(y_out_wie_t1, f_test)
        sdr_t1_ref_wie, _ = compute_sdr(y_out_wie_t1, wiener_linear(u_tone_filt)) # relative to Wiener linear
        sdr_t1_ref_true, _ = compute_sdr(y_out_wie_t1, y_ref_true) # relative to True linear (q1)

        # --- Method 2: True Target Compensation ---
        # y_target = q1 * u_filt
        # u_comp = F_inv_wie * (q1 * u_filt) - F_inv_wie * y_nl_wie(u_comp)
        # In frequency domain: U_target_wie = Q_fft[1] * U_filt * F_inv_wie
        U_target_wie = Q_fft[1] * np.fft.rfft(u_tone_filt) * F_inv_wie
        u_comp_wie_t2 = np.fft.irfft(U_target_wie, n=N)
        
        for _ in range(3):
            y_nl = wiener_nonlinear(u_comp_wie_t2)
            Y_nl = np.fft.rfft(y_nl)
            y_comp_nl = np.fft.irfft(Y_nl * F_inv_wie, n=N)
            u_comp_wie_t2 = np.fft.irfft(U_target_wie, n=N) - y_comp_nl

        y_out_wie_t2 = wiener_forward(u_comp_wie_t2)
        thd_t2 = compute_thd(y_out_wie_t2, f_test)
        sdr_t2_ref_true, _ = compute_sdr(y_out_wie_t2, y_ref_true)

        print(f"Method 1 (Wiener Target) | THD: {thd_t1:6.2f} dB | SDR (vs Wiener Lin): {sdr_t1_ref_wie:6.2f} dB | SDR (vs True Lin): {sdr_t1_ref_true:6.2f} dB")
        print(f"Method 2 (True Target)   | THD: {thd_t2:6.2f} dB | SDR (vs True Lin): {sdr_t2_ref_true:6.2f} dB")

    # 4. Amplitude Sweep for True Target Wiener Compensation
    print("\n--- Amplitude Sweep (True Target Wiener vs. Power Series) ---")
    sweep_amps = [0.05, 0.15, 0.30, 0.45]
    print(f"  {'Amp':<6} | {'Method':<25} | {'THD (dB)':<10} | {'SDR (dB)':<10}")
    print("-" * 65)
    for a in sweep_amps:
        u_sweep = a * np.sin(2 * np.pi * f_test * t)
        U_sweep_fft = np.fft.rfft(u_sweep)
        u_sweep_filt = np.fft.irfft(U_sweep_fft * bp_filter, n=N)
        y_ref_sweep = power_series_linear(u_sweep_filt)

        # PS LICFF
        u_comp_ps = u_sweep_filt.copy()
        for _ in range(3):
            y_nl = power_series_nonlinear(u_comp_ps)
            Y_nl = np.fft.rfft(y_nl)
            y_comp_nl = np.fft.irfft(Y_nl * F_inv_ps, n=N)
            u_comp_ps = u_sweep_filt - y_comp_nl
        y_out_ps = power_series_forward(u_comp_ps)
        thd_ps_s = compute_thd(y_out_ps, f_test)
        sdr_ps_s, _ = compute_sdr(y_out_ps, y_ref_sweep)
        print(f"  {a:<6.2f} | {'Power Series LICFF':<25} | {thd_ps_s:>10.2f} | {sdr_ps_s:>10.2f}")

        # Wiener True Target with different sigmas
        for sigma_dbfs in [-12.0, -6.0, 0.0]:
            sigma_linear = 10 ** (sigma_dbfs / 20.0)
            sigma_sq = sigma_linear ** 2

            g5_sc = q_sc[5].copy()
            g4_sc = q_sc[4].copy()
            g3_sc = q_sc[3] + 10.0 * sigma_sq * q_sc[5]
            g2_sc = q_sc[2] + 6.0 * sigma_sq * q_sc[4]
            g1_sc = q_sc[1] + 3.0 * sigma_sq * q_sc[3] + 15.0 * (sigma_sq**2) * q_sc[5]
            g0_sc = q_sc[0] + sigma_sq * q_sc[2] + 3.0 * (sigma_sq**2) * q_sc[4]

            G_fft = [np.fft.rfft(g0_sc), np.fft.rfft(g1_sc), np.fft.rfft(g2_sc), np.fft.rfft(g3_sc), np.fft.rfft(g4_sc), np.fft.rfft(g5_sc)]
            
            # Hermite-Wiener Forward Models
            def wiener_forward_s(x):
                y = np.zeros_like(x)
                y += np.fft.irfft(hermite_oversampled_fft(x, 0, sigma_sq) * G_fft[0], n=len(x))
                for p in range(1, 6):
                    y += np.fft.irfft(hermite_oversampled_fft(x, p, sigma_sq) * G_fft[p], n=len(x))
                return y

            def wiener_nonlinear_s(x):
                y = np.zeros_like(x)
                y += np.fft.irfft(hermite_oversampled_fft(x, 0, sigma_sq) * G_fft[0], n=len(x))
                for p in range(2, 6):
                    y += np.fft.irfft(hermite_oversampled_fft(x, p, sigma_sq) * G_fft[p], n=len(x))
                return y

            G_lin_abs = np.abs(G_fft[1])
            eps_f_wie = eps_in + (eps_out - eps_in) * (1.0 - bp_filter)
            F_inv_wie = np.conj(G_fft[1]) / (G_lin_abs**2 + eps_f_wie)
            F_inv_wie = F_inv_wie * bp_filter

            U_target_wie = Q_fft[1] * np.fft.rfft(u_sweep_filt) * F_inv_wie
            u_comp_wie_t2 = np.fft.irfft(U_target_wie, n=N)
            for _ in range(3):
                y_nl = wiener_nonlinear_s(u_comp_wie_t2)
                Y_nl = np.fft.rfft(y_nl)
                y_comp_nl = np.fft.irfft(Y_nl * F_inv_wie, n=N)
                u_comp_wie_t2 = np.fft.irfft(U_target_wie, n=N) - y_comp_nl
            
            # Clip safely
            u_comp_wie_t2_clipped = np.clip(u_comp_wie_t2, -1.5, 1.5)
            y_out_wie_t2 = wiener_forward_s(u_comp_wie_t2_clipped)
            thd_t2 = compute_thd(y_out_wie_t2, f_test)
            sdr_t2, _ = compute_sdr(y_out_wie_t2, y_ref_sweep)
            print(f"  {a:<6.2f} | {f'Wiener True (s={sigma_dbfs})':<25} | {thd_t2:>10.2f} | {sdr_t2:>10.2f}")
        print("-" * 65)

if __name__ == "__main__":
    conditions = {
        "soft": "/Users/vach/MeasureLab/hammerstein_kernel_sample_soft_condition.json",
        "hard": "/Users/vach/MeasureLab/hammerstein_kernel_sample_hard_condition.json"
    }

    for name, path in conditions.items():
        run_wiener_simulation(name, path)
