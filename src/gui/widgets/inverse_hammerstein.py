import os
import json
import logging
import numpy as np
from datetime import datetime
import soundfile as sf
from scipy.signal import windows, fftconvolve

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QGroupBox,
    QFormLayout, QDoubleSpinBox, QSpinBox, QFileDialog, QMessageBox,
    QTabWidget, QScrollArea, QTableWidget, QTableWidgetItem, QHeaderView,
    QProgressDialog
)
import pyqtgraph as pg

from src.core.localization import tr
from src.measurement_modules.base import MeasurementModule
from src.core.analysis import AudioCalc

logger = logging.getLogger(__name__)


class InverseModelWorker(QThread):
    progress = pyqtSignal(int, float, float)  # iter, total_error, thd
    update_plots = pyqtSignal(list, list)      # history_err_db, g_final_time
    finished = pyqtSignal(bool, dict, str)    # success, inverse_model_data, msg

    def __init__(self, raw_data, iterations, f_min, f_max):
        super().__init__()
        self.raw_data = raw_data
        self.iterations = iterations
        self.f_min = f_min
        self.f_max = f_max
        self.is_cancelled = False

    def cancel(self):
        self.is_cancelled = True

    def run(self):
        try:
            # 1. Parse kernels
            metadata = self.raw_data.get("metadata", {})
            sample_rate = metadata.get("sample_rate", 48000)

            # Kernels can be keys 'h1'..'h5' inside 'time_domain' -> 'kernels'
            time_domain = self.raw_data.get("time_domain", {})
            kernels_dict = time_domain.get("kernels", {})
            if not kernels_dict:
                raise ValueError(tr("No kernels found in the JSON file."))

            kernels = {k: np.array(v) for k, v in kernels_dict.items()}
            time_ms = np.array(time_domain.get("time_ms", []))

            # Retrieve at least h1 to h5
            required_keys = ["h1", "h2", "h3", "h4", "h5"]
            for rk in required_keys:
                if rk not in kernels:
                    raise ValueError(tr("Missing required kernel: {0}").format(rk))

            h1 = kernels["h1"]
            h2 = kernels["h2"]
            h3 = kernels["h3"]
            h4 = kernels["h4"]
            h5 = kernels["h5"]
            N = len(h1)

            if len(time_ms) == 0:
                time_ms = np.arange(N) / sample_rate * 1000.0

            # 2. Chebyshev to Power Series Conversion
            q0 = -h2 + h4
            q1 = h1 - 3 * h3 + 5 * h5
            q2 = 2 * h2 - 8 * h4
            q3 = 4 * h3 - 20 * h5
            q4 = 8 * h4
            q5 = 16 * h5

            Q1_fft_raw = np.fft.rfft(q1)
            G_scale = np.max(np.abs(Q1_fft_raw))

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

            # 3. Define active band filter
            freqs = np.fft.rfftfreq(N, d=1.0 / sample_rate)
            passband = (freqs >= self.f_min) & (freqs <= self.f_max)
            bp_filter = np.zeros_like(freqs)
            bp_filter[passband] = 1.0
            for i in range(len(freqs)):
                f = freqs[i]
                if f < self.f_min:
                    bp_filter[i] = np.clip(0.5 * (1.0 - np.cos(np.pi * (f - 10.0) / (self.f_min - 10.0))) if f >= 10.0 else 0.0, 0, 1)
                elif f > self.f_max:
                    nyquist = sample_rate / 2.0
                    roll_limit = min(nyquist * 0.95, self.f_max * 1.2)
                    if f < roll_limit:
                        bp_filter[i] = np.clip(0.5 * (1.0 + np.cos(np.pi * (f - self.f_max) / (roll_limit - self.f_max))), 0, 1)
                    else:
                        bp_filter[i] = 0.0

            def power_oversampled_fft(x, p, L=8):
                if p == 1:
                    return np.fft.rfft(x)
                N_x = len(x)
                X = np.fft.rfft(x)
                N_up = L * N_x
                X_up = np.zeros(N_up // 2 + 1, dtype=complex)
                X_up[: len(X)] = X * L
                x_up = np.fft.irfft(X_up, n=N_up)
                xp_up = x_up**p
                Xp_up = np.fft.rfft(xp_up)
                Xp = Xp_up[: N_x // 2 + 1] / L
                return Xp

            def forward_model(x):
                y = np.zeros_like(x)
                y += np.fft.irfft(np.fft.rfft(np.ones_like(x)) * Q0_fft, n=len(x))
                y += np.fft.irfft(power_oversampled_fft(x, 1) * Q1_fft, n=len(x))
                y += np.fft.irfft(power_oversampled_fft(x, 2) * Q2_fft, n=len(x))
                y += np.fft.irfft(power_oversampled_fft(x, 3) * Q3_fft, n=len(x))
                y += np.fft.irfft(power_oversampled_fft(x, 4) * Q4_fft, n=len(x))
                y += np.fft.irfft(power_oversampled_fft(x, 5) * Q5_fft, n=len(x))
                return y

            # 4. SSS Generation
            sweep_duration = N / sample_rate
            start_freq = self.f_min
            end_freq = self.f_max

            tukey_win = windows.tukey(N, alpha=0.02)
            t = np.linspace(0, sweep_duration, N, endpoint=False)
            start_margin = max(2.0, start_freq / 1.3)
            nyquist = sample_rate / 2.0
            end_margin = min(nyquist * 0.95, end_freq * 1.15)
            w1 = 2 * np.pi * start_margin
            T = sweep_duration
            L_param = np.log(end_margin / start_margin)

            phase = (w1 * T / L_param) * (np.exp(t * L_param / T) - 1)
            sss_signal = np.sin(phase) * tukey_win

            # Analytical inverse filter
            inv_envelope = np.exp(t * L_param / T)
            inverse_filter = inv_envelope * np.sin(phase) * tukey_win
            inverse_filter = np.flip(inverse_filter)

            direct_conv = fftconvolve(sss_signal, inverse_filter, mode="full")
            peak = np.max(np.abs(direct_conv))
            if peak > 1e-12:
                inverse_filter /= peak

            def deconvolve_signal(recorded, regularization=1e-4):
                S = np.fft.rfft(sss_signal)
                Y = np.fft.rfft(recorded)
                S_power = np.abs(S) ** 2
                epsilon = regularization * np.max(S_power) + 1e-12
                H = (Y * np.conj(S)) / (S_power + epsilon)
                return np.fft.irfft(H, n=N)

            gate_pre = int(0.01 * sample_rate)
            gate_post = int(0.02 * sample_rate)
            N_kernel = gate_pre + gate_post
            L_sweep = sweep_duration / np.log(end_margin / start_margin)

            def apply_phase_correction_and_frac_delay(g_k, k, frac_delay):
                N_k = len(g_k)
                G = np.fft.rfft(g_k)
                if k == 2:
                    G = G * 1j
                elif k == 3:
                    G = -G
                elif k == 4:
                    G = G * (-1j)
                if np.abs(frac_delay) > 1e-9:
                    freqs_k = np.fft.rfftfreq(N_k, d=1.0 / sample_rate)
                    phase_shift = np.exp(1j * 2 * np.pi * freqs_k * frac_delay / sample_rate)
                    G = G * phase_shift
                return np.fft.irfft(G, n=N_k)

            def measure_cascade_kernels(G_fft, amplitudes):
                num_amps = len(amplitudes)
                responses_meas = []
                clip_triggered = False

                for amp in amplitudes:
                    s_A = amp * sss_signal
                    u_A = np.zeros(N)
                    for p in range(1, 6):
                        S_A_p_fft = power_oversampled_fft(s_A, p)
                        U_p_fft = S_A_p_fft * G_fft[p - 1]
                        u_A += np.fft.irfft(U_p_fft, n=N)

                    if np.any(np.abs(u_A) >= 1.49):
                        clip_triggered = True
                    u_A = np.clip(u_A, -1.5, 1.5)
                    y_A = forward_model(u_A)
                    ir_A = deconvolve_signal(y_A)
                    responses_meas.append(ir_A)

                ref_step_idx = num_amps - 1
                base_align_sig = responses_meas[ref_step_idx]
                t1_idx = np.argmax(np.abs(base_align_sig))
                aligned_meas = responses_meas

                N_total = len(base_align_sig)
                g_meas_all = np.zeros((num_amps, 5, N_kernel))
                for j in range(num_amps):
                    ir_meas_raw = aligned_meas[j]
                    for k in range(1, 6):
                        t_k_exact = t1_idx - L_sweep * np.log(k) * sample_rate
                        t_k = int(np.round(t_k_exact))
                        frac_delay = t_k_exact - t_k
                        idx = (np.arange(t_k - gate_pre, t_k + gate_post)) % N_total
                        win = windows.tukey(N_kernel, alpha=0.1)
                        g_k_meas = ir_meas_raw[idx] * win
                        g_k_meas_corr = apply_phase_correction_and_frac_delay(g_k_meas, k, frac_delay)
                        g_meas_all[j, k - 1] = g_k_meas_corr

                N_fft_half = N_kernel // 2 + 1
                G_meas_k = {}
                for k in range(1, 6):
                    g_m_k_fft = np.empty((num_amps, N_fft_half), dtype=complex)
                    for j in range(num_amps):
                        g_m_k_fft[j] = np.fft.rfft(g_meas_all[j, k - 1])
                    G_meas_k[k] = g_m_k_fft

                R_array = np.array(amplitudes)
                R2 = R_array**2
                R3 = R_array**3
                R4 = R_array**4
                R5 = R_array**5

                T_list = np.zeros((5, N_fft_half), dtype=complex)
                g5_m = G_meas_k.get(5, np.zeros((num_amps, N_fft_half), dtype=complex))
                T_list[4] = 16 * np.sum(g5_m * R5[:, np.newaxis], axis=0) / np.sum(R_array**10)

                g4_m = G_meas_k.get(4, np.zeros((num_amps, N_fft_half), dtype=complex))
                T_list[3] = 8 * np.sum(g4_m * R4[:, np.newaxis], axis=0) / np.sum(R_array**8)

                g3_m = G_meas_k.get(3, np.zeros((num_amps, N_fft_half), dtype=complex))
                g3_prime_m = g3_m - (5 / 16) * T_list[4][np.newaxis, :] * R5[:, np.newaxis]
                T_list[2] = 4 * np.sum(g3_prime_m * R3[:, np.newaxis], axis=0) / np.sum(R_array**6)

                g2_m = G_meas_k.get(2, np.zeros((num_amps, N_fft_half), dtype=complex))
                g2_prime_m = g2_m - 0.5 * T_list[3][np.newaxis, :] * R4[:, np.newaxis]
                T_list[1] = 2 * np.sum(g2_prime_m * R2[:, np.newaxis], axis=0) / np.sum(R_array**4)

                g1_m = G_meas_k.get(1, np.zeros((num_amps, N_fft_half), dtype=complex))
                g1_prime_m = (
                    g1_m
                    - 0.75 * T_list[2][np.newaxis, :] * R3[:, np.newaxis]
                    - 0.625 * T_list[4][np.newaxis, :] * R5[:, np.newaxis]
                )
                T_list[0] = np.sum(g1_prime_m * R_array[:, np.newaxis], axis=0) / np.sum(R2)

                T_time = []
                for p in range(5):
                    t_p = np.fft.irfft(T_list[p], n=N_kernel)
                    t_p_aligned = np.roll(t_p, -gate_pre)
                    if len(t_p_aligned) < N:
                        t_p_full = np.pad(t_p_aligned, (0, N - len(t_p_aligned)))
                    else:
                        t_p_full = t_p_aligned[:N]
                    T_time.append(t_p_full)

                return T_time, clip_triggered

            # Initialize G kernels
            N_fft_half_full = N // 2 + 1
            Q1_sc_power = np.abs(Q1_fft) ** 2
            beta = 0.005
            delay_tau = gate_pre / sample_rate
            delay_2tau = 2.0 * delay_tau

            phase_shift_2tau = np.exp(-1j * 2 * np.pi * freqs * delay_2tau)
            G1_init_fft = (np.conj(Q1_fft) / (Q1_sc_power + beta)) * bp_filter * phase_shift_2tau

            G_fft = np.zeros((5, N_fft_half_full), dtype=complex)
            G_fft[0] = G1_init_fft

            # Amplitudes for the Chebyshev decomposition measurement
            a_amp, b_amp = 0.03, 0.30
            K_amp = 10
            k_arr = np.arange(1, K_amp + 1)
            cheb_nodes = 0.5 * (a_amp + b_amp) + 0.5 * (b_amp - a_amp) * np.cos((2 * k_arr - 1) / (2 * K_amp) * np.pi)
            measurement_amplitudes = np.sort(cheb_nodes)

            history_err_db = []
            H_target = Q1_fft * bp_filter

            F_lin_abs = np.abs(Q1_fft)
            eps_in = 1e-6
            eps_out = 0.5
            eps_f = eps_in + (eps_out - eps_in) * (1.0 - bp_filter)
            F_inv = np.conj(Q1_fft) / (F_lin_abs**2 + eps_f)

            center_idx = gate_pre
            N_keep = N // 3
            N_fade = N // 6

            win_centered = np.zeros(N)
            win_centered[:N_keep] = 1.0
            fade_shape = 0.5 * (1.0 + np.cos(np.pi * np.arange(N_fade) / N_fade))
            win_centered[N_keep : N_keep + N_fade] = fade_shape
            win_centered[-N_keep:] = 1.0
            win_centered[-N_keep - N_fade : -N_keep] = np.flip(fade_shape)

            g_win = np.roll(win_centered, center_idx)

            # Initial calibration measurement
            T_time_init, _ = measure_cascade_kernels(G_fft, measurement_amplitudes)
            T_fft_init = [np.fft.rfft(T_time_init[p]) for p in range(5)]

            C_fft = []
            C1 = np.ones_like(Q1_fft)
            idx_cal = np.abs(T_fft_init[0]) > 1e-4
            C1[idx_cal] = Q1_fft[idx_cal] / T_fft_init[0][idx_cal]
            C_fft.append(C1)

            Q_ffts = [Q1_fft, Q2_fft, Q3_fft, Q4_fft, Q5_fft]
            for p in range(1, 5):
                Cp = np.ones_like(Q_ffts[p])
                idx_p = np.abs(T_fft_init[p]) > 1e-6
                Cp[idx_p] = Q_ffts[p][idx_p] / T_fft_init[p][idx_p]
                C_fft.append(Cp)

            T_time = T_time_init
            T_fft = [np.fft.rfft(T_time[p]) for p in range(5)]
            E_fft = []
            T1_cal = T_fft[0] * C_fft[0]
            E_fft.append((T1_cal - Q1_fft) * bp_filter)

            for p in range(1, 5):
                Tp_cal = T_fft[p] * C_fft[p]
                E_fft.append(Tp_cal * bp_filter)

            harmonic_power = sum(np.sum(np.abs(E_fft[p]) ** 2) for p in range(1, 5))
            total_error = harmonic_power
            ref_power = np.sum(np.abs(H_target) ** 2)
            thd_db = 10 * np.log10(harmonic_power / ref_power)
            total_err_db = 10 * np.log10(total_error / ref_power)

            best_total_err_db = total_err_db
            best_thd_db = thd_db
            history_err_db.append((total_err_db, thd_db))

            # Send initial progress
            self.progress.emit(0, total_err_db, thd_db)
            self.update_plots.emit(history_err_db, [np.fft.irfft(G_fft[p], n=N) for p in range(5)])

            mu_base = [0.00, 0.20, 0.15, 0.10, 0.05]

            for iteration in range(self.iterations):
                if self.is_cancelled:
                    raise InterruptedError("Cancelled")

                mu_base = [m * 0.9 for m in mu_base]
                success_step = False
                max_search_steps = 4

                for search_step in range(max_search_steps):
                    if self.is_cancelled:
                        raise InterruptedError("Cancelled")
                    factor = 0.5**search_step
                    mu_step = [m * factor for m in mu_base]

                    G_fft_cand = G_fft.copy()
                    for p in range(5):
                        update = mu_step[p] * E_fft[p] * F_inv
                        G_fft_cand[p] = G_fft_cand[p] - update
                        G_fft_cand[p] = G_fft_cand[p] * bp_filter
                        g_t = np.fft.irfft(G_fft_cand[p], n=N)
                        g_t_win = g_t * g_win
                        G_fft_cand[p] = np.fft.rfft(g_t_win) * bp_filter

                    T_time_cand, clip_triggered = measure_cascade_kernels(G_fft_cand, measurement_amplitudes)

                    if clip_triggered:
                        continue

                    T_fft_cand = [np.fft.rfft(T_time_cand[p]) for p in range(5)]
                    E_fft_cand = []
                    T1_cal_cand = T_fft_cand[0] * C_fft[0]
                    E_fft_cand.append((T1_cal_cand - Q1_fft) * bp_filter)
                    for p in range(1, 5):
                        Tp_cal_cand = T_fft_cand[p] * C_fft[p]
                        E_fft_cand.append(Tp_cal_cand * bp_filter)

                    harmonic_power_cand = sum(np.sum(np.abs(E_fft_cand[p]) ** 2) for p in range(1, 5))
                    total_error_cand = harmonic_power_cand
                    thd_db_cand = 10 * np.log10(harmonic_power_cand / ref_power)
                    total_err_db_cand = 10 * np.log10(total_error_cand / ref_power)

                    if total_err_db_cand < best_total_err_db:
                        G_fft = G_fft_cand
                        T_time = T_time_cand
                        T_fft = T_fft_cand
                        E_fft = E_fft_cand
                        best_total_err_db = total_err_db_cand
                        best_thd_db = thd_db_cand
                        success_step = True
                        break

                if not success_step:
                    break

                history_err_db.append((best_total_err_db, best_thd_db))
                self.progress.emit(iteration + 1, best_total_err_db, best_thd_db)
                self.update_plots.emit(history_err_db, [np.fft.irfft(G_fft[p], n=N) for p in range(5)])

                if np.isnan(best_total_err_db) or best_total_err_db > 80.0:
                    break

            t_verify = np.arange(N) / sample_rate
            g_final_time = [np.fft.irfft(G_fft[p], n=N) for p in range(5)]

            # Verification evaluate helper
            def evaluate_test_signal(u_in, label):
                U_in_fft = np.fft.rfft(u_in)
                u_in_filt = np.fft.irfft(U_in_fft * bp_filter, n=N)
                y_target = u_in_filt.copy()
                y_raw = forward_model(u_in_filt)

                u_comp = np.zeros_like(u_in_filt)
                for p_idx in range(1, 6):
                    U_p_fft = power_oversampled_fft(u_in_filt, p_idx) * G_fft[p_idx - 1]
                    u_comp += np.fft.irfft(U_p_fft, n=N)

                y_comp = forward_model(u_comp)

                C_raw = np.fft.irfft(np.fft.rfft(y_raw) * np.conj(np.fft.rfft(y_target)), n=N)
                delay_raw = np.argmax(np.abs(C_raw))
                if delay_raw > N // 2:
                    delay_raw -= N
                y_raw_aligned = np.roll(y_raw, -delay_raw)

                C_comp = np.fft.irfft(np.fft.rfft(y_comp) * np.conj(np.fft.rfft(y_target)), n=N)
                delay_comp = np.argmax(np.abs(C_comp))
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

                sdr_raw = 20 * np.log10(rms_target / (rms_raw_err + 1e-12))
                sdr_comp = 20 * np.log10(rms_target / (rms_comp_err + 1e-12))
                improvement = sdr_comp - sdr_raw

                # Calculate THD
                idx_fund = np.argmin(np.abs(freqs - (1000.0 if "1k" in label.lower() else 3000.0)))
                w_bin = 3

                def get_thd(y_sig):
                    Y_fft = np.fft.rfft(y_sig)
                    fund_search_range = range(max(0, idx_fund - w_bin), min(len(freqs), idx_fund + w_bin + 1))
                    idx_fund_peak = max(fund_search_range, key=lambda i: np.abs(Y_fft[i]))
                    fund_power = np.abs(Y_fft[idx_fund_peak]) ** 2

                    harmonic_powers = []
                    f_test = 1000.0 if "1k" in label.lower() else 3000.0
                    for h in [2, 3, 4, 5]:
                        f_h = h * f_test
                        if f_h > sample_rate / 2:
                            break
                        idx_h = np.argmin(np.abs(freqs - f_h))
                        h_search_range = range(max(0, idx_h - w_bin), min(len(freqs), idx_h + w_bin + 1))
                        idx_h_peak = max(h_search_range, key=lambda i: np.abs(Y_fft[i]))
                        harmonic_powers.append(np.abs(Y_fft[idx_h_peak]) ** 2)

                    thd_val = np.sqrt(sum(harmonic_powers)) / (np.sqrt(fund_power) + 1e-12)
                    return 20 * np.log10(thd_val + 1e-12)

                thd_raw = get_thd(y_raw_scaled)
                thd_comp = get_thd(y_comp_scaled)

                return {
                    "label": label,
                    "sdr_raw": sdr_raw,
                    "sdr_comp": sdr_comp,
                    "improvement": improvement,
                    "thd_raw": thd_raw,
                    "thd_comp": thd_comp
                }

            # 1. 1 kHz Tone Tone
            u_1k = b_amp * np.sin(2 * np.pi * 1000.0 * t_verify)
            res_1k = evaluate_test_signal(u_1k, "1kHz Tone")

            # 2. 3 kHz Tone Tone (Untrained)
            u_3k = b_amp * np.sin(2 * np.pi * 3000.0 * t_verify)
            res_3k = evaluate_test_signal(u_3k, "3kHz Tone (Untrained)")

            validation_report = {
                "1k": res_1k,
                "3k": res_3k,
                "summary": {
                    "initial_thd": history_err_db[0][1],
                    "final_thd": history_err_db[-1][1],
                    "improvement": history_err_db[0][1] - history_err_db[-1][1]
                }
            }

            # 9. Format Inverse Hammerstein Model to JSON
            inv_mags = {}
            inv_phases = {}
            for p in range(5):
                h_key = f"h{p + 1}"
                inv_mags[h_key] = 20 * np.log10(np.abs(G_fft[p]) + 1e-12)
                total_delay = delay_2tau
                phase_correction = 2 * np.pi * freqs * total_delay
                G_corrected = G_fft[p] * np.exp(1j * phase_correction)
                phase_rad = np.unwrap(np.angle(G_corrected))
                phase_deg = phase_rad * 180.0 / np.pi
                phase_deg = (phase_deg + 180) % 360 - 180
                inv_phases[h_key] = phase_deg

            inv_phases["ref_phase"] = inv_phases["h1"]

            inv_metadata = {
                "format_version": "1.0",
                "export_timestamp": datetime.now().isoformat(),
                "module": "Inverse Hammerstein Predistorter",
                "sample_rate": float(sample_rate),
                "num_amplitudes": int(K_amp),
                "sweep_duration": float(sweep_duration),
                "start_freq": float(start_freq),
                "end_freq": float(end_freq),
                "input_mode": "L",
                "latency_sec": float(delay_2tau),
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
                "validation": validation_report
            }

            self.finished.emit(True, inverse_model_data, "")

        except InterruptedError:
            self.finished.emit(False, {}, tr("Cancelled"))
        except Exception as e:
            logger.exception("Inverse model generation failed")
            self.finished.emit(False, {}, str(e))


class WaveProcessWorker(QThread):
    progress = pyqtSignal(int)
    finished = pyqtSignal(bool, str)

    def __init__(self, input_path, output_path, inverse_model_data):
        super().__init__()
        self.input_path = input_path
        self.output_path = output_path
        self.inverse_model_data = inverse_model_data
        self.is_cancelled = False

    def cancel(self):
        self.is_cancelled = True

    def run(self):
        try:
            valid, msg = AudioCalc.validate_audio_file_size(self.input_path)
            if not valid:
                self.finished.emit(False, msg)
                return

            info = sf.info(self.input_path)
            file_sr = info.samplerate
            metadata = self.inverse_model_data.get("metadata", {})
            model_sr = metadata.get("sample_rate", 48000)

            if abs(file_sr - model_sr) > 1.0:
                self.finished.emit(False, tr("Sample rate mismatch: WAVE file is {0} Hz, but inverse model requires {1} Hz.").format(int(file_sr), int(model_sr)))
                return

            data, _ = sf.read(self.input_path, always_2d=True)
            M, channels = data.shape

            kernels_dict = self.inverse_model_data.get("time_domain", {}).get("kernels", {})
            g_final_time = [np.array(kernels_dict[f"h{p+1}"]) for p in range(5)]

            out_data = np.zeros_like(data)

            def apply_power_oversampled(x, p, L=8):
                if p == 1:
                    return x.copy()
                N_x = len(x)
                X = np.fft.rfft(x)
                N_up = L * N_x
                X_up = np.zeros(N_up // 2 + 1, dtype=complex)
                X_up[: len(X)] = X * L
                x_up = np.fft.irfft(X_up, n=N_up)
                xp_up = x_up**p
                Xp_up = np.fft.rfft(xp_up)
                Xp_up_filtered = np.zeros_like(Xp_up)
                Xp_up_filtered[: len(X)] = Xp_up[: len(X)]
                xp = np.fft.irfft(Xp_up_filtered / L, n=N_x)
                return xp

            for ch in range(channels):
                if self.is_cancelled:
                    raise InterruptedError("Cancelled")

                x_ch = data[:, ch]
                u_ch = np.zeros(M)

                for p in range(1, 6):
                    if self.is_cancelled:
                        raise InterruptedError("Cancelled")

                    xp = apply_power_oversampled(x_ch, p, L=8)
                    u_p = fftconvolve(xp, g_final_time[p - 1], mode="full")
                    u_ch += u_p[:M]

                    self.progress.emit(int(((ch * 5 + p) / (channels * 5)) * 100))

                out_data[:, ch] = u_ch

            max_val = np.max(np.abs(out_data))
            clipping_msg = ""
            if max_val > 1.0:
                clipping_msg = "\n" + tr("Warning: Output signal peaks at {0:.2f} dBFS. Output was normalized to avoid digital clipping.").format(20 * np.log10(max_val))
                out_data = out_data / max_val

            sf.write(self.output_path, out_data, int(model_sr), subtype="PCM_24" if info.subtype == "PCM_24" else "PCM_16")
            self.finished.emit(True, tr("Successfully processed and saved to {0}").format(os.path.basename(self.output_path)) + clipping_msg)

        except InterruptedError:
            self.finished.emit(False, tr("Cancelled"))
        except Exception as e:
            logger.exception("WAVE DPD processing failed")
            self.finished.emit(False, str(e))


class InverseHammerstein(MeasurementModule):
    def __init__(self, audio_engine):
        self.audio_engine = audio_engine

    @property
    def name(self) -> str:
        return "Inverse Hammerstein"

    @property
    def description(self) -> str:
        return "Generates Inverse Hammerstein predistortion models and applies DPD to WAVE files."

    def get_widget(self):
        return InverseHammersteinWidget(self)


class InverseHammersteinWidget(QWidget):
    def __init__(self, module: InverseHammerstein):
        super().__init__()
        self.module = module
        self.measured_model = None
        self.inverse_model = None

        self.model_worker = None
        self.wave_worker = None
        self.wave_input_path = ""

        self.init_ui()

    def init_ui(self):
        # Main layout
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setSpacing(5)

        # Left Panel: Sidebar wrapped in Scroll Area to respect size ceiling constraints
        sidebar_scroll = QScrollArea()
        sidebar_scroll.setFixedWidth(330)
        sidebar_scroll.setWidgetResizable(True)
        sidebar_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        sidebar_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        sidebar_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        sidebar_content = QWidget()
        sidebar_layout = QVBoxLayout(sidebar_content)
        sidebar_layout.setContentsMargins(0, 0, 4, 0)
        sidebar_layout.setSpacing(8)

        # Group 1: Model Source (Load Forward Model)
        source_group = QGroupBox(tr("Model Source"))
        source_form = QVBoxLayout(source_group)
        source_form.setSpacing(6)

        self.btn_load_measured = QPushButton(tr("Load Measured Model JSON..."))
        self.btn_load_measured.setStyleSheet("background-color: #4ba3e3; color: white; font-weight: bold; padding: 5px;")
        self.btn_load_measured.clicked.connect(self.load_measured_model)
        source_form.addWidget(self.btn_load_measured)

        self.lbl_status = QLabel(tr("No Model Loaded"))
        self.lbl_status.setStyleSheet("font-weight: bold; color: #d9534f;")
        self.lbl_sr = QLabel(tr("Rate:") + " -- Hz")
        self.lbl_order = QLabel(tr("Order:") + " --")

        info_layout = QFormLayout()
        info_layout.setSpacing(4)
        info_layout.addRow(tr("Status:"), self.lbl_status)
        info_layout.addRow(tr("Rate:"), self.lbl_sr)
        info_layout.addRow(tr("Order:"), self.lbl_order)
        source_form.addLayout(info_layout)
        sidebar_layout.addWidget(source_group)

        # Group 2: Inverse Model Generator
        self.gen_group = QGroupBox(tr("Inverse Model Generator"))
        gen_form = QFormLayout(self.gen_group)
        gen_form.setSpacing(6)

        self.spin_iter = QSpinBox()
        self.spin_iter.setRange(1, 100)
        self.spin_iter.setValue(15)
        gen_form.addRow(tr("Iterations (Phase 2):"), self.spin_iter)

        self.spin_fmin = QDoubleSpinBox()
        self.spin_fmin.setRange(10.0, 1000.0)
        self.spin_fmin.setValue(60.0)
        self.spin_fmin.setSuffix(" Hz")
        gen_form.addRow(tr("Passband Min (Hz):"), self.spin_fmin)

        self.spin_fmax = QDoubleSpinBox()
        self.spin_fmax.setRange(1000.0, 24000.0)
        self.spin_fmax.setValue(17000.0)
        self.spin_fmax.setSuffix(" Hz")
        gen_form.addRow(tr("Passband Max (Hz):"), self.spin_fmax)

        self.btn_generate = QPushButton(tr("Generate Inverse Model"))
        self.btn_generate.setStyleSheet("background-color: #2b8c56; color: white; font-weight: bold; padding: 6px;")
        self.btn_generate.clicked.connect(self.generate_inverse_model)
        gen_form.addRow(self.btn_generate)

        self.btn_export = QPushButton(tr("Export Inverse Model..."))
        self.btn_export.setEnabled(False)
        self.btn_export.clicked.connect(self.export_inverse_model)
        gen_form.addRow(self.btn_export)

        self.gen_group.setEnabled(False)
        sidebar_layout.addWidget(self.gen_group)

        # Group 3: WAVE File Processing
        self.wave_group = QGroupBox(tr("WAVE File DPD Processing"))
        wave_form = QVBoxLayout(self.wave_group)
        wave_form.setSpacing(6)

        self.btn_select_wave = QPushButton(tr("Select Input WAVE File..."))
        self.btn_select_wave.clicked.connect(self.select_wave_file)
        wave_form.addWidget(self.btn_select_wave)

        self.lbl_wave_file = QLabel(tr("No file selected"))
        self.lbl_wave_file.setWordWrap(True)
        wave_form.addWidget(self.lbl_wave_file)

        self.btn_apply_dpd = QPushButton(tr("Apply DPD & Save WAVE..."))
        self.btn_apply_dpd.setStyleSheet("background-color: #e68c14; color: white; font-weight: bold; padding: 6px;")
        self.btn_apply_dpd.setEnabled(False)
        self.btn_apply_dpd.clicked.connect(self.apply_dpd_wave)
        wave_form.addWidget(self.btn_apply_dpd)

        self.wave_group.setEnabled(False)
        sidebar_layout.addWidget(self.wave_group)

        sidebar_layout.addStretch()
        sidebar_content.setLayout(sidebar_layout)
        sidebar_scroll.setWidget(sidebar_content)
        main_layout.addWidget(sidebar_scroll)

        # Right Panel: Tab Content Area
        self.tabs = QTabWidget()

        # Tab 1: Optimization Convergence
        self.tab_convergence = QWidget()
        conv_layout = QVBoxLayout(self.tab_convergence)
        conv_layout.setContentsMargins(2, 2, 2, 2)
        self.conv_plot = pg.PlotWidget(title=tr("Optimization Convergence"))
        self.conv_plot.setLabel("left", tr("Error Level"), units="dB")
        self.conv_plot.setLabel("bottom", tr("Iterations"))
        self.conv_plot.showGrid(True, True, alpha=0.3)
        self.conv_plot.addLegend(offset=(10, 10))
        conv_layout.addWidget(self.conv_plot)
        self.tabs.addTab(self.tab_convergence, tr("Optimization Convergence"))

        # Tab 2: Inverse Kernels
        self.tab_kernels = QWidget()
        kernels_layout = QVBoxLayout(self.tab_kernels)
        kernels_layout.setContentsMargins(2, 2, 2, 2)
        self.kernel_plot = pg.PlotWidget(title=tr("Inverse Kernels"))
        self.kernel_plot.setLabel("left", tr("Normalized Amplitude"))
        self.kernel_plot.setLabel("bottom", tr("Time"), units="ms")
        self.kernel_plot.showGrid(True, True, alpha=0.3)
        self.kernel_plot.addLegend(offset=(10, 10))
        kernels_layout.addWidget(self.kernel_plot)
        self.tabs.addTab(self.tab_kernels, tr("Inverse Kernels"))

        # Tab 3: Bode Plots
        self.tab_bode = QWidget()
        bode_layout = QVBoxLayout(self.tab_bode)
        bode_layout.setContentsMargins(2, 2, 2, 2)
        self.mag_plot = pg.PlotWidget(title=tr("Bode Plots") + " - " + tr("Magnitude"))
        self.mag_plot.setLabel("left", tr("Gain"), units="dB")
        self.mag_plot.setLabel("bottom", tr("Frequency"), units="Hz")
        self.mag_plot.setLogMode(True, False)
        self.mag_plot.showGrid(True, True, alpha=0.3)
        self.mag_plot.addLegend(offset=(10, 10))
        bode_layout.addWidget(self.mag_plot)

        self.phase_plot = pg.PlotWidget(title=tr("Bode Plots") + " - " + tr("Phase"))
        self.phase_plot.setLabel("left", tr("Phase"), units="deg")
        self.phase_plot.setLabel("bottom", tr("Frequency"), units="Hz")
        self.phase_plot.setLogMode(True, False)
        self.phase_plot.showGrid(True, True, alpha=0.3)
        self.phase_plot.addLegend(offset=(10, 10))
        bode_layout.addWidget(self.phase_plot)
        self.tabs.addTab(self.tab_bode, tr("Bode Plots"))

        # Tab 4: Verification Results Table
        self.tab_results = QWidget()
        res_layout = QVBoxLayout(self.tab_results)
        res_layout.setContentsMargins(8, 8, 8, 8)
        self.table_results = QTableWidget()
        self.table_results.setColumnCount(5)
        self.table_results.setHorizontalHeaderLabels([
            tr("Test Signal"), 
            tr("SDR Raw"), 
            tr("SDR DPD"), 
            tr("THD Raw"), 
            tr("THD DPD")
        ])
        self.table_results.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table_results.verticalHeader().setVisible(False)
        res_layout.addWidget(self.table_results)
        self.tabs.addTab(self.tab_results, tr("Verification Results"))

        main_layout.addWidget(self.tabs, stretch=1)

    def load_measured_model(self):
        filepath, _ = QFileDialog.getOpenFileName(self, tr("Load Measured Model JSON..."), "", "JSON Files (*.json)")
        if not filepath:
            return

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Basic validation
            if "time_domain" not in data or "kernels" not in data["time_domain"]:
                raise ValueError(tr("Invalid file format: missing kernels."))

            self.measured_model = data
            metadata = data.get("metadata", {})
            self.lbl_status.setText(os.path.basename(filepath))
            self.lbl_status.setStyleSheet("font-weight: bold; color: #2b8c56;")
            self.lbl_sr.setText(tr("Rate:") + f" {metadata.get('sample_rate', 48000):g} Hz")
            self.lbl_order.setText(tr("Order:") + f" {metadata.get('P', 5)}")

            self.gen_group.setEnabled(True)
            self.wave_group.setEnabled(self.inverse_model is not None)

        except Exception as e:
            logger.exception("Failed to load model file")
            QMessageBox.critical(self, tr("Error"), tr("Failed to parse model file:\n{0}").format(e))

    def generate_inverse_model(self):
        if self.measured_model is None:
            return

        self.btn_generate.setEnabled(False)
        self.btn_load_measured.setEnabled(False)

        # Clear plots
        self.conv_plot.clear()
        self.kernel_plot.clear()
        self.mag_plot.clear()
        self.phase_plot.clear()
        self.table_results.setRowCount(0)

        # Setup Progress Dialog
        self.progress_dialog = QProgressDialog(tr("Generating Inverse Model..."), tr("Cancel"), 0, self.spin_iter.value() + 1, self)
        self.progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self.progress_dialog.setMinimumDuration(0)
        self.progress_dialog.setValue(0)

        self.model_worker = InverseModelWorker(
            self.measured_model,
            self.spin_iter.value(),
            self.spin_fmin.value(),
            self.spin_fmax.value()
        )
        self.model_worker.progress.connect(self.on_generation_progress)
        self.model_worker.update_plots.connect(self.on_generation_update_plots)
        self.model_worker.finished.connect(self.on_generation_finished)
        self.progress_dialog.canceled.connect(self.model_worker.cancel)

        self.model_worker.start()

    def on_generation_progress(self, iteration, total_error, thd):
        self.progress_dialog.setValue(iteration)
        self.progress_dialog.setLabelText(tr("Iteration {0}/{1} (Error: {2:.1f} dB)").format(iteration, self.spin_iter.value(), total_error))

    def on_generation_update_plots(self, history_err_db, g_final_time):
        # Draw convergence plot
        self.conv_plot.clear()
        history = np.array(history_err_db)
        self.conv_plot.plot(history[:, 0], pen=pg.mkPen("#1f77b4", width=2.5), name=tr("Total Error"))
        self.conv_plot.plot(history[:, 1], pen=pg.mkPen("#ff7f0e", width=2.5), name=tr("THD Error"))

        # Draw kernels plot
        self.kernel_plot.clear()
        N = len(g_final_time[0])
        sr = self.measured_model.get("metadata", {}).get("sample_rate", 48000)
        time_ms = (np.arange(N) - N // 2) / sr * 1000.0

        colors = ["#1f77b4", "#2ca02c", "#ff7f0e", "#9467bd", "#d62728"]
        for p in range(5):
            # Roll for display
            g_rolled = np.roll(g_final_time[p], N // 2)
            self.kernel_plot.plot(time_ms, g_rolled, pen=pg.mkPen(colors[p], width=1.5), name=f"g{p+1}")
        self.kernel_plot.setXRange(-5.0, 25.0)

    def on_generation_finished(self, success, inverse_model_data, msg):
        self.progress_dialog.close()
        self.btn_generate.setEnabled(True)
        self.btn_load_measured.setEnabled(True)

        if success:
            self.inverse_model = inverse_model_data
            self.btn_export.setEnabled(True)
            self.wave_group.setEnabled(True)

            # Update Bode Plots
            self.mag_plot.clear()
            self.phase_plot.clear()

            freqs = inverse_model_data["frequency_domain"]["freqs"]
            mags = inverse_model_data["frequency_domain"]["magnitudes_db"]
            phases = inverse_model_data["frequency_domain"]["phases_deg"]
            colors = ["#1f77b4", "#2ca02c", "#ff7f0e", "#9467bd", "#d62728"]

            for p in range(5):
                h_key = f"h{p+1}"
                self.mag_plot.plot(freqs, mags[h_key], pen=pg.mkPen(colors[p], width=1.5), name=f"G{p+1}")
                self.phase_plot.plot(freqs, phases[h_key], pen=pg.mkPen(colors[p], width=1.5), name=f"G{p+1}")

            # Populate table results
            val = inverse_model_data["validation"]
            self.table_results.setRowCount(2)

            # Row 0: 1kHz
            self.table_results.setItem(0, 0, QTableWidgetItem("1kHz Tone"))
            self.table_results.setItem(0, 1, QTableWidgetItem(f"{val['1k']['sdr_raw']:.1f} dB"))
            self.table_results.setItem(0, 2, QTableWidgetItem(f"{val['1k']['sdr_comp']:.1f} dB ({val['1k']['improvement']:+.1f} dB)"))
            self.table_results.setItem(0, 3, QTableWidgetItem(f"{val['1k']['thd_raw']:.1f} dB"))
            self.table_results.setItem(0, 4, QTableWidgetItem(f"{val['1k']['thd_comp']:.1f} dB ({val['1k']['thd_raw'] - val['1k']['thd_comp']:+.1f} dB)"))

            # Row 1: 3kHz
            self.table_results.setItem(1, 0, QTableWidgetItem("3kHz Tone (Untrained)"))
            self.table_results.setItem(1, 1, QTableWidgetItem(f"{val['3k']['sdr_raw']:.1f} dB"))
            self.table_results.setItem(1, 2, QTableWidgetItem(f"{val['3k']['sdr_comp']:.1f} dB ({val['3k']['improvement']:+.1f} dB)"))
            self.table_results.setItem(1, 3, QTableWidgetItem(f"{val['3k']['thd_raw']:.1f} dB"))
            self.table_results.setItem(1, 4, QTableWidgetItem(f"{val['3k']['thd_comp']:.1f} dB ({val['3k']['thd_raw'] - val['3k']['thd_comp']:+.1f} dB)"))

            # Highlight improvement cells in green
            # Just set item background for DPD cells
            for col in [2, 4]:
                for row in [0, 1]:
                    item = self.table_results.item(row, col)
                    if item:
                        # Convert color to QColor format for TableWidgetItem
                        from PyQt6.QtGui import QColor, QBrush
                        item.setBackground(QBrush(QColor(40, 180, 100, 50)))

            self.tabs.setCurrentIndex(3)  # Switch to Verification Results
            QMessageBox.information(
                self, 
                tr("Success"), 
                tr("Inverse model generated successfully.\nTHD suppression improvement: {0:.1f} dB").format(val["summary"]["improvement"])
            )
        else:
            if msg != tr("Cancelled"):
                QMessageBox.critical(self, tr("Error"), tr("Failed to generate inverse model:\n{0}").format(msg))

        self.model_worker = None

    def export_inverse_model(self):
        if self.inverse_model is None:
            return

        filepath, _ = QFileDialog.getSaveFileName(self, tr("Export Inverse Model..."), "inverse_hammerstein_model.json", "JSON Files (*.json)")
        if not filepath:
            return

        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(self.inverse_model, f, indent=2, ensure_ascii=False)
            QMessageBox.information(self, tr("Success"), tr("Successfully saved inverse model JSON to:\n{0}").format(filepath))
        except Exception as e:
            QMessageBox.critical(self, tr("Error"), tr("Failed to save inverse model to {0}:\n{1}").format(filepath, e))

    def select_wave_file(self):
        filepath, _ = QFileDialog.getOpenFileName(self, tr("Select Input WAVE File..."), "", tr("WAV Files (*.wav)"))
        if not filepath:
            return

        self.wave_input_path = filepath
        self.lbl_wave_file.setText(os.path.basename(filepath))
        self.btn_apply_dpd.setEnabled(self.inverse_model is not None)

    def apply_dpd_wave(self):
        if not self.wave_input_path or self.inverse_model is None:
            return

        output_path, _ = QFileDialog.getSaveFileName(self, tr("Apply DPD & Save WAVE..."), "dpd_output.wav", tr("WAV Files (*.wav)"))
        if not output_path:
            return

        self.btn_apply_dpd.setEnabled(False)
        self.btn_select_wave.setEnabled(False)

        self.progress_dialog = QProgressDialog(tr("Applying DPD processing..."), tr("Cancel"), 0, 100, self)
        self.progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self.progress_dialog.setMinimumDuration(0)
        self.progress_dialog.setValue(0)

        self.wave_worker = WaveProcessWorker(self.wave_input_path, output_path, self.inverse_model)
        self.wave_worker.progress.connect(self.progress_dialog.setValue)
        self.wave_worker.finished.connect(self.on_wave_process_finished)
        self.progress_dialog.canceled.connect(self.wave_worker.cancel)

        self.wave_worker.start()

    def on_wave_process_finished(self, success, msg):
        self.progress_dialog.close()
        self.btn_apply_dpd.setEnabled(True)
        self.btn_select_wave.setEnabled(True)

        if success:
            QMessageBox.information(self, tr("Success"), msg)
        else:
            if msg != tr("Cancelled"):
                QMessageBox.critical(self, tr("Error"), tr("DPD application failed:\n{0}").format(msg))

        self.wave_worker = None
