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


class RealtimeSSSAnalyzer(MeasurementModule):
    def __init__(self, audio_engine: AudioEngine):
        self.audio_engine = audio_engine
        self.is_running = False
        self.lock = threading.Lock()

        # Default SSS parameters
        self.start_freq = 20.0
        self.end_freq = 20000.0
        self.sweep_duration = 30.0
        self.output_amplitude = 0.5
        self.max_harmonic = 3
        self.averaging_count = 1
        self.current_sweep_idx = 0
        self.analysis_cycles = 16.0
        self.num_meas_points = 500

        # Latency state
        self.latency_samples = 0.0

        # Channel routing
        self.output_channel = 2  # Stereo default (copies output to both L and R)
        self.signal_channel = 0  # 0: Left Input
        self.ref_channel = 1  # 1: Right Input
        self.input_mode = "Single"  # "Single" or "XFER"

        # Engine & DSP State
        self.engine = None
        self.callback_id = None
        self.current_block_idx = 0
        self.max_blocks = 0

        # Dynamic measurement data queues
        self.measurement_queue = deque()
        self.prevent_buffer_underrun = False
        self.input_queue = None
        self.state = "IDLE"  # "IDLE", "PLAYING", "WAITING", "FINISHED"

    @property
    def name(self) -> str:
        return "Real-time SSS Lockin Analyzer"

    @property
    def description(self) -> str:
        return tr("Real-time frequency response and distortion sweep using SSS and digital Lock-in.")

    def get_widget(self):
        return RealtimeSSSAnalyzerWidget(self)

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
                with self.lock:
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


class RealtimeSSSAnalyzerWidget(QWidget):
    def __init__(self, module: RealtimeSSSAnalyzer):
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

        # LEFT PANEL: Controls (compact width, scrollable to prevent height overflow)
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(QFrame.Shape.NoFrame)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        left_scroll.setFixedWidth(330)

        left_container = QWidget()
        left_panel = QVBoxLayout(left_container)
        left_panel.setContentsMargins(0, 0, 4, 0)
        left_panel.setSpacing(6)

        # Start / Stop Control Button
        self.btn_toggle = QPushButton(tr("Start Sweep"))
        self.btn_toggle.setCheckable(True)
        self.btn_toggle.clicked.connect(self.on_toggle_sweep)
        self.btn_toggle.setEnabled(self.module.latency_samples > 0.0)
        left_panel.addWidget(self.btn_toggle)

        # Export Button (visible/enabled after Hammerstein calibration)
        self.export_btn = QPushButton(tr("Export Model..."))
        self.export_btn.setEnabled(False)
        self.export_btn.clicked.connect(self.on_export_model)
        left_panel.addWidget(self.export_btn)

        left_tabs = QTabWidget()

        # 1. Sweep Parameters Tab
        settings_tab = QWidget()
        form = QFormLayout()
        form.setContentsMargins(6, 6, 6, 6)
        form.setSpacing(4)
        self.settings_form = form

        self.combo_meas_mode = QComboBox()
        self.combo_meas_mode.addItem(tr("Real-time Sweep (Default)"), "sweep")
        self.combo_meas_mode.addItem(tr("Hammerstein Model"), "hammerstein")
        self.combo_meas_mode.currentIndexChanged.connect(self.on_meas_mode_changed)
        form.addRow(tr("Sweep Mode:"), self.combo_meas_mode)

        self.spin_start_freq = QDoubleSpinBox()
        self.spin_start_freq.setRange(20.0, 20000.0)
        self.spin_start_freq.setValue(self.module.start_freq)
        self.spin_start_freq.setSuffix(" Hz")
        form.addRow(tr("Start Freq:"), self.spin_start_freq)

        self.spin_end_freq = QDoubleSpinBox()
        self.spin_end_freq.setRange(20.0, 20000.0)
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

        # 2. Routing Tab
        routing_tab = QWidget()
        r_form = QFormLayout()
        r_form.setContentsMargins(6, 6, 6, 6)
        r_form.setSpacing(4)

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

        routing_tab.setLayout(r_form)
        left_tabs.addTab(routing_tab, tr("Routing"))

        # 3. Advanced Tab
        advanced_tab = QWidget()
        adv_form = QFormLayout()
        adv_form.setContentsMargins(6, 6, 6, 6)
        adv_form.setSpacing(4)

        self.spin_analysis_cycles = QDoubleSpinBox()
        self.spin_analysis_cycles.setRange(2.0, 512.0)
        self.spin_analysis_cycles.setSingleStep(1.0)
        self.spin_analysis_cycles.setValue(self.module.analysis_cycles)
        self.spin_analysis_cycles.setSuffix(" cycles")
        adv_form.addRow(tr("Analysis Cycles:"), self.spin_analysis_cycles)

        self.spin_meas_points = QSpinBox()
        self.spin_meas_points.setRange(100, 5000)
        self.spin_meas_points.setSingleStep(100)
        self.spin_meas_points.setValue(self.module.num_meas_points)
        adv_form.addRow(tr("Meas Points:"), self.spin_meas_points)

        self.chk_prevent_buffer_underrun = QCheckBox(tr("Prevent Buffer Underrun"))
        self.chk_prevent_buffer_underrun.setChecked(self.module.prevent_buffer_underrun)
        adv_form.addRow(tr("Prevent Buffer Underrun:"), self.chk_prevent_buffer_underrun)

        advanced_tab.setLayout(adv_form)
        left_tabs.addTab(advanced_tab, tr("Advanced"))

        left_panel.addWidget(left_tabs)

        # Calibration Box
        calib_group = QGroupBox(tr("Latency Calibration"))
        calib_layout = QVBoxLayout()
        calib_layout.setContentsMargins(6, 6, 6, 6)
        calib_layout.setSpacing(4)

        self.btn_calibrate = QPushButton(tr("Calibrate Latency"))
        self.btn_calibrate.clicked.connect(self.on_calibrate_latency)
        calib_layout.addWidget(self.btn_calibrate)

        self.lbl_calib_status = QLabel(tr("Uncalibrated (0.0 ms)"))
        self.lbl_calib_status.setStyleSheet("color: #ffaa00; font-weight: bold;")
        calib_layout.addWidget(self.lbl_calib_status)

        calib_group.setLayout(calib_layout)
        left_panel.addWidget(calib_group)

        # Overview Stats
        stats_group = QGroupBox(tr("Overview"))
        stats_layout = QVBoxLayout()
        stats_layout.setContentsMargins(6, 6, 6, 6)

        self.lbl_progress = QLabel(tr("Sweep Progress: --"))
        stats_layout.addWidget(self.lbl_progress)

        self.lbl_current_freq = QLabel(tr("Current Freq: -- Hz"))
        stats_layout.addWidget(self.lbl_current_freq)

        stats_group.setLayout(stats_layout)
        left_panel.addWidget(stats_group)

        # Display Options
        display_group = QGroupBox(tr("Display Options"))
        display_layout = QVBoxLayout()
        display_layout.setContentsMargins(6, 6, 6, 6)
        display_layout.setSpacing(4)

        self.chk_relative = QCheckBox(tr("Show Relative to Fundamental"))
        self.chk_relative.setChecked(False)
        self.chk_relative.toggled.connect(self.redraw_plots)
        display_layout.addWidget(self.chk_relative)

        self.chk_unwrap = QCheckBox(tr("Unwrap Phase"))
        self.chk_unwrap.setChecked(False)
        self.chk_unwrap.toggled.connect(self.redraw_plots)
        display_layout.addWidget(self.chk_unwrap)

        self.lbl_smoothing = QLabel(tr("Graph Smoothing:"))
        self.combo_smoothing = QComboBox()
        self.combo_smoothing.addItem(tr("None"), "None")
        self.combo_smoothing.addItem(tr("Low Smoothing"), "Light")
        self.combo_smoothing.addItem(tr("Medium Smoothing"), "Medium")
        self.combo_smoothing.addItem(tr("High Smoothing"), "Heavy")
        self.combo_smoothing.setCurrentIndex(1)
        self.combo_smoothing.currentIndexChanged.connect(self.redraw_plots)
        display_layout.addWidget(self.lbl_smoothing)
        display_layout.addWidget(self.combo_smoothing)
        self.lbl_smoothing.setVisible(False)
        self.combo_smoothing.setVisible(False)

        display_group.setLayout(display_layout)
        left_panel.addWidget(display_group)

        left_panel.addStretch()

        left_scroll.setWidget(left_container)
        left_scroll.setMinimumHeight(150)  # Allow scroll area to shrink vertically
        layout.addWidget(left_scroll)

        # RIGHT PANEL: Tab Widget
        self.plot_tabs = QTabWidget()
        self.plot_tabs.setMinimumHeight(450)

        # Tab 1: Magnitude Response
        self.mag_tab = QWidget()
        mag_layout = QVBoxLayout(self.mag_tab)
        self.plot_mag = pg.PlotWidget(title=tr("Magnitude Response"))
        self.plot_mag.setMinimumHeight(150)
        self.plot_mag.setLabel("bottom", tr("Frequency"), units="Hz")
        self.plot_mag.setLabel("left", tr("Amplitude"), units="dBFS")
        self.plot_mag.setLogMode(x=True, y=False)
        self.plot_mag.showGrid(x=True, y=True)
        self.plot_mag.setYRange(-140, 10)
        mag_layout.addWidget(self.plot_mag)
        self.plot_tabs.addTab(self.mag_tab, tr("Magnitude Response"))

        # Tab 2: Phase Response
        self.phase_tab = QWidget()
        phase_layout = QVBoxLayout(self.phase_tab)
        self.plot_phase = pg.PlotWidget(title=tr("Phase Response"))
        self.plot_phase.setMinimumHeight(150)
        self.plot_phase.setLabel("bottom", tr("Frequency"), units="Hz")
        self.plot_phase.setLabel("left", tr("Phase"), units="deg")
        self.plot_phase.setLogMode(x=True, y=False)
        self.plot_phase.showGrid(x=True, y=True)
        self.plot_phase.setYRange(-180, 180)
        self.plot_phase.setXLink(self.plot_mag)
        phase_layout.addWidget(self.plot_phase)
        self.plot_tabs.addTab(self.phase_tab, tr("Phase Response"))

        # Tab 3: Impulse Responses (Kernels)
        self.kernel_tab = QWidget()
        kernel_layout = QVBoxLayout(self.kernel_tab)
        self.plot_kernel = pg.PlotWidget(title=tr("Impulse Responses (Kernels)"))
        self.plot_kernel.setMinimumHeight(150)
        self.plot_kernel.setLabel("bottom", tr("Time"), units="ms")
        self.plot_kernel.setLabel("left", tr("Normalized Amplitude"))
        self.plot_kernel.showGrid(x=True, y=True)
        kernel_layout.addWidget(self.plot_kernel)
        self.plot_tabs.addTab(self.kernel_tab, tr("Impulse Responses (Kernels)"))
        self.plot_tabs.setTabEnabled(2, False)  # Disabled by default

        # Create Plot Curves with distinct colors
        # Colors: H1: Cyan, H2: Green, H3: Yellow, H4: Purple, H5: Red
        self.colors = ["#00ffff", "#00ff00", "#ffff00", "#ff00ff", "#ff3333"]
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

        layout.addWidget(self.plot_tabs, 2)
        self.setLayout(layout)
        self.setMinimumSize(990, 620)

        # Set initial X range based on default sweep params
        x_min = min(self.module.start_freq, self.module.end_freq)
        x_max = max(self.module.start_freq, self.module.end_freq)
        self.plot_mag.setXRange(np.log10(x_min), np.log10(x_max), padding=0)

        # Sync settings on initialization
        self.on_meas_mode_changed(0)

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
            self.module.prevent_buffer_underrun = self.chk_prevent_buffer_underrun.isChecked()

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

            self.is_hammerstein_mode = (self.combo_meas_mode.currentData() == "hammerstein")
            if self.is_hammerstein_mode:
                self.num_amplitudes = self.spin_amp_steps.value()
                max_amp_db = self.spin_amplitude.value()
                max_amp = 10 ** (max_amp_db / 20.0)
                self.amplitudes = np.linspace(0.2, 1.0, self.num_amplitudes) * max_amp
                self.current_amp_idx = 0
                self.current_avg_idx = 0

                self.module.output_amplitude = self.amplitudes[0]
                self.module.averaging_count = self.num_amplitudes * self.spin_averaging.value()

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

            if self.is_hammerstein_mode:
                self.raw_responses = np.zeros((self.num_amplitudes, self.max_blocks, self.module.max_harmonic), dtype=complex)
                self.raw_counts = np.zeros((self.num_amplitudes, self.max_blocks), dtype=int)
                self.H_freqs = []
                self.kernels_time = []
                self.time_ms = []
                self.plot_kernel.clear()
                self.plot_tabs.setTabEnabled(2, False)

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

                if self.is_hammerstein_mode:
                    self.calculate_hammerstein_kernels()
                    self.redraw_plots()
            else:
                self.export_btn.setEnabled(False)

            self.btn_toggle.setText(tr("Start Sweep"))
            self.btn_calibrate.setEnabled(True)
            self.set_controls_enabled(True)

        self.apply_theme()

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
        self.spin_analysis_cycles.setEnabled(enabled)
        self.spin_meas_points.setEnabled(enabled)
        self.chk_prevent_buffer_underrun.setEnabled(enabled)

    def on_meas_mode_changed(self, index):
        is_ham = self.combo_meas_mode.currentData() == "hammerstein"
        self.spin_amp_steps.setVisible(is_ham)
        label = self.settings_form.labelForField(self.spin_amp_steps)
        if label:
            label.setVisible(is_ham)

        self.combo_smoothing.setVisible(is_ham)
        self.lbl_smoothing.setVisible(is_ham)

        self.plot_tabs.setTabEnabled(2, is_ham)
        self.redraw_plots()

    def update_plots(self):
        # Retrieve all pending samples from queue
        items = []
        with self.module.lock:
            while self.module.measurement_queue:
                items.append(self.module.measurement_queue.popleft())

        # 1. Process new items first to update block_counts and plot_freqs_array
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
            else:
                freq_text += "\n" + tr("Analysis Freq: -- Hz")
            self.lbl_current_freq.setText(freq_text)

        # 3. Redraw curves if there were new items
        if items:
            self.redraw_plots()

    def redraw_plots(self):
        # Update Plot Labels based on mode
        if self.chk_relative.isChecked():
            self.plot_mag.setLabel("left", tr("Relative Gain"), units="dB")
            self.plot_phase.setLabel("left", tr("Relative Phase"), units="deg")
        else:
            if self.module.input_mode == "XFER":
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

        # Check if we should draw the final Hammerstein kernels
        is_ham = getattr(self, "is_hammerstein_mode", False)
        has_kernels = len(getattr(self, "H_freqs", [])) > 0
        is_measuring = (self.module.state in {"PLAYING", "WAITING"})

        if is_ham and has_kernels and not is_measuring:
            # Draw Hammerstein Kernels
            sort_idx = np.argsort(x_data)
            x_data_sorted = x_data[sort_idx]
            smooth_level = self.combo_smoothing.currentData()

            for idx in range(len(self.H_freqs)):
                H_p = self.H_freqs[idx][valid_indices][sort_idx]
                mag_db = 20 * np.log10(np.abs(H_p) + 1e-12)
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

            self.plot_tabs.setTabEnabled(2, True)
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

            self.mag_curves[idx].setData(x_data, y_gain)
            self.phase_curves[idx].setData(x_data, y_phase)

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

        try:
            return savgol_filter(y_data, window_size, polyorder=2)
        except Exception as e:
            logger.warning("Smoothing failed: %s", e)
            return y_data

    def calculate_hammerstein_kernels(self):
        sample_rate = self.module.audio_engine.sample_rate
        nyquist = sample_rate / 2.0
        P = self.module.max_harmonic
        max_blocks = self.max_blocks

        # 1. Compute averaged responses for each amplitude
        avg_responses = np.zeros_like(self.raw_responses)
        for amp_idx in range(self.num_amplitudes):
            for block_idx in range(max_blocks):
                cnt = self.raw_counts[amp_idx, block_idx]
                if cnt > 0:
                    avg_responses[amp_idx, block_idx] = self.raw_responses[amp_idx, block_idx] / cnt

        # 2. Scale responses by amplitude and apply phase correction
        # To compensate for sine expansion phase offsets:
        # H1: 1.0, H2: 1j, H3: -1.0, H4: -1j, H5: 1.0
        phase_corrections = [1.0, 1j, -1.0, -1j, 1.0]
        R_array = self.amplitudes
        g_scaled = np.zeros_like(avg_responses)
        for amp_idx in range(self.num_amplitudes):
            amp = R_array[amp_idx]
            for p in range(P):
                val = avg_responses[amp_idx, :, p]
                if self.module.input_mode == "XFER":
                    g_scaled[amp_idx, :, p] = val * amp * phase_corrections[p]
                else:
                    g_scaled[amp_idx, :, p] = val * phase_corrections[p]

        g1 = g_scaled[:, :, 0]
        g2 = g_scaled[:, :, 1] if P >= 2 else np.zeros_like(g1)
        g3 = g_scaled[:, :, 2] if P >= 3 else np.zeros_like(g1)
        g4 = g_scaled[:, :, 3] if P >= 4 else np.zeros_like(g1)
        g5 = g_scaled[:, :, 4] if P >= 5 else np.zeros_like(g1)

        R2 = R_array**2
        R3 = R_array**3
        R4 = R_array**4
        R5 = R_array**5

        H5 = 16 * np.sum(g5 * R5[:, np.newaxis], axis=0) / np.sum(R_array**10) if P >= 5 else np.zeros(max_blocks, dtype=complex)
        H4 = 8 * np.sum(g4 * R4[:, np.newaxis], axis=0) / np.sum(R_array**8) if P >= 4 else np.zeros(max_blocks, dtype=complex)

        if P >= 5:
            g3_prime = g3 - (5 / 16) * H5[np.newaxis, :] * R5[:, np.newaxis]
        else:
            g3_prime = g3
        H3 = 4 * np.sum(g3_prime * R3[:, np.newaxis], axis=0) / np.sum(R_array**6) if P >= 3 else np.zeros(max_blocks, dtype=complex)

        if P >= 4:
            g2_prime = g2 - 0.5 * H4[np.newaxis, :] * R4[:, np.newaxis]
        else:
            g2_prime = g2
        H2 = 2 * np.sum(g2_prime * R2[:, np.newaxis], axis=0) / np.sum(R_array**4) if P >= 2 else np.zeros(max_blocks, dtype=complex)

        g1_prime = g1.copy()
        if P >= 3:
            g1_prime -= 0.75 * H3[np.newaxis, :] * R3[:, np.newaxis]
        if P >= 5:
            g1_prime -= 0.625 * H5[np.newaxis, :] * R5[:, np.newaxis]
        H1 = np.sum(g1_prime * R_array[:, np.newaxis], axis=0) / np.sum(R_array**2)

        self.H_freqs = [H1, H2, H3, H4, H5][:P]

        # 3. Apply frequency mapping to map H_p(f_0) measured at fundamental f_0 to physical harmonic frequency p * f_0
        # H_p_mapped(f) = H_p_raw(f / p)
        plot_freqs = self.plot_freqs_array
        valid_idx = np.where(plot_freqs > 0)[0]
        if len(valid_idx) > 0:
            sort_idx = np.argsort(plot_freqs[valid_idx])
            sorted_freqs = plot_freqs[valid_idx][sort_idx]

            H_mapped_list = []
            for p in range(len(self.H_freqs)):
                H_raw = self.H_freqs[p][valid_idx][sort_idx]
                f_lookups = sorted_freqs / (p + 1)

                # Interpolate real and imaginary parts to map from f_lookups to sorted_freqs
                real_mapped = np.interp(f_lookups, sorted_freqs, np.real(H_raw), left=np.nan, right=np.nan)
                imag_mapped = np.interp(f_lookups, sorted_freqs, np.imag(H_raw), left=np.nan, right=np.nan)

                H_mapped = real_mapped + 1j * imag_mapped
                H_mapped_list.append(H_mapped)

            # Apply Butterworth lowpass filter to higher order mapped kernels
            for p in range(len(self.H_freqs)):
                H_p = H_mapped_list[p]
                if p >= 1:
                    f_cut = min(20000.0, 1.15 * sample_rate / (2 * (p + 1)))
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

            H_real = np.interp(freqs_lin, sorted_freqs, np.real(H_p_clean), left=0.0, right=0.0)
            H_imag = np.interp(freqs_lin, sorted_freqs, np.imag(H_p_clean), left=0.0, right=0.0)
            H_lin = H_real + 1j * H_imag

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

        cache_data = {
            "metadata": {
                "module": self.module.name,
                "sample_rate": sample_rate,
                "num_amplitudes": self.num_amplitudes,
                "sweep_duration": self.module.sweep_duration,
                "start_freq": self.module.start_freq,
                "end_freq": self.module.end_freq,
                "input_mode": self.module.input_mode,
                "latency_sec": self.module.latency_samples / sample_rate,
                "ref_max": float(ref_max),
                "P": len(self.kernels_time),
                "noise_floor_dbfs": None,
            },
            "time_domain": {
                "time_ms": self.time_ms,
                "kernels": {
                    f"h{p+1}": self.kernels_time[p] for p in range(len(self.kernels_time))
                },
            },
            "frequency_domain": {
                "freqs": sorted_freqs,
                "magnitudes_db": {
                    f"h{p+1}": 20 * np.log10(np.abs(self.H_freqs[p][valid_idx][sort_idx]) + 1e-12)
                    for p in range(len(self.H_freqs))
                },
                "phases_deg": {
                    f"h{p+1}": np.degrees(np.angle(self.H_freqs[p][valid_idx][sort_idx]))
                    for p in range(len(self.H_freqs))
                },
            },
        }
        set_active_model(cache_data)
        self.export_btn.setEnabled(True)

        from PyQt6.QtWidgets import QApplication
        from src.gui.main_window import MainWindow
        for widget in QApplication.topLevelWidgets():
            if isinstance(widget, MainWindow):
                widget.notify_active_model_changed()
                break

    def on_export_model(self):
        from src.core.hammerstein_model import get_active_model, has_active_model
        if not has_active_model():
            QMessageBox.warning(self, tr("Export Failed"), tr("No measurement data available to export."))
            return

        from PyQt6.QtWidgets import QFileDialog

        filepath, _ = QFileDialog.getSaveFileName(
            self,
            tr("Export Hammerstein Model"),
            "",
            tr("JSON Files (*.json)")
        )

        if not filepath:
            return

        try:
            data = get_active_model()
            save_hammerstein_model(filepath, data)
            QMessageBox.information(
                self,
                tr("Export Successful"),
                tr("Model exported successfully.")
            )
        except Exception as e:
            logger.error("Failed to export Hammerstein model to %s", filepath, exc_info=True)
            QMessageBox.critical(
                self,
                tr("Export Failed"),
                tr("Failed to save Hammerstein model: {0}").format(e)
            )

    def on_block_calculated(self, block_idx, sweep_idx, f_mid, results, is_valid):
        with self.module.lock:
            self.module.measurement_queue.append((block_idx, sweep_idx, f_mid, results, is_valid))

    def on_sweep_finished(self, sweep_idx):
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
            if checked:
                self.btn_toggle.setStyleSheet(
                    "QPushButton { background-color: #c62828; color: white; border: 1px solid #555; border-radius: 4px; font-weight: bold; font-size: 13px; }"
                    "QPushButton:hover { background-color: #d32f2f; }"
                )
            else:
                self.btn_toggle.setStyleSheet(
                    "QPushButton { background-color: #2e7d32; color: white; border: 1px solid #555; border-radius: 4px; font-weight: bold; font-size: 13px; }"
                    "QPushButton:hover { background-color: #388e3c; }"
                )
        else:
            if checked:
                self.btn_toggle.setStyleSheet(
                    "QPushButton { background-color: #ffcccc; color: black; border: 1px solid #ccc; border-radius: 4px; font-weight: bold; font-size: 13px; }"
                    "QPushButton:hover { background-color: #ffbbbb; }"
                )
            else:
                self.btn_toggle.setStyleSheet(
                    "QPushButton { background-color: #ccffcc; color: black; border: 1px solid #ccc; border-radius: 4px; font-weight: bold; font-size: 13px; }"
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
