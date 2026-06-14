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
    QScrollArea,
    QProgressBar,
    QCheckBox,
    QComboBox,
)
import pyqtgraph as pg

from src.core.localization import tr
from src.measurement_modules.base import MeasurementModule
from src.core.analysis import AudioCalc
from src.gui.styles import MONOSPACE_FONT_FAMILY

logger = logging.getLogger(__name__)


class LICFFEngine:
    """
    Core engine to perform Linear-Inverse Compensated Feedforward (LICFF)
    based on a loaded Hammerstein system model.
    """

    def __init__(self, model_data, f_min=60.0, f_max=17000.0, threshold_db=None):
        self.model_data = model_data
        self.f_min = f_min
        self.f_max = f_max
        self.threshold_db = threshold_db
        self.sample_rate = 48000
        self.N = 0
        self.q0_sum = 0.0

        # Buffer caching for arbitrary block sizes
        self._cached_M = 0
        self._cached_Q_fft = []
        self._cached_F_inv = None
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
        self._cached_F_inv = None
        self._cached_bp_filter = None

    def rebuild_filter(self):
        self.clear_cache()

    def _prepare_buffers_for_length(self, M):
        if self._cached_M == M:
            return self._cached_Q_fft, self._cached_F_inv, self._cached_bp_filter

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

        # Linear inverse filter F_inv for length M
        F_lin_abs = np.abs(Q_fft_M[1])
        eps_in = 1e-6
        eps_out = 0.5
        eps_f = eps_in + (eps_out - eps_in) * (1.0 - bp_filter_M)
        F_inv_M = np.conj(Q_fft_M[1]) / (F_lin_abs**2 + eps_f)
        F_inv_M = F_inv_M * bp_filter_M

        # Cache it
        self._cached_M = M
        self._cached_Q_fft = Q_fft_M
        self._cached_F_inv = F_inv_M
        self._cached_bp_filter = bp_filter_M

        return Q_fft_M, F_inv_M, bp_filter_M

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
        Q_fft, _, _ = self._prepare_buffers_for_length(M)

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
        Q_fft, _, _ = self._prepare_buffers_for_length(M)

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
        Q_fft, _, _ = self._prepare_buffers_for_length(M)
        return np.fft.irfft(np.fft.rfft(x) * Q_fft[1], n=M)

    def nonlinear_output(self, x):
        M = len(x)
        Y_fft = self.nonlinear_spectrum(x)
        return np.fft.irfft(Y_fft, n=M) + self.q0_sum

    def compensate(self, u_in, iterative=True, iters=3, clip_limit=1.5, linear_only=False):
        M = len(u_in)
        _, F_inv, bp_filter = self._prepare_buffers_for_length(M)

        if linear_only:
            U_in_fft = np.fft.rfft(u_in)
            u_comp = np.fft.irfft(U_in_fft * F_inv, n=M)
            u_comp = np.clip(u_comp, -clip_limit, clip_limit)
            return u_comp

        # Filter signal to active band
        U_in_fft = np.fft.rfft(u_in)
        u_in_filt = np.fft.irfft(U_in_fft * bp_filter, n=M)

        if not iterative:
            iters = 1

        u_comp = u_in_filt.copy()
        for _ in range(iters):
            Y_fft = self.nonlinear_spectrum(u_comp)
            # Apply linear inverse filter
            y_comp_nl = np.fft.irfft(Y_fft * F_inv, n=M)
            u_comp = u_in_filt - y_comp_nl

        u_comp = np.clip(u_comp, -clip_limit, clip_limit)
        return u_comp


class OfflineFFCompWorker(QThread):
    progress = pyqtSignal(int)
    finished = pyqtSignal(bool, str)

    def __init__(self, input_path, output_path, engine, iterative, iters, clip_limit, linear_only=False):
        super().__init__()
        self.input_path = input_path
        self.output_path = output_path
        self.engine = engine
        self.iterative = iterative
        self.iters = iters
        self.clip_limit = clip_limit
        self.linear_only = linear_only
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

                # Processing Block Configuration
                block_size = 65536
                overlap = 4096
                num_blocks = (M + block_size - 1) // block_size

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
                        # Apply compensation on the overlap block
                        u_comp = self.engine.compensate(
                            x_ch,
                            iterative=self.iterative,
                            iters=self.iters,
                            clip_limit=self.clip_limit,
                            linear_only=self.linear_only,
                        )
                        # Extract the valid non-overlapped part
                        chunk_out[:, ch] = u_comp[overlap : overlap + L_block]

                    out_data[start_out:end_out, :] = chunk_out
                    self.progress.emit(int(((b_idx + 1) / num_blocks) * 100))

                max_val = np.max(np.abs(out_data))
                clipping_msg = ""
                if max_val > 1.0:
                    clipping_msg = "\n" + tr(
                        "Warning: Output signal peaks at {0:.2f} dBFS. Output was normalized to avoid digital clipping."
                    ).format(20 * np.log10(max_val))
                    out_data = out_data / max_val

                sf.write(
                    self.output_path,
                    out_data,
                    int(model_sr),
                    subtype="PCM_24" if info.subtype == "PCM_24" else "PCM_16",
                )
                self.finished.emit(
                    True,
                    tr("Successfully processed and saved to {0}").format(os.path.basename(self.output_path))
                    + resample_msg
                    + clipping_msg,
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

    def init_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setSpacing(5)

        # Left Panel: Sidebar wrapped in Scroll Area
        sidebar_scroll = QScrollArea()
        sidebar_scroll.setFixedWidth(330)
        sidebar_scroll.setWidgetResizable(True)
        sidebar_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        sidebar_content = QWidget()
        sidebar_layout = QVBoxLayout(sidebar_content)
        sidebar_layout.setContentsMargins(0, 0, 4, 0)
        sidebar_layout.setSpacing(8)

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

        info_layout = QFormLayout()
        info_layout.setSpacing(4)
        info_layout.addRow(tr("Status:"), self.lbl_status)
        info_layout.addRow(tr("Rate:"), self.lbl_sr)
        info_layout.addRow(tr("N Samples:"), self.lbl_n)
        source_form.addLayout(info_layout)
        sidebar_layout.addWidget(source_group)

        # Group 2: Compensation Settings
        settings_group = QGroupBox(tr("Compensation Settings"))
        settings_form = QFormLayout(settings_group)
        settings_form.setSpacing(6)

        self.chk_linear_only = QCheckBox(tr("Linear-Only Compensation"))
        self.chk_linear_only.setChecked(False)
        self.chk_linear_only.toggled.connect(self.on_linear_only_toggled)
        settings_form.addRow(self.chk_linear_only)

        self.chk_iterative = QCheckBox(tr("Enable Iterative Compensation"))
        self.chk_iterative.setChecked(True)
        self.chk_iterative.toggled.connect(self.update_engine_params)
        settings_form.addRow(self.chk_iterative)

        self.spin_iters = QSpinBox()
        self.spin_iters.setRange(1, 20)
        self.spin_iters.setValue(3)
        self.spin_iters.valueChanged.connect(self.update_engine_params)
        settings_form.addRow(tr("Iterations:"), self.spin_iters)

        self.spin_clip = QDoubleSpinBox()
        self.spin_clip.setRange(0.5, 2.0)
        self.spin_clip.setSingleStep(0.1)
        self.spin_clip.setValue(1.5)
        settings_form.addRow(tr("Clip Limit:"), self.spin_clip)

        self.spin_fmin = QDoubleSpinBox()
        self.spin_fmin.setRange(10, 20000)
        self.spin_fmin.setValue(60)
        self.spin_fmin.setSuffix(" Hz")
        self.spin_fmin.valueChanged.connect(self.update_engine_params)
        settings_form.addRow(tr("Active Band Fmin:"), self.spin_fmin)

        self.spin_fmax = QDoubleSpinBox()
        self.spin_fmax.setRange(10, 24000)
        self.spin_fmax.setValue(17000)
        self.spin_fmax.setSuffix(" Hz")
        self.spin_fmax.valueChanged.connect(self.update_engine_params)
        settings_form.addRow(tr("Active Band Fmax:"), self.spin_fmax)

        sidebar_layout.addWidget(settings_group)
        sidebar_scroll.setWidget(sidebar_content)
        main_layout.addWidget(sidebar_scroll)

        # Right Panel: Tabs
        self.tabs = QTabWidget()
        self.setup_simulation_tab()
        self.setup_linear_response_tab()
        self.setup_offline_tab()
        main_layout.addWidget(self.tabs, stretch=1)

        self.chk_iterative.toggled.connect(self.spin_iters.setEnabled)

    def on_linear_only_toggled(self, checked):
        self.chk_iterative.setEnabled(not checked)
        self.spin_iters.setEnabled(not checked and self.chk_iterative.isChecked())
        if self.module.engine:
            self.run_simulation()

    def setup_simulation_tab(self):
        sim_tab = QWidget()
        sim_layout = QVBoxLayout(sim_tab)

        ctrl_layout = QHBoxLayout()
        self.combo_signal = QComboBox()
        self.combo_signal.addItems(
            [
                tr("1kHz Tone"),
                tr("3kHz Tone (Untrained)"),
                tr("Two-Tone (1.0k + 1.5k)"),
                tr("Multi-Tone (5 freqs)"),
                tr("Broadband Noise"),
            ]
        )
        ctrl_layout.addWidget(QLabel(tr("Test Signal:")))
        ctrl_layout.addWidget(self.combo_signal)

        self.spin_amp = QDoubleSpinBox()
        self.spin_amp.setRange(0.01, 1.0)
        self.spin_amp.setSingleStep(0.05)
        self.spin_amp.setValue(0.30)
        ctrl_layout.addWidget(QLabel(tr("Amplitude:")))
        ctrl_layout.addWidget(self.spin_amp)

        self.btn_run_sim = QPushButton(tr("Run Simulation"))
        self.btn_run_sim.clicked.connect(self.run_simulation)
        self.btn_run_sim.setEnabled(False)
        ctrl_layout.addWidget(self.btn_run_sim)
        sim_layout.addLayout(ctrl_layout)

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

        self.tabs.addTab(sim_tab, tr("Simulation"))

    def setup_offline_tab(self):
        off_tab = QWidget()
        off_layout = QFormLayout(off_tab)

        # Input File
        in_layout = QHBoxLayout()
        self.lbl_in_file = QLabel(tr("No file selected"))
        btn_in = QPushButton(tr("Select Input Wav..."))
        btn_in.clicked.connect(self.select_input_file)
        in_layout.addWidget(self.lbl_in_file, stretch=1)
        in_layout.addWidget(btn_in)
        off_layout.addRow(tr("Input Wav:"), in_layout)

        # Output File
        out_layout = QHBoxLayout()
        self.lbl_out_file = QLabel(tr("No output file"))
        btn_out = QPushButton(tr("Select Output Wav..."))
        btn_out.clicked.connect(self.select_output_file)
        out_layout.addWidget(self.lbl_out_file, stretch=1)
        out_layout.addWidget(btn_out)
        off_layout.addRow(tr("Output Wav:"), out_layout)

        self.btn_process_off = QPushButton(tr("Process & Save"))
        self.btn_process_off.clicked.connect(self.start_offline_processing)
        self.btn_process_off.setEnabled(False)
        off_layout.addRow(self.btn_process_off)

        self.progress_off = QProgressBar()
        off_layout.addRow(self.progress_off)

        self.tabs.addTab(off_tab, tr("Offline Processing"))

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

        self.tabs.addTab(lin_tab, tr("Linear Response"))

    def update_linear_response_plot(self):
        if not self.module.engine:
            return

        engine = self.module.engine
        M = engine.N
        sr = engine.sample_rate

        Q_fft, F_inv, bp_filter = engine._prepare_buffers_for_length(M)

        # Q_fft[1] is H1 (linear response)
        # F_inv is the inverse filter for H1
        # Compensated overall is H1 * F_inv
        mag_orig = 20 * np.log10(np.abs(Q_fft[1]) + 1e-12)
        mag_filter = 20 * np.log10(np.abs(F_inv) + 1e-12)
        mag_corr = 20 * np.log10(np.abs(Q_fft[1] * F_inv) + 1e-12)

        phase_orig = np.degrees(np.angle(Q_fft[1]))
        phase_filter = np.degrees(np.angle(F_inv))
        phase_corr = np.degrees(np.angle(Q_fft[1] * F_inv))

        freqs = np.fft.rfftfreq(M, d=1.0 / sr)
        freqs_plot = freqs.copy()
        freqs_plot[0] = freqs_plot[1] / 10.0
        log_freqs = np.log10(freqs_plot)

        self.curve_lin_mag_orig.setData(log_freqs, mag_orig)
        self.curve_lin_mag_filter.setData(log_freqs, mag_filter)
        self.curve_lin_mag_corr.setData(log_freqs, mag_corr)

        self.curve_lin_phase_orig.setData(log_freqs, phase_orig)
        self.curve_lin_phase_filter.setData(log_freqs, phase_filter)
        self.curve_lin_phase_corr.setData(log_freqs, phase_corr)

        self.plot_lin_mag.setXRange(np.log10(20), np.log10(sr / 2), padding=0.02)
        self.plot_lin_mag.setYRange(-60, 20, padding=0.0)

        self.plot_lin_phase.setXRange(np.log10(20), np.log10(sr / 2), padding=0.02)
        self.plot_lin_phase.setYRange(-190, 190, padding=0.0)

    # Online processing features removed to optimize for standard PC performance.

    def load_model(self):
        path, _ = QFileDialog.getOpenFileName(self, tr("Load Forward Model"), "", tr("JSON Files (*.json)"))
        if path:
            try:
                with open(path, "r") as f:
                    data = json.load(f)

                self.module.engine = LICFFEngine(data, f_min=self.spin_fmin.value(), f_max=self.spin_fmax.value())
                self.model_data = data

                self.lbl_status.setText(tr("Model Loaded"))
                self.lbl_status.setStyleSheet("font-weight: bold; color: #5cb85c;")
                self.lbl_sr.setText(f"{self.module.engine.sample_rate} Hz")
                self.lbl_n.setText(f"{self.module.engine.N}")

                self.btn_run_sim.setEnabled(True)
                self._update_process_btn()
                self.update_linear_response_plot()

                QMessageBox.information(self, tr("Success"), tr("Hammerstein model loaded successfully."))
            except Exception as e:
                self.lbl_status.setText(tr("Error Loading Model"))
                self.lbl_status.setStyleSheet("font-weight: bold; color: #d9534f;")
                self.btn_run_sim.setEnabled(False)
                self._update_process_btn()
                QMessageBox.critical(self, tr("Error"), tr("Failed to load model file: {0}").format(e))

    def update_engine_params(self):
        if self.module.engine:
            self.module.engine.f_min = self.spin_fmin.value()
            self.module.engine.f_max = self.spin_fmax.value()
            self.module.engine.rebuild_filter()
            self.update_linear_response_plot()

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
        else:  # Broadband Noise
            rng = np.random.default_rng(99)
            noise_fft = np.exp(1j * rng.uniform(0, 2 * np.pi, N // 2 + 1))
            noise_fft[0] = 0.0
            noise_fft[-1] = 0.0
            _, _, bp_filter = engine._prepare_buffers_for_length(N)
            u = np.fft.irfft(noise_fft * bp_filter, n=N)
            u = u / np.max(np.abs(u)) * amp
            f_test = 1000.0

        # Compensate
        iterative = self.chk_iterative.isChecked()
        iters = self.spin_iters.value()
        clip_limit = self.spin_clip.value()
        linear_only = self.chk_linear_only.isChecked()

        u_comp = engine.compensate(
            u, iterative=iterative, iters=iters, clip_limit=clip_limit, linear_only=linear_only
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
        elif is_noise:
            dist_name = "TD+N"
            dist_uncomp = None
            dist_comp = None
        else:
            dist_name = "THD"
            dist_uncomp = calculate_thd_db(y_uncomp, f_test)
            dist_comp = calculate_thd_db(y_comp, f_test)

        sdr_uncomp = calculate_sdr_db(y_uncomp, y_linear)
        sdr_comp = calculate_sdr_db(y_comp, y_linear)

        if is_noise:
            results_txt = (
                f"=== {sig_type} Simulation Results ===\n"
                f"Uncompensated SDR: {sdr_uncomp:6.2f} dB\n"
                f"Compensated   SDR: {sdr_comp:6.2f} dB\n"
                f"SDR Improvement:   {sdr_comp - sdr_uncomp:+.2f} dB"
            )
        else:
            suppression = dist_uncomp - dist_comp
            results_txt = (
                f"=== {sig_type} Simulation Results ===\n"
                f"Uncompensated {dist_name}: {dist_uncomp:6.2f} dB | SDR: {sdr_uncomp:6.2f} dB\n"
                f"Compensated   {dist_name}: {dist_comp:6.2f} dB | SDR: {sdr_comp:6.2f} dB\n"
                f"{dist_name} Suppression:   {suppression:+.2f} dB\n"
                f"SDR Improvement:   {sdr_comp - sdr_uncomp:+.2f} dB"
            )
        self.lbl_sim_results.setText(results_txt)

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
            return

        input_path = self.lbl_in_file.text()
        output_path = self.lbl_out_file.text()
        iterative = self.chk_iterative.isChecked()
        iters = self.spin_iters.value()
        clip_limit = self.spin_clip.value()
        linear_only = self.chk_linear_only.isChecked()

        self.btn_process_off.setEnabled(False)
        self.btn_process_off.setText(tr("Processing..."))
        self.progress_off.setValue(0)

        self.worker = OfflineFFCompWorker(
            input_path,
            output_path,
            self.module.engine,
            iterative,
            iters,
            clip_limit,
            linear_only=linear_only,
        )
        self.worker.progress.connect(self.progress_off.setValue)
        self.worker.finished.connect(self.on_offline_finished)
        self.worker.start()

    def on_offline_finished(self, success, msg):
        self.btn_process_off.setEnabled(True)
        self.btn_process_off.setText(tr("Process & Save"))
        if success:
            QMessageBox.information(self, tr("Success"), msg)
        else:
            QMessageBox.critical(self, tr("Error"), msg)

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait()
        super().closeEvent(event)
