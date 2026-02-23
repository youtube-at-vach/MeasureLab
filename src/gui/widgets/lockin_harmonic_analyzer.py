import logging
from collections import deque

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
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


class LockInHarmonicAnalyzer(MeasurementModule):
    def __init__(self, audio_engine: AudioEngine):
        self.audio_engine = audio_engine
        self.is_running = False

        # Long buffer for ultra-low THD extraction
        self.buffer_size = 262144
        self.input_data = np.zeros((self.buffer_size, 2))
        self.input_buffer_pos = 0

        # Generator Settings
        self.gen_frequency = 1000.0
        self.gen_amplitude = 0.5
        self.output_channel = 2  # Stereo default
        self.output_enabled = True

        # Input Routing Defaults
        self.signal_channel = 0  # 0: Left
        self.ref_channel = 1     # 1: Right

        # Harmonic Analysis Specs
        self.max_harmonic = 10

        # Results
        self.measured_freq = 0.0
        self.harmonics_amp = np.zeros(self.max_harmonic)
        self.harmonics_phase_deg = np.zeros(self.max_harmonic)
        self.thd_value = 0.0
        self.thd_db = -140.0
        self.thdn_value = 0.0
        self.thdn_db = -140.0
        self.ref_level_dbfs = -140.0
        self.residual_rms = 0.0

        # DSP State
        self._phase_gen = 0.0
        self.callback_id = None
        self.history_len = min(8192, self.buffer_size // 10)
        self.residual_history = deque(maxlen=self.history_len)

    @property
    def name(self) -> str:
        return "Lock-in THD Analyzer (Parallel)"

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
        self._phase_gen = 0.0

        sample_rate = self.audio_engine.sample_rate

        def callback(indata, outdata, frames, time, status):
            if not self.is_running:
                outdata.fill(0)
                return

            # --- Generator ---
            outdata.fill(0)
            if self.output_enabled:
                t = (np.arange(frames) + self._phase_gen) / sample_rate
                self._phase_gen += frames
                sig = self.gen_amplitude * np.sin(2 * np.pi * self.gen_frequency * t)

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

        self.callback_id = self.audio_engine.register_callback(callback)

    def stop_analysis(self):
        if self.is_running:
            self.is_running = False
            if self.callback_id is not None:
                self.audio_engine.unregister_callback(self.callback_id)
                self.callback_id = None

    def _get_ordered_input_data(self):
        data = self.input_data.copy()
        pos = self.input_buffer_pos
        if pos == 0:
            return data
        return np.roll(data, -pos, axis=0)

    def process(self):
        if not self.is_running:
            return

        data = self._get_ordered_input_data()
        fs = self.audio_engine.sample_rate

        sig = data[:, self.signal_channel]
        ref = data[:, self.ref_channel]

        N = len(sig)
        t = np.arange(N) / fs

        # 1. Analyze Reference
        ref_rms = np.sqrt(np.mean(ref**2))
        self.ref_level_dbfs = 20 * np.log10(ref_rms * np.sqrt(2) + 1e-12)

        if ref_rms < 0.0001:  # -80dB threshold
            self._reset_results()
            return

        # Estimate Ref Frequency by linear fit of unwrapped phase
        ref_analytic = hilbert(ref)
        
        # Trim edges
        trim = int(N * 0.05)
        if trim > 0:
            ref_analytic_trimmed = ref_analytic[trim:-trim]
            t_trimmed = t[trim:-trim]
        else:
            ref_analytic_trimmed = ref_analytic
            t_trimmed = t

        if len(ref_analytic_trimmed) < 100:
            self._reset_results()
            return

        ref_phase = np.unwrap(np.angle(ref_analytic_trimmed))
        omega, theta_0 = np.polyfit(t_trimmed, ref_phase, 1)
        
        # hilbert(sin(wt)) = sin(wt) - j*cos(wt), which has angle wt - pi/2.
        # We want the phase to represent the original sine wave, so add pi/2.
        theta_0 += np.pi / 2

        f0 = omega / (2 * np.pi)
        self.measured_freq = f0

        if f0 <= 0:
            self._reset_results()
            return

        # Ensure we only process integer numbers of cycles to avoid leakage
        samples_per_cycle = fs / f0
        n_cycles = int(N / samples_per_cycle)
        if n_cycles < 1:
            n_samples = N
        else:
            n_samples = int(n_cycles * samples_per_cycle)

        # Slice data for precise integer cycles without windowing for pure lock-in
        # (Alternatively use window W, but for pure frequencies integer cycles is best)
        sig_slice = sig[:n_samples]
        t_slice = t[:n_samples]

        # 2. Parallel Lock-in (Matrix Projection)
        # B = [cos(w_0 t + t_0), sin(...), cos(2w_0 t + 2t_0), sin(2w...)]
        # We can directly use the unwrapped phase if it's clean, or the fitted phase.
        # Fitted phase is much cleaner against ADC thermal noise.
        phase_ideal = omega * t_slice + theta_0
        
        # Allocate Basis Matrix (N_samples x 20)
        num_bases = self.max_harmonic * 2
        B = np.zeros((n_samples, num_bases))

        for n in range(1, self.max_harmonic + 1):
            idx = (n - 1) * 2
            B[:, idx] = np.cos(n * phase_ideal)
            B[:, idx + 1] = -np.sin(n * phase_ideal) # Negative sin to align with standard lock-in math
            # Notice standard IQ: I = sig * cos, Q = sig * -sin (if using exp(-jwt))
            # or Q = sig * sin. Let's stick to standard projection:
            B[:, idx + 1] = np.sin(n * phase_ideal)

        # Projection: X = (2/N) * B^T * S
        # Using BLAS np.dot
        X = (2.0 / n_samples) * np.dot(B.T, sig_slice)

        # 3. Compute Harmonics
        reconstructed_sig = np.zeros(n_samples)
        sum_sq_harmonics = 0.0

        for n in range(1, self.max_harmonic + 1):
            idx = (n - 1) * 2
            I_comp = X[idx]
            Q_comp = X[idx + 1]
            amp = np.sqrt(I_comp**2 + Q_comp**2)
            # Generator outputs sin(wt). Ref is sin(wt).
            # B_I = cos(n*wt), B_Q = sin(n*wt)
            # Signal component A*sin(n*wt + phi) = A*sin(n*wt)cos(phi) + A*cos(n*wt)sin(phi)
            # Projection onto B_I (cos) gives A*sin(phi)
            # Projection onto B_Q (sin) gives A*cos(phi)
            # Therefore: I_comp = A*sin(phi), Q_comp = A*cos(phi)
            # So phi = arctan(sin/cos) = arctan(I/Q)
            # numpy.arctan2(y, x) -> y=I_comp, x=Q_comp
            phase = np.arctan2(I_comp, Q_comp) # rad
            
            # Wrap phase to standard [-pi, pi]
            phase_deg = np.degrees(phase)
            phase_deg = (phase_deg + 180) % 360 - 180

            self.harmonics_amp[n - 1] = amp
            self.harmonics_phase_deg[n - 1] = phase_deg

            if n > 1:
                sum_sq_harmonics += (amp / np.sqrt(2))**2
                
            # Reconstruct for THD+N
            reconstructed_sig += amp * np.cos(n * phase_ideal - phase) 
            # Check phase formulation: A*cos(wt)*cos(phi) + A*sin(wt)*sin(phi) = A*cos(wt-phi)
            # if I = A*cos(phi), Q = A*sin(phi)
            # then I*cos(wt) + Q*sin(wt) = A*cos(phi)*cos(wt) + A*sin(phi)*sin(wt) = A*cos(wt - phi)

        # 4. THD Calculations
        fund_rms_sq = (self.harmonics_amp[0] / np.sqrt(2))**2

        if fund_rms_sq > 1e-15:
            # purely Harmonic Distortion (THD)
            thd_sq = sum_sq_harmonics / fund_rms_sq
            self.thd_value = np.sqrt(thd_sq) * 100
            self.thd_db = 10 * np.log10(thd_sq + 1e-15)

            # THD+N
            residual = sig_slice - reconstructed_sig
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
            self.thdn_db = 10 * np.log10(thdn_sq + 1e-15)
        else:
            self._reset_results()

    def _reset_results(self):
        self.measured_freq = 0.0
        self.harmonics_amp.fill(0)
        self.harmonics_phase_deg.fill(0)
        self.thd_value = 0.0
        self.thd_db = -140.0
        self.thdn_value = 0.0
        self.thdn_db = -140.0
        self.residual_rms = 0.0
        self.residual_history.clear()

class LockInHarmonicWidget(QWidget):
    def __init__(self, module: LockInHarmonicAnalyzer):
        super().__init__()
        self.module = module
        self.init_ui()
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_ui)
        self.timer.setInterval(200)  # 5 Hz update

    def init_ui(self):
        layout = QHBoxLayout()

        # LEFT: Controls
        left_panel = QVBoxLayout()
        settings_group = QGroupBox(tr("Settings"))
        form = QFormLayout()

        self.btn_toggle = QPushButton(tr("Start Analysis"))
        self.btn_toggle.setCheckable(True)
        self.btn_toggle.clicked.connect(self.on_toggle)
        self.btn_toggle.setStyleSheet("QPushButton:checked { background-color: #ccffcc; }")
        form.addRow(self.btn_toggle)

        # Output Channel
        self.combo_output_ch = QComboBox()
        self.combo_output_ch.addItems([tr("Left (Ch 1)"), tr("Right (Ch 2)"), tr("Stereo (Both)")])
        out_idx = 2 if self.module.output_channel == 2 else self.module.output_channel
        self.combo_output_ch.setCurrentIndex(out_idx)
        self.combo_output_ch.currentIndexChanged.connect(lambda v: setattr(self.module, "output_channel", v))
        form.addRow(tr("Output Ch:"), self.combo_output_ch)

        # Buffer size
        self.combo_buffer = QComboBox()
        self.combo_buffer.addItems(["65,536 (1.3s@48k)", "131,072 (2.7s@48k)", "262,144 (5.4s@48k)", "524,288 (10.9s@48k)"])
        self.combo_buffer.setCurrentIndex(2) # Default 262144
        self.combo_buffer.currentIndexChanged.connect(self.on_buffer_changed)
        form.addRow(tr("Buffer (Integ. Time):"), self.combo_buffer)

        self.freq_spin = QDoubleSpinBox()
        self.freq_spin.setRange(20, 20000)
        self.freq_spin.setValue(self.module.gen_frequency)
        self.freq_spin.setSuffix(" Hz")
        self.freq_spin.valueChanged.connect(lambda v: setattr(self.module, "gen_frequency", v))
        form.addRow(tr("Frequency:"), self.freq_spin)

        self.amp_spin = QDoubleSpinBox()
        self.amp_spin.setRange(-120, 20)
        self.amp_spin.setValue(-6.0)
        self.amp_spin.setSuffix(" dBFS")
        self.amp_spin.valueChanged.connect(self.on_amp_changed)
        form.addRow(tr("Amplitude:"), self.amp_spin)

        settings_group.setLayout(form)
        left_panel.addWidget(settings_group)

        # Routing
        routing_group = QGroupBox(tr("Input Routing"))
        r_form = QFormLayout()
        self.sig_combo = QComboBox()
        self.sig_combo.addItems([tr("Left"), tr("Right")])
        self.sig_combo.setCurrentIndex(self.module.signal_channel)
        self.sig_combo.currentIndexChanged.connect(lambda v: setattr(self.module, "signal_channel", v))
        r_form.addRow(tr("Signal Input:"), self.sig_combo)

        self.ref_combo = QComboBox()
        self.ref_combo.addItems([tr("Left"), tr("Right")])
        self.ref_combo.setCurrentIndex(self.module.ref_channel)
        self.ref_combo.currentIndexChanged.connect(lambda v: setattr(self.module, "ref_channel", v))
        r_form.addRow(tr("Reference Input:"), self.ref_combo)
        routing_group.setLayout(r_form)
        left_panel.addWidget(routing_group)

        # Overview
        ov_group = QGroupBox(tr("Overview"))
        ov_layout = QVBoxLayout()
        self.lbl_thd = QLabel("--")
        self.lbl_thd.setStyleSheet("font-size: 24px; font-weight: bold; color: #ff5555;")
        self.lbl_thdn = QLabel("--")
        self.lbl_thdn.setStyleSheet("font-size: 18px; color: #ffaaaa;")
        self.lbl_fund = QLabel(tr("Fundamental Amplitude: -- dBFS"))
        
        ov_layout.addWidget(QLabel(tr("THD:")))
        ov_layout.addWidget(self.lbl_thd)
        ov_layout.addWidget(QLabel(tr("THD+N:")))
        ov_layout.addWidget(self.lbl_thdn)
        ov_layout.addWidget(self.lbl_fund)
        ov_group.setLayout(ov_layout)
        left_panel.addWidget(ov_group)

        left_panel.addStretch()
        layout.addLayout(left_panel, 1)

        # RIGHT: Plots and Table
        right_panel = QVBoxLayout()
        self.tabs = QTabWidget()

        # Harmonic Table
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Harmonic", "Amp (dBFS)", "Level (dBc)", "Phase (deg)"])
        self.table.setRowCount(self.module.max_harmonic)
        for i in range(self.module.max_harmonic):
            self.table.setItem(i, 0, QTableWidgetItem(f"{i+1}th" if i > 0 else "Fund."))
        self.table.resizeColumnsToContents()
        self.tabs.addTab(self.table, tr("Harmonics Table"))

        # Bar Plot
        self.plot_bar = pg.PlotWidget(title="Harmonics Spectrum")
        self.plot_bar.setLabel("bottom", "Harmonic Order")
        self.plot_bar.setLabel("left", "Amplitude", units="dBFS")
        self.plot_bar.showGrid(y=True)
        self.plot_bar.setYRange(-160, 0)
        self.bar_items = pg.BarGraphItem(x=np.arange(1, 11), height=np.zeros(10), width=0.6, brush='b')
        self.plot_bar.addItem(self.bar_items)
        self.tabs.addTab(self.plot_bar, tr("Harmonics Plot"))

        # Residual Time
        self.plot_res = pg.PlotWidget(title="Residual Waveform")
        self.curve_res = self.plot_res.plot(pen="y")
        self.tabs.addTab(self.plot_res, tr("Residual"))

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

    def on_buffer_changed(self, idx):
        sizes = [65536, 131072, 262144, 524288]
        if 0 <= idx < len(sizes):
            self.module.buffer_size = sizes[idx]
            # Restart if running
            if self.module.is_running:
                self.module.stop_analysis()
                self.module.start_analysis()

    def on_amp_changed(self, val):
        self.module.gen_amplitude = 10 ** (val / 20)

    def update_ui(self):
        if not self.module.is_running:
            return
            
        self.module.process()

        thd_db = self.module.thd_db
        thd_pct = self.module.thd_value
        thdn_db = self.module.thdn_db
        thdn_pct = self.module.thdn_value

        self.lbl_thd.setText(f"{thd_db:.3f} dB ({thd_pct:.5f} %)")
        self.lbl_thdn.setText(f"{thdn_db:.3f} dB ({thdn_pct:.5f} %)")

        fund_dbfs = 20 * np.log10((self.module.harmonics_amp[0]/np.sqrt(2)) + 1e-15) + 3 # Adjusting RMS to peak for dBFS? Usually dBFS is peak. We calc peak.
        fund_peak = self.module.harmonics_amp[0]
        fund_dbfs = 20 * np.log10(fund_peak + 1e-15)
        self.lbl_fund.setText(f"Fundamental: {fund_dbfs:.2f} dBFS")

        # Update Table and Bar Plot
        heights = np.zeros(self.module.max_harmonic)
        for i in range(self.module.max_harmonic):
            amp_peak = self.module.harmonics_amp[i]
            phase = self.module.harmonics_phase_deg[i]
            
            amp_dbfs = 20 * np.log10(amp_peak + 1e-15)
            dbc = amp_dbfs - fund_dbfs if i > 0 else 0.0

            heights[i] = max(-160, amp_dbfs)

            self.table.setItem(i, 1, QTableWidgetItem(f"{amp_dbfs:.2f}"))
            self.table.setItem(i, 2, QTableWidgetItem(f"{dbc:.2f}" if i > 0 else "--"))
            self.table.setItem(i, 3, QTableWidgetItem(f"{phase:.2f}"))

        self.bar_items.setOpts(height=heights)

        res_hist = np.array(self.module.residual_history)
        if len(res_hist) > 0:
            self.curve_res.setData(res_hist)
