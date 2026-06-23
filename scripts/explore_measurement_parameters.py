#!/usr/bin/env python3
# ruff: noqa: E402
import sys
import os
import json
import numpy as np
import matplotlib.pyplot as plt

# Add project root to sys.path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from PyQt6.QtWidgets import QApplication
from src.core.audio_engine import AudioEngine
from src.gui.widgets.nonlinear_analyzer import NonlinearAnalyzer
from src.gui.widgets.lockin_harmonic_analyzer import LockInHarmonicAnalyzer

class DummyWorker:
    def __init__(self):
        self.is_running = True

def make_mock_run_play_rec(noise_level_db):
    def mock_run_play_rec(output_data, input_channels=2, progress_callback=None, check_cancelled=None):
        # output_data: (total_len, 2)
        ref_sig = output_data[:, 0].copy()

        # Apply true physical non-linear system
        # y(t) = x(t) - 0.08*x(t)^2 + 0.12*x(t)^3 - 0.04*x(t)^4 + 0.06*x(t)^5
        sig_dist = (
            ref_sig
            - 0.08 * (ref_sig**2)
            + 0.12 * (ref_sig**3)
            - 0.04 * (ref_sig**4)
            + 0.06 * (ref_sig**5)
        )

        # Inject noise
        if noise_level_db is not None:
            noise_rms = 10 ** (noise_level_db / 20.0)
            noise = np.random.normal(0, noise_rms, len(ref_sig))
            meas_sig = sig_dist + noise
        else:
            meas_sig = sig_dist

        rec_data = np.zeros_like(output_data)
        rec_data[:, 0] = meas_sig  # Meas (Left)
        rec_data[:, 1] = ref_sig   # Ref (Right)

        if progress_callback:
            progress_callback(100)
        return rec_data
    return mock_run_play_rec

def run_sss_simulation(engine, duration, averages, num_amplitudes, noise_level_db):
    nonlin_analyzer = NonlinearAnalyzer(engine)
    nonlin_analyzer.amplitude_db = -6.0
    nonlin_analyzer.num_amplitudes = num_amplitudes
    nonlin_analyzer.averages = averages
    nonlin_analyzer.sweep_duration = duration
    nonlin_analyzer.start_freq = 20.0
    nonlin_analyzer.end_freq = 20000.0
    nonlin_analyzer.input_mode = "XFER_REV"
    nonlin_analyzer.meas_channel_index = 0
    nonlin_analyzer.ref_channel_index = 1
    nonlin_analyzer.output_channel = "STEREO"

    nonlin_analyzer.run_play_rec = make_mock_run_play_rec(noise_level_db)

    sweep_results = {}
    def on_update_plot(freqs, mags, phases):
        sweep_results['freqs'] = freqs
        sweep_results['mags'] = mags
        sweep_results['phases'] = phases

    nonlin_analyzer.signals.update_plot.connect(on_update_plot)
    worker = DummyWorker()

    nonlin_analyzer._execute_measurement(worker)
    nonlin_analyzer.signals.update_plot.disconnect(on_update_plot)

    return sweep_results

def run_lockin_simulation(engine, noise_level_db, f0=1000.0, A_in=10**(-6.0/20.0)):
    lockin = LockInHarmonicAnalyzer(engine)
    lockin.signal_channel = 0
    lockin.ref_channel = 1
    lockin.max_harmonic = 5
    lockin.buffer_size = 262144
    lockin.gen_frequency = f0
    lockin.gen_amplitude = A_in
    lockin.output_enabled = True
    lockin.output_channel = 2

    def patched_estimate(ref, fs):
        ref_clean = ref - np.mean(ref)
        omega = 2.0 * np.pi * lockin.gen_frequency
        n_samples = len(ref_clean)
        t = np.arange(n_samples) / fs
        ref_i = (2.0 / n_samples) * np.dot(ref_clean, np.cos(omega * t))
        ref_q = (2.0 / n_samples) * np.dot(ref_clean, np.sin(omega * t))
        theta_0 = np.arctan2(ref_i, ref_q)
        return omega, theta_0

    def patched_extract(sig, ref, fs):
        sig_clean = sig - np.mean(sig)
        ref_clean = ref - np.mean(ref)
        rising_idx = np.flatnonzero((ref_clean[:-1] <= 0.0) & (ref_clean[1:] > 0.0))
        num_cycles = len(rising_idx) - 1
        if num_cycles < 1:
            return sig_clean, ref_clean, None
        start_idx = rising_idx[0]
        end_idx = rising_idx[-1]

        sig_seg = sig_clean[start_idx:end_idx]
        ref_seg = ref_clean[start_idx:end_idx]
        duration_sec = (end_idx - start_idx) / fs
        omega = 2.0 * np.pi * (num_cycles / duration_sec)
        theta_0 = -omega * (start_idx / fs)
        return sig_seg, ref_seg, (omega, theta_0)

    lockin._estimate_ref_phase_params = patched_estimate
    lockin._extract_coherent_segment = patched_extract

    fs = engine.sample_rate
    duration = 10.0  # Generate enough samples
    t = np.arange(int(fs * duration)) / fs
    ref_sig = A_in * np.sin(2 * np.pi * f0 * t)
    sig_clean = A_in * np.sin(2 * np.pi * f0 * t)
    sig_dist = (
        sig_clean
        - 0.08 * (sig_clean**2)
        + 0.12 * (sig_clean**3)
        - 0.04 * (sig_clean**4)
        + 0.06 * (sig_clean**5)
    )
    if noise_level_db is not None:
        noise = np.random.normal(0, 10 ** (noise_level_db / 20.0), len(t))
        meas_sig = sig_dist + noise
    else:
        meas_sig = sig_dist

    lockin.is_running = True
    lockin.input_data[:, lockin.signal_channel] = meas_sig[-lockin.buffer_size:]
    lockin.input_data[:, lockin.ref_channel] = ref_sig[-lockin.buffer_size:]
    lockin.input_buffer_pos = 0
    lockin.buffer_filled_samples = lockin.buffer_size

    lockin.process()

    meas_amps = lockin.harmonics_amp.copy()
    meas_phases = lockin.harmonics_phase_deg.copy()
    meas_fund_phase_deg = meas_phases[0]

    run_data = []
    for n in range(1, 6):
        meas_amp_db = 20 * np.log10(meas_amps[n-1] + 1e-12)
        meas_rel_phase_deg = meas_phases[n-1] - n * meas_fund_phase_deg
        meas_rel_phase_deg = (meas_rel_phase_deg + 180) % 360 - 180
        run_data.append({
            'amp_db': meas_amp_db,
            'phase_deg': meas_rel_phase_deg
        })
    return run_data

def evaluate_metrics(sss_results, lockin_results, f0, A_in):
    h_true_vals = {1: 1.0, 2: -0.08, 3: 0.12, 4: -0.04, 5: 0.06}

    freqs = sss_results['freqs']
    mags = sss_results['mags']
    phases = sss_results['phases']

    # 1. Kernel Gain RMSE for each order
    kernel_gain_rmse = {}
    kernel_phase_rmse = {}
    for p in range(1, 6):
        h_key = f"h{p}"
        true_val = h_true_vals[p]
        true_gain_db = 20 * np.log10(np.abs(true_val) + 1e-12)
        true_phase_deg = 0.0 if true_val > 0 else 180.0

        est_gain_db = mags[h_key]
        est_phase_deg = phases[h_key]

        gain_rmse = np.sqrt(np.mean((est_gain_db - true_gain_db)**2))

        phase_diff = (est_phase_deg - true_phase_deg + 180) % 360 - 180
        phase_rmse = np.sqrt(np.mean(phase_diff**2))

        kernel_gain_rmse[p] = float(gain_rmse)
        kernel_phase_rmse[p] = float(phase_rmse)

    # 2. SSS Prediction at 1kHz Harmonics
    H_dict = {}
    for p in range(1, 6):
        h_key = f"h{p}"
        mag_linear = 10 ** (mags[h_key] / 20.0)
        phase_rad = np.radians(phases[h_key])
        H_dict[p] = mag_linear * np.exp(1j * phase_rad)

    H_interp = {}
    nyquist = 48000.0 / 2.0
    for n in range(1, 6):
        f_n = n * f0
        H_interp[n] = {}
        if f_n > nyquist:
            for p in range(1, 6):
                H_interp[n][p] = 0.0 + 0.0j
            continue
        for p in range(1, 6):
            real_val = np.interp(f_n, freqs, np.real(H_dict[p]))
            imag_val = np.interp(f_n, freqs, np.imag(H_dict[p]))
            H_interp[n][p] = real_val + 1j * imag_val

    # SSS Model Y predictions
    Y_pred = {}
    Y_pred[1] = (1.0) * (A_in * H_interp[1][1] + (0.75 * (A_in**3)) * H_interp[1][3] + (0.625 * (A_in**5)) * H_interp[1][5])
    Y_pred[2] = (-1j) * ((0.5 * (A_in**2)) * H_interp[2][2] + (0.5 * (A_in**4)) * H_interp[2][4])
    Y_pred[3] = (-1.0) * ((0.25 * (A_in**3)) * H_interp[3][3] + (0.3125 * (A_in**5)) * H_interp[3][5])
    Y_pred[4] = (+1j) * ((0.125 * (A_in**4)) * H_interp[4][4])
    Y_pred[5] = (1.0) * ((0.0625 * (A_in**5)) * H_interp[5][5])

    # True Y analytical values
    H_true_interp = {n: {p: h_true_vals[p] + 0.0j for p in range(1, 6)} for n in range(1, 6)}
    Y_true = {}
    Y_true[1] = (1.0) * (A_in * H_true_interp[1][1] + (0.75 * (A_in**3)) * H_true_interp[1][3] + (0.625 * (A_in**5)) * H_true_interp[1][5])
    Y_true[2] = (-1j) * ((0.5 * (A_in**2)) * H_true_interp[2][2] + (0.5 * (A_in**4)) * H_true_interp[2][4])
    Y_true[3] = (-1.0) * ((0.25 * (A_in**3)) * H_true_interp[3][3] + (0.3125 * (A_in**5)) * H_true_interp[3][5])
    Y_true[4] = (+1j) * ((0.125 * (A_in**4)) * H_true_interp[4][4])
    Y_true[5] = (1.0) * ((0.0625 * (A_in**5)) * H_true_interp[5][5])

    sss_pred_data = []
    fund_phase_pred = np.angle(Y_pred[1])
    for n in range(1, 6):
        amp_db = 20 * np.log10(np.abs(Y_pred[n]) + 1e-12)
        rel_phase_deg = np.degrees(np.angle(Y_pred[n]) - n * fund_phase_pred)
        rel_phase_deg = (rel_phase_deg + 180) % 360 - 180
        sss_pred_data.append({'amp_db': amp_db, 'phase_deg': rel_phase_deg})

    true_pred_data = []
    fund_phase_true = np.angle(Y_true[1])
    for n in range(1, 6):
        amp_db = 20 * np.log10(np.abs(Y_true[n]) + 1e-12)
        rel_phase_deg = np.degrees(np.angle(Y_true[n]) - n * fund_phase_true)
        rel_phase_deg = (rel_phase_deg + 180) % 360 - 180
        true_pred_data.append({'amp_db': amp_db, 'phase_deg': rel_phase_deg})

    # Calculate errors at 1kHz (Phase A SSS vs True, Phase B Lockin vs True, and Phase A SSS vs Lockin)
    errors = []
    for n in range(1, 6):
        idx = n - 1

        # SSS vs True
        sss_amp_err = sss_pred_data[idx]['amp_db'] - true_pred_data[idx]['amp_db']
        sss_phase_err = (sss_pred_data[idx]['phase_deg'] - true_pred_data[idx]['phase_deg'] + 180) % 360 - 180

        # Lockin vs True
        lockin_amp_err = lockin_results[idx]['amp_db'] - true_pred_data[idx]['amp_db']
        lockin_phase_err = (lockin_results[idx]['phase_deg'] - true_pred_data[idx]['phase_deg'] + 180) % 360 - 180

        # SSS vs Lockin
        sss_vs_lockin_amp_err = sss_pred_data[idx]['amp_db'] - lockin_results[idx]['amp_db']
        sss_vs_lockin_phase_err = (sss_pred_data[idx]['phase_deg'] - lockin_results[idx]['phase_deg'] + 180) % 360 - 180

        errors.append({
            'harmonic': n,
            'sss_vs_true': {'amp_err': sss_amp_err, 'phase_err': sss_phase_err},
            'lockin_vs_true': {'amp_err': lockin_amp_err, 'phase_err': lockin_phase_err},
            'sss_vs_lockin': {'amp_err': sss_vs_lockin_amp_err, 'phase_err': sss_vs_lockin_phase_err}
        })

    return {
        'kernel_gain_rmse': kernel_gain_rmse,
        'kernel_phase_rmse': kernel_phase_rmse,
        'errors_1k': errors
    }

def main():
    print("[+] Starting Parameter Sensitivity Analysis...")
    QApplication(sys.argv)
    engine = AudioEngine()
    engine.set_sample_rate(48000)
    engine.set_block_size(1024)
    engine.set_offline_mode(False) # Let us mock run_play_rec

    f0 = 1000.0
    A_in = 10**(-6.0 / 20.0)

    # Grid spaces
    durations = [1.0, 2.0, 3.0, 5.0, 8.0, 10.0]
    averages = [1, 2, 3, 5, 8]
    amplitudes_counts = [5, 6, 7, 8, 10]
    noise_floors = [-110, -90, -70, -50] # dBFS

    results = []

    # Run once lockin simulations for each noise level (since Lock-in parameters don't depend on SSS sweep parameters)
    print("[*] Running pre-simulations for Lock-in...")
    lockin_db_cache = {}
    for nf in noise_floors:
        lockin_db_cache[nf] = run_lockin_simulation(engine, nf, f0, A_in)

    total_runs = len(durations) * len(averages) * len(amplitudes_counts) * len(noise_floors)
    current_run = 0

    print(f"[*] Total grid search combinations: {total_runs}")

    for nf in noise_floors:
        lockin_res = lockin_db_cache[nf]
        for duration in durations:
            for avg in averages:
                for num_amps in amplitudes_counts:
                    current_run += 1
                    if current_run % 50 == 0 or current_run == 1:
                        print(f"    Run {current_run}/{total_runs} (Noise: {nf} dBFS, Dur: {duration}s, Avg: {avg}, Amps: {num_amps})")

                    try:
                        sss_res = run_sss_simulation(engine, duration, avg, num_amps, nf)
                        metrics = evaluate_metrics(sss_res, lockin_res, f0, A_in)

                        run_info = {
                            'noise_level_db': nf,
                            'sweep_duration': duration,
                            'averages': avg,
                            'num_amplitudes': num_amps,
                            'metrics': metrics
                        }
                        results.append(run_info)
                    except Exception as e:
                        print(f"[-] Combination failed: Noise: {nf}, Dur: {duration}, Avg: {avg}, Amps: {num_amps}. Error: {e}")

    # Save to JSON
    json_path = "/Users/vach/MeasureLab/scripts/exploration_results.json"
    with open(json_path, 'w') as f:
        json.dump(results, f, indent=4)
    print(f"[+] Saved results to {json_path}")

    # Generate Plots
    print("[*] Generating visualization plots...")
    generate_plots(results)
    print("[+] Plot generation complete. Saved to scripts/exploration_sensitivity.png")

def generate_plots(results):
    target_noise = -90

    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    fig.suptitle(f"Nonlinear Kernel Estimation Sensitivity (Noise Floor = {target_noise} dBFS)", fontsize=16, fontweight='bold')

    def get_rmse(metrics_dict, p):
        gain_rmse = metrics_dict['kernel_gain_rmse']
        return gain_rmse.get(p, gain_rmse.get(str(p), 0.0))

    # Subplot 1: vs Sweep Duration (with fixed Averages=3, Amplitude Steps=5)
    ax1 = axes[0, 0]
    data_dur = [r for r in results if r['noise_level_db'] == target_noise and r['averages'] == 3 and r['num_amplitudes'] == 5]
    data_dur = sorted(data_dur, key=lambda x: x['sweep_duration'])
    if data_dur:
        durs = [x['sweep_duration'] for x in data_dur]
        h1_rmse = [get_rmse(x['metrics'], 1) for x in data_dur]
        h2_rmse = [get_rmse(x['metrics'], 2) for x in data_dur]
        h3_rmse = [get_rmse(x['metrics'], 3) for x in data_dur]
        h5_rmse = [get_rmse(x['metrics'], 5) for x in data_dur]

        ax1.plot(durs, h1_rmse, 'o-', label="h1 (Linear)", color='#1f77b4')
        ax1.plot(durs, h2_rmse, 's-', label="h2 (2nd)", color='#ff7f0e')
        ax1.plot(durs, h3_rmse, '^-', label="h3 (3rd)", color='#2ca02c')
        ax1.plot(durs, h5_rmse, 'd-', label="h5 (5th)", color='#9467bd')
        ax1.set_xlabel("Sweep Duration (seconds)")
        ax1.set_ylabel("Gain RMSE (dB)")
        ax1.set_title("Impact of Sweep Duration (Averages=3, Steps=5)")
        ax1.grid(True, linestyle='--', alpha=0.6)
        ax1.legend()

    # Subplot 2: vs Averages (with fixed Duration=5s, Amplitude Steps=5)
    ax2 = axes[0, 1]
    data_avg = [r for r in results if r['noise_level_db'] == target_noise and r['sweep_duration'] == 5.0 and r['num_amplitudes'] == 5]
    data_avg = sorted(data_avg, key=lambda x: x['averages'])
    if data_avg:
        avgs = [x['averages'] for x in data_avg]
        h1_rmse = [get_rmse(x['metrics'], 1) for x in data_avg]
        h2_rmse = [get_rmse(x['metrics'], 2) for x in data_avg]
        h3_rmse = [get_rmse(x['metrics'], 3) for x in data_avg]
        h5_rmse = [get_rmse(x['metrics'], 5) for x in data_avg]

        ax2.plot(avgs, h1_rmse, 'o-', label="h1 (Linear)", color='#1f77b4')
        ax2.plot(avgs, h2_rmse, 's-', label="h2 (2nd)", color='#ff7f0e')
        ax2.plot(avgs, h3_rmse, '^-', label="h3 (3rd)", color='#2ca02c')
        ax2.plot(avgs, h5_rmse, 'd-', label="h5 (5th)", color='#9467bd')
        ax2.set_xlabel("Averages (TSA Count)")
        ax2.set_ylabel("Gain RMSE (dB)")
        ax2.set_title("Impact of Time-Sync Averaging (Duration=5s, Steps=5)")
        ax2.grid(True, linestyle='--', alpha=0.6)
        ax2.legend()

    # Subplot 3: vs Amplitude Steps (with fixed Duration=5s, Averages=3)
    ax3 = axes[1, 0]
    data_amp = [r for r in results if r['noise_level_db'] == target_noise and r['sweep_duration'] == 5.0 and r['averages'] == 3]
    data_amp = sorted(data_amp, key=lambda x: x['num_amplitudes'])
    if data_amp:
        amps = [x['num_amplitudes'] for x in data_amp]
        h1_rmse = [get_rmse(x['metrics'], 1) for x in data_amp]
        h2_rmse = [get_rmse(x['metrics'], 2) for x in data_amp]
        h3_rmse = [get_rmse(x['metrics'], 3) for x in data_amp]
        h5_rmse = [get_rmse(x['metrics'], 5) for x in data_amp]

        ax3.plot(amps, h1_rmse, 'o-', label="h1 (Linear)", color='#1f77b4')
        ax3.plot(amps, h2_rmse, 's-', label="h2 (2nd)", color='#ff7f0e')
        ax3.plot(amps, h3_rmse, '^-', label="h3 (3rd)", color='#2ca02c')
        ax3.plot(amps, h5_rmse, 'd-', label="h5 (5th)", color='#9467bd')
        ax3.set_xlabel("Amplitude Steps (PHM Steps)")
        ax3.set_ylabel("Gain RMSE (dB)")
        ax3.set_title("Impact of Amplitude Steps (Duration=5s, Averages=3)")
        ax3.grid(True, linestyle='--', alpha=0.6)
        ax3.legend()

    # Subplot 4: vs Noise Level (with fixed Duration=5s, Averages=3, Amplitude Steps=5)
    ax4 = axes[1, 1]
    data_noise = [r for r in results if r['sweep_duration'] == 5.0 and r['averages'] == 3 and r['num_amplitudes'] == 5]
    data_noise = sorted(data_noise, key=lambda x: x['noise_level_db'])
    if data_noise:
        noises = [x['noise_level_db'] for x in data_noise]
        h1_rmse = [get_rmse(x['metrics'], 1) for x in data_noise]
        h2_rmse = [get_rmse(x['metrics'], 2) for x in data_noise]
        h3_rmse = [get_rmse(x['metrics'], 3) for x in data_noise]
        h5_rmse = [get_rmse(x['metrics'], 5) for x in data_noise]

        ax4.plot(noises, h1_rmse, 'o-', label="h1 (Linear)", color='#1f77b4')
        ax4.plot(noises, h2_rmse, 's-', label="h2 (2nd)", color='#ff7f0e')
        ax4.plot(noises, h3_rmse, '^-', label="h3 (3rd)", color='#2ca02c')
        ax4.plot(noises, h5_rmse, 'd-', label="h5 (5th)", color='#9467bd')
        ax4.set_xlabel("Noise Floor (dBFS)")
        ax4.set_ylabel("Gain RMSE (dB)")
        ax4.set_title("Impact of System Noise Floor (Duration=5s, Averages=3, Steps=5)")
        ax4.grid(True, linestyle='--', alpha=0.6)
        ax4.legend()

    plt.tight_layout()
    plt.savefig("/Users/vach/MeasureLab/scripts/exploration_sensitivity.png", dpi=150)
    plt.close()

if __name__ == '__main__':
    main()
