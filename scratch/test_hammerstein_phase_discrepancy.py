import numpy as np
import sys
import os

# Add project root to sys.path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.core.realtime_sss_core import RealtimeSSSEngine

def run_simulation():
    sample_rate = 48000
    sweep_duration = 8.0
    start_freq = 50.0
    end_freq = 15000.0
    P = 5

    # 1. Known Nonlinear System Definition: y(t) = a1*x(t) + a2*x(t)^2 + ...
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

    # 2. Run simulation
    num_amplitudes = 5
    max_amp = 0.5
    amplitudes = np.linspace(0.2, 1.0, num_amplitudes) * max_amp
    block_size = 1024
    
    raw_responses = None
    meas_freqs = None

    for amp_idx, amp in enumerate(amplitudes):
        engine = RealtimeSSSEngine(
            sample_rate=sample_rate,
            sweep_duration=sweep_duration,
            start_freq=start_freq,
            end_freq=end_freq,
            output_amplitude=amp,
            max_harmonic=P,
            analysis_cycles=16.0,
            num_meas_points=300
        )
        engine.prepare_sweep()
        engine.set_latency(0.0)

        meas_freqs = engine.meas_freqs
        num_meas_points = len(meas_freqs)
        if raw_responses is None:
            raw_responses = np.zeros((num_amplitudes, num_meas_points, P), dtype=complex)

        out_sig = engine.out_sig
        in_sig = run_system(out_sig)
        num_blocks = int(np.ceil(len(out_sig) / block_size))

        engine.reset_filter_states()
        for b_idx in range(num_blocks):
            start = b_idx * block_size
            end = min(start + block_size, len(out_sig))
            indata = np.zeros((block_size, 1))
            indata[:end-start, 0] = in_sig[start:end]
            ref_in = np.zeros((block_size, 1))
            ref_in[:end-start, 0] = out_sig[start:end]
            
            prev_idx = engine.next_meas_idx
            f_mid, results = engine.process_input_block(indata, b_idx, ref_in_block=ref_in)
            curr_idx = engine.next_meas_idx
            
            for idx in range(prev_idx, min(curr_idx, num_meas_points)):
                raw_responses[amp_idx, idx, :] = results

    # 3. Process with Phase Correction AND Frequency Mapping
    R_array = amplitudes
    R2 = R_array**2
    R3 = R_array**3
    R4 = R_array**4
    R5 = R_array**5

    # 3.1 First: Apply phase correction to raw responses (DDC+LS physical outputs)
    # Phase corrections: p=1: 1, p=2: 1j, p=3: -1, p=4: -1j, p=5: 1
    phase_corrections = [1.0, 1j, -1.0, -1j, 1.0]
    g_corrected = np.zeros_like(raw_responses)
    for amp_idx in range(num_amplitudes):
        amp = R_array[amp_idx]
        for p in range(P):
            # Scale by amplitude to get physical output y_p
            g_corrected[amp_idx, :, p] = raw_responses[amp_idx, :, p] * amp * phase_corrections[p]

    gc1 = g_corrected[:, :, 0]
    gc2 = g_corrected[:, :, 1]
    gc3 = g_corrected[:, :, 2]
    gc4 = g_corrected[:, :, 3]
    gc5 = g_corrected[:, :, 4]

    # 3.2 Second: Run Chebyshev Inversion
    H5_raw = 16 * np.sum(gc5 * R5[:, np.newaxis], axis=0) / np.sum(R_array**10)
    H4_raw = 8 * np.sum(gc4 * R4[:, np.newaxis], axis=0) / np.sum(R_array**8)
    
    gc3_prime = gc3 - (5 / 16) * H5_raw[np.newaxis, :] * R5[:, np.newaxis]
    H3_raw = 4 * np.sum(gc3_prime * R3[:, np.newaxis], axis=0) / np.sum(R_array**6)

    gc2_prime = gc2 - 0.5 * H4_raw[np.newaxis, :] * R4[:, np.newaxis]
    H2_raw = 2 * np.sum(gc2_prime * R2[:, np.newaxis], axis=0) / np.sum(R_array**4)

    gc1_prime = gc1 - 0.75 * H3_raw[np.newaxis, :] * R3[:, np.newaxis] - 0.625 * H5_raw[np.newaxis, :] * R5[:, np.newaxis]
    H1_raw = np.sum(gc1_prime * R_array[:, np.newaxis], axis=0) / np.sum(R_array**2)

    H_raw_list = [H1_raw, H2_raw, H3_raw, H4_raw, H5_raw]

    # 3.3 Third: Frequency Mapping
    # The value of H_p_raw at fundamental frequency f_0 belongs to harmonic frequency p * f_0.
    # Therefore, we map: H_p(p * f_0) = H_p_raw(f_0)
    # To evaluate H_p at a target frequency f, we interpolate from H_p_raw at f_0 = f / p.
    # Note: We only have measurements for f_0 in [start_freq, end_freq].
    # So H_p(f) is valid for f in [p * start_freq, p * end_freq].
    
    def get_mapped_H_p(p, f_eval):
        # We need H_p_raw at f_eval / p
        f_lookup = f_eval / p
        H_p_raw = H_raw_list[p-1]
        
        # Interpolate real and imaginary parts
        real_val = np.interp(f_eval, meas_freqs * p, np.real(H_p_raw), left=np.nan, right=np.nan)
        imag_val = np.interp(f_eval, meas_freqs * p, np.imag(H_p_raw), left=np.nan, right=np.nan)
        return real_val + 1j * imag_val

    # 4. Evaluate at a target frequency f = 2000.0 Hz
    # At f = 2000 Hz, we evaluate H_p(f).
    # This corresponds to:
    # H1: lookup at f_0 = 2000 Hz
    # H2: lookup at f_0 = 1000 Hz
    # H3: lookup at f_0 = 666.7 Hz
    # H4: lookup at f_0 = 500 Hz
    # H5: lookup at f_0 = 400 Hz
    # All these f_0 are within our sweep range [50, 15000] Hz.
    f_target = 2000.0

    print(f"\n--- Hammerstein Kernel Evaluation at {f_target:.2f} Hz ---")
    print("Applying Phase Correction AND Frequency Mapping:")
    
    for p in range(1, 6):
        # Theoretical Phase and Magnitude at f_target
        theory_phase = -360.0 * f_target * delays[p] / sample_rate
        theory_phase = (theory_phase + 180) % 360 - 180
        theory_mag_db = 20 * np.log10(a[p])

        # Current Implementation (No phase correction, No freq mapping - evaluated directly at f_target on meas_freqs)
        idx_target = np.argmin(np.abs(meas_freqs - f_target))
        H_curr_list = [H1_current, H2_current, H3_current, H4_current, H5_current] = [
            H1_raw, H2_raw, H3_raw, H4_raw, H5_raw # Note: current code in GUI has H_raw values but without phase correction
        ]
        # In current GUI, they use:
        # H_current = self.H_freqs[p-1] (which is H_raw, but WITHOUT phase correction gc)
        # Let's compute H_current as computed in GUI (using raw_responses instead of gc):
        pass

    # Let's write the clean evaluation logic:
    # Compute H_curr_gui exactly as GUI does (using raw_responses * amp, no phase correction, no freq mapping)
    g_gui = np.zeros_like(raw_responses)
    for amp_idx in range(num_amplitudes):
        amp = R_array[amp_idx]
        g_gui[amp_idx] = raw_responses[amp_idx] * amp
    gg1, gg2, gg3, gg4, gg5 = g_gui[:,:,0], g_gui[:,:,1], g_gui[:,:,2], g_gui[:,:,3], g_gui[:,:,4]
    
    H5_gui = 16 * np.sum(gg5 * R5[:, np.newaxis], axis=0) / np.sum(R_array**10)
    H4_gui = 8 * np.sum(gg4 * R4[:, np.newaxis], axis=0) / np.sum(R_array**8)
    gg3_prime = gg3 - (5 / 16) * H5_gui[np.newaxis, :] * R5[:, np.newaxis]
    H3_gui = 4 * np.sum(gg3_prime * R3[:, np.newaxis], axis=0) / np.sum(R_array**6)
    gg2_prime = gg2 - 0.5 * H4_gui[np.newaxis, :] * R4[:, np.newaxis]
    H2_gui = 2 * np.sum(gg2_prime * R2[:, np.newaxis], axis=0) / np.sum(R_array**4)
    gg1_prime = gg1 - 0.75 * H3_gui[np.newaxis, :] * R3[:, np.newaxis] - 0.625 * H5_gui[np.newaxis, :] * R5[:, np.newaxis]
    H1_gui = np.sum(gg1_prime * R_array[:, np.newaxis], axis=0) / np.sum(R_array**2)
    H_gui_list = [H1_gui, H2_gui, H3_gui, H4_gui, H5_gui]

    for p in range(1, 6):
        theory_phase = -360.0 * f_target * delays[p] / sample_rate
        theory_phase = (theory_phase + 180) % 360 - 180
        theory_mag_db = 20 * np.log10(a[p])

        # GUI Value at f_target
        idx_target = np.argmin(np.abs(meas_freqs - f_target))
        val_gui = H_gui_list[p-1][idx_target]
        phase_gui = np.degrees(np.angle(val_gui))
        phase_gui = (phase_gui + 180) % 360 - 180
        mag_gui = 20 * np.log10(np.abs(val_gui) + 1e-12)

        # Mapped and Phase Corrected Value
        val_mapped = get_mapped_H_p(p, f_target)
        phase_mapped = np.degrees(np.angle(val_mapped))
        phase_mapped = (phase_mapped + 180) % 360 - 180
        mag_mapped = 20 * np.log10(np.abs(val_mapped) + 1e-12)

        print(f"[H{p}] Theoretical: Mag = {theory_mag_db:6.2f} dB, Phase = {theory_phase:7.2f}°")
        print(f"     GUI (Current): Mag = {mag_gui:6.2f} dB, Phase = {phase_gui:7.2f}° (Error: Mag = {mag_gui-theory_mag_db:5.2f} dB, Phase = {(phase_gui-theory_phase+180)%360-180:6.2f}°)")
        print(f"     Mapped+Corr:   Mag = {mag_mapped:6.2f} dB, Phase = {phase_mapped:7.2f}° (Error: Mag = {mag_mapped-theory_mag_db:5.2f} dB, Phase = {(phase_mapped-theory_phase+180)%360-180:6.2f}°)")

if __name__ == "__main__":
    run_simulation()
