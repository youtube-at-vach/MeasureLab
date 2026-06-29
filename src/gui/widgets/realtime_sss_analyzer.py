import logging
import queue
import threading
from collections import deque
import numpy as np
import pyqtgraph as pg
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
    QFileDialog,
)

from src.core.audio_engine import AudioEngine
from src.core.localization import tr
from src.measurement_modules.base import MeasurementModule
from src.core.realtime_sss_core import RealtimeSSSEngine, measure_system_latency
from src.core.hammerstein_model import set_active_model, save_hammerstein_model

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
                            f_mid, results = self.engine.process_input_block(p_sig_in, p_block_idx, ref_in_block=p_ref_in)
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
        self.sweep_duration = 20.0
        self.output_amplitude = 0.5
        self.max_harmonic = 3
        self.averaging_count = 1
        self.current_sweep_idx = 0
        self.analysis_cycles = 16.0
        self.num_meas_points = 500

        # Hammerstein parameters
        self.meas_mode = "Harmonics"  # "Harmonics" or "Hammerstein"
        self.num_amplitudes = 5
        self.min_amplitude_db = -30.0
        self.current_amplitude_idx = 0
        self.accumulated_sweeps = None
        self.amplitude_steps = []

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
        self.current_amplitude_idx = 0
        self.measurement_queue.clear()

        # Determine start amplitude based on mode
        start_amp = self.output_amplitude
        if self.meas_mode == "Hammerstein" and len(self.amplitude_steps) > 0:
            start_amp = self.amplitude_steps[0]

        # Initialize core engine
        self.engine = RealtimeSSSEngine(
            sample_rate=self.audio_engine.sample_rate,
            sweep_duration=self.sweep_duration,
            start_freq=self.start_freq,
            end_freq=self.end_freq,
            output_amplitude=start_amp,
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

        # Stored data for Hammerstein model separation
        self.separated_freqs = None
        self.separated_H_mag = []
        self.separated_H_phase = []
        self.separated_kernels_time = []
        self.separated_time_ms = None

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
        left_panel.addWidget(self.btn_toggle)

        left_tabs = QTabWidget()

        # 1. Sweep Parameters Tab
        settings_tab = QWidget()
        form = QFormLayout()
        form.setContentsMargins(6, 6, 6, 6)
        form.setSpacing(4)

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

        self.combo_meas_mode = QComboBox()
        self.combo_meas_mode.addItem(tr("Harmonics Response"), "Harmonics")
        self.combo_meas_mode.addItem(tr("Hammerstein Model"), "Hammerstein")
        meas_idx = 1 if self.module.meas_mode == "Hammerstein" else 0
        self.combo_meas_mode.setCurrentIndex(meas_idx)
        self.combo_meas_mode.currentIndexChanged.connect(self.on_meas_mode_changed)
        form.addRow(tr("Measurement Mode:"), self.combo_meas_mode)

        self.spin_amp_steps = QSpinBox()
        self.spin_amp_steps.setRange(2, 10)
        self.spin_amp_steps.setValue(self.module.num_amplitudes)
        form.addRow(tr("Amplitude Steps:"), self.spin_amp_steps)

        self.spin_min_amp = QDoubleSpinBox()
        self.spin_min_amp.setRange(-60.0, 0.0)
        self.spin_min_amp.setValue(self.module.min_amplitude_db)
        self.spin_min_amp.setSuffix(" dBFS")
        form.addRow(tr("Min Amplitude:"), self.spin_min_amp)

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
        self.spin_analysis_cycles.setRange(2.0, 128.0)
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

        self.btn_export = QPushButton(tr("Export Model..."))
        self.btn_export.setEnabled(False)
        self.btn_export.clicked.connect(self.on_export_model)
        stats_layout.addWidget(self.btn_export)

        stats_group.setLayout(stats_layout)
        left_panel.addWidget(stats_group)

        left_panel.addStretch()

        left_scroll.setWidget(left_container)
        left_scroll.setMinimumHeight(150)  # Allow scroll area to shrink vertically
        layout.addWidget(left_scroll)

        # RIGHT PANEL: QTabWidget for Domain switching
        self.right_tabs = QTabWidget()

        # Plot 1: Magnitude Response (Live Sweep)
        self.plot_mag = pg.PlotWidget(title=tr("Magnitude Response"))
        self.plot_mag.setMinimumHeight(150)
        self.plot_mag.setLabel("bottom", tr("Frequency"), units="Hz")
        self.plot_mag.setLabel("left", tr("Amplitude"), units="dBFS")
        self.plot_mag.setLogMode(x=True, y=False)
        self.plot_mag.showGrid(x=True, y=True)
        self.plot_mag.setYRange(-140, 10)

        # Plot 2: Phase Response (Live Sweep)
        self.plot_phase = pg.PlotWidget(title=tr("Phase Response"))
        self.plot_phase.setMinimumHeight(150)
        self.plot_phase.setLabel("bottom", tr("Frequency"), units="Hz")
        self.plot_phase.setLabel("left", tr("Phase"), units="deg")
        self.plot_phase.setLogMode(x=True, y=False)
        self.plot_phase.showGrid(x=True, y=True)
        self.plot_phase.setYRange(-180, 180)
        self.plot_phase.setXLink(self.plot_mag)

        # Plot 4: Hammerstein Magnitude Response (Separated Kernels Freq)
        self.plot_ham_mag = pg.PlotWidget(title=tr("Hammerstein Magnitude Response"))
        self.plot_ham_mag.setMinimumHeight(150)
        self.plot_ham_mag.setLabel("bottom", tr("Frequency"), units="Hz")
        self.plot_ham_mag.setLabel("left", tr("Gain"), units="dB")
        self.plot_ham_mag.setLogMode(x=True, y=False)
        self.plot_ham_mag.showGrid(x=True, y=True)
        self.plot_ham_mag.setYRange(-140, 10)

        # Plot 5: Hammerstein Phase Response (Separated Kernels Freq)
        self.plot_ham_phase = pg.PlotWidget(title=tr("Hammerstein Phase Response"))
        self.plot_ham_phase.setMinimumHeight(150)
        self.plot_ham_phase.setLabel("bottom", tr("Frequency"), units="Hz")
        self.plot_ham_phase.setLabel("left", tr("Phase"), units="deg")
        self.plot_ham_phase.setLogMode(x=True, y=False)
        self.plot_ham_phase.showGrid(x=True, y=True)
        self.plot_ham_phase.setYRange(-180, 180)
        self.plot_ham_phase.setXLink(self.plot_ham_mag)

        # Plot 3: Time Domain Kernels
        self.plot_time = pg.PlotWidget(title=tr("Hammerstein Time Kernels (h1 - h5)"))
        self.plot_time.setMinimumHeight(300)
        self.plot_time.setLabel("bottom", tr("Time"), units="ms")
        self.plot_time.setLabel("left", tr("Amplitude"))
        self.plot_time.showGrid(x=True, y=True)
        self.plot_time.setYRange(-1.1, 1.1)

        # Tab 1: Frequency Domain (Live Sweep)
        freq_widget = QWidget()
        freq_layout = QVBoxLayout(freq_widget)
        freq_layout.setContentsMargins(0, 0, 0, 0)
        freq_layout.setSpacing(4)
        freq_layout.addWidget(self.plot_mag)
        freq_layout.addWidget(self.plot_phase)
        self.right_tabs.addTab(freq_widget, tr("Frequency Domain (Live)"))

        # Tab 2: Hammerstein Frequency Domain (Separated Kernels)
        ham_freq_widget = QWidget()
        ham_freq_layout = QVBoxLayout(ham_freq_widget)
        ham_freq_layout.setContentsMargins(0, 0, 0, 0)
        ham_freq_layout.setSpacing(4)
        ham_freq_layout.addWidget(self.plot_ham_mag)
        ham_freq_layout.addWidget(self.plot_ham_phase)
        self.right_tabs.addTab(ham_freq_widget, tr("Hammerstein (Freq)"))

        # Tab 3: Time Domain (Kernels)
        time_widget = QWidget()
        time_layout = QVBoxLayout(time_widget)
        time_layout.setContentsMargins(0, 0, 0, 0)
        time_layout.setSpacing(4)
        time_layout.addWidget(self.plot_time)
        self.right_tabs.addTab(time_widget, tr("Time Domain (Kernels)"))

        # Create Plot Curves with distinct colors
        # Colors: H1: Cyan, H2: Green, H3: Yellow, H4: Purple, H5: Red
        self.colors = ["#00ffff", "#00ff00", "#ffff00", "#ff00ff", "#ff3333"]
        self.mag_curves = []
        self.phase_curves = []
        self.ham_mag_curves = []
        self.ham_phase_curves = []
        self.time_curves = []

        # Add legends
        self.plot_mag.addLegend(offset=(10, 10))
        self.plot_ham_mag.addLegend(offset=(10, 10))
        self.plot_time.addLegend(offset=(10, 10))

        for idx in range(5):
            lbl = tr("Fundamental") if idx == 0 else tr("{0}th Harmonic").format(idx + 1)
            mag_c = self.plot_mag.plot(pen=self.colors[idx], name=lbl)
            phase_c = self.plot_phase.plot(pen=self.colors[idx])
            self.mag_curves.append(mag_c)
            self.phase_curves.append(phase_c)

            ham_mag_c = self.plot_ham_mag.plot(pen=self.colors[idx], name=lbl)
            ham_phase_c = self.plot_ham_phase.plot(pen=self.colors[idx])
            self.ham_mag_curves.append(ham_mag_c)
            self.ham_phase_curves.append(ham_phase_c)

            lbl_time = tr("Fundamental (h1)") if idx == 0 else tr("Kernel h{0}").format(idx + 1)
            time_c = self.plot_time.plot(pen=self.colors[idx], name=lbl_time)
            self.time_curves.append(time_c)

        layout.addWidget(self.right_tabs, 2)
        self.setLayout(layout)
        self.setMinimumSize(990, 620)

        # Set initial X range based on default sweep params
        x_min = min(self.module.start_freq, self.module.end_freq)
        x_max = max(self.module.start_freq, self.module.end_freq)
        self.plot_mag.setXRange(np.log10(x_min), np.log10(x_max), padding=0)
        self.plot_ham_mag.setXRange(np.log10(x_min), np.log10(x_max), padding=0)

        self.on_meas_mode_changed()

    def on_meas_mode_changed(self):
        is_hammerstein = (self.combo_meas_mode.currentData() == "Hammerstein")
        self.spin_amp_steps.setEnabled(is_hammerstein)
        self.spin_min_amp.setEnabled(is_hammerstein)

        # Tab index: 0 is Live, 1 is Hammerstein (Freq), 2 is Time Domain (Kernels)
        self.right_tabs.setTabVisible(1, is_hammerstein)
        self.right_tabs.setTabVisible(2, is_hammerstein)

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
        self.btn_toggle.setEnabled(True)

    def on_calibration_error(self, err_msg):
        self.lbl_calib_status.setText(tr("Calibration Error!"))
        self.lbl_calib_status.setStyleSheet("color: #ff3333; font-weight: bold;")
        self.btn_calibrate.setEnabled(True)
        self.btn_toggle.setEnabled(True)

    def on_toggle_sweep(self, checked):
        if checked:
            # Sync parameters from GUI
            self.module.meas_mode = self.combo_meas_mode.currentData()
            self.module.num_amplitudes = self.spin_amp_steps.value()
            self.module.min_amplitude_db = self.spin_min_amp.value()

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

            # Update Plot Labels based on mode
            if self.module.input_mode == "XFER":
                self.plot_mag.setLabel("left", tr("Gain"), units="dB")
            else:
                self.plot_mag.setLabel("left", tr("Amplitude"), units="dBFS")

            # Set X range based on current sweep params
            start_val = self.module.start_freq
            end_val = self.module.end_freq
            x_min = min(start_val, end_val)
            x_max = max(start_val, end_val)
            self.plot_mag.setXRange(np.log10(x_min), np.log10(x_max), padding=0)
            self.plot_ham_mag.setXRange(np.log10(x_min), np.log10(x_max), padding=0)

            # Clear plot curves
            for idx in range(5):
                self.mag_curves[idx].setData([], [])
                self.phase_curves[idx].setData([], [])
                self.ham_mag_curves[idx].setData([], [])
                self.ham_phase_curves[idx].setData([], [])
                self.time_curves[idx].setData([], [])

            # Reset tabs to frequency domain
            self.right_tabs.setCurrentIndex(0)

            # Pre-compute amplitude steps for Hammerstein mode
            if self.module.meas_mode == "Hammerstein":
                max_amp = self.module.output_amplitude
                min_amp = 10 ** (self.module.min_amplitude_db / 20.0)
                self.module.amplitude_steps = np.linspace(min_amp, max_amp, self.module.num_amplitudes).tolist()
                self.module.current_amplitude_idx = 0
            else:
                self.module.amplitude_steps = []
                self.module.current_amplitude_idx = 0

            self.btn_toggle.setText(tr("Stop Sweep"))
            self.btn_calibrate.setEnabled(False)
            self.set_controls_enabled(False)
            self.btn_export.setEnabled(False)

            self.module.start_analysis()

            # Initialize accumulated arrays
            self.max_blocks = self.module.max_blocks
            self.accumulated_results = np.zeros((self.max_blocks, 5), dtype=complex)
            self.block_counts = np.zeros(self.max_blocks, dtype=int)
            self.plot_freqs_array = np.zeros(self.max_blocks)
            self.current_analysis_freq = None

            # Allocate 3D buffer for Hammerstein sweeps
            if self.module.meas_mode == "Hammerstein":
                self.module.accumulated_sweeps = np.zeros(
                    (self.module.num_amplitudes, self.max_blocks, 5),
                    dtype=complex
                )

            # Spawn calculation thread (always asynchronous)
            self.calc_thread = SSSCalculationThread(
                self.module.engine,
                self.module.input_queue,
                prevent_underrun=self.module.prevent_buffer_underrun
            )
            self.calc_thread.block_calculated.connect(self.on_block_calculated)
            self.calc_thread.sweep_finished.connect(self.on_sweep_finished)
            self.calc_thread.start()

            self.timer.start()
        else:
            was_finished = (self.module.state == "FINISHED")
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

            # If the sweep completed successfully, force UI to show 100% progress and final frequency
            if was_finished:
                total_sweeps = self.module.averaging_count
                if self.module.meas_mode == "Hammerstein":
                    total_sweeps *= self.module.num_amplitudes

                progress_text = tr("Sweep (Audio): {0:.1f}% (Sweep {1}/{2})").format(
                    100.0,
                    total_sweeps,
                    total_sweeps
                )
                progress_text += "\n" + tr("Analysis: {0:.1f}%").format(100.0)
                self.lbl_progress.setText(progress_text)

                freq_text = tr("Audio Freq: {0:.1f} Hz").format(self.module.end_freq)
                freq_text += "\n" + tr("Analysis Freq: {0:.1f} Hz").format(self.module.end_freq)
                self.lbl_current_freq.setText(freq_text)

            self.btn_toggle.setText(tr("Start Sweep"))
            self.btn_calibrate.setEnabled(True)
            self.set_controls_enabled(True)

        self.apply_theme()

    def set_controls_enabled(self, enabled):
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

        self.combo_meas_mode.setEnabled(enabled)
        if enabled:
            self.on_meas_mode_changed()
        else:
            self.spin_amp_steps.setEnabled(False)
            self.spin_min_amp.setEnabled(False)

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

        for block_idx, _sweep_idx, f_mid, results, is_valid in items:
            if is_valid and block_idx < self.max_blocks:
                if f_min <= f_mid <= f_max:
                    n_harm = min(len(results), 5)
                    # Accumulate complex values
                    self.accumulated_results[block_idx, :n_harm] += results[:n_harm]
                    self.block_counts[block_idx] += 1
                    self.plot_freqs_array[block_idx] = f_mid
                    latest_f_mid = f_mid
                    self.current_analysis_freq = latest_f_mid

        # 2. Display progress info (always run to update audio capture progress, even if items is empty)
        if self.module.engine and self.module.engine.sweep_samples > 0:
            if self.module.meas_mode == "Hammerstein":
                total_sweeps = self.module.averaging_count * self.module.num_amplitudes
                current_sweep_num = self.module.current_amplitude_idx * self.module.averaging_count + self.module.current_sweep_idx + 1

                # Audio capture progress
                audio_blocks = (self.module.current_amplitude_idx * self.module.averaging_count + self.module.current_sweep_idx) * self.max_blocks + self.module.current_block_idx
                audio_blocks = min(audio_blocks, self.max_blocks * total_sweeps)
                audio_pct = (audio_blocks / (self.max_blocks * total_sweeps)) * 100.0

                # Calculation progress
                calc_blocks = self.module.current_amplitude_idx * self.module.averaging_count * self.max_blocks + np.sum(self.block_counts)
                calc_blocks = min(calc_blocks, self.max_blocks * total_sweeps)
                calc_pct = (calc_blocks / (self.max_blocks * total_sweeps)) * 100.0
            else:
                total_sweeps = self.module.averaging_count
                current_sweep_num = self.module.current_sweep_idx + 1

                audio_blocks = self.module.current_sweep_idx * self.max_blocks + self.module.current_block_idx
                audio_blocks = min(audio_blocks, self.max_blocks * total_sweeps)
                audio_pct = (audio_blocks / (self.max_blocks * total_sweeps)) * 100.0

                calc_blocks = np.sum(self.block_counts)
                calc_blocks = min(calc_blocks, self.max_blocks * total_sweeps)
                calc_pct = (calc_blocks / (self.max_blocks * total_sweeps)) * 100.0

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
                        if isinstance(val, (int, float, np.floating, np.integer)) and not hasattr(val, "_mock_return_value"):
                            audio_freq = float(val)
                    except Exception as e:
                        logger.debug(f"Failed to evaluate sweep frequency: {e}")

            # Format label text
            progress_text = tr("Sweep (Audio): {0:.1f}% (Sweep {1}/{2})").format(
                audio_pct,
                min(current_sweep_num, total_sweeps),
                total_sweeps
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
        if not items:
            return

        valid_indices = np.where(self.block_counts > 0)[0]
        if len(valid_indices) == 0:
            return

        # Hammerstein測定中のリアルタイムでの高調波表示
        x_data = self.plot_freqs_array[valid_indices]

        # Redraw
        for idx in range(self.module.max_harmonic):
            counts = self.block_counts[valid_indices]
            avg_complex = self.accumulated_results[valid_indices, idx] / counts

            # Compute amplitude in dBFS
            amp = np.abs(avg_complex)
            y_gain = 20 * np.log10(amp + 1e-15)

            # Compute phase in degrees
            y_phase = np.degrees(np.angle(avg_complex))

            self.mag_curves[idx].setData(x_data, y_gain)
            self.phase_curves[idx].setData(x_data, y_phase)

    def on_block_calculated(self, block_idx, sweep_idx, f_mid, results, is_valid):
        with self.module.lock:
            self.module.measurement_queue.append((block_idx, sweep_idx, f_mid, results, is_valid))

    def on_sweep_finished(self, sweep_idx):
        with self.module.lock:
            # Process any remaining calculation blocks from the queue first.
            # This ensures that the accumulated results for the completed sweep
            # are fully updated before we save them or clear the buffers.
            f_min = min(self.module.start_freq, self.module.end_freq)
            f_max = max(self.module.start_freq, self.module.end_freq)
            while self.module.measurement_queue:
                block_idx, _, f_mid, results, is_valid = self.module.measurement_queue.popleft()
                if is_valid and block_idx < self.max_blocks:
                    if f_min <= f_mid <= f_max:
                        n_harm = min(len(results), 5)
                        self.accumulated_results[block_idx, :n_harm] += results[:n_harm]
                        self.block_counts[block_idx] += 1
                        self.plot_freqs_array[block_idx] = f_mid
                        self.current_analysis_freq = f_mid

            if sweep_idx + 1 < self.module.averaging_count:
                # Proceed to next sweep and reset filter states
                self.module.current_sweep_idx += 1
                self.module.current_block_idx = 0
                self.module.engine.reset_filter_states()
                self.module.state = "PLAYING"
            else:
                # Average for this amplitude step completed
                if self.module.meas_mode == "Hammerstein":
                    j = self.module.current_amplitude_idx
                    counts = np.clip(self.block_counts, 1, None)
                    avg_results = self.accumulated_results / counts[:, None]
                    avg_results[self.block_counts == 0] = 0.0j
                    self.module.accumulated_sweeps[j] = avg_results

                    # Reset accumulated arrays for the next amplitude step
                    self.accumulated_results.fill(0.0)
                    self.block_counts.fill(0)

                    if self.module.current_amplitude_idx + 1 < self.module.num_amplitudes:
                        # Proceed to the next amplitude step
                        self.module.current_amplitude_idx += 1
                        self.module.current_sweep_idx = 0
                        self.module.current_block_idx = 0

                        next_amp = self.module.amplitude_steps[self.module.current_amplitude_idx]
                        self.module.engine.output_amplitude = next_amp
                        self.module.engine.prepare_sweep()
                        self.module.state = "PLAYING"
                    else:
                        self.module.state = "FINISHED"
                else:
                    self.module.state = "FINISHED"

        if self.module.state == "FINISHED":
            # Deactivate sweep button safely on main UI thread
            # This triggers on_toggle_sweep(False) which stops calculations and runs final update_plots()
            self.btn_toggle.setChecked(False)
            self.on_toggle_sweep(False)

            # Apply Hammerstein kernel separation if selected
            if self.module.meas_mode == "Hammerstein":
                self.perform_hammerstein_separation()

    def perform_hammerstein_separation(self):
        try:
            max_blocks = self.max_blocks
            max_harm = min(self.module.max_harmonic, 5)
            sample_rate = self.module.audio_engine.sample_rate

            # shape: (num_amplitudes, max_blocks, max_harmonic)
            G = self.module.accumulated_sweeps[:, :max_blocks, :max_harm]
            R = np.array(self.module.amplitude_steps)

            H_f = np.zeros((max_harm, max_blocks), dtype=complex)

            R2 = R**2
            R3 = R**3
            R4 = R**4
            R5 = R**5

            # 5次 (harm_idx = 4)
            if max_harm >= 5:
                H_f[4] = 16.0 * np.sum(G[:, :, 4] * R5[:, np.newaxis], axis=0) / np.sum(R**10)

            # 4次 (harm_idx = 3)
            if max_harm >= 4:
                H_f[3] = 8.0 * np.sum(G[:, :, 3] * R4[:, np.newaxis], axis=0) / np.sum(R**8)

            # 3次 (harm_idx = 2)
            if max_harm >= 3:
                g3_prime = G[:, :, 2].copy()
                if max_harm >= 5:
                    g3_prime -= (5.0 / 16.0) * H_f[4][np.newaxis, :] * R5[:, np.newaxis]
                H_f[2] = 4.0 * np.sum(g3_prime * R3[:, np.newaxis], axis=0) / np.sum(R**6)

            # 2次 (harm_idx = 1)
            if max_harm >= 2:
                g2_prime = G[:, :, 1].copy()
                if max_harm >= 4:
                    g2_prime -= 0.5 * H_f[3][np.newaxis, :] * R4[:, np.newaxis]
                H_f[1] = 2.0 * np.sum(g2_prime * R2[:, np.newaxis], axis=0) / np.sum(R**4)

            # 1次 (harm_idx = 0)
            if max_harm >= 1:
                g1_prime = G[:, :, 0].copy()
                if max_harm >= 3:
                    g1_prime -= 0.75 * H_f[2][np.newaxis, :] * R3[:, np.newaxis]
                if max_harm >= 5:
                    g1_prime -= 0.625 * H_f[4][np.newaxis, :] * R5[:, np.newaxis]
                H_f[0] = np.sum(g1_prime * R[:, np.newaxis], axis=0) / np.sum(R2)

            # Calculate frequency response for valid indices
            # Find which blocks were actually populated during the sweep
            valid_indices = np.where(self.plot_freqs_array > 0)[0]
            if len(valid_indices) == 0:
                return

            x_freqs = self.plot_freqs_array[valid_indices]
            self.separated_freqs = x_freqs
            self.separated_H_mag = []
            self.separated_H_phase = []

            for p in range(max_harm):
                H_p = H_f[p, valid_indices]
                amp = np.abs(H_p)
                mag_db = 20 * np.log10(amp + 1e-15)
                phase_deg = np.degrees(np.unwrap(np.angle(H_p)))

                self.separated_H_mag.append(mag_db)
                self.separated_H_phase.append(phase_deg)

                # Update Frequency curves with separated Hammerstein kernels
                self.ham_mag_curves[p].setData(x_freqs, mag_db)
                self.ham_phase_curves[p].setData(x_freqs, phase_deg)

            # --- Time Domain Kernel Computation ---
            # Interpolate from log-spaced sweep points to a linear grid for IFFT
            N_fft = 2048
            N_rfft = N_fft // 2 + 1
            freqs_linear = np.linspace(0, sample_rate / 2.0, N_rfft)

            self.separated_kernels_time = []
            gate_pre = N_fft // 4

            for p in range(max_harm):
                H_p = H_f[p, valid_indices]

                # Perform linear interpolation on complex components (real & imag)
                H_real_interp = np.interp(freqs_linear, x_freqs, np.real(H_p), left=0.0, right=0.0)
                H_imag_interp = np.interp(freqs_linear, x_freqs, np.imag(H_p), left=0.0, right=0.0)
                H_interp = H_real_interp + 1j * H_imag_interp

                # Bandpass window (Tukey style) to prevent Gibbs ringing
                f_min = min(self.module.start_freq, self.module.end_freq)
                f_max = max(self.module.start_freq, self.module.end_freq)
                window = np.ones(N_rfft)

                # Fade in low frequencies
                fade_low_width = int(np.count_nonzero(freqs_linear < f_min))
                if fade_low_width > 0:
                    window[:fade_low_width] = 0.5 * (1.0 - np.cos(np.pi * np.arange(fade_low_width) / fade_low_width))

                # Fade out high frequencies
                fade_high_mask = freqs_linear > f_max
                window[fade_high_mask] = 0.0

                H_interp *= window

                # IFFT to obtain the time domain kernel
                h_p = np.fft.irfft(H_interp, n=N_fft)

                # Roll to center the negative and positive time parts around peak
                h_p_shifted = np.roll(h_p, gate_pre)
                self.separated_kernels_time.append(h_p_shifted)

                # Update plot curve
                self.time_curves[p].setData((np.arange(N_fft) - gate_pre) / sample_rate * 1000.0, h_p_shifted)

            self.separated_time_ms = (np.arange(N_fft) - gate_pre) / sample_rate * 1000.0

            # Switch right tab to Time Domain for user confirmation
            self.right_tabs.setCurrentIndex(1)

            # Build and cache active model data
            model_data = self._build_model_data()
            if model_data:
                set_active_model(model_data)
                self.btn_export.setEnabled(True)
        except Exception as e:
            logger.error(f"Error in Hammerstein separation: {e}", exc_info=True)

    def _build_model_data(self) -> dict | None:
        if self.separated_freqs is None or len(self.separated_H_mag) == 0:
            return None
        max_harm = len(self.separated_H_mag)

        # Build standard model format
        return {
            "metadata": {
                "sample_rate": self.module.audio_engine.sample_rate,
                "P": max_harm,
                "start_freq": self.module.start_freq,
                "end_freq": self.module.end_freq,
                "sweep_duration": self.module.sweep_duration,
                "output_amplitude_dbfs": 20 * np.log10(self.module.output_amplitude),
                "input_mode": self.module.input_mode,
            },
            "time_domain": {
                "time_ms": self.separated_time_ms.tolist(),
                "kernels": {
                    f"h{p+1}": self.separated_kernels_time[p].tolist() for p in range(max_harm)
                }
            },
            "frequency_domain": {
                "freqs": self.separated_freqs.tolist(),
                "magnitudes_db": {
                    f"h{p+1}": self.separated_H_mag[p].tolist() for p in range(max_harm)
                },
                "phases_deg": {
                    f"h{p+1}": self.separated_H_phase[p].tolist() for p in range(max_harm)
                }
            }
        }

    def on_export_model(self):
        model_data = self._build_model_data()
        if not model_data:
            QMessageBox.warning(self, tr("Export Warning"), tr("No Hammerstein model data available to export."))
            return

        import os

        filepath, _ = QFileDialog.getSaveFileName(
            self,
            tr("Export Hammerstein Model"),
            "",
            "JSON Files (*.json)"
        )
        if not filepath:
            return

        try:
            save_hammerstein_model(filepath, model_data)
            QMessageBox.information(
                self,
                tr("Export Complete"),
                tr("Successfully exported Hammerstein model to:\n{0}").format(os.path.basename(filepath))
            )
        except Exception as e:
            logger.error("Failed to export Hammerstein model to %s: %s", filepath, e, exc_info=True)
            QMessageBox.critical(
                self,
                tr("Export Error"),
                tr("Failed to save model file:\n{0}").format(str(e))
            )

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
