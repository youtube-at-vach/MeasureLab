import os
import json
import numpy as np
from scipy.signal import windows

def run_simulation(condition_name, json_path):
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

    print(f"\n======================================================================")
    print(f" Simulating Feedforward for: {condition_name.upper()} CONDITION")
    print(f"======================================================================")
    print(f"Sample Rate: {sample_rate} Hz")
    print(f"Kernel Length: {N} samples ({N / sample_rate * 1000.0:.2f} ms)")

    # 1. Chebyshev to Power Series Conversion
    q0 = -h2 + h4
    q1 = h1 - 3 * h3 + 5 * h5  # True linear dynamic response
    q2 = 2 * h2 - 8 * h4
    q3 = 4 * h3 - 20 * h5
    q4 = 8 * h4
    q5 = 16 * h5

    # Scale the system using peak frequency response of q1
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

    Q_fft = [
        np.fft.rfft(q0_sc),
        np.fft.rfft(q1_sc),
        np.fft.rfft(q2_sc),
        np.fft.rfft(q3_sc),
        np.fft.rfft(q4_sc),
        np.fft.rfft(q5_sc)
    ]

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

    # Oversampled power evaluation to prevent aliasing
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

    # Forward model simulators
    def forward_model(x):
        y = np.zeros_like(x)
        y += np.fft.irfft(np.fft.rfft(np.ones_like(x)) * Q_fft[0], n=len(x))
        for p in range(1, 6):
            y += np.fft.irfft(power_oversampled_fft(x, p) * Q_fft[p], n=len(x))
        return y

    def linear_output(x):
        return np.fft.irfft(power_oversampled_fft(x, 1) * Q_fft[1], n=len(x))

    def nonlinear_output(x):
        y = np.zeros_like(x)
        y += np.fft.irfft(np.fft.rfft(np.ones_like(x)) * Q_fft[0], n=len(x))
        for p in range(2, 6):
            y += np.fft.irfft(power_oversampled_fft(x, p) * Q_fft[p], n=len(x))
        return y

    # Design the linear inverse filter (F_inv)
    F_lin_abs = np.abs(Q_fft[1])
    eps_in = 1e-6
    eps_out = 0.5
    eps_f = eps_in + (eps_out - eps_in) * (1.0 - bp_filter)
    F_inv = np.conj(Q_fft[1]) / (F_lin_abs**2 + eps_f)
    F_inv = F_inv * bp_filter # Restrict inverse to active band

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

    # Evaluate SDR helper (with AC coupling and polarity alignment)
    def compute_sdr(y_sig, y_ref):
        # Remove DC component (AC couple)
        y_sig_ac = y_sig - np.mean(y_sig)
        y_ref_ac = y_ref - np.mean(y_ref)

        # Align signals using cross correlation to find delay
        C = np.fft.irfft(np.fft.rfft(y_sig_ac) * np.conj(np.fft.rfft(y_ref_ac)), n=len(y_sig_ac))
        delay = np.argmax(np.abs(C))
        if delay > len(y_sig_ac) // 2:
            delay -= len(y_sig_ac)
        y_sig_aligned = np.roll(y_sig_ac, -delay)

        # Detect and compensate polarity/sign
        corr_val = C[delay]
        sign = np.sign(corr_val) if np.abs(corr_val) > 1e-12 else 1.0

        # Gain-normalization to avoid linear gain differences affecting SDR
        rms_ref = np.sqrt(np.mean(y_ref_ac**2))
        rms_sig = np.sqrt(np.mean(y_sig_aligned**2))
        y_sig_scaled = y_sig_aligned * sign * (rms_ref / (rms_sig + 1e-12))

        err = y_sig_scaled - y_ref_ac
        rms_err = np.sqrt(np.mean(err**2))
        sdr = 20 * np.log10(rms_ref / (rms_err + 1e-12))
        return sdr, delay

    # 2. Setup Best Compensation Logic (Iterative LICFF)
    def run_compensation(u_in, method, iters=3):
        U_in_fft = np.fft.rfft(u_in)
        u_in_filt = np.fft.irfft(U_in_fft * bp_filter, n=N)

        if method == "uncomp":
            return forward_model(u_in_filt)

        elif method == "iterative":
            # Best Method: Iterative Linear-Inverse Compensated Feedforward
            u_comp = u_in_filt.copy()
            for _ in range(iters):
                y_nl = nonlinear_output(u_comp)
                Y_nl = np.fft.rfft(y_nl)
                y_comp_nl = np.fft.irfft(Y_nl * F_inv, n=N)
                u_comp = u_in_filt - y_comp_nl
                u_comp = np.clip(u_comp, -1.5, 1.5)
            return forward_model(u_comp)

    # 3. Tone Evaluations (Fixed 1 kHz Tone, Amp = 0.30)
    t = np.arange(N) / sample_rate
    f_test = 1000.0
    amp = 0.30

    u_tone = amp * np.sin(2 * np.pi * f_test * t)
    y_ref = linear_output(u_tone)

    methods = {
        "uncomp": "Baseline (Uncompensated)",
        "iterative": "Iterative LICFF (Best Method)"
    }
    results = {}

    for m in methods.keys():
        y_out = run_compensation(u_tone, m, iters=3)
        thd = compute_thd(y_out, f_test)
        sdr, delay = compute_sdr(y_out, y_ref)
        results[m] = {"thd": thd, "sdr": sdr, "delay": delay}

    print("\n--- 1 kHz Tone Simulation Results (Amp = 0.30) ---")
    for m, label in methods.items():
        res = results[m]
        print(f"{label:<30} | THD: {res['thd']:6.2f} dB | SDR: {res['sdr']:6.2f} dB | Delay: {res['delay']} samples")

    # 4. Amplitude Sweep for 1 kHz Tone
    print("\n--- Amplitude Sweep (1 kHz Tone) ---")
    sweep_amps = [0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45]
    print(f"  {'Amp':<6} | {'Method':<20} | {'THD (dB)':<10} | {'SDR (dB)':<10} | {'Clipping?':<10}")
    print("-" * 65)
    for a in sweep_amps:
        u_sweep = a * np.sin(2 * np.pi * f_test * t)
        y_ref_sweep = linear_output(u_sweep)
        for m in methods.keys():
            U_in_fft = np.fft.rfft(u_sweep)
            u_in_filt = np.fft.irfft(U_in_fft * bp_filter, n=N)
            is_clipped = False

            if m == "uncomp":
                y_out = forward_model(u_in_filt)
            elif m == "iterative":
                u_comp = u_in_filt.copy()
                for _ in range(3):
                    y_nl = nonlinear_output(u_comp)
                    Y_nl = np.fft.rfft(y_nl)
                    y_comp_nl = np.fft.irfft(Y_nl * F_inv, n=N)
                    u_comp = u_in_filt - y_comp_nl
                if np.any(np.abs(u_comp) > 1.49):
                    is_clipped = True
                u_comp = np.clip(u_comp, -1.5, 1.5)
                y_out = forward_model(u_comp)

            thd_s = compute_thd(y_out, f_test)
            sdr_s, _ = compute_sdr(y_out, y_ref_sweep)
            clip_str = "CLIPPED!" if is_clipped else "No"
            print(f"  {a:<6.2f} | {m:<20} | {thd_s:>10.2f} | {sdr_s:>10.2f} | {clip_str:<10}")
        print("-" * 65)

    # 5. Untrained Signals Evaluation (Amp = 0.30)
    print("\n--- Untrained Signals Generalization (Amp = 0.30) ---")
    untrained_signals = {
        "3kHz Tone (Untrained Freq)": amp * np.sin(2 * np.pi * 3000.0 * t),
        "Two-Tone (1.0k + 1.5k)": (amp / 2) * (np.sin(2 * np.pi * 1000.0 * t) + np.sin(2 * np.pi * 1500.0 * t)),
        "Multi-Tone (5 freqs)": (amp / 2.5) * sum(np.sin(2 * np.pi * f * t) for f in [300, 700, 1300, 2700, 5500]),
    }

    rng = np.random.default_rng(99)
    noise_fft = np.exp(1j * rng.uniform(0, 2 * np.pi, N // 2 + 1))
    noise_fft[0] = 0.0
    noise_fft[-1] = 0.0
    u_noise = np.fft.irfft(noise_fft * bp_filter, n=N)
    u_noise = u_noise / np.max(np.abs(u_noise)) * amp
    untrained_signals["Broadband Noise"] = u_noise

    gen_results = {}
    for name, u_sig in untrained_signals.items():
        y_ref_sig = linear_output(u_sig)
        gen_results[name] = {}
        for m in methods.keys():
            y_out = run_compensation(u_sig, m, iters=3)
            sdr, _ = compute_sdr(y_out, y_ref_sig)
            gen_results[name][m] = sdr

    for name, sdr_dict in gen_results.items():
        print(f"\nSignal: {name}")
        for m in methods.keys():
            print(f"  {m:<10} SDR: {sdr_dict[m]:6.2f} dB (Improvement: {sdr_dict[m] - sdr_dict['uncomp']:+6.2f} dB)")

    return {
        "tone_results": results,
        "gen_results": gen_results
    }

if __name__ == "__main__":
    conditions = {
        "soft": "/Users/vach/MeasureLab/hammerstein_kernel_sample_soft_condition.json",
        "hard": "/Users/vach/MeasureLab/hammerstein_kernel_sample_hard_condition.json"
    }

    summary = {}
    for name, path in conditions.items():
        summary[name] = run_simulation(name, path)
