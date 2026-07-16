import logging
import queue
import threading
from collections import deque
import numpy as np
import pyqtgraph as pg
import scipy.signal
from scipy.signal import savgol_filter
from PyQt6.QtCore import QTimer, QThread, pyqtSignal, QSize, Qt
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
    QMessageBox,
)

from src.core.audio_engine import AudioEngine
from src.core.localization import tr
from src.measurement_modules.base import MeasurementModule
from src.core.realtime_sss_core import RealtimeSSSEngine, measure_system_latency
from src.core.hammerstein_model import save_hammerstein_model, set_active_model

logger = logging.getLogger(__name__)


class LatencyCalibThread(QThread):
    finished_sig = pyqtSignal(float)
    error_sig = pyqtSignal(str)

    def __init__(self, audio_engine, start_freq, end_freq, out_ch, in_ch):
        super().__init__()
        self.audio_engine = audio_engine
        self.start_freq = start_freq
        self.end_freq = end_freq
        self.out_ch = out_ch
        self.in_ch = in_ch

    def run(self):
        try:
            latency = measure_system_latency(
                self.audio_engine,
                self.start_freq,
                self.end_freq,
                duration=0.25,
                in_ch=self.in_ch,
                out_ch=self.out_ch,
            )
            self.finished_sig.emit(latency)
        except Exception as e:
            logger.error(f"Latency calibration failed: {e}", exc_info=True)
            self.error_sig.emit(str(e))


class SSSCalculationThread(QThread):
    block_calculated = pyqtSignal(int, int, float, list, bool)  # block_idx, sweep_idx, f_mid, results, is_valid
    sweep_finished = pyqtSignal(int)  # sweep_idx

    def __init__(self, engine, input_queue, prevent_underrun=False):
        super().__init__()
        self.engine = engine
        self.input_queue = input_queue
        self.prevent_underrun = prevent_underrun
        self.is_running = True
        self.pending_blocks = []

    def run(self):
        while self.is_running:
            try:
                # Use a timeout to periodically check if the thread should be stopped
                item = self.input_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            block_idx, sweep_idx, sig_in, ref_in, max_blocks = item

            if self.prevent_underrun:
                self.pending_blocks.append(item)
                if block_idx == max_blocks - 1:
                    for p_item in self.pending_blocks:
                        if not self.is_running:
                            break
                        p_block_idx, p_sweep_idx, p_sig_in, p_ref_in, p_max_blocks = p_item
                        try:
                            f_mid, results = self.engine.process_input_block(
                                p_sig_in, p_block_idx, ref_in_block=p_ref_in
                            )
                            is_valid = self.engine.last_block_was_valid
                            self.block_calculated.emit(p_block_idx, p_sweep_idx, f_mid, results, is_valid)
                        except Exception as e:
                            logger.error(f"Error in background computation: {e}", exc_info=True)
                        if p_block_idx == p_max_blocks - 1:
                            self.sweep_finished.emit(p_sweep_idx)
                    self.pending_blocks.clear()
            else:
                # Perform the computationally heavy Least-Squares fit in the background
                try:
                    f_mid, results = self.engine.process_input_block(sig_in, block_idx, ref_in_block=ref_in)
                    is_valid = self.engine.last_block_was_valid
                    self.block_calculated.emit(block_idx, sweep_idx, f_mid, results, is_valid)
                except Exception as e:
                    logger.error(f"Error in background computation: {e}", exc_info=True)

                if block_idx == max_blocks - 1:
                    self.sweep_finished.emit(sweep_idx)

            self.input_queue.task_done()

    def stop(self):
        self.is_running = False


class LockInModeler(MeasurementModule):
    def __init__(self, audio_engine: AudioEngine):
        self.audio_engine = audio_engine
        self.is_running = False
        self.lock = threading.RLock()

        # Default SSS parameters
        self.start_freq = 20.0
        self.end_freq = 20000.0
        self.sweep_duration = 20.0
        self.output_amplitude = 0.5
        self.max_harmonic = 5
        self.averaging_count = 1
        self.current_sweep_idx = 0
        self.analysis_cycles = 64.0
        self.num_meas_points = 500
        self.min_analysis_window = 0.1

        # Latency state
        self.latency_samples = 0.0

        # Channel routing
        self.output_channel = 2  # Stereo default (copies output to both L and R)
        self.signal_channel = 0  # 0: Left Input
        self.ref_channel = 1  # 1: Right Input
        self.input_mode = "XFER"  # "Single" or "XFER"
        self.ref_phase_only = True

        # Engine & DSP State
        self.engine = None
        self.callback_id = None
        self.current_block_idx = 0
        self.max_blocks = 0

        # Dynamic measurement data queues
        self.measurement_queue = deque()
        self.prevent_buffer_underrun = True
        self.input_queue = None
        self.state = "IDLE"  # "IDLE", "PLAYING", "WAITING", "FINISHED"

        self.widget = None

    @property
    def name(self) -> str:
        return "Lock-in Modeler"

    @property
    def description(self) -> str:
        return tr("Real-time frequency response and distortion sweep using SSS and digital Lock-in.")

    def get_widget(self):
        self.widget = LockInModelerWidget(self)
        return self.widget

    def start_analysis(self):
        if self.is_running:
            return
        self.is_running = True

        self.current_block_idx = 0
        self.current_sweep_idx = 0
        self.measurement_queue.clear()

        # Initialize core engine
        self.engine = RealtimeSSSEngine(
            sample_rate=self.audio_engine.sample_rate,
            sweep_duration=self.sweep_duration,
            start_freq=self.start_freq,
            end_freq=self.end_freq,
            output_amplitude=self.output_amplitude,
            max_harmonic=self.max_harmonic,
            analysis_cycles=self.analysis_cycles,
            num_meas_points=self.num_meas_points,
            min_analysis_window=self.min_analysis_window,
            ref_phase_only=self.ref_phase_only,
        )
        self.engine.prepare_sweep()
        self.engine.set_latency(self.latency_samples)

        frames = self.audio_engine.block_size
        self.max_blocks = int(np.ceil((self.engine.sweep_samples + self.latency_samples) / frames))

        input_mode = getattr(self, "input_mode", "Single")
        sig_ch = self.signal_channel
        ref_ch = self.ref_channel

        self.input_queue = queue.Queue()
        self.state = "PLAYING"

        def callback(indata, outdata, frames, time, status):
            if not self.is_running:
                outdata.fill(0)
                return

            with self.lock:
                if self.state == "WAITING":
                    outdata.fill(0)
                    return

                if self.current_block_idx >= self.max_blocks:
                    self.state = "WAITING"
                    outdata.fill(0)
                    return

                # Extract target input channel
                sig_in = np.zeros((frames, 1))
                if indata.shape[1] > sig_ch:
                    sig_in[:, 0] = indata[:, sig_ch]
                elif indata.shape[1] > 0:
                    sig_in[:, 0] = indata[:, 0]

                # Extract reference input channel if in XFER mode
                ref_in = None
                if input_mode == "XFER":
                    ref_in = np.zeros((frames, 1))
                    if indata.shape[1] > ref_ch:
                        ref_in[:, 0] = indata[:, ref_ch]
                    elif indata.shape[1] > 0:
                        ref_in[:, 0] = indata[:, 0]

                # 1. Output Generation (Lightweight)
                self.engine.generate_output_block(outdata, self.current_block_idx)
                # 2. Add raw data to background processing queue
                self.input_queue.put((self.current_block_idx, self.current_sweep_idx, sig_in, ref_in, self.max_blocks))

                self.current_block_idx += 1

        self.callback_id = self.audio_engine.register_callback(callback)

    def stop_analysis(self):
        if self.is_running:
            self.is_running = False
            if self.callback_id is not None:
                self.audio_engine.unregister_callback(self.callback_id)
                self.callback_id = None
            if self.engine:
                self.engine.reset_filter_states()


class LockInModelerWidget(QWidget):
    def __init__(self, module: LockInModeler):
        super().__init__()
        self.module = module
        self.calib_thread = None

        # Data store for plotting
        self.plot_freqs = []
        self.current_analysis_freq = None
        self.plot_gains = [[] for _ in range(5)]
        self.plot_phases = [[] for _ in range(5)]

        # Hammerstein parameters
        self.is_hammerstein_mode = False
        self.num_amplitudes = 5
        self.amplitudes = []
        self.current_amp_idx = 0
        self.current_avg_idx = 0
        self.H_freqs = []
        self.kernels_time = []
        self.time_ms = []
        self.raw_responses = None
        self.raw_counts = None

        self.init_ui()

        # Theme manager
        self.app = QApplication.instance()
        if hasattr(self.app, "theme_manager"):
            self.app.theme_manager.theme_changed.connect(self.apply_theme)
            self.apply_theme(self.app.theme_manager.get_current_theme())

        # Update timer (60 Hz for fluid plotting response)
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_plots)
        self.timer.setInterval(16)

    def minimumSizeHint(self) -> QSize:
        return QSize(1000, 650)

    def init_ui(self):
        layout = QHBoxLayout()
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # LEFT PANEL: Controls (static layout without QScrollArea)
        left_panel = QWidget()
        left_panel.setFixedWidth(320)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)

        # Start / Stop Control Button
        self.btn_toggle = QPushButton(tr("Start Sweep"))
        self.btn_toggle.setCheckable(True)
        self.btn_toggle.clicked.connect(self.on_toggle_sweep)
        self.btn_toggle.setEnabled(self.module.latency_samples > 0.0)
        left_layout.addWidget(self.btn_toggle)

        # Export Button (visible/enabled after Hammerstein calibration)
        self.export_btn = QPushButton(tr("Export Model..."))
        self.export_btn.setEnabled(False)
        self.export_btn.clicked.connect(self.on_export_model)
        left_layout.addWidget(self.export_btn)

        left_tabs = QTabWidget()

        # 1. Sweep Parameters Tab
        settings_tab = QWidget()
        form = QFormLayout()
        form.setContentsMargins(6, 6, 6, 6)
        form.setSpacing(6)
        self.settings_form = form

        self.combo_meas_mode = QComboBox()
        self.combo_meas_mode.addItem(tr("Sweep Measurement (Default)"), "sweep")
        self.combo_meas_mode.addItem(tr("Nonlinear Model (Forward)"), "hammerstein")
        self.combo_meas_mode.currentIndexChanged.connect(self.on_meas_mode_changed)
        form.addRow(tr("Sweep Mode:"), self.combo_meas_mode)

        sample_rate = self.module.audio_engine.sample_rate
        nyquist = sample_rate / 2.0

        self.spin_start_freq = QDoubleSpinBox()
        self.spin_start_freq.setRange(2.0, nyquist)
        self.spin_start_freq.setValue(self.module.start_freq)
        self.spin_start_freq.setSuffix(" Hz")
        form.addRow(tr("Start Freq:"), self.spin_start_freq)

        self.spin_end_freq = QDoubleSpinBox()
        self.spin_end_freq.setRange(2.0, nyquist)
        self.spin_end_freq.setValue(self.module.end_freq)
        self.spin_end_freq.setSuffix(" Hz")
        form.addRow(tr("End Freq:"), self.spin_end_freq)

        self.spin_duration = QDoubleSpinBox()
        self.spin_duration.setRange(2.0, 600.0)
        self.spin_duration.setValue(self.module.sweep_duration)
        self.spin_duration.setSuffix(" s")
        form.addRow(tr("Duration:"), self.spin_duration)

        self.spin_amplitude = QDoubleSpinBox()
        self.spin_amplitude.setRange(-100.0, 0.0)
        # Convert output linear amplitude to dBFS
        init_db = 20 * np.log10(self.module.output_amplitude)
        self.spin_amplitude.setValue(init_db)
        self.spin_amplitude.setSuffix(" dBFS")
        form.addRow(tr("Amplitude:"), self.spin_amplitude)

        self.spin_max_harmonic = QSpinBox()
        self.spin_max_harmonic.setRange(1, 5)
        self.spin_max_harmonic.setValue(self.module.max_harmonic)
        self.spin_max_harmonic.valueChanged.connect(self.update_harmonic_visibility)
        form.addRow(tr("Max Harmonic:"), self.spin_max_harmonic)

        self.spin_averaging = QSpinBox()
        self.spin_averaging.setRange(1, 100)
        self.spin_averaging.setValue(self.module.averaging_count)
        form.addRow(tr("Averages:"), self.spin_averaging)

        self.spin_amp_steps = QSpinBox()
        self.spin_amp_steps.setRange(5, 10)
        self.spin_amp_steps.setValue(5)
        form.addRow(tr("Amplitude Steps:"), self.spin_amp_steps)
        self.spin_amp_steps.setVisible(False)

        settings_tab.setLayout(form)
        left_tabs.addTab(settings_tab, tr("Settings"))

        # 2. Display Option Tab
        display_tab = QWidget()
        display_layout = QVBoxLayout(display_tab)
        display_layout.setContentsMargins(8, 8, 8, 8)
        display_layout.setSpacing(10)

        # Group for check boxes
        options_layout = QVBoxLayout()
        options_layout.setSpacing(6)

        self.chk_relative = QCheckBox(tr("Show Relative to Fundamental"))
        self.chk_relative.setChecked(False)
        self.chk_relative.toggled.connect(self.redraw_plots)
        options_layout.addWidget(self.chk_relative)

        self.chk_unwrap = QCheckBox(tr("Unwrap Phase"))
        self.chk_unwrap.setChecked(False)
        self.chk_unwrap.toggled.connect(self.redraw_plots)
        options_layout.addWidget(self.chk_unwrap)

        self.chk_show_raw = QCheckBox(tr("Show Raw Lock-in (Unprocessed)"))
        self.chk_show_raw.setChecked(False)
        self.chk_show_raw.toggled.connect(self.redraw_plots)
        options_layout.addWidget(self.chk_show_raw)

        display_layout.addLayout(options_layout)

        # Separator spacing
        display_layout.addSpacing(4)

        # Form layout for display settings
        display_form = QFormLayout()
        display_form.setContentsMargins(0, 0, 0, 0)
        display_form.setSpacing(6)

        self.lbl_amplitude_select = QLabel(tr("Display Data:"))
        self.combo_amplitude_select = QComboBox()
        self.combo_amplitude_select.addItem(tr("Model Kernels"), "kernels")
        self.combo_amplitude_select.currentIndexChanged.connect(self.redraw_plots)
        self.combo_amplitude_select.setVisible(False)
        self.lbl_amplitude_select.setVisible(False)
        display_form.addRow(self.lbl_amplitude_select, self.combo_amplitude_select)

        self.lbl_smoothing = QLabel(tr("Graph Smoothing:"))
        self.combo_smoothing = QComboBox()
        self.combo_smoothing.addItem(tr("None"), "None")
        self.combo_smoothing.addItem(tr("Low Smoothing"), "Light")
        self.combo_smoothing.addItem(tr("Medium Smoothing"), "Medium")
        self.combo_smoothing.addItem(tr("High Smoothing"), "Heavy")
        self.combo_smoothing.setCurrentIndex(0)
        self.combo_smoothing.currentIndexChanged.connect(self.redraw_plots)
        display_form.addRow(self.lbl_smoothing, self.combo_smoothing)

        display_layout.addLayout(display_form)
        display_layout.addStretch()

        left_tabs.addTab(display_tab, tr("Display"))

        # 3. Routing & Cal Tab (Consolidated)
        routing_tab = QWidget()
        routing_layout = QVBoxLayout(routing_tab)
        routing_layout.setContentsMargins(6, 6, 6, 6)
        routing_layout.setSpacing(8)

        r_form = QFormLayout()
        r_form.setSpacing(6)

        self.combo_output_ch = QComboBox()
        self.combo_output_ch.addItems([tr("Left (Ch 1)"), tr("Right (Ch 2)"), tr("Stereo (Both)")])
        out_idx = 2 if self.module.output_channel == 2 else self.module.output_channel
        self.combo_output_ch.setCurrentIndex(out_idx)
        r_form.addRow(tr("Output Ch:"), self.combo_output_ch)

        self.combo_in_mode = QComboBox()
        self.combo_in_mode.addItem(tr("Single Ch (Left Input)"), "Single_L")
        self.combo_in_mode.addItem(tr("Single Ch (Right Input)"), "Single_R")
        self.combo_in_mode.addItem(tr("2-Ch Relative (Ref=Left, Meas=Right)"), "XFER")
        self.combo_in_mode.addItem(tr("2-Ch Relative (Ref=Right, Meas=Left)"), "XFER_REV")

        # Determine initial selection based on module variables
        if getattr(self.module, "input_mode", "Single") == "XFER":
            if self.module.ref_channel == 0 and self.module.signal_channel == 1:
                self.combo_in_mode.setCurrentIndex(2)
            else:
                self.combo_in_mode.setCurrentIndex(3)
        else:
            if self.module.signal_channel == 0:
                self.combo_in_mode.setCurrentIndex(0)
            else:
                self.combo_in_mode.setCurrentIndex(1)
        r_form.addRow(tr("Input Mode:"), self.combo_in_mode)

        self.chk_ref_phase_only = QCheckBox(tr("REF Phase Lock Only (Absolute)"))
        self.chk_ref_phase_only.setChecked(getattr(self.module, "ref_phase_only", False))
        self.chk_ref_phase_only.toggled.connect(self.on_ref_phase_only_toggled)
        r_form.addRow("", self.chk_ref_phase_only)

        self.combo_in_mode.currentIndexChanged.connect(self.on_in_mode_changed)
        self.on_in_mode_changed(self.combo_in_mode.currentIndex())

        routing_layout.addLayout(r_form)

        routing_layout.addStretch()

        left_tabs.addTab(routing_tab, tr("Routing"))

        # 4. Advanced Tab
        advanced_tab = QWidget()
        adv_layout = QVBoxLayout(advanced_tab)
        adv_layout.setContentsMargins(4, 4, 4, 4)
        adv_layout.setSpacing(6)

        # General Advanced Form
        adv_form_widget = QWidget()
        adv_form = QFormLayout(adv_form_widget)
        adv_form.setContentsMargins(2, 2, 2, 2)
        adv_form.setSpacing(6)

        self.combo_preset = QComboBox()
        self.combo_preset.addItem(tr("Fast & Dynamic (16 cyc / 30 ms)"), "fast")
        self.combo_preset.addItem(tr("Normal (64 cyc / 100 ms)"), "normal")
        self.combo_preset.addItem(tr("High Resolution (128 cyc / 500 ms)"), "high_res")
        self.combo_preset.addItem(tr("High Stability (256 cyc / 1.0 s)"), "high_stab")
        self.combo_preset.addItem(tr("Maximum Stability (512 cyc / 2.0 s)"), "max_stab")
        self.combo_preset.addItem(tr("Custom"), "custom")
        self.combo_preset.currentIndexChanged.connect(self.on_preset_changed)
        adv_form.addRow(tr("Preset:"), self.combo_preset)

        self.spin_analysis_cycles = QDoubleSpinBox()
        self.spin_analysis_cycles.setRange(2.0, 2048.0)
        self.spin_analysis_cycles.setSingleStep(1.0)
        self.spin_analysis_cycles.setValue(self.module.analysis_cycles)
        self.spin_analysis_cycles.setSuffix(" cycles")
        self.spin_analysis_cycles.valueChanged.connect(self.on_advanced_spin_changed)
        adv_form.addRow(tr("Analysis Cycles:"), self.spin_analysis_cycles)

        self.spin_meas_points = QSpinBox()
        self.spin_meas_points.setRange(100, 5000)
        self.spin_meas_points.setSingleStep(100)
        self.spin_meas_points.setValue(self.module.num_meas_points)
        adv_form.addRow(tr("Meas Points:"), self.spin_meas_points)

        self.spin_min_window = QDoubleSpinBox()
        self.spin_min_window.setRange(2.0, 5000.0)
        self.spin_min_window.setSingleStep(1.0)
        self.spin_min_window.setValue(self.module.min_analysis_window * 1000.0)
        self.spin_min_window.setSuffix(" ms")
        self.spin_min_window.valueChanged.connect(self.on_advanced_spin_changed)
        adv_form.addRow(tr("Min Window:"), self.spin_min_window)

        # Sync combo box index on startup based on self.module.analysis_cycles and self.module.min_analysis_window
        self.sync_preset_from_values()

        self.chk_realtime_display = QCheckBox(tr("Real-time Display"))
        self.chk_realtime_display.setChecked(not self.module.prevent_buffer_underrun)
        adv_form.addRow(tr("Real-time Display:"), self.chk_realtime_display)

        adv_layout.addWidget(adv_form_widget)
        adv_layout.addStretch()
        left_tabs.addTab(advanced_tab, tr("Advanced"))

        left_layout.addWidget(left_tabs)

        # Latency Calibration Box (moved outside tab)
        calib_group = QGroupBox(tr("Latency Calibration"))
        calib_layout = QVBoxLayout()
        calib_layout.setContentsMargins(8, 8, 8, 8)
        calib_layout.setSpacing(6)

        self.btn_calibrate = QPushButton(tr("Calibrate Latency"))
        self.btn_calibrate.clicked.connect(self.on_calibrate_latency)
        calib_layout.addWidget(self.btn_calibrate)

        self.lbl_calib_status = QLabel(tr("Uncalibrated (0.0 ms)"))
        self.lbl_calib_status.setStyleSheet("color: #ffaa00; font-weight: bold;")
        calib_layout.addWidget(self.lbl_calib_status)

        calib_group.setLayout(calib_layout)
        left_layout.addWidget(calib_group)

        # Overview Stats (moved outside, kept at the bottom)
        stats_group = QGroupBox(tr("Overview"))
        stats_layout = QVBoxLayout()
        stats_layout.setContentsMargins(8, 8, 8, 8)
        stats_layout.setSpacing(4)

        self.lbl_progress = QLabel(tr("Sweep Progress: --"))
        stats_layout.addWidget(self.lbl_progress)

        self.lbl_current_freq = QLabel(tr("Current Freq: -- Hz"))
        stats_layout.addWidget(self.lbl_current_freq)

        self.lbl_resolution = QLabel(tr("Resolution (ENBW): --"))
        stats_layout.addWidget(self.lbl_resolution)

        stats_group.setLayout(stats_layout)
        left_layout.addWidget(stats_group)

        left_layout.addStretch()
        layout.addWidget(left_panel)

        # RIGHT PANEL: Container & Layout
        right_container = QWidget()
        right_layout = QVBoxLayout(right_container)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)

        # RIGHT PANEL: Tab Widget
        self.plot_tabs = QTabWidget()
        self.plot_tabs.setMinimumHeight(450)

        # Tab 1: Frequency Response (Magnitude & Phase stacked)
        self.freq_tab = QWidget()
        freq_layout = QVBoxLayout(self.freq_tab)
        freq_layout.setContentsMargins(4, 4, 4, 4)
        freq_layout.setSpacing(6)

        # Checkboxes for harmonic visibility control
        self.chk_harmonics_layout = QHBoxLayout()
        self.chk_harmonics_layout.setContentsMargins(4, 2, 4, 2)
        self.chk_harmonics_layout.setSpacing(10)

        self.chk_harmonics = []
        labels = [tr("Fundamental"), tr("2nd"), tr("3rd"), tr("4th"), tr("5th")]
        for lbl in labels:
            chk = QCheckBox(lbl)
            chk.setChecked(True)
            chk.toggled.connect(self.update_harmonic_visibility)
            self.chk_harmonics.append(chk)
            self.chk_harmonics_layout.addWidget(chk)

        self.chk_harmonics_layout.addStretch()
        freq_layout.addLayout(self.chk_harmonics_layout)

        self.plot_mag = pg.PlotWidget(title=tr("Magnitude Response"))
        self.plot_mag.setMinimumHeight(150)
        self.plot_mag.setLabel("bottom", tr("Frequency (Hz)"))
        self.plot_mag.setLabel("left", tr("Amplitude"), units="dBFS")
        self.plot_mag.setLogMode(x=True, y=False)
        self.plot_mag.showGrid(x=True, y=True)
        self.plot_mag.setYRange(-140, 10)
        freq_layout.addWidget(self.plot_mag)

        self.plot_phase = pg.PlotWidget(title=tr("Phase Response"))
        self.plot_phase.setMinimumHeight(150)
        self.plot_phase.setLabel("bottom", tr("Frequency (Hz)"))
        self.plot_phase.setLabel("left", tr("Phase"), units="deg")
        self.plot_phase.setLogMode(x=True, y=False)
        self.plot_phase.showGrid(x=True, y=True)
        self.plot_phase.setYRange(-180, 180)
        self.plot_phase.setXLink(self.plot_mag)
        freq_layout.addWidget(self.plot_phase)

        self.plot_tabs.addTab(self.freq_tab, tr("Frequency Response"))

        # Tab 2: Impulse Responses (Kernels)
        self.kernel_tab = QWidget()
        kernel_layout = QVBoxLayout(self.kernel_tab)
        self.plot_kernel = pg.PlotWidget(title=tr("Impulse Responses (Kernels)"))
        self.plot_kernel.setMinimumHeight(150)
        self.plot_kernel.setLabel("bottom", tr("Time"), units="ms")
        self.plot_kernel.setLabel("left", tr("Normalized Amplitude"))
        self.plot_kernel.showGrid(x=True, y=True)
        kernel_layout.addWidget(self.plot_kernel)
        self.plot_tabs.addTab(self.kernel_tab, tr("Impulse Responses (Kernels)"))
        self.plot_tabs.setTabEnabled(1, False)

        # Create Plot Curves with distinct colors (modernized palette)
        # 1st: Light Blue, 2nd: Light Green, 3rd: Light Amber, 4th: Purple, 5th: Light Red
        self.colors = ["#4fc3f7", "#81c784", "#ffd54f", "#ba68c8", "#e57373"]
        self.mag_curves = []
        self.phase_curves = []
        self.kernel_curves = []

        # Add legends
        self.plot_mag.addLegend(offset=(10, 10))
        self.plot_kernel.addLegend(offset=(10, 10))

        for idx in range(5):
            lbl = tr("Fundamental") if idx == 0 else tr("{0}th Harmonic").format(idx + 1)
            mag_c = self.plot_mag.plot(pen=self.colors[idx], name=lbl)
            phase_c = self.plot_phase.plot(pen=self.colors[idx])
            self.mag_curves.append(mag_c)
            self.phase_curves.append(phase_c)

            lbl_k = tr("1st Order (h1)") if idx == 0 else tr("{0}th Order (h{1})").format(idx + 1, idx + 1)
            kernel_c = self.plot_kernel.plot(pen=self.colors[idx], name=lbl_k)
            self.kernel_curves.append(kernel_c)

        right_layout.addWidget(self.plot_tabs)
        layout.addWidget(right_container, 2)
        self.setLayout(layout)
        self.setMinimumSize(990, 620)

        # Set initial X range based on default sweep params
        x_min = min(self.module.start_freq, self.module.end_freq)
        x_max = max(self.module.start_freq, self.module.end_freq)
        self.plot_mag.setXRange(np.log10(x_min), np.log10(x_max), padding=0)

        # Sync settings on initialization
        self.on_meas_mode_changed(0)
        self.update_harmonic_visibility()

    def on_calibrate_latency(self):
        # Update settings parameters for calibration sweep
        self.module.start_freq = self.spin_start_freq.value()
        self.module.end_freq = self.spin_end_freq.value()
        self.module.output_channel = (
            2 if self.combo_output_ch.currentIndex() == 2 else self.combo_output_ch.currentIndex()
        )

        # Sync input mode and channels
        in_idx = self.combo_in_mode.currentIndex()
        if in_idx == 0:
            self.module.input_mode = "Single"
            self.module.signal_channel = 0
            self.module.ref_channel = 1
        elif in_idx == 1:
            self.module.input_mode = "Single"
            self.module.signal_channel = 1
            self.module.ref_channel = 0
        elif in_idx == 2:
            self.module.input_mode = "XFER"
            self.module.ref_channel = 0
            self.module.signal_channel = 1
        elif in_idx == 3:
            self.module.input_mode = "XFER"
            self.module.ref_channel = 1
            self.module.signal_channel = 0

        self.btn_calibrate.setEnabled(False)
        self.btn_toggle.setEnabled(False)
        self.lbl_calib_status.setText(tr("Calibrating Latency..."))
        self.lbl_calib_status.setStyleSheet("color: #ffaa00; font-weight: bold;")

        # Start calibration in a separate thread to keep UI interactive
        self.calib_thread = LatencyCalibThread(
            self.module.audio_engine,
            self.module.start_freq,
            self.module.end_freq,
            self.module.output_channel,
            self.module.signal_channel,
        )
        self.calib_thread.finished_sig.connect(self.on_calibration_success)
        self.calib_thread.error_sig.connect(self.on_calibration_error)
        self.calib_thread.start()

    def on_calibration_success(self, latency_samples):
        self.module.latency_samples = latency_samples
        ms = latency_samples / self.module.audio_engine.sample_rate * 1000.0
        self.lbl_calib_status.setText(tr("{0:.2f} ms ({1:.1f} samples)").format(ms, latency_samples))
        self.lbl_calib_status.setStyleSheet("color: #00ff00; font-weight: bold;")
        self.btn_calibrate.setEnabled(True)
        self.btn_toggle.setEnabled(self.module.latency_samples > 0.0)

    def on_calibration_error(self, err_msg):
        self.module.latency_samples = 0.0
        self.lbl_calib_status.setText(tr("Calibration Error!"))
        self.lbl_calib_status.setStyleSheet("color: #ff3333; font-weight: bold;")
        self.btn_calibrate.setEnabled(True)
        self.btn_toggle.setEnabled(False)

    def on_toggle_sweep(self, checked):
        if checked:
            # Sync parameters from GUI
            self.module.start_freq = self.spin_start_freq.value()
            self.module.end_freq = self.spin_end_freq.value()
            self.module.sweep_duration = self.spin_duration.value()
            # Convert dBFS to linear amplitude
            self.module.output_amplitude = 10 ** (self.spin_amplitude.value() / 20.0)
            self.module.max_harmonic = self.spin_max_harmonic.value()
            self.module.averaging_count = self.spin_averaging.value()
            self.module.analysis_cycles = self.spin_analysis_cycles.value()
            self.module.num_meas_points = self.spin_meas_points.value()
            self.module.min_analysis_window = self.spin_min_window.value() / 1000.0
            self.module.prevent_buffer_underrun = not self.chk_realtime_display.isChecked()

            self.module.output_channel = (
                2 if self.combo_output_ch.currentIndex() == 2 else self.combo_output_ch.currentIndex()
            )

            # Sync input mode and channels
            self.module.ref_phase_only = self.chk_ref_phase_only.isChecked()
            in_idx = self.combo_in_mode.currentIndex()
            if in_idx == 0:
                self.module.input_mode = "Single"
                self.module.signal_channel = 0
                self.module.ref_channel = 1
            elif in_idx == 1:
                self.module.input_mode = "Single"
                self.module.signal_channel = 1
                self.module.ref_channel = 0
            elif in_idx == 2:
                self.module.input_mode = "XFER"
                self.module.ref_channel = 0
                self.module.signal_channel = 1
            elif in_idx == 3:
                self.module.input_mode = "XFER"
                self.module.ref_channel = 1
                self.module.signal_channel = 0

            mode = self.combo_meas_mode.currentData()
            self.is_hammerstein_mode = mode == "hammerstein"
            if self.is_hammerstein_mode:
                self.num_amplitudes = self.spin_amp_steps.value()
                max_amp_db = self.spin_amplitude.value()
                max_amp = 10 ** (max_amp_db / 20.0)
                self.amplitudes = np.linspace(0.2, 1.0, self.num_amplitudes) * max_amp
                self.current_amp_idx = 0
                self.current_avg_idx = 0

                self.module.output_amplitude = self.amplitudes[0]
                self.module.averaging_count = self.num_amplitudes * self.spin_averaging.value()

                if hasattr(self, "combo_amplitude_select"):
                    self.combo_amplitude_select.blockSignals(True)
                    self.combo_amplitude_select.clear()
                    self.combo_amplitude_select.addItem(tr("Model Kernels"), "kernels")
                    for i, amp in enumerate(self.amplitudes):
                        self.combo_amplitude_select.addItem(tr("Amplitude {0} ({1:.3f} V)").format(i + 1, amp), f"amp_{i}")
                    self.combo_amplitude_select.blockSignals(False)
                    self.combo_amplitude_select.setCurrentIndex(0)

            # Update Plot Labels based on mode
            self.redraw_plots()

            # Set X range based on current sweep params
            start_val = self.module.start_freq
            end_val = self.module.end_freq
            x_min = min(start_val, end_val)
            x_max = max(start_val, end_val)
            self.plot_mag.setXRange(np.log10(x_min), np.log10(x_max), padding=0)

            # Clear plot curves
            for idx in range(5):
                self.mag_curves[idx].setData([], [])
                self.phase_curves[idx].setData([], [])
                self.kernel_curves[idx].setData([], [])

            self.plot_tabs.setTabEnabled(1, False)

            self.btn_toggle.setText(tr("Stop Sweep"))
            self.btn_calibrate.setEnabled(False)
            self.set_controls_enabled(False)
            self.export_btn.setEnabled(False)

            self.module.start_analysis()

            # Initialize accumulated arrays
            self.max_blocks = self.module.max_blocks
            self.accumulated_results = np.zeros((self.max_blocks, 5), dtype=complex)
            self.block_counts = np.zeros(self.max_blocks, dtype=int)
            self.plot_freqs_array = np.zeros(self.max_blocks)
            self.current_analysis_freq = None

            self.H_freqs = []
            self.kernels_time = []
            self.time_ms = []

            if self.is_hammerstein_mode:
                self.raw_responses = np.zeros(
                    (self.num_amplitudes, self.max_blocks, self.module.max_harmonic), dtype=complex
                )
                self.raw_counts = np.zeros((self.num_amplitudes, self.max_blocks), dtype=int)

            # Spawn calculation thread (always asynchronous)
            self.calc_thread = SSSCalculationThread(
                self.module.engine, self.module.input_queue, prevent_underrun=self.module.prevent_buffer_underrun
            )
            self.calc_thread.block_calculated.connect(self.on_block_calculated)
            self.calc_thread.sweep_finished.connect(self.on_sweep_finished)
            self.calc_thread.start()

            self.timer.start()
        else:
            was_finished = self.module.state == "FINISHED"
            self.module.stop_analysis()
            self.timer.stop()

            # Terminate and clean up the async calculation thread
            if hasattr(self, "calc_thread") and self.calc_thread:
                self.calc_thread.stop()
                self.calc_thread.wait()
                self.calc_thread = None
            self.module.state = "IDLE"

            # Render any remaining calculation blocks from the queue
            self.update_plots()

            if was_finished:
                total_sweeps = self.module.averaging_count
                progress_text = tr("Sweep (Audio): {0:.1f}% (Sweep {1}/{2})").format(100.0, total_sweeps, total_sweeps)
                progress_text += "\n" + tr("Analysis: {0:.1f}%").format(100.0)
                self.lbl_progress.setText(progress_text)

                freq_text = tr("Audio Freq: {0:.1f} Hz").format(self.module.end_freq)
                freq_text += "\n" + tr("Analysis Freq: {0:.1f} Hz").format(self.module.end_freq)
                self.lbl_current_freq.setText(freq_text)

                # Set resolution based on end frequency (handle mocked objects in tests)
                fs = self.module.audio_engine.sample_rate
                if isinstance(fs, (int, float)):
                    max_win = 1.0
                    if self.module.engine and hasattr(self.module.engine, "max_analysis_window"):
                        val = self.module.engine.max_analysis_window
                        if isinstance(val, (int, float)):
                            max_win = val

                    window_seconds = np.clip(
                        self.module.analysis_cycles / max(self.module.end_freq, 1.0),
                        self.module.min_analysis_window,
                        max_win,
                    )
                    window_samples = int(max(256.0, float(window_seconds * fs)))
                    enbw = 1.5 * fs / window_samples
                    self.lbl_resolution.setText(
                        tr("Resolution (ENBW): {0:.1f} Hz ({1} samples)").format(enbw, window_samples)
                    )
                else:
                    self.lbl_resolution.setText(tr("Resolution (ENBW): --"))

                self.calculate_hammerstein_kernels()
                self.redraw_plots()
            else:
                self.export_btn.setEnabled(False)
                self.lbl_resolution.setText(tr("Resolution (ENBW): --"))

            self.btn_toggle.setText(tr("Start Sweep"))
            self.btn_calibrate.setEnabled(True)
            self.set_controls_enabled(True)

        self.apply_theme()

    def showEvent(self, event):
        super().showEvent(event)
        self.update_frequency_limits()

    def update_frequency_limits(self):
        sample_rate = self.module.audio_engine.sample_rate
        nyquist = sample_rate / 2.0

        self.spin_start_freq.blockSignals(True)
        self.spin_start_freq.setRange(2.0, nyquist)
        if self.spin_start_freq.value() > nyquist:
            self.spin_start_freq.setValue(min(20.0, nyquist))
            self.module.start_freq = self.spin_start_freq.value()
        self.spin_start_freq.blockSignals(False)

        self.spin_end_freq.blockSignals(True)
        self.spin_end_freq.setRange(2.0, nyquist)
        if self.spin_end_freq.value() > nyquist:
            self.spin_end_freq.setValue(nyquist)
            self.module.end_freq = self.spin_end_freq.value()
        self.spin_end_freq.blockSignals(False)

    def set_controls_enabled(self, enabled):
        self.combo_meas_mode.setEnabled(enabled)
        self.spin_amp_steps.setEnabled(enabled)
        self.spin_start_freq.setEnabled(enabled)
        self.spin_end_freq.setEnabled(enabled)
        self.spin_duration.setEnabled(enabled)
        self.spin_amplitude.setEnabled(enabled)
        self.spin_max_harmonic.setEnabled(enabled)
        self.spin_averaging.setEnabled(enabled)
        self.combo_output_ch.setEnabled(enabled)
        self.combo_in_mode.setEnabled(enabled)
        self.chk_ref_phase_only.setEnabled(enabled and self.combo_in_mode.currentIndex() in {2, 3})
        self.combo_preset.setEnabled(enabled)
        self.spin_analysis_cycles.setEnabled(enabled)
        self.spin_meas_points.setEnabled(enabled)
        self.spin_min_window.setEnabled(enabled)
        self.chk_realtime_display.setEnabled(enabled)

    def sync_preset_from_values(self):
        cycles = self.spin_analysis_cycles.value()
        window_ms = self.spin_min_window.value()

        presets = {
            "fast": (16.0, 30.0),
            "normal": (64.0, 100.0),
            "high_res": (128.0, 500.0),
            "high_stab": (256.0, 1000.0),
            "max_stab": (512.0, 2000.0),
        }

        matched_key = "custom"
        for key, (p_cyc, p_win) in presets.items():
            if abs(cycles - p_cyc) < 1e-3 and abs(window_ms - p_win) < 1e-3:
                matched_key = key
                break

        self.combo_preset.blockSignals(True)
        idx = self.combo_preset.findData(matched_key)
        if idx >= 0:
            self.combo_preset.setCurrentIndex(idx)
        self.combo_preset.blockSignals(False)

    def on_preset_changed(self, index):
        key = self.combo_preset.currentData()
        if key == "custom":
            return

        presets = {
            "fast": (16.0, 30.0),
            "normal": (64.0, 100.0),
            "high_res": (128.0, 500.0),
            "high_stab": (256.0, 1000.0),
            "max_stab": (512.0, 2000.0),
        }

        if key in presets:
            cyc, win = presets[key]

            self.spin_analysis_cycles.blockSignals(True)
            self.spin_min_window.blockSignals(True)

            self.spin_analysis_cycles.setValue(cyc)
            self.spin_min_window.setValue(win)

            self.spin_analysis_cycles.blockSignals(False)
            self.spin_min_window.blockSignals(False)

            self.module.analysis_cycles = cyc
            self.module.min_analysis_window = win / 1000.0

    def on_advanced_spin_changed(self, value):
        self.sync_preset_from_values()
        self.module.analysis_cycles = self.spin_analysis_cycles.value()
        self.module.min_analysis_window = self.spin_min_window.value() / 1000.0

    def on_in_mode_changed(self, idx):
        is_xfer = idx in {2, 3}
        self.chk_ref_phase_only.setEnabled(is_xfer)

    def on_ref_phase_only_toggled(self, checked):
        self.module.ref_phase_only = checked
        self.redraw_plots()

    def on_meas_mode_changed(self, index):
        mode = self.combo_meas_mode.currentData()
        is_ham = mode == "hammerstein"

        self.spin_amp_steps.setVisible(is_ham)
        label = self.settings_form.labelForField(self.spin_amp_steps)
        if label:
            label.setVisible(is_ham)

        if hasattr(self, "chk_show_raw"):
            self.chk_show_raw.setChecked(not is_ham)
            self.chk_show_raw.setVisible(True)

        if hasattr(self, "combo_amplitude_select"):
            self.combo_amplitude_select.setVisible(is_ham)
            self.lbl_amplitude_select.setVisible(is_ham)
            if not is_ham:
                self.combo_amplitude_select.setCurrentIndex(0)

        self.plot_tabs.setTabEnabled(1, True)
        self.export_btn.setEnabled(False)
        self.redraw_plots()

    def update_harmonic_visibility(self):
        max_h = self.spin_max_harmonic.value()
        for idx, chk in enumerate(self.chk_harmonics):
            has_harmonic = (idx + 1) <= max_h
            chk.setEnabled(has_harmonic)
            visible = chk.isChecked() and has_harmonic

            if idx < len(self.mag_curves):
                self.mag_curves[idx].setVisible(visible)
            if idx < len(self.phase_curves):
                self.phase_curves[idx].setVisible(visible)
            if idx < len(self.kernel_curves):
                self.kernel_curves[idx].setVisible(visible)

    def process_remaining_queue(self):
        items = []
        with self.module.lock:
            while self.module.measurement_queue:
                items.append(self.module.measurement_queue.popleft())

        if not items:
            return False

        latest_f_mid = None
        f_min = min(self.module.start_freq, self.module.end_freq)
        f_max = max(self.module.start_freq, self.module.end_freq)

        for block_idx, sweep_idx, f_mid, results, is_valid in items:
            if is_valid and block_idx < self.max_blocks:
                if f_min <= f_mid <= f_max:
                    n_harm = min(len(results), 5)
                    # Accumulate complex values
                    self.accumulated_results[block_idx, :n_harm] += results[:n_harm]
                    self.block_counts[block_idx] += 1
                    self.plot_freqs_array[block_idx] = f_mid
                    latest_f_mid = f_mid
                    self.current_analysis_freq = latest_f_mid

                    if getattr(self, "is_hammerstein_mode", False):
                        N_avg = self.spin_averaging.value()
                        amp_idx = sweep_idx // N_avg
                        if amp_idx < self.num_amplitudes:
                            self.raw_responses[amp_idx, block_idx, :n_harm] += results[:n_harm]
                            self.raw_counts[amp_idx, block_idx] += 1
        return True

    def update_plots(self):
        # Retrieve all pending samples from queue
        has_new_items = self.process_remaining_queue()

        # 2. Display progress info (always run to update audio capture progress, even if items is empty)
        if self.module.engine and self.module.engine.sweep_samples > 0:
            total_blocks = self.max_blocks * self.module.averaging_count

            # Audio capture progress
            audio_blocks = self.module.current_sweep_idx * self.max_blocks + self.module.current_block_idx
            audio_blocks = min(audio_blocks, total_blocks)
            audio_pct = (audio_blocks / total_blocks) * 100.0

            # Calculation progress
            if getattr(self, "is_hammerstein_mode", False):
                calc_blocks = int(np.sum(self.raw_counts))
            else:
                calc_blocks = np.sum(self.block_counts)
            calc_blocks = min(calc_blocks, total_blocks)
            calc_pct = (calc_blocks / total_blocks) * 100.0

            # Current audio sweep frequency
            # Calculate physical sample index of current audio block
            audio_sample_idx = self.module.current_block_idx * self.module.audio_engine.block_size
            audio_freq = 0.0
            if hasattr(self.module.engine, "_frequency_at_sample"):
                func = self.module.engine._frequency_at_sample
                # Ensure the method itself is not mocked
                if not hasattr(func, "_mock_return_value") and "MagicMock" not in type(func).__name__:
                    try:
                        val = func(audio_sample_idx)
                        if isinstance(val, (int, float, np.floating, np.integer)) and not hasattr(
                            val, "_mock_return_value"
                        ):
                            audio_freq = float(val)
                    except Exception as e:
                        logger.debug(f"Failed to evaluate sweep frequency: {e}")

            # Format label text
            progress_text = tr("Sweep (Audio): {0:.1f}% (Sweep {1}/{2})").format(
                audio_pct,
                min(self.module.current_sweep_idx + 1, self.module.averaging_count),
                self.module.averaging_count,
            )
            if self.module.state == "WAITING":
                progress_text += "\n" + tr("Analysis: {0:.1f}% (Catching up...)").format(calc_pct)
            else:
                progress_text += "\n" + tr("Analysis: {0:.1f}%").format(calc_pct)

            self.lbl_progress.setText(progress_text)

            freq_text = tr("Audio Freq: {0:.1f} Hz").format(audio_freq)

            # Find the latest calculated frequency
            # Use persistent current_analysis_freq to avoid flickering back to previous sweep end
            display_f_mid = self.current_analysis_freq

            if display_f_mid is not None:
                freq_text += "\n" + tr("Analysis Freq: {0:.1f} Hz").format(display_f_mid)

                # Calculate real-time window size and ENBW safely (handle mocked objects in tests)
                fs = self.module.audio_engine.sample_rate
                if isinstance(fs, (int, float)) and self.module.engine:
                    max_win = 1.0
                    if hasattr(self.module.engine, "max_analysis_window"):
                        val = self.module.engine.max_analysis_window
                        if isinstance(val, (int, float)):
                            max_win = val

                    window_seconds = np.clip(
                        self.module.analysis_cycles / max(display_f_mid, 1.0), self.module.min_analysis_window, max_win
                    )
                    window_samples = int(max(256.0, float(window_seconds * fs)))
                    enbw = 1.5 * fs / window_samples

                    self.lbl_resolution.setText(
                        tr("Resolution (ENBW): {0:.1f} Hz ({1} samples)").format(enbw, window_samples)
                    )
                else:
                    self.lbl_resolution.setText(tr("Resolution (ENBW): --"))
            else:
                freq_text += "\n" + tr("Analysis Freq: -- Hz")
                self.lbl_resolution.setText(tr("Resolution (ENBW): --"))
            self.lbl_current_freq.setText(freq_text)

        # 3. Redraw curves if there were new items
        if has_new_items:
            self.redraw_plots()

    def redraw_plots(self, *args):
        # Update Plot Labels based on mode
        if self.chk_relative.isChecked():
            self.plot_mag.setLabel("left", tr("Relative Gain"), units="dB")
            self.plot_phase.setLabel("left", tr("Relative Phase"), units="deg")
        else:
            if self.module.input_mode == "XFER" and not getattr(self.module, "ref_phase_only", False):
                self.plot_mag.setLabel("left", tr("Gain"), units="dB")
            else:
                self.plot_mag.setLabel("left", tr("Amplitude"), units="dBFS")
            self.plot_phase.setLabel("left", tr("Phase"), units="deg")

        if not hasattr(self, "block_counts") or self.block_counts is None:
            return

        valid_indices = np.where(self.block_counts > 0)[0]
        if len(valid_indices) == 0:
            return

        x_data = self.plot_freqs_array[valid_indices]

        # Check if we should display a specific amplitude in Hammerstein mode
        amp_idx = -1
        if hasattr(self, "combo_amplitude_select") and self.is_hammerstein_mode:
            amp_idx = self.combo_amplitude_select.currentIndex() - 1

        if amp_idx >= 0:
            # We are displaying raw response of a specific amplitude step
            self.plot_tabs.setTabEnabled(1, False)
            if self.raw_responses is None or self.raw_counts is None:
                return

            counts = self.raw_counts[amp_idx, valid_indices]
            pos = counts > 0
            if not np.any(pos):
                # No data yet for this amplitude step
                for idx in range(self.module.max_harmonic):
                    self.mag_curves[idx].setData([], [])
                    self.phase_curves[idx].setData([], [])
                return

            for idx in range(self.module.max_harmonic):
                avg_complex = np.zeros(len(valid_indices), dtype=complex)
                avg_complex[pos] = self.raw_responses[amp_idx, valid_indices[pos], idx] / counts[pos]

                # Apply predistortion restoration if restored mode is active
                if (getattr(self, "is_predistorted_hammerstein_mode", False)
                        and self.chk_show_restored.isChecked()
                        and idx >= 1):
                    predist_mgr = self.predistortion_managers[amp_idx]
                    current_predist_mgr = predist_mgr if predist_mgr is not None else getattr(self, "predistortion_manager", None)
                    if current_predist_mgr is not None:
                        H1_raw = self.raw_responses[amp_idx, valid_indices, 0] / np.maximum(counts, 1)
                        valid_blocks = counts > 0
                        if np.sum(valid_blocks) >= 2:
                            H1_base = H1_raw[valid_blocks]
                            freq_base = x_data[valid_blocks]
                            avg_complex = current_predist_mgr.restore_true_response(
                                harmonic_order=idx + 1,
                                target_freqs=x_data,
                                measured_complex=avg_complex,
                                H1_base=H1_base,
                                freq_base=freq_base
                            )

                if self.chk_relative.isChecked():
                    fundamental_complex = np.zeros(len(valid_indices), dtype=complex)
                    fundamental_complex[pos] = self.raw_responses[amp_idx, valid_indices[pos], 0] / counts[pos]
                    avg_complex = avg_complex / (fundamental_complex + 1e-30)

                # Compute amplitude in dBFS (or dB if relative)
                amp = np.abs(avg_complex)
                y_gain = 20 * np.log10(amp + 1e-15)

                # Compute phase in degrees
                if self.chk_unwrap.isChecked():
                    y_phase = np.degrees(np.unwrap(np.angle(avg_complex)))
                else:
                    y_phase = np.degrees(np.angle(avg_complex))

                # Apply smoothing
                smooth_level = self.combo_smoothing.currentData()
                y_gain_smoothed = self.apply_smoothing(y_gain, smooth_level)
                y_phase_smoothed = self.apply_smoothing(y_phase, smooth_level)

                self.mag_curves[idx].setData(x_data, y_gain_smoothed)
                self.phase_curves[idx].setData(x_data, y_phase_smoothed)

            return

        # Check if we should draw the final kernels
        has_kernels = len(getattr(self, "H_freqs", [])) > 0
        is_measuring = self.module.state in {"PLAYING", "WAITING"}
        show_processed = not self.chk_show_raw.isChecked() if hasattr(self, "chk_show_raw") else True

        if has_kernels and not is_measuring:
            self.plot_tabs.setTabEnabled(1, True)
            if show_processed:
                # Draw Kernels (Hammerstein or Sweep)
                sort_idx = np.argsort(x_data)
                x_data_sorted = x_data[sort_idx]
                smooth_level = self.combo_smoothing.currentData()

                H_fundamental = self.H_freqs[0][valid_indices][sort_idx] if len(self.H_freqs) > 0 else 1.0

                for idx in range(len(self.H_freqs)):
                    H_p = self.H_freqs[idx][valid_indices][sort_idx]
                    if self.chk_relative.isChecked():
                        H_p = H_p / (H_fundamental + 1e-30)

                    mag_db = 20 * np.log10(np.abs(H_p) + 1e-12)
                    if self.chk_unwrap.isChecked():
                        # H_p may contain NaNs from frequency mapping. Unwrap only non-NaN elements.
                        nan_mask = np.isnan(H_p)
                        phase_deg = np.zeros_like(H_p, dtype=float)
                        if not np.all(nan_mask):
                            phase_deg[~nan_mask] = np.degrees(np.unwrap(np.angle(H_p[~nan_mask])))
                        phase_deg[nan_mask] = np.nan
                    else:
                        phase_deg = np.degrees(np.angle(H_p))

                    # Apply smoothing
                    mag_smoothed = self.apply_smoothing(mag_db, smooth_level)
                    phase_smoothed = self.apply_smoothing(phase_deg, smooth_level)

                    self.mag_curves[idx].setData(x_data_sorted, mag_smoothed)
                    self.phase_curves[idx].setData(x_data_sorted, phase_smoothed)

                if len(self.kernels_time) > 0:
                    ref_max = np.max(np.abs(self.kernels_time[0]))
                    if ref_max < 1e-12:
                        ref_max = 1.0
                    for idx in range(len(self.kernels_time)):
                        norm_kernel = self.kernels_time[idx] / ref_max
                        self.kernel_curves[idx].setData(self.time_ms, norm_kernel)

                return

        # Redraw standard real-time sweeps
        for idx in range(self.module.max_harmonic):
            counts = self.block_counts[valid_indices]
            avg_complex = self.accumulated_results[valid_indices, idx] / counts

            if self.chk_relative.isChecked():
                fundamental_complex = self.accumulated_results[valid_indices, 0] / counts
                avg_complex = avg_complex / (fundamental_complex + 1e-30)

            # Compute amplitude in dBFS (or dB if relative)
            amp = np.abs(avg_complex)
            y_gain = 20 * np.log10(amp + 1e-15)

            # Compute phase in degrees
            if self.chk_unwrap.isChecked():
                y_phase = np.degrees(np.unwrap(np.angle(avg_complex)))
            else:
                y_phase = np.degrees(np.angle(avg_complex))

            # Apply smoothing
            smooth_level = self.combo_smoothing.currentData()
            y_gain_smoothed = self.apply_smoothing(y_gain, smooth_level)
            y_phase_smoothed = self.apply_smoothing(y_phase, smooth_level)

            self.mag_curves[idx].setData(x_data, y_gain_smoothed)
            self.phase_curves[idx].setData(x_data, y_phase_smoothed)

    def apply_smoothing(self, y_data, level):
        if level == "None" or len(y_data) < 15:
            return y_data

        window_size = 15
        if level == "Medium":
            window_size = 35
        elif level == "Heavy":
            window_size = 75

        window_size = min(window_size, len(y_data) - 1)
        if window_size % 2 == 0:
            window_size -= 1

        if window_size < 5:
            return y_data

        # Handle NaNs by temporarily interpolating them before passing to savgol_filter
        nan_mask = np.isnan(y_data)
        y_clean = np.copy(y_data)

        if np.any(nan_mask):
            if np.all(nan_mask):
                return y_data
            x = np.arange(len(y_clean))
            y_clean[nan_mask] = np.interp(x[nan_mask], x[~nan_mask], y_clean[~nan_mask])

        try:
            smoothed = savgol_filter(y_clean, window_size, polyorder=2)
            if np.any(nan_mask):
                smoothed[nan_mask] = np.nan
            return smoothed
        except Exception as e:
            logger.warning("Smoothing failed: %s", e)
            return y_data

    def calculate_hammerstein_kernels(self):
        sample_rate = self.module.audio_engine.sample_rate
        nyquist = sample_rate / 2.0
        P = self.module.max_harmonic
        max_blocks = self.max_blocks

        plot_freqs = self.plot_freqs_array
        valid_idx = np.where(plot_freqs > 0)[0]
        if len(valid_idx) < 2:
            self.H_freqs = [np.zeros(max_blocks, dtype=complex) for _ in range(P)]
            self.kernels_time = [np.zeros(int(0.02 * sample_rate)) for _ in range(P)]
            return

        sort_idx = np.argsort(plot_freqs[valid_idx])
        sorted_freqs = plot_freqs[valid_idx][sort_idx]

        if getattr(self, "is_hammerstein_mode", False):
            # 1. Compute averaged responses for each amplitude
            avg_responses = np.zeros_like(self.raw_responses)
            for amp_idx in range(self.num_amplitudes):
                for block_idx in range(max_blocks):
                    cnt = self.raw_counts[amp_idx, block_idx]
                    if cnt > 0:
                        avg_responses[amp_idx, block_idx] = self.raw_responses[amp_idx, block_idx] / cnt

            # Parallel Complex Hammerstein Estimation (Chebyshev-based subtraction from estimate_power_kernels)
            from src.core.hammerstein_model import estimate_hammerstein_kernels

            H_est, sorted_freqs = estimate_hammerstein_kernels(
                amplitudes=self.amplitudes,
                avg_responses=avg_responses,
                plot_freqs=plot_freqs,
                max_harmonic=P,
                sample_rate=sample_rate,
                input_mode=self.module.input_mode,
                ref_phase_only=getattr(self.module, "ref_phase_only", False),
            )

            self.H_freqs = []
            for p in range(P):
                H_full = np.zeros(max_blocks, dtype=complex)
                H_full[valid_idx[sort_idx]] = H_est[p]
                self.H_freqs.append(H_full)
        else:
            # Standard Sweep Mode (Non-Hammerstein)
            # Directly use accumulated_results and apply phase corrections
            self.H_freqs = []
            phase_corrections = [(1j) ** p for p in range(P)]
            for p in range(P):
                H_p = np.zeros(max_blocks, dtype=complex)
                counts = self.block_counts[valid_idx]
                avg_complex = self.accumulated_results[valid_idx, p] / counts

                H_p[valid_idx] = avg_complex * phase_corrections[p]
                self.H_freqs.append(H_p)

            # 3. Apply frequency mapping to map H_p(f_0) measured at fundamental f_0 to physical harmonic frequency p * f_0
            # H_p_mapped(f) = H_p_raw(f / p)
            H_mapped_list = []
            for p in range(len(self.H_freqs)):
                H_raw = self.H_freqs[p][valid_idx[sort_idx]]
                f_lookups = sorted_freqs / (p + 1)

                # Polar Interpolation to prevent phase distortion
                nan_mask = np.isnan(H_raw)
                valid_mask = ~nan_mask

                if np.any(valid_mask):
                    valid_H = H_raw[valid_mask]
                    xp = sorted_freqs[valid_mask]

                    mags_valid = np.abs(valid_H)
                    phases_valid = np.unwrap(np.angle(valid_H))

                    # Dynamically reduce resolution to improve real-time performance bounds
                    TARGET_RESOLUTION = 2000
                    if len(valid_H) > TARGET_RESOLUTION:
                        step = len(valid_H) // TARGET_RESOLUTION
                        mags_valid = mags_valid[::step]
                        phases_valid = phases_valid[::step]
                        xp = xp[::step]

                    mag_mapped = np.interp(f_lookups, xp, mags_valid, left=np.nan, right=np.nan)
                    phase_mapped = np.interp(f_lookups, xp, phases_valid, left=np.nan, right=np.nan)
                else:
                    mag_mapped = np.full_like(f_lookups, np.nan)
                    phase_mapped = np.full_like(f_lookups, np.nan)

                H_mapped = mag_mapped * np.exp(1j * phase_mapped)
                H_mapped_list.append(H_mapped)

            # Apply Butterworth lowpass filter to higher order mapped kernels
            for p in range(len(self.H_freqs)):
                H_p = H_mapped_list[p]
                if p >= 1:
                    f_cut = min(20000.0, 1.15 * sample_rate / 2)
                    lpf = 1.0 / np.sqrt(1.0 + (sorted_freqs / f_cut) ** 16)
                    H_p = H_p * lpf

                # Pad back to max_blocks length
                H_full = np.zeros(max_blocks, dtype=complex)
                H_full[valid_idx[sort_idx]] = H_p
                self.H_freqs[p] = H_full

        # 4. Reconstruct time domain kernels
        if len(valid_idx) == 0:
            return

        sorted_freqs = plot_freqs[valid_idx][sort_idx]
        gate_pre = int(0.007 * sample_rate)
        N_kernel = int(0.02 * sample_rate)

        # Calculate dynamic N_fft based on N_kernel to prevent shape mismatches at higher sample rates
        N_fft = int(2 ** np.ceil(np.log2(N_kernel)))
        N_fft = max(2048, N_fft)

        freqs_lin = np.linspace(0, nyquist, N_fft // 2 + 1)

        self.time_ms = (np.arange(N_kernel) - gate_pre) / sample_rate * 1000.0
        self.kernels_time = []

        for p in range(len(self.H_freqs)):
            H_p = self.H_freqs[p][valid_idx][sort_idx]
            # Replace NaNs from frequency mapping with 0.0 before IFFT
            mask_nan = np.isnan(H_p)
            H_p_clean = H_p.copy()
            H_p_clean[mask_nan] = 0.0

            mags = np.abs(H_p_clean)
            valid_mask = ~mask_nan
            phases = np.zeros_like(H_p_clean, dtype=float)
            if np.any(valid_mask):
                phases[valid_mask] = np.unwrap(np.angle(H_p_clean[valid_mask]))
            mag_lin = np.interp(freqs_lin, sorted_freqs, mags, left=0.0, right=0.0)
            phase_lin = np.interp(freqs_lin, sorted_freqs, phases, left=0.0, right=0.0)
            H_lin = mag_lin * np.exp(1j * phase_lin)

            phase_shift = np.exp(-1j * 2 * np.pi * freqs_lin * (gate_pre / sample_rate))
            H_lin_shifted = H_lin * phase_shift

            h_full = np.fft.irfft(H_lin_shifted, n=N_fft)
            h_cropped = h_full[:N_kernel]

            win = scipy.signal.windows.tukey(N_kernel, alpha=0.1)
            self.kernels_time.append(h_cropped * win)

        # 5. Push to active model cache
        ref_max = np.max(np.abs(self.kernels_time[0])) if len(self.kernels_time) > 0 else 1.0
        if ref_max < 1e-12:
            ref_max = 1.0

        is_ham = getattr(self, "is_hammerstein_mode", False)

        cache_data = {
            "metadata": {
                "module": self.module.name,
                "sample_rate": sample_rate,
                "num_amplitudes": self.num_amplitudes if is_ham else 1,
                "end_freq": self.module.end_freq,
                "input_mode": self.module.input_mode,
                "ref_phase_only": getattr(self.module, "ref_phase_only", False),
                "latency_sec": self.module.latency_samples / sample_rate,
                "ref_max": float(ref_max),
                "g_ref": 1.0,
                "P": len(self.kernels_time),
                "noise_floor_dbfs": None,
                "amplitude_dbfs": self.spin_amplitude.value(),
                "model_direction": "forward",
                "model_structure": "parallel_complex_hammerstein" if is_ham else "parallel_complex_hammerstein",
                "model_domain": "complex" if is_ham else "real",
                "model_algorithm": "vectorized" if is_ham else "vectorized",
            },
            "time_domain": {
                "time_ms": self.time_ms,
                "kernels": {f"h{p + 1}": self.kernels_time[p] for p in range(len(self.kernels_time))},
            },
            "frequency_domain": {
                "freqs": sorted_freqs,
                "magnitudes_db": {
                    f"h{p + 1}": 20 * np.log10(np.abs(self.H_freqs[p][valid_idx][sort_idx]) + 1e-12)
                    for p in range(len(self.H_freqs))
                },
                "phases_deg": {
                    f"h{p + 1}": np.degrees(np.angle(self.H_freqs[p][valid_idx][sort_idx]))
                    for p in range(len(self.H_freqs))
                },
            },
        }
        set_active_model(cache_data)
        self.export_btn.setEnabled(getattr(self, "is_hammerstein_mode", False))

        from PyQt6.QtWidgets import QApplication
        from src.gui.main_window import MainWindow

        for widget in QApplication.topLevelWidgets():
            if isinstance(widget, MainWindow):
                widget.notify_active_model_changed()
                break

    def on_export_model(self):
        if not getattr(self, "is_hammerstein_mode", False):
            QMessageBox.warning(self, tr("Export Failed"), tr("Model export is only supported for Nonlinear Model modes."))
            return

        from src.core.hammerstein_model import get_active_model, has_active_model

        if not has_active_model():
            QMessageBox.warning(self, tr("Export Failed"), tr("No measurement data available to export."))
            return

        from PyQt6.QtWidgets import QFileDialog

        filepath, _ = QFileDialog.getSaveFileName(self, tr("Export Nonlinear Model"), "", tr("JSON Files (*.json)"))

        if not filepath:
            return

        try:
            data = get_active_model()
            save_hammerstein_model(filepath, data)
            QMessageBox.information(self, tr("Export Successful"), tr("Model exported successfully."))
        except Exception as e:
            logger.error("Failed to export Hammerstein model to %s", filepath, exc_info=True)
            QMessageBox.critical(self, tr("Export Failed"), tr("Failed to save nonlinear model: {0}").format(e))

    def on_block_calculated(self, block_idx, sweep_idx, f_mid, results, is_valid):
        with self.module.lock:
            self.module.measurement_queue.append((block_idx, sweep_idx, f_mid, results, is_valid))

    def on_sweep_finished(self, sweep_idx):
        try:
            with self.module.lock:
                if sweep_idx + 1 < self.module.averaging_count:
                    # Proceed to next sweep and reset filter states
                    self.module.current_sweep_idx += 1
                    self.module.current_block_idx = 0

                    if getattr(self, "is_hammerstein_mode", False):
                        N_avg = self.spin_averaging.value()
                        old_amp_idx = sweep_idx // N_avg
                        new_amp_idx = (sweep_idx + 1) // N_avg
                        if new_amp_idx != old_amp_idx:
                            self.accumulated_results.fill(0.0j)
                            self.block_counts.fill(0)
                        self.module.engine.output_amplitude = self.amplitudes[new_amp_idx]

                    self.module.engine.reset_filter_states()
                    self.module.state = "PLAYING"
                else:
                    self.module.state = "FINISHED"
        except Exception as e:
            logger.error(f"Error in on_sweep_finished: {e}", exc_info=True)
            self.module.state = "FINISHED"

        if self.module.state == "FINISHED":
            # Deactivate sweep button safely on main UI thread
            self.btn_toggle.setChecked(False)
            self.on_toggle_sweep(False)

    def apply_theme(self, theme_name=None):
        if not theme_name and hasattr(self.app, "theme_manager"):
            theme_name = self.app.theme_manager.get_current_theme()

        if theme_name == "system" and hasattr(self.app, "theme_manager"):
            theme_name = self.app.theme_manager.get_effective_theme()

        checked = self.btn_toggle.isChecked()

        if theme_name == "dark":
            button_style = (
                "QPushButton { background-color: #3a3a3a; color: white; border: 1px solid #555; border-radius: 4px; font-size: 12px; padding: 5px; }"
                "QPushButton:hover { background-color: #444444; }"
                "QPushButton:disabled { background-color: #222222; color: #777777; border: 1px solid #333; }"
            )
            self.export_btn.setStyleSheet(button_style)
            self.btn_calibrate.setStyleSheet(button_style)

            if checked:
                self.btn_toggle.setStyleSheet(
                    "QPushButton { background-color: #c62828; color: white; border: 1px solid #555; border-radius: 4px; font-weight: bold; font-size: 12px; padding: 5px; }"
                    "QPushButton:hover { background-color: #d32f2f; }"
                )
            else:
                self.btn_toggle.setStyleSheet(
                    "QPushButton { background-color: #2e7d32; color: white; border: 1px solid #555; border-radius: 4px; font-weight: bold; font-size: 12px; padding: 5px; }"
                    "QPushButton:hover { background-color: #388e3c; }"
                )
        else:
            button_style = (
                "QPushButton { background-color: #e0e0e0; color: black; border: 1px solid #ccc; border-radius: 4px; font-size: 12px; padding: 5px; }"
                "QPushButton:hover { background-color: #d5d5d5; }"
                "QPushButton:disabled { background-color: #f0f0f0; color: #aaaaaa; border: 1px solid #ddd; }"
            )
            self.export_btn.setStyleSheet(button_style)
            self.btn_calibrate.setStyleSheet(button_style)

            if checked:
                self.btn_toggle.setStyleSheet(
                    "QPushButton { background-color: #ffcccc; color: black; border: 1px solid #ccc; border-radius: 4px; font-weight: bold; font-size: 12px; padding: 5px; }"
                    "QPushButton:hover { background-color: #ffbbbb; }"
                )
            else:
                self.btn_toggle.setStyleSheet(
                    "QPushButton { background-color: #ccffcc; color: black; border: 1px solid #ccc; border-radius: 4px; font-weight: bold; font-size: 12px; padding: 5px; }"
                    "QPushButton:hover { background-color: #bbfebb; }"
                )

    def closeEvent(self, event):
        self.timer.stop()
        self.module.stop_analysis()
        if self.calib_thread and self.calib_thread.isRunning():
            self.calib_thread.wait()
        if hasattr(self, "calc_thread") and self.calc_thread and self.calc_thread.isRunning():
            self.calc_thread.stop()
            self.calc_thread.wait()
        super().closeEvent(event)
