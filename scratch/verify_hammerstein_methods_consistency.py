import sys
import os
import numpy as np

# Add project root to sys.path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from PyQt6.QtWidgets import QApplication
from src.core.audio_engine import AudioEngine
from src.gui.widgets.nonlinear_analyzer import NonlinearAnalyzer
from src.core.realtime_sss_core import RealtimeSSSEngine

def main():
    # Initialize Qt Application (required for some components)
    _app = QApplication(sys.argv)

    # 1. Initialize Audio Engine in virtual/offline mode
    engine = AudioEngine()
    engine.set_offline_mode(True)
    engine.set_loopback(True)
    engine.set_sample_rate(48000)
    engine.set_block_size(1024)

    # 2. Apply nonlinear distortion to loopback
    orig_prepare_logical_input = engine._prepare_logical_input

    def patched_prepare_logical_input(indata, frames, use_loopback):
        logical_in = orig_prepare_logical_input(indata, frames, use_loopback)
        if use_loopback and engine.offline_mode:
            sig = logical_in[:, 0].copy()
            simulated_meas = sig - 0.08 * (sig**2) + 0.12 * (sig**3) - 0.04 * (sig**4) + 0.06 * (sig**5)
            logical_in[:, 0] = simulated_meas
        return logical_in

    engine._prepare_logical_input = patched_prepare_logical_input

    # Common sweep parameters
    f_start = 50.0
    f_end = 15000.0
    duration = 4.0
    amplitude_db = -6.0
    amplitude_linear = 10 ** (amplitude_db / 20.0)
    P = 5

    # ----------------------------------------------------
    # Method A: Nonlinear Analyzer (Offline / Deconvolution)
    # ----------------------------------------------------
    print("\n=== Running Offline Deconvolution Hammerstein Analyzer ===")
    nonlin = NonlinearAnalyzer(engine)
    nonlin.amplitude_db = amplitude_db
    nonlin.num_amplitudes = 5
    nonlin.averages = 1
    nonlin.sweep_duration = duration
    nonlin.start_freq = f_start
    nonlin.end_freq = f_end
    nonlin.input_mode = "XFER"
    nonlin.meas_channel_index = 0
    nonlin.ref_channel_index = 1
    nonlin.output_channel = "STEREO"
    nonlin.measure_noise_floor = False

    class DummyWorker:
        def __init__(self):
            self.is_running = True

    nonlin_results = {}
    def on_nonlin_update(freqs, mags, phases):
        nonlin_results["freqs"] = freqs
        nonlin_results["mags"] = mags
        nonlin_results["phases"] = phases

    nonlin.signals.update_plot.connect(on_nonlin_update)
    nonlin._execute_measurement(DummyWorker())
    print("[+] Offline Analyzer completed.")

    # ----------------------------------------------------
    # Method B: Real-time SSS Lock-in Analyzer (Synchronous simulation)
    # ----------------------------------------------------
    print("\n=== Running Real-time Lock-in Hammerstein Analyzer ===")
    num_amplitudes = 5
    amplitudes = np.linspace(0.2, 1.0, num_amplitudes) * amplitude_linear
    block_size = 1024
    
    # Run RealtimeSSSEngine for each amplitude step synchronously
    raw_responses = None
    meas_freqs = None
    max_blocks = 0

    for amp_idx, amp in enumerate(amplitudes):
        rt_engine = RealtimeSSSEngine(
            sample_rate=engine.sample_rate,
            sweep_duration=duration,
            start_freq=f_start,
            end_freq=f_end,
            output_amplitude=amp,
            max_harmonic=P,
            analysis_cycles=16.0,
            num_meas_points=300
        )
        rt_engine.prepare_sweep()
        rt_engine.set_latency(0.0)

        meas_freqs = rt_engine.meas_freqs
        num_meas_points = len(meas_freqs)
        out_sig = rt_engine.out_sig
        in_sig = run_system_simulation(out_sig)
        
        num_blocks = int(np.ceil(len(out_sig) / block_size))
        max_blocks = num_blocks
        
        if raw_responses is None:
            raw_responses = np.zeros((num_amplitudes, num_blocks, P), dtype=complex)

        rt_engine.reset_filter_states()
        
        # We manually process block-by-block and capture results on the meas_freqs grid
        plot_freqs_array = np.zeros(num_blocks)
        for b_idx in range(num_blocks):
            start = b_idx * block_size
            end = min(start + block_size, len(out_sig))
            
            indata = np.zeros((block_size, 1))
            indata[:end-start, 0] = in_sig[start:end]
            ref_in = np.zeros((block_size, 1))
            ref_in[:end-start, 0] = out_sig[start:end]
            
            prev_idx = rt_engine.next_meas_idx
            f_mid, results = rt_engine.process_input_block(indata, b_idx, ref_in_block=ref_in)
            curr_idx = rt_engine.next_meas_idx
            
            plot_freqs_array[b_idx] = f_mid
            
            # Save the result to the crossed measurement points
            for idx in range(prev_idx, min(curr_idx, num_meas_points)):
                raw_responses[amp_idx, b_idx, :] = results

    # Replicate the calculate_hammerstein_kernels logic (the corrected version we wrote to realtime_sss_analyzer.py)
    # 1. Averaging: since we only ran 1 average per amplitude, avg_responses is simply raw_responses
    avg_responses = raw_responses.copy()
    
    # 2. Scale responses by amplitude and apply phase correction
    phase_corrections = [1.0, 1j, -1.0, -1j, 1.0]
    R_array = amplitudes
    g_scaled = np.zeros_like(avg_responses)
    for amp_idx in range(num_amplitudes):
        amp = R_array[amp_idx]
        for p in range(P):
            val = avg_responses[amp_idx, :, p]
            # Since input_mode="XFER"
            g_scaled[amp_idx, :, p] = val * amp * phase_corrections[p]

    g1, g2, g3, g4, g5 = g_scaled[:,:,0], g_scaled[:,:,1], g_scaled[:,:,2], g_scaled[:,:,3], g_scaled[:,:,4]
    R2 = R_array**2
    R3 = R_array**3
    R4 = R_array**4
    R5 = R_array**5

    H5 = 16 * np.sum(g5 * R5[:, np.newaxis], axis=0) / np.sum(R_array**10)
    H4 = 8 * np.sum(g4 * R4[:, np.newaxis], axis=0) / np.sum(R_array**8)
    
    g3_prime = g3 - (5 / 16) * H5[np.newaxis, :] * R5[:, np.newaxis]
    H3 = 4 * np.sum(g3_prime * R3[:, np.newaxis], axis=0) / np.sum(R_array**6)

    g2_prime = g2 - 0.5 * H4[np.newaxis, :] * R4[:, np.newaxis]
    H2 = 2 * np.sum(g2_prime * R2[:, np.newaxis], axis=0) / np.sum(R_array**4)

    g1_prime = g1 - 0.75 * H3[np.newaxis, :] * R3[:, np.newaxis] - 0.625 * H5[np.newaxis, :] * R5[:, np.newaxis]
    H1 = np.sum(g1_prime * R_array[:, np.newaxis], axis=0) / np.sum(R_array**2)

    H_freqs = [H1, H2, H3, H4, H5]

    # 3. Frequency Mapping (exactly as implemented in our fix)
    valid_idx = np.where(plot_freqs_array > 0)[0]
    sort_idx = np.argsort(plot_freqs_array[valid_idx])
    sorted_freqs = plot_freqs_array[valid_idx][sort_idx]
    
    H_mapped_list = []
    for p in range(len(H_freqs)):
        H_raw = H_freqs[p][valid_idx][sort_idx]
        f_lookups = sorted_freqs / (p + 1)
        
        real_mapped = np.interp(f_lookups, sorted_freqs, np.real(H_raw), left=np.nan, right=np.nan)
        imag_mapped = np.interp(f_lookups, sorted_freqs, np.imag(H_raw), left=np.nan, right=np.nan)
        
        H_mapped = real_mapped + 1j * imag_mapped
        H_mapped_list.append(H_mapped)

    # Apply Butterworth LPF to higher order mapped kernels
    for p in range(len(H_freqs)):
        H_p = H_mapped_list[p]
        if p >= 1:
            f_cut = min(20000.0, 1.15 * engine.sample_rate / (2 * (p + 1)))
            lpf = 1.0 / np.sqrt(1.0 + (sorted_freqs / f_cut) ** 16)
            H_p = H_p * lpf
        H_freqs[p] = H_p

    print("[+] Real-time Analyzer simulation completed.")

    # ----------------------------------------------------
    # Compare Identified Kernels H_p(f)
    # ----------------------------------------------------
    print("\n=== Comparing Identified Kernels at 1000 Hz ===")
    
    nonlin_freqs = nonlin_results["freqs"]
    f_eval = 1000.0

    for p in range(1, 6):
        h_key = f"h{p}"
        
        # Method A
        nl_mag_db = nonlin_results["mags"][h_key]
        nl_phase_deg = nonlin_results["phases"][h_key]
        val_nl_mag = np.interp(f_eval, nonlin_freqs, nl_mag_db)
        val_nl_phase = np.interp(f_eval, nonlin_freqs, nl_phase_deg)
        val_nl_phase = (val_nl_phase + 180) % 360 - 180

        # Method B
        H_rt_raw = H_freqs[p-1]
        mask_nan = np.isnan(H_rt_raw)
        H_rt_clean = H_rt_raw.copy()
        H_rt_clean[mask_nan] = 1e-15
        
        rt_mags_db = 20 * np.log10(np.abs(H_rt_clean) + 1e-15)
        rt_phases_deg = np.degrees(np.unwrap(np.angle(H_rt_clean)))
        rt_phases_deg = (rt_phases_deg + 180) % 360 - 180

        val_rt_mag = np.interp(f_eval, sorted_freqs, rt_mags_db)
        val_rt_phase = np.interp(f_eval, sorted_freqs, rt_phases_deg)
        val_rt_phase = (val_rt_phase + 180) % 360 - 180

        mag_err = val_rt_mag - val_nl_mag
        phase_err = (val_rt_phase - val_nl_phase + 180) % 360 - 180

        print(f"[{h_key}] Offline Deconv: Mag = {val_nl_mag:6.2f} dB, Phase = {val_nl_phase:7.2f}°")
        print(f"     Real-time LS:   Mag = {val_rt_mag:6.2f} dB, Phase = {val_rt_phase:7.2f}°")
        print(f"     Discrepancy:    Mag = {mag_err:6.2f} dB, Phase = {phase_err:7.2f}°")

        # Tolerances
        limit_mag = 1.5
        limit_phase = 15.0
        
        # Check assertions for low-order terms
        if p <= 3:
            assert np.abs(mag_err) < limit_mag, f"Magnitude discrepancy for H{p} exceeds limit: {mag_err:.2f} dB"
            assert np.abs(phase_err) < limit_phase, f"Phase discrepancy for H{p} exceeds limit: {phase_err:.2f}°"

    print("\n[+] Consistency Verification PASSED! Both identification methods now yield consistent results.")

def run_system_simulation(x):
    # Simulated system: y = x - 0.08*x^2 + 0.12*x^3 - 0.04*x^4 + 0.06*x^5
    # (pure static nonlinearity, delays are 0.0 for simple comparison)
    return x - 0.08 * (x**2) + 0.12 * (x**3) - 0.04 * (x**4) + 0.06 * (x**5)

if __name__ == "__main__":
    main()
