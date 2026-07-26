import numpy as np
from scipy.signal import butter, lfilter
from scipy.interpolate import interp1d
from scipy.signal.windows import tukey

from src.core.realtime_sss_core import RealtimeSSSEngine
from src.core.hammerstein_model import estimate_hammerstein_kernels

# System Coefficients: w = x + d2*x^2 + d3*x^3 + d4*x^4 + d5*x^5
d_coeffs = {1: 1.0, 2: 0.04, 3: 0.025, 4: 0.012, 5: 0.006}
fc_lti = 1200.0  # Cutoff for LTI Lowpass Filter


def sim_dut_system(x, fs):
    """Simulates the forward Hammerstein system (Nonlinearity + LPF) for tests."""
    w = (
        d_coeffs[1] * x
        + d_coeffs[2] * (x**2)
        + d_coeffs[3] * (x**3)
        + d_coeffs[4] * (x**4)
        + d_coeffs[5] * (x**5)
    )
    b, a = butter(2, fc_lti / (fs / 2.0), btype="low")
    return lfilter(b, a, w)


def simulate_adaptive_sweep(start_freq, end_freq, duration, amplitude, max_harmonic, num_points, mu, fs):
    """Runs a simulated adaptive sweep to obtain the correction envelopes."""
    meas_freqs = np.logspace(np.log10(start_freq + 5.0), np.log10(end_freq - 10.0), num_points)
    F_corr = {n: np.zeros(num_points, dtype=complex) for n in range(2, max_harmonic + 1)}
    latency = 64.2
    analysis_cycles = 12.0
    min_analysis_window = 0.012

    # 4 iterations
    for _ in range(4):
        f1 = start_freq / 1.3
        f2 = end_freq * 1.15
        ln_ratio = np.log(f2 / f1)
        k_param = int(np.round((f1 / ln_ratio) * duration))
        L_param = k_param / f1
        T_actual = L_param * ln_ratio
        num_samples = int(np.round(fs * T_actual))
        t = np.arange(num_samples) / fs
        phase = 2 * np.pi * k_param * np.exp(t / L_param)
        f_inst = f1 * np.exp(t / L_param)

        x_base = np.sin(phase)
        win = tukey(num_samples, alpha=0.02)

        x_corr = x_base.copy()
        for n in range(2, max_harmonic + 1):
            F_func = interp1d(meas_freqs, F_corr[n], kind="linear", fill_value="extrapolate")
            F_inst_vals = F_func(f_inst)
            mag_vals = np.abs(F_inst_vals)
            phase_vals = np.angle(F_inst_vals)
            x_corr += mag_vals * np.sin(n * phase + phase_vals)

        x_corr_win = x_corr * amplitude * win
        x_base_win = x_base * amplitude * win

        engine = RealtimeSSSEngine(
            sample_rate=fs,
            sweep_duration=duration,
            start_freq=start_freq,
            end_freq=end_freq,
            output_amplitude=amplitude,
            max_harmonic=max_harmonic,
            analysis_cycles=analysis_cycles,
            num_meas_points=num_points,
            min_analysis_window=min_analysis_window,
        )
        engine.prepare_sweep()
        engine.set_latency(latency)

        frames = 1024
        max_blocks = int(np.ceil((engine.sweep_samples + latency) / frames))

        accumulated_results = np.zeros((max_blocks, max_harmonic), dtype=complex)
        block_counts = np.zeros(max_blocks, dtype=int)
        plot_freqs = np.zeros(max_blocks)

        total_len = len(x_corr_win) + int(np.ceil(latency))
        recorded_data = np.zeros((total_len, 2), dtype=np.float32)
        recorded_data[: len(x_corr_win), 1] = x_base_win
        recorded_data[: len(x_corr_win), 0] = sim_dut_system(x_corr_win, fs)

        for b in range(max_blocks):
            start_idx = b * frames
            end_idx = min(start_idx + frames, total_len)
            indata_block = np.zeros((frames, 2), dtype=np.float32)
            chunk_len = end_idx - start_idx
            if chunk_len > 0:
                indata_block[:chunk_len, :] = recorded_data[start_idx:end_idx, :]

            sig_in = indata_block[:, [0]]
            ref_in = indata_block[:, [1]]
            f_mid, results, _ = engine.process_input_block(sig_in, b, ref_in_block=ref_in)
            if engine.last_block_was_valid:
                accumulated_results[b, :] = results[:max_harmonic]
                block_counts[b] += 1
                plot_freqs[b] = f_mid

        valid_mask = block_counts > 0
        raw_freqs = plot_freqs[valid_mask]
        raw_results = accumulated_results[valid_mask, :]
        sort_idx = np.argsort(raw_freqs)
        raw_freqs_sorted = raw_freqs[sort_idx]
        raw_results_sorted = raw_results[sort_idx, :]

        H_meas = {}
        for n in range(1, max_harmonic + 1):
            real_func = interp1d(
                raw_freqs_sorted, raw_results_sorted[:, n - 1].real, kind="linear", fill_value="extrapolate"
            )
            imag_func = interp1d(
                raw_freqs_sorted, raw_results_sorted[:, n - 1].imag, kind="linear", fill_value="extrapolate"
            )
            H_meas[n] = real_func(meas_freqs) + 1j * imag_func(meas_freqs)

        H0_1 = H_meas[1].copy()

        def get_H0_1_interpolated(f_target_array, H0_1=H0_1):
            H_func_real = interp1d(meas_freqs, H0_1.real, kind="linear", fill_value="extrapolate")
            H_func_imag = interp1d(meas_freqs, H0_1.imag, kind="linear", fill_value="extrapolate")
            h_vals = H_func_real(f_target_array) + 1j * H_func_imag(f_target_array)
            mag = np.abs(h_vals)
            min_mag = 1e-4 * np.max(np.abs(H0_1))
            bad_mask = mag < min_mag
            if np.any(bad_mask):
                h_vals[bad_mask] = (h_vals[bad_mask] / (mag[bad_mask] + 1e-12)) * min_mag
            return h_vals

        for n in range(2, max_harmonic + 1):
            Hn_vals = H_meas[n]
            H1_nf_vals = get_H0_1_interpolated(n * meas_freqs)
            delta_corr = -Hn_vals / H1_nf_vals
            F_corr[n] += mu * delta_corr

    return F_corr, meas_freqs


def apply_counter_model(A, C_freqs, meas_freqs, fs):
    """Applies Counter Model kernels to input A."""
    N = len(A)
    f_fft = np.fft.rfftfreq(N, d=1.0 / fs)
    mx = np.zeros(N, dtype=np.float64)

    for p in range(1, len(C_freqs) + 1):
        Ap = A**p
        Ap_fft = np.fft.rfft(Ap, n=N)

        C_p = C_freqs[p - 1]
        C_real = np.interp(f_fft, meas_freqs, C_p.real)
        C_imag = np.interp(f_fft, meas_freqs, C_p.imag)
        C_fft = C_real + 1j * C_imag

        filtered_fft = Ap_fft * C_fft
        mx += np.fft.irfft(filtered_fft, n=N)

    return mx


def get_harmonic_level(y, fs, f_target, tolerance=5.0):
    """Finds peak magnitude of a harmonic in the Hanning-windowed spectrum."""
    N = len(y)
    Y = np.fft.rfft(y * np.hanning(N), n=N)
    mags = np.abs(Y) / (N / 4.0)
    freqs = np.fft.rfftfreq(N, d=1.0 / fs)
    mags_db = 20 * np.log10(mags + 1e-12)

    idx = np.argmin(np.abs(freqs - f_target))
    search_range = int(np.ceil(tolerance / (freqs[1] - freqs[0])))
    start = max(0, idx - search_range)
    end = min(len(mags_db), idx + search_range + 1)
    return np.max(mags_db[start:end])


def test_counter_model_harmonic_suppression():
    """Verifies that the Counter Model successfully separates kernels and reduces output harmonic distortion."""
    fs = 48000
    start_freq = 100.0
    end_freq = 2000.0
    duration = 3.0
    max_harmonic = 5
    num_points = 200
    mu = 0.5

    amplitudes = np.array([0.4, 0.7, 1.0])
    num_amps = len(amplitudes)

    avg_responses = None
    meas_freqs = None

    # Step 1: Run sweeps to gather correction envelopes
    for amp_idx, amp in enumerate(amplitudes):
        F_corr, m_freqs = simulate_adaptive_sweep(
            start_freq, end_freq, duration, amp, max_harmonic, num_points, mu, fs
        )
        if avg_responses is None:
            meas_freqs = m_freqs
            avg_responses = np.zeros((num_amps, len(meas_freqs), max_harmonic), dtype=complex)

        avg_responses[amp_idx, :, 0] = 0.0j
        for n in range(2, max_harmonic + 1):
            avg_responses[amp_idx, :, n - 1] = F_corr[n]

    # Step 2: Estimate Counter Model kernels
    C_freqs, sorted_freqs = estimate_hammerstein_kernels(
        amplitudes=amplitudes,
        avg_responses=avg_responses,
        plot_freqs=meas_freqs,
        max_harmonic=max_harmonic,
        sample_rate=fs,
        input_mode="XFER",
        ref_phase_only=False,
    )

    assert len(C_freqs) == max_harmonic
    assert len(sorted_freqs) == len(meas_freqs)

    # Step 3: Apply the Counter Model predistortion on a new single tone
    f0 = 200.0
    R_val = 0.6
    t_val = np.arange(fs * 2) / fs
    A_t = R_val * np.sin(2.0 * np.pi * f0 * t_val)

    # Output without predistortion
    y_uncorr = sim_dut_system(A_t, fs)

    # Output with predistortion
    Mx_A = apply_counter_model(A_t, C_freqs, sorted_freqs, fs)
    x_corr = A_t + Mx_A
    y_corr = sim_dut_system(x_corr, fs)

    # Step 4: Measure H2 and H3 harmonic levels and check suppression
    h2_uncorr = get_harmonic_level(y_uncorr, fs, 2.0 * f0)
    h2_corr = get_harmonic_level(y_corr, fs, 2.0 * f0)
    h2_reduction = h2_uncorr - h2_corr

    h3_uncorr = get_harmonic_level(y_uncorr, fs, 3.0 * f0)
    h3_corr = get_harmonic_level(y_corr, fs, 3.0 * f0)
    h3_reduction = h3_uncorr - h3_corr

    print(f"H2 Reduction: {h2_reduction:.2f} dB")
    print(f"H3 Reduction: {h3_reduction:.2f} dB")

    # Harmonic suppression should be at least 15 dB
    assert h2_reduction >= 15.0, f"H2 suppression is too low: {h2_reduction:.2f} dB"
    assert h3_reduction >= 15.0, f"H3 suppression is too low: {h3_reduction:.2f} dB"
