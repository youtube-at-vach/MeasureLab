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
        self._triggered = False

        # Data storage for plotting (Delta Samples)
        # We expect ~1 pulse per second. Storing 3600 points = 1 hour history.
        self.max_history = 3600
        self.history_buffer = np.zeros(self.max_history, dtype=np.float64)
        self.history_write_pos = 0
        self.history_filled = 0
        
        # Also store timestamp for X axis (approximate wall clock)
        self.time_buffer = np.zeros(self.max_history, dtype=np.float64)
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
            self._triggered = False
            self.history_buffer.fill(np.nan)
            self.time_buffer.fill(np.nan)
            self.history_write_pos = 0
            self.history_filled = 0
            self._filter_window = []

        def callback(indata, outdata, frames, time_info, status):
            if indata is None:
                return

            # Analyze Channel 1 (Left) by default for now
            # TODO: Make channel selectable
            if indata.shape[1] > 0:
                sig = indata[:, 0]
            else:
                return

            # Simple Schmitt Trigger Logic
            # Find rising edges crossing threshold
            
            # We need to process sample by sample or vectorized. 
            # Vectorized is faster but we need to carry over state.
            # Given Python, let's try a vectorized approach for finding crossings, 
            # then refine.
            
            # However, for 1PPS, strictly sequential processing is safer to avoiding missing 
            # or double counting if logic gets complex. 
            # But loop in python is slow.
            # Let's try `np.where` logic.
            
            # Trigger State:
            # Low: signal < (threshold - hysteresis)
            # High: signal > (threshold + hysteresis)
            # Rising Edge: Low -> High
            
            # Optimization: If signal is way below threshold everywhere, skip.
            if np.max(sig) < (self.threshold_fs - self.hysteresis_fs):
                self._total_samples_processed += frames
                # If we were triggered high, we need to check if we fell low to reset?
                # Actually we just need to detect the moment we cross UP.
                # But we need to re-arm (go low) before next trigger.
                
                # If we were strictly HIGH, and now we are LOW, we are re-armed.
                if self._triggered:
                     self._triggered = False
                return

            # Iterate is safest for correct hysteresis state across blocks
            # To optimize, we can likely find indices where threshold is crossed.
            
            th_high = self.threshold_fs
            th_low = self.threshold_fs - self.hysteresis_fs
            
            # Local mutable state
            current_idx = 0
            
            # We assume frames is small enough (e.g. 1024) to iterate if needed, 
            # but let's try to be smart.
            
            # Indices where signal > th_high
            high_indices = np.where(sig > th_high)[0]
            
            # Indices where signal < th_low
            low_indices = np.where(sig < th_low)[0]
            
            # This is still tricky to reconstruct sequential state without iteration 
            # if multiple pulses could occur (unlikely in 1 block for 1PPS but possible with noise).
            
            # Let's just iterate for now. 1k samples at 48k is ~20ms. 
            # 20ms of python loop might be tight. 
            # Actually, `1PPS` implies very infrequent events.
            # We only really care about the transition.
            
            # Let's do a stateful scan using Numba if available? No, stick to numpy/python.
            
            # Hybrid:
            # 1. Identify potential regions of interest?
            # 2. Or just loop. A loop of 1024 float comparisons in pure python is ... acceptable?
            #    1024 * 10 steps might be 10k ops. 48000 samples/sec -> 48 callbacks/sec.
            #    Process load: simple loop is fine.
            
            t_samples = self._total_samples_processed
            
            for i in range(frames):
                s = sig[i]
                abs_pos = t_samples + i
                
                if not self._triggered:
                    if s >= th_high:
                        self._triggered = True
                        # Rising edge detected
                        if self._last_trigger_sample_index != -1:
                            delta = abs_pos - self._last_trigger_sample_index
                            
                            # Outlier Rejection Logic
                            accepted = True
                            if self.filter_enabled and len(self._filter_window) >= self.filter_window_size:
                                # Robust detection using Median and MAD
                                window = np.array(self._filter_window)
                                med = np.median(window)
                                mad = np.median(np.abs(window - med))
                                
                                # Estimate sigma (1.4826 * MAD for normal distribution)
                                sigma = 1.4826 * mad
                                
                                # Minimum threshold to allow for perfect clocks (avoid div by zero or strict zero tolerance)
                                # Allow at least 1 sample of jitter even if history is perfect
                                thresh_val = max(sigma * self.filter_tolerance_sigma, 1.0)
                                
                                if abs(delta - med) > thresh_val:
                                    accepted = False
                            
                            # Update filter window (Rolling)
                            # We add the new value to the window ONLY if accepted?
                            # Or if we want to track step changes, we must eventually accept new values.
                            # Standard Hampel: Use previous window to test current.
                            # Then slide window. If rejected, do we put the raw value or the median?
                            # To be robust against single bit errors but track steps:
                            # 1. If rejected, maybe substitute with median for the window update?
                            # 2. Or just don't update window? (Risk: lock up if rate changes)
                            # 3. Update window with raw value? (Risk: window gets polluted by burst)
                            
                            # Hybrid: Update window with raw value, but maybe limit queue size.
                            # For visualization "Rejection", we usually want to hide it.
                            
                            # Let's start with: Update window with RAW value so we adapt to new rates.
                            # But if the "outlier" is 8000 samples away, a window of 5 will take 3 samples to flip.
                            # This is acceptable for a "Monitor".
                            self._filter_window.append(delta)
                            if len(self._filter_window) > self.filter_window_size:
                                self._filter_window.pop(0)

                            if accepted:
                                # Store result
                                with self._lock:
                                    idx = self.history_write_pos
                                    self.history_buffer[idx] = delta
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
        """Returns (times, deltas) arrays correctly ordered."""
        with self._lock:
            if self.history_filled == 0:
                return np.array([]), np.array([])
            
            # Reconstruct ordered buffer
            # oldest is at (write_pos - filled) % max
            # newest is at (write_pos - 1) % max
            
            end = self.history_write_pos
            start = (end - self.history_filled) % self.max_history
            
            if start < end:
                # Contiguous
                t = self.time_buffer[start:end].copy()
                d = self.history_buffer[start:end].copy()
            else:
                # Wrapped
                t = np.concatenate((self.time_buffer[start:], self.time_buffer[:end]))
                d = np.concatenate((self.history_buffer[start:], self.history_buffer[:end]))
                
            return t, d


class OnePPSMonitorWidget(QWidget):
    def __init__(self, module: OnePPSMonitor):
        super().__init__()
        self.module = module
        self._init_ui()
        
        self.timer = QTimer()
        self.timer.timeout.connect(self._update_plot)
        self.timer.setInterval(200) # Update GUI 5 times a second is plenty for 1PPS

    def _init_ui(self):
        layout = QHBoxLayout(self)
        
        # Left: Plot
        plot_layout = QVBoxLayout()
        self.plot_widget = pg.PlotWidget(title=tr("1PPS Delta Samples"))
        self.plot_widget.setLabel("left", tr("Delta (Samples)"))
        self.plot_widget.setLabel("bottom", tr("Time (s)"))
        self.plot_widget.showGrid(x=True, y=True)
        self.curve = self.plot_widget.plot(pen='y', symbol='o', symbolBrush='y', symbolSize=5)
        
        # Add a target line for nominal
        self.nominal_line = pg.InfiniteLine(angle=0, pen=pg.mkPen('g', style=Qt.PenStyle.DashLine))
        self.plot_widget.addItem(self.nominal_line)
        
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
        
        # Get current sample rate from engine
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
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel(tr("Window:")))
        self.spin_window = QDoubleSpinBox() # Using DoubleSpinBox for int for consistency/convenience? No, standard spinbox
        from PyQt6.QtWidgets import QSpinBox
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
        self.lbl_current = QLabel("Last: -")
        self.lbl_error = QLabel("Error: -")
        self.lbl_ppm = QLabel("PPM: -")
        
        stats_group = QGroupBox(tr("Statistics"))
        stats_vbox = QVBoxLayout(stats_group)
        stats_vbox.addWidget(self.lbl_current)
        stats_vbox.addWidget(self.lbl_error)
        stats_vbox.addWidget(self.lbl_ppm)
        
        ctrl_layout.addWidget(ctrl_group)
        ctrl_layout.addWidget(stats_group)
        ctrl_layout.addStretch()
        
        layout.addLayout(ctrl_layout)

        # Initialize
        self.module.nominal_rate = self.spin_rate.value()
        self.nominal_line.setPos(self.module.nominal_rate)
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
        self.nominal_line.setPos(val)

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
        t, d = self.module.get_history_arrays()
        if len(d) > 0:
            self.curve.setData(t, d)
            
            last_val = d[-1]
            nominal = self.module.nominal_rate
            error = last_val - nominal
            ppm = (error / nominal) * 1e6 if nominal != 0 else 0
            
            self.lbl_current.setText(f"Last: {last_val:.0f}")
            self.lbl_error.setText(f"Error: {error:+.0f}")
            self.lbl_ppm.setText(f"PPM: {ppm:+.2f}")
