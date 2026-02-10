
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

    def _process_loop(self):
        while self.is_running:
            try:
                item = self.data_queue.get(timeout=0.1)
                if item is None:
                    break

                sig, frames = item

                # Processing Logic
                # Optimization: If signal is way below threshold everywhere, skip.
                if np.max(sig) < (self.threshold_fs - self.hysteresis_fs):
                    self._total_samples_processed += frames
                    if self._triggered:
                         self._triggered = False
                    continue

                th_high = self.threshold_fs
                th_low = self.threshold_fs - self.hysteresis_fs

                t_samples = self._total_samples_processed
                nominal = self.nominal_rate

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

                                # 0. Gate Filter (Hard Rejection)
                                # Reject if deviation is > 50% of nominal (e.g. double trigger or missed trigger)
                                # This handles the massive glitches seen in 1PPS (e.g. 192kHz -> < 96k or > 288k)
                                # 50% is safe for 1PPS.
                                gate_threshold = nominal * 0.5
                                is_gross_outlier = abs(delta - nominal) > gate_threshold

                                accepted = not is_gross_outlier

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
                                    error_samples = delta - nominal
                                    # PPM = (Error / Nominal) * 1e6
                                    # Seconds Error = Error / Nominal_Rate (Sampling Rate ~ Nominal) assuming Nominal is Rate
                                    # We store PPM. UI can convert to Seconds (PPM * 1e-6).
                                    instant_ppm = (error_samples / nominal) * 1e6 if nominal != 0 else 0

                                    # 3. Regression Update
                                    # x = Pulse Count (approx seconds)
                                    # y = Actual Sample Position relative to first
                                    y_val = abs_pos - self._first_trigger_sample_index
                                    # x_val = round(y_val / nominal) 
                                    # Better: x is the index of the pulse.
                                    # Since we might have missed pulses, let's trust the "nominal" grid?
                                    # No, existing logic was:
                                    x_val = round(y_val / nominal)

                                    reg_n += 1
                                    reg_sx += x_val
                                    reg_sy += y_val
                                    reg_sxx += x_val * x_val
                                    reg_sxy += x_val * y_val

                                    # Slope Calculation
                                    denom = (reg_n * reg_sxx - reg_sx * reg_sx)
                                    if denom != 0:
                                        slope = (reg_n * reg_sxy - reg_sx * reg_sy) / denom
                                        cumulative_ppm = ((slope - nominal) / nominal) * 1e6
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

                    else:
                        if s <= th_low:
                            self._triggered = False

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

        # Threshold
        vbox_settings.addWidget(QLabel(tr("Threshold (FS):")))
        self.spin_thresh = QDoubleSpinBox()
        self.spin_thresh.setRange(-1.0, 1.0)
        self.spin_thresh.setSingleStep(0.01)
        self.spin_thresh.setValue(0.5)
        self.spin_thresh.valueChanged.connect(self._on_thresh_changed)
        vbox_settings.addWidget(self.spin_thresh)

        # Hysteresis
        vbox_settings.addWidget(QLabel(tr("Hysteresis (FS):")))
        self.spin_hyst = QDoubleSpinBox()
        self.spin_hyst.setRange(0.0, 0.5)
        self.spin_hyst.setSingleStep(0.01)
        self.spin_hyst.setValue(0.05)
        self.spin_hyst.valueChanged.connect(self._on_hyst_changed)
        vbox_settings.addWidget(self.spin_hyst)

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
        self.lbl_count = QLabel("Count: -")
        self.lbl_inst = QLabel("Inst: -")
        self.lbl_cumul = QLabel("Cumul: -")
        self.lbl_rate = QLabel("Rate: -")

        self.lbl_mean = QLabel("Mean: -")
        self.lbl_std = QLabel("Std Dev: -")
        self.lbl_min = QLabel("Min: -")
        self.lbl_max = QLabel("Max: -")


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
        self.module.nominal_rate = self.spin_rate.value()
        self._on_thresh_changed(self.spin_thresh.value())
        self._on_hyst_changed(self.spin_hyst.value())
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
        
        # Factor definition: Corrected_Freq = Raw_Freq * Factor
        # Here, `current_ppm` describes how much the measured signal deviates from nominal.
        # If signal is 1PPS (1Hz), and we measure 1 + delta, we want to multiply by 1/(1+delta) to get 1.
        # However, the user wants the dimensions to match Frequency Counter, where:
        # factor = f_ref / f_meas
        # For f_meas = f_ref * (1 + delta), factor = 1 / (1 + delta) approx 1 - delta.
        # Wait, the Frequency Counter uses: new_factor = target / avg_raw.
        # So we should use the same here:
        new_factor = 1.0 / (1.0 + current_ppm / 1e6)
        
        # ACTUALLY, to align with the user's observation that it's "like a reciprocal",
        # let's use the exact same formula: f_ref / f_meas.
        # current_ppm = (f_meas / f_ref - 1) * 1e6
        # -> f_meas / f_ref = 1 + current_ppm / 1e6
        # -> f_ref / f_meas = 1 / (1 + current_ppm / 1e6)
        
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

    def _on_thresh_changed(self, val):
        self.module.threshold_fs = val

    def _on_hyst_changed(self, val):
        self.module.hysteresis_fs = val

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

            self.lbl_inst.setText(f"Inst: {fmt(last_ip)}")
            self.lbl_cumul.setText(f"Cumul: {fmt(last_cp)}")

            # Effective Rate
            nominal = self.module.nominal_rate
            eff_rate = nominal * (1.0 + last_cp / 1e6) # last_cp is in PPM internally? 
            # WAIT. last_cp derived from cp_plot, which is SCALED. 
            # Logic error in previous step fixed implicitly here if I check carefully.
            # NO: get_history_arrays returns PPM arrays.
            # ip_plot = ip * scale.
            # If scale=1e-6 (Seconds), ip_plot is in seconds.
            # then last_cp is in seconds.
            # Formula was: eff_rate = nominal * (1.0 + last_cp / 1e6) assuming last_cp is PPM.
            # If last_cp is seconds, formula is wrong.
            # Let's fix this robustness: use internal buffer for calculation, or unscale.

            # Better: use the raw buffer values `ip`, `cp` which are always PPM.
            raw_cp = cp[-1]
            eff_rate = nominal * (1.0 + raw_cp / 1e6)
            self.lbl_rate.setText(f"Rate: {eff_rate:.4f} Hz")

            self.lbl_mean.setText(f"Mean: {fmt(mean_val)}")
            self.lbl_std.setText(f"Std Dev: {fmt(std_val)}")
            self.lbl_min.setText(f"Min: {fmt(min_val)}")
            self.lbl_max.setText(f"Max: {fmt(max_val)}")
        else:
            if self.module.is_running:
                 self.lbl_inst.setText(tr(f"Warming Up... ({count}/{self.module.warmup_count})"))
                 self.lbl_cumul.setText("-")
                 self.lbl_rate.setText("-")

