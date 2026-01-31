import argparse
from collections import deque

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
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

        # NCO Statistics
        self.nco_history = deque(maxlen=10)
        self.nco_avg_count = 10
        self.nco_mean = 1000.0
        self.nco_std = 0.0

        # Stability Stats


        # Internal State
        self._nco_phase = 0.0
        self._last_unwrapped_phase = 0.0
        self._first_run = True

        # Startup transient handling
        self._samples_received = 0
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

    def run(self, args: argparse.Namespace):
        print("CLI not implemented")

    def get_widget(self):
        return LockInFrequencyCounterWidget(self)

    def start_analysis(self):
        if self.is_running:
            return

        self.is_running = True
        self.input_data = np.zeros((self.buffer_size, 2))

        # Reset State
        self._nco_phase = 0.0
        self._last_unwrapped_phase = 0.0
        self._first_run = True
        self.start_time = 0
        self.smoothed_freq_dev = 0.0
        self.current_phase_deg = 0.0

        self.current_amp_db = -120.0
        self.signal_present = False
        self.pid.reset()
        self.nco_history.clear()
        self.nco_mean = self.gen_frequency
        self.nco_std = 0.0

        self._samples_received = 0
        self._discard_initial_estimates = 3
        self._estimates_discarded = 0

        self.time_axis.clear()
        self.freq_dev_history.clear()
        self.phase_history.clear()
        self.iq_history_i.clear()
        self.iq_history_q.clear()

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
                t = (np.arange(frames) + self._nco_phase) / sample_rate
                sig = 0.5 * np.cos(2 * np.pi * self.gen_frequency * t)
                outdata[:, 0] = sig
                outdata[:, 1] = sig

            self._nco_phase += frames

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
        seg_len = n_samples // n_segments

        # Calculate Phase for each segment
        seg_phases = []
        seg_centers = []

        for i in range(n_segments):
            start = i * seg_len
            end = start + seg_len
            segment = z[start:end]
            win = np.hanning(len(segment))
            avg = np.mean(segment * win)

            if np.abs(avg) < 1e-9:
                self.signal_present = False
                return  # Noise

            phi = np.angle(avg)
            seg_phases.append(phi)
            seg_centers.append(start + seg_len / 2)

        # Unwrap phases across segments
        seg_phases_unwrapped = np.unwrap(seg_phases)

        # Helper time array
        t_centers = np.array(seg_centers) / sr

        if len(t_centers) > 1:
            slope, intercept = np.polyfit(t_centers, seg_phases_unwrapped, 1)
            delta_f = slope / (2 * np.pi)

            if self._estimates_discarded < self._discard_initial_estimates:
                self._estimates_discarded += 1
                # Keep the UI stable at start: don't integrate or append history yet.
                self.current_freq_dev = 0.0
                self.smoothed_freq_dev = 0.0
                return

            # Mean Vector for IQ
            mean_vec = np.mean(z)
            self.iq_history_i.append(np.real(mean_vec))
            self.iq_history_q.append(np.imag(mean_vec))

            self.signal_present = True

            self.current_freq_dev = delta_f

            # Smoothing (EMA)
            dt = n_samples / sr  # approx time per buffer
            tau = self.smoothing_tau
            if tau > 0:
                alpha = dt / (tau + dt)
                # Initialize smoothed value if first valid
                if self.start_time == 0:
                    self.smoothed_freq_dev = delta_f
                else:
                    self.smoothed_freq_dev = self.smoothed_freq_dev + alpha * (delta_f - self.smoothed_freq_dev)
            else:
                self.smoothed_freq_dev = delta_f


            import time

            now = time.time()
            if self.start_time == 0:
                self.start_time = now

            # Integrate Phase using RAW Delta F for physical correctness
            self.current_phase_deg += delta_f * 360.0 * 0.1

            self.freq_dev_history.append(delta_f)
            self.phase_history.append(self.current_phase_deg)
            self.time_axis.append(now - self.start_time)

            # --- FLL / Lock Logic ---
            if self.locked:
                # PID Controller
                # Error = Delta F (Signal - NCO)
                # If Delta F is positive, Signal > NCO, so we need to increase NCO freq.
                # correction = PID(error)

                dt_process = n_samples / sr
                correction = self.pid.update(delta_f, dt_process)

                new_freq = self.gen_frequency + correction

                # Safety Clamp
                new_freq = max(20.0, min(new_freq, 20000.0))

                self.gen_frequency = new_freq

                # Statistics
                self.nco_history.append(new_freq)
                if len(self.nco_history) > self.nco_avg_count:
                     # Resize if needed (deque handles appending but maxlen might need update if changed at runtime)
                     # For simplicity, we just rely on maxlen if it was fixed, but here user can change it.
                     # So we'll manually slice if needed or re-create deque in setter.
                     pass
                
                # Calculate Stats
                data = list(self.nco_history)
                if len(data) > 0:
                    self.nco_mean = float(np.mean(data))
                    self.nco_std = float(np.std(data))
                else:
                    self.nco_mean = new_freq
                    self.nco_std = 0.0



class LockInFrequencyCounterWidget(QWidget):
    def __init__(self, module: LockInFrequencyCounter):
        super().__init__()
        self.module = module
        self.init_ui()
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_ui)
        self.timer.start(100)  # 10Hz



    def get_decimal_places(self, val_std, default=5, max_places=6):
        if val_std <= 0:
            return default
        try:
            std_to_use = val_std

            if std_to_use <= 1e-9:
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
        # Using a small form layout or just label+spinbox
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
        from PyQt6.QtWidgets import QCheckBox
        self.lock_check = QCheckBox(tr("Lock NCO to Signal (FLL)"))
        self.lock_check.toggled.connect(self.on_lock_toggled)
        controls_layout.addWidget(self.lock_check)

        # Spacer to push Start button to the right or keep it near? 
        # Let's keep it compact.
        controls_layout.addStretch()

        # Start/Stop
        self.btn_run = QPushButton(tr("Start"))
        self.btn_run.setCheckable(True)
        self.btn_run.clicked.connect(self.on_run_clicked)
        controls_layout.addWidget(self.btn_run)

        main_layout.addLayout(controls_layout)

        # -- Plots (Splitter) --
        # We move the splitter INSIDE the Main tab so it takes up the rest of the space
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
        # Tab 2: Settings (PID, Input, Stats)
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

        # Input Channel (L/R)
        self.input_ch_combo = QComboBox()
        self.input_ch_combo.addItems([tr("Ch 1"), tr("Ch 2")])
        self.input_ch_combo.setCurrentIndex(int(getattr(self.module, "signal_channel", 0)))
        self.input_ch_combo.currentIndexChanged.connect(self.on_input_channel_changed)
        form_input.addRow(tr("Channel:"), self.input_ch_combo)

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
        form_stats.addRow(tr("NCO Avg Count:"), self.avg_spin)

        # Variance Display
        self.lbl_nco_var = QLabel("σ: 0.00 Hz")
        form_stats.addRow(tr("NCO Std Dev:"), self.lbl_nco_var)

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
        settings_layout.addStretch() # Push everything up

        self.tabs.addTab(self.tab_settings, tr("Settings"))

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

        # Disable Lock (FLL) if in Loopback/Ref Out mode
        # Index 1 is Loopback
        is_loopback = (idx == 1)
        if is_loopback:
            self.lock_check.setChecked(False)
            self.lock_check.setEnabled(False)
        else:
            self.lock_check.setEnabled(True)

    def on_input_channel_changed(self, idx):
        self.module.signal_channel = int(idx)

    def on_gate_changed(self, val):
        self.module.gate_threshold_db = float(val)

    def on_lock_toggled(self, checked):
        self.module.locked = checked
        # When locking is enabled, disable manual editing logic temporarily if needed
        # but here we just update module state.
        self.freq_spin.setReadOnly(checked) # Prevent manual fight

    def on_pid_changed(self):
        self.module.pid.kp = self.kp_spin.value()
        self.module.pid.ki = self.ki_spin.value()
        self.module.pid.kd = self.kd_spin.value()
        
    def on_avg_changed(self, val):
        self.module.nco_avg_count = int(val)
        # Resize deque
        current_data = list(self.module.nco_history)
        self.module.nco_history = deque(current_data, maxlen=self.module.nco_avg_count)

    def on_run_clicked(self, checked):
        if checked:
            self.module.start_analysis()
            self.btn_run.setText(tr("Stop"))
            self.btn_run.setStyleSheet("background-color: #ffcccc;")
        else:
            self.module.stop_analysis()
            self.btn_run.setText(tr("Start"))
            self.btn_run.setStyleSheet("")

    def update_ui(self):
        if self.module.is_running:
            self.module.process_data()

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
                
                f_smoothed = np.convolve(f_data, kernel, mode='valid')
                p_smoothed = np.convolve(p_data, kernel, mode='valid')
                
                # The 'valid' mode reduces the output size by window-1.
                # We need to slice the time axis to match the end of the smoothed data
                # (which corresponds to the latest times).
                # t_data should be sliced from [window-1:]
                t_plot = t_data[smoothing_window - 1:]
                
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
                # Block signals to prevent on_freq_changed loop
                self.freq_spin.blockSignals(True)

                # Dynamic Precision Logic
                # Only apply dynamic precision if averaging is actually enabled (>= 2 samples)
                if self.module.nco_avg_count >= 2:
                    decimals = self.get_decimal_places(self.module.nco_std, default=5, max_places=6)
                    self.freq_spin.setDecimals(decimals)
                else:
                    self.freq_spin.setDecimals(5)

                # Display MEAN value if we have history, else current
                if len(self.module.nco_history) > 0:
                     self.freq_spin.setValue(self.module.nco_mean)
                else:
                     self.freq_spin.setValue(self.module.gen_frequency)
                self.freq_spin.blockSignals(False)
                
            # Update Variance Label
            self.lbl_nco_var.setText(f"σ: {self.module.nco_std:.4e} Hz")

