import logging
import threading
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
)
from scipy.signal import freqz, fftconvolve, chirp as signal_chirp

from src.core.audio_engine import AudioEngine
from src.core.localization import tr
from src.measurement_modules.base import MeasurementModule
from src.core.nonlinear_response_analyzer_core import (
    generate_schroeder_multisine,
    generate_gaussian_noise,
    identify_bussgang,
    identify_bla_ls,
    identify_tsa_svd,
    SimulatedNonlinearResponseSystem,
)

logger = logging.getLogger(__name__)


class NonlinearResponseAnalyzerSignals(QObject):
    update_plots = pyqtSignal(dict)  # results dictionary containing LTI FR, SNL data, fit info, etc.
    progress = pyqtSignal(int)
    latency_result = pyqtSignal(float)
    finished = pyqtSignal()
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


class NonlinearResponseAnalyzerWorker(QThread):
    def __init__(self, estimator):
        super().__init__()
        self.estimator = estimator
        self.is_running = True

    def run(self):
        try:
            self.estimator._execute_measurement(self)
        except Exception as e:
            logger.error("NonlinearResponseAnalyzerWorker Error: %s", e, exc_info=True)
            self.estimator.signals.error.emit(str(e))
        finally:
            self.estimator.signals.finished.emit()

    def stop(self):
        self.is_running = False


class LatencyWorker(QThread):
    def __init__(self, estimator):
        super().__init__()
        self.estimator = estimator

    def run(self):
        try:
            self.estimator.calibrate_latency()
        except Exception as e:
            self.estimator.signals.error.emit(str(e))


class NonlinearResponseAnalyzer(MeasurementModule):
    def __init__(self, audio_engine: AudioEngine):
        self.audio_engine = audio_engine
        self.signals = NonlinearResponseAnalyzerSignals()

        # Signal parameters
        self.stimulus_type = "Schroeder Multisine"
        self.amplitude_db = -6.0
        self.duration_sec = 2.0
        self.averages = 1

        # Model parameters
        self.poly_order = 3
        self.lti_len = 128
        self.na_poles = 2
        self.nb_zeros = 2
        self.method = "Bussgang Theorem"

        self.latency_sec = 0.0

        # Routing configs
        self.output_channel = "L"
        self.input_channel_idx = 0

        self.worker = None
        self.cal_worker = None
        self._dummy_callback_id = None

        self.signals.finished.connect(self._cleanup_dummy_callback)

    @property
    def name(self) -> str:
        return "Nonlinear Response Analyzer"

    @property
    def description(self) -> str:
        return "Analyzes linear block (LTI) and static nonlinearity (SNL) response characteristics."

    def get_widget(self):
        return NonlinearResponseAnalyzerWidget(self)

    def _dummy_callback(self, indata, outdata, frames, time, status):
        pass

    def _cleanup_dummy_callback(self):
        if self._dummy_callback_id is not None:
            self.audio_engine.unregister_callback(self._dummy_callback_id)
            self._dummy_callback_id = None

    def run_play_rec(self, output_data, input_channels=2):
        session = PlayRecSession(self.audio_engine, output_data, input_channels)
        session.start()
        expected_duration = len(output_data) / self.audio_engine.sample_rate
        session.wait(timeout=expected_duration + 3.0)
        session.stop()
        return session.input_data

    def start_measurement(self):
        if self.worker and self.worker.isRunning():
            return
        if self._dummy_callback_id is None:
            self._dummy_callback_id = self.audio_engine.register_callback(self._dummy_callback)

        self.worker = NonlinearResponseAnalyzerWorker(self)
        self.worker.start()

    def start_latency_calibration(self):
        if self.cal_worker and self.cal_worker.isRunning():
            return
        if self._dummy_callback_id is None:
            self._dummy_callback_id = self.audio_engine.register_callback(self._dummy_callback)

        self.cal_worker = LatencyWorker(self)
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

        padding = int(0.5 * sample_rate)
        out_signal = np.concatenate([chirp, np.zeros(padding)])

        out_data = np.zeros((len(out_signal), 2), dtype=np.float32)
        out_data[:, 0] = out_signal
        out_data[:, 1] = out_signal

        logger.info("Executing latency calibration...")

        if getattr(self.audio_engine, "offline_mode", False):
            # Simulating short latency for virtual mode
            self.latency_sec = 0.0125
            self.signals.latency_result.emit(self.latency_sec)
            return

        rec_data = self.run_play_rec(out_data, input_channels=2)
        recorded = rec_data[:, self.input_channel_idx if rec_data.shape[1] > 1 else 0]

        correlation = fftconvolve(recorded, np.flip(chirp), mode="full")
        lag = np.argmax(np.abs(correlation)) - len(chirp) + 1

        self.latency_sec = max(0.0, lag / sample_rate)
        self.signals.latency_result.emit(self.latency_sec)
        logger.info(f"Calibration successful: Latency = {self.latency_sec * 1000:.2f} ms")

    def _execute_measurement(self, worker):
        sample_rate = self.audio_engine.sample_rate
        duration = self.duration_sec
        start_freq = 20.0
        end_freq = min(20000.0, sample_rate / 2.1)

        # 1. Generate stimulus
        if self.stimulus_type == "Schroeder Multisine":
            u_stim = generate_schroeder_multisine(sample_rate, duration, start_freq, end_freq, self.amplitude_db)
        else:
            u_stim = generate_gaussian_noise(sample_rate, duration, start_freq, end_freq, self.amplitude_db)

        # Apply padding to ensure tail capture
        padding_samples = int(0.1 * sample_rate)
        u_padded = np.concatenate([u_stim, np.zeros(padding_samples)])

        # Prepare stereo play buffers
        out_data = np.zeros((len(u_padded), 2), dtype=np.float32)
        if self.output_channel in {"L", "STEREO"}:
            out_data[:, 0] = u_padded
        if self.output_channel in {"R", "STEREO"}:
            out_data[:, 1] = u_padded

        accum_rec = None
        for avg in range(self.averages):
            if not worker.is_running:
                return

            if getattr(self.audio_engine, "offline_mode", False):
                # Simulated system
                sim = SimulatedNonlinearResponseSystem(sample_rate)
                rec = np.zeros((len(u_padded), 2), dtype=np.float32)
                rec[:, self.input_channel_idx] = sim.process(u_padded, noise_std=0.002)
            else:
                rec = self.run_play_rec(out_data, input_channels=2)

            if accum_rec is None:
                accum_rec = rec
            else:
                accum_rec += rec

            self.signals.progress.emit(int(100 * (avg + 1) / self.averages))

        averaged_rec = accum_rec / self.averages

        # Align input/output to compensate for latency
        u_meas = u_stim
        y_meas = averaged_rec[:, self.input_channel_idx]

        # Calculate exact lag dynamically via cross-correlation to eliminate starting jitter
        correlation = fftconvolve(y_meas, np.flip(u_stim), mode="full")
        lag = np.argmax(np.abs(correlation)) - len(u_stim) + 1

        # Fallback to nominal latency if correlation result is invalid
        nominal_samples = int(np.round(self.latency_sec * sample_rate))
        if lag < 0 or lag >= len(y_meas):
            logger.warning(f"Correlation-based alignment failed (lag={lag}). Falling back to nominal latency.")
            latency_samples = nominal_samples
        else:
            latency_samples = lag
            logger.info(
                f"Dynamic alignment applied: lag = {latency_samples} samples ({latency_samples / sample_rate * 1000:.2f} ms)"
            )

        if latency_samples > 0 and latency_samples < len(y_meas):
            y_meas = y_meas[latency_samples : latency_samples + len(u_meas)]
            # Match lengths
            if len(y_meas) < len(u_meas):
                u_meas = u_meas[: len(y_meas)]
        else:
            y_meas = y_meas[: len(u_meas)]

        if len(y_meas) < 256:
            raise ValueError(tr("Acquired signal is too short. Verify connection or sample rate."))

        # 2. Run Estimation
        if self.method == "Bussgang Theorem":
            g, c, fit_ratio, y_pred, x_est = identify_bussgang(u_meas, y_meas, self.poly_order, self.lti_len)
            a = np.array([1.0])
            b = g
        elif self.method == "Best Linear Approximation (BLA)":
            b, a, c, fit_ratio, y_pred, x_est = identify_bla_ls(
                u_meas, y_meas, self.poly_order, self.na_poles, self.nb_zeros
            )
        else:  # Two-Stage Method (SVD)
            b, a, c, fit_ratio, y_pred, x_est = identify_tsa_svd(
                u_meas, y_meas, self.poly_order, self.na_poles, self.nb_zeros
            )

        # 3. Compute Frequency Response of the LTI block
        w, h = freqz(b, a, worN=512, fs=sample_rate)
        freqs = w
        mag_db = 20 * np.log10(np.abs(h) + 1e-12)
        phase_deg = np.angle(h) * 180 / np.pi

        # 4. Prepare SNL plot data
        x_min, x_max = np.min(x_est), np.max(x_est)
        x_grid = np.linspace(x_min, x_max, 300)
        y_grid = np.zeros_like(x_grid)
        for i, coeff in enumerate(c, start=1):
            y_grid += coeff * (x_grid**i)

        results = {
            "freqs": freqs,
            "mag_db": mag_db,
            "phase_deg": phase_deg,
            "x_est": x_est,
            "y_meas": y_meas,
            "y_pred": y_pred,
            "x_grid": x_grid,
            "y_grid": y_grid,
            "fit_ratio": fit_ratio,
            "poly_coeffs": c,
            "u_meas": u_meas,
        }

        self.signals.update_plots.emit(results)


class NonlinearResponseAnalyzerWidget(QWidget):
    def __init__(self, module: NonlinearResponseAnalyzer):
        super().__init__()
        self.module = module

        # Setup signals
        self.module.signals.update_plots.connect(self.on_update_plots)
        self.module.signals.progress.connect(self.on_progress)
        self.module.signals.latency_result.connect(self.on_latency_result)
        self.module.signals.error.connect(self.on_error)
        self.module.signals.finished.connect(self.on_finished)

        self.init_ui()

    def init_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(4, 4, 4, 4)
        main_layout.setSpacing(6)

        # Left panel: Scroll area for controls
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFixedWidth(320)

        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(6, 6, 6, 6)
        scroll_layout.setSpacing(8)

        # 1. Stimulus Parameters Group
        stim_group = QGroupBox(tr("Stimulus Parameters"))
        stim_layout = QFormLayout(stim_group)
        stim_layout.setContentsMargins(6, 6, 6, 6)
        stim_layout.setSpacing(4)

        self.stim_type_combo = QComboBox()
        stim_types = [
            (tr("Schroeder Multisine"), "Schroeder Multisine"),
            (tr("Gaussian Noise"), "Gaussian Noise"),
        ]
        for label, data in stim_types:
            self.stim_type_combo.addItem(label, data)
        self.stim_type_combo.currentIndexChanged.connect(self.on_stim_type_changed)
        stim_layout.addRow(tr("Signal Type:"), self.stim_type_combo)
        idx_stim = self.stim_type_combo.findData(self.module.stimulus_type)
        if idx_stim >= 0:
            self.stim_type_combo.setCurrentIndex(idx_stim)

        self.amp_spin = QDoubleSpinBox()
        self.amp_spin.setRange(-60.0, 0.0)
        self.amp_spin.setValue(self.module.amplitude_db)
        self.amp_spin.setSuffix(" dBFS")
        self.amp_spin.valueChanged.connect(self.on_amp_changed)
        stim_layout.addRow(tr("Amplitude:"), self.amp_spin)

        self.dur_spin = QDoubleSpinBox()
        self.dur_spin.setRange(0.5, 10.0)
        self.dur_spin.setValue(self.module.duration_sec)
        self.dur_spin.setSuffix(tr(" s"))
        self.dur_spin.valueChanged.connect(self.on_dur_changed)
        stim_layout.addRow(tr("Duration:"), self.dur_spin)

        self.avg_spin = QSpinBox()
        self.avg_spin.setRange(1, 10)
        self.avg_spin.setValue(self.module.averages)
        self.avg_spin.valueChanged.connect(self.on_avg_changed)
        stim_layout.addRow(tr("Averages:"), self.avg_spin)

        scroll_layout.addWidget(stim_group)

        # 2. Model Structure Group
        model_group = QGroupBox(tr("Model Architecture"))
        model_layout = QFormLayout(model_group)
        model_layout.setContentsMargins(6, 6, 6, 6)
        model_layout.setSpacing(4)

        self.method_combo = QComboBox()
        methods = [
            (tr("Bussgang Theorem"), "Bussgang Theorem"),
            (tr("Best Linear Approximation (BLA)"), "Best Linear Approximation (BLA)"),
            (tr("Two-Stage Method (SVD)"), "Two-Stage Method (SVD)"),
        ]
        for label, data in methods:
            self.method_combo.addItem(label, data)
        self.method_combo.currentIndexChanged.connect(self.on_method_changed)
        model_layout.addRow(tr("Algorithm:"), self.method_combo)
        idx_method = self.method_combo.findData(self.module.method)
        if idx_method >= 0:
            self.method_combo.setCurrentIndex(idx_method)

        self.poly_spin = QSpinBox()
        self.poly_spin.setRange(1, 10)
        self.poly_spin.setValue(self.module.poly_order)
        self.poly_spin.valueChanged.connect(self.on_poly_changed)
        model_layout.addRow(tr("Poly Degree (P):"), self.poly_spin)

        self.lti_len_spin = QSpinBox()
        self.lti_len_spin.setRange(8, 256)
        self.lti_len_spin.setValue(self.module.lti_len)
        self.lti_len_spin.valueChanged.connect(self.on_lti_len_changed)
        model_layout.addRow(tr("LTI Length (Bussgang):"), self.lti_len_spin)

        self.na_spin = QSpinBox()
        self.na_spin.setRange(0, 10)
        self.na_spin.setValue(self.module.na_poles)
        self.na_spin.valueChanged.connect(self.on_na_changed)
        model_layout.addRow(tr("na (Poles):"), self.na_spin)

        self.nb_spin = QSpinBox()
        self.nb_spin.setRange(0, 10)
        self.nb_spin.setValue(self.module.nb_zeros)
        self.nb_spin.valueChanged.connect(self.on_nb_changed)
        model_layout.addRow(tr("nb (Zeros):"), self.nb_spin)

        scroll_layout.addWidget(model_group)

        # 3. Routing parameters Group
        route_group = QGroupBox(tr("Audio Routing"))
        route_layout = QFormLayout(route_group)
        route_layout.setContentsMargins(6, 6, 6, 6)
        route_layout.setSpacing(4)

        self.out_ch_combo = QComboBox()
        self.out_ch_combo.addItems(["L", "R", "STEREO"])
        self.out_ch_combo.currentTextChanged.connect(self.on_out_ch_changed)
        route_layout.addRow(tr("Out Channel:"), self.out_ch_combo)

        self.in_ch_combo = QComboBox()
        self.in_ch_combo.addItems([tr("Channel 1 (Left)"), tr("Channel 2 (Right)")])
        self.in_ch_combo.currentIndexChanged.connect(self.on_in_ch_changed)
        route_layout.addRow(tr("In Channel:"), self.in_ch_combo)

        scroll_layout.addWidget(route_group)

        # 4. Identification Controls Group
        ctrl_group = QGroupBox(tr("Estimation Run"))
        ctrl_layout = QVBoxLayout(ctrl_group)
        ctrl_layout.setContentsMargins(6, 6, 6, 6)
        ctrl_layout.setSpacing(6)

        self.cal_btn = QPushButton(tr("Calibrate Latency"))
        self.cal_btn.clicked.connect(self.on_calibrate_clicked)
        ctrl_layout.addWidget(self.cal_btn)

        self.latency_label = QLabel(tr("Latency: {0:.2f} ms").format(self.module.latency_sec * 1000.0))
        ctrl_layout.addWidget(self.latency_label)

        self.run_btn = QPushButton(tr("Run Identification"))
        self.run_btn.setStyleSheet("font-weight: bold; background-color: #0b5ed7; color: white;")
        self.run_btn.clicked.connect(self.on_run_clicked)
        ctrl_layout.addWidget(self.run_btn)

        self.stop_btn = QPushButton(tr("Stop"))
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.on_stop_clicked)
        ctrl_layout.addWidget(self.stop_btn)

        self.pbar = QProgressBar()
        self.pbar.setValue(0)
        ctrl_layout.addWidget(self.pbar)

        self.fit_label = QLabel(tr("Model Fit R²: -"))
        self.fit_label.setStyleSheet("font-weight: bold;")
        ctrl_layout.addWidget(self.fit_label)

        scroll_layout.addWidget(ctrl_group)
        scroll_layout.addStretch()

        scroll_area.setWidget(scroll_content)
        main_layout.addWidget(scroll_area)

        # Right panel: Plot tab widget
        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs, stretch=1)

        # Tab 1: LTI Frequency Response
        self.lti_tab = QWidget()
        lti_layout = QVBoxLayout(self.lti_tab)
        lti_layout.setContentsMargins(2, 2, 2, 2)

        self.lti_mag_plot = pg.PlotWidget(title=tr("LTI Block Magnitude Response"))
        self.lti_mag_plot.setLabel("left", tr("Magnitude"), units="dB")
        self.lti_mag_plot.setLabel("bottom", tr("Frequency"), units="Hz")
        self.lti_mag_plot.setLogMode(x=True, y=False)
        self.lti_mag_plot.showGrid(x=True, y=True)

        self.lti_phase_plot = pg.PlotWidget(title=tr("LTI Block Phase Response"))
        self.lti_phase_plot.setLabel("left", tr("Phase"), units="degrees")
        self.lti_phase_plot.setLabel("bottom", tr("Frequency"), units="Hz")
        self.lti_phase_plot.setLogMode(x=True, y=False)
        self.lti_phase_plot.showGrid(x=True, y=True)

        lti_layout.addWidget(self.lti_mag_plot)
        lti_layout.addWidget(self.lti_phase_plot)
        self.tabs.addTab(self.lti_tab, tr("LTI Response"))

        # Tab 2: Static Nonlinearity (SNL)
        self.snl_tab = QWidget()
        snl_layout = QVBoxLayout(self.snl_tab)
        snl_layout.setContentsMargins(2, 2, 2, 2)

        self.snl_plot = pg.PlotWidget(title=tr("Static Nonlinearity f(x)"))
        self.snl_plot.setLabel("left", tr("Output y(t)"))
        self.snl_plot.setLabel("bottom", tr("Estimated Intermediate x(t)"))
        self.snl_plot.showGrid(x=True, y=True)
        snl_layout.addWidget(self.snl_plot)
        self.tabs.addTab(self.snl_tab, tr("Static Nonlinearity"))

        # Tab 3: Time Validation & Residuals
        self.val_tab = QWidget()
        val_layout = QVBoxLayout(self.val_tab)
        val_layout.setContentsMargins(2, 2, 2, 2)

        self.val_plot = pg.PlotWidget(title=tr("Time Domain Validation"))
        self.val_plot.setLabel("left", tr("Output"))
        self.val_plot.setLabel("bottom", tr("Time index"))
        self.val_plot.showGrid(x=True, y=True)
        self.val_plot.addLegend()

        self.res_plot = pg.PlotWidget(title=tr("Model Residual Error"))
        self.res_plot.setLabel("left", tr("Error"))
        self.res_plot.setLabel("bottom", tr("Time index"))
        self.res_plot.showGrid(x=True, y=True)

        val_layout.addWidget(self.val_plot)
        val_layout.addWidget(self.res_plot)
        self.tabs.addTab(self.val_tab, tr("Validation & Residuals"))

        # Tab 4: Input Distribution
        self.dist_tab = QWidget()
        dist_layout = QVBoxLayout(self.dist_tab)
        dist_layout.setContentsMargins(2, 2, 2, 2)

        self.dist_plot = pg.PlotWidget(title=tr("Intermediate Signal Distribution"))
        self.dist_plot.setLabel("left", tr("Count"))
        self.dist_plot.setLabel("bottom", tr("Amplitude"))
        self.dist_plot.showGrid(x=True, y=True)
        dist_layout.addWidget(self.dist_plot)
        self.tabs.addTab(self.dist_tab, tr("Input Distribution"))

        self.on_stim_type_changed()
        self.on_method_changed()

    def on_stim_type_changed(self, _index=None):
        self.module.stimulus_type = self.stim_type_combo.currentData()

    def on_amp_changed(self, value):
        self.module.amplitude_db = value

    def on_dur_changed(self, value):
        self.module.duration_sec = value

    def on_avg_changed(self, value):
        self.module.averages = value

    def on_method_changed(self, _index=None):
        self.module.method = self.method_combo.currentData()
        # Dynamically toggle settings visibility
        is_bussgang = self.module.method == "Bussgang Theorem"
        self.lti_len_spin.setEnabled(is_bussgang)
        self.na_spin.setEnabled(not is_bussgang)
        self.nb_spin.setEnabled(not is_bussgang)

    def on_poly_changed(self, value):
        self.module.poly_order = value

    def on_lti_len_changed(self, value):
        self.module.lti_len = value

    def on_na_changed(self, value):
        self.module.na_poles = value

    def on_nb_changed(self, value):
        self.module.nb_zeros = value

    def on_out_ch_changed(self, text):
        self.module.output_channel = text

    def on_in_ch_changed(self, index):
        self.module.input_channel_idx = index

    def on_calibrate_clicked(self):
        self.cal_btn.setEnabled(False)
        self.run_btn.setEnabled(False)
        self.pbar.setValue(0)
        self.module.start_latency_calibration()

    def on_run_clicked(self):
        self.run_btn.setEnabled(False)
        self.cal_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.pbar.setValue(0)
        self.module.start_measurement()

    def on_stop_clicked(self):
        self.module.stop_measurement()
        self.stop_btn.setEnabled(False)

    def on_progress(self, val):
        self.pbar.setValue(val)

    def on_latency_result(self, val):
        self.latency_label.setText(tr("Latency: {0:.2f} ms").format(val * 1000.0))
        self.cal_btn.setEnabled(True)
        self.run_btn.setEnabled(True)

    def on_finished(self):
        self.run_btn.setEnabled(True)
        self.cal_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.pbar.setValue(100)

    def on_error(self, err_msg):
        QMessageBox.critical(self, tr("Error"), tr("Measurement failed: {0}").format(err_msg))
        self.on_finished()

    def on_update_plots(self, results):
        # 1. Update LTI tab
        self.lti_mag_plot.clear()
        self.lti_mag_plot.plot(results["freqs"], results["mag_db"], pen=pg.mkPen("c", width=2))

        self.lti_phase_plot.clear()
        self.lti_phase_plot.plot(results["freqs"], results["phase_deg"], pen=pg.mkPen("c", width=2))

        # 2. Update SNL tab
        self.snl_plot.clear()
        # Downsample scatter data for better performance if there are too many samples
        x_est = results["x_est"]
        y_meas = results["y_meas"]
        if len(x_est) > 5000:
            indices = np.random.choice(len(x_est), 5000, replace=False)
            x_scatter = x_est[indices]
            y_scatter = y_meas[indices]
        else:
            x_scatter = x_est
            y_scatter = y_meas

        self.snl_plot.plot(x_scatter, y_scatter, pen=None, symbol="o", symbolSize=3, symbolBrush=(128, 128, 128, 80))
        self.snl_plot.plot(results["x_grid"], results["y_grid"], pen=pg.mkPen("y", width=2.5))

        # 3. Update Validation & Residuals
        self.val_plot.clear()
        y_meas_show = y_meas[:1000]  # Plot first 1000 samples for responsiveness
        y_pred_show = results["y_pred"][:1000]
        self.val_plot.plot(y_meas_show, pen=pg.mkPen("w", width=1), name=tr("Measured"))
        self.val_plot.plot(
            y_pred_show, pen=pg.mkPen("y", width=1.5, style=Qt.PenStyle.DashLine), name=tr("Model Prediction")
        )

        self.res_plot.clear()
        res_show = (y_meas - results["y_pred"])[:1000]
        self.res_plot.plot(res_show, pen=pg.mkPen("r", width=1))

        # Update Fit label
        fit_r2 = results["fit_ratio"]
        if np.isfinite(fit_r2):
            self.fit_label.setText(tr("Model Fit R²: {0:.4f}").format(fit_r2))
        else:
            self.fit_label.setText(tr("Model Fit R²: N/A"))

        # 4. Update Input Distribution
        self.dist_plot.clear()
        x_est_finite = x_est[np.isfinite(x_est)] if x_est is not None else np.array([])
        if len(x_est_finite) > 0:
            # Compute histogram
            counts, bins = np.histogram(x_est_finite, bins=50)
            # Plot step-like histogram
            self.dist_plot.plot(bins, counts, stepMode="center", fillLevel=0, fillOutline=True, brush=(0, 255, 255, 80))
