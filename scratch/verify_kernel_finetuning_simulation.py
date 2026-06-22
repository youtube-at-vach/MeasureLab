#!/usr/bin/env python3
"""
Simulation script to verify the feasibility of fine-tuning SSS kernel models 
using parallel lock-in measurements at multiple amplitudes (Approach A).
"""
import numpy as np

def generate_true_kernels():
    """
    Define simulated 'True' system kernels at f0 and its harmonics.
    These values are complex numbers representing magnitude and phase.
    """
    # Key: harmonic order n, Value: dict of {power p: complex_value}
    # True kernels representing a realistic physical system (e.g. speaker/amp)
    H_true = {
        1: {1: 0.8 + 0.1j,  3: -0.05 + 0.08j, 5: 0.01 - 0.02j}, # Fundamental components (H1, H3, H5)
        2: {2: 0.15 - 0.05j, 4: -0.03 + 0.01j},                # 2nd harmonic components (H2, H4)
        3: {3: -0.12 + 0.1j,  5: 0.02 - 0.01j},                # 3rd harmonic components (H3, H5)
        4: {4: 0.04 - 0.03j},                                  # 4th harmonic component (H4)
        5: {5: -0.015 + 0.01j}                                 # 5th harmonic component (H5)
    }
    return H_true

def perturb_kernels(H_true, gain_err_db=2.0, phase_err_deg=15.0):
    """
    Generate an 'Initial SSS Model' by adding measurement errors (noise)
    to the True kernels, representing typical sweep measurement limitations.
    """
    np.random.seed(42) # For reproducibility
    H_init = {}
    for n, p_dict in H_true.items():
        H_init[n] = {}
        for p, val in p_dict.items():
            # Add gain error
            gain_factor = 10 ** (np.random.uniform(-gain_err_db, gain_err_db) / 20.0)
            # Add phase error
            phase_offset = np.radians(np.random.uniform(-phase_err_deg, phase_err_deg))
            
            mag = np.abs(val) * gain_factor
            phase = np.angle(val) + phase_offset
            H_init[n][p] = mag * np.exp(1j * phase)
    return H_init

def simulate_lockin_measurement(H_true, amplitudes):
    """
    Simulate real-device (G) lock-in measurements for a set of amplitudes.
    Outputs the complex harmonic amplitudes Y_G[n] for n=1..5.
    """
    measurements = []
    # Add small measurement noise (lock-in has high SNR, so noise is very small)
    noise_floor = 1e-5 
    
    for A in amplitudes:
        Y_G = {}
        # n = 1
        Y_G[1] = A * H_true[1][1] + 0.75 * (A**3) * H_true[1][3] + 0.625 * (A**5) * H_true[1][5]
        # n = 2
        Y_G[2] = -1j * (0.5 * (A**2) * H_true[2][2] + 0.5 * (A**4) * H_true[2][4])
        # n = 3
        Y_G[3] = -1.0 * (0.25 * (A**3) * H_true[3][3] + 0.3125 * (A**5) * H_true[3][5])
        # n = 4
        Y_G[4] = 1j * (0.125 * (A**4) * H_true[4][4])
        # n = 5
        Y_G[5] = 0.0625 * (A**5) * H_true[5][5]
        
        # Add complex Gaussian noise to simulate instrumentation limits
        for n in range(1, 6):
            noise = (np.random.normal(0, noise_floor) + 1j * np.random.normal(0, noise_floor))
            Y_G[n] += noise
            
        measurements.append(Y_G)
        
    return measurements

def solve_least_squares_tuning(amplitudes, measurements):
    """
    Use Linear Least Squares (LSTD) to estimate/recover the kernel values
    directly from multi-amplitude lock-in measurements.
    """
    H_tuned = {n: {} for n in range(1, 6)}
    K = len(amplitudes)
    A = np.array(amplitudes)
    
    # ----------------------------------------------------
    # Tuning Fundamental kernels (p=1, 3, 5) from Y[1]
    # Y[1] = A * H1 + 0.75 * A^3 * H3 + 0.625 * A^5 * H5
    # ----------------------------------------------------
    # Construct regression matrix X1 (K x 3)
    X1 = np.zeros((K, 3), dtype=complex)
    X1[:, 0] = A
    X1[:, 1] = 0.75 * (A**3)
    X1[:, 2] = 0.625 * (A**5)
    
    # Target vector (K x 1)
    Y1 = np.array([meas[1] for meas in measurements])
    
    # Solve via pseudoinverse (or least squares solver)
    H1_fit, _, _, _ = np.linalg.lstsq(X1, Y1, rcond=None)
    H_tuned[1][1] = H1_fit[0]
    H_tuned[1][3] = H1_fit[1]
    H_tuned[1][5] = H1_fit[2]
    
    # ----------------------------------------------------
    # Tuning 2nd Harmonic kernels (p=2, 4) from Y[2]
    # Y[2] = -1j * (0.5 * A^2 * H2 + 0.5 * A^4 * H4)
    # ----------------------------------------------------
    X2 = np.zeros((K, 2), dtype=complex)
    X2[:, 0] = -0.5j * (A**2)
    X2[:, 1] = -0.5j * (A**4)
    
    Y2 = np.array([meas[2] for meas in measurements])
    H2_fit, _, _, _ = np.linalg.lstsq(X2, Y2, rcond=None)
    H_tuned[2][2] = H2_fit[0]
    H_tuned[2][4] = H2_fit[1]
    
    # ----------------------------------------------------
    # Tuning 3rd Harmonic kernels (p=3, 5) from Y[3]
    # Y[3] = -1.0 * (0.25 * A^3 * H3 + 0.3125 * A^5 * H5)
    # ----------------------------------------------------
    X3 = np.zeros((K, 2), dtype=complex)
    X3[:, 0] = -0.25 * (A**3)
    X3[:, 1] = -0.3125 * (A**5)
    
    Y3 = np.array([meas[3] for meas in measurements])
    H3_fit, _, _, _ = np.linalg.lstsq(X3, Y3, rcond=None)
    H_tuned[3][3] = H3_fit[0]
    H_tuned[3][5] = H3_fit[1]
    
    # ----------------------------------------------------
    # Tuning 4th Harmonic kernel (p=4) from Y[4]
    # Y[4] = 1j * 0.125 * A^4 * H4
    # ----------------------------------------------------
    X4 = (1j * 0.125 * (A**4)).reshape(-1, 1)
    Y4 = np.array([meas[4] for meas in measurements])
    H4_fit, _, _, _ = np.linalg.lstsq(X4, Y4, rcond=None)
    H_tuned[4][4] = H4_fit[0]
    
    # ----------------------------------------------------
    # Tuning 5th Harmonic kernel (p=5) from Y[5]
    # Y[5] = 0.0625 * A^5 * H5
    # ----------------------------------------------------
    X5 = (0.0625 * (A**5)).reshape(-1, 1)
    Y5 = np.array([meas[5] for meas in measurements])
    H5_fit, _, _, _ = np.linalg.lstsq(X5, Y5, rcond=None)
    H_tuned[5][5] = H5_fit[0]
    
    return H_tuned

def calculate_model_prediction(H_dict, A):
    """
    Calculate the model output prediction for a given input amplitude.
    """
    Y = {}
    Y[1] = A * H_dict[1][1] + 0.75 * (A**3) * H_dict[1][3] + 0.625 * (A**5) * H_dict[1][5]
    Y[2] = -1j * (0.5 * (A**2) * H_dict[2][2] + 0.5 * (A**4) * H_dict[2][4])
    Y[3] = -1.0 * (0.25 * (A**3) * H_dict[3][3] + 0.3125 * (A**5) * H_dict[3][5])
    Y[4] = 1j * (0.125 * (A**4) * H_dict[4][4])
    Y[5] = 0.0625 * (A**5) * H_dict[5][5]
    return Y

def main():
    print("=== SSS Model Fine-Tuning Simulation ===")
    
    # 1. Define True Kernels
    H_true = generate_true_kernels()
    
    # 2. Simulate SSS model measurement with noise/perturbation
    H_init = perturb_kernels(H_true, gain_err_db=2.0, phase_err_deg=15.0)
    
    # 3. Simulate Parallel Lock-in measurements at 3 different amplitudes
    # Amplitudes in linear scaling (e.g. -12dBFS, -6dBFS, 0dBFS equivalent)
    test_amplitudes = [
        10 ** (-12.0 / 20.0), # 0.251
        10 ** (-6.0 / 20.0),  # 0.501
        10 ** (0.0 / 20.0)    # 1.0
    ]
    
    print(f"Simulating Lock-in measurements at amplitudes: "
          f"{', '.join([f'{20*np.log10(a):.1f} dBFS' for a in test_amplitudes])}...")
    lockin_meas = simulate_lockin_measurement(H_true, test_amplitudes)
    
    # 4. Run the Least Squares Tuning algorithm
    print("Running Least Squares Tuning...")
    H_tuned = solve_least_squares_tuning(test_amplitudes, lockin_meas)
    
    # 5. Evaluate results
    print("\n=== Kernel Optimization Evaluation ===")
    print(f"{'Kernel':<10} | {'True Value':<25} | {'Initial SSS':<25} | {'Tuned Model':<25}")
    print("-" * 95)
    
    # Helper to format complex numbers
    def fmt(c):
        return f"{c.real:+.4f}{c.imag:+.4f}j"

    # We compare kernels that are shared across components
    for n in range(1, 6):
        for p in sorted(H_true[n].keys()):
            k_name = f"H{p}({n}f0)"
            v_true = H_true[n][p]
            v_init = H_init[n][p]
            v_tuned = H_tuned[n][p]
            
            print(f"{k_name:<10} | {fmt(v_true):<25} | {fmt(v_init):<25} | {fmt(v_tuned):<25}")
            
    # 6. Prediction Error Evaluation (Generalization to unseen amplitudes)
    # We test on an unseen amplitude (e.g. -3 dBFS)
    eval_amp = 10 ** (-3.0 / 20.0)
    Y_true = calculate_model_prediction(H_true, eval_amp)
    Y_init = calculate_model_prediction(H_init, eval_amp)
    Y_tuned = calculate_model_prediction(H_tuned, eval_amp)
    
    print(f"\n=== Prediction Error on Unseen Amplitude ({20*np.log10(eval_amp):.1f} dBFS) ===")
    print(f"{'Harmonic':<10} | {'True Output':<25} | {'Initial SSS Error (dB)':<25} | {'Tuned Model Error (dB)':<25}")
    print("-" * 95)
    
    for n in range(1, 6):
        db_true = 20 * np.log10(np.abs(Y_true[n]) + 1e-12)
        
        # Initial error
        err_init = Y_true[n] - Y_init[n]
        err_init_db = 20 * np.log10(np.abs(err_init) + 1e-12) - db_true
        
        # Tuned error
        err_tuned = Y_true[n] - Y_tuned[n]
        err_tuned_db = 20 * np.log10(np.abs(err_tuned) + 1e-12) - db_true
        
        print(f"H{n:<8} | {fmt(Y_true[n]):<25} | {err_init_db:>10.2f} dB                | {err_tuned_db:>10.2f} dB")

if __name__ == "__main__":
    main()
