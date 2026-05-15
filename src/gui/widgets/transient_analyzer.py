from typing import Optional

import numpy as np
import pyqtgraph as pg
import pywt
from PyQt6.QtCore import QRectF, QThread, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from src.core.audio_engine import AudioEngine
from src.core.localization import tr
from src.core.utils import format_si
from src.measurement_modules.base import MeasurementModule


def calculate_wavelet_scalogram(
    data: np.ndarray,
    fs: int,
    wavelet_name: str,
    min_anal_freq: float,
    max_anal_freq: float,
):
    """
    Calculate a wavelet scalogram from a snapshot of recorded data.

    Returns: (times, frequencies, magnitude_scalogram)
    """
    if data is None or len(data) == 0:
        return None, None, None

    num_scales = 120
    min_freq = min_anal_freq
    max_freq = max_anal_freq
    if max_freq > fs / 2:
        max_freq = fs / 2

    if min_freq <= 0:
        min_freq = 1
    if min_freq >= max_freq:
        min_freq = max_freq - 10

    freqs = np.linspace(min_freq, max_freq, num_scales)
    scales = pywt.frequency2scale(wavelet_name, freqs / fs)
    cwtmatr, frequencies = pywt.cwt(data, scales, wavelet_name, sampling_period=1.0 / fs)
    mag = np.abs(cwtmatr)
    times = np.arange(len(data)) / fs

    return times, frequencies, mag


class WaveletAnalysisWorker(QThread):
    result_ready = pyqtSignal(object, object, object)
    failed = pyqtSignal(str)

    def __init__(
        self,
        data: np.ndarray,
        fs: int,
        wavelet_name: str,
        min_anal_freq: float,
        max_anal_freq: float,
    ):
        super().__init__()
        self.data = np.asarray(data, dtype=float).copy()
        self.fs = int(fs)
        self.wavelet_name = str(wavelet_name)
        self.min_anal_freq = float(min_anal_freq)
        self.max_anal_freq = float(max_anal_freq)

    def run(self):
        try:
            times, freqs, mag = calculate_wavelet_scalogram(
                self.data,
                self.fs,
                self.wavelet_name,
                self.min_anal_freq,
                self.max_anal_freq,
            )
            self.result_ready.emit(times, freqs, mag)
        except Exception as e:
            self.failed.emit(str(e))


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
        return calculate_wavelet_scalogram(
            self.final_data,
            self.fs,
            self.wavelet_name,
            self.min_anal_freq,
            self.max_anal_freq,
        )


class TransientAnalyzerWidget(QWidget):
    def __init__(self, module: TransientAnalyzer):
        super().__init__()
        self.module = module
        self.analysis_worker = None
        self.init_ui()
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_status)
        self.timer.start(100)

    def init_ui(self):
        layout = QHBoxLayout()

        left_panel = QWidget()
        left_panel.setFixedWidth(360)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(5, 5, 5, 5)

        settings_tabs = QTabWidget()

        # --- Settings & Controls ---
        ctrl_group = QGroupBox(tr("Controls"))
        ctrl_layout = QFormLayout()

        # Input Channel
        self.chan_combo = QComboBox()
        self.chan_combo.addItem(tr("Left"), "Left")
        self.chan_combo.addItem(tr("Right"), "Right")
        self.chan_combo.addItem(tr("Average"), "Average")
        chan_idx = self.chan_combo.findData(self.module.input_channel)
        if chan_idx >= 0:
            self.chan_combo.setCurrentIndex(chan_idx)
        self.chan_combo.currentIndexChanged.connect(self.on_channel_changed)
        ctrl_layout.addRow(tr("Channel:"), self.chan_combo)

        # Wavelet
        self.wavelet_combo = QComboBox()
        # Common continuous wavelets
        self.wavelet_combo.addItems(["cmor1.5-1.0", "mexh", "morl", "cgau1", "gaus1"])
        self.wavelet_combo.setEditable(True)
        self.wavelet_combo.currentTextChanged.connect(self.on_wavelet_changed)
        ctrl_layout.addRow(tr("Wavelet:"), self.wavelet_combo)

        self.min_freq_spin = QSpinBox()
        self.min_freq_spin.setRange(1, 96000)
        self.min_freq_spin.setValue(self.module.min_anal_freq)
        self.min_freq_spin.setSuffix(" Hz")
        self.min_freq_spin.valueChanged.connect(self.on_min_freq_changed)
        ctrl_layout.addRow(tr("Min Freq:"), self.min_freq_spin)

        self.max_freq_spin = QSpinBox()
        self.max_freq_spin.setRange(1, 96000)
        self.max_freq_spin.setValue(self.module.max_anal_freq)
        self.max_freq_spin.setSuffix(" Hz")
        self.max_freq_spin.valueChanged.connect(self.on_max_freq_changed)
        ctrl_layout.addRow(tr("Max Freq:"), self.max_freq_spin)

        # Record Duration
        self.rec_time_spin = QDoubleSpinBox()
        self.rec_time_spin.setRange(0.1, 3.0)
        self.rec_time_spin.setDecimals(2)
        self.rec_time_spin.setSingleStep(0.1)
        self.rec_time_spin.setValue(float(self.module.record_duration_s))
        self.rec_time_spin.setSuffix(" s")
        self.rec_time_spin.valueChanged.connect(self.on_record_time_changed)
        ctrl_layout.addRow(tr("Record Time:"), self.rec_time_spin)

        ctrl_group.setLayout(ctrl_layout)
        settings_tab = QWidget()
        settings_layout = QVBoxLayout(settings_tab)
        settings_layout.addWidget(ctrl_group)

        note_label = QLabel(tr("Note: CWT analysis is computationally intensive. Long recordings may take time."))
        note_label.setStyleSheet("color: gray; font-style: italic;")
        note_label.setWordWrap(True)
        settings_layout.addWidget(note_label)
        settings_layout.addStretch()
        settings_tabs.addTab(settings_tab, tr("Settings"))

        # --- Trigger ---
        trig_group = QGroupBox(tr("Trigger"))
        trig_layout = QFormLayout()

        self.trig_enable = QCheckBox(tr("Enable"))
        self.trig_enable.setChecked(bool(self.module.trigger_enabled))
        self.trig_enable.toggled.connect(self.on_trigger_enabled_changed)
        trig_layout.addRow(self.trig_enable)

        self.trig_source_combo = QComboBox()
        self.trig_source_combo.addItem(tr("Left"), "Left")
        self.trig_source_combo.addItem(tr("Right"), "Right")
        trig_src_idx = self.trig_source_combo.findData(self.module.trigger_source)
        if trig_src_idx >= 0:
            self.trig_source_combo.setCurrentIndex(trig_src_idx)
        self.trig_source_combo.currentIndexChanged.connect(self.on_trigger_source_changed)
        trig_layout.addRow(tr("Source:"), self.trig_source_combo)

        self.trig_slope_combo = QComboBox()
        self.trig_slope_combo.addItem(tr("Rising"), "Rising")
        self.trig_slope_combo.addItem(tr("Falling"), "Falling")
        trig_slope_idx = self.trig_slope_combo.findData(self.module.trigger_slope)
        if trig_slope_idx >= 0:
            self.trig_slope_combo.setCurrentIndex(trig_slope_idx)
        self.trig_slope_combo.currentIndexChanged.connect(self.on_trigger_slope_changed)
        trig_layout.addRow(tr("Slope:"), self.trig_slope_combo)

        self.trig_level_spin = QDoubleSpinBox()
        self.trig_level_spin.setRange(-10.0, 10.0)
        self.trig_level_spin.setDecimals(3)
        self.trig_level_spin.setSingleStep(0.01)
        self.trig_level_spin.setValue(float(self.module.trigger_level))
        self.trig_level_spin.valueChanged.connect(self.on_trigger_level_changed)
        trig_layout.addRow(tr("Level:"), self.trig_level_spin)

        trig_group.setLayout(trig_layout)
        trigger_tab = QWidget()
        trigger_layout = QVBoxLayout(trigger_tab)
        trigger_layout.addWidget(trig_group)
        trigger_layout.addStretch()
        settings_tabs.addTab(trigger_tab, tr("Trigger"))

        left_layout.addWidget(settings_tabs)

        # Buttons
        self.rec_btn = QPushButton(tr("Record"))
        self.rec_btn.setCheckable(True)
        self.rec_btn.clicked.connect(self.on_record_toggle)
        self.rec_btn.setFixedHeight(36)
        left_layout.addWidget(self.rec_btn)

        self.analyze_btn = QPushButton(tr("Analyze"))
        self.analyze_btn.clicked.connect(self.on_analyze)
        self.analyze_btn.setEnabled(False)
        self.analyze_btn.setFixedHeight(36)
        self.analyze_btn.setToolTip(
            tr("Warning: Analysis can be slow for long recordings.\nComplexity ~ O(N * Scales).")
        )
        left_layout.addWidget(self.analyze_btn)

        layout.addWidget(left_panel)

        # --- Visualization ---
        plot_tabs = QTabWidget()

        # 1. Scalogram (Image)
        scalo_tab = QWidget()
        scalo_layout = QVBoxLayout(scalo_tab)
        self.wave_plot = pg.PlotWidget(title=tr("Transient Waveform"))
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
        scalo_layout.addWidget(self.scalo_win)
        plot_tabs.addTab(scalo_tab, tr("Wavelet Scalogram"))

        # 2. Waveform Plot
        waveform_tab = QWidget()
        waveform_layout = QVBoxLayout(waveform_tab)
        self.wave_plot.setLabel("left", tr("Amplitude"))
        self.wave_plot.setLabel("bottom", tr("Time"), units="s")
        self.wave_plot.showGrid(x=True, y=True)
        waveform_layout.addWidget(self.wave_plot)
        plot_tabs.addTab(waveform_tab, tr("Waveform"))

        layout.addWidget(plot_tabs)

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
        self.analyze_btn.setEnabled(self.analysis_worker is None)
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

    def on_analyze(self):
        if self.module.final_data is None:
            return

        if self.analysis_worker is not None:
            return

        self.analyze_btn.setEnabled(False)
        self.analyze_btn.setText(tr("Analyzing..."))
        self.rec_btn.setEnabled(False)

        self.analysis_worker = WaveletAnalysisWorker(
            self.module.final_data,
            self.module.fs,
            self.module.wavelet_name,
            self.module.min_anal_freq,
            self.module.max_anal_freq,
        )
        self.analysis_worker.result_ready.connect(self.on_analysis_finished)
        self.analysis_worker.failed.connect(self.on_analysis_failed)
        self.analysis_worker.finished.connect(self.analysis_worker.deleteLater)
        self.analysis_worker.start()

    def on_analysis_finished(self, times, freqs, mag):
        self.analysis_worker = None
        self._restore_analysis_ui()

        if times is None:
            return

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

    def on_analysis_failed(self, message: str):
        self.analysis_worker = None
        self._restore_analysis_ui()
        QMessageBox.critical(self, tr("Error"), message)

    def _restore_analysis_ui(self):
        self.analyze_btn.setEnabled(self.module.final_data is not None)
        self.analyze_btn.setText(tr("Analyze"))
        self.rec_btn.setEnabled(True)
