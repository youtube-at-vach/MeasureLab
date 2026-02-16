
import threading
import time
import queue

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.core.audio_engine import AudioEngine
from src.core.localization import tr
from src.measurement_modules.base import MeasurementModule


class OnePPSMonitor(MeasurementModule):
    """
    Experimental widget to monitor 1PPS signals and measure sample intervals.
    """

    def __init__(self, audio_engine: AudioEngine):
        self.audio_engine = audio_engine
        self.is_running = False
        self._lock = threading.Lock()

        self.data_queue = queue.Queue()
        self.process_thread = None

        # User settings
        self.threshold_fs = 0.5
        self.hysteresis_fs = 0.05
        self.target_pps = 1.0
        self.nominal_rate = 48000.0

        # Filter settings (Robust Median/MAD)
        self.filter_enabled = False
        self.filter_window_size = 5
        self.filter_tolerance_sigma = 3.0

        # Filter state
        self._filter_window = []  # List of recent valid deltas

        # Analysis state
        self._total_samples_processed = 0
        self._last_trigger_sample_index = -1
        self._first_trigger_sample_index = -1  # To track cumulative drift
        self._first_trigger_sample_index = -1  # To track cumulative drift
        self._triggered = False
        self._pulses_detected = 0
        self.warmup_count = 7

        # Triggered Waveform Visualization
        self.vis_window_pre = 0.5
        self.vis_window_post = 0.5
        self.vis_buffer_size = 96000 # 2 seconds circular buffer to hold history for pre-trigger
        self.vis_buffer = np.zeros(self.vis_buffer_size, dtype=np.float32)
        self.vis_write_pos = 0

        self.last_trig_waveform = None
        self.last_trig_time = 0
        self.last_trig_time = 0
        self._capture_trigger_index = -1

        # Regression State (Online Least Squares)
        # y = mx + c
        # x = Pulse Count (Seconds)
        # y = Sample Index (Samples from start)
        # m = Sample Rate (Slope)
        self._reg_n = 0
        self._reg_sx = 0.0
        self._reg_sy = 0.0
        self._reg_sxx = 0.0
        self._reg_sxy = 0.0

        # Data storage for plotting
        # We store PPM values now
        self.max_history = 3600
        self.instant_ppm_buffer = np.zeros(self.max_history, dtype=np.float64)
        self.cumulative_ppm_buffer = np.zeros(self.max_history, dtype=np.float64)
        self.time_buffer = np.zeros(self.max_history, dtype=np.float64)

        self.history_write_pos = 0
        self.history_filled = 0
        self._start_time = 0.0

        self.callback_id = None

    @property
    def name(self) -> str:
        return "1PPS Monitor"

    @property
    def description(self) -> str:
        return "Monitor 1PPS signal intervals (Experimental)."

    def get_widget(self):
        return OnePPSMonitorWidget(self)



    def start_analysis(self):
        if self.is_running:
            return

        self.is_running = True
        self._start_time = time.time()

        # Reset State
        self._total_samples_processed = 0
        self._last_trigger_sample_index = -1
        self._first_trigger_sample_index = -1
        self._last_trigger_sample_index = -1
        self._first_trigger_sample_index = -1
        self._triggered = False
        self._pulses_detected = 0

        self._reg_n = 0
        self._reg_sx = 0.0
        self._reg_sy = 0.0
        self._reg_sxx = 0.0
        self._reg_sxy = 0.0

        self.instant_ppm_buffer.fill(np.nan)
        self.cumulative_ppm_buffer.fill(np.nan)
        self.time_buffer.fill(np.nan)

        self.history_write_pos = 0
        self.history_filled = 0
        self._filter_window = []

        # Reset visualization buffer
        self.vis_buffer.fill(0)
        self.vis_write_pos = 0
        self.last_trig_waveform = None
        self.vis_write_pos = 0
        self.last_trig_waveform = None
        self._capture_trigger_index = -1

        # Clear queue
        while not self.data_queue.empty():
            try:
                self.data_queue.get_nowait()
            except queue.Empty:
                break

        # Start Processing Thread
        self.process_thread = threading.Thread(target=self._process_loop, daemon=True)
        self.process_thread.start()

        def callback(indata, outdata, frames, time_info, status):
            if indata is None:
                return

            if indata.shape[1] > 0:
                # Copy data to avoid buffer issues and push to queue
                # indata is only valid during the callback
                sig = indata[:, 0].copy()
                self.data_queue.put((sig, frames))

            outdata.fill(0)

        self.callback_id = self.audio_engine.register_callback(callback)

    def get_pulse_count(self):
        with self._lock:
            return self._pulses_detected


    def stop_analysis(self):
        if not self.is_running:
            return

        if self.callback_id is not None:
            self.audio_engine.unregister_callback(self.callback_id)
            self.callback_id = None

        self.is_running = False

        # Signal thread to stop (using is_running flag or None sentinel)
        self.data_queue.put(None)

        if self.process_thread:
            self.process_thread.join(timeout=1.0)
            self.process_thread = None

    def get_latest_waveform(self):
        """Returns the last triggered waveform window or None."""
        with self._lock:
            if self.last_trig_waveform is not None:
                return self.last_trig_waveform.copy()
            return None

    def _process_loop(self):
        while self.is_running:
            try:
                item = self.data_queue.get(timeout=0.1)
                if item is None:
                    break

                sig, frames = item

                # Update Visualization Buffer
                # We do this under lock to prevent tearing when reading? 
                # Actually, for visualization, tearing is acceptable usually, but let's be safe-ish or just atomic write.
                # Since we want a rolling view, we just write to the ring buffer.
                # If frames > buffer size, we just take the last part.

                write_len = min(frames, self.vis_buffer_size)
                src_data = sig[-write_len:].astype(np.float32)

                # Check for buffer resize if rate changed drastically?
                # For now assume fixed size enough for ~1s at 48k. 
                # If 192k, it will be 0.25s, which might be too short for 1PPS.
                # Let's dynamically resize if needed in future, but for now fixed is okay or we check nominal.

                # Logic for ring buffer write
                with self._lock:
                     # Calculate split
                    remain = self.vis_buffer_size - self.vis_write_pos
                    if write_len <= remain:
                        self.vis_buffer[self.vis_write_pos : self.vis_write_pos + write_len] = src_data
                        self.vis_write_pos = (self.vis_write_pos + write_len) % self.vis_buffer_size
                    else:
                        # Split write
                        part1 = remain
                        part2 = write_len - remain
                        self.vis_buffer[self.vis_write_pos : self.vis_buffer_size] = src_data[:part1]
                        self.vis_buffer[0 : part2] = src_data[part1:]
                        self.vis_write_pos = part2

                # Processing Logic
                # Optimization: If signal is way below threshold everywhere, skip.
                if np.max(sig) < (self.threshold_fs - self.hysteresis_fs):
                    self._total_samples_processed += frames
                    if self._triggered:
                         self._triggered = False

                    # Still need to handle waveform capture if active
                    # Still need to handle waveform capture if active
                    if self._capture_trigger_index != -1:
                         # Current head is self._total_samples_processed + frames (since we skipped loop)
                         # We skip processing loop, but frames are counted.
                         # Check if enough samples:
                         current_head = self._total_samples_processed + frames
                         required_post = int(self.vis_window_post * self.nominal_rate)
                         if (current_head - self._capture_trigger_index) >= required_post:
                              self._capture_waveform(required_post, current_head)

                    continue

                th_high = self.threshold_fs
                th_low = self.threshold_fs - self.hysteresis_fs

                t_samples = self._total_samples_processed
                sample_rate = self.nominal_rate
                expected_interval = sample_rate / self.target_pps if self.target_pps > 0 else sample_rate

                # Local copies for speed
                reg_n = self._reg_n
                reg_sx = self._reg_sx
                reg_sy = self._reg_sy
                reg_sxx = self._reg_sxx
                reg_sxy = self._reg_sxy

                for i in range(frames):
                    s = sig[i]
                    abs_pos = t_samples + i

                    if not self._triggered:
                        if s >= th_high:
                            self._triggered = True

                            # --- Triggered Visualization Capture ---
                            # Capture window around this point
                            # We are at 'abs_pos'. The 'sig' we are processing is in the buffer?
                            # 'sig[i]' is current sample. 
                            # We need to extract from buffer where we just wrote.
                            # Since we write 'sig' to buffer at the start of loop, 'sig[i]' corresponds to
                            # the latest data.
                            # 'vis_write_pos' points to NEXT write.
                            # Current sample 'sig[i]' is at (vis_write_pos - (frames - i)) % size

                            # Let's simplify: We just detected a trigger.
                            # We want [-pre, +post] window. If we have enough post data?
                            # No, we are processing real-time. We don't have post data yet.
                            # So we just mark the trigger time/index.
                            # AND we can immediately extract the PRE-trigger part from buffer.
                            # BUT we need to wait for POST-trigger part.
                            # So, let's just record "samples_since_trigger = 0" and "capturing = True"


                            # --- Triggered Visualization Capture ---
                            if self._capture_trigger_index == -1:
                                self._capture_trigger_index = abs_pos

                            # Rising edge detected

                            # First pulse logic
                            if self._first_trigger_sample_index == -1:
                                self._first_trigger_sample_index = abs_pos
                                self._last_trigger_sample_index = abs_pos

                                # Initialize regression
                                reg_n = 1
                                reg_sx = 0.0
                                reg_sy = 0.0
                                reg_sxx = 0.0
                                reg_sxy = 0.0

                                # Count first pulse (even if not used for interval yet)
                                self._pulses_detected += 1

                            else:
                                # Instantaneous calculation
                                delta = abs_pos - self._last_trigger_sample_index

                                # 0. Gate Filter (Hard Rejection) - REMOVED
                                # We no longer reject based on 50% deviation.
                                # is_gross_outlier = abs(delta - nominal) > gate_threshold
                                is_gross_outlier = False

                                accepted = True

                                # 1. MAD/Median Filter
                                if accepted and self.filter_enabled and len(self._filter_window) >= self.filter_window_size:
                                    window = np.array(self._filter_window)
                                    med = np.median(window)
                                    mad = np.median(np.abs(window - med))
                                    # If MAD is 0 (perfect signal), use a tiny epsilon to avoid div by zero logic or too strict
                                    mad = max(mad, 1e-9)

                                    sigma = 1.4826 * mad
                                    thresh_val = max(sigma * self.filter_tolerance_sigma, 1.0) # at least 1 sample

                                    if abs(delta - med) > thresh_val:
                                        accepted = False

                                if accepted:
                                    self._pulses_detected += 1
                                    self._filter_window.append(delta)
                                    if len(self._filter_window) > self.filter_window_size:
                                        self._filter_window.pop(0)

                                    # 2. Instantaneous Result
                                    error_samples = delta - expected_interval
                                    # PPM = (Error / Expected) * 1e6
                                    # Seconds Error = Error / Sample_Rate
                                    instant_ppm = (error_samples / expected_interval) * 1e6 if expected_interval != 0 else 0

                                    # x = Pulse Count (approx seconds)
                                    # y = Actual Sample Position relative to first
                                    y_val = abs_pos - self._first_trigger_sample_index

                                    # x is the index of the pulse.
                                    # Since we might have missed pulses, let's estimate index from y_val
                                    x_val = round(y_val / expected_interval)

                                    reg_n += 1
                                    reg_sx += x_val
                                    reg_sy += y_val
                                    reg_sxx += x_val * x_val
                                    reg_sxy += x_val * y_val

                                    # Slope Calculation
                                    denom = (reg_n * reg_sxx - reg_sx * reg_sx)
                                    if denom != 0:
                                        slope = (reg_n * reg_sxy - reg_sx * reg_sy) / denom
                                        # Slope is Samples per Pulse.
                                        # Nominal Samples per Pulse is expected_interval.
                                        # PPM Error = (measured_slope - expected) / expected
                                        cumulative_ppm = ((slope - expected_interval) / expected_interval) * 1e6
                                    else:
                                        cumulative_ppm = 0.0

                                    # Store result
                                    if self._pulses_detected > self.warmup_count:
                                        with self._lock:
                                            idx = self.history_write_pos
                                            self.instant_ppm_buffer[idx] = instant_ppm
                                            self.cumulative_ppm_buffer[idx] = cumulative_ppm
                                            self.time_buffer[idx] = time.time() - self._start_time

                                            self.history_write_pos = (idx + 1) % self.max_history
                                            self.history_filled = min(self.history_filled + 1, self.max_history)


                                # 4. Update Trigger State
                                # FIX for "Death Spiral":
                                # Even if rejected by MAD, we MUST update the trigger index if it passed the Gate Filter.
                                # Because if we don't, the NEXT delta will be double, and will be rejected by everything.
                                # Passing Gate Filter means it IS the pulse for this second, just maybe jittery.
                                if not is_gross_outlier:
                                    self._last_trigger_sample_index = abs_pos

                    if s <= th_low:
                        self._triggered = False

                # Handle Waveform Capture (If not skipped by optimization)
                # Handle Waveform Capture (If not skipped by optimization)
                if self._capture_trigger_index != -1:
                    current_head = self._total_samples_processed + frames
                    required_post = int(self.vis_window_post * self.nominal_rate)

                    if (current_head - self._capture_trigger_index) >= required_post:
                        self._capture_waveform(required_post, current_head)


                # Save back regression state
                self._reg_n = reg_n
                self._reg_sx = reg_sx
                self._reg_sy = reg_sy
                self._reg_sxx = reg_sxx
                self._reg_sxy = reg_sxy

                self._total_samples_processed += frames

            except queue.Empty:
                continue
            except Exception as e:
                print(f"OnePPSMonitor Worker Error: {e}")

    def _capture_waveform(self, required_post, current_head):
        """Helper to extract waveform from buffer."""
        required_pre = int(self.vis_window_pre * self.nominal_rate)

        with self._lock:
            # Total samples to extract = pre + post
            total_samps = required_pre + required_post

            # Use absolute trigger index to calculate exact read index
            samples_since_trig = current_head - self._capture_trigger_index

            # Start read at: Head - SamplesSince - Pre
            read_idx = (self.vis_write_pos - samples_since_trig - required_pre) % self.vis_buffer_size

            # Extract
            if read_idx + total_samps <= self.vis_buffer_size:
                waveform = self.vis_buffer[read_idx : read_idx + total_samps].copy()
            else:
                part1 = self.vis_buffer[read_idx:].copy()
                part2 = self.vis_buffer[:total_samps - len(part1)].copy()
                waveform = np.concatenate((part1, part2))

            self.last_trig_waveform = waveform

        self._capture_trigger_index = -1 # Done


    def get_history_arrays(self):
        """Returns (times, instant_ppm, cumulative_ppm) arrays correctly ordered."""
        with self._lock:
            if self.history_filled == 0:
                return np.array([]), np.array([]), np.array([])

            end = self.history_write_pos
            start = (end - self.history_filled) % self.max_history

            if start < end:
                # Contiguous
                t = self.time_buffer[start:end].copy()
                ip = self.instant_ppm_buffer[start:end].copy()
                cp = self.cumulative_ppm_buffer[start:end].copy()
            else:
                # Wrapped
                t = np.concatenate((self.time_buffer[start:], self.time_buffer[:end]))
                ip = np.concatenate((self.instant_ppm_buffer[start:], self.instant_ppm_buffer[:end]))
                cp = np.concatenate((self.cumulative_ppm_buffer[start:], self.cumulative_ppm_buffer[:end]))

            return t, ip, cp


class OnePPSMonitorWidget(QWidget):
    def __init__(self, module: OnePPSMonitor):
        super().__init__()
        self.module = module
        self._init_ui()

        self.timer = QTimer()
        self.timer.timeout.connect(self._update_plot)
        self.timer.setInterval(200) # Update GUI 5 times a second

        self.last_pulse_count = 0
        self.indicator_on_timer = QTimer()
        self.indicator_on_timer.setSingleShot(True)
        self.indicator_on_timer.timeout.connect(self._turn_off_indicator)
        self.indicator_on_timer.setInterval(100) # 100ms flash

    def _init_ui(self):
        layout = QHBoxLayout(self)

        # Left: Plot
        plot_layout = QVBoxLayout()
        self.plot_widget = pg.PlotWidget(title=tr("1PPS Frequency Deviation"))
        self.plot_widget.setLabel("left", tr("Deviation"), units="ppm")
        self.plot_widget.setLabel("bottom", tr("Time"), units="s")
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        self.plot_widget.addLegend()

        # Curves
        self.curve_instant = self.plot_widget.plot(
            pen=pg.mkPen('y', width=1, style=Qt.PenStyle.DotLine), 
            symbol='o', symbolBrush='y', symbolSize=3, 
            name=tr("Instantaneous")
        )
        self.curve_cumulative = self.plot_widget.plot(
            pen=pg.mkPen('c', width=2), 
            name=tr("Cumulative Avg")
        )

        # Zero line
        self.zero_line = pg.InfiniteLine(angle=0, pen=pg.mkPen('w', style=Qt.PenStyle.SolidLine, alpha=0.5))
        self.plot_widget.addItem(self.zero_line)

        plot_layout.addWidget(self.plot_widget)
        layout.addLayout(plot_layout, stretch=1)

        # Right: Controls
        ctrl_layout = QVBoxLayout()

        # indicator Group
        ind_layout = QHBoxLayout()
        ind_layout.addWidget(QLabel(tr("Pulse:")))
        self.lbl_indicator = QLabel()
        self.lbl_indicator.setFixedSize(20, 20)
        self.lbl_indicator.setStyleSheet("background-color: gray; border-radius: 10px; border: 1px solid black;")
        ind_layout.addWidget(self.lbl_indicator)
        ind_layout.addStretch()
        ctrl_layout.addLayout(ind_layout)

        # Start Button (Always visible)
        self.btn_start = QPushButton(tr("Start"))
        self.btn_start.setCheckable(True)
        self.btn_start.clicked.connect(self._on_start_toggled)
        ctrl_layout.addWidget(self.btn_start)

        # Tabs
        from PyQt6.QtWidgets import QTabWidget
        self.tabs = QTabWidget()
        ctrl_layout.addWidget(self.tabs)

        # --- Tab 1: Settings ---
        tab_settings = QWidget()
        vbox_settings = QVBoxLayout(tab_settings)

        # Nominal Rate
        rate_group = QGroupBox(tr("Sample Rate"))
        rate_vbox = QVBoxLayout(rate_group)

        self.chk_sync_rate = QCheckBox(tr("Sync with Audio Engine"))
        self.chk_sync_rate.setChecked(True) # Default to True
        self.chk_sync_rate.toggled.connect(self._on_sync_toggled)
        rate_vbox.addWidget(self.chk_sync_rate)

        rate_row = QHBoxLayout()
        rate_row.addWidget(QLabel(tr("Nominal Rate (Hz):")))
        self.spin_rate = QDoubleSpinBox()
        self.spin_rate.setRange(1.0, 384000.0)
        current_sr = float(self.module.audio_engine.sample_rate)
        self.spin_rate.setValue(current_sr)
        self.spin_rate.setDecimals(1)
        self.spin_rate.valueChanged.connect(self._on_rate_changed)
        rate_row.addWidget(self.spin_rate)
        rate_vbox.addLayout(rate_row)

        vbox_settings.addWidget(rate_group)

        # Target PPS
        pps_group = QHBoxLayout()
        pps_group.addWidget(QLabel(tr("Target PPS:")))

        self.combo_pps_preset = QComboBox()
        self.combo_pps_preset.addItems([tr("1 PPS"), tr("Other...")])
        self.combo_pps_preset.currentIndexChanged.connect(self._on_pps_preset_changed)
        pps_group.addWidget(self.combo_pps_preset)

        self.spin_pps = QDoubleSpinBox()
        self.spin_pps.setRange(0.1, 1000.0)
        self.spin_pps.setValue(1.0)
        self.spin_pps.setSingleStep(0.1)
        self.spin_pps.setSuffix(" Hz")
        self.spin_pps.setEnabled(False) # Disabled by default (1 PPS selected)
        self.spin_pps.valueChanged.connect(self._on_pps_changed)
        pps_group.addWidget(self.spin_pps)
        vbox_settings.addLayout(pps_group)



        # Outlier Filter Group
        filter_group = QGroupBox(tr("Outlier Rejection"))
        filter_vbox = QVBoxLayout(filter_group)

        self.chk_filter = QCheckBox(tr("Enable Filter (Median/MAD)"))
        self.chk_filter.toggled.connect(self._on_filter_toggled)
        filter_vbox.addWidget(self.chk_filter)

        # Window size
        from PyQt6.QtWidgets import QSpinBox
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel(tr("Window:")))
        self.spin_window = QSpinBox()
        self.spin_window.setRange(3, 50)
        self.spin_window.setValue(5)
        self.spin_window.valueChanged.connect(self._on_window_changed)
        filter_row.addWidget(self.spin_window)
        filter_vbox.addLayout(filter_row)

        # Tolerance
        tol_row = QHBoxLayout()
        tol_row.addWidget(QLabel(tr("Tolerance (Sigma):")))
        self.spin_tol = QDoubleSpinBox()
        self.spin_tol.setRange(0.1, 10.0)
        self.spin_tol.setValue(3.0)
        self.spin_tol.setSingleStep(0.1)
        self.spin_tol.valueChanged.connect(self._on_tol_changed)
        tol_row.addWidget(self.spin_tol)
        filter_vbox.addLayout(tol_row)

        vbox_settings.addWidget(filter_group)
        vbox_settings.addStretch()

        self.tabs.addTab(tab_settings, tr("Settings"))

        # --- Tab 1.5: Waveform ---
        tab_waveform = QWidget()
        vbox_waveform = QVBoxLayout(tab_waveform)

        # Plot
        self.plot_waveform = pg.PlotWidget(title=tr("Input Waveform (Triggered)"))
        self.plot_waveform.setMaximumWidth(400)
        self.plot_waveform.setLabel("left", tr("Amplitude"), units="FS")
        self.plot_waveform.setLabel("bottom", tr("Time (rel to trig)"), units="s")
        self.plot_waveform.showGrid(x=True, y=True, alpha=0.3)
        self.plot_waveform.setYRange(-1.1, 1.1)
        # Set X range to show pre/post trigger
        self.plot_waveform.setXRange(-0.5, 0.5)
        self.curve_waveform = self.plot_waveform.plot(pen='y')

        # Threshold Lines
        self.line_thresh_high = pg.InfiniteLine(angle=0, pen=pg.mkPen('g', width=1), label=tr("Thresh"), labelOpts={'position':0.9, 'color': (200,255,200)})
        self.line_thresh_low = pg.InfiniteLine(angle=0, pen=pg.mkPen('r', width=1, style=Qt.PenStyle.DashLine), label=tr("Hyst"), labelOpts={'position':0.9, 'color': (255,200,200)})
        self.plot_waveform.addItem(self.line_thresh_high)
        self.plot_waveform.addItem(self.line_thresh_low)

        vbox_waveform.addWidget(self.plot_waveform)

        # Controls for Threshold (Synced)
        form_layout = QHBoxLayout()
        form_layout.addWidget(QLabel(tr("Threshold:")))
        self.spin_thresh_wave = QDoubleSpinBox()
        self.spin_thresh_wave.setRange(-1.0, 1.0)
        self.spin_thresh_wave.setSingleStep(0.01)
        self.spin_thresh_wave.setValue(0.5)
        self.spin_thresh_wave.valueChanged.connect(self._on_thresh_wave_changed)
        form_layout.addWidget(self.spin_thresh_wave)

        form_layout.addWidget(QLabel(tr("Hysteresis:")))
        self.spin_hyst_wave = QDoubleSpinBox()
        self.spin_hyst_wave.setRange(0.0, 0.5)
        self.spin_hyst_wave.setSingleStep(0.01)
        self.spin_hyst_wave.setValue(0.05)
        self.spin_hyst_wave.valueChanged.connect(self._on_hyst_wave_changed)
        form_layout.addWidget(self.spin_hyst_wave)

        vbox_waveform.addLayout(form_layout)

        # Latency Compensation

        comp_layout = QHBoxLayout()
        self.chk_latency_comp = QCheckBox(tr("Compensate Input Latency"))
        self.chk_latency_comp.setChecked(False)
        self.chk_latency_comp.toggled.connect(self._update_plot)
        comp_layout.addWidget(self.chk_latency_comp)

        self.lbl_latency_val = QLabel("(Lat: N/A)")
        comp_layout.addWidget(self.lbl_latency_val)

        comp_layout.addSpacing(10)
        comp_layout.addWidget(QLabel(tr("Manual Offset:")))
        self.spin_manual_latency = QDoubleSpinBox()
        self.spin_manual_latency.setRange(-1000.0, 1000.0)
        self.spin_manual_latency.setSuffix(" ms")
        self.spin_manual_latency.setValue(0.0)
        self.spin_manual_latency.valueChanged.connect(self._update_plot)
        comp_layout.addWidget(self.spin_manual_latency)

        comp_layout.addStretch()

        vbox_waveform.addLayout(comp_layout)

        self.tabs.addTab(tab_waveform, tr("Waveform"))

        # --- Tab 2: Display ---
        tab_display = QWidget()
        vbox_display = QVBoxLayout(tab_display)

        # Plot Options
        plot_group = QGroupBox(tr("Display Options"))
        plot_vbox = QVBoxLayout(plot_group)

        plot_vbox.addWidget(QLabel(tr("Unit:")))
        self.combo_unit = QComboBox()
        self.combo_unit.addItems(["PPM", "Seconds"])
        self.combo_unit.currentIndexChanged.connect(self._update_plot)
        plot_vbox.addWidget(self.combo_unit)

        self.chk_show_inst = QCheckBox(tr("Show Instantaneous"))
        self.chk_show_inst.setChecked(True)
        self.chk_show_inst.toggled.connect(self.curve_instant.setVisible)
        plot_vbox.addWidget(self.chk_show_inst)

        vbox_display.addWidget(plot_group)

        # Calibration
        cal_group = QGroupBox(tr("Calibration"))
        cal_vbox = QVBoxLayout(cal_group)

        self.lbl_stored_cal = QLabel(tr("Stored 1PPS Cal: 0.000 ppm"))
        cal_vbox.addWidget(self.lbl_stored_cal)

        self.btn_calibrate = QPushButton(tr("Calibrate from Current"))
        self.btn_calibrate.clicked.connect(self._on_calibrate_clicked)
        cal_vbox.addWidget(self.btn_calibrate)

        vbox_display.addWidget(cal_group)


        # Stats
        self.lbl_count = QLabel(f"{tr('Count')}: -")
        self.lbl_inst = QLabel(f"{tr('Inst')}: -")
        self.lbl_cumul = QLabel(f"{tr('Cumul')}: -")
        self.lbl_rate = QLabel(f"{tr('Rate')}: -")

        self.lbl_mean = QLabel(f"{tr('Mean')}: -")
        self.lbl_std = QLabel(f"{tr('Std Dev')}: -")
        self.lbl_min = QLabel(f"{tr('Min')}: -")
        self.lbl_max = QLabel(f"{tr('Max')}: -")


        stats_group = QGroupBox(tr("Statistics"))
        stats_vbox = QVBoxLayout(stats_group)
        stats_vbox.addWidget(self.lbl_count)
        stats_vbox.addWidget(self.lbl_inst)
        stats_vbox.addWidget(self.lbl_cumul)

        stats_vbox.addWidget(self.lbl_rate)
        stats_vbox.addWidget(self.lbl_mean)
        stats_vbox.addWidget(self.lbl_std)
        stats_vbox.addWidget(self.lbl_min)
        stats_vbox.addWidget(self.lbl_max)

        vbox_display.addWidget(stats_group)
        vbox_display.addStretch()

        self.tabs.addTab(tab_display, tr("Display"))

        layout.addLayout(ctrl_layout)

        # Initialize
        self.module.target_pps = self.spin_pps.value()
        self.module.nominal_rate = self.spin_rate.value()
        # Initialize Waveform controls with module defaults if any, or just trigger handler
        self._on_thresh_wave_changed(self.spin_thresh_wave.value())
        self._on_hyst_wave_changed(self.spin_hyst_wave.value())
        self._on_filter_toggled(self.chk_filter.isChecked())
        self._on_window_changed(self.spin_window.value())
        self._on_tol_changed(self.spin_tol.value())

        # Initial sync state
        self._on_sync_toggled(self.chk_sync_rate.isChecked())

    def showEvent(self, event):
        super().showEvent(event)
        self._update_calibration_label()
        if self.chk_sync_rate.isChecked():
            self._sync_sample_rate()

    def _update_calibration_label(self):
        cal = self.module.audio_engine.calibration.frequency_calibration_1pps
        # Factor acting as multiplier: Corrected = Raw * Factor
        # So PPM error in factor is (factor - 1.0) * 1e6
        ppm = (cal - 1.0) * 1e6
        self.lbl_stored_cal.setText(tr("Stored 1PPS Cal: {0:+.3f} ppm").format(ppm))

    def _on_calibrate_clicked(self):
        # 1. Get current Cumulative PPM
        # We need a valid measurement
        if not self.module.is_running:
             QMessageBox.warning(self, tr("Error"), tr("Monitor is not running."))
             return

        # Check if we have enough history/warmup
        count = self.module.get_pulse_count()
        if count < self.module.warmup_count * 2:
             QMessageBox.warning(self, tr("Error"), tr("Not enough data to calibrate. Please wait."))
             return

        # Get last cumulative PPM
        t, ip, cp = self.module.get_history_arrays()
        if len(cp) == 0:
             QMessageBox.warning(self, tr("Error"), tr("No data available."))
             return

        current_ppm = cp[-1] # This is the "measured error" in ppm

        # 2. Calculate new calibration factor
        # The logic is: We measured 'current_ppm' error with the CURRENT system.
        # This implies the system clock is off by that amount (or the source is).
        # We assume the source (1PPS) is perfect.
        # So we want to correct the system so that THIS signal reads 0 ppm.

        # Factor definition: Corrected_Freq = Raw_Freq * Factor
        # Corresponds to: Corrected_PPM = Raw_PPM - Calibration_PPM (approx)

        # Exact math:
        # We want Corrected_Freq = Nominal
        # Currently: Measured_Freq = Nominal * (1 + current_ppm/1e6)
        # But Measured_Freq is derived from samples.
        # Correction Factor should scale the SAMPLE RATE or the FREQUENCY?
        # In `frequency_counter.py`, precise_freq = detected_freq * factor.

        # Here, `current_ppm` describes how much the measured signal deviates from nominal.
        # If signal is 1PPS (1Hz), and we measure 1 + delta, we want to multiply by 1/(1+delta) to get 1.

        # Factor acting as multiplier: Corrected_Freq = Measured_Freq * Factor
        # For a fast sampling clock (positive ppm), measured signal appears at a LOWER
        # frequency than reality when using nominal rate.
        # ppm = (Actual_Rate / Nominal_Rate - 1) * 1e6
        # Corrected_Rate = Nominal_Rate * (1 + ppm/1e6)
        # So we multiply measured frequency by (1 + ppm/1e6) to get true frequency.
        new_factor = (1.0 + current_ppm / 1e6)

        # 3. Confirmation Dialog
        ret = QMessageBox.question(
            self,
            tr("Confirm Calibration"),
            tr(
                "Current Measured Deviation: {0:+.3f} ppm\n\n"
                "This will set the 1PPS calibration parameter.\n"
                "Note: This does not affect the Frequency Counter calibration.\n\n"
                "Save this calibration?"
            ).format(current_ppm),
             QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if ret == QMessageBox.StandardButton.Yes:
            self.module.audio_engine.calibration.set_frequency_calibration_1pps(new_factor)
            self._update_calibration_label()
            QMessageBox.information(self, tr("Success"), tr("Calibration saved."))

    def _sync_sample_rate(self):
        engine_sr = float(self.module.audio_engine.sample_rate)
        if abs(self.spin_rate.value() - engine_sr) > 0.1:
            self.spin_rate.setValue(engine_sr)

    def _on_sync_toggled(self, checked):
        self.spin_rate.setEnabled(not checked)
        if checked:
            self._sync_sample_rate()

    def _on_start_toggled(self, checked):
        if checked:
            # Re-sync before starting if enabled
            if self.chk_sync_rate.isChecked():
                self._sync_sample_rate()

            self.module.start_analysis()
            self.timer.start()
            self.btn_start.setText(tr("Stop"))
        else:
            self.timer.stop()
            self.module.stop_analysis()
            self.btn_start.setText(tr("Start"))

    def _on_rate_changed(self, val):
        self.module.nominal_rate = val

    def _on_pps_changed(self, val):
        self.module.target_pps = val

    def _on_pps_preset_changed(self, index):
        if index == 0: # 1 PPS
            self.spin_pps.setValue(1.0)
            self.spin_pps.setEnabled(False)
        else: # Other...
            self.spin_pps.setEnabled(True)

    def _on_thresh_wave_changed(self, val):
        self.module.threshold_fs = val
        self.line_thresh_high.setValue(val)
        self.line_thresh_low.setValue(val - self.module.hysteresis_fs)

    def _on_hyst_wave_changed(self, val):
        self.module.hysteresis_fs = val
        self.line_thresh_low.setValue(self.module.threshold_fs - val)

    def _turn_off_indicator(self):
        self.lbl_indicator.setStyleSheet("background-color: gray; border-radius: 10px; border: 1px solid black;")

    def _on_filter_toggled(self, checked):
        self.module.filter_enabled = checked

    def _on_window_changed(self, val):
        self.module.filter_window_size = int(val)

    def _on_tol_changed(self, val):
        self.module.filter_tolerance_sigma = val

    def _update_plot(self):
        # Poll for sample rate changes if sync is enabled
        if self.chk_sync_rate.isChecked():
             self._sync_sample_rate()

        t, ip, cp = self.module.get_history_arrays()
        count = self.module.get_pulse_count()
        self.lbl_count.setText(f"{tr('Count')}: {count}")

        # Pulse Indicator Logic
        if count > self.last_pulse_count:
            self.lbl_indicator.setStyleSheet("background-color: #00FF00; border-radius: 10px; border: 1px solid black;")
            self.indicator_on_timer.start()
        self.last_pulse_count = count

        # Waveform Update (only if tab is visible)
        if self.tabs.currentWidget().layout() is not None and self.plot_waveform.isVisible():
             # Basic visibility check, can be improved checking current tab index
             # Tab 1.5 is index 1 (Settings=0, Waveform=1, Display=2)
             if self.tabs.currentIndex() == 1:
                wave_data = self.module.get_latest_waveform()
                if wave_data is not None:

                     lat = self.module.audio_engine.get_input_latency()
                     self.lbl_latency_val.setText(f"({tr('Lat')}: {lat*1000:.1f} ms)")

                     # Create time axis
                     # trigger is at index corresponding to 'vis_window_pre'
                     # 0.1s pre means trigger is at index 4800 (if 48k)
                     n = len(wave_data)
                     # t = (np.arange(n) - (self.module.vis_window_pre * self.module.nominal_rate)) / self.module.nominal_rate
                     # More robust:
                     pre_samps = int(self.module.vis_window_pre * self.module.nominal_rate)
                     t_wave = (np.arange(n) - pre_samps) / self.module.nominal_rate

                     # Latency Compensation
                     if self.chk_latency_comp.isChecked():
                         # Subtract input latency to shift time 'back' 
                         # (e.g. if event happened 10ms ago but we just got it, the timestamp t=0 is "now", so event is at -10ms)
                         # Wait, our t=0 is the TRIGGER point in the buffer.
                         # The buffer is filled by callback. 
                         # If latency is L, the signal at index i actually arrived at the ADC L seconds before it was written/processed?
                         # Input Latency = Time between ADC capture and Callback.
                         # So the sample at index i was captured at (Time_Current - Latency - (Indices_from_end / Rate)).
                         # Our specific Trigger Point is at t=0 relative to the captured buffer window.
                         # If we want "Time relative to Pulse Arrival at ADC", 
                         # The Pulse Arrived at ADC, then Latency later it Arrived at Callback.
                         # Step 1: Detect Pulse in Buffer. Trigger Index T.
                         # This Index T corresponds to some time.
                         # If we say T is t=0.
                         # Using the latency compensation means we want to show... what?
                         # The user likely wants to know the "absolute time" or just shift it so it matches something?
                         # User said: "shift drawing range by buffer latency".
                         # If we shift X axis by -Latency, then t=0 (Trigger) becomes t=-Latency.
                         # This means "The trigger event happened -Latency seconds ago relative to the timestamp of the data block"?
                         # Actually usually in audio apps, "Compensate Latency" means aligning recording with playback.
                         # Here we are just plotting.
                         # If the user wants to see "When did the pulse happen at the connector?",
                         # And our t=0 is "When did the software see the pulse?".
                         # The software sees it 'Latency' seconds LATE.
                         # So the Pulse actually happened at t = -Latency relative to Software Time.
                         # So if we plot X axis, the Pulse (Peak) is at X=0 in Software Time.
                         # In "Connector Time", the Pulse is at X=0, but the Software Time 0 is actually +Latency?
                         # Let's simple shift: t_adjusted = t_wave - latency?
                         # If t_wave=0 (Trigger), t_adjusted = -Latency.
                         # So the peak moves to -Latency.
                         # This seems correct if t=0 implies "When software processed it".
                         # Use audio_engine.get_input_latency()

                         manual_offset_sec = self.spin_manual_latency.value() / 1000.0

                         # Total shift = Latency + Manual Offset
                         t_wave -= (lat + manual_offset_sec)

                     self.curve_waveform.setData(t_wave, wave_data)

        if len(t) > 0:

            # Unit Conversion
            unit = self.combo_unit.currentText()
            if unit == "Seconds":
                # PPM to Seconds: PPM * 1e-6
                scale = 1e-6
                unit_label = "s"

                def fmt(v):
                    return pg.siFormat(v, suffix='s', precision=3)
            else:
                scale = 1.0
                unit_label = "ppm"

                def fmt(v):
                    return f"{v:+.3f} ppm"

            ip_plot = ip * scale
            cp_plot = cp * scale

            self.plot_widget.setLabel("left", tr("Deviation"), units=unit_label)
            self.curve_instant.setData(t, ip_plot)
            self.curve_cumulative.setData(t, cp_plot)

            # Stats calculation on visible data (Instantaneous)
            vals = ip_plot

            last_ip = vals[-1]
            last_cp = cp_plot[-1]

            mean_val = np.mean(vals)
            std_val = np.std(vals)
            min_val = np.min(vals)
            max_val = np.max(vals)

            self.lbl_inst.setText(f"{tr('Inst')}: {fmt(last_ip)}")
            self.lbl_cumul.setText(f"{tr('Cumul')}: {fmt(last_cp)}")

            # Effective Rate
            nominal = self.module.nominal_rate

            # Use raw buffer values (always PPM) to calculate effective rate
            raw_cp = cp[-1]
            eff_rate = nominal * (1.0 + raw_cp / 1e6)
            self.lbl_rate.setText(f"{tr('Rate')}: {eff_rate:.4f} Hz")

            self.lbl_mean.setText(f"{tr('Mean')}: {fmt(mean_val)}")
            self.lbl_std.setText(f"{tr('Std Dev')}: {fmt(std_val)}")
            self.lbl_min.setText(f"{tr('Min')}: {fmt(min_val)}")
            self.lbl_max.setText(f"{tr('Max')}: {fmt(max_val)}")
        else:
            if self.module.is_running:
                 self.lbl_inst.setText(tr("Warming Up... ({0}/{1})").format(count, self.module.warmup_count))
                 self.lbl_cumul.setText("-")
                 self.lbl_rate.setText("-")

