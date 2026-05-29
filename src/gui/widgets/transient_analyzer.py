from typing import Optional

import numpy as np
import pyqtgraph as pg
import pywt
from PyQt6.QtCore import QRectF, Qt, QTimer, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
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


class CWTWorker(QThread):
    finished = pyqtSignal(object, object, object, object)  # times, freqs, mag, error_msg

    def __init__(self, analyzer: "TransientAnalyzer"):
        super().__init__()
        self.analyzer = analyzer
        # Extract necessary values/data to avoid accessing shared state across threads
        self.final_data = analyzer.final_data.copy() if analyzer.final_data is not None else None
        self.fs = analyzer.fs
        self.min_anal_freq = analyzer.min_anal_freq
        self.max_anal_freq = analyzer.max_anal_freq
        self.wavelet_name = analyzer.wavelet_name

    def run(self):
        try:
            if self.final_data is None or len(self.final_data) == 0:
                self.finished.emit(None, None, None, None)
                return

            # Use linear frequencies for correct axis mapping in ImageItem
            num_scales = 120
            min_freq = self.min_anal_freq
            max_freq = self.max_anal_freq
            if max_freq > self.fs / 2:
                max_freq = self.fs / 2

            # Check integrity
            if min_freq <= 0:
                min_freq = 1
            if min_freq >= max_freq:
                min_freq = max_freq - 10

            # Linear space for frequencies to match linear Y-axis of plot
            freqs = np.linspace(min_freq, max_freq, num_scales)

            scales = pywt.frequency2scale(self.wavelet_name, freqs / self.fs)

            # Run CWT
            cwtmatr, frequencies = pywt.cwt(self.final_data, scales, self.wavelet_name, sampling_period=1.0 / self.fs)

            # Calculate Magnitude
            mag = np.abs(cwtmatr)

            times = np.arange(len(self.final_data)) / self.fs

            self.finished.emit(times, frequencies, mag, None)
        except Exception as e:
            self.finished.emit(None, None, None, str(e))


class TransientAnalyzer(MeasurementModule):
    def __init__(self, audio_engine: AudioEngine):
        self.audio_engine = audio_engine

        # State
        self.is_recording = False
        self.recorded_data = []  # List of chunks
        self.final_data = None  # Numpy array (1D) after stop
        self.fs = 48000

        # Settings
        self.input_channel = "Left"
        self.wavelet_name = "cmor1.5-1.0"
        self.scale_min = 1
        self.scale_max = 128
        self.scale_step = 1
        self.min_anal_freq = 20
        self.max_anal_freq = 20000
        self.record_duration_s = 0.5
        self.ringing_enabled = False
        self.ringing_window_width_ms = 2.0

        # Trigger (oscilloscope-like)
        self.trigger_enabled = False
        self.trigger_source = "Left"  # 'Left' or 'Right'
        self.trigger_slope = "Rising"  # 'Rising' or 'Falling'
        self.trigger_level = 0.0

        # Recording limit (enforced in audio callback for accuracy)
        self._target_samples = None
        self._recorded_samples = 0
        self._triggered = False
        self._prev_trigger_sample = None

        self.callback_id = None
        self.widget = None

    @property
    def name(self) -> str:
        return "Transient Analyzer"

    @property
    def description(self) -> str:
        return "Transient analysis using Wavelet Transform."

    def get_widget(self):
        if self.widget is None:
            self.widget = TransientAnalyzerWidget(self)
        return self.widget

    def start_recording(self):
        self.recorded_data = []
        self.is_recording = True
        self.fs = self.audio_engine.sample_rate
        self._recorded_samples = 0
        duration_s = float(self.record_duration_s)
        if duration_s <= 0:
            duration_s = 0.01
        if duration_s > 3.0:
            duration_s = 3.0
        self._target_samples = int(max(1, round(duration_s * self.fs)))
        self._triggered = not self.trigger_enabled
        self._prev_trigger_sample = None
        self.callback_id = self.audio_engine.register_callback(self._audio_callback)

    def stop_recording(self):
        self.is_recording = False
        if self.callback_id:
            self.audio_engine.unregister_callback(self.callback_id)
            self.callback_id = None

        self._target_samples = None
        self._triggered = False
        self._prev_trigger_sample = None

        # Concatenate data
        if self.recorded_data:
            full_raw = np.concatenate(self.recorded_data, axis=0)

            # Select channel
            if self.input_channel == "Left":
                self.final_data = full_raw[:, 0]
            elif self.input_channel == "Right":
                if full_raw.shape[1] > 1:
                    self.final_data = full_raw[:, 1]
                else:
                    self.final_data = full_raw[:, 0]
            else:  # Average
                self.final_data = np.mean(full_raw, axis=1)
        else:
            self.final_data = None

    def _get_trigger_signal(self, indata: np.ndarray) -> np.ndarray:
        """Return 1D signal used for trigger detection."""
        if indata is None or indata.size == 0:
            return np.asarray([], dtype=float)

        if indata.ndim == 1:
            return np.asarray(indata, dtype=float)

        if self.trigger_source == "Left":
            return np.asarray(indata[:, 0], dtype=float)
        if self.trigger_source == "Right":
            if indata.shape[1] > 1:
                return np.asarray(indata[:, 1], dtype=float)
            return np.asarray(indata[:, 0], dtype=float)

        return np.asarray(indata[:, 0], dtype=float)

    def _find_trigger_index(self, sig: np.ndarray) -> Optional[int]:
        """Find the first index in sig where the trigger condition becomes true."""
        if sig is None or sig.size == 0:
            return None

        level = float(self.trigger_level)
        prev = self._prev_trigger_sample

        if prev is not None:
            if self.trigger_slope == "Rising":
                if prev <= level and sig[0] > level:
                    return 0
            else:
                if prev >= level and sig[0] < level:
                    return 0

        if sig.size < 2:
            return None

        if self.trigger_slope == "Rising":
            crossings = np.where((sig[:-1] <= level) & (sig[1:] > level))[0]
        else:
            crossings = np.where((sig[:-1] >= level) & (sig[1:] < level))[0]
        if crossings.size == 0:
            return None
        return int(crossings[0] + 1)

    def _audio_callback(self, indata, outdata, frames, time, status):
        if self.is_recording:
            target = self._target_samples
            if target is None:
                self.recorded_data.append(indata.copy())
            else:
                if not self._triggered:
                    sig = self._get_trigger_signal(indata)
                    trig_idx = self._find_trigger_index(sig)
                    # Update prev sample for next block
                    if sig.size > 0:
                        self._prev_trigger_sample = float(sig[-1])

                    if trig_idx is None:
                        outdata.fill(0)
                        return

                    self._triggered = True
                    start = int(trig_idx)
                else:
                    start = 0

                remaining = target - self._recorded_samples
                if remaining > 0:
                    chunk = indata[start : start + remaining].copy()
                    if chunk.size > 0:
                        self.recorded_data.append(chunk)
                        self._recorded_samples += chunk.shape[0]

                if self._recorded_samples >= target:
                    # Stop collecting immediately; UI will finalize/unregister shortly.
                    self.is_recording = False
        outdata.fill(0)

    def analyze(self):
        """
        Perform CWT on final_data.
        Returns: (times, frequencies, magnitude_scalogram)
        """
        if self.final_data is None or len(self.final_data) == 0:
            return None, None, None

        # Use linear frequencies for correct axis mapping in ImageItem
        num_scales = 120
        min_freq = self.min_anal_freq
        max_freq = self.max_anal_freq
        if max_freq > self.fs / 2:
            max_freq = self.fs / 2

        # Check integrity
        if min_freq <= 0:
            min_freq = 1
        if min_freq >= max_freq:
            min_freq = max_freq - 10

        # Linear space for frequencies to match linear Y-axis of plot
        freqs = np.linspace(min_freq, max_freq, num_scales)

        scales = pywt.frequency2scale(self.wavelet_name, freqs / self.fs)

        # Run CWT
        cwtmatr, frequencies = pywt.cwt(self.final_data, scales, self.wavelet_name, sampling_period=1.0 / self.fs)

        # Calculate Magnitude
        mag = np.abs(cwtmatr)

        times = np.arange(len(self.final_data)) / self.fs

        return times, frequencies, mag

    def calculate_ringing_metrics(self, window_width_ms: float) -> Optional[dict]:
        """
        Calculate DAC filter ringing metrics from final_data.
        
        Args:
            window_width_ms: Width of the integration window in milliseconds.
            
        Returns:
            A dictionary containing ringing metrics, window boundaries, and validation flags.
        """
        if self.final_data is None or len(self.final_data) == 0:
            return None

        data = self.final_data
        fs = self.fs

        # Calculate peak
        abs_data = np.abs(data)
        peak_idx = int(np.argmax(abs_data))
        peak_val = float(abs_data[peak_idx])

        # Convert to dBFS
        epsilon = 1e-12
        peak_db = 20 * np.log10(peak_val + epsilon)

        # Validation: check if it looks like an impulse response
        rms = float(np.sqrt(np.mean(data ** 2)))
        crest_factor_db = 20 * np.log10((peak_val / (rms + epsilon)) + epsilon)

        is_valid = True
        error_msg = None
        if crest_factor_db < 12.0:
            is_valid = False
            error_msg = tr("Warning: Waveform does not look like an impulse (Low Crest Factor).")

        # Define window boundaries in samples
        offset_samples = max(2, int(round(0.04 * fs / 1000.0)))
        window_samples = int(round(window_width_ms * fs / 1000.0))

        # Pre-ringing window
        pre_start = max(0, peak_idx - window_samples)
        pre_end = max(0, peak_idx - offset_samples)

        # Post-ringing window
        post_start = min(len(data), peak_idx + offset_samples)
        post_end = min(len(data), peak_idx + window_samples)

        # Compute energy (sum of squares)
        if pre_end > pre_start:
            pre_energy = float(np.sum(data[pre_start:pre_end] ** 2))
        else:
            pre_energy = 0.0

        if post_end > post_start:
            post_energy = float(np.sum(data[post_start:post_end] ** 2))
        else:
            post_energy = 0.0

        # Calculate ratio in dB
        if pre_energy > epsilon and post_energy > epsilon:
            ratio_db = 10 * np.log10(pre_energy / post_energy)
        elif pre_energy <= epsilon and post_energy > epsilon:
            ratio_db = -100.0  # Cap at -100 dB
        elif pre_energy > epsilon and post_energy <= epsilon:
            ratio_db = 100.0   # Cap at 100 dB
        else:
            ratio_db = 0.0

        # Estimate filter type
        if not is_valid:
            filter_type = tr("Unknown")
        else:
            if ratio_db < -20.0:
                filter_type = tr("Minimum Phase")
            elif -3.0 <= ratio_db <= 3.0:
                filter_type = tr("Linear Phase")
            else:
                filter_type = tr("Mixed / Intermediate Phase")

        return {
            "peak_idx": peak_idx,
            "peak_val": peak_val,
            "peak_db": peak_db,
            "pre_energy": pre_energy,
            "post_energy": post_energy,
            "ratio_db": ratio_db,
            "filter_type": filter_type,
            "pre_start_idx": pre_start,
            "pre_end_idx": pre_end,
            "post_start_idx": post_start,
            "post_end_idx": post_end,
            "is_valid": is_valid,
            "error_msg": error_msg,
            "crest_factor_db": crest_factor_db
        }



class TransientAnalyzerWidget(QWidget):
    def __init__(self, module: TransientAnalyzer):
        super().__init__()
        self.module = module
        self.init_ui()
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_status)
        self.timer.start(100)
        self.worker = None

    def init_ui(self):
        layout = QVBoxLayout(self)

        # Create Tab Widget for Controls
        self.control_tabs = QTabWidget()

        # --- Tab 1: Recording & Settings ---
        tab_record = QWidget()
        rec_layout = QHBoxLayout(tab_record)

        # Channel
        rec_layout.addWidget(QLabel(tr("Channel:")))
        self.chan_combo = QComboBox()
        self.chan_combo.addItem(tr("Left"), "Left")
        self.chan_combo.addItem(tr("Right"), "Right")
        self.chan_combo.addItem(tr("Average"), "Average")
        chan_idx = self.chan_combo.findData(self.module.input_channel)
        if chan_idx >= 0:
            self.chan_combo.setCurrentIndex(chan_idx)
        self.chan_combo.currentIndexChanged.connect(self.on_channel_changed)
        rec_layout.addWidget(self.chan_combo)

        # Wavelet
        rec_layout.addWidget(QLabel(tr("Wavelet:")))
        self.wavelet_combo = QComboBox()
        self.wavelet_combo.addItems(["cmor1.5-1.0", "mexh", "morl", "cgau1", "gaus1"])
        self.wavelet_combo.setEditable(True)
        self.wavelet_combo.currentTextChanged.connect(self.on_wavelet_changed)
        rec_layout.addWidget(self.wavelet_combo)

        # Min Freq
        rec_layout.addWidget(QLabel(tr("Min Freq:")))
        self.min_freq_spin = QSpinBox()
        self.min_freq_spin.setRange(1, 96000)
        self.min_freq_spin.setValue(self.module.min_anal_freq)
        self.min_freq_spin.setSuffix(" Hz")
        self.min_freq_spin.valueChanged.connect(self.on_min_freq_changed)
        rec_layout.addWidget(self.min_freq_spin)

        # Max Freq
        rec_layout.addWidget(QLabel(tr("Max Freq:")))
        self.max_freq_spin = QSpinBox()
        self.max_freq_spin.setRange(1, 96000)
        self.max_freq_spin.setValue(self.module.max_anal_freq)
        self.max_freq_spin.setSuffix(" Hz")
        self.max_freq_spin.valueChanged.connect(self.on_max_freq_changed)
        rec_layout.addWidget(self.max_freq_spin)

        # Record Duration
        rec_layout.addWidget(QLabel(tr("Record Time:")))
        self.rec_time_spin = QDoubleSpinBox()
        self.rec_time_spin.setRange(0.1, 3.0)
        self.rec_time_spin.setDecimals(2)
        self.rec_time_spin.setSingleStep(0.1)
        self.rec_time_spin.setValue(float(self.module.record_duration_s))
        self.rec_time_spin.setSuffix(" s")
        self.rec_time_spin.valueChanged.connect(self.on_record_time_changed)
        rec_layout.addWidget(self.rec_time_spin)

        # Record Button
        self.rec_btn = QPushButton(tr("Record"))
        self.rec_btn.setCheckable(True)
        self.rec_btn.clicked.connect(self.on_record_toggle)
        rec_layout.addWidget(self.rec_btn)

        # Analyze Button
        self.analyze_btn = QPushButton(tr("Analyze"))
        self.analyze_btn.clicked.connect(self.on_analyze)
        self.analyze_btn.setEnabled(False)
        self.analyze_btn.setToolTip(
            tr("Warning: Analysis can be slow for long recordings.\nComplexity ~ O(N * Scales).")
        )
        rec_layout.addWidget(self.analyze_btn)

        self.control_tabs.addTab(tab_record, tr("Recording & Settings"))

        # --- Tab 2: Trigger ---
        tab_trigger = QWidget()
        trig_layout = QHBoxLayout(tab_trigger)

        self.trig_enable = QCheckBox(tr("Enable"))
        self.trig_enable.setChecked(bool(self.module.trigger_enabled))
        self.trig_enable.toggled.connect(self.on_trigger_enabled_changed)
        trig_layout.addWidget(self.trig_enable)

        trig_layout.addWidget(QLabel(tr("Source:")))
        self.trig_source_combo = QComboBox()
        self.trig_source_combo.addItem(tr("Left"), "Left")
        self.trig_source_combo.addItem(tr("Right"), "Right")
        trig_src_idx = self.trig_source_combo.findData(self.module.trigger_source)
        if trig_src_idx >= 0:
            self.trig_source_combo.setCurrentIndex(trig_src_idx)
        self.trig_source_combo.currentIndexChanged.connect(self.on_trigger_source_changed)
        trig_layout.addWidget(self.trig_source_combo)

        trig_layout.addWidget(QLabel(tr("Slope:")))
        self.trig_slope_combo = QComboBox()
        self.trig_slope_combo.addItem(tr("Rising"), "Rising")
        self.trig_slope_combo.addItem(tr("Falling"), "Falling")
        trig_slope_idx = self.trig_slope_combo.findData(self.module.trigger_slope)
        if trig_slope_idx >= 0:
            self.trig_slope_combo.setCurrentIndex(trig_slope_idx)
        self.trig_slope_combo.currentIndexChanged.connect(self.on_trigger_slope_changed)
        trig_layout.addWidget(self.trig_slope_combo)

        trig_layout.addWidget(QLabel(tr("Level:")))
        self.trig_level_spin = QDoubleSpinBox()
        self.trig_level_spin.setRange(-10.0, 10.0)
        self.trig_level_spin.setDecimals(3)
        self.trig_level_spin.setSingleStep(0.01)
        self.trig_level_spin.setValue(float(self.module.trigger_level))
        self.trig_level_spin.valueChanged.connect(self.on_trigger_level_changed)
        trig_layout.addWidget(self.trig_level_spin)
        
        trig_layout.addStretch()

        self.control_tabs.addTab(tab_trigger, tr("Trigger"))

        # --- Tab 3: Ringing Analysis ---
        tab_ringing = QWidget()
        ringing_layout = QHBoxLayout(tab_ringing)

        self.ringing_enable = QCheckBox(tr("Enable Analysis & Overlay"))
        self.ringing_enable.setChecked(bool(self.module.ringing_enabled))
        self.ringing_enable.toggled.connect(self.on_ringing_enabled_changed)
        ringing_layout.addWidget(self.ringing_enable)

        ringing_layout.addWidget(QLabel(tr("Window:")))
        self.ringing_width_spin = QDoubleSpinBox()
        self.ringing_width_spin.setRange(0.2, 10.0)
        self.ringing_width_spin.setDecimals(1)
        self.ringing_width_spin.setSingleStep(0.1)
        self.ringing_width_spin.setValue(float(self.module.ringing_window_width_ms))
        self.ringing_width_spin.setSuffix(" ms")
        self.ringing_width_spin.valueChanged.connect(self.on_ringing_width_changed)
        ringing_layout.addWidget(self.ringing_width_spin)

        # Metrics labels
        self.lbl_ringing_ratio = QLabel(tr("Pre/Post Ratio: N/A"))
        self.lbl_ringing_ratio.setStyleSheet("font-weight: bold;")
        ringing_layout.addWidget(self.lbl_ringing_ratio)

        self.lbl_filter_type = QLabel(tr("Filter Type: N/A"))
        self.lbl_filter_type.setStyleSheet("font-weight: bold; color: #3498db;")
        ringing_layout.addWidget(self.lbl_filter_type)

        # Warning label
        self.lbl_ringing_warning = QLabel("")
        self.lbl_ringing_warning.setStyleSheet("color: #ff5555; font-size: 10px; font-style: italic;")
        self.lbl_ringing_warning.setWordWrap(True)
        ringing_layout.addWidget(self.lbl_ringing_warning)
        
        ringing_layout.addStretch()

        self.control_tabs.addTab(tab_ringing, tr("Filter Ringing Analysis"))

        layout.addWidget(self.control_tabs)

        # Complexity Note
        note_label = QLabel(tr("Note: CWT analysis is computationally intensive. Long recordings may take time."))
        note_label.setStyleSheet("color: gray; font-style: italic;")
        layout.addWidget(note_label)

        # --- Visualization ---
        splitter = QSplitter(Qt.Orientation.Vertical)

        # 1. Waveform Plot
        self.wave_plot = pg.PlotWidget(title=tr("Transient Waveform"))
        self.wave_plot.setLabel("left", tr("Amplitude"))
        self.wave_plot.setLabel("bottom", tr("Time"), units="s")
        self.wave_plot.showGrid(x=True, y=True)
        
        # Ringing overlay elements (hidden/disabled by default)
        self.ringing_peak_line = pg.InfiniteLine(pos=0, angle=90, pen=pg.mkPen("r", width=1.5, style=Qt.PenStyle.DashLine))
        self.ringing_pre_region = pg.LinearRegionItem(values=[0, 0], orientation=pg.LinearRegionItem.Vertical, brush=pg.mkBrush(0, 191, 255, 30), movable=False)
        self.ringing_post_region = pg.LinearRegionItem(values=[0, 0], orientation=pg.LinearRegionItem.Vertical, brush=pg.mkBrush(50, 205, 50, 30), movable=False)

        splitter.addWidget(self.wave_plot)

        # 2. Scalogram (Image)
        self.scalo_win = pg.GraphicsLayoutWidget()
        self.scalo_plot = self.scalo_win.addPlot(title=tr("Wavelet Scalogram"))
        self.scalo_plot.setLabel("left", tr("Frequency"), units="Hz")
        self.scalo_plot.setLabel("bottom", tr("Time"), units="s")

        self.img_item = pg.ImageItem()
        self.scalo_plot.addItem(self.img_item)

        # Histogram
        self.hist = pg.HistogramLUTItem()
        self.hist.setImageItem(self.img_item)
        self.hist.gradient.loadPreset("viridis")
        self.scalo_win.addItem(self.hist)

        splitter.addWidget(self.scalo_win)
        layout.addWidget(splitter)

        # Link X Axes
        self.scalo_plot.setXLink(self.wave_plot)

        self.setLayout(layout)

    def _set_log_freq_axis(self, min_hz: float, max_hz: float):
        # We render the image in log10(Hz) coordinates; this sets ticks as Hz labels.
        try:
            lo = float(min_hz)
            hi = float(max_hz)
        except (TypeError, ValueError):
            return

        if not np.isfinite(lo) or not np.isfinite(hi):
            return
        if lo <= 0:
            lo = 1e-6
        if hi <= lo:
            hi = lo * 10.0

        log_lo = float(np.log10(lo))
        log_hi = float(np.log10(hi))

        exp_min = int(np.floor(log_lo))
        exp_max = int(np.ceil(log_hi))

        major = []
        minor = []
        for exp in range(exp_min, exp_max + 1):
            for mult in (1.0, 2.0, 5.0):
                f = mult * (10.0**exp)
                if f < lo or f > hi:
                    continue
                pos = float(np.log10(f))
                if mult == 1.0:
                    major.append((pos, format_si(f, unit="", sig_figs=3, space="")))
                else:
                    minor.append((pos, ""))

        self.scalo_plot.getAxis("left").setTicks([major, minor])

    def on_channel_changed(self, _index):
        value = self.chan_combo.currentData()
        if value:
            self.module.input_channel = value

    def on_wavelet_changed(self, val):
        self.module.wavelet_name = val

    def on_min_freq_changed(self, val):
        self.module.min_anal_freq = val

    def on_max_freq_changed(self, val):
        self.module.max_anal_freq = val

    def on_record_time_changed(self, val):
        self.module.record_duration_s = float(val)

    def on_trigger_enabled_changed(self, enabled: bool):
        self.module.trigger_enabled = bool(enabled)

    def on_trigger_source_changed(self, _index: int):
        value = self.trig_source_combo.currentData()
        if value:
            self.module.trigger_source = value

    def on_trigger_slope_changed(self, _index: int):
        value = self.trig_slope_combo.currentData()
        if value:
            self.module.trigger_slope = value

    def on_trigger_level_changed(self, val: float):
        self.module.trigger_level = float(val)

    def _start_recording_ui(self):
        self.module.start_recording()
        self.rec_btn.setText(tr("Stop"))
        self.rec_btn.setStyleSheet("background-color: #ffcccc; color: red;")
        self.analyze_btn.setEnabled(False)

    def _stop_recording_ui(self):
        self.module.stop_recording()
        self.rec_btn.setText(tr("Record"))
        self.rec_btn.setStyleSheet("")
        self.analyze_btn.setEnabled(True)
        self.update_waveform_plot()

    def on_record_toggle(self):
        if self.rec_btn.isChecked():
            self._start_recording_ui()
        else:
            self._stop_recording_ui()

    def update_status(self):
        # If the module stopped itself (exact sample count reached), finalize UI/state.
        if self.rec_btn.isChecked() and (not self.module.is_recording):
            self.rec_btn.setChecked(False)
            self._stop_recording_ui()

    def update_waveform_plot(self):
        if self.module.final_data is None:
            return

        t = np.arange(len(self.module.final_data)) / self.module.fs
        self.wave_plot.clear()
        self.wave_plot.plot(t, self.module.final_data, pen="y")
        self.update_ringing_analysis()

    def on_ringing_enabled_changed(self, enabled: bool):
        self.module.ringing_enabled = bool(enabled)
        self.update_ringing_analysis()

    def on_ringing_width_changed(self, val: float):
        self.module.ringing_window_width_ms = float(val)
        self.update_ringing_analysis()

    def update_ringing_analysis(self):
        # Remove any existing overlay items first
        try:
            self.wave_plot.removeItem(self.ringing_peak_line)
            self.wave_plot.removeItem(self.ringing_pre_region)
            self.wave_plot.removeItem(self.ringing_post_region)
        except Exception:
            pass

        if not self.module.ringing_enabled or self.module.final_data is None:
            self.lbl_ringing_ratio.setText(tr("Pre/Post Ratio: N/A"))
            self.lbl_filter_type.setText(tr("Filter Type: N/A"))
            self.lbl_ringing_warning.setText("")
            return

        metrics = self.module.calculate_ringing_metrics(self.module.ringing_window_width_ms)
        if metrics is None:
            return

        # Update labels
        ratio_db = metrics["ratio_db"]
        if ratio_db == -100.0:
            self.lbl_ringing_ratio.setText(tr("Pre/Post Ratio: -INF dB (Pure Min Phase)"))
        elif ratio_db == 100.0:
            self.lbl_ringing_ratio.setText(tr("Pre/Post Ratio: +INF dB"))
        else:
            self.lbl_ringing_ratio.setText(tr("Pre/Post Ratio: {0:+.2f} dB").format(ratio_db))

        self.lbl_filter_type.setText(tr("Filter Type: {0}").format(metrics["filter_type"]))
        
        if metrics["error_msg"]:
            self.lbl_ringing_warning.setText(metrics["error_msg"])
        else:
            self.lbl_ringing_warning.setText("")

        # Add visual overlay items to the plot
        fs = self.module.fs
        peak_t = metrics["peak_idx"] / fs
        
        self.ringing_peak_line.setValue(peak_t)
        self.wave_plot.addItem(self.ringing_peak_line)

        # Set region values (in seconds)
        pre_start_t = metrics["pre_start_idx"] / fs
        pre_end_t = metrics["pre_end_idx"] / fs
        self.ringing_pre_region.setRegion([pre_start_t, pre_end_t])
        self.wave_plot.addItem(self.ringing_pre_region)

        post_start_t = metrics["post_start_idx"] / fs
        post_end_t = metrics["post_end_idx"] / fs
        self.ringing_post_region.setRegion([post_start_t, post_end_t])
        self.wave_plot.addItem(self.ringing_post_region)

    def on_analyze(self):
        if self.module.final_data is None:
            return

        self.analyze_btn.setEnabled(False)
        self.analyze_btn.setText(tr("Analyzing..."))
        self.rec_btn.setEnabled(False)
        QApplication.processEvents()

        self.worker = CWTWorker(self.module)
        self.worker.finished.connect(self.on_analysis_finished)
        self.worker.start()

    def on_analysis_finished(self, times, freqs, mag, error_msg):
        self.analyze_btn.setEnabled(True)
        self.analyze_btn.setText(tr("Analyze"))
        self.rec_btn.setEnabled(True)

        if error_msg:
            QMessageBox.critical(self, tr("Error"), error_msg)
            return

        if times is None:
            return

        try:
            img_data = mag.T

            self.img_item.setImage(img_data, autoLevels=True)

            min_f = np.min(freqs)
            max_f = np.max(freqs)
            duration = times[-1]

            # Log-frequency Y axis: map Hz -> log10(Hz)
            min_f = float(max(min_f, 1e-6))
            max_f = float(max(max_f, min_f * 1.0001))
            y0 = float(np.log10(min_f))
            y1 = float(np.log10(max_f))
            self.img_item.setRect(QRectF(0, y0, duration, y1 - y0))
            self._set_log_freq_axis(min_f, max_f)

        except Exception as e:
            QMessageBox.critical(self, tr("Error"), str(e))
