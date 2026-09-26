import logging
import time
import threading
from types import MappingProxyType

import numpy as np
import pyqtgraph as pg
from scipy.signal import butter, lfilter, sosfilt
from PyQt6.QtCore import QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from src.core.audio_engine import AudioEngine
from src.core.localization import tr
from src.gui.styles import button_style
from src.core.analysis import AudioCalc
from src.core.sound_level import ImpulseTimeWeighting, LevelHistory
from src.measurement_modules.base import MeasurementModule
from src.gui.widgets.compactable_interface import CompactableWidgetInterface
from src.gui.widgets.splittable_interface import SplittableWidgetInterface


logger = logging.getLogger(__name__)


class _AcquisitionEvents(QObject):
    finished = pyqtSignal(object)


class SoundLevelMeter(MeasurementModule):
    TIME_CONSTANTS = MappingProxyType({"FAST": 0.125, "SLOW": 1.0, "10ms": 0.010})

    def __init__(self, audio_engine: AudioEngine):
        super().__init__()
        self.audio_engine = audio_engine
        self.is_running = False
        self.freq_weighting = "A"
        self.time_weighting = "FAST"
        self.channel = 0
        self.target_duration = None
        self.bandwidth_mode = "20Hz - 20kHz"
        self.callback_id = None
        self._run_token = None
        self._state_lock = threading.RLock()
        self._events = _AcquisitionEvents()
        # Stream shutdown must run on the owning thread, never inside PortAudio.
        self._events.finished.connect(self._finish_analysis, Qt.ConnectionType.QueuedConnection)
        self.sample_rate = float(audio_engine.sample_rate or 48000)
        self.bw_filter = self.bw_filter_state = None
        self.sos_filter = self.filter_state = None
        self._reset_measurements()

    @property
    def name(self):
        return "Sound Level Meter"

    @property
    def description(self):
        return "Advanced sound pressure level meter with A/C/Z weighting and time constants."

    def get_widget(self):
        return SoundLevelMeterWidget(self)

    def _set_parameter(self, name, value):
        with self._state_lock:
            if getattr(self, name) == value:
                return
            setattr(self, name, value)
            self._update_filters()
            self._reset_measurements()

    def set_freq_weighting(self, weighting):
        self._set_parameter("freq_weighting", weighting)

    def set_time_weighting(self, weighting):
        self._set_parameter("time_weighting", weighting)

    def set_channel(self, channel):
        self._set_parameter("channel", channel)

    def set_target_duration(self, duration_str):
        duration = None
        if duration_str != "Continuous":
            duration = float(int(duration_str[:-3]) * 60 if duration_str.endswith("min") else int(duration_str[:-1]))
        self._set_parameter("target_duration", duration)

    def set_bandwidth_mode(self, mode):
        self._set_parameter("bandwidth_mode", mode)

    def _reset_measurements(self):
        """Start a new acquisition interval; caller owns the processing lock."""
        self.leq_integrator = 0.0
        self.leq_samples = 0
        self.lmax = -np.inf
        self.lmin = np.inf
        self.lpeak = -np.inf
        self.current_sq_val = 0.0
        self._impulse = ImpulseTimeWeighting()
        self._history = LevelHistory(self.sample_rate)
        self._history_snapshot = None
        self._target_samples = None if self.target_duration is None else round(self.target_duration * self.sample_rate)
        self.results = dict.fromkeys(("Lp", "Leq", "LE", "Lmax", "Lmin", "Lpeak"), -np.inf)

    def reset_measurements(self):
        with self._state_lock:
            self._update_filters()
            self._reset_measurements()

    def _update_filters(self):
        """Design and reset filters within the acquisition lock."""
        self.sample_rate = float(self.audio_engine.sample_rate or 48000)
        upper = 12500 if "12.5kHz" in self.bandwidth_mode else 8000 if "8kHz" in self.bandwidth_mode else 20000
        highpass = butter(4, 20, btype="highpass", fs=self.sample_rate, output="sos")
        if upper < self.sample_rate * 0.5 * 0.95:
            lowpass = butter(4, upper, btype="lowpass", fs=self.sample_rate, output="sos")
            self.bw_filter = np.vstack((highpass, lowpass))
        else:
            self.bw_filter = highpass
        self.bw_filter_state = np.zeros((len(self.bw_filter), 2))
        if self.freq_weighting == "A":
            self.sos_filter = AudioCalc.design_a_weighting(self.sample_rate)
        elif self.freq_weighting == "C":
            self.sos_filter = AudioCalc.design_c_weighting(self.sample_rate)
        else:
            self.sos_filter = None
        self.filter_state = None if self.sos_filter is None else np.zeros((len(self.sos_filter), 2))

    def start_analysis(self):
        if self.is_running:
            return
        self.stop_analysis()  # Release any registration awaiting completion delivery.
        with self._state_lock:
            self._update_filters()
            self._reset_measurements()
            token = self._run_token = object()
            self.is_running = True

        def callback(indata, outdata, frames, time_info, status):
            self.callback(indata, outdata, frames, time_info, status, run_token=token)

        try:
            self.callback_id = self.audio_engine.register_callback(callback)
        except Exception:
            with self._state_lock:
                self.is_running = False
                self._run_token = None
            logger.exception("Failed to start sound level measurement")

    def _finish_analysis(self, token):
        if token is self._run_token and not self.is_running:
            self.stop_analysis()

    def stop_analysis(self):
        with self._state_lock:
            self.is_running = False
            self._run_token = None
            callback_id, self.callback_id = self.callback_id, None
        if callback_id is not None:
            self.audio_engine.unregister_callback(callback_id)

    def callback(self, indata, outdata, frames, time_info, status, *, run_token=None):
        with self._state_lock:
            if not self.is_running or (run_token is not None and run_token is not self._run_token):
                return
            if not len(indata):
                return
            if self.sample_rate != float(self.audio_engine.sample_rate or 48000):
                self._update_filters()
                self._reset_measurements()
            # A fixed-duration acquisition includes exactly this many samples,
            # including the final partial callback. Wall-clock time is irrelevant.
            remaining = len(indata) if self._target_samples is None else self._target_samples - self.leq_samples
            signal = indata[:remaining, self.channel if self.channel < indata.shape[1] else 0]
            if not len(signal):
                return
            if self.bw_filter is not None:
                signal, self.bw_filter_state = sosfilt(self.bw_filter, signal, zi=self.bw_filter_state)
            if self.sos_filter is not None:
                signal, self.filter_state = sosfilt(self.sos_filter, signal, zi=self.filter_state)
            powers = signal**2
            if self.time_weighting == "IMPULSE":
                weighted = self._impulse.process(powers, self.sample_rate)
            else:
                alpha = -np.expm1(-1 / (self.sample_rate * self.TIME_CONSTANTS[self.time_weighting]))
                weighted, _ = lfilter([alpha], [1, -(1 - alpha)], powers, zi=[self.current_sq_val * (1 - alpha)])
            self.current_sq_val = float(weighted[-1])
            self.lmax = max(self.lmax, float(np.max(weighted)))
            self.lmin = min(self.lmin, float(np.min(weighted)))
            self.lpeak = max(self.lpeak, float(np.max(powers)))
            self.leq_integrator += float(np.sum(powers))
            self.leq_samples += len(powers)
            self._history.append(weighted)
            linear_results = {
                "Lp": self.current_sq_val,
                "Leq": self.leq_integrator / self.leq_samples,
                "LE": self.leq_integrator / self.sample_rate,
                "Lmax": self.lmax,
                "Lmin": self.lmin,
                "Lpeak": self.lpeak,
            }
            self.results = {key: float(10 * np.log10(value + 1e-12)) for key, value in linear_results.items()}
            if self._target_samples is not None and self.leq_samples >= self._target_samples:
                self.is_running = False
                self._events.finished.emit(self._run_token)

    def get_display_snapshot(self):
        with self._state_lock:
            if self._history_snapshot is None or self._history_snapshot.revision != self._history.revision:
                self._history_snapshot = self._history.snapshot()
            return self.results.copy(), self.leq_samples / self.sample_rate, self._history_snapshot

    @property
    def ln_history_count(self):
        return self._history.count

    def calculate_ln_statistics(self):
        return self.get_display_snapshot()[2].statistics.copy()

    def get_ln_histogram(self, bin_size=0.5):
        return self.get_display_snapshot()[2].histogram(bin_size)


class SoundLevelMeterWidget(QWidget, CompactableWidgetInterface, SplittableWidgetInterface):
    def __init__(self, module: SoundLevelMeter):
        QWidget.__init__(self)
        CompactableWidgetInterface.__init__(self)
        SplittableWidgetInterface.__init__(self)
        self.module = module

        # State tracking for optimization
        self._last_metrics = {}

        self.init_ui()

        # Theme handling
        self.app = QApplication.instance()
        if hasattr(self.app, "theme_manager"):
            self.app.theme_manager.theme_changed.connect(self.apply_theme)
            self.apply_theme(self.app.theme_manager.get_current_theme())

        self.last_ln_update_time = 0.0
        self._last_history_view = None
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_display)
        self.timer.start(50)  # 20Hz refresh

    def closeEvent(self, event):
        self.timer.stop()
        self.module.stop_analysis()
        super().closeEvent(event)

    def init_ui(self):
        # Main Layout: Sidebar (Left) + Content (Right)
        main_layout = QHBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)

        # --- Sidebar ---
        self.sidebar = QWidget()
        self.sidebar.setFixedWidth(250)
        self.control_widget = self.sidebar
        sidebar_layout = QVBoxLayout()
        sidebar_layout.setContentsMargins(10, 10, 10, 10)

        # Controls Group
        controls_group = QGroupBox(tr("Controls"))
        controls_layout = QVBoxLayout()

        self.btn_start = QPushButton(tr("Start"))
        self.btn_start.setCheckable(True)
        self.btn_start.setMinimumHeight(40)
        self.btn_start.toggled.connect(self.on_start_toggle)
        controls_layout.addWidget(self.btn_start)

        self.btn_reset = QPushButton(tr("Reset"))
        self.btn_reset.clicked.connect(self.module.reset_measurements)
        controls_layout.addWidget(self.btn_reset)

        controls_group.setLayout(controls_layout)
        sidebar_layout.addWidget(controls_group)

        # Settings Group
        settings_group = QGroupBox(tr("Settings"))
        settings_layout = QVBoxLayout()

        # Channel
        settings_layout.addWidget(QLabel(tr("Channel:")))
        self.combo_channel = QComboBox()
        self.combo_channel.addItems(["L", "R"])
        self.combo_channel.currentIndexChanged.connect(self.module.set_channel)
        settings_layout.addWidget(self.combo_channel)

        # Freq Weight
        settings_layout.addWidget(QLabel(tr("Freq Weight:")))
        self.combo_freq = QComboBox()
        self.combo_freq.addItems(["A", "C", "Z"])
        self.combo_freq.currentTextChanged.connect(self.module.set_freq_weighting)
        settings_layout.addWidget(self.combo_freq)

        # Time Weight
        settings_layout.addWidget(QLabel(tr("Time Weight:")))
        self.combo_time = QComboBox()
        self.combo_time.addItems(["FAST", "SLOW", "IMPULSE", "10ms"])
        self.combo_time.currentTextChanged.connect(self.module.set_time_weighting)
        settings_layout.addWidget(self.combo_time)

        # Bandwidth
        settings_layout.addWidget(QLabel(tr("Bandwidth:")))
        self.combo_bw = QComboBox()
        self.combo_bw.addItems(["20Hz - 20kHz", "20Hz - 12.5kHz", "20Hz - 8kHz"])
        self.combo_bw.currentTextChanged.connect(self.module.set_bandwidth_mode)
        settings_layout.addWidget(self.combo_bw)

        # Duration
        settings_layout.addWidget(QLabel(tr("Duration:")))
        self.combo_duration = QComboBox()
        self.combo_duration.addItems(
            ["Continuous", "1s", "3s", "5s", "10s", "20s", "30s", "1min", "2min", "5min", "10min", "15min", "30min"]
        )
        self.combo_duration.currentTextChanged.connect(self.module.set_target_duration)
        settings_layout.addWidget(self.combo_duration)

        settings_group.setToolTip(tr("Changing a measurement setting resets the acquisition and statistics."))
        settings_group.setLayout(settings_layout)
        sidebar_layout.addWidget(settings_group)

        sidebar_layout.addStretch()
        self.sidebar.setLayout(sidebar_layout)

        # --- Main Content Area ---
        content_area = QWidget()
        self.display_widget = content_area
        content_layout = QVBoxLayout()
        content_layout.setContentsMargins(10, 10, 10, 10)

        self.calibration_warning = QLabel("⚠ " + tr("SPL calibration is not set. Values are shown in dBFS."))
        self.calibration_warning.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.calibration_warning.setWordWrap(True)
        self.calibration_warning.setStyleSheet(
            "background-color: #fff3cd; color: #664d03; "
            "border: 1px solid #ffca2c; border-radius: 6px; "
            "font-weight: bold; padding: 8px;"
        )
        content_layout.addWidget(self.calibration_warning)

        self.acquisition_label = QLabel()
        self.acquisition_label.setWordWrap(True)
        self.acquisition_label.setToolTip(
            tr("LN uses 100 ms samples and retains the latest 10 hours. Leq covers the full acquisition.")
        )
        content_layout.addWidget(self.acquisition_label)

        # 1. Main Display (Big Numbers)
        display_frame = QWidget()
        display_frame.setObjectName("soundLevelReadouts")
        display_frame.setStyleSheet("QWidget#soundLevelReadouts { background-color: #000; border-radius: 8px; }")
        display_layout = QHBoxLayout()
        display_layout.setContentsMargins(8, 6, 8, 6)

        # Lp Display
        self.disp_lp = self._create_big_display(tr("Instantaneous (Lp)"), "#00ff00")
        display_layout.addWidget(self.disp_lp["container"])

        # Leq Display
        self.disp_leq = self._create_big_display(tr("Equivalent (Leq)"), "#00ccff")
        display_layout.addWidget(self.disp_leq["container"])

        display_frame.setLayout(display_layout)
        content_layout.addWidget(display_frame)

        # 2. Tabs for Graphs and Stats
        self.tabs = QTabWidget()

        # Tab 1: Histogram (Graph)
        self.tab_hist = QWidget()
        hist_layout = QVBoxLayout()

        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setBackground("#111")
        self.plot_widget.showGrid(x=True, y=True)
        self.plot_widget.setLabel("bottom", tr("Level"), units="dBFS")
        self.plot_widget.setLabel("left", tr("Probability"), units="%")

        self.hist_item = pg.BarGraphItem(x=[0], height=[0], width=0.4, brush="g")
        self.plot_widget.addItem(self.hist_item)

        hist_layout.addWidget(self.plot_widget)
        self.tab_hist.setLayout(hist_layout)
        self.tabs.addTab(self.tab_hist, tr("Histogram (LN)"))

        # Tab 2: Statistics (LN Table)
        self.tab_stats = QWidget()
        stats_layout = QVBoxLayout()
        ln_grid = QGridLayout()
        self.ln_labels = {}
        ln_metrics = [
            ("L5", "L5", 0, 0),
            ("L10", "L10", 0, 1),
            ("L50", "L50", 0, 2),
            ("L90", "L90", 0, 3),
            ("L95", "L95", 1, 0),
            ("Lhigh", "Lhigh", 1, 1),
            ("Llow", "Llow", 1, 2),
            ("Lave", "Lave", 1, 3),
        ]
        ln_font_style = "font-size: 24px; font-weight: bold; color: #00ffff;"

        for key, title_text, r, c in ln_metrics:
            container = QWidget()
            v_box = QVBoxLayout()
            title = QLabel(title_text)
            title.setAlignment(Qt.AlignmentFlag.AlignCenter)
            title.setStyleSheet("font-weight: bold; font-size: 14pt; color: #eee;")
            val_lbl = QLabel("--.-")
            val_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            val_lbl.setStyleSheet(ln_font_style)
            v_box.addWidget(title)
            v_box.addWidget(val_lbl)
            container.setLayout(v_box)
            container.setStyleSheet("background-color: #222; border-radius: 6px; margin: 4px;")
            ln_grid.addWidget(container, r, c)
            self.ln_labels[key] = val_lbl

        stats_layout.addLayout(ln_grid)
        stats_layout.addStretch()
        self.tab_stats.setLayout(stats_layout)
        self.tabs.addTab(self.tab_stats, tr("Statistics"))

        # Tab 3: Detailed Metrics
        self.tab_metrics = QWidget()
        metrics_layout = QVBoxLayout()
        m_grid = QGridLayout()
        self.metric_labels = {}
        metrics_list = [
            ("Lmax", tr("Maximum Level"), 0, 0),
            ("Lmin", tr("Minimum Level"), 0, 1),
            ("Lpeak", tr("Peak Level"), 1, 0),
            ("LE", tr("Sound Exposure Level"), 1, 1),
        ]

        for key, desc, r, c in metrics_list:
            container = QWidget()
            v_box = QVBoxLayout()
            lbl_title = QLabel(key)
            lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl_title.setStyleSheet("font-weight: bold; font-size: 16pt;")

            lbl_desc = QLabel(desc)
            lbl_desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl_desc.setStyleSheet("font-size: 11pt; color: #aaa;")

            lbl_val = QLabel("--.-")
            lbl_val.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl_val.setStyleSheet("font-size: 28px; font-weight: bold; color: #ffaa00;")

            v_box.addWidget(lbl_title)
            v_box.addWidget(lbl_desc)
            v_box.addWidget(lbl_val)
            container.setLayout(v_box)
            container.setStyleSheet("background-color: #1a1a1a; border-radius: 6px; margin: 5px;")
            m_grid.addWidget(container, r, c)
            self.metric_labels[key] = lbl_val

        metrics_layout.addLayout(m_grid)
        metrics_layout.addStretch()
        self.tab_metrics.setLayout(metrics_layout)
        self.tabs.addTab(self.tab_metrics, tr("Details"))

        content_layout.addWidget(self.tabs)
        content_area.setLayout(content_layout)

        # Assemble
        main_layout.addWidget(self.sidebar)
        main_layout.addWidget(content_area)
        self.setLayout(main_layout)
        self._update_calibration_display()

    def get_display_widget(self) -> QWidget:
        """Returns the display sub-widget (main display and tabs area)."""
        return self.display_widget

    def get_control_widget(self) -> QWidget:
        """Returns the controls sub-widget (sidebar settings panel)."""
        return self.control_widget

    def restore_split_panels(self) -> None:
        """Re-inserts display_widget and control_widget into the main layout after split reattach."""
        layout = self.layout()
        if layout is None:
            return
        layout.addWidget(self.control_widget)
        layout.addWidget(self.display_widget)
        self.control_widget.show()
        self.display_widget.show()

    def _create_big_display(self, title, color):
        container = QWidget()
        layout = QVBoxLayout()
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        lbl_title = QLabel(title)
        lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_title.setStyleSheet("color: #aaa; font-size: 14pt;")

        lbl_val = QLabel("--.-")
        lbl_val.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_val.setStyleSheet(f"color: {color}; font-size: 64px; font-weight: bold;")

        lbl_unit = QLabel("dB")
        lbl_unit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_unit.setStyleSheet(f"color: {color}; font-size: 18pt;")

        layout.addWidget(lbl_title)
        layout.addWidget(lbl_val)
        layout.addWidget(lbl_unit)
        container.setLayout(layout)
        return {"container": container, "label": lbl_val, "unit": lbl_unit}

    def _get_spl_calibration_offset(self):
        """Return a finite SPL offset, or None when absolute SPL is unavailable."""
        try:
            calibration = self.module.audio_engine.calibration
            offset = calibration.get_spl_offset_db()
            if offset is not None and np.isfinite(float(offset)):
                return float(offset)
        except (AttributeError, TypeError, ValueError):
            pass
        return None

    def _update_calibration_display(self):
        """Keep the warning banner and displayed units consistent with calibration."""
        spl_offset = self._get_spl_calibration_offset()
        spl_calibrated = spl_offset is not None
        level_unit = "dB SPL" if spl_calibrated else "dBFS"

        self.calibration_warning.setVisible(not spl_calibrated and not self.is_compact_mode())
        if self.disp_lp["unit"].text() != level_unit:
            self.disp_lp["unit"].setText(level_unit)
            self.disp_leq["unit"].setText(level_unit)

        return (spl_offset if spl_calibrated else 0.0), level_unit

    def on_start_toggle(self, checked):
        if checked:
            self.module.start_analysis()
        else:
            self.module.stop_analysis()
        self.update_display()
        self.apply_theme()

    def apply_theme(self, theme_name=None):
        if not theme_name and hasattr(self.app, "theme_manager"):
            theme_name = self.app.theme_manager.get_current_theme()

        if theme_name == "system" and hasattr(self.app, "theme_manager"):
            theme_name = self.app.theme_manager.get_effective_theme()

        checked = self.btn_start.isChecked()

        if checked:
            self.btn_start.setStyleSheet(button_style("stop", extra="font-weight: bold; font-size: 14px;"))
        else:
            self.btn_start.setStyleSheet(button_style("primary", extra="font-weight: bold; font-size: 14px;"))

    def update_display(self):
        running = self.module.is_running
        if not running and self.module.callback_id is not None:
            self.module.stop_analysis()
        if self.btn_start.isChecked() != running:
            self.btn_start.blockSignals(True)
            self.btn_start.setChecked(running)
            self.btn_start.blockSignals(False)
            self.apply_theme()
        self.btn_start.setText(tr("Stop") if running else tr("Start"))
        cal_db, level_unit = self._update_calibration_display()
        vals, elapsed, history = self.module.get_display_snapshot()
        self.acquisition_label.setText(
            tr("{state} · Acquired: {elapsed:.1f} s · LN window: {window:.1f} s").format(
                state=tr("Running") if running else tr("Stopped"),
                elapsed=elapsed,
                window=history.powers.size * history.interval_seconds,
            )
        )

        def fmt(value):
            return f"{value + cal_db:.1f}" if np.isfinite(value) else "--.-"

        for key, display in (("Lp", self.disp_lp), ("Leq", self.disp_leq)):
            text = fmt(vals[key])
            if self._last_metrics.get(key) != text:
                self._last_metrics[key] = text
                display["label"].setText(text)
        for key, label in self.metric_labels.items():
            text = f"{fmt(vals[key])} {level_unit}"
            if self._last_metrics.get(key) != text:
                self._last_metrics[key] = text
                label.setText(text)

        # A reset or stop is visible immediately. Expensive distribution work
        # runs at most four times per second, on a detached history snapshot.
        view_key = (history, cal_db, level_unit)
        previous = self._last_history_view
        unchanged = previous is not None and previous[0] is history and previous[1:] == view_key[1:]
        if unchanged:
            return
        now = time.monotonic()
        if running and history.powers.size and now - self.last_ln_update_time < 0.25:
            return
        self.last_ln_update_time = now
        self._last_history_view = view_key
        for key, label in self.ln_labels.items():
            label.setText(f"{fmt(history.statistics.get(key, -np.inf))} {level_unit}")
        centers, probabilities = history.histogram()
        self.hist_item.setOpts(x=centers + cal_db, height=probabilities, width=0.4)
        self.plot_widget.setLabel("bottom", tr("Level"), units=level_unit)

    def update_compact_layout(self):
        compact = self.is_compact_mode()
        # In split mode sidebar/control_widget lives in its own window (parent != self).
        # Only hide it when it is still embedded in this widget.
        if hasattr(self, "sidebar"):
            is_split = self.sidebar.parent() is not self
            if not is_split:
                self.sidebar.setHidden(compact)
        if hasattr(self, "tabs"):
            self.tabs.setHidden(compact)
        if hasattr(self, "calibration_warning"):
            self._update_calibration_display()

        # Trigger parent window size adjustment to prevent vertical stretching
        win = self.window()
        if win:
            from PyQt6 import sip
            from PyQt6.QtCore import QTimer

            QTimer.singleShot(50, lambda: win.adjustSize() if not sip.isdeleted(win) else None)
