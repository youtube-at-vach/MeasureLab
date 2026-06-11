import os
import json
import numpy as np
from datetime import datetime

def run_ila_training(condition_name, json_path):
    # 1. Load measured kernels and metadata
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

    # 2. Chebyshev to Power Series Conversion
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

    # Forward model F simulator
    def forward_model(x):
        y = np.zeros_like(x)
        y += np.fft.irfft(np.fft.rfft(np.ones_like(x)) * Q0_fft, n=len(x))
        y += np.fft.irfft(np.fft.rfft(x) * Q1_fft, n=len(x))
        y += np.fft.irfft(np.fft.rfft(x**2) * Q2_fft, n=len(x))
        y += np.fft.irfft(np.fft.rfft(x**3) * Q3_fft, n=len(x))
        y += np.fft.irfft(np.fft.rfft(x**4) * Q4_fft, n=len(x))
        y += np.fft.irfft(np.fft.rfft(x**5) * Q5_fft, n=len(x))
        return y

    # 4. Design Inverse Wiener Filter for true linear response q1
    Q1_sc_power = np.abs(Q1_fft) ** 2
    beta = 0.005  # Regularization parameter
    Q1_inv = (np.conj(Q1_fft) / (Q1_sc_power + beta)) * bp_filter

    # 5. Iterative ILA Training Loop
    num_iterations = 8
    num_realizations = 4
    # Define training amplitudes (hard condition saturates early, so limit training range)
    if condition_name == "hard":
        training_amps = np.linspace(0.01, 0.30, 15)
    else:
        training_amps = np.linspace(0.01, 0.50, 15)
    N_fft_half = N // 2 + 1

    # Initialize W_filters with the linear inverse filter
    W_filters = np.zeros((5, N_fft_half), dtype=complex)
    W_filters[0] = Q1_inv

    # Seed generator for reproducibility
    rng = np.random.default_rng(42)

    def apply_ila_predistortion(u_val):
        x_pred = np.zeros_like(u_val)

        # Linear inverse (Order 1) is always applied
        u_pow_fft = np.fft.rfft(u_val)
        x_pred += np.fft.irfft(u_pow_fft * W_filters[0], n=len(u_val))

        # High-order non-linear terms (Order 2 to 5) with smooth fade-in
        amp_peak = np.max(np.abs(u_val))
        if amp_peak > 0.05:
            # Smooth fade factor from 0.0 to 1.0 between amp 0.05 and 0.15
            fade_factor = np.clip((amp_peak - 0.05) / 0.10, 0.0, 1.0)

            x_high = np.zeros_like(u_val)
            for p_idx, p in enumerate([2, 3, 4, 5], start=1):
                up_val = u_val**p
                W_p = W_filters[p_idx]
                x_high += np.fft.irfft(np.fft.rfft(up_val) * W_p, n=len(u_val))

            x_pred += fade_factor * x_high

        return np.clip(x_pred, -1.05, 1.05)

    print(f"\n--- Training ILA Inverse Model ({num_iterations} iterations, {num_realizations} realizations/amp) ---")

    # Set step size (relaxation factor) to stabilize convergence under strong non-linearities
    alpha = 0.20 if condition_name == "hard" else 0.60

    for iter_idx in range(num_iterations):
        X_train_fft = []
        Y_powers_fft = {p: [] for p in [1, 2, 3, 4, 5]}

        for amp in training_amps:
            for _ in range(num_realizations):
                # Generate white noise
                raw_noise = rng.normal(0.0, 1.0, N)
                # Band-limit to passband
                noise_filt = np.fft.irfft(np.fft.rfft(raw_noise) * bp_filter, n=N)
                # Normalize peak amplitude to amp
                peak = np.max(np.abs(noise_filt))
                if peak > 1e-12:
                    noise_filt = (noise_filt / peak) * amp

                # Predistort using current predistorter
                x_in = apply_ila_predistortion(noise_filt)
                y_out = forward_model(x_in)

                X_train_fft.append(np.fft.rfft(x_in))
                for p in [1, 2, 3, 4, 5]:
                    Y_powers_fft[p].append(np.fft.rfft(y_out**p))

        X_train_fft = np.array(X_train_fft)
        for p in [1, 2, 3, 4, 5]:
            Y_powers_fft[p] = np.array(Y_powers_fft[p])

        # New candidate filters to solve
        W_filters_new = np.zeros_like(W_filters)
        W_filters_new[0] = Q1_inv

        # Solve Weighted Least Squares at each frequency bin
        for fi in range(N_fft_half):
            if not passband[fi]:
                continue

            num_samples = len(X_train_fft)
            A_high = np.zeros((num_samples, 4), dtype=complex)
            for p_idx, p in enumerate([2, 3, 4, 5]):
                A_high[:, p_idx] = Y_powers_fft[p][:, fi]

            A_linear = Y_powers_fft[1][:, fi]
            b = X_train_fft[:, fi]
            b_res = b - A_linear * Q1_inv[fi]

            # WLS weights (use uniform weights to focus on large amplitude distortions rather than low-amp noise)
            weights = []
            for _ in training_amps:
                for _ in range(num_realizations):
                    weights.append(1.0)
            weights = np.array(weights)

            A_weighted = A_high * weights[:, np.newaxis]
            b_weighted = b_res * weights

            # Form normal equations
            AH_A = np.conj(A_weighted.T) @ A_weighted
            AH_b = np.conj(A_weighted.T) @ b_weighted

            # Condition-specific regularization for high orders to prevent divergence
            if condition_name == "hard":
                # Moderately strong regularization to control high-order kernels
                lambdas = np.array([3e2, 1e2, 3e2, 1e2])
            else:
                # Soft condition
                lambdas = np.array([1e2, 1e1, 1e2, 1e1])

            try:
                W_high = np.linalg.solve(AH_A + np.diag(lambdas), AH_b)
            except np.linalg.LinAlgError:
                W_high = np.linalg.lstsq(AH_A + np.diag(lambdas), AH_b, rcond=1e-4)[0]

            W_filters_new[1:, fi] = W_high

        # Apply relaxation update to stabilize the loop
        W_filters[1:] = (1.0 - alpha) * W_filters[1:] + alpha * W_filters_new[1:]

        # Apply Time-Domain Windowing to smooth identified high-order filters (narrower window)
        win = np.ones(N)
        N_keep = N // 8
        N_fade = N // 8
        fade = 0.5 * (1.0 + np.cos(np.pi * np.arange(N_fade) / N_fade))
        win[N_keep : N_keep + N_fade] = fade
        win[N_keep + N_fade :] = 0.0

        for p_idx in range(1, 5):
            w_time = np.fft.irfft(W_filters[p_idx], n=N)
            w_time_win = w_time * win
            W_filters[p_idx] = np.fft.rfft(w_time_win)

        print(f"  Iteration {iter_idx + 1}/{num_iterations} completed.")

    # 6. Post-Optimization Verification and Validation on Untrained Signals
    print("\n--- Verifying and Validating Linearization on Untrained Signals ---")
    t_verify = np.arange(N) / sample_rate
    b_amp = 0.30  # Peak validation amplitude

    # Reg Q1 linear target response
    Q1_fft_reg = Q1_fft * (np.conj(Q1_fft) / (Q1_sc_power + beta))

    def evaluate_test_signal(u_in, label):
        U_in_fft = np.fft.rfft(u_in)
        u_in_filt = np.fft.irfft(U_in_fft * bp_filter, n=N)
        y_target = np.fft.irfft(np.fft.rfft(u_in_filt) * Q1_fft_reg, n=N)
        y_raw = forward_model(u_in_filt)

        x_comp = apply_ila_predistortion(y_target)
        y_comp = forward_model(x_comp)

        # Circular cross-correlation via FFT using argmax to prevent phase inversion
        C_raw = np.fft.irfft(np.fft.rfft(y_raw) * np.conj(np.fft.rfft(y_target)), n=N)
        delay_raw = np.argmax(C_raw)
        if delay_raw > N // 2:
            delay_raw -= N
        y_raw_aligned = np.roll(y_raw, -delay_raw)

        C_comp = np.fft.irfft(np.fft.rfft(y_comp) * np.conj(np.fft.rfft(y_target)), n=N)
        delay_comp = np.argmax(C_comp)
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
    noise_fft = np.exp(1j * rng_val.uniform(0, 2 * np.pi, N // 2 + 1))
    noise_fft[0] = 0.0  # Zero DC
    noise_fft[-1] = 0.0  # Zero Nyquist
    u_noise_filt = np.fft.irfft(noise_fft * bp_filter, n=N)
    u_noise_filt = u_noise_filt / np.max(np.abs(u_noise_filt)) * b_amp
    res_noise = evaluate_test_signal(u_noise_filt, "Broadband Noise")

    # Print Validation Report
    print("\n" + "=" * 55)
    print("         GENERALIZATION VALIDATION REPORT (ILA)")
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

    # Convert back to time-domain to pad to length N
    g_final_time = [np.fft.irfft(W_filters[p], n=N) for p in range(5)]

    # 7. Save Inverse Hammerstein Model to JSON (with _ila suffix)
    inv_mags = {}
    inv_phases = {}
    for p in range(5):
        h_key = f"h{p + 1}"
        inv_mags[h_key] = 20 * np.log10(np.abs(W_filters[p]) + 1e-12)

        # No delay correction needed
        phase_rad = np.unwrap(np.angle(W_filters[p]))
        phase_deg = phase_rad * 180.0 / np.pi
        phase_deg = (phase_deg + 180) % 360 - 180
        inv_phases[h_key] = phase_deg

    inv_phases["ref_phase"] = inv_phases["h1"]

    inv_metadata = {
        "format_version": "1.0",
        "export_timestamp": datetime.now().isoformat(),
        "module": "ILA Inverse Hammerstein Predistorter",
        "sample_rate": float(sample_rate),
        "num_amplitudes": len(training_amps),
        "sweep_duration": float(N / sample_rate),
        "start_freq": 60.0,
        "end_freq": 17000.0,
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

    workspace_json_path = os.path.join("/Users/vach/MeasureLab", f"inverse_hammerstein_model_{condition_name}_ila.json")
    try:
        with open(workspace_json_path, "w", encoding="utf-8") as f:
            json.dump(inverse_model_data, f, indent=2, ensure_ascii=False)
        print(f"Successfully saved ILA inverse model JSON to: {workspace_json_path}")
    except Exception as e:
        print(f"Failed to save ILA inverse model to {workspace_json_path}: {e}")

    # Compute metric values for report
    return {
        "initial_thd_db": res_1k["thd_raw"],
        "final_thd_db": res_1k["thd_comp"],
        "improvement": res_1k["thd_raw"] - res_1k["thd_comp"],
        "total_sweeps": num_iterations * len(training_amps) * num_realizations,
        "res_1k": res_1k,
        "res_3k": res_3k,
        "res_2tone": res_2tone,
        "res_multi": res_multi,
        "res_noise": res_noise,
    }

if __name__ == "__main__":
    conditions = {
        "soft": "/Users/vach/MeasureLab/hammerstein_kernel_sample_soft_condition.json",
        "hard": "/Users/vach/MeasureLab/hammerstein_kernel_sample_hard_condition.json"
    }
    results = {}
    for name, path in conditions.items():
        print("\n" + "=" * 60)
        print(f" STARTING ILA OPTIMIZATION FOR: {name.upper()} CONDITION")
        print("=" * 60)
        results[name] = run_ila_training(name, path)

    # Print comparison report
    print("\n" + "=" * 80)
    print("                 ILA DPD COMPARISON REPORT (SOFT vs HARD)")
    print("=" * 80)
    print(f"  {'Metric':<28} |  {'Soft Condition':<22} |  {'Hard Condition':<22}")
    print("-" * 80)

    r_soft = results["soft"]
    r_hard = results["hard"]

    print(f"  {'Initial Tone THD Error':<28} |  {r_soft['initial_thd_db']:>7.2f} dB              |  {r_hard['initial_thd_db']:>7.2f} dB")
    print(f"  {'Final Tone THD Error':<28} |  {r_soft['final_thd_db']:>7.2f} dB              |  {r_hard['final_thd_db']:>7.2f} dB")
    print(f"  {'Suppression Improvement':<28} |  {r_soft['improvement']:>7.2f} dB              |  {r_hard['improvement']:>7.2f} dB")
    print(f"  {'Total Sweeps Needed':<28} |  {r_soft['total_sweeps']:>5d} sweeps             |  {r_hard['total_sweeps']:>5d} sweeps")
    print("-" * 80)
    print("  THD Performance (Lower is Better):")

    # 1kHz Tone (Original) THD
    imp_1k_thd_soft = r_soft['res_1k']['thd_raw'] - r_soft['res_1k']['thd_comp']
    imp_1k_thd_hard = r_hard['res_1k']['thd_raw'] - r_hard['res_1k']['thd_comp']
    print(f"  - 1kHz Tone (Original)       |  {r_soft['res_1k']['thd_raw']:>5.1f} -> {r_soft['res_1k']['thd_comp']:>5.1f} dB      |  {r_hard['res_1k']['thd_raw']:>5.1f} -> {r_hard['res_1k']['thd_comp']:>5.1f} dB")
    print(f"                               |  (Imp: {imp_1k_thd_soft:>6.2f} dB)         |  (Imp: {imp_1k_thd_hard:>6.2f} dB)")

    # 3kHz Tone (Untrained) THD
    imp_3k_thd_soft = r_soft['res_3k']['thd_raw'] - r_soft['res_3k']['thd_comp']
    imp_3k_thd_hard = r_hard['res_3k']['thd_raw'] - r_hard['res_3k']['thd_comp']
    print(f"  - 3kHz Tone (Untrained)      |  {r_soft['res_3k']['thd_raw']:>5.1f} -> {r_soft['res_3k']['thd_comp']:>5.1f} dB      |  {r_hard['res_3k']['thd_raw']:>5.1f} -> {r_hard['res_3k']['thd_comp']:>5.1f} dB")
    print(f"                               |  (Imp: {imp_3k_thd_soft:>6.2f} dB)         |  (Imp: {imp_3k_thd_hard:>6.2f} dB)")

    print("-" * 80)
    print("  SDR Performance (Higher is Better):")

    # 1kHz Tone (Original) SDR
    print(f"  - 1kHz Tone (Original)       |  {r_soft['res_1k']['sdr_raw']:>5.1f} -> {r_soft['res_1k']['sdr_comp']:>5.1f} dB      |  {r_hard['res_1k']['sdr_raw']:>5.1f} -> {r_hard['res_1k']['sdr_comp']:>5.1f} dB")
    print(f"                               |  (Imp: {r_soft['res_1k']['improvement']:>6.2f} dB)         |  (Imp: {r_hard['res_1k']['improvement']:>6.2f} dB)")

    # 3kHz Tone (Untrained) SDR
    print(f"  - 3kHz Tone (Untrained)      |  {r_soft['res_3k']['sdr_raw']:>5.1f} -> {r_soft['res_3k']['sdr_comp']:>5.1f} dB      |  {r_hard['res_3k']['sdr_raw']:>5.1f} -> {r_hard['res_3k']['sdr_comp']:>5.1f} dB")
    print(f"                               |  (Imp: {r_soft['res_3k']['improvement']:>6.2f} dB)         |  (Imp: {r_hard['res_3k']['improvement']:>6.2f} dB)")

    # Two-Tone (Untrained)
    print(f"  - Two-Tone (1.0k + 1.5k)     |  {r_soft['res_2tone']['sdr_raw']:>5.1f} -> {r_soft['res_2tone']['sdr_comp']:>5.1f} dB      |  {r_hard['res_2tone']['sdr_raw']:>5.1f} -> {r_hard['res_2tone']['sdr_comp']:>5.1f} dB")
    print(f"                               |  (Imp: {r_soft['res_2tone']['improvement']:>6.2f} dB)         |  (Imp: {r_hard['res_2tone']['improvement']:>6.2f} dB)")

    # Multi-Tone (5 freqs)
    print(f"  - Multi-Tone (5 freqs)       |  {r_soft['res_multi']['sdr_raw']:>5.1f} -> {r_soft['res_multi']['sdr_comp']:>5.1f} dB      |  {r_hard['res_multi']['sdr_raw']:>5.1f} -> {r_hard['res_multi']['sdr_comp']:>5.1f} dB")
    print(f"                               |  (Imp: {r_soft['res_multi']['improvement']:>6.2f} dB)         |  (Imp: {r_hard['res_multi']['improvement']:>6.2f} dB)")

    # Broadband Noise
    print(f"  - Broadband Noise            |  {r_soft['res_noise']['sdr_raw']:>5.1f} -> {r_soft['res_noise']['sdr_comp']:>5.1f} dB      |  {r_hard['res_noise']['sdr_raw']:>5.1f} -> {r_hard['res_noise']['sdr_comp']:>5.1f} dB")
    print(f"                               |  (Imp: {r_soft['res_noise']['improvement']:>6.2f} dB)         |  (Imp: {r_hard['res_noise']['improvement']:>6.2f} dB)")
    print("=" * 80)
