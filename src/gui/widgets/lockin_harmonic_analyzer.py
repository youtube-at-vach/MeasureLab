import logging
import threading
from collections import deque

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from scipy.signal import hilbert

from src.core.audio_engine import AudioEngine
from src.core.localization import tr
from src.measurement_modules.base import MeasurementModule

logger = logging.getLogger(__name__)
DISTORTION_DB_FLOOR = -300.0
DISTORTION_RATIO_EPS = 10 ** (DISTORTION_DB_FLOOR / 10.0)
MAX_ANALYSIS_HARMONIC = 200
MAX_COMPENSATION_HARMONIC = 50
NYQUIST_HARMONIC_MARGIN = 0.48


class LockInHarmonicAnalyzer(MeasurementModule):
    def __init__(self, audio_engine: AudioEngine):
        self.audio_engine = audio_engine
        self.is_running = False
        self.lock = threading.Lock()

        # Long buffer for ultra-low THD extraction
        self.buffer_size = 262144
        self.input_data = np.zeros((self.buffer_size, 2))
        self.input_buffer_pos = 0
        self.buffer_filled_samples = 0

        # Generator Settings
        self.gen_frequency = 1000.0
        self.gen_amplitude = 0.5
        self.output_channel = 2  # Stereo default
        self.output_enabled = True

        # Input Routing Defaults
        self.signal_channel = 0  # 0: Left
        self.ref_channel = 1  # 1: Right

        # Harmonic Analysis Specs
        self.max_harmonic = 10
        self.min_analysis_samples = 2048

        # Results
        self.measured_freq = 0.0
        self._allocate_harmonic_buffers()
        self.thd_value = 0.0
        self.thd_db = DISTORTION_DB_FLOOR
        self.thdn_value = 0.0
        self.thdn_db = DISTORTION_DB_FLOOR
        self.ref_level_dbfs = -140.0
        self.residual_rms = 0.0

        # DSP State
        self._phase_gen = 0.0
        self.callback_id = None
        self.history_len = min(8192, self.buffer_size // 10)
        self.residual_history = deque(maxlen=self.history_len)

        # Distortion Compensation State
        self.compensation_enabled = False
        self.comp_max_harmonic = 5
        self.compensation_coeffs = np.zeros(self.max_harmonic, dtype=complex)
        self.is_calibrating = False
        self.calibration_target_steps = 10
        self.calibration_current_step = 0
        self.calibration_alpha = 0.5
        self.frames_since_last_cal = 0

    def _allocate_harmonic_buffers(self):
        with self.lock:
            self.harmonics_amp = np.zeros(self.max_harmonic)
            self.harmonics_phase_deg = np.zeros(self.max_harmonic)
            old_coeffs = getattr(self, "compensation_coeffs", None)
            self.compensation_coeffs = np.zeros(self.max_harmonic, dtype=complex)
            if old_coeffs is not None:
                n = min(len(old_coeffs), self.max_harmonic)
                self.compensation_coeffs[:n] = old_coeffs[:n]

    def set_max_harmonic(self, val: int):
        if val == self.max_harmonic:
            return
        self.max_harmonic = val
        self._allocate_harmonic_buffers()

    @property
    def name(self) -> str:
        return "Lock-in Harmonic Analyzer"

    @property
    def description(self) -> str:
        return "Ultra-precision THD measurement using parallel reference-locked matrix projection."

    def get_widget(self):
        return LockInHarmonicWidget(self)

    def start_analysis(self):
        if self.is_running:
            return
        self.is_running = True

        self.input_data = np.zeros((self.buffer_size, 2))
        self.input_buffer_pos = 0
        self.buffer_filled_samples = 0
        self._phase_gen = 0.0

        sample_rate = self.audio_engine.sample_rate

        def callback(indata, outdata, frames, time, status):
            if not self.is_running:
                outdata.fill(0)
                return

            # --- Generator ---
            outdata.fill(0)
            if self.output_enabled:
                phase_step = 2 * np.pi * self.gen_frequency / sample_rate
                wt = self._phase_gen + np.arange(frames) * phase_step
                self._phase_gen = (self._phase_gen + frames * phase_step) % (2 * np.pi)
                sig = self.gen_amplitude * np.sin(wt)

                if self.compensation_enabled:
                    for n in range(2, min(self.max_harmonic + 1, self.comp_max_harmonic + 1)):
                        c = self.compensation_coeffs[n - 1]
                        if c.real != 0 or c.imag != 0:
                            sig += c.real * np.cos(n * wt) + c.imag * np.sin(n * wt)

                if self.output_channel == 2:  # Stereo
                    if outdata.shape[1] >= 2:
                        outdata[:, 0] = sig
                        outdata[:, 1] = sig
                elif outdata.shape[1] > self.output_channel:
                    outdata[:, self.output_channel] = sig

            # --- Input Capture ---
            if indata.shape[1] >= 2:
                new_data = indata[:, :2]
            else:
                new_data = np.column_stack((indata[:, 0], indata[:, 0]))

            n = len(new_data)
            with self.lock:
                p = self.input_buffer_pos

                if p + n <= self.buffer_size:
                    self.input_data[p : p + n] = new_data
                    self.input_buffer_pos = (p + n) % self.buffer_size
                else:
                    chunk1 = self.buffer_size - p
                    chunk2 = n - chunk1
                    self.input_data[p:] = new_data[:chunk1]
                    self.input_data[:chunk2] = new_data[chunk1:]
                    self.input_buffer_pos = chunk2

                self.buffer_filled_samples = min(self.buffer_size, self.buffer_filled_samples + n)

        self.callback_id = self.audio_engine.register_callback(callback)

    def stop_analysis(self):
        if self.is_running:
            self.is_running = False
            if self.callback_id is not None:
                self.audio_engine.unregister_callback(self.callback_id)
                self.callback_id = None

    def start_calibration(self):
        with self.lock:
            if not self.compensation_enabled:
                return
            self.is_calibrating = True
            self.calibration_current_step = 0
            self.frames_since_last_cal = 0

    def stop_calibration(self):
        with self.lock:
            self.is_calibrating = False

    def clear_compensation(self):
        with self.lock:
            self.compensation_coeffs.fill(0)
            self.is_calibrating = False

    def clear_buffer(self):
        with self.lock:
            self.input_data.fill(0)
            self.input_buffer_pos = 0
            self.buffer_filled_samples = 0
            self._reset_results()

    def _get_ordered_input_data(self):
        with self.lock:
            data = self.input_data.copy()
            pos = self.input_buffer_pos
        if pos == 0:
            return data
        return np.roll(data, -pos, axis=0)

    def _estimate_ref_phase_params(self, ref: np.ndarray, fs: float):
        n_samples = len(ref)
        if n_samples < 100:
            return None, None

        t = np.arange(n_samples) / fs
        ref_analytic = hilbert(ref)

        trim = int(n_samples * 0.05)
        if trim > 0 and (n_samples - 2 * trim) >= 100:
            ref_analytic = ref_analytic[trim:-trim]
            t = t[trim:-trim]

        if len(ref_analytic) < 100:
            return None, None

        ref_phase = np.unwrap(np.angle(ref_analytic))
        omega, theta_0 = np.polyfit(t, ref_phase, 1)
        # hilbert(sin(wt)) = sin(wt) - j*cos(wt) -> phase is wt - pi/2
        theta_0 += np.pi / 2
        return omega, theta_0

    def _extract_coherent_segment(self, sig: np.ndarray, ref: np.ndarray, fs: float):
        """Cut a recent integer-cycle segment using rising zero crossings."""
        if len(ref) < 4:
            return sig, ref, None

        rising_idx = np.flatnonzero((ref[:-1] <= 0.0) & (ref[1:] > 0.0))
        num_cycles = len(rising_idx) - 1
        if num_cycles < 1:
            return sig, ref, None

        # Sub-sample crossing timing via linear interpolation.
        def get_crossing(idx):
            y0 = ref[idx]
            y1 = ref[idx + 1]
            dy = y1 - y0
            frac = 0.0 if abs(dy) < 1e-18 else (-y0 / dy)
            return idx + np.clip(frac, 0.0, 1.0)

        start_cross = get_crossing(rising_idx[0])
        end_cross = get_crossing(rising_idx[-1])

        if end_cross <= start_cross:
            return sig, ref, None

        start_idx = max(0, int(np.floor(start_cross)))
        end_idx = min(len(ref), int(np.ceil(end_cross)) + 1)
        if (end_idx - start_idx) < self.min_analysis_samples:
            return sig, ref, None

        sig_seg = sig[start_idx:end_idx]
        ref_seg = ref[start_idx:end_idx]

        duration_sec = (end_cross - start_cross) / fs
        if duration_sec <= 0:
            return sig, ref, None

        omega = 2.0 * np.pi * (num_cycles / duration_sec)
        # Rising zero crossing defines sin phase = 0 at t = start_cross/fs.
        theta_0 = -omega * (start_cross / fs)
        return sig_seg, ref_seg, (omega, theta_0)

    def process(self):
        if not self.is_running:
            return

        with self.lock:
            filled = self.buffer_filled_samples

        if filled < self.buffer_size:
            return

        data = self._get_ordered_input_data()
        fs = self.audio_engine.sample_rate

        sig_full = data[:, self.signal_channel]
        ref_full = data[:, self.ref_channel]

        # 1. Analyze Reference
        ref_rms = np.sqrt(np.mean(ref_full**2))
        self.ref_level_dbfs = 20 * np.log10(ref_rms * np.sqrt(2) + 1e-12)

        if ref_rms < 0.0001:  # -80dB threshold
            self._reset_results()
            return

        omega_pre, _ = self._estimate_ref_phase_params(ref_full, fs)
        if omega_pre is None:
            self._reset_results()
            return

        f0_pre = omega_pre / (2 * np.pi)
        if f0_pre <= 0:
            self._reset_results()
            return

        # Always use coherent (bin-centered) mode
        sig, ref, phase_seed = self._extract_coherent_segment(sig_full, ref_full, fs)
        if phase_seed is not None:
            omega, theta_0 = phase_seed
        else:
            omega, theta_0 = self._estimate_ref_phase_params(ref, fs)
            if omega is None:
                self._reset_results()
                return

        N = len(sig)
        t = np.arange(N) / fs

        # Refine phase anchor at current omega.
        ref_i = (2.0 / N) * np.dot(ref, np.cos(omega * t))
        ref_q = (2.0 / N) * np.dot(ref, np.sin(omega * t))
        theta_0 = np.arctan2(ref_i, ref_q)

        f0 = omega / (2 * np.pi)
        self.measured_freq = f0
        if f0 <= 0:
            self._reset_results()
            return

        # 2. Parallel Lock-in (Matrix Projection)
        phase_ideal = omega * t + theta_0

        # Allocate Basis Matrix with DC term: [1, cos(1w), sin(1w), ...]
        num_bases = 1 + self.max_harmonic * 2
        B = np.zeros((N, num_bases))
        B[:, 0] = 1.0

        for n in range(1, self.max_harmonic + 1):
            idx = 1 + (n - 1) * 2
            B[:, idx] = np.cos(n * phase_ideal)
            B[:, idx + 1] = np.sin(n * phase_ideal)

        # Matrix projection over coherent cycles
        gram = np.dot(B.T, B)
        rhs = np.dot(B.T, sig)
        try:
            coeff = np.linalg.solve(gram, rhs)
        except np.linalg.LinAlgError:
            coeff = np.linalg.lstsq(B, sig, rcond=None)[0]

        # Harmonic coefficients only (excluding DC term)
        X = coeff[1:]

        # 3. Compute Harmonics
        reconstructed_sig = np.full(N, coeff[0])
        sum_sq_harmonics = 0.0

        for n in range(1, self.max_harmonic + 1):
            idx = (n - 1) * 2
            I_comp = X[idx]
            Q_comp = X[idx + 1]
            b_idx = 1 + idx
            amp = np.sqrt(I_comp**2 + Q_comp**2)
            # Generator outputs sin(wt). Ref is sin(wt).
            # B_I = cos(n*wt), B_Q = sin(n*wt)
            # Signal component A*sin(n*wt + phi) = A*sin(n*wt)cos(phi) + A*cos(n*wt)sin(phi)
            # Projection onto B_I (cos) gives A*sin(phi)
            # Projection onto B_Q (sin) gives A*cos(phi)
            # Therefore: I_comp = A*sin(phi), Q_comp = A*cos(phi)
            # So phi = arctan(sin/cos) = arctan(I/Q)
            # numpy.arctan2(y, x) -> y=I_comp, x=Q_comp
            phase = np.arctan2(I_comp, Q_comp)  # rad

            # Wrap phase to standard [-pi, pi]
            phase_deg = np.degrees(phase)
            phase_deg = (phase_deg + 180) % 360 - 180

            self.harmonics_amp[n - 1] = amp
            self.harmonics_phase_deg[n - 1] = phase_deg

            if n > 1:
                sum_sq_harmonics += (amp / np.sqrt(2)) ** 2

            # Reconstruct for THD+N by directly using the projections and basis functions
            # I_comp * cos(n * wt) + Q_comp * sin(n * wt)
            reconstructed_sig += I_comp * B[:, b_idx] + Q_comp * B[:, b_idx + 1]

        # 4. THD Calculations
        fund_rms_sq = (self.harmonics_amp[0] / np.sqrt(2)) ** 2

        if fund_rms_sq > 1e-15:
            # purely Harmonic Distortion (THD)
            thd_sq = sum_sq_harmonics / fund_rms_sq
            self.thd_value = np.sqrt(thd_sq) * 100
            self.thd_db = 10 * np.log10(thd_sq + DISTORTION_RATIO_EPS)

            # THD+N
            residual = sig - reconstructed_sig
            self.residual_rms = np.sqrt(np.mean(residual**2))

            # Store some residual history for plot
            step = max(1, len(residual) // self.history_len)
            decimated_res = residual[::step]
            self.residual_history.clear()
            self.residual_history.extend(decimated_res)

            noise_rms_sq = self.residual_rms**2
            num_sq = sum_sq_harmonics + noise_rms_sq
            thdn_sq = num_sq / fund_rms_sq

            self.thdn_value = np.sqrt(thdn_sq) * 100
            self.thdn_db = 10 * np.log10(thdn_sq + DISTORTION_RATIO_EPS)

            # 5. Auto-Calibration Logic
            if self.is_calibrating:
                self.frames_since_last_cal += 1
                if self.frames_since_last_cal >= 3:
                    self.frames_since_last_cal = 0
                    self.calibration_current_step += 1

                    fund_meas_amp = self.harmonics_amp[0]
                    if fund_meas_amp > 1e-12:
                        scale = self.gen_amplitude / fund_meas_amp
                        for n in range(2, min(self.max_harmonic + 1, self.comp_max_harmonic + 1)):
                            idx = (n - 1) * 2
                            I_meas = X[idx]
                            Q_meas = X[idx + 1]
                            delta_I = -self.calibration_alpha * I_meas * scale
                            delta_Q = -self.calibration_alpha * Q_meas * scale
                            self.compensation_coeffs[n - 1] += complex(delta_I, delta_Q)

                    if self.calibration_current_step >= self.calibration_target_steps:
                        self.is_calibrating = False

        else:
            self._reset_results()

    def _reset_results(self):
        self.measured_freq = 0.0
        self.harmonics_amp.fill(0)
        self.harmonics_phase_deg.fill(0)
        self.thd_value = 0.0
        self.thd_db = DISTORTION_DB_FLOOR
        self.thdn_value = 0.0
        self.thdn_db = DISTORTION_DB_FLOOR
        self.residual_rms = 0.0
        self.residual_history.clear()


class LockInHarmonicWidget(QWidget):
    def __init__(self, module: LockInHarmonicAnalyzer):
        super().__init__()
        self.module = module
        self._last_fs = 0
        self.ref_compensation_coeffs = np.zeros(self.module.max_harmonic, dtype=complex)
        self.init_ui()
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_ui)
        self.timer.setInterval(200)  # 5 Hz update

    def init_ui(self):
        layout = QHBoxLayout()

        # LEFT: Controls
        left_panel = QVBoxLayout()

        self.btn_toggle = QPushButton(tr("Start Analysis"))
        self.btn_toggle.setCheckable(True)
        self.btn_toggle.clicked.connect(self.on_toggle)
        self.btn_toggle.setStyleSheet("QPushButton:checked { background-color: #ccffcc; }")
        left_panel.addWidget(self.btn_toggle)

        left_tabs = QTabWidget()
        left_tabs.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)

        # Settings Tab
        settings_tab = QWidget()
        form = QFormLayout()

        # Output Channel
        self.combo_output_ch = QComboBox()
        self.combo_output_ch.addItems([tr("Left (Ch 1)"), tr("Right (Ch 2)"), tr("Stereo (Both)")])
        out_idx = 2 if self.module.output_channel == 2 else self.module.output_channel
        self.combo_output_ch.setCurrentIndex(out_idx)
        self.combo_output_ch.currentIndexChanged.connect(self.on_output_ch_changed)
        form.addRow(tr("Output Ch:"), self.combo_output_ch)

        # Buffer size
        self.combo_buffer = QComboBox()
        self._update_buffer_labels()
        self.combo_buffer.setCurrentIndex(2)  # Default 262144
        self.combo_buffer.currentIndexChanged.connect(self.on_buffer_changed)
        form.addRow(tr("Buffer (Integ. Time):"), self.combo_buffer)

        self.freq_spin = QDoubleSpinBox()
        self.freq_spin.setRange(20, 20000)
        self.freq_spin.setValue(self.module.gen_frequency)
        self.freq_spin.setSuffix(" Hz")
        self.freq_spin.valueChanged.connect(self.on_freq_changed)
        form.addRow(tr("Frequency:"), self.freq_spin)

        self.amp_spin = QDoubleSpinBox()
        self.amp_spin.setRange(-120, 20)
        self.amp_spin.setValue(-6.0)
        self.amp_spin.setSuffix(" dBFS")
        self.amp_spin.valueChanged.connect(self.on_amp_changed)
        form.addRow(tr("Amplitude:"), self.amp_spin)

        self.harmonic_spin = QSpinBox()
        harmonic_limit = self._calculate_harmonic_limit()
        initial_harmonic = min(self.module.max_harmonic, harmonic_limit)
        self.harmonic_spin.setRange(2, harmonic_limit)
        self.harmonic_spin.setValue(initial_harmonic)
        if self.module.max_harmonic != self.harmonic_spin.value():
            self.module.set_max_harmonic(self.harmonic_spin.value())
        self.harmonic_spin.valueChanged.connect(self.on_max_harmonic_changed)
        form.addRow(tr("Harmonics:"), self.harmonic_spin)

        settings_tab.setLayout(form)
        left_tabs.addTab(settings_tab, tr("Settings"))

        # Distortion Compensation Tab
        comp_tab = QWidget()
        c_form = QFormLayout()

        self.btn_comp_enable = QPushButton(tr("Enable Compensation"))
        self.btn_comp_enable.setCheckable(True)
        self.btn_comp_enable.setChecked(self.module.compensation_enabled)
        self.btn_comp_enable.clicked.connect(self.on_comp_enable)
        c_form.addRow(self.btn_comp_enable)

        self.comp_max_spin = QSpinBox()
        self.comp_max_spin.setRange(2, self._compensation_order_limit())
        self.comp_max_spin.setValue(min(self.module.comp_max_harmonic, self.comp_max_spin.maximum()))
        self.module.comp_max_harmonic = self.comp_max_spin.value()
        self.comp_max_spin.valueChanged.connect(self.on_comp_max_changed)
        c_form.addRow(tr("Comp. Max Harmonic:"), self.comp_max_spin)

        calib_layout = QHBoxLayout()
        self.btn_calib = QPushButton(tr("Auto-Calibrate"))
        self.btn_calib.clicked.connect(self.on_calibrate)
        self.btn_clear_comp = QPushButton(tr("Clear"))
        self.btn_clear_comp.clicked.connect(self.on_clear_comp)
        calib_layout.addWidget(self.btn_calib)
        calib_layout.addWidget(self.btn_clear_comp)
        c_form.addRow(calib_layout)

        self.lbl_calib_status = QLabel("")
        self.lbl_calib_status.setStyleSheet("color: #ffaa00; font-weight: bold;")
        c_form.addRow(self.lbl_calib_status)

        comp_tab.setLayout(c_form)
        left_tabs.addTab(comp_tab, tr("Compensation"))

        # Routing Tab
        routing_tab = QWidget()
        r_form = QFormLayout()
        self.sig_combo = QComboBox()
        self.sig_combo.addItems([tr("Left"), tr("Right")])
        self.sig_combo.setCurrentIndex(self.module.signal_channel)
        self.sig_combo.currentIndexChanged.connect(self.on_sig_ch_changed)
        r_form.addRow(tr("Signal Input:"), self.sig_combo)

        self.ref_combo = QComboBox()
        self.ref_combo.addItems([tr("Left"), tr("Right")])
        self.ref_combo.setCurrentIndex(self.module.ref_channel)
        self.ref_combo.currentIndexChanged.connect(self.on_ref_ch_changed)
        r_form.addRow(tr("Reference Input:"), self.ref_combo)
        routing_tab.setLayout(r_form)
        left_tabs.addTab(routing_tab, tr("Routing"))

        left_panel.addWidget(left_tabs)

        # Overview
        ov_group = QGroupBox(tr("Overview"))
        ov_layout = QVBoxLayout()
        self.lbl_thd = QLabel("--")
        self.lbl_thd.setStyleSheet("font-size: 24px; font-weight: bold; color: #ff5555;")
        self.lbl_thd.setMinimumWidth(320)
        self.lbl_thdn = QLabel("--")
        self.lbl_thdn.setStyleSheet("font-size: 18px; color: #ffaaaa;")
        self.lbl_thdn.setMinimumWidth(320)
        self.lbl_fund = QLabel(tr("Fundamental Amplitude: -- dBFS"))

        ov_layout.addWidget(QLabel(tr("THD:")))
        ov_layout.addWidget(self.lbl_thd)
        ov_layout.addWidget(QLabel(tr("THD+N:")))
        ov_layout.addWidget(self.lbl_thdn)
        ov_layout.addWidget(self.lbl_fund)
        ov_group.setLayout(ov_layout)
        ov_group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        left_panel.addWidget(ov_group)
        left_panel.addStretch()

        left_panel_widget = QWidget()
        left_panel_widget.setLayout(left_panel)
        left_panel_widget.setFixedWidth(340)  # Fixed width to prevent UI jumping
        layout.addWidget(left_panel_widget)

        # RIGHT: Plots and Table
        right_panel = QVBoxLayout()
        self.tabs = QTabWidget()

        # Harmonic Table
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels([tr("Harmonic"), tr("Amp (dBFS)"), tr("Level (dBc)"), tr("Phase (deg)")])
        self.table.setRowCount(self.module.max_harmonic)

        # Set fixed widths for stability and readability
        self.table.setColumnWidth(0, 80)
        self.table.setColumnWidth(1, 100)
        self.table.setColumnWidth(2, 100)
        self.table.setColumnWidth(3, 110)  # Widened phase column

        for i in range(self.module.max_harmonic):
            self.table.setItem(i, 0, QTableWidgetItem(tr("{}th").format(i + 1) if i > 0 else tr("Fund.")))
        # Removed resizeColumnsToContents() to prevent jumping
        self.tabs.addTab(self.table, tr("Harmonics Table"))

        # Bar Plot
        self.plot_bar = pg.PlotWidget(title=tr("Harmonics Spectrum"))
        self.plot_bar.setLabel("bottom", tr("Harmonic Order"))
        self.plot_bar.setLabel("left", tr("Amplitude"), units="dBFS")
        self.plot_bar.showGrid(y=True)
        self.plot_bar.setYRange(-200, 0)
        x_indices = np.arange(1, self.module.max_harmonic + 1)
        self.bar_items = pg.BarGraphItem(x=x_indices, y0=-200, height=np.zeros(len(x_indices)), width=0.6, brush="b")
        self.plot_bar.addItem(self.bar_items)
        self.tabs.addTab(self.plot_bar, tr("Harmonics Plot"))

        # Residual Time
        self.plot_res = pg.PlotWidget(title=tr("Residual Waveform"))
        self.curve_res = self.plot_res.plot(pen="y")
        self.tabs.addTab(self.plot_res, tr("Residual"))

        # Compensation Data
        comp_data_tab = QWidget()
        comp_data_layout = QVBoxLayout(comp_data_tab)

        comp_ctrl_layout = QHBoxLayout()
        self.btn_save_comp_ref = QPushButton(tr("Save as Reference"))
        self.btn_clear_comp_ref = QPushButton(tr("Clear Reference"))
        self.btn_export_comp = QPushButton(tr("Export..."))
        self.chk_show_comp_diff = QCheckBox(tr("Show Difference"))

        self.btn_save_comp_ref.clicked.connect(self.on_save_comp_ref)
        self.btn_clear_comp_ref.clicked.connect(self.on_clear_comp_ref)
        self.btn_export_comp.clicked.connect(self.on_export_comp)
        self.chk_show_comp_diff.toggled.connect(self.on_comp_diff_toggled)

        comp_ctrl_layout.addWidget(self.btn_save_comp_ref)
        comp_ctrl_layout.addWidget(self.btn_clear_comp_ref)
        comp_ctrl_layout.addWidget(self.btn_export_comp)
        comp_ctrl_layout.addWidget(self.chk_show_comp_diff)
        comp_ctrl_layout.addStretch()

        comp_data_layout.addLayout(comp_ctrl_layout)

        self.comp_table = QTableWidget()
        self.comp_table.setColumnCount(5)
        self.comp_table.setHorizontalHeaderLabels(
            [tr("Harmonic"), tr("Amp (dBFS)"), tr("Phase (deg)"), tr("ΔAmp (dB)"), tr("ΔPhase (deg)")]
        )

        self._resize_compensation_table()

        self.comp_table.setColumnHidden(3, True)
        self.comp_table.setColumnHidden(4, True)

        comp_data_layout.addWidget(self.comp_table)
        self.tabs.addTab(comp_data_tab, tr("Compensation Data"))

        right_panel.addWidget(self.tabs)
        layout.addLayout(right_panel, 2)

        self.setLayout(layout)

    def on_toggle(self, checked):
        if checked:
            self.module.start_analysis()
            self.timer.start()
            self.btn_toggle.setText(tr("Stop Analysis"))
        else:
            self.module.stop_analysis()
            self.timer.stop()
            self.btn_toggle.setText(tr("Start Analysis"))

    def on_comp_enable(self, checked):
        self.module.compensation_enabled = checked
        if not checked:
            self.module.stop_calibration()

    def on_comp_max_changed(self, val):
        self.module.comp_max_harmonic = val

    def on_calibrate(self):
        if not self.module.compensation_enabled:
            self.btn_comp_enable.setChecked(True)
            self.module.compensation_enabled = True
        self.module.start_calibration()

    def on_clear_comp(self):
        self.module.clear_compensation()

    def on_save_comp_ref(self):
        self.ref_compensation_coeffs = np.copy(self.module.compensation_coeffs)

    def on_clear_comp_ref(self):
        self.ref_compensation_coeffs.fill(0)

    def on_comp_diff_toggled(self, checked):
        self.comp_table.setColumnHidden(3, not checked)
        self.comp_table.setColumnHidden(4, not checked)

    def on_export_comp(self, filename=None):
        from PyQt6.QtWidgets import QFileDialog, QMessageBox
        import json

        # Disable the UI timer and button to prevent reentrancy and multiple dialogs on Linux
        was_running = self.module.is_running
        if was_running:
            self.timer.stop()
        self.btn_export_comp.setEnabled(False)

        try:
            if not filename:
                filename, _ = QFileDialog.getSaveFileName(
                    self, tr("Export Compensation Data"), "", "JSON Files (*.json)"
                )
            if not filename:
                return

            coeffs_list = []
            for i in range(1, len(self.module.compensation_coeffs)):
                c = self.module.compensation_coeffs[i]
                amp = np.abs(c)
                phase = np.arctan2(c.real, c.imag)
                phase_deg = np.degrees(phase)
                phase_deg = (phase_deg + 180) % 360 - 180
                coeffs_list.append(
                    {
                        "harmonic": i + 1,
                        "real": float(c.real),
                        "imag": float(c.imag),
                        "amp_linear": float(amp),
                        "phase_deg": float(phase_deg),
                    }
                )

            data = {
                "format": "MeasureLab_Harmonic_Compensation",
                "version": "1.1",
                "fundamental_frequency": float(self.module.gen_frequency),
                "fundamental_amplitude": float(self.module.gen_amplitude),
                "max_harmonic": int(self.module.max_harmonic),
                "compensation_coeffs": coeffs_list,
            }

            with open(filename, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            logger.info(f"Successfully exported compensation data to {filename}")
        except Exception as e:
            logger.error(f"Failed to export compensation data: {e}")
            QMessageBox.critical(self, tr("Error"), tr("Failed to export compensation data: {0}").format(str(e)))
        finally:
            # Restore state
            self.btn_export_comp.setEnabled(True)
            if was_running and self.module.is_running:
                self.timer.start()

    def _get_comp_amp_phase(self, c: complex):
        amp = np.abs(c)
        phase = np.arctan2(c.real, c.imag)
        phase_deg = np.degrees(phase)
        phase_deg = (phase_deg + 180) % 360 - 180
        return amp, phase_deg

    def on_buffer_changed(self, idx):
        sizes = [65536, 131072, 262144, 524288]
        if 0 <= idx < len(sizes):
            self.module.buffer_size = sizes[idx]
            if self.module.is_running:
                self.module.stop_analysis()
                self.module.start_analysis()

    def on_max_harmonic_changed(self, val):
        self.module.set_max_harmonic(val)

        if len(self.ref_compensation_coeffs) < val:
            new_ref = np.zeros(val, dtype=complex)
            n = len(self.ref_compensation_coeffs)
            new_ref[:n] = self.ref_compensation_coeffs
            self.ref_compensation_coeffs = new_ref

        self._resize_harmonic_table(val)
        self._update_compensation_order_limit()
        self._resize_compensation_table()

        # Re-create plot items
        self.plot_bar.removeItem(self.bar_items)
        x_indices = np.arange(1, val + 1)
        self.bar_items = pg.BarGraphItem(x=x_indices, y0=-200, height=np.zeros(val), width=0.6, brush="b")
        self.plot_bar.addItem(self.bar_items)
        self.module.clear_buffer()

    def on_amp_changed(self, val):
        self.module.gen_amplitude = 10 ** (val / 20)
        self.module.clear_buffer()

    def on_freq_changed(self, val):
        self.module.gen_frequency = val
        self._update_harmonic_limit()
        self.module.clear_buffer()

    def on_output_ch_changed(self, val):
        self.module.output_channel = val
        self.module.clear_buffer()

    def on_sig_ch_changed(self, val):
        self.module.signal_channel = val
        self.module.clear_buffer()

    def on_ref_ch_changed(self, val):
        self.module.ref_channel = val
        self.module.clear_buffer()

    def _calculate_harmonic_limit(self):
        """Return the maximum measurable harmonic order for the current frequency."""
        fs = self.module.audio_engine.sample_rate
        f0 = self.module.gen_frequency
        if f0 > 0:
            # Nyquist margin (e.g. 48% of FS) to avoid aliasing artifacts near Nyquist.
            limit = int(np.floor((fs * NYQUIST_HARMONIC_MARGIN) / f0))
            return max(2, min(MAX_ANALYSIS_HARMONIC, limit))
        return MAX_ANALYSIS_HARMONIC

    def _compensation_order_limit(self):
        return min(MAX_COMPENSATION_HARMONIC, self.module.max_harmonic)

    def _update_compensation_order_limit(self):
        if not hasattr(self, "comp_max_spin"):
            return

        limit = self._compensation_order_limit()
        if self.comp_max_spin.maximum() != limit:
            self.comp_max_spin.setMaximum(limit)
        if self.module.comp_max_harmonic != self.comp_max_spin.value():
            self.module.comp_max_harmonic = self.comp_max_spin.value()

    def _resize_harmonic_table(self, row_count):
        if not hasattr(self, "table"):
            return

        self.table.setRowCount(row_count)
        for i in range(row_count):
            if not self.table.item(i, 0):
                self.table.setItem(i, 0, QTableWidgetItem(tr("{}th").format(i + 1) if i > 0 else tr("Fund.")))

    def _resize_compensation_table(self):
        if not hasattr(self, "comp_table"):
            return

        row_count = max(0, self._compensation_order_limit() - 1)
        self.comp_table.setRowCount(row_count)
        for i in range(row_count):
            if not self.comp_table.item(i, 0):
                self.comp_table.setItem(i, 0, QTableWidgetItem(tr("{}th").format(i + 2)))

    def _update_harmonic_limit(self):
        """Update the maximum allowed harmonic order based on fundamental frequency and sample rate."""
        limit = self._calculate_harmonic_limit()
        if self.harmonic_spin.maximum() != limit:
            self.harmonic_spin.setMaximum(limit)
            # If current value exceeds new limit, it will be automatically clamped by QSpinBox,
            # and valueChanged will trigger module update.
        self._update_compensation_order_limit()
        self._resize_compensation_table()

    def _update_buffer_labels(self):
        """Update the buffer combo box items with dynamic integration time labels."""
        fs = self.module.audio_engine.sample_rate
        if fs == self._last_fs:
            return

        self._last_fs = fs
        sizes = [65536, 131072, 262144, 524288]
        current_idx = self.combo_buffer.currentIndex()
        if current_idx < 0:
            current_idx = 2  # Default to 262144

        self.combo_buffer.blockSignals(True)
        self.combo_buffer.clear()
        for s in sizes:
            time_sec = s / fs
            self.combo_buffer.addItem(tr("{:,} ({:.1f}s@{}k)").format(s, time_sec, fs // 1000))
        self.combo_buffer.setCurrentIndex(current_idx)
        self.combo_buffer.blockSignals(False)

    def _format_percent(self, value: float) -> str:
        if value >= 0.001:
            return tr("{:.5f} %").format(value)
        if value > 0:
            return tr("{:.3e} %").format(value)
        return tr("0 %")

    def update_ui(self):
        if not self.module.is_running:
            return

        with self.module.lock:
            filled = self.module.buffer_filled_samples
            size = self.module.buffer_size

        if filled < size:
            pct = int((filled / size) * 100)
            self.lbl_thd.setText(tr("Buffering... {}%").format(pct))
            self.lbl_thd.setStyleSheet("font-size: 24px; font-weight: bold; color: #ffaa00;")
            self.lbl_thdn.setText("--")
            self.lbl_fund.setText(tr("Fundamental Amplitude: -- dBFS"))
            return

        self.lbl_thd.setStyleSheet("font-size: 24px; font-weight: bold; color: #ff5555;")
        self._update_harmonic_limit()
        self._update_buffer_labels()
        self.module.process()

        thd_db = self.module.thd_db
        thd_pct = self.module.thd_value
        thdn_db = self.module.thdn_db
        thdn_pct = self.module.thdn_value

        self.lbl_thd.setText(tr("{} dB ({})").format(f"{thd_db:.3f}", self._format_percent(thd_pct)))
        self.lbl_thdn.setText(tr("{} dB ({})").format(f"{thdn_db:.3f}", self._format_percent(thdn_pct)))

        if self.module.is_calibrating:
            step = self.module.calibration_current_step
            total = self.module.calibration_target_steps
            self.lbl_calib_status.setText(tr("Calibrating... {}/{}").format(step, total))
            self.lbl_calib_status.setStyleSheet("color: #ffaa00; font-weight: bold;")
        else:
            if np.any(np.abs(self.module.compensation_coeffs) > 0) and self.module.compensation_enabled:
                self.lbl_calib_status.setText(tr("Compensation Active"))
                self.lbl_calib_status.setStyleSheet("color: #55ff55; font-weight: bold;")
            else:
                self.lbl_calib_status.setText("")

        fund_dbfs = (
            20 * np.log10((self.module.harmonics_amp[0] / np.sqrt(2)) + 1e-15) + 3
        )  # Adjusting RMS to peak for dBFS? Usually dBFS is peak. We calc peak.
        fund_peak = self.module.harmonics_amp[0]
        fund_dbfs = 20 * np.log10(fund_peak + 1e-15)
        self.lbl_fund.setText(tr("Fundamental: {} dBFS").format(f"{fund_dbfs:.2f}"))

        # Update Table and Bar Plot
        heights = np.zeros(self.module.max_harmonic)
        show_diff = self.chk_show_comp_diff.isChecked()

        self.table.setUpdatesEnabled(False)
        self.comp_table.setUpdatesEnabled(False)

        try:
            for i in range(self.module.max_harmonic):
                amp_peak = self.module.harmonics_amp[i]
                phase = self.module.harmonics_phase_deg[i]

                amp_dbfs = 20 * np.log10(amp_peak + 1e-15)
                dbc = amp_dbfs - fund_dbfs if i > 0 else 0.0

                heights[i] = max(0, amp_dbfs + 200)

                if item := self.table.item(i, 1):
                    item.setText(f"{amp_dbfs:.2f}")
                else:
                    self.table.setItem(i, 1, QTableWidgetItem(f"{amp_dbfs:.2f}"))

                if item := self.table.item(i, 2):
                    item.setText(f"{dbc:.2f}" if i > 0 else tr("--"))
                else:
                    self.table.setItem(i, 2, QTableWidgetItem(f"{dbc:.2f}" if i > 0 else tr("--")))

                if item := self.table.item(i, 3):
                    item.setText(f"{phase:.2f}")
                else:
                    self.table.setItem(i, 3, QTableWidgetItem(f"{phase:.2f}"))

                # Update Compensation Table inline to save loops
                if i > 0:
                    c = self.module.compensation_coeffs[i]
                    amp, phase_deg = self._get_comp_amp_phase(c)
                    amp_dbfs_comp = 20 * np.log10(amp + 1e-15)

                    if item := self.comp_table.item(i - 1, 1):
                        item.setText(f"{amp_dbfs_comp:.2f}")
                    else:
                        self.comp_table.setItem(i - 1, 1, QTableWidgetItem(f"{amp_dbfs_comp:.2f}"))

                    if item := self.comp_table.item(i - 1, 2):
                        item.setText(f"{phase_deg:.2f}")
                    else:
                        self.comp_table.setItem(i - 1, 2, QTableWidgetItem(f"{phase_deg:.2f}"))

                    if show_diff:
                        ref_c = self.ref_compensation_coeffs[i]
                        ref_amp, ref_phase_deg = self._get_comp_amp_phase(ref_c)
                        ref_amp_dbfs = 20 * np.log10(ref_amp + 1e-15)

                        diff_amp = amp_dbfs_comp - ref_amp_dbfs
                        diff_phase = phase_deg - ref_phase_deg
                        diff_phase = (diff_phase + 180) % 360 - 180

                        if item := self.comp_table.item(i - 1, 3):
                            item.setText(f"{diff_amp:+.2f}")
                        else:
                            self.comp_table.setItem(i - 1, 3, QTableWidgetItem(f"{diff_amp:+.2f}"))

                        if item := self.comp_table.item(i - 1, 4):
                            item.setText(f"{diff_phase:+.2f}")
                        else:
                            self.comp_table.setItem(i - 1, 4, QTableWidgetItem(f"{diff_phase:+.2f}"))
        finally:
            self.table.setUpdatesEnabled(True)
            self.comp_table.setUpdatesEnabled(True)

        self.bar_items.setOpts(height=heights)

        res_hist = np.array(self.module.residual_history)
        if len(res_hist) > 0:
            self.curve_res.setData(res_hist)
