import numpy as np
import pytest
from scipy.signal import fftconvolve

from src.core.nonlinear_analyzer_core import (
    generate_sss_and_inverse,
    calculate_chebyshev_matrix,
    process_amplitude_responses,
)


def test_nonlinear_analyzer_linear():
    """
    Verifies that for a pure linear system (y = x),
    the linear fundamental kernel h1 is detected at ~0 dB,
    and higher-order kernels h2 to h5 are highly suppressed (<-60 dB).
    """
    sample_rate = 44100
    sweep_duration = 1.0
    start_freq = 20.0
    end_freq = 20000.0
    P = 5

    # 1. Generate sweep and inverse filter
    sss, inv_filter = generate_sss_and_inverse(
        sample_rate, sweep_duration, start_freq, end_freq
    )

    # 2. Setup Amplitudes
    max_amp = 0.5  # Max Peak Amplitude (-6 dBFS equivalent)
    num_amplitudes = 5
    norm_v = np.linspace(0.2, 1.0, num_amplitudes)
    amplitudes = norm_v * max_amp

    # 3. Simulate Linear System: y = x
    responses_meas = []
    responses_ref = []

    for amp in amplitudes:
        # Linear excitation input
        x_sig = amp * sss
        # Linear system output
        y_sig = x_sig  # y = x

        # Add tail padding to match experimental behavior
        padding = np.zeros(int(0.1 * sample_rate))
        x_sig_padded = np.concatenate([x_sig, padding])
        y_sig_padded = np.concatenate([y_sig, padding])

        # Deconvolution in time-domain
        ir_ref = fftconvolve(x_sig_padded, inv_filter, mode="full")
        ir_meas = fftconvolve(y_sig_padded, inv_filter, mode="full")

        responses_ref.append(ir_ref)
        responses_meas.append(ir_meas)

    # 4. Construct Matrix M and its inverse
    _, M_pinv = calculate_chebyshev_matrix(num_amplitudes, norm_v, P)

    # 5. Process
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
        M_pinv=M_pinv,
    )

    # 6. Mathematical Assertions
    # Fundamental linear response (h1) should be very close to 0 dB gain across the band
    assert np.all(np.abs(mags["h1"]) < 1.0), "h1 linear response is not flat/near 0 dB"

    # Higher order responses (h2 to h5) must be heavily suppressed (<-60 dB)
    for p in range(2, 6):
        h_key = f"h{p}"
        max_harmonic_db = np.max(mags[h_key])
        assert max_harmonic_db < -60.0, (
            f"Pseudo-kernel {h_key} was detected for a linear system! "
            f"Max level = {max_harmonic_db:.2f} dB, expected <-60 dB."
        )


def test_nonlinear_analyzer_quadratic():
    """
    Verifies that for a quadratic non-linear system (y = x + 0.1 * x^2),
    h2 is detected as the dominant non-linear harmonic component,
    while h3, h4, and h5 are highly suppressed.
    """
    sample_rate = 44100
    sweep_duration = 1.0
    start_freq = 20.0
    end_freq = 20000.0
    P = 5

    # 1. Generate sweep and inverse filter
    sss, inv_filter = generate_sss_and_inverse(
        sample_rate, sweep_duration, start_freq, end_freq
    )

    # 2. Setup Amplitudes
    max_amp = 0.5
    num_amplitudes = 5
    norm_v = np.linspace(0.2, 1.0, num_amplitudes)
    amplitudes = norm_v * max_amp

    # 3. Simulate Quadratic Non-linear System: y = x + 0.1 * x^2
    responses_meas = []
    responses_ref = []

    a = 0.1
    for amp in amplitudes:
        x_sig = amp * sss
        # Non-linear quadratic transformation
        y_sig = x_sig + a * (x_sig ** 2)

        padding = np.zeros(int(0.1 * sample_rate))
        x_sig_padded = np.concatenate([x_sig, padding])
        y_sig_padded = np.concatenate([y_sig, padding])

        ir_ref = fftconvolve(x_sig_padded, inv_filter, mode="full")
        ir_meas = fftconvolve(y_sig_padded, inv_filter, mode="full")

        responses_ref.append(ir_ref)
        responses_meas.append(ir_meas)

    # 4. Construct Matrix M
    _, M_pinv = calculate_chebyshev_matrix(num_amplitudes, norm_v, P)

    # 5. Process
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
        M_pinv=M_pinv,
    )

    # h1 is fundamental (near 0 dB)
    assert np.all(np.abs(mags["h1"]) < 1.5)

    # h2 should be the dominant distortion component
    # Average magnitude of h2 should be significantly higher than h3, h4, h5
    h2_avg = np.mean(mags["h2"])
    assert h2_avg > -60.0, f"h2 not dominant, average magnitude: {h2_avg} dB"
    h3_avg = np.mean(mags["h3"])
    assert h2_avg > h3_avg + 10.0, f"h2 is not dominant over h3: h2={h2_avg:.2f} dB, h3={h3_avg:.2f} dB"

    # h3, h4, h5 should be highly suppressed (<-50 dB)
    for p in [3, 4, 5]:
        h_key = f"h{p}"
        assert np.max(mags[h_key]) < -50.0, f"Pseudo-kernel {h_key} detected in quadratic system!"


def test_nonlinear_analyzer_cubic():
    """
    Verifies that for a cubic non-linear system (y = x + 0.15 * x^3),
    h3 is detected as the dominant non-linear harmonic component,
    while h2, h4, and h5 are highly suppressed.
    """
    sample_rate = 44100
    sweep_duration = 1.0
    start_freq = 20.0
    end_freq = 20000.0
    P = 5

    # 1. Generate sweep and inverse filter
    sss, inv_filter = generate_sss_and_inverse(
        sample_rate, sweep_duration, start_freq, end_freq
    )

    # 2. Setup Amplitudes
    max_amp = 0.5
    num_amplitudes = 5
    norm_v = np.linspace(0.2, 1.0, num_amplitudes)
    amplitudes = norm_v * max_amp

    # 3. Simulate Cubic Non-linear System: y = x + 0.15 * x^3
    responses_meas = []
    responses_ref = []

    b = 0.15
    for amp in amplitudes:
        x_sig = amp * sss
        # Non-linear cubic transformation
        y_sig = x_sig + b * (x_sig ** 3)

        padding = np.zeros(int(0.1 * sample_rate))
        x_sig_padded = np.concatenate([x_sig, padding])
        y_sig_padded = np.concatenate([y_sig, padding])

        ir_ref = fftconvolve(x_sig_padded, inv_filter, mode="full")
        ir_meas = fftconvolve(y_sig_padded, inv_filter, mode="full")

        responses_ref.append(ir_ref)
        responses_meas.append(ir_meas)

    # 4. Construct Matrix M
    _, M_pinv = calculate_chebyshev_matrix(num_amplitudes, norm_v, P)

    # 5. Process
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
        M_pinv=M_pinv,
    )

    # h1 is fundamental (near 0 dB)
    assert np.all(np.abs(mags["h1"]) < 1.5)

    # h3 should be the dominant distortion component
    h3_avg = np.mean(mags["h3"])
    assert h3_avg > -55.0, f"h3 not dominant, average magnitude: {h3_avg} dB"
    h2_avg = np.mean(mags["h2"])
    assert h3_avg > h2_avg + 10.0, f"h3 is not dominant over h2: h3={h3_avg:.2f} dB, h2={h2_avg:.2f} dB"

    # h2, h4, h5 should be highly suppressed (<-50 dB)
    for p in [2, 4, 5]:
        h_key = f"h{p}"
        assert np.max(mags[h_key]) < -50.0, f"Pseudo-kernel {h_key} detected in cubic system!"
