import os
import json
import logging
import numpy as np
import soundfile as sf

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QGroupBox,
    QFormLayout,
    QDoubleSpinBox,
    QSpinBox,
    QFileDialog,
    QMessageBox,
    QTabWidget,
    QProgressBar,
    QCheckBox,
    QComboBox,
)
import pyqtgraph as pg

from src.core.localization import tr
from src.measurement_modules.base import MeasurementModule
from src.core.analysis import AudioCalc
from src.gui.styles import MONOSPACE_FONT_FAMILY
from src.core.transmission_logic import apply_octave_smoothing

logger = logging.getLogger(__name__)


class LICFFEngine:
    """
    Core engine to perform Linear-Inverse Compensated Feedforward (LICFF)
    based on a loaded Hammerstein system model.
    """

    def __init__(
        self,
        model_data,
        f_min=60.0,
        f_max=17000.0,
        threshold_db=None,
        reg_mode="manual_tikhonov",
        reg_val=1e-6,
        out_of_band_mode="bypass_aligned",
        linear_smoothing_fraction=0.0,
    ):
        self.model_data = model_data
        self.f_min = f_min
        self.f_max = f_max
        self.threshold_db = threshold_db
        self.reg_mode = reg_mode
        self.reg_val = reg_val
        self.out_of_band_mode = out_of_band_mode
        self.linear_smoothing_fraction = linear_smoothing_fraction
        self.last_resolved_eps_in = 1e-6
        self.sample_rate = 48000
        self.N = 0
        self.q0_sum = 0.0

        # Buffer caching for arbitrary block sizes
        self._cached_M = 0
        self._cached_Q_fft = []
        self._cached_F_inv_lin = None
        self._cached_F_inv_nl = None
        self._cached_bp_filter = None

        self.parse_model()

    def parse_model(self):
        metadata = self.model_data.get("metadata", {})
        self.sample_rate = metadata.get("sample_rate", 48000)
        self.g_ref = metadata.get("g_ref", 1.0)

        time_domain = self.model_data.get("time_domain", {})
        kernels_dict = time_domain.get("kernels", {})
        if not kernels_dict:
            raise ValueError(tr("No kernels found in the JSON file."))

        kernels = {k: np.array(v) for k, v in kernels_dict.items()}
        required_keys = ["h1", "h2", "h3", "h4", "h5"]
        for rk in required_keys:
            if rk not in kernels:
                raise ValueError(tr("Missing required kernel: {0}").format(rk))

        h1 = kernels["h1"]
        h2 = kernels["h2"]
        h3 = kernels["h3"]
        h4 = kernels["h4"]
        h5 = kernels["h5"]
        self.N = len(h1)

        # Direct mapping (measured kernels from the analyzer are already power-series coefficients)
        self.q0 = np.zeros_like(h1)
        self.q1 = h1.copy()
        self.q2 = h2.copy()
        self.q3 = h3.copy()
        self.q4 = h4.copy()
        self.q5 = h5.copy()

        # Noise thresholding for high-order kernels
        if self.threshold_db is not None:
            peak_h1 = np.max(np.abs(self.q1))
            threshold_linear = 10 ** (self.threshold_db / 20.0)
            for p in range(2, 6):
                qp_name = f"q{p}"
                qp = getattr(self, qp_name)
                peak_qp = np.max(np.abs(qp))
                if peak_qp < peak_h1 * threshold_linear:
                    setattr(self, qp_name, np.zeros_like(qp))
                    logger.info(
                        "LICFFEngine: Kernel h%d peak (%e) is below relative threshold (%e). Zeroed out.",
                        p,
                        peak_qp,
                        peak_h1 * threshold_linear,
                    )

        # Scale based on linear peak response
        Q1_fft_raw = np.fft.rfft(self.q1)
        self.G_scale = np.max(np.abs(Q1_fft_raw))
        if self.G_scale < 1e-12:
            self.G_scale = 1.0

        self.q0_sc = self.q0 / self.G_scale
        self.q1_sc = self.q1 / self.G_scale
        self.q2_sc = self.q2 / self.G_scale
        self.q3_sc = self.q3 / self.G_scale
        self.q4_sc = self.q4 / self.G_scale
        self.q5_sc = self.q5 / self.G_scale

        self.q0_sum = np.sum(self.q0_sc)

        # Reset cache
        self.clear_cache()

    def clear_cache(self):
        self._cached_M = 0
        self._cached_Q_fft = []
        self._cached_F_inv_lin = None
        self._cached_F_inv_nl = None
        self._cached_bp_filter = None

    def rebuild_filter(self):
        self.clear_cache()

    def get_max_inverse_filter_boost_db(self):
        if self.N <= 0:
            return 0.0
        _, F_inv_lin, _, _ = self._prepare_buffers_for_length(self.N)
        max_val = np.max(np.abs(F_inv_lin))
        if max_val <= 0:
            return 0.0
        return 20 * np.log10(max_val)

    def solve_eps_in(self, target_boost_db, Q1_fft, bp_filter):
        """
        Solve for eps_in that results in exactly target_boost_db peak gain in the passband
        using logarithmic bisection search.
        """
        target_gain = 10 ** (target_boost_db / 20.0)
        eps_approx = 1.0 / (4.0 * target_gain**2)

        H1_abs = np.abs(Q1_fft)
        mask = bp_filter > 0.05
        H1_pass = H1_abs[mask]
        if len(H1_pass) == 0:
            return eps_approx

        low = 1e-12
        high = 1.0
        for _ in range(25):
            mid = np.sqrt(low * high)
            eps_f_pass = mid + (0.5 - mid) * (1.0 - bp_filter[mask])
            gains = H1_pass / (H1_pass**2 + eps_f_pass)
            max_gain = np.max(gains)
            if max_gain > target_gain:
                low = mid
            else:
                high = mid
        return np.sqrt(low * high)

    def _prepare_buffers_for_length(self, M):
        if self._cached_M == M:
            return self._cached_Q_fft, self._cached_F_inv_lin, self._cached_F_inv_nl, self._cached_bp_filter

        # Compute M-point FFT of the scaled kernels (padded with zeros automatically)
        Q_fft_M = [
            np.fft.rfft(self.q0_sc, n=M),
            np.fft.rfft(self.q1_sc, n=M),
            np.fft.rfft(self.q2_sc, n=M),
            np.fft.rfft(self.q3_sc, n=M),
            np.fft.rfft(self.q4_sc, n=M),
            np.fft.rfft(self.q5_sc, n=M),
        ]

        # Design active band filter for length M
        freqs = np.fft.rfftfreq(M, d=1.0 / self.sample_rate)
        passband = (freqs >= self.f_min) & (freqs <= self.f_max)
        bp_filter_M = np.zeros_like(freqs)
        bp_filter_M[passband] = 1.0
        for i in range(len(freqs)):
            f = freqs[i]
            if f < self.f_min:
                bp_filter_M[i] = np.clip(
                    0.5 * (1.0 - np.cos(np.pi * (f - 10.0) / (self.f_min - 10.0))) if f >= 10.0 else 0.0, 0, 1
                )
            elif f > self.f_max:
                nyquist = self.sample_rate / 2.0
                roll_limit = min(nyquist * 0.95, self.f_max * 1.2)
                if f < roll_limit:
                    bp_filter_M[i] = np.clip(
                        0.5 * (1.0 + np.cos(np.pi * (f - self.f_max) / (roll_limit - self.f_max))), 0, 1
                    )
                else:
                    bp_filter_M[i] = 0.0

        # Determine eps_in
        if self.reg_mode == "auto_broadband":
            target_boost_db = 3.0
        elif self.reg_mode == "auto_tones":
            target_boost_db = 20.0
        elif self.reg_mode == "manual_boost":
            target_boost_db = self.reg_val
        else:  # manual_tikhonov
            target_boost_db = None
            eps_in = self.reg_val

        if target_boost_db is not None:
            eps_in = self.solve_eps_in(target_boost_db, Q_fft_M[1], bp_filter_M)

        self.last_resolved_eps_in = eps_in

        # Linear inverse filter F_inv for length M
        F_lin_abs = np.abs(Q_fft_M[1])
        if self.linear_smoothing_fraction > 0.0:
            # Apply octave smoothing in dB magnitude domain
            F_lin_abs_db = 20 * np.log10(np.maximum(F_lin_abs, 1e-12))
            smoothed_db = apply_octave_smoothing(freqs, F_lin_abs_db, self.linear_smoothing_fraction)
            F_lin_abs_smooth = 10 ** (smoothed_db / 20.0)
        else:
            F_lin_abs_smooth = F_lin_abs

        eps_out = 0.5
        eps_f = eps_in + (eps_out - eps_in) * (1.0 - bp_filter_M)

        # Form inverse filter using smoothed amplitude, preserving phase
        F_phase = Q_fft_M[1] / np.maximum(F_lin_abs, 1e-12)
        F_inv_raw = np.conj(F_phase) * (F_lin_abs_smooth / (F_lin_abs_smooth**2 + eps_f))

        # Decouple filters: nonlinear distortion feedback is active band only
        F_inv_nl_M = F_inv_raw * bp_filter_M

        # Linear inverse filter: depends on out_of_band_mode
        if self.out_of_band_mode == "bypass_aligned":
            # Out-of-band: gain is 1.0, phase is conjugate of Q1 (aligned delay)
            F_thru = np.conj(Q_fft_M[1]) / np.maximum(F_lin_abs, 1e-12)
            F_inv_lin_M = F_inv_raw * bp_filter_M + F_thru * (1.0 - bp_filter_M)
        elif self.out_of_band_mode == "bypass_pure":
            # Pure bypass: gain 1.0, phase 0
            F_inv_lin_M = F_inv_raw * bp_filter_M + 1.0 * (1.0 - bp_filter_M)
        else:  # "cut"
            F_inv_lin_M = F_inv_raw * bp_filter_M

        # Cache it
        self._cached_M = M
        self._cached_Q_fft = Q_fft_M
        self._cached_F_inv_lin = F_inv_lin_M
        self._cached_F_inv_nl = F_inv_nl_M
        self._cached_bp_filter = bp_filter_M

        return Q_fft_M, F_inv_lin_M, F_inv_nl_M, bp_filter_M

    def power_oversampled_fft(self, x, p, L=8):
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

    def nonlinear_spectrum(self, x, L=8):
        M = len(x)
        X = np.fft.rfft(x)
        N_up = L * M
        X_up = np.zeros(N_up // 2 + 1, dtype=complex)
        X_up[: len(X)] = X * L
        x_up = np.fft.irfft(X_up, n=N_up)

        x_up2 = x_up * x_up
        x_up3 = x_up2 * x_up
        x_up4 = x_up3 * x_up
        x_up5 = x_up4 * x_up

        Y_fft = np.zeros_like(X, dtype=complex)
        Q_fft, _, _, _ = self._prepare_buffers_for_length(M)

        # p=2
        Xp_up = np.fft.rfft(x_up2)
        Y_fft += (Xp_up[: len(X)] / L) * Q_fft[2]

        # p=3
        Xp_up = np.fft.rfft(x_up3)
        Y_fft += (Xp_up[: len(X)] / L) * Q_fft[3]

        # p=4
        Xp_up = np.fft.rfft(x_up4)
        Y_fft += (Xp_up[: len(X)] / L) * Q_fft[4]

        # p=5
        Xp_up = np.fft.rfft(x_up5)
        Y_fft += (Xp_up[: len(X)] / L) * Q_fft[5]

        Y_fft[-1] = np.real(Y_fft[-1])
        return Y_fft

    def forward_model(self, x, L=8):
        M = len(x)
        X = np.fft.rfft(x)
        N_up = L * M
        X_up = np.zeros(N_up // 2 + 1, dtype=complex)
        X_up[: len(X)] = X * L
        x_up = np.fft.irfft(X_up, n=N_up)

        x_up2 = x_up * x_up
        x_up3 = x_up2 * x_up
        x_up4 = x_up3 * x_up
        x_up5 = x_up4 * x_up

        Y_fft = np.zeros_like(X, dtype=complex)
        Q_fft, _, _, _ = self._prepare_buffers_for_length(M)

        # p=1
        Y_fft += X * Q_fft[1]

        # p=2
        Xp_up = np.fft.rfft(x_up2)
        Y_fft += (Xp_up[: len(X)] / L) * Q_fft[2]

        # p=3
        Xp_up = np.fft.rfft(x_up3)
        Y_fft += (Xp_up[: len(X)] / L) * Q_fft[3]

        # p=4
        Xp_up = np.fft.rfft(x_up4)
        Y_fft += (Xp_up[: len(X)] / L) * Q_fft[4]

        # p=5
        Xp_up = np.fft.rfft(x_up5)
        Y_fft += (Xp_up[: len(X)] / L) * Q_fft[5]

        Y_fft[-1] = np.real(Y_fft[-1])
        y_model = np.fft.irfft(Y_fft, n=M) + self.q0_sum
        return y_model

    def linear_output(self, x):
        M = len(x)
        Q_fft, _, _, _ = self._prepare_buffers_for_length(M)
        return np.fft.irfft(np.fft.rfft(x) * Q_fft[1], n=M)

    def nonlinear_output(self, x):
        M = len(x)
        Y_fft = self.nonlinear_spectrum(x)
        return np.fft.irfft(Y_fft, n=M) + self.q0_sum

    def compensate(
        self, u_in, iterative=False, iters=3, clip_limit=1.5, linear_only=False, bypass_linear_eq=False, stats=None
    ):
        M = len(u_in)
        _, F_inv_lin, F_inv_nl, bp_filter = self._prepare_buffers_for_length(M)

        if bypass_linear_eq:
            # Keep linear response as-is (bypass EQ)
            u_comp_linear = u_in.copy()
        else:
            # Base linear compensation (equalization & delay cancellation)
            U_in_fft = np.fft.rfft(u_in)
            u_comp_linear = np.fft.irfft(U_in_fft * F_inv_lin, n=M)

        if stats is not None:
            stats["clipping_count"] = 0
            stats["instability_detected"] = False

        if linear_only:
            u_comp_linear_clipped = np.clip(u_comp_linear, -clip_limit, clip_limit)
            if stats is not None:
                stats["clipping_count"] = int(np.sum(np.abs(u_comp_linear) >= clip_limit))
                if (
                    np.any(np.isnan(u_comp_linear))
                    or np.any(np.isinf(u_comp_linear))
                    or np.max(np.abs(u_comp_linear)) > 10.0 * clip_limit
                ):
                    stats["instability_detected"] = True
            return u_comp_linear_clipped

        if not iterative:
            iters = 1

        u_comp = u_comp_linear.copy()
        instability = False

        if np.any(np.isnan(u_comp)) or np.any(np.isinf(u_comp)) or np.max(np.abs(u_comp)) > 10.0 * clip_limit:
            instability = True

        u_comp = np.clip(u_comp, -clip_limit, clip_limit)

        for _ in range(iters):
            Y_fft = self.nonlinear_spectrum(u_comp)
            # Apply linear inverse filter to the nonlinear distortion components
            y_comp_nl = np.fft.irfft(Y_fft * F_inv_nl, n=M)
            u_comp_raw = u_comp_linear - y_comp_nl

            if (
                np.any(np.isnan(u_comp_raw))
                or np.any(np.isinf(u_comp_raw))
                or np.max(np.abs(u_comp_raw)) > 10.0 * clip_limit
            ):
                instability = True

            u_comp = np.clip(u_comp_raw, -clip_limit, clip_limit)

        if stats is not None:
            stats["clipping_count"] = int(np.sum(np.abs(u_comp) >= (clip_limit - 1e-7)))
            stats["instability_detected"] = instability

        return u_comp


def process_block_task(
    engine, chunk_padded, iterative, iters, clip_limit, linear_only, bypass_linear_eq, b_idx, L_block, overlap
):
    """
    Worker function to process a single block across all channels.
    Runs in a separate process.
    """
    channels = chunk_padded.shape[1]
    chunk_out = np.zeros((L_block, channels))
    block_stats_list = []

    for ch in range(channels):
        x_ch = chunk_padded[:, ch]
        stats = {}
        u_comp = engine.compensate(
            x_ch,
            iterative=iterative,
            iters=iters,
            clip_limit=clip_limit,
            linear_only=linear_only,
            bypass_linear_eq=bypass_linear_eq,
            stats=stats,
        )
        chunk_out_ch = u_comp[overlap : overlap + L_block]
        chunk_out[:, ch] = chunk_out_ch

        ch_clip_count = int(np.sum(np.abs(chunk_out_ch) >= (clip_limit - 1e-7)))
        x_ch_valid = chunk_padded[overlap : overlap + L_block, ch]
        sum_sq_in = float(np.sum(x_ch_valid**2))
        sum_sq_out = float(np.sum(chunk_out_ch**2))
        peak_in = float(np.max(np.abs(x_ch_valid)))

        block_stats_list.append(
            {
                "clipping_count": ch_clip_count,
                "instability_detected": bool(stats.get("instability_detected", False)),
                "sum_sq_in": sum_sq_in,
                "sum_sq_out": sum_sq_out,
                "peak_in": peak_in,
            }
        )

    return chunk_out, block_stats_list


class OfflineFFCompWorker(QThread):
    progress = pyqtSignal(int)
    finished = pyqtSignal(bool, str)

    def __init__(
        self,
        input_path,
        output_path,
        engine,
        iterative,
        iters,
        clip_limit,
        linear_only=False,
        bypass_linear_eq=False,
        volume_matching="none",
        abort_on_instability=False,
    ):
        super().__init__()
        self.input_path = input_path
        self.output_path = output_path
        self.engine = engine
        self.iterative = iterative
        self.iters = iters
        self.clip_limit = clip_limit
        self.linear_only = linear_only
        self.bypass_linear_eq = bypass_linear_eq
        self.volume_matching = volume_matching
        self.abort_on_instability = abort_on_instability
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
            model_sr = self.engine.sample_rate

            resample_msg = ""
            infile = None
            try:
                if abs(file_sr - model_sr) > 1.0:
                    raw_data, _ = sf.read(self.input_path, always_2d=True)
                    data = AudioCalc.resample(raw_data, file_sr, int(model_sr))
                    resample_msg = "\n" + tr(" (Resampled from {0} Hz to {1} Hz)").format(int(file_sr), int(model_sr))
                    M, channels = data.shape

                    def get_input_slice(start, end):
                        if start < 0 or end > M:
                            slice_data = data[max(0, start) : min(M, end)]
                            pad_left = max(0, -start)
                            pad_right = max(0, end - M)
                            return np.pad(slice_data, ((pad_left, pad_right), (0, 0)), mode="constant")
                        return data[start:end]
                else:
                    infile = sf.SoundFile(self.input_path, "r")
                    M = infile.frames
                    channels = infile.channels

                    def get_input_slice(start, end):
                        if start < 0:
                            infile.seek(0)
                            read_len = end
                            chunk = infile.read(read_len, always_2d=True)
                            pad_left = -start
                            pad_right = max(0, read_len - len(chunk))
                            return np.pad(chunk, ((pad_left, pad_right), (0, 0)), mode="constant")
                        elif end > M:
                            infile.seek(start)
                            chunk = infile.read(M - start, always_2d=True)
                            pad_left = 0
                            pad_right = end - M
                            return np.pad(chunk, ((pad_left, pad_right), (0, 0)), mode="constant")
                        else:
                            infile.seek(start)
                            return infile.read(end - start, always_2d=True)

                out_data = np.zeros((M, channels))
                sum_sq_in = np.zeros(channels)
                sum_sq_out = np.zeros(channels)
                peak_in = 0.0

                # Statistics tracking
                total_clipping_count = [0] * channels
                instability_detected = [False] * channels

                # Processing Block Configuration
                block_size = 65536
                overlap = 4096
                num_blocks = (M + block_size - 1) // block_size

                # Decide whether to use multiprocessing based on workload and core count
                use_multiprocessing = num_blocks > 2 and (os.cpu_count() or 1) > 1

                if use_multiprocessing:
                    max_workers = max(1, (os.cpu_count() or 2) - 1)

                    # Create thread-specific engines to prevent race conditions on cache buffers
                    engines = [
                        LICFFEngine(
                            self.engine.model_data,
                            f_min=self.engine.f_min,
                            f_max=self.engine.f_max,
                            threshold_db=self.engine.threshold_db,
                            reg_mode=self.engine.reg_mode,
                            reg_val=self.engine.reg_val,
                            out_of_band_mode=self.engine.out_of_band_mode,
                            linear_smoothing_fraction=self.engine.linear_smoothing_fraction,
                        )
                        for _ in range(max_workers)
                    ]

                    # Pre-warm LICFFEngine buffers for all thread engines
                    for eng in engines:
                        eng._prepare_buffers_for_length(block_size + 2 * overlap)
                        last_block_size = M - (num_blocks - 1) * block_size
                        if last_block_size != block_size:
                            eng._prepare_buffers_for_length(last_block_size + 2 * overlap)

                    import concurrent.futures

                    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                        futures = {}
                        for b_idx in range(num_blocks):
                            start_out = b_idx * block_size
                            end_out = min(start_out + block_size, M)
                            L_block = end_out - start_out

                            start_in = start_out - overlap
                            end_in = end_out + overlap

                            chunk_padded = get_input_slice(start_in, end_in)

                            # Assign an engine to this worker thread in a round-robin fashion
                            thread_engine = engines[b_idx % max_workers]

                            future = executor.submit(
                                process_block_task,
                                thread_engine,
                                chunk_padded,
                                self.iterative,
                                self.iters,
                                self.clip_limit,
                                self.linear_only,
                                self.bypass_linear_eq,
                                b_idx,
                                L_block,
                                overlap,
                            )
                            futures[future] = b_idx

                        completed_count = 0
                        for future in concurrent.futures.as_completed(futures):
                            if self.is_cancelled:
                                executor.shutdown(wait=False, cancel_futures=True)
                                raise InterruptedError("Cancelled")

                            b_idx = futures[future]
                            try:
                                chunk_out, block_stats_list = future.result()
                            except Exception as e:
                                executor.shutdown(wait=False, cancel_futures=True)
                                raise e

                            start_out = b_idx * block_size
                            end_out = min(start_out + block_size, M)
                            L_block = end_out - start_out

                            out_data[start_out:end_out, :] = chunk_out

                            for ch in range(channels):
                                block_stats = block_stats_list[ch]
                                total_clipping_count[ch] += block_stats["clipping_count"]

                                if block_stats["instability_detected"]:
                                    instability_detected[ch] = True
                                    if self.abort_on_instability:
                                        executor.shutdown(wait=False, cancel_futures=True)
                                        raise ValueError(
                                            tr("Instability/runaway detected during compensation. Processing aborted.")
                                        )

                                sum_sq_in[ch] += block_stats["sum_sq_in"]
                                sum_sq_out[ch] += block_stats["sum_sq_out"]
                                peak_in = max(peak_in, block_stats["peak_in"])

                            completed_count += 1
                            self.progress.emit(int((completed_count / num_blocks) * 100))
                else:
                    # Single-threaded fallback
                    for b_idx in range(num_blocks):
                        if self.is_cancelled:
                            raise InterruptedError("Cancelled")

                        start_out = b_idx * block_size
                        end_out = min(start_out + block_size, M)
                        L_block = end_out - start_out

                        start_in = start_out - overlap
                        end_in = end_out + overlap

                        chunk_padded = get_input_slice(start_in, end_in)
                        chunk_out = np.zeros((L_block, channels))

                        for ch in range(channels):
                            x_ch = chunk_padded[:, ch]
                            block_stats = {}
                            u_comp = self.engine.compensate(
                                x_ch,
                                iterative=self.iterative,
                                iters=self.iters,
                                clip_limit=self.clip_limit,
                                linear_only=self.linear_only,
                                bypass_linear_eq=self.bypass_linear_eq,
                                stats=block_stats,
                            )
                            chunk_out_ch = u_comp[overlap : overlap + L_block]
                            chunk_out[:, ch] = chunk_out_ch

                            ch_clip_count = np.sum(np.abs(chunk_out_ch) >= (self.clip_limit - 1e-7))
                            total_clipping_count[ch] += int(ch_clip_count)

                            if block_stats.get("instability_detected", False):
                                instability_detected[ch] = True
                                if self.abort_on_instability:
                                    raise ValueError(
                                        tr("Instability/runaway detected during compensation. Processing aborted.")
                                    )

                            x_ch_valid = chunk_padded[overlap : overlap + L_block, ch]
                            sum_sq_in[ch] += np.sum(x_ch_valid**2)
                            sum_sq_out[ch] += np.sum(chunk_out_ch**2)
                            peak_in = max(peak_in, np.max(np.abs(x_ch_valid)))

                        out_data[start_out:end_out, :] = chunk_out
                        self.progress.emit(int(((b_idx + 1) / num_blocks) * 100))

                rms_in = np.sqrt(np.sum(sum_sq_in) / max(1, M * channels))
                rms_out = np.sqrt(np.sum(sum_sq_out) / max(1, M * channels))
                peak_out = np.max(np.abs(out_data))

                clipping_msg = ""
                write_matched_orig = False
                matched_orig_path = ""
                scale_factor = 1.0

                if self.volume_matching == "rms":
                    g_y = rms_in / max(1e-12, rms_out)
                    peak_y_scaled = g_y * peak_out
                    if peak_y_scaled <= 1.0:
                        out_data = out_data * g_y
                        scale_factor = 1.0
                    else:
                        scale_factor = 1.0 / max(1e-12, peak_y_scaled)
                        out_data = out_data * (g_y * scale_factor)
                        applied_attenuation_db = 20 * np.log10(peak_y_scaled)
                        clipping_msg = "\n" + tr(
                            "Warning: Output would clip (+{0:.2f} dBFS) at matched RMS volume. "
                            "Both output and original files were attenuated by {0:.2f} dB to prevent clipping."
                        ).format(applied_attenuation_db)
                    write_matched_orig = True
                elif self.volume_matching == "peak":
                    g_y = peak_in / max(1e-12, peak_out)
                    out_data = out_data * g_y
                else:
                    if peak_out > 1.0:
                        clipping_msg = "\n" + tr(
                            "Warning: Output signal peaks at {0:.2f} dBFS. Output was normalized to avoid digital clipping."
                        ).format(20 * np.log10(peak_out))
                        out_data = out_data / peak_out

                sf.write(
                    self.output_path,
                    out_data,
                    int(model_sr),
                    subtype="PCM_24" if info.subtype == "PCM_24" else "PCM_16",
                )

                stats_msg = "\n\n" + tr("--- Processing Stats ---")
                for ch in range(channels):
                    ch_clip = total_clipping_count[ch]
                    ch_clip_pct = (ch_clip / max(1, M)) * 100
                    inst_str = tr("Yes (Runaway Warning!)") if instability_detected[ch] else tr("No")
                    stats_msg += "\n" + tr("Channel {0}: Clips: {1} ({2:.3f}%), Oscillation: {3}").format(
                        ch + 1, ch_clip, ch_clip_pct, inst_str
                    )

                if write_matched_orig:
                    if abs(file_sr - model_sr) > 1.0:
                        matched_orig_data = data * scale_factor
                    else:
                        raw_data, _ = sf.read(self.input_path, always_2d=True)
                        matched_orig_data = raw_data * scale_factor

                    base, ext = os.path.splitext(self.output_path)
                    matched_orig_path = base + "_matched_orig" + ext
                    sf.write(
                        matched_orig_path,
                        matched_orig_data,
                        int(model_sr if abs(file_sr - model_sr) > 1.0 else file_sr),
                        subtype="PCM_24" if info.subtype == "PCM_24" else "PCM_16",
                    )
                    self.finished.emit(
                        True,
                        tr("Successfully exported to {0}\nGain-matched original saved to {1}").format(
                            os.path.basename(self.output_path), os.path.basename(matched_orig_path)
                        )
                        + resample_msg
                        + clipping_msg
                        + stats_msg,
                    )
                else:
                    self.finished.emit(
                        True,
                        tr("Successfully exported to {0}").format(os.path.basename(self.output_path))
                        + resample_msg
                        + clipping_msg
                        + stats_msg,
                    )

            finally:
                if infile is not None:
                    infile.close()

        except InterruptedError:
            self.finished.emit(False, tr("Cancelled"))
        except Exception as e:
            logger.exception("Offline feedforward processing failed")
            self.finished.emit(False, str(e))


class FeedforwardCompensator(MeasurementModule):
    def __init__(self, audio_engine):
        self.audio_engine = audio_engine
        self.engine = None

    @property
    def name(self) -> str:
        return "Feedforward Compensator"

    @property
    def description(self) -> str:
        return "Applies feedforward distortion compensation (LICFF) to audio signals."

    def get_widget(self):
        return FeedforwardCompensatorWidget(self)


class FeedforwardCompensatorWidget(QWidget):
    def __init__(self, module: FeedforwardCompensator):
        super().__init__()
        self.module = module
        self.model_data = None
        self.worker = None
        self.init_ui()
        self.setAcceptDrops(True)
        self.set_controls_enabled(False)

    def init_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setSpacing(5)

        # Left Panel: Sidebar TabWidget
        sidebar_tabs = QTabWidget()
        sidebar_tabs.setFixedWidth(380)

        # Tab 1: Model Source
        tab_model = QWidget()
        tab_model_layout = QVBoxLayout(tab_model)
        tab_model_layout.setContentsMargins(4, 4, 4, 4)
        tab_model_layout.setSpacing(8)

        # Group 1: Model Source
        source_group = QGroupBox(tr("Model Source"))
        source_form = QVBoxLayout(source_group)
        source_form.setSpacing(6)

        self.btn_load_model = QPushButton(tr("Load Forward Model JSON..."))
        self.btn_load_model.setStyleSheet("background-color: #4ba3e3; color: white; font-weight: bold; padding: 5px;")
        self.btn_load_model.clicked.connect(self.load_model)
        source_form.addWidget(self.btn_load_model)

        self.lbl_status = QLabel(tr("No Model Loaded"))
        self.lbl_status.setStyleSheet("font-weight: bold; color: #d9534f;")
        self.lbl_sr = QLabel("-- Hz")
        self.lbl_n = QLabel("--")
        self.lbl_max_boost = QLabel("-- dB")
        self.lbl_resolved_eps = QLabel("--")

        info_layout = QFormLayout()
        info_layout.setSpacing(4)
        info_layout.addRow(tr("Status:"), self.lbl_status)
        info_layout.addRow(tr("Rate:"), self.lbl_sr)
        info_layout.addRow(tr("N Samples:"), self.lbl_n)
        info_layout.addRow(tr("Max Filter Boost:"), self.lbl_max_boost)
        info_layout.addRow(tr("Resolved eps_in:"), self.lbl_resolved_eps)
        source_form.addLayout(info_layout)
        tab_model_layout.addWidget(source_group)
        tab_model_layout.addStretch()

        # Tab 2: Compensation Settings
        tab_settings = QWidget()
        tab_settings_layout = QVBoxLayout(tab_settings)
        tab_settings_layout.setContentsMargins(4, 4, 4, 4)
        tab_settings_layout.setSpacing(8)

        # Group 2: Compensation Settings
        self.settings_group = QGroupBox(tr("Compensation Settings"))
        settings_form = QFormLayout(self.settings_group)
        settings_form.setSpacing(6)

        self.combo_comp_mode = QComboBox()
        self.combo_comp_mode.addItems(
            [
                tr("Linear & Nonlinear"),
                tr("Nonlinear Only (No Linear EQ)"),
                tr("Linear Only"),
            ]
        )
        self.combo_comp_mode.setCurrentIndex(0)
        self.combo_comp_mode.currentIndexChanged.connect(self.on_comp_mode_changed)
        settings_form.addRow(tr("Compensation Mode:"), self.combo_comp_mode)

        self.chk_iterative = QCheckBox(tr("Enable Iterative Compensation"))
        self.chk_iterative.setChecked(False)
        self.chk_iterative.toggled.connect(self.update_engine_params)
        settings_form.addRow(self.chk_iterative)

        self.spin_iters = QSpinBox()
        self.spin_iters.setRange(1, 20)
        self.spin_iters.setValue(3)
        self.spin_iters.valueChanged.connect(self.update_engine_params)
        settings_form.addRow(tr("Iterations:"), self.spin_iters)

        self.spin_fmin = QDoubleSpinBox()
        self.spin_fmin.setRange(10, 20000)
        self.spin_fmin.setValue(60)
        self.spin_fmin.setSuffix(" Hz")
        self.spin_fmin.valueChanged.connect(self.update_engine_params)
        self.spin_fmin.valueChanged.connect(self.adjust_fmax_range)
        settings_form.addRow(tr("Active Band Fmin:"), self.spin_fmin)

        self.spin_fmax = QDoubleSpinBox()
        self.spin_fmax.setRange(10, 24000)
        self.spin_fmax.setValue(17000)
        self.spin_fmax.setSuffix(" Hz")
        self.spin_fmax.valueChanged.connect(self.update_engine_params)
        self.spin_fmax.valueChanged.connect(self.adjust_min_range)
        settings_form.addRow(tr("Active Band Fmax:"), self.spin_fmax)

        self.combo_oob_mode = QComboBox()
        self.combo_oob_mode.addItems(
            [
                tr("Cut"),
                tr("Bypass (Phase Aligned)"),
                tr("Bypass (Pure)"),
            ]
        )
        self.combo_oob_mode.setCurrentIndex(1)
        self.combo_oob_mode.currentIndexChanged.connect(self.update_engine_params)
        settings_form.addRow(tr("Out-of-band Mode:"), self.combo_oob_mode)

        self.combo_linear_smooth = QComboBox()
        self.combo_linear_smooth.addItems(
            [
                tr("None"),
                tr("1/48 Octave"),
                tr("1/24 Octave"),
                tr("1/12 Octave"),
                tr("1/6 Octave"),
                tr("1/3 Octave"),
            ]
        )
        self.combo_linear_smooth.setCurrentIndex(0)
        self.combo_linear_smooth.currentIndexChanged.connect(self.update_engine_params)
        settings_form.addRow(tr("Linear Smoothing:"), self.combo_linear_smooth)

        self.combo_reg_mode = QComboBox()
        self.combo_reg_mode.addItems(
            [
                tr("Auto (Broadband / Music)"),
                tr("Auto (Pure Tones)"),
                tr("Manual (Max Boost)"),
                tr("Manual (Tikhonov)"),
            ]
        )
        self.combo_reg_mode.currentIndexChanged.connect(self.on_reg_mode_changed)
        settings_form.addRow(tr("Regularization Mode:"), self.combo_reg_mode)

        self.spin_reg_val = QDoubleSpinBox()
        self.spin_reg_val.setEnabled(False)
        self.spin_reg_val.setRange(0.0, 40.0)
        self.spin_reg_val.setValue(3.0)
        self.spin_reg_val.setSuffix(" dB")
        self.spin_reg_val.setDecimals(1)
        self.spin_reg_val.valueChanged.connect(self.update_engine_params)
        settings_form.addRow(tr("Reg. Value:"), self.spin_reg_val)
        tab_settings_layout.addWidget(self.settings_group)

        # Group 3: Simulation Control
        self.sim_ctrl_group = QGroupBox(tr("Simulation Control"))
        sim_ctrl_form = QFormLayout(self.sim_ctrl_group)
        sim_ctrl_form.setSpacing(6)

        self.combo_signal = QComboBox()
        self.combo_signal.addItems(
            [
                tr("1kHz Tone"),
                tr("3kHz Tone (Untrained)"),
                tr("Two-Tone (1.0k + 1.5k)"),
                tr("Multi-Tone (5 freqs)"),
                tr("Broadband Noise"),
                tr("Step Response"),
                tr("Impulse Response"),
            ]
        )
        self.combo_signal.currentIndexChanged.connect(self.run_simulation)
        sim_ctrl_form.addRow(tr("Test Signal:"), self.combo_signal)

        self.spin_amp = QDoubleSpinBox()
        self.spin_amp.setRange(0.01, 1.0)
        self.spin_amp.setSingleStep(0.05)
        self.spin_amp.setValue(0.30)
        self.spin_amp.valueChanged.connect(self.run_simulation)
        sim_ctrl_form.addRow(tr("Amplitude:"), self.spin_amp)

        tab_settings_layout.addWidget(self.sim_ctrl_group)
        tab_settings_layout.addStretch()

        sidebar_tabs.addTab(tab_model, tr("Model Source"))
        sidebar_tabs.addTab(tab_settings, tr("Compensation Settings"))

        main_layout.addWidget(sidebar_tabs)

        # Right Panel: Tabs
        self.tabs = QTabWidget()
        self.tabs.setMinimumWidth(200)
        self.setup_simulation_tab()
        self.setup_transient_tab()
        self.setup_linear_response_tab()
        self.setup_offline_tab()
        main_layout.addWidget(self.tabs, stretch=1)

        self.chk_iterative.toggled.connect(self.spin_iters.setEnabled)

    def set_controls_enabled(self, enabled):
        self.combo_comp_mode.setEnabled(enabled)
        self.combo_linear_smooth.setEnabled(enabled)
        self.chk_iterative.setEnabled(enabled)
        self.spin_iters.setEnabled(enabled and self.chk_iterative.isChecked())
        self.spin_fmin.setEnabled(enabled)
        self.spin_fmax.setEnabled(enabled)
        self.combo_oob_mode.setEnabled(enabled)
        self.combo_reg_mode.setEnabled(enabled)
        if enabled:
            self.on_reg_mode_changed()
        else:
            self.spin_reg_val.setEnabled(False)
        self.sim_ctrl_group.setEnabled(enabled)
        self.tabs.setTabEnabled(3, enabled)

    def adjust_fmax_range(self, val):
        self.spin_fmax.setMinimum(val + 10.0)

    def adjust_min_range(self, val):
        self.spin_fmin.setMaximum(val - 10.0)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if any(url.toLocalFile().lower().endswith(".wav") for url in urls):
                event.acceptProposedAction()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            filepath = url.toLocalFile()
            if filepath.lower().endswith(".wav"):
                self.lbl_in_file.setText(filepath)
                base, ext = os.path.splitext(filepath)
                self.lbl_out_file.setText(base + "_comp" + ext)
                self._update_process_btn()
                break

    def on_comp_mode_changed(self, index):
        # Modes:
        # 0: Linear & Nonlinear
        # 1: Nonlinear Only (No Linear EQ)
        # 2: Linear Only
        is_linear_only = index == 2
        self.chk_iterative.setEnabled(not is_linear_only)
        self.spin_iters.setEnabled(not is_linear_only and self.chk_iterative.isChecked())
        if self.module.engine:
            self.run_simulation()

    def setup_simulation_tab(self):
        sim_tab = QWidget()
        sim_layout = QVBoxLayout(sim_tab)

        # Results Label
        self.lbl_sim_results = QLabel(tr("Run simulation to see results."))
        self.lbl_sim_results.setStyleSheet(
            f"font-family: {MONOSPACE_FONT_FAMILY}; font-size: 11px; background-color: #2b2b2b; color: #a9b7c6; padding: 8px; border-radius: 4px;"
        )
        sim_layout.addWidget(self.lbl_sim_results)

        # Plot Widget
        self.plot_sim = pg.PlotWidget(title=tr("Spectrum Comparison"))
        self.plot_sim.setLabel("bottom", "Frequency", units="Hz")
        self.plot_sim.setLabel("left", "Magnitude", units="dBr")
        self.plot_sim.showGrid(x=True, y=True, alpha=0.3)
        self.plot_sim.addLegend()
        self.plot_sim.getPlotItem().getAxis("bottom").setLogMode(True)

        self.curve_uncomp = self.plot_sim.plot(pen="r", name=tr("Uncompensated"))
        self.curve_comp = self.plot_sim.plot(pen="g", name=tr("Compensated"))
        self.curve_linear = self.plot_sim.plot(pen="b", name=tr("Ideal Linear"))
        sim_layout.addWidget(self.plot_sim)

        self.tabs.addTab(sim_tab, tr("Spectrum"))

    def setup_transient_tab(self):
        trans_tab = QWidget()
        trans_layout = QVBoxLayout(trans_tab)
        trans_layout.setContentsMargins(5, 5, 5, 5)
        trans_layout.setSpacing(5)

        # Control / Description
        ctrl_layout = QHBoxLayout()

        # Add warning/explanation label
        lbl_info = QLabel(
            tr(
                "Note: Step transitions cause Gibbs ringing due to the Active Band filter (Fmin/Fmax) required for inverse filter stability."
            )
        )
        lbl_info.setStyleSheet("color: #e0a800; font-size: 10px;")
        lbl_info.setWordWrap(True)

        ctrl_layout.addWidget(lbl_info, stretch=1)
        trans_layout.addLayout(ctrl_layout)

        # Plot Widget
        self.plot_trans = pg.PlotWidget(title=tr("Transient Response (Time Domain)"))
        self.plot_trans.setLabel("bottom", tr("Time"), units="s")
        self.plot_trans.setLabel("left", tr("Amplitude"))
        self.plot_trans.showGrid(x=True, y=True, alpha=0.3)
        self.plot_trans.addLegend()

        self.curve_t_uncomp = self.plot_trans.plot(pen="r", name=tr("Uncompensated"))
        self.curve_t_comp = self.plot_trans.plot(pen="g", name=tr("Compensated"))
        self.curve_t_ideal_ref = self.plot_trans.plot(pen="b", name=tr("Ideal Reference"))

        trans_layout.addWidget(self.plot_trans)
        self.tabs.addTab(trans_tab, tr("Waveform"))

    def setup_offline_tab(self):
        off_tab = QWidget()
        off_layout = QFormLayout(off_tab)

        # Input File
        in_layout = QHBoxLayout()
        self.lbl_in_file = QLabel(tr("No file selected"))
        btn_in = QPushButton(tr("Browse..."))
        btn_in.clicked.connect(self.select_input_file)
        in_layout.addWidget(self.lbl_in_file, stretch=1)
        in_layout.addWidget(btn_in)
        off_layout.addRow(tr("Input File:"), in_layout)

        # Output File
        out_layout = QHBoxLayout()
        self.lbl_out_file = QLabel(tr("No output file"))
        btn_out = QPushButton(tr("Browse..."))
        btn_out.clicked.connect(self.select_output_file)
        out_layout.addWidget(self.lbl_out_file, stretch=1)
        out_layout.addWidget(btn_out)
        off_layout.addRow(tr("Output File:"), out_layout)

        # Volume Matching
        self.chk_output_matched_orig = QCheckBox(tr("Export Gain-Matched Original for Comparison"))
        self.chk_output_matched_orig.setChecked(True)
        off_layout.addRow(self.chk_output_matched_orig)

        # Abort on Instability
        self.chk_abort_on_instability = QCheckBox(tr("Abort on Instability"))
        self.chk_abort_on_instability.setChecked(True)
        off_layout.addRow(self.chk_abort_on_instability)

        self.btn_process_off = QPushButton(tr("Run Export"))
        self.btn_process_off.clicked.connect(self.start_offline_processing)
        self.btn_process_off.setEnabled(False)
        off_layout.addRow(self.btn_process_off)

        self.progress_off = QProgressBar()
        off_layout.addRow(self.progress_off)

        self.tabs.addTab(off_tab, tr("File Export"))

    def setup_linear_response_tab(self):
        lin_tab = QWidget()
        lin_layout = QVBoxLayout(lin_tab)
        lin_layout.setContentsMargins(5, 5, 5, 5)
        lin_layout.setSpacing(5)

        # Magnitude Plot
        self.plot_lin_mag = pg.PlotWidget(title=tr("Magnitude Response"))
        self.plot_lin_mag.setLabel("bottom", tr("Frequency"), units="Hz")
        self.plot_lin_mag.setLabel("left", tr("Magnitude"), units="dB")
        self.plot_lin_mag.showGrid(x=True, y=True, alpha=0.3)
        self.plot_lin_mag.addLegend()
        self.plot_lin_mag.getPlotItem().getAxis("bottom").setLogMode(True)

        self.curve_lin_mag_orig = self.plot_lin_mag.plot(pen="r", name=tr("Uncompensated (Linear)"))
        self.curve_lin_mag_filter = self.plot_lin_mag.plot(pen="g", name=tr("Inverse Filter"))
        self.curve_lin_mag_corr = self.plot_lin_mag.plot(pen="b", name=tr("Compensated (Overall)"))
        lin_layout.addWidget(self.plot_lin_mag, stretch=1)

        # Phase Plot
        self.plot_lin_phase = pg.PlotWidget(title=tr("Phase Response"))
        self.plot_lin_phase.setLabel("bottom", tr("Frequency"), units="Hz")
        self.plot_lin_phase.setLabel("left", tr("Phase"), units="deg")
        self.plot_lin_phase.showGrid(x=True, y=True, alpha=0.3)
        self.plot_lin_phase.addLegend()
        self.plot_lin_phase.getPlotItem().getAxis("bottom").setLogMode(True)

        self.curve_lin_phase_orig = self.plot_lin_phase.plot(pen="r", name=tr("Uncompensated (Linear)"))
        self.curve_lin_phase_filter = self.plot_lin_phase.plot(pen="g", name=tr("Inverse Filter"))
        self.curve_lin_phase_corr = self.plot_lin_phase.plot(pen="b", name=tr("Compensated (Overall)"))
        lin_layout.addWidget(self.plot_lin_phase, stretch=1)

        self.tabs.addTab(lin_tab, tr("Filter Response"))

    def update_linear_response_plot(self):
        if not self.module.engine:
            return

        engine = self.module.engine
        M = engine.N
        sr = engine.sample_rate

        Q_fft, F_inv_raw, _, bp_filter = engine._prepare_buffers_for_length(M)

        comp_mode_idx = self.combo_comp_mode.currentIndex()
        bypass_linear_eq = comp_mode_idx == 1

        if bypass_linear_eq:
            # If linear EQ is bypassed, the inverse filter for the linear path is effectively a thru filter (1.0)
            F_inv = np.ones_like(F_inv_raw)
            if engine.out_of_band_mode == "bypass_aligned":
                F_lin_abs = np.abs(Q_fft[1])
                F_inv = np.conj(Q_fft[1]) / np.maximum(F_lin_abs, 1e-12)
        else:
            F_inv = F_inv_raw.copy()

        # H1 peak index corresponds to the gate_pre offset inserted during kernel extraction.
        # Align the time origin to this peak for clear phase visualization without linear delay phase rotation.
        t_peak = np.argmax(np.abs(engine.q1_sc))
        freqs = np.fft.rfftfreq(M, d=1.0 / sr)
        phase_shift = np.exp(1j * 2 * np.pi * freqs * t_peak / sr)

        Q_fft_aligned = Q_fft[1] * phase_shift
        F_inv_aligned = F_inv * np.conj(phase_shift)

        # Q_fft[1] is H1 (linear response)
        # F_inv is the inverse filter for H1
        # Compensated overall is H1 * F_inv
        mag_orig = 20 * np.log10(np.abs(Q_fft_aligned) + 1e-12)
        mag_filter = 20 * np.log10(np.abs(F_inv_aligned) + 1e-12)
        mag_corr = 20 * np.log10(np.abs(Q_fft[1] * F_inv) + 1e-12)

        phase_orig = np.degrees(np.angle(Q_fft_aligned))
        phase_filter = np.degrees(np.angle(F_inv_aligned))
        phase_corr = np.degrees(np.angle(Q_fft[1] * F_inv))

        freqs = np.fft.rfftfreq(M, d=1.0 / sr)
        freqs_plot = freqs.copy()
        freqs_plot[0] = freqs_plot[1] / 10.0
        log_freqs = np.log10(freqs_plot)

        # Plot magnitudes (they do not contain NaN)
        self.curve_lin_mag_orig.setData(log_freqs, mag_orig)
        self.curve_lin_mag_filter.setData(log_freqs, mag_filter)
        self.curve_lin_mag_corr.setData(log_freqs, mag_corr)

        # Mask out phase where the magnitude is extremely low (e.g. below -60 dB)
        # to prevent noisy phase oscillation in stopbands or zero-energy bins.
        # Filter the arrays directly to prevent PyQtGraph/Qt C++ crash with NaN values.
        mask_orig = mag_orig > -60.0
        mask_filter = mag_filter > -60.0
        mask_corr = mag_corr > -60.0

        self.curve_lin_phase_orig.setData(log_freqs[mask_orig], phase_orig[mask_orig])
        self.curve_lin_phase_filter.setData(log_freqs[mask_filter], phase_filter[mask_filter])
        self.curve_lin_phase_corr.setData(log_freqs[mask_corr], phase_corr[mask_corr])

        self.plot_lin_mag.setXRange(np.log10(20), np.log10(sr / 2), padding=0.02)
        self.plot_lin_mag.setYRange(-60, 20, padding=0.0)

        self.plot_lin_phase.setXRange(np.log10(20), np.log10(sr / 2), padding=0.02)
        self.plot_lin_phase.setYRange(-190, 190, padding=0.0)

    # Online processing features removed to optimize for standard PC performance.

    def get_oob_mode(self):
        mode_idx = self.combo_oob_mode.currentIndex()
        modes = ["cut", "bypass_aligned", "bypass_pure"]
        return modes[mode_idx]

    def get_linear_smoothing_fraction(self):
        idx = self.combo_linear_smooth.currentIndex()
        fractions = [0.0, 48.0, 24.0, 12.0, 6.0, 3.0]
        return fractions[idx]

    def get_reg_params(self):
        mode_idx = self.combo_reg_mode.currentIndex()
        modes = ["auto_broadband", "auto_tones", "manual_boost", "manual_tikhonov"]
        reg_mode = modes[mode_idx]
        reg_val = self.spin_reg_val.value()
        return reg_mode, reg_val

    def on_reg_mode_changed(self):
        mode_idx = self.combo_reg_mode.currentIndex()
        # Modes:
        # 0: Auto (Broadband / Music)
        # 1: Auto (Pure Tones)
        # 2: Manual (Max Boost)
        # 3: Manual (Tikhonov)

        self.spin_reg_val.blockSignals(True)

        if mode_idx == 0:  # Auto (Broadband / Music)
            self.spin_reg_val.setEnabled(False)
            self.spin_reg_val.setSuffix(" dB")
            self.spin_reg_val.setDecimals(1)
            self.spin_reg_val.setRange(0.0, 40.0)
            self.spin_reg_val.setValue(3.0)
        elif mode_idx == 1:  # Auto (Pure Tones)
            self.spin_reg_val.setEnabled(False)
            self.spin_reg_val.setSuffix(" dB")
            self.spin_reg_val.setDecimals(1)
            self.spin_reg_val.setRange(0.0, 40.0)
            self.spin_reg_val.setValue(20.0)
        elif mode_idx == 2:  # Manual (Max Boost)
            self.spin_reg_val.setEnabled(True)
            self.spin_reg_val.setSuffix(" dB")
            self.spin_reg_val.setDecimals(1)
            self.spin_reg_val.setRange(0.0, 40.0)
            self.spin_reg_val.setSingleStep(0.5)
            self.spin_reg_val.setValue(12.0)
        elif mode_idx == 3:  # Manual (Tikhonov)
            self.spin_reg_val.setEnabled(True)
            self.spin_reg_val.setSuffix("")
            self.spin_reg_val.setDecimals(6)
            self.spin_reg_val.setRange(1e-6, 1.0)
            self.spin_reg_val.setSingleStep(0.01)
            self.spin_reg_val.setValue(0.20)

        self.spin_reg_val.blockSignals(False)
        self.update_engine_params()

    def load_model(self):
        path, _ = QFileDialog.getOpenFileName(self, tr("Load Forward Model"), "", tr("JSON Files (*.json)"))
        if path:
            try:
                with open(path, "r") as f:
                    data = json.load(f)

                reg_mode, reg_val = self.get_reg_params()
                oob_mode = self.get_oob_mode()
                self.module.engine = LICFFEngine(
                    data,
                    f_min=self.spin_fmin.value(),
                    f_max=self.spin_fmax.value(),
                    reg_mode=reg_mode,
                    reg_val=reg_val,
                    out_of_band_mode=oob_mode,
                    linear_smoothing_fraction=self.get_linear_smoothing_fraction(),
                )
                self.model_data = data

                self.lbl_status.setText(tr("Model Loaded"))
                self.lbl_status.setStyleSheet("font-weight: bold; color: #5cb85c;")
                self.lbl_sr.setText(f"{self.module.engine.sample_rate} Hz")
                self.lbl_n.setText(f"{self.module.engine.N}")
                self.lbl_max_boost.setText(f"{self.module.engine.get_max_inverse_filter_boost_db():.2f} dB")
                self.lbl_resolved_eps.setText(f"{self.module.engine.last_resolved_eps_in:.2e}")

                self.set_controls_enabled(True)
                self._update_process_btn()
                self.update_linear_response_plot()
                self.run_simulation()

                QMessageBox.information(self, tr("Success"), tr("Nonlinear model loaded successfully."))
            except Exception as e:
                self.lbl_status.setText(tr("Error Loading Model"))
                self.lbl_status.setStyleSheet("font-weight: bold; color: #d9534f;")
                self.set_controls_enabled(False)
                self._update_process_btn()
                QMessageBox.critical(self, tr("Error"), tr("Failed to load model file: {0}").format(e))

    def update_engine_params(self):
        if self.module.engine:
            reg_mode, reg_val = self.get_reg_params()
            oob_mode = self.get_oob_mode()
            self.module.engine.f_min = self.spin_fmin.value()
            self.module.engine.f_max = self.spin_fmax.value()
            self.module.engine.reg_mode = reg_mode
            self.module.engine.reg_val = reg_val
            self.module.engine.out_of_band_mode = oob_mode
            self.module.engine.linear_smoothing_fraction = self.get_linear_smoothing_fraction()
            self.module.engine.rebuild_filter()
            self.lbl_max_boost.setText(f"{self.module.engine.get_max_inverse_filter_boost_db():.2f} dB")
            self.lbl_resolved_eps.setText(f"{self.module.engine.last_resolved_eps_in:.2e}")
            self.update_linear_response_plot()
            self.run_simulation()

    def run_simulation(self):
        if not self.module.engine:
            return

        engine = self.module.engine
        N = engine.N
        sr = engine.sample_rate
        amp = self.spin_amp.value()
        sig_type = self.combo_signal.currentText()

        t = np.arange(N) / sr

        # Generate signal
        if sig_type == tr("1kHz Tone"):
            u = amp * np.sin(2 * np.pi * 1000.0 * t)
            f_test = 1000.0
        elif sig_type == tr("3kHz Tone (Untrained)"):
            u = amp * np.sin(2 * np.pi * 3000.0 * t)
            f_test = 3000.0
        elif sig_type == tr("Two-Tone (1.0k + 1.5k)"):
            u = (amp / 2.0) * (np.sin(2 * np.pi * 1000.0 * t) + np.sin(2 * np.pi * 1500.0 * t))
            f_test = 1000.0
        elif sig_type == tr("Multi-Tone (5 freqs)"):
            u = (amp / 2.5) * sum(np.sin(2 * np.pi * f * t) for f in [300, 700, 1300, 2700, 5500])
            f_test = 1300.0
        elif sig_type == tr("Step Response"):
            u_raw = np.zeros(N)
            u_raw[N // 10 :] = amp
            _, _, _, bp_filter = engine._prepare_buffers_for_length(N)
            U_fft = np.fft.rfft(u_raw)
            u = np.fft.irfft(U_fft * bp_filter, n=N)
            max_val = np.max(np.abs(u))
            if max_val > 1e-12:
                u = u * (amp / max_val)
            f_test = 1000.0
        elif sig_type == tr("Impulse Response"):
            u = np.zeros(N)
            u[N // 10] = amp
            f_test = 1000.0
        else:  # Broadband Noise
            rng = np.random.default_rng(99)
            noise_fft = np.exp(1j * rng.uniform(0, 2 * np.pi, N // 2 + 1))
            noise_fft[0] = 0.0
            noise_fft[-1] = 0.0
            _, _, _, bp_filter = engine._prepare_buffers_for_length(N)
            u = np.fft.irfft(noise_fft * bp_filter, n=N)
            u = u / np.max(np.abs(u)) * amp
            f_test = 1000.0

        # Compensate
        iterative = self.chk_iterative.isChecked()
        iters = self.spin_iters.value()
        clip_limit = 2.0

        comp_mode_idx = self.combo_comp_mode.currentIndex()
        linear_only = comp_mode_idx == 2
        bypass_linear_eq = comp_mode_idx == 1

        u_comp = engine.compensate(
            u,
            iterative=iterative,
            iters=iters,
            clip_limit=clip_limit,
            linear_only=linear_only,
            bypass_linear_eq=bypass_linear_eq,
        )

        # Output
        y_uncomp = engine.forward_model(u)
        y_comp = engine.forward_model(u_comp)
        y_linear = engine.linear_output(u)

        # Plot Spectrum
        freqs = np.fft.rfftfreq(N, d=1.0 / sr)
        Y_uncomp_raw = 20 * np.log10(np.abs(np.fft.rfft(y_uncomp)) + 1e-12)
        Y_comp_raw = 20 * np.log10(np.abs(np.fft.rfft(y_comp)) + 1e-12)
        Y_linear_raw = 20 * np.log10(np.abs(np.fft.rfft(y_linear)) + 1e-12)

        # Normalize relative to the peak of the ideal linear response (dBr)
        ref_level = np.max(Y_linear_raw)
        Y_uncomp = Y_uncomp_raw - ref_level
        Y_comp = Y_comp_raw - ref_level
        Y_linear = Y_linear_raw - ref_level

        # Limit plot bounds to avoid log(0) issues
        freqs_plot = freqs.copy()
        freqs_plot[0] = freqs_plot[1] / 10.0
        log_freqs = np.log10(freqs_plot)

        self.curve_uncomp.setData(log_freqs, Y_uncomp)
        self.curve_comp.setData(log_freqs, Y_comp)
        self.curve_linear.setData(log_freqs, Y_linear)
        self.plot_sim.setXRange(np.log10(20), np.log10(sr / 2), padding=0.02)
        self.plot_sim.setYRange(-140, 10, padding=0.0)

        # Band-limited ideal linear response: H1 * bp_filter * u
        Q_fft, _, _, bp_filter = engine._prepare_buffers_for_length(N)
        y_bl_linear = np.fft.irfft(np.fft.rfft(u) * bp_filter * Q_fft[1], n=N)

        # Update Transient Plot
        t_peak = np.argmax(np.abs(engine.q1_sc))
        t_axis = (np.arange(N) - t_peak) / sr

        self.curve_t_uncomp.setData(t_axis, y_uncomp)

        # Both linear-only and nonlinear compensation cancel the group delay (t_peak).
        # To align the compensated output with the other reference curves (which are left-shifted by t_peak),
        # we shift y_comp forward in time (right-shift by t_peak).
        is_transient = "Step" in sig_type or "Impulse" in sig_type
        if is_transient:
            # Shift and pad with zeros to avoid wrap-around artifacts in transient responses
            if t_peak > 0:
                y_comp_aligned = np.zeros_like(y_comp)
                y_comp_aligned[t_peak:] = y_comp[:-t_peak]
            elif t_peak < 0:
                y_comp_aligned = np.zeros_like(y_comp)
                y_comp_aligned[:t_peak] = y_comp[-t_peak:]
            else:
                y_comp_aligned = y_comp.copy()
        else:
            # For periodic signals (tones/noise), np.roll is fine
            y_comp_aligned = np.roll(y_comp, t_peak)

        self.curve_t_comp.setData(t_axis, y_comp_aligned)
        self.curve_t_ideal_ref.setData(t_axis, y_bl_linear)
        self.curve_t_ideal_ref.show()

        if "Step" in sig_type or "Impulse" in sig_type:
            self.plot_trans.setXRange(t_axis[0], min(0.010, t_axis[-1]), padding=0.0)
        else:
            self.plot_trans.setXRange(t_axis[0], t_axis[-1], padding=0.0)

        # Metrics calculation
        def calculate_thd_db(y_sig, f_ref):
            N_fft = len(y_sig)
            Y_fft = np.fft.rfft(y_sig)
            freqs_fft = np.fft.rfftfreq(N_fft, d=1.0 / sr)
            idx_fund = np.argmin(np.abs(freqs_fft - f_ref))
            w_bin = 3
            fund_search = range(max(0, idx_fund - w_bin), min(len(freqs_fft), idx_fund + w_bin + 1))
            idx_fund_peak = max(fund_search, key=lambda i: np.abs(Y_fft[i]))
            fund_pow = np.abs(Y_fft[idx_fund_peak]) ** 2

            harmonic_powers = []
            for h in [2, 3, 4, 5]:
                f_h = h * f_ref
                if f_h > sr / 2:
                    break
                idx_h = np.argmin(np.abs(freqs_fft - f_h))
                h_search = range(max(0, idx_h - w_bin), min(len(freqs_fft), idx_h + w_bin + 1))
                idx_h_peak = max(h_search, key=lambda i: np.abs(Y_fft[i]))
                harmonic_powers.append(np.abs(Y_fft[idx_h_peak]) ** 2)

            thd = np.sqrt(sum(harmonic_powers)) / (np.sqrt(fund_pow) + 1e-12)
            return 20 * np.log10(thd + 1e-12)

        def calculate_sdr_db(y_sig, y_ref_sig):
            y_sig_ac = y_sig - np.mean(y_sig)
            y_ref_ac = y_ref_sig - np.mean(y_ref_sig)

            C = np.fft.irfft(np.fft.rfft(y_sig_ac) * np.conj(np.fft.rfft(y_ref_ac)), n=len(y_sig_ac))
            delay = np.argmax(np.abs(C))
            if delay > len(y_sig_ac) // 2:
                delay -= len(y_sig_ac)
            y_sig_aligned = np.roll(y_sig_ac, -delay)

            corr_val = C[delay]
            sign = np.sign(corr_val) if np.abs(corr_val) > 1e-12 else 1.0

            rms_ref = np.sqrt(np.mean(y_ref_ac**2))
            rms_sig = np.sqrt(np.mean(y_sig_aligned**2))
            y_sig_scaled = y_sig_aligned * sign * (rms_ref / (rms_sig + 1e-12))

            err = y_sig_scaled - y_ref_ac
            sdr = 20 * np.log10(rms_ref / (np.sqrt(np.mean(err**2)) + 1e-12))
            return sdr

        is_multitone = sig_type in [tr("Two-Tone (1.0k + 1.5k)"), tr("Multi-Tone (5 freqs)")]
        is_noise = sig_type == tr("Broadband Noise")
        is_transient = "Step" in sig_type or "Impulse" in sig_type

        if is_multitone:
            dist_name = "TD+N"
            if sig_type == tr("Two-Tone (1.0k + 1.5k)"):
                expected_tones = [1000.0, 1500.0]
            else:
                expected_tones = [300.0, 700.0, 1300.0, 2700.0, 5500.0]

            freqs_fft = np.fft.rfftfreq(N, d=1.0 / sr)
            mag_uncomp = np.abs(np.fft.rfft(y_uncomp))
            mag_comp = np.abs(np.fft.rfft(y_comp))

            dist_uncomp = AudioCalc.calculate_multitone_tdn(mag_uncomp, freqs_fft, expected_tones)["tdn_db"]
            dist_comp = AudioCalc.calculate_multitone_tdn(mag_comp, freqs_fft, expected_tones)["tdn_db"]
        elif is_noise or is_transient:
            dist_name = "TD+N"
            dist_uncomp = None
            dist_comp = None
        else:
            dist_name = "THD"
            dist_uncomp = calculate_thd_db(y_uncomp, f_test)
            dist_comp = calculate_thd_db(y_comp, f_test)

        sdr_uncomp = calculate_sdr_db(y_uncomp, y_linear)
        sdr_comp = calculate_sdr_db(y_comp, y_linear)

        sdr_improvement = sdr_comp - sdr_uncomp
        sdr_imp_color = "#5cb85c" if sdr_improvement >= 0 else "#d9534f"

        if is_noise or is_transient:
            results_html = (
                f"<h4>=== {sig_type} Simulation Results ===</h4>"
                f"<table style='font-family: {MONOSPACE_FONT_FAMILY}; font-size: 11px; border-spacing: 12px 2px; color: #a9b7c6;'>"
                f"<tr><td><b>Metric</b></td><td><b>Uncompensated</b></td><td><b>Compensated</b></td><td><b>Improvement</b></td></tr>"
                f"<tr><td>SDR</td><td>{sdr_uncomp:6.2f} dB</td><td>{sdr_comp:6.2f} dB</td>"
                f"<td><span style='color: {sdr_imp_color}; font-weight: bold;'>{sdr_improvement:+.2f} dB</span></td></tr>"
                f"</table>"
            )
        else:
            suppression = dist_uncomp - dist_comp
            sup_color = "#5cb85c" if suppression >= 0 else "#d9534f"
            results_html = (
                f"<h4>=== {sig_type} Simulation Results ===</h4>"
                f"<table style='font-family: {MONOSPACE_FONT_FAMILY}; font-size: 11px; border-spacing: 12px 2px; color: #a9b7c6;'>"
                f"<tr><td><b>Metric</b></td><td><b>Uncompensated</b></td><td><b>Compensated</b></td><td><b>Improvement</b></td></tr>"
                f"<tr><td>{dist_name}</td><td>{dist_uncomp:6.2f} dB</td><td>{dist_comp:6.2f} dB</td>"
                f"<td><span style='color: {sup_color}; font-weight: bold;'>{suppression:+.2f} dB</span></td></tr>"
                f"<tr><td>SDR</td><td>{sdr_uncomp:6.2f} dB</td><td>{sdr_comp:6.2f} dB</td>"
                f"<td><span style='color: {sdr_imp_color}; font-weight: bold;'>{sdr_improvement:+.2f} dB</span></td></tr>"
                f"</table>"
            )
        self.lbl_sim_results.setText(results_html)

    def select_input_file(self):
        path, _ = QFileDialog.getOpenFileName(self, tr("Open Wav File"), "", tr("Wav Files (*.wav)"))
        if path:
            self.lbl_in_file.setText(path)
            self._update_process_btn()
            base, ext = os.path.splitext(path)
            self.lbl_out_file.setText(base + "_comp" + ext)

    def select_output_file(self):
        path, _ = QFileDialog.getSaveFileName(
            self, tr("Save Wav File"), self.lbl_out_file.text(), tr("Wav Files (*.wav)")
        )
        if path:
            self.lbl_out_file.setText(path)
            self._update_process_btn()

    def _update_process_btn(self):
        has_in = os.path.exists(self.lbl_in_file.text())
        has_out = self.lbl_out_file.text() != tr("No output file")
        self.btn_process_off.setEnabled(has_in and has_out and self.model_data is not None)

    def start_offline_processing(self):
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.btn_process_off.setEnabled(False)
            self.btn_process_off.setText(tr("Cancelling..."))
            return

        input_path = self.lbl_in_file.text()
        output_path = self.lbl_out_file.text()
        iterative = self.chk_iterative.isChecked()
        iters = self.spin_iters.value()
        clip_limit = 2.0

        comp_mode_idx = self.combo_comp_mode.currentIndex()
        linear_only = comp_mode_idx == 2
        bypass_linear_eq = comp_mode_idx == 1

        abort_on_instability = self.chk_abort_on_instability.isChecked()
        vol_match = "rms" if self.chk_output_matched_orig.isChecked() else "none"

        self.btn_process_off.setText(tr("Cancel"))
        self.progress_off.setValue(0)

        self.worker = OfflineFFCompWorker(
            input_path,
            output_path,
            self.module.engine,
            iterative,
            iters,
            clip_limit,
            linear_only=linear_only,
            bypass_linear_eq=bypass_linear_eq,
            volume_matching=vol_match,
            abort_on_instability=abort_on_instability,
        )
        self.worker.progress.connect(self.progress_off.setValue)
        self.worker.finished.connect(self.on_offline_finished)
        self.worker.start()

    def on_offline_finished(self, success, msg):
        self.btn_process_off.setText(tr("Run Export"))
        self._update_process_btn()
        if success:
            QMessageBox.information(self, tr("Success"), msg)
        else:
            QMessageBox.critical(self, tr("Error"), msg)

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait()
        super().closeEvent(event)
