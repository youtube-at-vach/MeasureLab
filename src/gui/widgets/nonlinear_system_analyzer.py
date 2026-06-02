import logging
import threading
import time
import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import QObject, QThread, QTimer, pyqtSignal, Qt
from PyQt6.QtWidgets import (
    QCheckBox,
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
)
from scipy.signal import (
    chirp as signal_chirp,
    windows,
    fftconvolve,
    coherence,
    savgol_filter,
)

from src.core.audio_engine import AudioEngine
from src.core.fft_manager import fft_manager
from src.core.localization import tr
from src.measurement_modules.base import MeasurementModule
from src.gui.widgets.comparable_interface import ComparableWidgetInterface
from src.core.nonlinear_analyzer_core import (
    generate_sss_and_inverse,
    calculate_chebyshev_matrix,
    process_amplitude_responses,
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
        self.sweep_duration = 3.0  # seconds
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
        sss, inv_filter = generate_sss_and_inverse(
            sample_rate, self.sweep_duration, self.start_freq, self.end_freq
        )
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
        sss, inv_filter = generate_sss_and_inverse(
            sample_rate, self.sweep_duration, self.start_freq, self.end_freq
        )

        for amp_idx, amp in enumerate(amplitudes):
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

            for avg in range(self.averages):
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
                    - 0.08 * (simulated_meas ** 2)
                    + 0.12 * (simulated_meas ** 3)
                    - 0.04 * (simulated_meas ** 4)
                    + 0.06 * (simulated_meas ** 5)
                )
                simulated_meas = np.concatenate([simulated_meas, np.zeros(padding_samples)])
                averaged_data[:, self.meas_channel_index] = simulated_meas
                averaged_data[:, self.ref_channel_index] = np.concatenate([amp * sss, np.zeros(padding_samples)])

            # Deconvolution to get raw impulse responses
            sig_ref = averaged_data[:, self.ref_channel_index]
            sig_meas = averaged_data[:, self.meas_channel_index]

            ir_ref_raw = fftconvolve(sig_ref, inv_filter, mode="full")
            ir_meas_raw = fftconvolve(sig_meas, inv_filter, mode="full")

            responses_ref.append(ir_ref_raw)
            responses_meas.append(ir_meas_raw)

        # 2. Parallel Hammerstein Separation and Analysis using Core Module
        norm_v = amplitudes / max_amp
        _, M_pinv = calculate_chebyshev_matrix(self.num_amplitudes, norm_v, P)

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
            M_pinv=M_pinv,
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

        self.in_mode_combo = QComboBox()
        self.in_mode_combo.addItem(tr("XFER (Ref=L, Meas=R)"), "XFER")
        self.in_mode_combo.addItem(tr("1-Ch Mode (L)"), "L")
        self.in_mode_combo.setCurrentIndex(0)
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

        # Premium Plot Legends
        self.mag_plot.addLegend(offset=(10, 10))
        self.phase_plot.addLegend(offset=(10, 10))
        self.kernel_plot.addLegend(offset=(10, 10))

        main_layout.addWidget(self.plot_tabs, stretch=1)

    def on_routing_changed(self):
        mode = self.in_mode_combo.currentData()
        self.module.input_mode = mode
        if mode == "L":
            self.module.meas_channel_index = 0
            self.module.ref_channel_index = 0  # 1-Ch Mode has no reference but align L for safety
        else:  # XFER
            self.module.meas_channel_index = 1
            self.module.ref_channel_index = 0
        # Disable calibrate button for XFER mode since delay is automatically canceled
        self.cal_btn.setEnabled(mode == "L")

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

        self.module.start_measurement()

    def stop_measurement(self):
        self.module.stop_measurement()
        self.on_sweep_finished()

    def on_sweep_finished(self):
        self.start_btn.setEnabled(True)
        self.cal_btn.setEnabled(self.module.input_mode == "L")
        self.stop_btn.setEnabled(False)

    def on_latency_result(self, val):
        self.latency_label.setText(f"{val * 1000:.2f} ms")
        QMessageBox.information(
            self,
            tr("Calibration Successful"),
            tr("Measured loopback delay: {0:.2f} ms").format(val * 1000)
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
            "h1": (75, 163, 227),    # #4ba3e3
            "h2": (43, 140, 86),     # #2b8c56
            "h3": (230, 140, 20),    # #e68c14
            "h4": (200, 50, 160),    # #c832a0
            "h5": (217, 83, 79),     # #d9534f
        }
        
        labels = {
            "h1": tr("Fundamental (Linear h1)"),
            "h2": tr("2nd Harmonic (h2)"),
            "h3": tr("3rd Harmonic (h3)"),
            "h4": tr("4th Harmonic (h4)"),
            "h5": tr("5th Harmonic (h5)"),
        }

        # Clear existing curves before redrawing
        self.mag_plot.clear()
        self.phase_plot.clear()

        for key in ["h1", "h2", "h3", "h4", "h5"]:
            if key in magnitudes_db_dict:
                # Apply Savitzky-Golay Smoothing
                mag_smoothed = self.apply_smoothing(magnitudes_db_dict[key], smooth_level)
                phase_smoothed = self.apply_smoothing(phases_deg_dict[key], smooth_level)

                # Magnitude Plot
                pen_mag = pg.mkPen(color=colors[key], width=2)
                self.mag_plot.plot(
                    freqs,
                    mag_smoothed,
                    pen=pen_mag,
                    name=labels[key]
                )

                # Phase Plot
                pen_phase = pg.mkPen(color=colors[key], width=1.5, style=Qt.PenStyle.SolidLine)
                self.phase_plot.plot(
                    freqs,
                    phase_smoothed,
                    pen=pen_phase,
                    name=labels[key]
                )

    def on_update_kernels(self, time_ms, separated_kernels_data):
        self.kernel_plot.clear()
        
        # Auto-fit the X Range to focus on the impulse peak details (-5ms to +35ms)
        self.kernel_plot.setXRange(-5.0, 35.0)

        colors = [
            (75, 163, 227),  # h1
            (43, 140, 86),   # h2
            (230, 140, 20),  # h3
            (200, 50, 160),  # h4
            (217, 83, 79),   # h5
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
            self.kernel_plot.plot(
                time_ms,
                separated_kernels_data[p],
                pen=pen,
                name=labels[p]
            )

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
