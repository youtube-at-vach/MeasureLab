import numpy as np
from unittest.mock import MagicMock
from src.core.nonlinear_analyzer_core import (
    generate_sss_and_inverse,
    deconvolve_signal,
    process_amplitude_responses,
)
from src.gui.widgets.lockin_harmonic_analyzer import LockInHarmonicAnalyzer


def test_lockin_vs_nonlinear_consistency():
    """
    Verifies the consistency of amplitude and phase measurements between:
    1. Lock-in Harmonic Analyzer's direct single-tone measurement logic.
    2. Nonlinear System Analyzer's SSS (Swept Sine) Chebyshev-inversion & simulator logic.

    A known simulated nonlinear system with frequency-dependent phase shifts (delays) is used.
    Systematic phase offsets are now automatically calibrated out by the core module.
    """
    # 1. Configuration
    sample_rate = 44100
    sweep_duration = 2.0
    start_freq = 20.0
    end_freq = 20000.0
    P = 5
    f0 = 1000.0  # Test frequency
    amp_db = -6.0
    amp_in = 10 ** (amp_db / 20.0)

    # 2. Known Nonlinear System Definition: y(t) = a1*x(t) + a2*x(t)^2 + ...
    # with frequency-domain delays (phase shifts) for each order
    a = {
        1: 1.0,
        2: 0.08,
        3: 0.12,
        4: 0.04,
        5: 0.06
    }
    delays = {
        1: 5.0,   # samples
        2: 8.0,   # samples
        3: 12.0,  # samples
        4: 15.0,  # samples
        5: 20.0   # samples
    }

    # Phase delay helper
    def apply_delay(x, delay_samples):
        N = len(x)
        X = np.fft.rfft(x)
        freqs = np.fft.rfftfreq(N, 1.0 / sample_rate)
        H = np.exp(-1j * 2 * np.pi * freqs * delay_samples / sample_rate)
        return np.fft.irfft(X * H, n=N)

    # Nonlinear system simulation
    def run_system(x):
        y = np.zeros_like(x)
        for p in range(1, P + 1):
            comp = a[p] * (x ** p)
            y += apply_delay(comp, delays[p])
        return y

    # 3. --- Part A: Measurement Sweep (With Delay System) ---
    # The core now automatically calibrates out systematic sweep phase offsets.
    sss, _ = generate_sss_and_inverse(sample_rate, sweep_duration, start_freq, end_freq)
    num_amplitudes = 5
    amplitudes = np.linspace(0.2, 1.0, num_amplitudes) * amp_in

    responses_meas = []
    responses_ref = []
    for amp in amplitudes:
        x_sig = amp * sss
        y_sig = run_system(x_sig)

        padding = np.zeros(int(0.2 * sample_rate))
        x_sig_padded = np.concatenate([x_sig, padding])
        y_sig_padded = np.concatenate([y_sig, padding])

        ir_ref = deconvolve_signal(x_sig_padded, sss)
        ir_meas = deconvolve_signal(y_sig_padded, sss)

        responses_ref.append(ir_ref)
        responses_meas.append(ir_meas)

    freqs, mags, phases, _, _ = process_amplitude_responses(
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
        calibrate_systematic=True,  # Test the automatic calibration
    )

    # Interpolate H_p(f) directly (systematic phase is already calibrated out by core)
    H_dict = {}
    for p in range(1, 6):
        h_key = f"h{p}"
        mag_linear = 10 ** (mags[h_key] / 20.0)
        phase_rad = np.radians(phases[h_key])
        H_dict[p] = mag_linear * np.exp(1j * phase_rad)

    # Print theoretical vs measured phases of H_p at 1000 Hz
    print("\n--- Hammerstein Kernel Phase Comparison at 1000 Hz ---")
    for p in range(1, 6):
        h_key = f"h{p}"
        meas_phase = np.interp(1000.0, freqs, phases[h_key])
        # Wrap phase to [-180, 180]
        meas_phase = (meas_phase + 180) % 360 - 180
        theory_phase = -360.0 * 1000.0 * delays[p] / sample_rate
        theory_phase = (theory_phase + 180) % 360 - 180
        print(f"[{h_key}] Theory Phase={theory_phase:.2f}°, Meas Phase={meas_phase:.2f}°, Diff={meas_phase - theory_phase:.2f}°")

    H_interp = {}
    for n in range(1, 6):
        f_n = n * f0
        H_interp[n] = {}
        for p in range(1, 6):
            real_val = np.interp(f_n, freqs, np.real(H_dict[p]))
            imag_val = np.interp(f_n, freqs, np.imag(H_dict[p]))
            H_interp[n][p] = real_val + 1j * imag_val

    # Synthesize predicted output components Y[n] (from simulator formulas)
    Y = {}
    Y[1] = (1.0) * (
        amp_in * H_interp[1][1] + (0.75 * (amp_in**3)) * H_interp[1][3] + (0.625 * (amp_in**5)) * H_interp[1][5]
    )
    Y[2] = (-1j) * ((0.5 * (amp_in**2)) * H_interp[2][2] + (0.5 * (amp_in**4)) * H_interp[2][4])
    Y[3] = (-1.0) * ((0.25 * (amp_in**3)) * H_interp[3][3] + (0.3125 * (amp_in**5)) * H_interp[3][5])
    Y[4] = (+1j) * ((0.125 * (amp_in**4)) * H_interp[4][4])
    Y[5] = (1.0) * ((0.0625 * (amp_in**5)) * H_interp[5][5])

    fund_phase_nonlin = np.angle(Y[1])

    # 4. --- Part B: Lock-in Harmonic Analyzer (Direct Single-Tone Capture) ---
    mock_audio_engine = MagicMock()
    mock_audio_engine.sample_rate = sample_rate

    lockin = LockInHarmonicAnalyzer(mock_audio_engine)
    lockin.gen_frequency = f0
    lockin.gen_amplitude = amp_in
    lockin.max_harmonic = P

    # Generate reference and signal with a arbitrary starting phase offset
    theta_ref = 0.35  # starting phase offset in radians
    t_lockin = np.arange(lockin.buffer_size) / sample_rate
    ref_sig = amp_in * np.sin(2 * np.pi * f0 * t_lockin + theta_ref)
    sig_sig = run_system(ref_sig)

    # Directly inject into the lockin buffers to run synchronous DSP logic
    lockin.input_data[:, lockin.ref_channel] = ref_sig
    lockin.input_data[:, lockin.signal_channel] = sig_sig
    lockin.buffer_filled_samples = lockin.buffer_size
    lockin.is_running = True

    lockin.process()

    # 5. --- Part C: Comparitive Verification & Assertions ---
    for n in range(1, 6):
        h_key = f"h{n}"
        y_val = Y[n]

        # Predicted values from Nonlinear Simulator
        pred_amp_dbfs = 20 * np.log10(np.abs(y_val) + 1e-12)
        pred_rel_phase_deg = np.degrees(np.angle(y_val) - n * fund_phase_nonlin)
        pred_rel_phase_deg = (pred_rel_phase_deg + 180) % 360 - 180

        # Measured values from Lock-in Analyzer
        meas_amp_dbfs = 20 * np.log10(lockin.harmonics_amp[n - 1] + 1e-12)
        meas_phase_raw_deg = lockin.harmonics_phase_deg[n - 1]

        # In Lock-in, we calculate relative phase to fundamental (Lock-in phase display alignment)
        # relative_phase_lockin = phi_n - n * phi_1
        fund_phase_lockin_deg = lockin.harmonics_phase_deg[0]
        meas_rel_phase_deg = meas_phase_raw_deg - n * fund_phase_lockin_deg
        meas_rel_phase_deg = (meas_rel_phase_deg + 180) % 360 - 180

        print(f"DEBUG: n={n}, raw_phase={meas_phase_raw_deg:.2f}, fund_phase={fund_phase_lockin_deg:.2f}, rel_phase={meas_rel_phase_deg:.2f}")

        # Amplitude discrepancy should be < 3.5 dB (due to interpolation/window leakage on high-order terms)
        amp_diff = np.abs(meas_amp_dbfs - pred_amp_dbfs)
        print(f"[{h_key}] Amplitude: Pred={pred_amp_dbfs:.2f} dBFS, Meas={meas_amp_dbfs:.2f} dBFS, Diff={amp_diff:.2f} dB")
        assert amp_diff < 3.5, f"[{h_key}] Amplitude discrepancy exceeds tolerance: {amp_diff:.2f} dB"

        # Phase discrepancy should be < 20.0 degrees (due to interpolation/window leakage on high-order terms)
        phase_diff = np.abs(meas_rel_phase_deg - pred_rel_phase_deg)
        phase_diff = np.minimum(phase_diff, 360.0 - phase_diff)
        print(f"[{h_key}] Rel Phase: Pred={pred_rel_phase_deg:.2f}°, Meas={meas_rel_phase_deg:.2f}°, Diff={phase_diff:.2f}°")
        assert phase_diff < 20.0, f"[{h_key}] Relative phase discrepancy exceeds tolerance: {phase_diff:.2f}°"
