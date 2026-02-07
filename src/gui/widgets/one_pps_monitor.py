import argparse
import threading
import time

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
        self._triggered = False
        
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

    def run(self, args: argparse.Namespace):
        """CLI entry point (not used in GUI mode)."""
        print("1PPS Monitor CLI mode not implemented.")

    def start_analysis(self):
        if self.is_running:
            return

        self.is_running = True
        self._start_time = time.time()
        
        with self._lock:
            self._total_samples_processed = 0
            self._last_trigger_sample_index = -1
            self._first_trigger_sample_index = -1
            self._triggered = False
            
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

        def callback(indata, outdata, frames, time_info, status):
            if indata is None:
                return

            if indata.shape[1] > 0:
                sig = indata[:, 0]
            else:
                return

            # Optimization: If signal is way below threshold everywhere, skip.
            if np.max(sig) < (self.threshold_fs - self.hysteresis_fs):
                self._total_samples_processed += frames
                if self._triggered:
                     self._triggered = False
                return

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
                                with self._lock:
                                    idx = self.history_write_pos
                                    self.instant_ppm_buffer[idx] = instant_ppm
                                    self.cumulative_ppm_buffer[idx] = cumulative_ppm
                                    self.time_buffer[idx] = time.time() - self._start_time
                                    
                                    self.history_write_pos = (idx + 1) % self.max_history
                                    self.history_filled = min(self.history_filled + 1, self.max_history)
                                
                                # 4. Update Trigger State (Only if accepted!)
                                # If we reject, we assume this trigger was noise (glitch)
                                # and we continue waiting for the "real" next pulse relative to the LAST GOOD one.
                                # However, if it was a valid pulse but just very jittery, rejecting it means we lose time sync?
                                # For 1PPS, a glitch is usually an extra edge. Ignoring it keeps us locked to the 1s grid.
                                self._last_trigger_sample_index = abs_pos
                            else:
                                # Rejected.
                                # If it was a gross outlier (e.g. double trigger), ignoring it is correct.
                                # We do NOT update _last_trigger_sample_index.
                                pass
                        
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
            outdata.fill(0)

        self.callback_id = self.audio_engine.register_callback(callback)

    def stop_analysis(self):
        if not self.is_running:
            return

        if self.callback_id is not None:
            self.audio_engine.unregister_callback(self.callback_id)
            self.callback_id = None

        self.is_running = False
        
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
        
        # --- Plot Options ---
        plot_group = QGroupBox(tr("Display Options"))
        plot_vbox = QVBoxLayout(plot_group)
        
        plot_vbox.addWidget(QLabel(tr("Unit:")))
        self.combo_unit = QComboBox()
        self.combo_unit.addItems(["PPM", "Seconds"])
        self.combo_unit.currentIndexChanged.connect(self._update_plot)
        plot_vbox.addWidget(self.combo_unit)
        
        ctrl_layout.addWidget(plot_group)
        
        # --- Settings ---
        ctrl_group = QGroupBox(tr("Settings"))
        ctrl_vbox = QVBoxLayout(ctrl_group)
        
        # Controls
        self.btn_start = QPushButton(tr("Start"))
        self.btn_start.setCheckable(True)
        self.btn_start.clicked.connect(self._on_start_toggled)
        ctrl_vbox.addWidget(self.btn_start)
        
        ctrl_vbox.addWidget(QLabel(tr("Nominal Rate (Hz):")))
        self.spin_rate = QDoubleSpinBox()
        self.spin_rate.setRange(1.0, 384000.0)
        
        current_sr = float(self.module.audio_engine.sample_rate)
        self.spin_rate.setValue(current_sr)
        
        self.spin_rate.setDecimals(1)
        self.spin_rate.valueChanged.connect(self._on_rate_changed)
        ctrl_vbox.addWidget(self.spin_rate)
        
        # Threshold
        ctrl_vbox.addWidget(QLabel(tr("Threshold (FS):")))
        self.spin_thresh = QDoubleSpinBox()
        self.spin_thresh.setRange(-1.0, 1.0)
        self.spin_thresh.setSingleStep(0.01)
        self.spin_thresh.setValue(0.5)
        self.spin_thresh.valueChanged.connect(self._on_thresh_changed)
        ctrl_vbox.addWidget(self.spin_thresh)

        # Hysteresis
        ctrl_vbox.addWidget(QLabel(tr("Hysteresis (FS):")))
        self.spin_hyst = QDoubleSpinBox()
        self.spin_hyst.setRange(0.0, 0.5)
        self.spin_hyst.setSingleStep(0.01)
        self.spin_hyst.setValue(0.05)
        self.spin_hyst.valueChanged.connect(self._on_hyst_changed)
        ctrl_vbox.addWidget(self.spin_hyst)

        # Outlier Filter
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
        
        ctrl_vbox.addWidget(filter_group)
        
        # Stats
        self.lbl_inst = QLabel("Inst: -")
        self.lbl_cumul = QLabel("Cumul: -")
        self.lbl_mean = QLabel("Mean: -")
        self.lbl_std = QLabel("Std Dev: -")
        self.lbl_min = QLabel("Min: -")
        self.lbl_max = QLabel("Max: -")
        
        stats_group = QGroupBox(tr("Statistics"))
        stats_vbox = QVBoxLayout(stats_group)
        stats_vbox.addWidget(self.lbl_inst)
        stats_vbox.addWidget(self.lbl_cumul)
        stats_vbox.addWidget(self.lbl_mean)
        stats_vbox.addWidget(self.lbl_std)
        stats_vbox.addWidget(self.lbl_min)
        stats_vbox.addWidget(self.lbl_max)
        
        ctrl_layout.addWidget(ctrl_group)
        ctrl_layout.addWidget(stats_group)
        ctrl_layout.addStretch()
        
        layout.addLayout(ctrl_layout)

        # Initialize
        self.module.nominal_rate = self.spin_rate.value()
        self._on_thresh_changed(self.spin_thresh.value())
        self._on_hyst_changed(self.spin_hyst.value())
        self._on_filter_toggled(self.chk_filter.isChecked())
        self._on_window_changed(self.spin_window.value())
        self._on_tol_changed(self.spin_tol.value())

    def _on_start_toggled(self, checked):
        if checked:
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
        t, ip, cp = self.module.get_history_arrays()
        if len(t) > 0:
            # Unit Conversion
            unit = self.combo_unit.currentText()
            if unit == "Seconds":
                # PPM to Seconds: PPM * 1e-6
                scale = 1e-6
                unit_label = "s"
                fmt = "{:.3e}"
            else:
                scale = 1.0
                unit_label = "ppm"
                fmt = "{:+.3f}"

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
            
            self.lbl_inst.setText(f"Inst: {fmt.format(last_ip)}")
            self.lbl_cumul.setText(f"Cumul: {fmt.format(last_cp)}")
            
            self.lbl_mean.setText(f"Mean: {fmt.format(mean_val)}")
            self.lbl_std.setText(f"Std Dev: {fmt.format(std_val)}")
            self.lbl_min.setText(f"Min: {fmt.format(min_val)}")
            self.lbl_max.setText(f"Max: {fmt.format(max_val)}")
