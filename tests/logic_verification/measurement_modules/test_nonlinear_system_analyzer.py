import numpy as np
from src.core.nonlinear_analyzer_core import (
    generate_sss_and_inverse,
    deconvolve_signal,
    process_amplitude_responses,
)


def test_nonlinear_analyzer_linear():
    """
    Verifies that for a pure linear system (y = x),
    the linear fundamental kernel h1 is detected at ~0 dB,
    and higher-order kernels h2 to h5 are highly suppressed (<-50 dB).
    """
    sample_rate = 44100
    sweep_duration = 2.0
    start_freq = 20.0
    end_freq = 20000.0
    P = 5

    # 1. Generate sweep
    sss, _ = generate_sss_and_inverse(sample_rate, sweep_duration, start_freq, end_freq)

    # 2. Setup Amplitudes
    max_amp = 0.5
    num_amplitudes = 5
    amplitudes = np.linspace(0.2, 1.0, num_amplitudes) * max_amp

    # 3. Simulate Linear System: y = x
    responses_meas = []
    responses_ref = []

    for amp in amplitudes:
        x_sig = amp * sss
        y_sig = x_sig  # y = x

        padding = np.zeros(int(0.2 * sample_rate))
        x_sig_padded = np.concatenate([x_sig, padding])
        y_sig_padded = np.concatenate([y_sig, padding])

        # Deconvolution in frequency domain
        ir_ref = deconvolve_signal(x_sig_padded, sss)
        ir_meas = deconvolve_signal(y_sig_padded, sss)

        responses_ref.append(ir_ref)
        responses_meas.append(ir_meas)

    # 4. Process
    (
        freqs,
        mags,
        phases,
        time_ms,
        separated_kernels_data,
    ) = process_amplitude_responses(
        responses_meas,
        responses_ref,
        sample_rate,
        start_freq,
        end_freq,
        input_mode="XFER",
        latency_sec=0.0,
        sweep_duration=sweep_duration,
        P=P,
        amplitudes=amplitudes,
    )

    # Filter to stable frequency region (200 Hz to 15 kHz) for assertions
    assert_mask = (freqs >= 200.0) & (freqs <= 15000.0)

    # h1 linear response should be very close to 0 dB gain across the band
    assert np.all(np.abs(mags["h1"][assert_mask]) < 1.0), "h1 linear response is not flat/near 0 dB"

    # Higher order responses (h2 to h5) must be heavily suppressed (<-50 dB)
    for p in range(2, 6):
        h_key = f"h{p}"
        max_harmonic_db = np.max(mags[h_key][assert_mask])
        assert max_harmonic_db < -50.0, (
            f"Pseudo-kernel {h_key} was detected for a linear system! "
            f"Max level = {max_harmonic_db:.2f} dB, expected <-50 dB."
        )


def test_nonlinear_analyzer_quadratic():
    """
    Verifies that for a quadratic non-linear system (y = x + 0.1 * x^2),
    h2 is detected as the dominant non-linear harmonic component and matches
    the simulated polynomial coefficient of 0.1 (-20 dB).
    """
    sample_rate = 44100
    sweep_duration = 2.0
    start_freq = 20.0
    end_freq = 20000.0
    P = 5

    sss, _ = generate_sss_and_inverse(sample_rate, sweep_duration, start_freq, end_freq)

    max_amp = 0.5
    num_amplitudes = 5
    amplitudes = np.linspace(0.2, 1.0, num_amplitudes) * max_amp

    responses_meas = []
    responses_ref = []

    a = 0.1
    for amp in amplitudes:
        x_sig = amp * sss
        y_sig = x_sig + a * (x_sig**2)

        padding = np.zeros(int(0.2 * sample_rate))
        x_sig_padded = np.concatenate([x_sig, padding])
        y_sig_padded = np.concatenate([y_sig, padding])

        ir_ref = deconvolve_signal(x_sig_padded, sss)
        ir_meas = deconvolve_signal(y_sig_padded, sss)

        responses_ref.append(ir_ref)
        responses_meas.append(ir_meas)

    (
        freqs,
        mags,
        phases,
        time_ms,
        separated_kernels_data,
    ) = process_amplitude_responses(
        responses_meas,
        responses_ref,
        sample_rate,
        start_freq,
        end_freq,
        input_mode="XFER",
        latency_sec=0.0,
        sweep_duration=sweep_duration,
        P=P,
        amplitudes=amplitudes,
    )

    # Filter to stable frequency region (200 Hz to 15 kHz) for assertions
    assert_mask = (freqs >= 200.0) & (freqs <= 15000.0)

    # h1 is fundamental (near 0 dB)
    assert np.all(np.abs(mags["h1"][assert_mask]) < 1.5)

    # h2 should be the dominant distortion component
    h2_avg = np.mean(mags["h2"][assert_mask])
    assert h2_avg > -50.0, f"h2 not dominant, average magnitude: {h2_avg} dB"

    # Check that h2 matches simulated coefficient a=0.1 -> -20 dB
    assert -23.0 < h2_avg < -17.0, f"h2 level {h2_avg} dB deviates from expected polynomial weight (~-20 dB)"

    # h3, h4, h5 should be suppressed (<-30 dB)
    for p in [3, 4, 5]:
        h_key = f"h{p}"
        max_val = np.max(mags[h_key][assert_mask])
        assert max_val < -30.0, f"Harmonic {h_key} detected in quadratic system: {max_val:.2f} dB"


def test_nonlinear_analyzer_cubic():
    """
    Verifies that for a cubic non-linear system (y = x + 0.15 * x^3),
    h3 is detected as the dominant non-linear harmonic component and matches
    the simulated polynomial coefficient of 0.15 (-16.48 dB).
    """
    sample_rate = 44100
    sweep_duration = 2.0
    start_freq = 20.0
    end_freq = 20000.0
    P = 5

    sss, _ = generate_sss_and_inverse(sample_rate, sweep_duration, start_freq, end_freq)

    max_amp = 0.5
    num_amplitudes = 5
    amplitudes = np.linspace(0.2, 1.0, num_amplitudes) * max_amp

    responses_meas = []
    responses_ref = []

    b = 0.15
    for amp in amplitudes:
        x_sig = amp * sss
        y_sig = x_sig + b * (x_sig**3)

        padding = np.zeros(int(0.2 * sample_rate))
        x_sig_padded = np.concatenate([x_sig, padding])
        y_sig_padded = np.concatenate([y_sig, padding])

        ir_ref = deconvolve_signal(x_sig_padded, sss)
        ir_meas = deconvolve_signal(y_sig_padded, sss)

        responses_ref.append(ir_ref)
        responses_meas.append(ir_meas)

    (
        freqs,
        mags,
        phases,
        time_ms,
        separated_kernels_data,
    ) = process_amplitude_responses(
        responses_meas,
        responses_ref,
        sample_rate,
        start_freq,
        end_freq,
        input_mode="XFER",
        latency_sec=0.0,
        sweep_duration=sweep_duration,
        P=P,
        amplitudes=amplitudes,
    )

    # Filter to stable frequency region (200 Hz to 15 kHz) for assertions
    assert_mask = (freqs >= 200.0) & (freqs <= 15000.0)

    # h1 is fundamental (near 0 dB)
    assert np.all(np.abs(mags["h1"][assert_mask]) < 1.5)

    # h3 should be the dominant distortion component
    # y = x + 0.15 * x^3. Power series kernel h3 is 0.15 -> 20 log10(0.15) = -16.48 dB.
    h3_avg = np.mean(mags["h3"][assert_mask])
    assert -19.5 < h3_avg < -13.5, f"h3 level {h3_avg} dB deviates from expected (~-16.5 dB)"

    # h2, h4, h5 should be suppressed (<-28 dB)
    for p in [2, 4, 5]:
        h_key = f"h{p}"
        max_val = np.max(mags[h_key][assert_mask])
        assert max_val < -28.0, f"Harmonic {h_key} detected in cubic system: {max_val:.2f} dB"


def test_nonlinear_analyzer_comprehensive():
    """
    Comprehensive physical validation:
    1. Amplitude Invariance: separation results h_p are independent of maximum measurement amplitude R.
    2. Gating and Alignment: harmonic impulse peaks align exactly to t=0 (gate center).
    3. Leakage Suppression: h1 is correctly cleaned from g3/g5 leakage using Chebyshev algebraic subtraction.
    4. Coefficient Recovery: y = a1*x + a2*x^2 + a3*x^3 + a4*x^4 + a5*x^5 matches theoretical coefficients.
    5. Phase sanity: Phase does not wrap or rotate abnormally across the sweep band.
    """
    sample_rate = 44100
    sweep_duration = 2.0
    start_freq = 20.0
    end_freq = 20000.0
    P = 5

    sss, _ = generate_sss_and_inverse(sample_rate, sweep_duration, start_freq, end_freq)

    # Expected magnitudes (dB) based on simulated power series coefficients:
    # a1 = 1.0   -> 0.0 dB
    # a2 = 0.1   -> -20.0 dB
    # a3 = 0.08  -> -21.94 dB
    # a4 = 0.04  -> -27.96 dB
    # a5 = 0.02  -> -33.98 dB
    expected_mags = {
        "h1": 0.0,
        "h2": -20.0,
        "h3": 20 * np.log10(0.08),
        "h4": 20 * np.log10(0.04),
        "h5": 20 * np.log10(0.02),
    }

    def simulate_and_process(max_amp):
        num_amplitudes = 5
        amplitudes = np.linspace(0.2, 1.0, num_amplitudes) * max_amp

        responses_meas = []
        responses_ref = []

        for amp in amplitudes:
            x_sig = amp * sss
            # Nonlinear polynomial excitation
            y_sig = (
                1.0 * x_sig
                + 0.1 * (x_sig**2)
                + 0.08 * (x_sig**3)
                + 0.04 * (x_sig**4)
                + 0.02 * (x_sig**5)
            )

            padding = np.zeros(int(0.2 * sample_rate))
            x_sig_padded = np.concatenate([x_sig, padding])
            y_sig_padded = np.concatenate([y_sig, padding])

            ir_ref = deconvolve_signal(x_sig_padded, sss)
            ir_meas = deconvolve_signal(y_sig_padded, sss)

            responses_ref.append(ir_ref)
            responses_meas.append(ir_meas)

        return process_amplitude_responses(
            responses_meas,
            responses_ref,
            sample_rate,
            start_freq,
            end_freq,
            input_mode="XFER",
            latency_sec=0.0,
            sweep_duration=sweep_duration,
            P=P,
            amplitudes=amplitudes,
        )

    # 1. Verify Amplitude Invariance (R=0.4 vs R=0.7)
    res1 = simulate_and_process(0.4)
    res2 = simulate_and_process(0.7)

    # Filter to stable frequency region (200 Hz to 15 kHz) for assertions
    freqs = res1[0]
    assert_mask = (freqs >= 200.0) & (freqs <= 15000.0)

    # Mags should be highly similar (within 2 dB error margin inside stable bandwidth)
    for k in ["h1", "h2", "h3", "h4", "h5"]:
        diff = np.abs(np.mean(res1[1][k][assert_mask]) - np.mean(res2[1][k][assert_mask]))
        assert diff < 2.0, f"Amplitude invariance failed for {k}! Diff = {diff:.2f} dB"

    # 2. Alignment validation: All separated kernels should peak at t=0
    for p in range(P):
        kernel = res1[4][p]
        peak_idx = np.argmax(np.abs(kernel))
        peak_time = res1[3][peak_idx]
        assert np.abs(peak_time) < 0.5, f"Kernel h{p+1} peak is misaligned! Peak at {peak_time:.2f} ms"

    # 3. Leakage Suppression & Coefficient Recovery
    h1_mag_avg = np.mean(res1[1]["h1"][assert_mask])
    assert np.abs(h1_mag_avg - expected_mags["h1"]) < 1.0, (
        f"h1 leakage removal failed. Level: {h1_mag_avg:.2f} dB, expected: {expected_mags['h1']:.2f} dB"
    )

    # Higher orders should match expected coefficients within acceptable tolerances
    for k in ["h2", "h3", "h4", "h5"]:
        mag_avg = np.mean(res1[1][k][assert_mask])
        tolerance = 2.0
        assert np.abs(mag_avg - expected_mags[k]) < tolerance, (
            f"Power series kernel {k} deviated. Got {mag_avg:.2f} dB, expected {expected_mags[k]:.2f} dB"
        )

    # 4. Phase sanity: Verify that phase response for h1 is stable and doesn't rotate abnormally (linear phase close to 0)
    h1_phase = res1[2]["h1"][assert_mask]
    assert np.all(np.abs(h1_phase) < 10.0), f"Phase response for h1 is wrapping abnormally: {np.max(np.abs(h1_phase))} deg"


def test_nonlinear_analyzer_phase_shift():
    """
    Verifies that the Parallel Hammerstein separation accurately reconstructs
    frequency-dependent phase shifts (specifically time delays) for each order
    by using a baseline loopback calibration to cancel stationary systematic offsets.
    """
    sample_rate = 44100
    sweep_duration = 2.0
    start_freq = 20.0
    end_freq = 20000.0
    P = 5

    # 1. Generate sweep
    sss, _ = generate_sss_and_inverse(sample_rate, sweep_duration, start_freq, end_freq)

    # 2. Setup Amplitudes
    max_amp = 0.5
    num_amplitudes = 5
    amplitudes = np.linspace(0.2, 1.0, num_amplitudes) * max_amp

    a = {
        1: 1.0,
        2: 0.1,
        3: 0.08,
        4: 0.04,
        5: 0.02
    }

    # Frequency domain delay application helper
    def apply_delay(x, delay_samples):
        N = len(x)
        X = np.fft.rfft(x)
        freqs = np.fft.rfftfreq(N, 1.0 / sample_rate)
        H = np.exp(-1j * 2 * np.pi * freqs * delay_samples / sample_rate)
        return np.fft.irfft(X * H, n=N)

    def run_simulation(delays_dict):
        responses_meas = []
        responses_ref = []
        for amp in amplitudes:
            x_sig = amp * sss
            y_sig = np.zeros_like(x_sig)

            for p in range(1, P + 1):
                comp = a[p] * (x_sig ** p)
                y_sig += apply_delay(comp, delays_dict[p])

            padding = np.zeros(int(0.2 * sample_rate))
            x_sig_padded = np.concatenate([x_sig, padding])
            y_sig_padded = np.concatenate([y_sig, padding])

            ir_ref = deconvolve_signal(x_sig_padded, sss)
            ir_meas = deconvolve_signal(y_sig_padded, sss)

            responses_ref.append(ir_ref)
            responses_meas.append(ir_meas)

        return process_amplitude_responses(
            responses_meas,
            responses_ref,
            sample_rate,
            start_freq,
            end_freq,
            input_mode="XFER",
            latency_sec=0.0,
            sweep_duration=sweep_duration,
            P=P,
            amplitudes=amplitudes,
        )

    # --- Baseline Simulation (delays = 0) ---
    zero_delays = {1: 0.0, 2: 0.0, 3: 0.0, 4: 0.0, 5: 0.0}
    freqs, _, phases_zero, _, _ = run_simulation(zero_delays)

    assert_mask = (freqs >= 200.0) & (freqs <= 15000.0)
    eval_freqs = freqs[assert_mask]

    # Record systematic phase offset curves
    systematic_phase_curves = {}
    for p in range(1, P + 1):
        h_key = f"h{p}"
        meas_baseline = phases_zero[h_key][assert_mask]
        systematic_phase_curves[p] = (meas_baseline + 180) % 360 - 180

    # --- Test Simulation (with delays) ---
    test_delays = {
        1: 5.0,
        2: 8.0,
        3: 12.0,
        4: 15.0,
        5: 20.0
    }
    _, _, phases_meas, _, _ = run_simulation(test_delays)

    for p in range(1, P + 1):
        h_key = f"h{p}"
        
        # Theoretical phase delay: -2 * pi * f * delay / fs
        # (XFER relative delay after baseline calibration is exactly delays[p])
        theory_phase_rad = -2 * np.pi * eval_freqs * test_delays[p] / sample_rate
        theory_phase_deg = np.degrees(theory_phase_rad)
        theory_phase_deg = (theory_phase_deg + 180) % 360 - 180

        # Compensate measured phase using systematic calibration curve
        meas_raw = phases_meas[h_key][assert_mask]
        phase_meas_compensated = meas_raw - systematic_phase_curves[p]
        phase_meas_compensated = (phase_meas_compensated + 180) % 360 - 180

        # Calculate phase differences accounting for circular wrapping
        diff = np.abs(phase_meas_compensated - theory_phase_deg)
        diff = np.minimum(diff, 360.0 - diff)

        # Average phase error should be well under 10.0 degrees (typically < 1.5 deg, h2 is around 6.2 deg)
        mae = np.mean(diff)
        assert mae < 10.0, f"Phase reconstruction MAE for {h_key} is too high: {mae:.2f} deg"
        
        # Max phase error should be under 20.0 degrees
        max_err = np.max(diff)
        assert max_err < 20.0, f"Phase reconstruction Max Error for {h_key} is too high: {max_err:.2f} deg"


