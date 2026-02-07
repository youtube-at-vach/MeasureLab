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
                            # Cannot calculate delta or cumulative on very first pulse
                        else:
                            # Instantaneous calculation
                            delta = abs_pos - self._last_trigger_sample_index
                            
                            # Outlier Rejection Logic
                            accepted = True
                            if self.filter_enabled and len(self._filter_window) >= self.filter_window_size:
                                window = np.array(self._filter_window)
                                med = np.median(window)
                                mad = np.median(np.abs(window - med))
                                sigma = 1.4826 * mad
                                thresh_val = max(sigma * self.filter_tolerance_sigma, 1.0)
                                if abs(delta - med) > thresh_val:
                                    accepted = False
                            
                            self._filter_window.append(delta)
                            if len(self._filter_window) > self.filter_window_size:
                                self._filter_window.pop(0)

                            if accepted:
                                # 1. Instantaneous PPM
                                error_samples = delta - nominal
                                instant_ppm = (error_samples / nominal) * 1e6 if nominal != 0 else 0
                                
                                # 2. Cumulative PPM
                                # Total samples elapsed since start
                                total_delta_samples = abs_pos - self._first_trigger_sample_index
                                
                                # Estimate number of seconds elapsed (rounded to nearest integer)
                                # This assumes the clock drift is < 0.5 seconds over the measurement period
                                # so we can infer the "true" time index.
                                # For 1PPS, this is safe.
                                total_seconds = round(total_delta_samples / nominal)
                                
                                if total_seconds > 0:
                                    cumulative_rate = total_delta_samples / total_seconds
                                    cumulative_error = cumulative_rate - nominal
                                    cumulative_ppm = (cumulative_error / nominal) * 1e6
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
                        
                        self._last_trigger_sample_index = abs_pos
                else:
                    if s <= th_low:
                        self._triggered = False
            
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
        self.lbl_inst = QLabel("Inst PPM: -")
        self.lbl_cumul = QLabel("Cumul PPM: -")
        
        stats_group = QGroupBox(tr("Statistics"))
        stats_vbox = QVBoxLayout(stats_group)
        stats_vbox.addWidget(self.lbl_inst)
        stats_vbox.addWidget(self.lbl_cumul)
        
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
            self.curve_instant.setData(t, ip)
            self.curve_cumulative.setData(t, cp)
            
            last_ip = ip[-1]
            last_cp = cp[-1]
            
            self.lbl_inst.setText(f"Inst PPM: {last_ip:+.2f}")
            self.lbl_cumul.setText(f"Cumul PPM: {last_cp:+.4f}")
