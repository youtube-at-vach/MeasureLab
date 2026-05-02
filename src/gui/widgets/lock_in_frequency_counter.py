import time
from collections import deque

import numpy as np
import pyqtgraph as pg
import scipy.signal
import scipy.stats
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from src.core.audio_engine import AudioEngine
from src.core.localization import tr
from src.core.utils import format_si
from src.measurement_modules.base import MeasurementModule


class PIDController:
    def __init__(self, kp=0.5, ki=0.2, kd=0.0):
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.prev_error = 0.0
        self.integral = 0.0

    def reset(self):
        self.prev_error = 0.0
        self.integral = 0.0

    def update(self, error, dt):
        if dt <= 0:
            return 0.0

        # Proportional
        p_term = self.kp * error

        # Integral
        self.integral += error * dt
        i_term = self.ki * self.integral

        # Derivative
        derivative = (error - self.prev_error) / dt
        d_term = self.kd * derivative

        self.prev_error = error

        return p_term + i_term + d_term


class KalmanFilter1D:
    def __init__(self, process_noise=1e-10, measurement_noise=1e-6):
        self.q = process_noise  # Process noise covariance (Q)
        self.r = measurement_noise  # Measurement noise covariance (R)
        self.x = 0.0  # State estimate
        self.p = 1.0  # Estimation error covariance
        self._first_run = True

    def reset(self):
        self._first_run = True
        self.p = 1.0

    def update(self, measurement):
        if self._first_run:
            self.x = measurement
            self.p = self.r
            self._first_run = False
            return self.x

        # Prediction Step
        # x_k|k-1 = x_k-1|k-1 (Constant value model)
        # P_k|k-1 = P_k-1|k-1 + Q
        p_pred = self.p + self.q

        # Update Step
        # K = P_pred / (P_pred + R)
        if (p_pred + self.r) == 0:
            k = 0
        else:
            k = p_pred / (p_pred + self.r)

        # x_k = x_pred + K * (z_k - x_pred)
        self.x = self.x + k * (measurement - self.x)

        # P_k = (1 - K) * P_pred
        self.p = (1.0 - k) * p_pred

        return self.x

    def get_std_uncertainty(self):
        return float(np.sqrt(self.p))


class LockInFrequencyCounter(MeasurementModule):
    def __init__(self, audio_engine: AudioEngine):
        self.audio_engine = audio_engine
        self.is_running = False
        self.buffer_size = 4096
        self.input_data = np.zeros((self.buffer_size, 2))

        # Signal detect (match FrequencyCounter-style amplitude gate)
        self.gate_threshold_db = -60.0
        self.current_amp_db = -120.0
        self.signal_present = False

        # Settings
        self.gen_frequency = 1000.0  # NCO Frequency
        self.signal_channel = 0  # 0: Ch1 (L), 1: Ch2 (R)
        self.ref_channel = 1
        self.ref_mode = "internal"  # internal, loopback
        # Display is ~1000 points @ 10 Hz = ~100 s window. A ~2 s EMA time constant
        # provides stable readout without feeling laggy.
        self.smoothing_tau = 2.0
        self.locked = False
        self.feedback_gain = 0.5  # Deprecated in favor of PID, kept for compat if needed, but not used in new logic

        self.pid = PIDController(kp=0.5, ki=0.2, kd=0.0)

        # NCO Statistics / Kalman Filter
        # nco_avg_count now controls the Process Noise Q (Smoothness/Stiffness) AND Display Averaging
        self.nco_avg_count = 10
        self.kf = KalmanFilter1D(process_noise=1e-10, measurement_noise=1e-6)

        # Buffer to estimate Measurement Noise R adaptively
        self.r_history = deque(maxlen=20)

        # Display Averaging Buffer (Post-Kalman)
        self.nco_history = deque(maxlen=self.nco_avg_count)

        self.update_kalman_params()

        self.nco_mean = 1000.0  # Instant KF estimate
        self.nco_std = 0.0  # KF Uncertainty

        self.nco_display_mean = 1000.0  # Averaged KF estimate for UI
        self.nco_display_std = 0.0  # Std Dev of the averaging window

        # Stability Stats

        # Internal State
        self._nco_phase_rad = 0.0
        self._last_unwrapped_phase = 0.0
        self._first_run = True

        # Startup transient handling
        self._samples_received = 0
        self._last_samples_processed = 0
        # Only enable estimate discarding during real-time streaming (set in start_analysis).
        # This keeps offline/unit-test calls to process_data() responsive.
        self._discard_initial_estimates = 0
        self._estimates_discarded = 0

        # Plot Data Buffers
        self.max_history = 1000  # points on plot
        self.time_axis = deque(maxlen=self.max_history)
        self.freq_dev_history = deque(maxlen=self.max_history)
        self.phase_history = deque(maxlen=self.max_history)
        self.iq_history_i = deque(maxlen=self.max_history)  # For I-Q plot
        self.iq_history_q = deque(maxlen=self.max_history)

        # Distribution / TIC-like statistics buffers. 100k samples keeps long
        # stability runs useful without allowing unbounded memory growth.
        self.distribution_max_samples = 100000
        self.frequency_distribution = deque(maxlen=self.distribution_max_samples)
        self.interval_distribution = deque(maxlen=self.distribution_max_samples)
        self.distribution_timestamps = deque(maxlen=self.distribution_max_samples)

        self.start_time = 0

        # Current Value
        self.current_freq_dev = 0.0
        self.smoothed_freq_dev = 0.0
        self.current_phase_deg = 0.0
        self.phase_std = 0.0

        self.callback_id = None

    @property
    def name(self) -> str:
        return "Lock-in Frequency Counter"

    @property
    def description(self) -> str:
        return tr("Precision Frequency & Phase Drift Measurement using Lock-in Principle.")

    def get_widget(self):
        return LockInFrequencyCounterWidget(self)

    def update_kalman_params(self):
        # Map nco_avg_count to Process Noise Q.
        # Larger count = Expect more stability = Lower Q = More smoothing.
        # Q = Base / (Count^2)
        # Count 10 -> Q=1e-8. Count 100 -> Q=1e-10.
        self.kf.q = 1e-6 / (float(self.nco_avg_count) ** 2)

    def start_analysis(self):
        if self.is_running:
            return

        self.is_running = True
        self.input_data = np.zeros((self.buffer_size, 2))

        # Reset State
        self._nco_phase_rad = 0.0
        self._last_unwrapped_phase = 0.0
        self._first_run = True
        self.start_time = 0
        self.smoothed_freq_dev = 0.0
        self.current_phase_deg = 0.0

        self.current_amp_db = -120.0
        self.signal_present = False
        self.pid.reset()

        # Reset Kalman and R estimation
        self.kf.reset()
        self.r_history.clear()
        self.nco_history.clear()
        self.update_kalman_params()
        self.nco_mean = self.gen_frequency
        self.nco_std = 0.0
        self.nco_display_mean = self.gen_frequency
        self.nco_display_std = 0.0

        self._samples_received = 0
        self._last_samples_processed = 0
        self._discard_initial_estimates = 3
        self._estimates_discarded = 0

        self.time_axis.clear()
        self.freq_dev_history.clear()
        self.phase_history.clear()
        self.iq_history_i.clear()
        self.iq_history_q.clear()
        self.frequency_distribution.clear()
        self.interval_distribution.clear()
        self.distribution_timestamps.clear()

        sample_rate = self.audio_engine.sample_rate

        def callback(indata, outdata, frames, time_info, status):
            # Input Capture
            if indata.shape[1] >= 2:
                new_data = indata[:, :2]
            else:
                new_data = np.column_stack((indata[:, 0], indata[:, 0]))

            # Roll buffer
            if len(new_data) > self.buffer_size:
                self.input_data[:] = new_data[-self.buffer_size :]
            else:
                self.input_data = np.roll(self.input_data, -len(new_data), axis=0)
                self.input_data[-len(new_data) :] = new_data

            self._samples_received += frames

            # Output Generation
            outdata.fill(0)
            if self.ref_mode == "loopback":
                # Phase Accumulator for smooth frequency transitions
                phase_increment = 2 * np.pi * self.gen_frequency / sample_rate

                # Create phase array for this block
                phases = self._nco_phase_rad + np.arange(frames) * phase_increment

                # Signal Generation
                sig = 0.5 * np.cos(phases)

                if self.ref_channel == 1:
                    outdata[:, 1] = sig
                else:
                    outdata[:, 0] = sig

                # Update accumulator for next block, keep bounded [0, 2pi]
                self._nco_phase_rad = (self._nco_phase_rad + frames * phase_increment) % (2 * np.pi)

        self.callback_id = self.audio_engine.register_callback(callback)

    def stop_analysis(self):
        if self.is_running:
            if self.callback_id is not None:
                self.audio_engine.unregister_callback(self.callback_id)
                self.callback_id = None
            self.is_running = False

    def process_data(self):
        if not self.is_running:
            return

        # Wait until we have a fully populated buffer, then discard a few initial
        # estimates to avoid startup transients causing a "first point jump".
        if self._samples_received < self.buffer_size:
            # In normal operation, samples arrive via the audio callback and the
            # buffer starts as zeros. In unit tests / offline use, input_data may
            # be populated directly without advancing _samples_received.
            if self._samples_received == 0 and np.any(self.input_data):
                pass
            else:
                return

        samples_elapsed = self._samples_received - self._last_samples_processed
        if samples_elapsed == 0 and self._samples_received > 0:
            return  # Wait for new audio samples

        # Get Snapshot
        data = self.input_data
        sig = data[:, self.signal_channel]
        n_samples = len(sig)
        sr = self.audio_engine.sample_rate

        # 1) Signal detect (RMS gate)
        rms = float(np.sqrt(np.mean(sig.astype(np.float64) ** 2)))
        self.current_amp_db = float(20.0 * np.log10(rms + 1e-12))
        if self.current_amp_db < float(getattr(self, "gate_threshold_db", -60.0)):
            self.signal_present = False
            return

        t = np.arange(n_samples) / sr

        # NCO
        osc = np.exp(-1j * 2 * np.pi * self.gen_frequency * t)

        # Mixing
        z = sig * osc

        # Split into segments to find slope

        n_segments = 4
        stride = n_samples // n_segments

        # Ripple period (samples) = sr / (2 * freq) because mix product is basically at 2*f
        # (Assuming locked or close to lock)
        period_2f = sr / (2.0 * self.gen_frequency)

        # How many full cycles fit in the available stride?
        num_cycles = max(1, int(stride / period_2f))

        # Optimal length
        seg_len = int(round(num_cycles * period_2f))

        if seg_len > stride:
            seg_len = stride

        # Calculate Phase for each segment
        seg_phases = []
        seg_centers = []

        for i in range(n_segments):
            start = i * stride
            end = start + seg_len
            segment = z[start:end]
            # Use periodic Blackman-Harris for extremely high suppression of 2f component leakage.
            # Symmetric windows leak when seg_len is an integer number of periods,
            # causing a rotating phase bias which integrates into a systematic drift.
            win = scipy.signal.windows.blackmanharris(len(segment), sym=False)
            avg = np.mean(segment * win)

            if np.abs(avg) < 1e-9:
                self.signal_present = False
                return  # Noise

            phi = np.angle(avg)
            seg_phases.append(phi)
            seg_centers.append(start + seg_len / 2.0)

        # Unwrap phases across segments
        seg_phases_unwrapped = np.unwrap(seg_phases)

        # Helper time array
        t_centers = np.array(seg_centers) / sr

        if len(t_centers) > 1:
            slope, intercept = np.polyfit(t_centers, seg_phases_unwrapped, 1)
            delta_f = slope / (2 * np.pi)

            if self._estimates_discarded < self._discard_initial_estimates:
                self._estimates_discarded += 1
                self.current_freq_dev = 0.0
                self.smoothed_freq_dev = 0.0
                return

            # Mean Vector for IQ
            mean_vec = np.mean(z)
            self.iq_history_i.append(np.real(mean_vec))
            self.iq_history_q.append(np.imag(mean_vec))

            self.signal_present = True

            self.current_freq_dev = delta_f
            measured_frequency = self.gen_frequency + delta_f
            if measured_frequency > 0.0:
                self.frequency_distribution.append(measured_frequency)
                self.interval_distribution.append(1.0 / measured_frequency)
                self.distribution_timestamps.append(time.time())

            # Smoothing (EMA)
            if samples_elapsed > 0:
                dt = samples_elapsed / sr
            else:
                dt = n_samples / sr  # fallback for offline/test mode
            self._last_samples_processed = self._samples_received

            tau = self.smoothing_tau
            if tau > 0:
                alpha = dt / (tau + dt)
                if self.start_time == 0:
                    self.smoothed_freq_dev = delta_f
                else:
                    self.smoothed_freq_dev = self.smoothed_freq_dev + alpha * (delta_f - self.smoothed_freq_dev)
            else:
                self.smoothed_freq_dev = delta_f

            now = time.time()
            if self.start_time == 0:
                self.start_time = now

            # Integrate Phase using RAW Delta F for physical correctness
            self.current_phase_deg += delta_f * 360.0 * dt

            self.freq_dev_history.append(delta_f)
            self.phase_history.append(self.current_phase_deg)
            self.time_axis.append(now - self.start_time)

            # --- FLL / Lock Logic ---
            if self.locked:
                # PID Controller
                dt_process = n_samples / sr
                correction = self.pid.update(delta_f, dt_process)

                new_freq = self.gen_frequency + correction

                # Safety Clamp
                new_freq = max(20.0, min(new_freq, 20000.0))

                self.gen_frequency = new_freq

                # Use Adaptive R based on recent NCO variation
                # This assumes the PID jitter represents the "Measurement Noise" for the KF
                self.r_history.append(new_freq)

                # Update R if we have enough history
                if len(self.r_history) >= 2:
                    var_est = np.var(self.r_history)
                    # Add small floor to avoid div by zero or over-confidence
                    self.kf.r = var_est + 1e-12

                # Update Kalman Filter
                self.nco_mean = self.kf.update(new_freq)
                self.nco_std = self.kf.get_std_uncertainty()

                # --- Post-Kalman Averaging for Stability ---
                self.nco_history.append(self.nco_mean)

                if len(self.nco_history) > 0:
                    self.nco_display_mean = np.mean(self.nco_history)
                    # Use std of the filtered history as a stability metric for display
                    self.nco_display_std = np.std(self.nco_history)
                else:
                    self.nco_display_mean = self.nco_mean
                    self.nco_display_std = self.nco_std

            else:
                self.nco_mean = self.gen_frequency
                self.nco_std = 0.0
                self.nco_display_mean = self.gen_frequency
                self.nco_display_std = 0.0

    def clear_distribution_data(self):
        self.frequency_distribution.clear()
        self.interval_distribution.clear()
        self.distribution_timestamps.clear()

    def get_distribution_data(self, mode):
        if mode == "interval":
            return np.asarray(self.interval_distribution, dtype=np.float64), "s"
        return np.asarray(self.frequency_distribution, dtype=np.float64), "Hz"

    def calculate_distribution_stats(self, mode):
        values, unit = self.get_distribution_data(mode)
        values = values[np.isfinite(values)]
        count = int(values.size)
        if count == 0:
            return {"count": 0, "unit": unit}

        mean = float(np.mean(values))
        stddev = float(np.std(values, ddof=1)) if count > 1 else 0.0
        pk_pk = float(np.ptp(values)) if count > 1 else 0.0
        rms_deviation = float(np.sqrt(np.mean((values - mean) ** 2)))
        skewness = float(scipy.stats.skew(values, bias=False)) if count > 2 and stddev > 0 else 0.0
        kurtosis = float(scipy.stats.kurtosis(values, fisher=True, bias=False)) if count > 3 and stddev > 0 else 0.0

        if mode == "interval":
            rms_jitter = rms_deviation
        else:
            intervals = np.asarray(self.interval_distribution, dtype=np.float64)
            intervals = intervals[np.isfinite(intervals)]
            if intervals.size > 0:
                interval_mean = float(np.mean(intervals))
                rms_jitter = float(np.sqrt(np.mean((intervals - interval_mean) ** 2)))
            else:
                rms_jitter = 0.0

        allan_dev = 0.0
        if count > 1:
            diffs = np.diff(values)
            allan_dev = float(np.sqrt(0.5 * np.mean(diffs**2)))

        return {
            "count": count,
            "unit": unit,
            "mean": mean,
            "stddev": stddev,
            "pk_pk": pk_pk,
            "rms_jitter": rms_jitter,
            "skewness": skewness,
            "kurtosis": kurtosis,
            "allan_dev": allan_dev,
            "min": float(np.min(values)),
            "max": float(np.max(values)),
        }


class LockInFrequencyCounterWidget(QWidget):
    def __init__(self, module: LockInFrequencyCounter):
        super().__init__()
        self.module = module
        self.init_ui()
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_ui)
        self.timer.start(100)  # 10Hz

    def get_decimal_places(self, val_std, default=5, max_places=12):
        if val_std <= 0:
            return default
        try:
            std_to_use = val_std

            if std_to_use <= 1e-15:
                return max_places
            places = -int(np.floor(np.log10(std_to_use)))

            if places < 0:
                places = 0
            if places > max_places:
                places = max_places
            return places
        except Exception:
            return default

    def init_ui(self):
        layout = QVBoxLayout(self)

        # -- Controls via Tabs --
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        # =======================
        # Tab 1: Main (Controls + Plots)
        # =======================
        self.tab_main = QWidget()
        main_layout = QVBoxLayout(self.tab_main)

        # -- Top Row: Controls --
        controls_layout = QHBoxLayout()

        # NCO Freq
        lbl_freq = QLabel(tr("NCO Frequency:"))
        self.freq_spin = QDoubleSpinBox()
        self.freq_spin.setRange(20, 20000)
        self.freq_spin.setValue(1000.0)
        self.freq_spin.setSuffix(" Hz")
        self.freq_spin.setDecimals(5)
        self.freq_spin.valueChanged.connect(self.on_freq_changed)

        controls_layout.addWidget(lbl_freq)
        controls_layout.addWidget(self.freq_spin)

        # Lock / FLL
        self.lock_check = QCheckBox(tr("Lock NCO to Signal (FLL)"))
        self.lock_check.toggled.connect(self.on_lock_toggled)
        controls_layout.addWidget(self.lock_check)

        controls_layout.addStretch()

        # Start/Stop
        self.btn_run = QPushButton(tr("Start"))
        self.btn_run.setCheckable(True)
        self.btn_run.clicked.connect(self.on_run_clicked)
        controls_layout.addWidget(self.btn_run)

        main_layout.addLayout(controls_layout)

        # -- Plots (Splitter) --
        splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(splitter)

        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)

        # Frequency Deviation Data
        self.plot_freq = pg.PlotWidget(title=tr("Frequency Deviation Δf (Hz)"))
        self.plot_freq.showGrid(x=True, y=True)
        self.curve_freq = self.plot_freq.plot(pen="g")

        # Phase Data
        self.plot_phase = pg.PlotWidget(title=tr("Integrated Phase φ (deg)"))
        self.plot_phase.showGrid(x=True, y=True)
        self.curve_phase = self.plot_phase.plot(pen="c")

        # Smoothing Controls
        smoothing_layout = QHBoxLayout()
        smoothing_layout.setContentsMargins(5, 0, 5, 0)
        lbl_smooth = QLabel(tr("Plot Smoothing:"))
        self.slider_smooth = QSlider(Qt.Orientation.Horizontal)
        self.slider_smooth.setRange(1, 50)
        self.slider_smooth.setValue(1)
        self.slider_smooth.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.slider_smooth.setTickInterval(5)
        self.lbl_smooth_val = QLabel("1")
        self.slider_smooth.valueChanged.connect(lambda v: self.lbl_smooth_val.setText(str(v)))

        smoothing_layout.addWidget(lbl_smooth)
        smoothing_layout.addWidget(self.slider_smooth)
        smoothing_layout.addWidget(self.lbl_smooth_val)

        left_layout.addLayout(smoothing_layout)
        left_layout.addWidget(self.plot_freq)
        left_layout.addWidget(self.plot_phase)

        splitter.addWidget(left_widget)

        # I-Q Plot
        self.plot_iq = pg.PlotWidget(title=tr("I-Q Phase Space"))
        self.plot_iq.setAspectLocked(True)
        self.plot_iq.showGrid(x=True, y=True)
        self.plot_iq.setXRange(-1, 1)
        self.plot_iq.setYRange(-1, 1)
        self.scatter_iq = pg.ScatterPlotItem(pen=None, brush="y", size=5)
        self.plot_iq.addItem(self.scatter_iq)
        splitter.addWidget(self.plot_iq)

        splitter.setSizes([600, 300])

        self.tabs.addTab(self.tab_main, tr("Main"))

        # =======================
        # Tab 2: Distribution / TIC Statistics
        # =======================
        self.tab_distribution = QWidget()
        distribution_layout = QVBoxLayout(self.tab_distribution)

        distribution_controls = QHBoxLayout()
        distribution_controls.addWidget(QLabel(tr("Distribution View:")))

        self.distribution_mode_combo = QComboBox()
        self.distribution_mode_combo.addItems([tr("Frequency Histogram"), tr("Time Interval Histogram")])
        self.distribution_mode_combo.currentIndexChanged.connect(self.on_distribution_mode_changed)
        distribution_controls.addWidget(self.distribution_mode_combo)

        distribution_controls.addWidget(QLabel(tr("Bins:")))
        self.hist_bins_spin = QSpinBox()
        self.hist_bins_spin.setRange(5, 500)
        self.hist_bins_spin.setValue(80)
        self.hist_bins_spin.valueChanged.connect(self.on_hist_bins_changed)
        distribution_controls.addWidget(self.hist_bins_spin)

        self.btn_clear_distribution = QPushButton(tr("Clear Distribution"))
        self.btn_clear_distribution.clicked.connect(self.on_clear_distribution_clicked)
        distribution_controls.addWidget(self.btn_clear_distribution)
        distribution_controls.addStretch()
        distribution_layout.addLayout(distribution_controls)

        distribution_splitter = QSplitter(Qt.Orientation.Horizontal)
        distribution_layout.addWidget(distribution_splitter)

        self.plot_distribution = pg.PlotWidget(title=tr("Frequency Histogram"))
        self.plot_distribution.showGrid(x=True, y=True)
        self.plot_distribution.setLabel("left", tr("Count"))
        self.plot_distribution.setLabel("bottom", tr("Frequency"), units="Hz")
        self.histogram_item = None
        distribution_splitter.addWidget(self.plot_distribution)

        group_distribution_stats = QGroupBox(tr("Distribution Statistics"))
        stats_grid = QGridLayout(group_distribution_stats)
        self.distribution_stats_labels = {}
        stat_rows = [
            ("count", tr("Samples")),
            ("mean", tr("Mean")),
            ("stddev", tr("Std Dev")),
            ("pk_pk", tr("Pk-Pk")),
            ("rms_jitter", tr("RMS Jitter")),
            ("allan_dev", tr("Allan Deviation")),
            ("skewness", tr("Skewness")),
            ("kurtosis", tr("Kurtosis (excess)")),
            ("min", tr("Min")),
            ("max", tr("Max")),
        ]
        for row, (key, label) in enumerate(stat_rows):
            stats_grid.addWidget(QLabel(label + ":"), row, 0)
            value_label = QLabel("--")
            value_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            stats_grid.addWidget(value_label, row, 1)
            self.distribution_stats_labels[key] = value_label

        distribution_splitter.addWidget(group_distribution_stats)
        distribution_splitter.setSizes([650, 250])

        self.tabs.addTab(self.tab_distribution, tr("Distribution"))

        # =======================
        # Tab 3: Settings (PID, Input, Stats)
        # =======================
        self.tab_settings = QWidget()
        settings_layout = QVBoxLayout(self.tab_settings)

        # -- Group 1: Input & Gate --
        group_input = QGroupBox(tr("Input & Signal Detection"))
        form_input = QFormLayout(group_input)

        # Ref Mode
        self.ref_combo = QComboBox()
        self.ref_combo.addItems([tr("Internal (NCO)"), tr("Loopback (Ref Out)")])
        self.ref_combo.currentIndexChanged.connect(self.on_ref_mode_changed)
        form_input.addRow(tr("Reference Mode:"), self.ref_combo)

        # Output Channel (L/R) for Ref Out
        self.output_ch_combo = QComboBox()
        self.output_ch_combo.addItems([tr("Ch 1 (L)"), tr("Ch 2 (R)")])
        self.output_ch_combo.setCurrentIndex(int(getattr(self.module, "ref_channel", 1)))
        self.output_ch_combo.currentIndexChanged.connect(self.on_output_channel_changed)
        form_input.addRow(tr("Output Channel:"), self.output_ch_combo)

        # Input Channel (L/R)
        self.input_ch_combo = QComboBox()
        self.input_ch_combo.addItems([tr("Ch 1 (L)"), tr("Ch 2 (R)")])
        self.input_ch_combo.setCurrentIndex(int(getattr(self.module, "signal_channel", 0)))
        self.input_ch_combo.currentIndexChanged.connect(self.on_input_channel_changed)
        form_input.addRow(tr("Channel:"), self.input_ch_combo)

        # Initialize enabling state
        self.on_ref_mode_changed(self.ref_combo.currentIndex())

        # Signal gate
        self.gate_spin = QDoubleSpinBox()
        self.gate_spin.setRange(-120.0, 0.0)
        self.gate_spin.setDecimals(1)
        self.gate_spin.setSingleStep(1.0)
        self.gate_spin.setValue(float(getattr(self.module, "gate_threshold_db", -60.0)))
        self.gate_spin.setSuffix(" dB")
        self.gate_spin.valueChanged.connect(self.on_gate_changed)
        form_input.addRow(tr("Gate Threshold:"), self.gate_spin)

        settings_layout.addWidget(group_input)

        # -- Group 2: Statistics / Display --
        group_stats = QGroupBox(tr("Statistics & Averaging"))
        form_stats = QFormLayout(group_stats)

        # NCO Averaging Settings
        self.avg_spin = QSpinBox()
        self.avg_spin.setRange(1, 1000)
        self.avg_spin.setValue(self.module.nco_avg_count)
        self.avg_spin.valueChanged.connect(self.on_avg_changed)
        form_stats.addRow(tr("Avg Count (KF-Q & Display):"), self.avg_spin)

        # Variance Display
        self.lbl_nco_var = QLabel("σ: 0.00 Hz")
        form_stats.addRow(tr("Display Uncertainty:"), self.lbl_nco_var)

        settings_layout.addWidget(group_stats)

        # -- Group 3: PID Parameters --
        group_pid = QGroupBox(tr("PID Control Loop"))
        form_pid = QFormLayout(group_pid)

        self.kp_spin = QDoubleSpinBox()
        self.kp_spin.setRange(0.0, 100.0)
        self.kp_spin.setSingleStep(0.1)
        self.kp_spin.setValue(self.module.pid.kp)
        self.kp_spin.valueChanged.connect(self.on_pid_changed)
        form_pid.addRow(tr("Proportional (Kp):"), self.kp_spin)

        self.ki_spin = QDoubleSpinBox()
        self.kp_spin.setRange(0.0, 100.0)
        self.ki_spin.setSingleStep(0.1)
        self.ki_spin.setValue(self.module.pid.ki)
        self.ki_spin.valueChanged.connect(self.on_pid_changed)
        form_pid.addRow(tr("Integral (Ki):"), self.ki_spin)

        self.kd_spin = QDoubleSpinBox()
        self.kd_spin.setRange(0.0, 100.0)
        self.kd_spin.setSingleStep(0.001)
        self.kd_spin.setDecimals(4)
        self.kd_spin.setValue(self.module.pid.kd)
        self.kd_spin.valueChanged.connect(self.on_pid_changed)
        form_pid.addRow(tr("Derivative (Kd):"), self.kd_spin)

        settings_layout.addWidget(group_pid)
        settings_layout.addStretch()  # Push everything up

        self.tabs.addTab(self.tab_settings, tr("Settings"))
        self.tabs.currentChanged.connect(self.on_tab_changed)

        # -- Meters --
        meters_layout = QHBoxLayout()

        # Signal indicator (shown only when signal is missing)
        self.lbl_signal_status = QLabel(tr("No Signal"))
        self.lbl_signal_status.setStyleSheet("font-size: 16px; font-weight: bold;")
        self.lbl_signal_status.setVisible(False)
        meters_layout.addWidget(self.lbl_signal_status)

        self.lbl_delta_f = QLabel(tr("Δf: {0:.6f} Hz").format(0.0))
        self.lbl_delta_f.setStyleSheet("font-size: 16px; font-weight: bold;")
        meters_layout.addWidget(self.lbl_delta_f)

        self.lbl_phase = QLabel(tr("φ: {0:.2f}°").format(0.0))
        self.lbl_phase.setStyleSheet("font-size: 16px; font-weight: bold;")
        meters_layout.addWidget(self.lbl_phase)

        layout.addLayout(meters_layout)

    def on_freq_changed(self, val):
        self.module.gen_frequency = val

    def on_ref_mode_changed(self, idx):
        modes = ["internal", "loopback"]
        self.module.ref_mode = modes[idx]
        is_loopback = idx == 1
        self.output_ch_combo.setEnabled(is_loopback)

    def on_output_channel_changed(self, idx):
        self.module.ref_channel = int(idx)

    def on_input_channel_changed(self, idx):
        self.module.signal_channel = int(idx)

    def on_gate_changed(self, val):
        self.module.gate_threshold_db = float(val)

    def on_lock_toggled(self, checked):
        self.module.locked = checked
        self.freq_spin.setReadOnly(checked)

    def on_pid_changed(self):
        self.module.pid.kp = self.kp_spin.value()
        self.module.pid.ki = self.ki_spin.value()
        self.module.pid.kd = self.kd_spin.value()

    def on_avg_changed(self, val):
        self.module.nco_avg_count = int(val)
        self.module.update_kalman_params()
        # Resize deque for display averaging
        current_data = list(self.module.nco_history)
        self.module.nco_history = deque(current_data, maxlen=self.module.nco_avg_count)

    def on_distribution_mode_changed(self, _idx):
        self.update_distribution_plot()

    def on_hist_bins_changed(self, _val):
        self.update_distribution_plot()

    def on_clear_distribution_clicked(self):
        self.module.clear_distribution_data()
        self.update_distribution_plot()

    def on_tab_changed(self, _idx):
        if self.tabs.currentWidget() == self.tab_distribution:
            self.update_distribution_plot()

    def on_run_clicked(self, checked):
        if checked:
            self.module.start_analysis()
            self.btn_run.setText(tr("Stop"))
            self.btn_run.setStyleSheet("background-color: #ffcccc;")
        else:
            self.module.stop_analysis()
            self.btn_run.setText(tr("Start"))
            self.btn_run.setStyleSheet("")

    def _distribution_mode(self):
        if self.distribution_mode_combo.currentIndex() == 1:
            return "interval"
        return "frequency"

    def _format_value(self, value, unit="", sig_figs=6):
        if value is None:
            return "--"
        try:
            x = float(value)
        except (TypeError, ValueError):
            return "--"
        if not np.isfinite(x):
            return "--"
        if unit in ("Hz", "s"):
            return format_si(x, unit, sig_figs=sig_figs)
        return f"{x:.{int(sig_figs)}g}"

    def update_distribution_plot(self):
        mode = self._distribution_mode()
        data, unit = self.module.get_distribution_data(mode)
        data = data[np.isfinite(data)]

        if self.histogram_item is not None:
            self.plot_distribution.removeItem(self.histogram_item)
            self.histogram_item = None

        if mode == "interval":
            self.plot_distribution.setTitle(tr("Time Interval Histogram"))
            self.plot_distribution.setLabel("bottom", tr("Time Interval"), units="s")
        else:
            self.plot_distribution.setTitle(tr("Frequency Histogram"))
            self.plot_distribution.setLabel("bottom", tr("Frequency"), units="Hz")
        self.plot_distribution.setLabel("left", tr("Count"))

        if data.size > 0:
            counts, edges = np.histogram(data, bins=int(self.hist_bins_spin.value()))
            centers = (edges[:-1] + edges[1:]) / 2.0
            widths = np.diff(edges)
            self.histogram_item = pg.BarGraphItem(
                x=centers, height=counts, width=widths, brush=(80, 180, 255, 160), pen="c"
            )
            self.plot_distribution.addItem(self.histogram_item)

        stats = self.module.calculate_distribution_stats(mode)
        count = int(stats.get("count", 0))
        self.distribution_stats_labels["count"].setText(str(count))

        if count == 0:
            for key, label in self.distribution_stats_labels.items():
                if key != "count":
                    label.setText("--")
            return

        value_unit = str(stats.get("unit", unit))
        for key in ("mean", "min", "max"):
            self.distribution_stats_labels[key].setText(self._format_value(stats.get(key), value_unit, sig_figs=12))
        for key in ("stddev", "pk_pk", "allan_dev"):
            self.distribution_stats_labels[key].setText(self._format_value(stats.get(key), value_unit, sig_figs=6))
        self.distribution_stats_labels["rms_jitter"].setText(
            self._format_value(stats.get("rms_jitter"), "s", sig_figs=6)
        )
        self.distribution_stats_labels["skewness"].setText(self._format_value(stats.get("skewness"), sig_figs=6))
        self.distribution_stats_labels["kurtosis"].setText(self._format_value(stats.get("kurtosis"), sig_figs=6))

    def update_ui(self):
        if self.module.is_running:
            self.module.process_data()
            if self.tabs.currentWidget() == self.tab_distribution:
                self.update_distribution_plot()

            # Signal present indicator
            has_signal = bool(getattr(self.module, "signal_present", False))
            self.lbl_signal_status.setVisible(not has_signal)

            delta_f_smooth = self.module.smoothed_freq_dev

            t_data = list(self.module.time_axis)
            f_data = list(self.module.freq_dev_history)
            p_data = list(self.module.phase_history)

            # --- Smoothing Logic ---
            smoothing_window = self.slider_smooth.value()

            # Apply smoothing only if window > 1 and we have enough data
            if smoothing_window > 1 and len(f_data) >= smoothing_window:
                # Use a simple moving average convolution
                kernel = np.ones(smoothing_window) / smoothing_window

                f_smoothed = np.convolve(f_data, kernel, mode="valid")
                p_smoothed = np.convolve(p_data, kernel, mode="valid")

                # The 'valid' mode reduces the output size by window-1.
                # We need to slice the time axis to match the end of the smoothed data
                # (which corresponds to the latest times).
                # t_data should be sliced from [window-1:]
                t_plot = t_data[smoothing_window - 1 :]

                self.curve_freq.setData(t_plot, f_smoothed)
                self.curve_phase.setData(t_plot, p_smoothed)
            else:
                # Raw Plot
                if len(t_data) > 0:
                    self.curve_freq.setData(t_data, f_data)
                    self.curve_phase.setData(t_data, p_data)

            if len(t_data) > 0:
                i_data = list(self.module.iq_history_i)
                q_data = list(self.module.iq_history_q)

                n_tail = 50
                if len(i_data) > n_tail:
                    self.scatter_iq.setData(i_data[-n_tail:], q_data[-n_tail:])
                else:
                    self.scatter_iq.setData(i_data, q_data)

            # Meters (Smoothed for consistency)
            self.lbl_delta_f.setText(tr("Δf: {0:.6f} Hz").format(delta_f_smooth))
            self.lbl_phase.setText(tr("φ: {0:.2f}°").format(self.module.current_phase_deg))

            # Update NCO display if locked (and changed)
            if self.module.locked:
                self.freq_spin.blockSignals(True)

                # Use Display Stats (Averaged) for UI
                decimals = self.get_decimal_places(self.module.nco_display_std, default=5, max_places=12)
                self.freq_spin.setDecimals(decimals)

                self.freq_spin.setValue(self.module.nco_display_mean)
                self.freq_spin.blockSignals(False)

            # Update Variance Label
            self.lbl_nco_var.setText(f"σ: {self.module.nco_display_std:.4e} Hz")
