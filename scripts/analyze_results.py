#!/usr/bin/env python3
import json
import numpy as np

def main():
    json_path = "/Users/vach/MeasureLab/scripts/exploration_results.json"
    with open(json_path, 'r') as f:
        results = json.load(f)
        
    print("=== MEASUREMENT PARAMETERS SENSITIVITY ANALYSIS ===")
    
    # 1. Base case: default settings (Noise: -90 dB, Dur: 5.0s, Avg: 3, Amps: 5)
    default_case = [r for r in results if r['noise_level_db'] == -90 and r['sweep_duration'] == 5.0 and r['averages'] == 3 and r['num_amplitudes'] == 5]
    if default_case:
        dc = default_case[0]
        print(f"\n[Default Config] Noise: -90 dBFS, Duration: 5.0s, Averages: 3, Amplitude Steps: 5")
        for p in [1, 2, 3, 5]:
            rmse = dc['metrics']['kernel_gain_rmse'][str(p)]
            print(f"  Kernel h{p} Gain RMSE: {rmse:.4f} dB")
            
    # 2. Sweeping Duration (Averages=3, Steps=5, Noise=-90dB)
    print("\n--- Sensitivity: Sweep Duration (Averages=3, Steps=5, Noise=-90dB) ---")
    data_dur = [r for r in results if r['noise_level_db'] == -90 and r['averages'] == 3 and r['num_amplitudes'] == 5]
    data_dur = sorted(data_dur, key=lambda x: x['sweep_duration'])
    print(f"{'Duration':<10} | {'h1 RMSE (dB)':<12} | {'h2 RMSE (dB)':<12} | {'h3 RMSE (dB)':<12} | {'h5 RMSE (dB)':<12}")
    print("-" * 65)
    for r in data_dur:
        dur = r['sweep_duration']
        h1 = r['metrics']['kernel_gain_rmse']['1']
        h2 = r['metrics']['kernel_gain_rmse']['2']
        h3 = r['metrics']['kernel_gain_rmse']['3']
        h5 = r['metrics']['kernel_gain_rmse']['5']
        print(f"{dur:<10.1f} | {h1:<12.4f} | {h2:<12.4f} | {h3:<12.4f} | {h5:<12.4f}")

    # 3. Sweeping Averages (Duration=5s, Steps=5, Noise=-90dB)
    print("\n--- Sensitivity: Averages / TSA (Duration=5.0s, Steps=5, Noise=-90dB) ---")
    data_avg = [r for r in results if r['noise_level_db'] == -90 and r['sweep_duration'] == 5.0 and r['num_amplitudes'] == 5]
    data_avg = sorted(data_avg, key=lambda x: x['averages'])
    print(f"{'Averages':<10} | {'h1 RMSE (dB)':<12} | {'h2 RMSE (dB)':<12} | {'h3 RMSE (dB)':<12} | {'h5 RMSE (dB)':<12}")
    print("-" * 65)
    for r in data_avg:
        avg = r['averages']
        h1 = r['metrics']['kernel_gain_rmse']['1']
        h2 = r['metrics']['kernel_gain_rmse']['2']
        h3 = r['metrics']['kernel_gain_rmse']['3']
        h5 = r['metrics']['kernel_gain_rmse']['5']
        print(f"{avg:<10d} | {h1:<12.4f} | {h2:<12.4f} | {h3:<12.4f} | {h5:<12.4f}")

    # 4. Sweeping Amplitude Steps (Duration=5s, Averages=3, Noise=-90dB)
    print("\n--- Sensitivity: Amplitude Steps / PHM (Duration=5.0s, Averages=3, Noise=-90dB) ---")
    data_amp = [r for r in results if r['noise_level_db'] == -90 and r['sweep_duration'] == 5.0 and r['averages'] == 3]
    data_amp = sorted(data_amp, key=lambda x: x['num_amplitudes'])
    print(f"{'Steps':<10} | {'h1 RMSE (dB)':<12} | {'h2 RMSE (dB)':<12} | {'h3 RMSE (dB)':<12} | {'h5 RMSE (dB)':<12}")
    print("-" * 65)
    for r in data_amp:
        amps = r['num_amplitudes']
        h1 = r['metrics']['kernel_gain_rmse']['1']
        h2 = r['metrics']['kernel_gain_rmse']['2']
        h3 = r['metrics']['kernel_gain_rmse']['3']
        h5 = r['metrics']['kernel_gain_rmse']['5']
        print(f"{amps:<10d} | {h1:<12.4f} | {h2:<12.4f} | {h3:<12.4f} | {h5:<12.4f}")

    # 5. Lock-in vs SSS Predictions at 1kHz Harmonics
    print("\n--- 1kHz Harmonics Error comparison (SSS vs Lock-in vs True) at Noise=-90dBFS, Dur=5s, Avg=3, Steps=5 ---")
    if default_case:
        dc = default_case[0]
        print(f"{'Harmonic':<10} | {'SSS vs True (dB)':<18} | {'Lock-in vs True (dB)':<22} | {'SSS vs Lockin (dB)':<20}")
        print("-" * 78)
        for err in dc['metrics']['errors_1k']:
            n = err['harmonic']
            sss_t = err['sss_vs_true']['amp_err']
            lock_t = err['lockin_vs_true']['amp_err']
            sss_l = err['sss_vs_lockin']['amp_err']
            print(f"{n:<10d} | {sss_t:<18.4f} | {lock_t:<22.4f} | {sss_l:<20.4f}")

if __name__ == '__main__':
    main()
