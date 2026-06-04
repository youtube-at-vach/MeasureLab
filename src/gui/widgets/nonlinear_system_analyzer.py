import logging
import threading
import time
import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import QObject, QThread, pyqtSignal, Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
    QMessageBox,
    QSlider,
    QGridLayout,
)
from scipy.signal import (
    chirp as signal_chirp,
    fftconvolve,
    savgol_filter,
)

from src.core.audio_engine import AudioEngine
from src.core.localization import tr
from src.measurement_modules.base import MeasurementModule
from src.gui.widgets.comparable_interface import ComparableWidgetInterface
from src.core.nonlinear_analyzer_core import (
    generate_sss_and_inverse,
    process_amplitude_responses,
    deconvolve_signal,
)

logger = logging.getLogger(__name__)


class NonlinearSystemAnalyzerSignals(QObject):
    update_plot = pyqtSignal(object, dict, dict)  # freqs, magnitudes_db_dict, phases_deg_dict
    update_kernels = pyqtSignal(object, list)  # time_ms, list of kernels [h1, h2, h3, h4, h5]
    sweep_finished = pyqtSignal()
    progress = pyqtSignal(int)
    latency_result = pyqtSignal(float)
    error = pyqtSignal(str)


class PlayRecSession:
    """Helper to run a synchronous play/record session via AudioEngine."""

    def __init__(self, audio_engine, output_data, input_channels=2):
        self.audio_engine = audio_engine
        self.output_data = output_data
        self.total_frames = len(output_data)
        self.input_channels = input_channels
        self.input_data = np.zeros((self.total_frames, input_channels), dtype=np.float32)
        self.current_frame = 0
        self.is_complete = False
        self.callback_id = None
        self.lock = threading.Lock()
        self.completion_event = threading.Event()
        self.error = None

    def start(self):
        self.callback_id = self.audio_engine.register_callback(self._callback)
        if self.audio_engine.stream is None and not getattr(self.audio_engine, "offline_mode", False):
            self.error = tr("Audio stream failed to start. Please check audio device settings.")
            self.is_complete = True
            self.completion_event.set()

    def stop(self):
        if self.callback_id is not None:
            self.audio_engine.unregister_callback(self.callback_id)
            self.callback_id = None

    def wait(self, timeout=None):
        completed = self.completion_event.wait(timeout)
        if not completed:
            self.error = tr("Audio playback timed out. Audio device may have stopped responding.")
        if self.error:
            raise RuntimeError(str(self.error))

    def _callback(self, indata, outdata, frames, time, status):
        with self.lock:
            if self.is_complete:
                outdata.fill(0)
                return

            try:
                remaining = self.total_frames - self.current_frame
                chunk = min(frames, remaining)

                # Playback
                ch_out = min(outdata.shape[1], self.output_data.shape[1])
                outdata[:chunk, :ch_out] = self.output_data[self.current_frame : self.current_frame + chunk, :ch_out]
                if ch_out < outdata.shape[1]:
                    outdata[:chunk, ch_out:] = 0
                if chunk < frames:
                    outdata[chunk:, :] = 0

                # Record
                if indata.shape[1] > 0:
                    ch_to_copy = min(self.input_channels, indata.shape[1])
                    self.input_data[self.current_frame : self.current_frame + chunk, :ch_to_copy] = indata[
                        :chunk, :ch_to_copy
                    ]

                self.current_frame += chunk

                if self.current_frame >= self.total_frames:
                    self.is_complete = True
                    self.completion_event.set()
            except Exception as e:
                self.error = f"Audio Callback Error: {e}"
                self.is_complete = True
                self.completion_event.set()


class NonlinearSweepWorker(QThread):
    def __init__(self, analyzer):
        super().__init__()
        self.analyzer = analyzer
        self.is_running = True

    def run(self):
        try:
            self.analyzer._execute_measurement(self)
        except Exception as e:
            logger.error("NonlinearSweepWorker Error: %s", e, exc_info=True)
            self.analyzer.signals.error.emit(str(e))
        finally:
            self.analyzer.signals.sweep_finished.emit()

    def stop(self):
        self.is_running = False


class LatencyCalWorker(QThread):
    def __init__(self, analyzer):
        super().__init__()
        self.analyzer = analyzer

    def run(self):
        try:
            self.analyzer.calibrate_latency()
        except Exception as e:
            self.analyzer.signals.error.emit(str(e))


class NonlinearSystemAnalyzer(MeasurementModule):
    def __init__(self, audio_engine: AudioEngine):
        self.audio_engine = audio_engine
        self.signals = NonlinearSystemAnalyzerSignals()

        # Sweep Parameters
        self.start_freq = 20.0
        self.end_freq = 20000.0
        self.sweep_duration = 5.0  # seconds (Optimized for minimizing phase errors on UAC-232)
        self.amplitude_db = -6.0  # dBFS (peak)
        self.averages = 2  # TSA (Time Synchronized Averaging) count
        self.num_amplitudes = 5  # Number of amplitude steps for PHM (typically 5 to 7 steps)
        self.latency_sec = 0.0

        # Routing Config
        self.output_channel = "STEREO"  # 'L', 'R', 'STEREO'
        self.input_mode = "XFER"  # 'L' (Single Ch), 'XFER' (2-Ch relative)
        self.ref_channel_index = 0
        self.meas_channel_index = 1

        self.worker = None
        self.cal_worker = None
        self._dummy_callback_id = None
        self.signals.sweep_finished.connect(self._cleanup_dummy_callback)

    @property
    def name(self) -> str:
        return "Nonlinear System Analyzer"

    @property
    def description(self) -> str:
        return "Extracts true linear response and 2nd-5th harmonics using SSS and Parallel Hammerstein modeling."

    def get_widget(self):
        return NonlinearSystemAnalyzerWidget(self)

    def _dummy_callback(self, indata, outdata, frames, time, status):
        pass

    @property
    def tr(self):
        return tr

    def _cleanup_dummy_callback(self):
        if self._dummy_callback_id is not None:
            self.audio_engine.unregister_callback(self._dummy_callback_id)
            self._dummy_callback_id = None

    def run_play_rec(self, output_data, input_channels=2):
        session = PlayRecSession(self.audio_engine, output_data, input_channels)
        session.start()
        expected_duration = len(output_data) / self.audio_engine.sample_rate
        session.wait(timeout=expected_duration + 2.0)
        session.stop()
        return session.input_data

    def start_measurement(self):
        if self.worker and self.worker.isRunning():
            return
        if self._dummy_callback_id is None:
            self._dummy_callback_id = self.audio_engine.register_callback(self._dummy_callback)

        self.worker = NonlinearSweepWorker(self)
        self.worker.start()

    def start_latency_calibration(self):
        if self.cal_worker and self.cal_worker.isRunning():
            return
        if self._dummy_callback_id is None:
            self._dummy_callback_id = self.audio_engine.register_callback(self._dummy_callback)

        self.cal_worker = LatencyCalWorker(self)
        self.cal_worker.finished.connect(self._cleanup_dummy_callback)
        self.cal_worker.start()

    def stop_measurement(self):
        if self.worker:
            self.worker.stop()
            self.worker.wait()
        self._cleanup_dummy_callback()

    def calibrate_latency(self):
        """Measures loopback latency using a short logarithmic chirp signal."""
        sample_rate = self.audio_engine.sample_rate
        duration = 0.5
        t = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)
        chirp = 0.3 * signal_chirp(t, f0=20, t1=duration, f1=10000, method="logarithmic")

        # Zero-pad chirp to allow for buffer delays
        padding = int(0.5 * sample_rate)
        out_signal = np.concatenate([chirp, np.zeros(padding)])

        out_data = np.zeros((len(out_signal), 2), dtype=np.float32)
        out_data[:, 0] = out_signal
        out_data[:, 1] = out_signal

        logger.info("Executing latency calibration chirp...")
        rec_data = self.run_play_rec(out_data, input_channels=2)

        # Use measurement channel (or channel 0) to align
        recorded = rec_data[:, self.meas_channel_index if rec_data.shape[1] > 1 else 0]

        # Calculate cross-correlation to find peak delay
        correlation = fftconvolve(recorded, np.flip(chirp), mode="full")
        lag = np.argmax(np.abs(correlation)) - len(chirp) + 1

        self.latency_sec = max(0.0, lag / sample_rate)
        self.signals.latency_result.emit(self.latency_sec)
        logger.info(f"Calibration successful: Latency = {self.latency_sec * 1000:.2f} ms ({lag} samples)")

    def _generate_sss_and_inverse(self, sample_rate, amplitude=1.0):
        """
        Generates SSS signal and inverse match filter by delegating to the core implementation.
        Scaled by amplitude for playback.
        """
        sss, inv_filter = generate_sss_and_inverse(sample_rate, self.sweep_duration, self.start_freq, self.end_freq)
        return amplitude * sss, inv_filter

    def _execute_measurement(self, worker):
        sample_rate = self.audio_engine.sample_rate
        P = 5  # We support up to P=5 orders

        # 1. Define Amplitude Scanning Range
        max_amp = 10 ** (self.amplitude_db / 20)
        amplitudes = np.linspace(0.2, 1.0, self.num_amplitudes) * max_amp

        logger.info(f"Starting SSS/PHM measurement. Scanned amplitudes (linear): {amplitudes}")

        responses_ref = []
        responses_meas = []

        total_sweeps = self.num_amplitudes * self.averages
        sweep_counter = 0
        padding_samples = int(0.5 * sample_rate)  # 500ms tail padding

        # Generate the single reference sweep and matching analytical inverse filter
        sss, inv_filter = generate_sss_and_inverse(sample_rate, self.sweep_duration, self.start_freq, self.end_freq)

        for _amp_idx, amp in enumerate(amplitudes):
            if not worker.is_running:
                return

            out_signal = np.concatenate([amp * sss, np.zeros(padding_samples)])

            # Router output allocation
            out_data = np.zeros((len(out_signal), 2), dtype=np.float32)
            if self.output_channel in {"L", "STEREO"}:
                out_data[:, 0] = out_signal
            if self.output_channel in {"R", "STEREO"}:
                out_data[:, 1] = out_signal

            accum_data = None
            ref_peak_idx = None

            for _avg in range(self.averages):
                if not worker.is_running:
                    return

                rec_data = self.run_play_rec(out_data, input_channels=2)

                # Real-world OS hardware delay alignment using the measurement channel
                align_sig = rec_data[:, self.meas_channel_index if rec_data.shape[1] > 1 else 0]
                temp_ir = fftconvolve(align_sig, inv_filter, mode="full")
                peak_idx = np.argmax(np.abs(temp_ir))

                if accum_data is None:
                    accum_data = rec_data
                    ref_peak_idx = peak_idx
                else:
                    shift = ref_peak_idx - peak_idx
                    shifted = np.roll(rec_data, shift, axis=0)
                    if shift > 0:
                        shifted[:shift, :] = 0
                    elif shift < 0:
                        shifted[shift:, :] = 0
                    accum_data += shifted

                sweep_counter += 1
                progress_pct = int(90 * (sweep_counter / total_sweeps))
                self.signals.progress.emit(progress_pct)

            averaged_data = accum_data / self.averages

            # Execute Offline Mode/Virtual Loopback emulation if active
            if getattr(self.audio_engine, "offline_mode", False):
                simulated_meas = amp * sss
                # Apply simulated non-linear system transfer
                simulated_meas = (
                    simulated_meas
                    - 0.08 * (simulated_meas**2)
                    + 0.12 * (simulated_meas**3)
                    - 0.04 * (simulated_meas**4)
                    + 0.06 * (simulated_meas**5)
                )
                simulated_meas = np.concatenate([simulated_meas, np.zeros(padding_samples)])
                clean_ref = np.concatenate([amp * sss, np.zeros(padding_samples)])
                if self.meas_channel_index == self.ref_channel_index:
                    averaged_data[:, self.meas_channel_index] = simulated_meas
                else:
                    averaged_data[:, self.meas_channel_index] = simulated_meas
                    averaged_data[:, self.ref_channel_index] = clean_ref

            # Deconvolution to get raw impulse responses
            sig_ref = averaged_data[:, self.ref_channel_index]
            sig_meas = averaged_data[:, self.meas_channel_index]

            ir_ref_raw = deconvolve_signal(sig_ref, sss)
            ir_meas_raw = deconvolve_signal(sig_meas, sss)

            responses_ref.append(ir_ref_raw)
            responses_meas.append(ir_meas_raw)

        # 2. Parallel Hammerstein Separation and Analysis using Core Module
        (
            valid_freqs,
            magnitudes_db_dict,
            phases_deg_dict,
            time_ms,
            separated_kernels_data,
        ) = process_amplitude_responses(
            responses_meas,
            responses_ref,
            sample_rate,
            self.start_freq,
            self.end_freq,
            self.input_mode,
            self.latency_sec,
            sweep_duration=self.sweep_duration,
            P=P,
            amplitudes=amplitudes,
        )

        self.signals.progress.emit(95)

        # Emit plots
        self.signals.update_plot.emit(valid_freqs, magnitudes_db_dict, phases_deg_dict)
        self.signals.update_kernels.emit(time_ms, separated_kernels_data)
        self.signals.progress.emit(100)


class NonlinearSystemAnalyzerWidget(QWidget, ComparableWidgetInterface):
    def __init__(self, module: NonlinearSystemAnalyzer):
        QWidget.__init__(self)
        ComparableWidgetInterface.__init__(self)
        self.module = module

        # Bode plots vertical cursor synchronization lines (log scale pos)
        self.sim_freq_line_mag = pg.InfiniteLine(
            pos=3.0,  # log10(1000.0)
            movable=True,
            angle=90,
            pen=pg.mkPen((200, 200, 200), width=1.5, style=Qt.PenStyle.DashLine),
            label="Sim Freq: 1000 Hz",
            labelOpts={"position": 0.9, "color": (200, 200, 200), "fill": (40, 40, 40, 200)},
        )
        self.sim_freq_line_phase = pg.InfiniteLine(
            pos=3.0,  # log10(1000.0)
            movable=True,
            angle=90,
            pen=pg.mkPen((200, 200, 200), width=1.5, style=Qt.PenStyle.DashLine),
            label="Sim Freq: 1000 Hz",
            labelOpts={"position": 0.9, "color": (200, 200, 200), "fill": (40, 40, 40, 200)},
        )
        self.sim_freq_line_mag.setVisible(False)
        self.sim_freq_line_phase.setVisible(False)

        self.sim_freq_line_mag.sigPositionChanged.connect(self._on_mag_line_dragged)
        self.sim_freq_line_phase.sigPositionChanged.connect(self._on_phase_line_dragged)

        self.init_ui()

        # Connect Signals
        self.module.signals.update_plot.connect(self.on_update_plot)
        self.module.signals.update_kernels.connect(self.on_update_kernels)
        self.module.signals.sweep_finished.connect(self.on_sweep_finished)
        self.module.signals.progress.connect(self.progress_bar.setValue)
        self.module.signals.latency_result.connect(self.on_latency_result)
        self.module.signals.error.connect(self.on_error)

        # Stored data cache for comparisons
        self.cached_freqs = None
        self.cached_mags = {}
        self.cached_phases = {}

    def init_ui(self):
        # Premium layout design
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setSpacing(5)

        # --- Sidebar Container (Left Side, Fixed Width) ---
        sidebar_container = QWidget()
        sidebar_container.setFixedWidth(260)
        sidebar_main_layout = QVBoxLayout(sidebar_container)
        sidebar_main_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_main_layout.setSpacing(10)

        # Module Header Info (Experimental Badge)
        badge_layout = QHBoxLayout()
        badge_title = QLabel(f"<b>{tr('Nonlinear System Analyzer')}</b>")
        badge_label = QLabel(tr("Experimental"))
        badge_label.setStyleSheet(
            "background-color: #d9534f; color: white; border-radius: 4px; padding: 2px 5px; font-size: 10px; font-weight: bold;"
        )
        badge_layout.addWidget(badge_title)
        badge_layout.addWidget(badge_label)
        sidebar_main_layout.addLayout(badge_layout)

        # --- Parameter Scroll Area ---
        parameter_scroll = QScrollArea()
        parameter_scroll.setWidgetResizable(True)
        parameter_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        parameter_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        parameter_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(0, 0, 4, 0)
        scroll_layout.setSpacing(10)

        # Group 1: General Sweep Parameters
        sweep_group = QGroupBox(tr("SSS Parameters"))
        sweep_form = QFormLayout(sweep_group)
        sweep_form.setContentsMargins(6, 8, 6, 8)
        sweep_form.setSpacing(6)

        self.start_spin = QDoubleSpinBox()
        self.start_spin.setRange(2, 20000)
        self.start_spin.setValue(self.module.start_freq)
        self.start_spin.valueChanged.connect(lambda v: setattr(self.module, "start_freq", v))
        sweep_form.addRow(tr("Start Freq (Hz):"), self.start_spin)

        self.end_spin = QDoubleSpinBox()
        self.end_spin.setRange(20, 24000)
        self.end_spin.setValue(self.module.end_freq)
        self.end_spin.valueChanged.connect(lambda v: setattr(self.module, "end_freq", v))
        sweep_form.addRow(tr("End Freq (Hz):"), self.end_spin)

        self.duration_spin = QDoubleSpinBox()
        self.duration_spin.setRange(0.5, 30.0)
        self.duration_spin.setSingleStep(0.5)
        self.duration_spin.setValue(self.module.sweep_duration)
        self.duration_spin.valueChanged.connect(lambda v: setattr(self.module, "sweep_duration", v))
        sweep_form.addRow(tr("Sweep Time (s):"), self.duration_spin)

        self.tsa_spin = QSpinBox()
        self.tsa_spin.setRange(1, 20)
        self.tsa_spin.setValue(self.module.averages)
        self.tsa_spin.valueChanged.connect(lambda v: setattr(self.module, "averages", v))
        sweep_form.addRow(tr("TSA Averages:"), self.tsa_spin)

        scroll_layout.addWidget(sweep_group)

        # Group 2: Parallel Hammerstein Model Parameters
        phm_group = QGroupBox(tr("Hammerstein Modeling"))
        phm_form = QFormLayout(phm_group)
        phm_form.setContentsMargins(6, 8, 6, 8)
        phm_form.setSpacing(6)

        self.amp_spin = QDoubleSpinBox()
        self.amp_spin.setRange(-60.0, 0.0)
        self.amp_spin.setSingleStep(1.0)
        self.amp_spin.setValue(self.module.amplitude_db)
        self.amp_spin.valueChanged.connect(lambda v: setattr(self.module, "amplitude_db", v))
        phm_form.addRow(tr("Max Amp (dBFS):"), self.amp_spin)

        self.steps_spin = QSpinBox()
        self.steps_spin.setRange(5, 10)  # Safe range to keep execution < 30s
        self.steps_spin.setValue(self.module.num_amplitudes)
        self.steps_spin.valueChanged.connect(lambda v: setattr(self.module, "num_amplitudes", v))
        phm_form.addRow(tr("Amp Scans (P=5):"), self.steps_spin)

        self.smooth_combo = QComboBox()
        self.smooth_combo.addItem(tr("None"), "None")
        self.smooth_combo.addItem(tr("Light (Savitzky-Golay)"), "Light")
        self.smooth_combo.addItem(tr("Medium (Savitzky-Golay)"), "Medium")
        self.smooth_combo.addItem(tr("Heavy (Savitzky-Golay)"), "Heavy")
        self.smooth_combo.setCurrentIndex(1)  # Default: Light
        self.smooth_combo.currentIndexChanged.connect(self.refresh_plots_with_smoothing)
        phm_form.addRow(tr("Display Smoothing:"), self.smooth_combo)

        scroll_layout.addWidget(phm_group)

        # Group 3: Routing & Calibration
        route_group = QGroupBox(tr("Routing & Calibration"))
        route_form = QFormLayout(route_group)
        route_form.setContentsMargins(6, 8, 6, 8)
        route_form.setSpacing(6)

        self.out_combo = QComboBox()
        self.out_combo.addItem(tr("Left"), "L")
        self.out_combo.addItem(tr("Right"), "R")
        self.out_combo.addItem(tr("Stereo"), "STEREO")
        self.out_combo.setCurrentIndex(2)  # Default: Stereo
        self.out_combo.currentIndexChanged.connect(self.on_routing_changed)
        route_form.addRow(tr("Output Ch:"), self.out_combo)

        self.in_mode_combo = QComboBox()
        self.in_mode_combo.addItem(tr("Left (Ch1)"), "L")
        self.in_mode_combo.addItem(tr("Right (Ch2)"), "R")
        self.in_mode_combo.addItem(tr("XFER (Ref=L, Meas=R)"), "XFER")
        self.in_mode_combo.addItem(tr("XFER (Ref=R, Meas=L)"), "XFER_REV")
        self.in_mode_combo.setCurrentIndex(2)  # Default: XFER (Ref=L, Meas=R)
        self.in_mode_combo.currentIndexChanged.connect(self.on_routing_changed)
        route_form.addRow(tr("Input Mode:"), self.in_mode_combo)

        # Latency Display
        self.latency_label = QLabel("0.00 ms")
        self.latency_label.setStyleSheet("font-weight: bold; color: #4ba3e3;")
        route_form.addRow(tr("Latency:"), self.latency_label)

        # Calibrate Button
        self.cal_btn = QPushButton(tr("Calibrate Delay"))
        self.cal_btn.clicked.connect(self.module.start_latency_calibration)
        route_form.addRow(self.cal_btn)

        scroll_layout.addWidget(route_group)

        scroll_layout.addStretch()
        scroll_content.setLayout(scroll_layout)
        parameter_scroll.setWidget(scroll_content)
        sidebar_main_layout.addWidget(parameter_scroll)

        # --- Fixed Measurement Controls (Bottom) ---
        ctrl_container = QWidget()
        ctrl_main_layout = QVBoxLayout(ctrl_container)
        ctrl_main_layout.setContentsMargins(0, 0, 0, 0)
        ctrl_main_layout.setSpacing(8)

        ctrl_layout = QHBoxLayout()
        self.start_btn = QPushButton(tr("Start Analysis"))
        self.start_btn.setStyleSheet(
            "background-color: #2b8c56; color: white; font-weight: bold; padding: 6px 12px; border-radius: 4px;"
        )
        self.start_btn.clicked.connect(self.start_measurement)
        self.stop_btn = QPushButton(tr("Stop"))
        self.stop_btn.setStyleSheet(
            "background-color: #d9534f; color: white; font-weight: bold; padding: 6px 12px; border-radius: 4px;"
        )
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_measurement)
        ctrl_layout.addWidget(self.start_btn)
        ctrl_layout.addWidget(self.stop_btn)
        ctrl_main_layout.addLayout(ctrl_layout)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(12)
        ctrl_main_layout.addWidget(self.progress_bar)

        sidebar_main_layout.addWidget(ctrl_container)
        main_layout.addWidget(sidebar_container)

        # --- Plot Content Area (Right Side, Tab Widget) ---
        self.plot_tabs = QTabWidget()
        self.plot_tabs.setMinimumHeight(450)

        # Tab 1: Magnitude Response (Bode Plot)
        self.mag_tab = QWidget()
        mag_layout = QVBoxLayout(self.mag_tab)
        self.mag_plot = pg.PlotWidget(title=tr("Bode Magnitude Response (PHM Separation)"))
        self.mag_plot.setLabel("left", tr("Gain"), units="dB")
        self.mag_plot.setLabel("bottom", tr("Frequency"), units="Hz")
        self.mag_plot.setLogMode(True, False)
        self.mag_plot.showGrid(True, True, alpha=0.3)
        self.mag_plot.addItem(self.sim_freq_line_mag)
        mag_layout.addWidget(self.mag_plot)
        self.plot_tabs.addTab(self.mag_tab, tr("Bode Magnitude"))

        # Tab 2: Phase Response
        self.phase_tab = QWidget()
        phase_layout = QVBoxLayout(self.phase_tab)
        self.phase_plot = pg.PlotWidget(title=tr("Bode Phase Response (PHM Separation)"))
        self.phase_plot.setLabel("left", tr("Phase"), units="deg")
        self.phase_plot.setLabel("bottom", tr("Frequency"), units="Hz")
        self.phase_plot.setLogMode(True, False)
        self.phase_plot.showGrid(True, True, alpha=0.3)
        self.phase_plot.addItem(self.sim_freq_line_phase)
        phase_layout.addWidget(self.phase_plot)
        self.plot_tabs.addTab(self.phase_tab, tr("Bode Phase"))

        # Tab 3: Time Domain Kernels h_p(t)
        self.kernel_tab = QWidget()
        kernel_layout = QVBoxLayout(self.kernel_tab)
        self.kernel_plot = pg.PlotWidget(title=tr("Separated Parallel Hammerstein Kernels"))
        self.kernel_plot.setLabel("left", tr("Normalized Amplitude"))
        self.kernel_plot.setLabel("bottom", tr("Time"), units="ms")
        self.kernel_plot.showGrid(True, True, alpha=0.3)
        kernel_layout.addWidget(self.kernel_plot)
        self.plot_tabs.addTab(self.kernel_tab, tr("Hammerstein Kernels"))

        # Tab 4: Harmonic Simulator
        self.sim_tab = QWidget()
        self.init_simulator_tab()
        self.plot_tabs.addTab(self.sim_tab, tr("Harmonic Simulator"))

        # Premium Plot Legends
        self.mag_plot.addLegend(offset=(10, 10))
        self.phase_plot.addLegend(offset=(10, 10))
        self.kernel_plot.addLegend(offset=(10, 10))

        main_layout.addWidget(self.plot_tabs, stretch=1)
        self.on_routing_changed()

    def on_routing_changed(self):
        mode = self.in_mode_combo.currentData()
        self.module.input_mode = mode
        if mode == "L":
            self.module.meas_channel_index = 0
            self.module.ref_channel_index = 0
        elif mode == "R":
            self.module.meas_channel_index = 1
            self.module.ref_channel_index = 1
        elif mode == "XFER_REV":
            self.module.meas_channel_index = 0
            self.module.ref_channel_index = 1
        else:  # XFER
            self.module.meas_channel_index = 1
            self.module.ref_channel_index = 0

        self.module.output_channel = self.out_combo.currentData()
        # Disable calibrate button for XFER modes since delay is automatically canceled
        self.cal_btn.setEnabled(mode in {"L", "R"})

    def start_measurement(self):
        # Turn off main audio engine stream if running to capture hardware exclusively
        if self.module.audio_engine.stream and self.module.audio_engine.stream.active:
            self.module.audio_engine.stop_stream()

        self.start_btn.setEnabled(False)
        self.cal_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.progress_bar.setValue(0)

        # Clear existing plots
        self.mag_plot.clear()
        self.phase_plot.clear()
        self.kernel_plot.clear()

        # Hide simulator items during active sweep
        self.sim_freq_line_mag.setVisible(False)
        self.sim_freq_line_phase.setVisible(False)
        self.sim_container.setVisible(False)
        self.sim_error_label.setVisible(True)
        self.sim_plot.clear()

        self.module.start_measurement()

    def stop_measurement(self):
        self.module.stop_measurement()
        self.on_sweep_finished()

    def on_sweep_finished(self):
        self.start_btn.setEnabled(True)
        self.cal_btn.setEnabled(self.module.input_mode in {"L", "R"})
        self.stop_btn.setEnabled(False)

    def on_latency_result(self, val):
        self.latency_label.setText(f"{val * 1000:.2f} ms")
        QMessageBox.information(
            self, tr("Calibration Successful"), tr("Measured loopback delay: {0:.2f} ms").format(val * 1000)
        )

    def on_error(self, message):
        QMessageBox.critical(self, tr("Measurement Error"), message)
        self.on_sweep_finished()

    def refresh_plots_with_smoothing(self):
        if self.cached_freqs is not None:
            self.on_update_plot(self.cached_freqs, self.cached_mags, self.cached_phases)

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

    def on_update_plot(self, freqs, magnitudes_db_dict, phases_deg_dict):
        self.cached_freqs = freqs
        self.cached_mags = magnitudes_db_dict
        self.cached_phases = phases_deg_dict

        # Retrieve current display smoothing level
        smooth_level = self.smooth_combo.currentData()

        # Premium Palette
        # h1: Light blue, h2: Green, h3: Amber/Orange, h4: Magenta/Pink, h5: Crimson Red
        colors = {
            "h1": (75, 163, 227),  # #4ba3e3
            "h2": (43, 140, 86),  # #2b8c56
            "h3": (230, 140, 20),  # #e68c14
            "h4": (200, 50, 160),  # #c832a0
            "h5": (217, 83, 79),  # #d9534f
        }

        labels = {
            "h1": tr("Fundamental (Linear Kernel h1)"),
            "h2": tr("2nd Order (Kernel h2)"),
            "h3": tr("3rd Order (Kernel h3)"),
            "h4": tr("4th Order (Kernel h4)"),
            "h5": tr("5th Order (Kernel h5)"),
        }

        # Clear existing curves before redrawing
        self.mag_plot.clear()
        self.phase_plot.clear()

        # Restore InfiniteLine items as plotWidget.clear() deletes them
        self.mag_plot.addItem(self.sim_freq_line_mag)
        self.phase_plot.addItem(self.sim_freq_line_phase)

        for key in ["h1", "h2", "h3", "h4", "h5"]:
            if key in magnitudes_db_dict:
                # Apply Savitzky-Golay Smoothing
                mag_smoothed = self.apply_smoothing(magnitudes_db_dict[key], smooth_level)
                phase_smoothed = self.apply_smoothing(phases_deg_dict[key], smooth_level)

                # Magnitude Plot
                pen_mag = pg.mkPen(color=colors[key], width=2)
                self.mag_plot.plot(freqs, mag_smoothed, pen=pen_mag, name=labels[key])

                # Phase Plot
                pen_phase = pg.mkPen(color=colors[key], width=1.5, style=Qt.PenStyle.SolidLine)
                self.phase_plot.plot(freqs, phase_smoothed, pen=pen_phase, name=labels[key])

        # Enable simulator after measurement is successfully processed
        self.sim_error_label.setVisible(False)
        self.sim_container.setVisible(True)
        self.sim_freq_line_mag.setVisible(True)
        self.sim_freq_line_phase.setVisible(True)
        self.update_simulation()

    def on_update_kernels(self, time_ms, separated_kernels_data):
        self.kernel_plot.clear()

        # Auto-fit the X Range to focus on the impulse peak details (-5ms to +35ms)
        self.kernel_plot.setXRange(-5.0, 35.0)

        colors = [
            (75, 163, 227),  # h1
            (43, 140, 86),  # h2
            (230, 140, 20),  # h3
            (200, 50, 160),  # h4
            (217, 83, 79),  # h5
        ]

        labels = [
            tr("Kernel h1"),
            tr("Kernel h2"),
            tr("Kernel h3"),
            tr("Kernel h4"),
            tr("Kernel h5"),
        ]

        for p in range(len(separated_kernels_data)):
            pen = pg.mkPen(color=colors[p], width=1.8)
            self.kernel_plot.plot(time_ms, separated_kernels_data[p], pen=pen, name=labels[p])

    # --- ComparableWidgetInterface ---
    def get_comparison_data(self):
        # Implements ComparableWidgetInterface for data overlay and save comparison traces
        if self.cached_freqs is None or "h1" not in self.cached_mags:
            return None

        # We export the primary fundamental response (h1) as the default comparison trace
        return {
            "x": self.cached_freqs,
            "y": self.cached_mags["h1"],
            "title": f"PHM Fundamental (h1) Sweep - {time.strftime('%H:%M:%S')}",
            "x_label": "Frequency",
            "x_units": "Hz",
            "y_label": "Gain",
            "y_units": "dB",
        }

    # --- Simulator Methods ---
    def init_simulator_tab(self):
        # Main layout for simulator tab
        layout = QVBoxLayout(self.sim_tab)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(5)

        # Warning label shown when data is not yet measured
        self.sim_error_label = QLabel(tr("Please run SSS analysis to enable the simulator."))
        self.sim_error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.sim_error_label.setStyleSheet("font-size: 14px; color: #d9534f; font-weight: bold;")
        layout.addWidget(self.sim_error_label)

        # Simulator main container
        self.sim_container = QWidget()
        container_layout = QHBoxLayout(self.sim_container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(10)

        # --- Left: Control Panel ---
        ctrl_panel = QWidget()
        ctrl_panel.setFixedWidth(260)
        ctrl_layout = QVBoxLayout(ctrl_panel)
        ctrl_layout.setContentsMargins(0, 0, 0, 0)
        ctrl_layout.setSpacing(10)

        # Frequency group
        freq_group = QGroupBox(tr("Input Frequency"))
        freq_form = QVBoxLayout(freq_group)
        freq_form.setSpacing(6)

        self.sim_f0_spin = QDoubleSpinBox()
        self.sim_f0_spin.setRange(20.0, 20000.0)
        self.sim_f0_spin.setSuffix(" Hz")
        self.sim_f0_spin.setValue(1000.0)
        self.sim_f0_spin.setSingleStep(100.0)
        self.sim_f0_spin.valueChanged.connect(self._on_sim_freq_spin_changed)
        freq_form.addWidget(self.sim_f0_spin)

        self.sim_f0_slider = QSlider(Qt.Orientation.Horizontal)
        self.sim_f0_slider.setRange(0, 1000)
        self.sim_f0_slider.setValue(500)
        self.sim_f0_slider.valueChanged.connect(self._on_sim_freq_slider_changed)
        freq_form.addWidget(self.sim_f0_slider)
        ctrl_layout.addWidget(freq_group)

        # Amplitude group
        amp_group = QGroupBox(tr("Input Amplitude"))
        amp_form = QVBoxLayout(amp_group)
        amp_form.setSpacing(6)

        self.sim_amp_spin = QDoubleSpinBox()
        self.sim_amp_spin.setRange(-60.0, 0.0)
        self.sim_amp_spin.setSuffix(" dBFS")
        self.sim_amp_spin.setValue(-6.0)
        self.sim_amp_spin.setSingleStep(1.0)
        self.sim_amp_spin.valueChanged.connect(self._on_sim_amp_spin_changed)
        amp_form.addWidget(self.sim_amp_spin)

        self.sim_amp_slider = QSlider(Qt.Orientation.Horizontal)
        self.sim_amp_slider.setRange(-600, 0)
        self.sim_amp_slider.setValue(-60)
        self.sim_amp_slider.valueChanged.connect(self._on_sim_amp_slider_changed)
        amp_form.addWidget(self.sim_amp_slider)
        ctrl_layout.addWidget(amp_group)

        ctrl_layout.addStretch()
        container_layout.addWidget(ctrl_panel)

        # --- Right: Results Panel ---
        result_panel = QWidget()
        res_layout = QVBoxLayout(result_panel)
        res_layout.setContentsMargins(0, 0, 0, 0)
        res_layout.setSpacing(10)

        # Numeric Grid Layout
        grid_widget = QWidget()
        grid_layout = QGridLayout(grid_widget)
        grid_layout.setContentsMargins(5, 5, 5, 5)
        grid_layout.setSpacing(8)

        # Headers
        grid_layout.addWidget(QLabel(f"<b>{tr('Harmonic')}</b>"), 0, 0)
        grid_layout.addWidget(QLabel(f"<b>{tr('Frequency')}</b>"), 0, 1)
        grid_layout.addWidget(QLabel(f"<b>{tr('Amplitude')}</b>"), 0, 2)
        grid_layout.addWidget(QLabel(f"<b>{tr('Phase')}</b>"), 0, 3)

        self.sim_result_labels = {}
        harmonics_labels = [
            ("h1", tr("Fundamental")),
            ("h2", tr("2nd Harmonic")),
            ("h3", tr("3rd Harmonic")),
            ("h4", tr("4th Harmonic")),
            ("h5", tr("5th Harmonic")),
        ]

        colors_hex = {
            "h1": "#4ba3e3",
            "h2": "#2b8c56",
            "h3": "#e68c14",
            "h4": "#c832a0",
            "h5": "#d9534f",
        }

        for idx, (key, label) in enumerate(harmonics_labels, 1):
            lbl_name = QLabel(label)
            lbl_name.setStyleSheet(f"color: {colors_hex[key]}; font-weight: bold;")
            lbl_freq = QLabel("-- Hz")
            lbl_amp = QLabel("-- dBFS")
            lbl_phase = QLabel("--°")

            grid_layout.addWidget(lbl_name, idx, 0)
            grid_layout.addWidget(lbl_freq, idx, 1)
            grid_layout.addWidget(lbl_amp, idx, 2)
            grid_layout.addWidget(lbl_phase, idx, 3)

            self.sim_result_labels[key] = {"freq": lbl_freq, "amp": lbl_amp, "phase": lbl_phase}

        res_layout.addWidget(grid_widget)

        # Predicted Spectrum Bar Plot
        self.sim_plot = pg.PlotWidget(title=tr("Output Prediction Spectrum"))
        self.sim_plot.setLabel("left", tr("Amplitude"), units="dBFS")
        self.sim_plot.setLabel("bottom", tr("Frequency"), units="Hz")
        self.sim_plot.setLogMode(True, False)
        self.sim_plot.setXRange(np.log10(20.0), np.log10(100000.0))
        self.sim_plot.setYRange(-120.0, 10.0)
        self.sim_plot.showGrid(True, True, alpha=0.3)
        res_layout.addWidget(self.sim_plot, stretch=1)

        container_layout.addWidget(result_panel, stretch=1)
        layout.addWidget(self.sim_container)

        self.sim_container.setVisible(False)

    def _on_mag_line_dragged(self, line):
        pos = line.value()  # log10(freq)
        freq = 10**pos
        if self.cached_freqs is not None and len(self.cached_freqs) > 0:
            min_f = self.cached_freqs[0]
            max_f = self.cached_freqs[-1]
            freq = max(min_f, min(max_f, freq))
            pos = np.log10(freq)
        else:
            freq = max(20.0, min(20000.0, freq))
            pos = np.log10(freq)

        self.sim_freq_line_phase.blockSignals(True)
        self.sim_freq_line_phase.setValue(pos)
        self.sim_freq_line_phase.blockSignals(False)

        # Update labels dynamically
        self.sim_freq_line_mag.label.setText(f"Sim Freq: {freq:.0f} Hz")
        self.sim_freq_line_phase.label.setText(f"Sim Freq: {freq:.0f} Hz")

        self.sim_f0_spin.blockSignals(True)
        self.sim_f0_spin.setValue(freq)
        self.sim_f0_spin.blockSignals(False)

        self._update_slider_from_freq(freq)
        self.update_simulation()

    def _on_phase_line_dragged(self, line):
        pos = line.value()  # log10(freq)
        freq = 10**pos
        if self.cached_freqs is not None and len(self.cached_freqs) > 0:
            min_f = self.cached_freqs[0]
            max_f = self.cached_freqs[-1]
            freq = max(min_f, min(max_f, freq))
            pos = np.log10(freq)
        else:
            freq = max(20.0, min(20000.0, freq))
            pos = np.log10(freq)

        self.sim_freq_line_mag.blockSignals(True)
        self.sim_freq_line_mag.setValue(pos)
        self.sim_freq_line_mag.blockSignals(False)

        # Update labels dynamically
        self.sim_freq_line_mag.label.setText(f"Sim Freq: {freq:.0f} Hz")
        self.sim_freq_line_phase.label.setText(f"Sim Freq: {freq:.0f} Hz")

        self.sim_f0_spin.blockSignals(True)
        self.sim_f0_spin.setValue(freq)
        self.sim_f0_spin.blockSignals(False)

        self._update_slider_from_freq(freq)
        self.update_simulation()

    def _update_plot_lines(self, pos):
        log_pos = np.log10(pos)
        self.sim_freq_line_mag.blockSignals(True)
        self.sim_freq_line_mag.setValue(log_pos)
        self.sim_freq_line_mag.blockSignals(False)

        self.sim_freq_line_phase.blockSignals(True)
        self.sim_freq_line_phase.setValue(log_pos)
        self.sim_freq_line_phase.blockSignals(False)

        # Update labels dynamically
        self.sim_freq_line_mag.label.setText(f"Sim Freq: {pos:.0f} Hz")
        self.sim_freq_line_phase.label.setText(f"Sim Freq: {pos:.0f} Hz")

    def _on_sim_freq_spin_changed(self, val):
        self._update_slider_from_freq(val)
        self._update_plot_lines(val)
        self.update_simulation()

    def _on_sim_freq_slider_changed(self, val):
        freq = 20.0 * (1000.0 ** (val / 1000.0))
        self.sim_f0_spin.blockSignals(True)
        self.sim_f0_spin.setValue(freq)
        self.sim_f0_spin.blockSignals(False)
        self._update_plot_lines(freq)
        self.update_simulation()

    def _update_slider_from_freq(self, freq):
        val = int(1000.0 * np.log(freq / 20.0) / np.log(1000.0))
        val = max(0, min(1000, val))
        self.sim_f0_slider.blockSignals(True)
        self.sim_f0_slider.setValue(val)
        self.sim_f0_slider.blockSignals(False)

    def _on_sim_amp_spin_changed(self, val):
        self.sim_amp_slider.blockSignals(True)
        self.sim_amp_slider.setValue(int(val * 10))
        self.sim_amp_slider.blockSignals(False)
        self.update_simulation()

    def _on_sim_amp_slider_changed(self, val):
        amp = val / 10.0
        self.sim_amp_spin.blockSignals(True)
        self.sim_amp_spin.setValue(amp)
        self.sim_amp_spin.blockSignals(False)
        self.update_simulation()

    def update_simulation(self):
        if self.cached_freqs is None or len(self.cached_freqs) == 0:
            return

        f0 = self.sim_f0_spin.value()
        amp_db = self.sim_amp_spin.value()

        # 1. Reconstruct complex transfer functions H_p(f) from cached magnitudes and phases
        H_dict = {}
        for p in range(1, 6):
            h_key = f"h{p}"
            if h_key not in self.cached_mags or h_key not in self.cached_phases:
                continue
            mag_linear = 10 ** (self.cached_mags[h_key] / 20.0)
            phase_rad = np.radians(self.cached_phases[h_key])
            H_dict[p] = mag_linear * np.exp(1j * phase_rad)

        # 2. Interpolate complex H_p(f_n) for each harmonic frequency f_n = n * f0
        H_interp = {}
        sample_rate = self.module.audio_engine.sample_rate
        nyquist = sample_rate / 2.0

        for n in range(1, 6):
            f_n = n * f0
            H_interp[n] = {}
            if f_n > nyquist:
                # Exceeded Nyquist, set to zero to represent out of band
                for p in range(1, 6):
                    H_interp[n][p] = 0.0 + 0.0j
                continue

            for p in range(1, 6):
                if p not in H_dict:
                    H_interp[n][p] = 0.0 + 0.0j
                    continue
                # Interpolate real and imaginary parts separately for smooth phase behavior
                real_val = np.interp(f_n, self.cached_freqs, np.real(H_dict[p]))
                imag_val = np.interp(f_n, self.cached_freqs, np.imag(H_dict[p]))
                H_interp[n][p] = real_val + 1j * imag_val

        # 3. Input linear amplitude
        A_in = 10 ** (amp_db / 20.0)

        # 4. Synthesize harmonic outputs using Parallel Hammerstein model formulas
        # Incorporate complex multipliers for sine-wave input phase alignment:
        # 1st: +1,  2nd: -1j,  3rd: -1,  4th: +1j,  5th: +1
        Y = {}
        Y[1] = (1.0) * (
            A_in * H_interp[1][1] + (0.75 * (A_in**3)) * H_interp[1][3] + (0.625 * (A_in**5)) * H_interp[1][5]
        )
        Y[2] = (-1j) * ((0.5 * (A_in**2)) * H_interp[2][2] + (0.5 * (A_in**4)) * H_interp[2][4])
        Y[3] = (-1.0) * ((0.25 * (A_in**3)) * H_interp[3][3] + (0.3125 * (A_in**5)) * H_interp[3][5])
        Y[4] = (+1j) * ((0.125 * (A_in**4)) * H_interp[4][4])
        Y[5] = (1.0) * ((0.0625 * (A_in**5)) * H_interp[5][5])

        # Get fundamental phase to anchor relative harmonic phases
        fundamental_phase_rad = np.angle(Y[1])

        # 5. Update UI Labels & Predictions Plot
        self.sim_plot.clear()

        colors = {
            "h1": (75, 163, 227),  # #4ba3e3
            "h2": (43, 140, 86),  # #2b8c56
            "h3": (230, 140, 20),  # #e68c14
            "h4": (200, 50, 160),  # #c832a0
            "h5": (217, 83, 79),  # #d9534f
        }

        for n in range(1, 6):
            h_key = f"h{n}"
            f_n = n * f0
            labels = self.sim_result_labels[h_key]

            if f_n > nyquist:
                labels["freq"].setText(f"{f_n / 1000.0:.2f} kHz (N/A)")
                labels["amp"].setText("N/A (Nyquist)")
                labels["phase"].setText("N/A")
                continue

            y_val = Y[n]
            mag_val_db = 20 * np.log10(np.abs(y_val) + 1e-12)

            # Phase calculation relative to the fundamental component (n * fundamental_phase)
            relative_phase_rad = np.angle(y_val) - n * fundamental_phase_rad
            phase_val_deg = np.degrees(relative_phase_rad)
            phase_val_deg = (phase_val_deg + 180) % 360 - 180

            labels["freq"].setText(f"{f_n:.1f} Hz")
            labels["amp"].setText(f"{mag_val_db:.1f} dB")
            labels["phase"].setText(f"{phase_val_deg:+.1f}°")

            # Draw vertical bar and dot for predicted output spectrum
            pen_color = colors[h_key]
            curve = pg.PlotDataItem(
                x=[f_n, f_n],
                y=[-120.0, mag_val_db],
                pen=pg.mkPen(color=pen_color, width=2.5),
                symbol="o",
                symbolBrush=pg.mkBrush(color=pen_color),
                symbolSize=8,
            )
            self.sim_plot.addItem(curve)
