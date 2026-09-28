"""Long-span monitoring with a sample-clocked, peak-preserving envelope."""

import logging
import math
import threading
from collections import deque
from dataclasses import dataclass

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import QEvent, QSignalBlocker, Qt, QTimer
from PyQt6.QtGui import QPalette
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.core.audio_engine import AudioEngine
from src.core.localization import tr
from src.core.utils import format_si
from src.gui.styles import button_style
from src.gui.widgets.compactable_interface import CompactableWidgetInterface
from src.gui.widgets.splittable_interface import SplittableWidgetInterface
from src.measurement_modules.base import MeasurementModule

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TimeSeriesFrame:
    """Detached acquisition data; display changes never modify these values.

    Values contain min/max/mean for both channels. The last bucket may be
    partial; its weight preserves both the newest peak and the exact DC mean.
    Times refer to bucket ends relative to the newest sample.
    """

    times: np.ndarray
    values: np.ndarray
    interval_s: float
    channels: int
    last_bucket_fraction: float = 1.0

    @property
    def duration_s(self) -> float:
        return (len(self.times) - 1 + self.last_bucket_fraction) * self.interval_s

    def dc_mean(self) -> np.ndarray:
        total = self.values[:, 2].sum(axis=0, dtype=np.float64)
        total -= self.values[-1, 2].astype(np.float64) * (1 - self.last_bucket_fraction)
        return total / (len(self.times) - 1 + self.last_bucket_fraction)

    def cropped(self, span_s: float) -> "TimeSeriesFrame":
        start = int(np.searchsorted(self.times, -span_s, side="right"))
        return TimeSeriesFrame(
            self.times[start:], self.values[start:], self.interval_s, self.channels, self.last_bucket_fraction
        )

    def envelope(self, max_bins: int) -> tuple[np.ndarray, np.ndarray]:
        """Reduce drawing cost without discarding extrema or the final bucket."""
        count = len(self.times)
        if count <= max_bins:
            return self.times, self.values
        step = math.ceil(count / max_bins)
        starts = np.arange(0, count, step)
        ends = np.minimum(starts + step, count)
        values = np.empty((len(starts), 3, 2), dtype=np.float32)
        values[:, 0] = np.minimum.reduceat(self.values[:, 0], starts)
        values[:, 1] = np.maximum.reduceat(self.values[:, 1], starts)
        sums = np.add.reduceat(self.values[:, 2], starts, dtype=np.float64)
        weights = (ends - starts).astype(np.float64)
        sums[-1] -= self.values[-1, 2].astype(np.float64) * (1 - self.last_bucket_fraction)
        weights[-1] -= 1 - self.last_bucket_fraction
        values[:, 2] = sums / weights[:, None]
        return (self.times[starts] + self.times[ends - 1]) / 2, values


class RawTimeSeries(MeasurementModule):
    """Bounded envelope history, independent of callback and GUI cadence."""

    def __init__(self, audio_engine: AudioEngine):
        self.audio_engine = audio_engine
        self.is_running = False
        self.time_span_s = 10.0
        self.vscale = 1.0
        self.paused = False
        self.show_dc_offset = False
        self.show_volts = False
        self.max_span_s = 300.0
        self.storage_rate_hz = 2000.0  # Approximate bucket rate, never the timebase.
        self.callback_id = None
        self.error_message = ""
        self.revision = 0
        self._lock = threading.Lock()
        self._run_token = None
        self._held_frame: TimeSeriesFrame | None = None
        self._reset_history(float(audio_engine.sample_rate))

    @property
    def name(self) -> str:
        return "Raw Time Series"

    @property
    def description(self) -> str:
        return "Long-span scrolling time series monitor."

    def get_widget(self):
        return RawTimeSeriesWidget(self)

    def _reset_history(self, sample_rate: float):
        if not math.isfinite(sample_rate) or sample_rate <= 0:
            raise ValueError("Invalid sample rate")
        self._sample_rate = sample_rate
        self._bucket_size = max(1, round(sample_rate / self.storage_rate_hz))
        self._interval = self._bucket_size / sample_rate
        self._capacity = math.ceil(self.max_span_s / self._interval) + 1
        self._chunk_size = min(1024, self._capacity)
        self._chunks: deque[np.ndarray] = deque(maxlen=math.ceil(self._capacity / self._chunk_size))
        self._chunk = np.empty((self._chunk_size, 3, 2), dtype=np.float32)
        self._chunk_filled = 0
        self._pending = np.empty((0, 2), dtype=np.float32)
        self._filled = self._sample_count = 0
        self._channels = 0
        self._held_frame = None
        self.paused = False
        self.revision += 1

    def start_analysis(self):
        if self.is_running:
            return
        # Also retry a registration whose previous removal failed.
        self.stop_analysis()
        with self._lock:
            self._reset_history(float(self.audio_engine.sample_rate))
            self.error_message = ""
            token = self._run_token = object()
            self.is_running = True

        def callback(indata, outdata, frames, time, status):
            if outdata is not None:
                outdata.fill(0)
            with self._lock:
                if not self.is_running or token is not self._run_token:
                    return
                if float(self.audio_engine.sample_rate) != self._sample_rate:
                    self._interrupt(tr("Sample rate changed. Start again to acquire a new history."))
                    return
                if status and (
                    getattr(status, "input_overflow", False)
                    or getattr(status, "input_underflow", False)
                    or not hasattr(status, "input_overflow")
                ):
                    self._interrupt(tr("Audio input was interrupted. Start again to acquire a new history."))
                    return
                if indata is None or indata.ndim != 2 or indata.shape[1] == 0 or len(indata) != frames:
                    self._interrupt(tr("Audio input was interrupted. Start again to acquire a new history."))
                    return
                if not len(indata):
                    return
                channels = min(2, indata.shape[1])
                if self._channels and channels != self._channels:
                    self._interrupt(tr("Input channels changed. Start again to acquire a new history."))
                    return
                self._channels = channels
                data = indata[:, :2] if channels == 2 else np.repeat(indata[:, :1], 2, axis=1)
                self._append(data)

        try:
            self.callback_id = self.audio_engine.register_callback(callback)
        except Exception as exc:
            with self._lock:
                self._interrupt(str(exc))
                self._run_token = None
            raise

    def _interrupt(self, message: str):
        # The GUI/owner unregisters later: never stop PortAudio from its callback.
        self.error_message = message
        self.is_running = False
        self.revision += 1

    def _append(self, data: np.ndarray):
        """Reduce contiguous sample buckets, carrying their phase across callbacks."""
        if len(self._pending):
            data = np.concatenate((self._pending, data))
        complete = len(data) // self._bucket_size * self._bucket_size
        if not np.isfinite(data[complete:]).all():
            self._interrupt(tr("Invalid audio samples. Start again to acquire a new history."))
            return
        groups = data[:complete].reshape(-1, self._bucket_size, 2)
        if len(groups):
            values = np.stack(
                (groups.min(axis=1), groups.max(axis=1), groups.mean(axis=1, dtype=np.float64)), axis=1
            ).astype(np.float32)
            if not np.isfinite(values).all():
                self._interrupt(tr("Invalid audio samples. Start again to acquire a new history."))
                return
            self._store_buckets(values)
        self._sample_count += len(data) - len(self._pending)
        self._pending = data[complete:].copy()
        self.revision += 1

    def _store_buckets(self, values: np.ndarray):
        """Publish immutable chunks so copying a five-minute view cannot block audio.

        Only the current, at-most-24-KiB chunk is mutable. The GUI takes references
        to completed chunks and copies the current tail under the short lock,
        then assembles its detached frame after releasing the lock.
        """
        self._filled = min(self._capacity, self._filled + len(values))
        values = values[-self._capacity :]
        offset = 0
        while offset < len(values):
            count = min(len(values) - offset, self._chunk_size - self._chunk_filled)
            self._chunk[self._chunk_filled : self._chunk_filled + count] = values[offset : offset + count]
            self._chunk_filled += count
            offset += count
            if self._chunk_filled == self._chunk_size:
                self._chunk.setflags(write=False)
                self._chunks.append(self._chunk)
                self._chunk = np.empty_like(self._chunk)
                self._chunk_filled = 0

    def stop_analysis(self):
        with self._lock:
            self.is_running = False
            self._run_token = None
        if self.callback_id is not None:
            # Retain the id on failure so the owner can retry cleanup.
            self.audio_engine.unregister_callback(self.callback_id)
            self.callback_id = None

    def set_display_hold(self, enabled: bool):
        if enabled == self.paused:
            return
        self._held_frame = self._snapshot(self.max_span_s) if enabled else None
        self.paused = enabled

    def _snapshot(self, span_s: float) -> TimeSeriesFrame | None:
        with self._lock:
            interval, sample_rate = self._interval, self._sample_rate
            bucket_size, channels = self._bucket_size, self._channels
            count = min(self._filled, math.ceil(span_s / interval))
            pending = self._pending  # Replaced, never modified by the callback.
            parts = []
            remaining = count
            tail_count = min(remaining, self._chunk_filled)
            if tail_count:
                parts.append(self._chunk[self._chunk_filled - tail_count : self._chunk_filled].copy())
                remaining -= tail_count
            for chunk in reversed(self._chunks):
                if remaining <= 0:
                    break
                parts.append(chunk[-remaining:])
                remaining -= len(parts[-1])

        remainder = len(pending)
        if count <= 0 and not remainder:
            return None
        times = np.empty(count + bool(remainder), dtype=np.float64)
        times[:count] = np.arange(-count + 1, 1, dtype=np.float64) * interval - remainder / sample_rate
        if remainder:
            partial = np.stack(
                (pending.min(axis=0), pending.max(axis=0), pending.mean(axis=0, dtype=np.float64))
            ).astype(np.float32)
            parts.insert(0, partial[None])
            times[-1] = 0.0
        values = np.concatenate(parts[::-1])
        times.setflags(write=False)
        values.setflags(write=False)
        return TimeSeriesFrame(
            times, values, interval, channels, remainder / bucket_size if remainder else 1.0
        ).cropped(span_s)

    def get_display_frame(self, span_s: float) -> TimeSeriesFrame | None:
        if not math.isfinite(span_s) or span_s <= 0:
            return None
        if self.paused:
            return self._held_frame.cropped(span_s) if self._held_frame is not None else None
        return self._snapshot(min(span_s, self.max_span_s))

    def get_display_data(self, span_s: float) -> tuple[np.ndarray, np.ndarray] | None:
        """Return bucket means for callers needing a single value per interval."""
        frame = self.get_display_frame(span_s)
        return (frame.times, frame.values[:, 2]) if frame is not None else None


class RawTimeSeriesWidget(QWidget, CompactableWidgetInterface, SplittableWidgetInterface):
    def __init__(self, module: RawTimeSeries):
        QWidget.__init__(self)
        CompactableWidgetInterface.__init__(self)
        SplittableWidgetInterface.__init__(self)
        self.module = module
        self._last_frame = None
        self._last_view_key = None
        self._init_ui()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._update_plot)
        self.timer.start(100)
        self._update_plot()

    def get_display_widget(self) -> QWidget:
        return self.display_widget

    def get_control_widget(self) -> QWidget:
        return self.right_widget

    def restore_split_panels(self) -> None:
        layout = self.layout()
        layout.addWidget(self.display_widget, stretch=1)
        layout.addWidget(self.right_widget)
        self.display_widget.show()
        self.right_widget.show()
        self.update_compact_layout()

    def _init_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(12)
        self.display_widget = QWidget()
        left = QVBoxLayout(self.display_widget)
        left.setContentsMargins(0, 0, 0, 0)

        transport = QHBoxLayout()
        self.btn_start = QPushButton(tr("Start"))
        self.btn_start.setStyleSheet(button_style("primary", toggle=True))
        self.btn_start.setCheckable(True)
        self.btn_start.setToolTip(tr("Start a new history. Stop keeps the last acquired data."))
        self.btn_start.clicked.connect(self._on_start_toggled)
        self.btn_pause = QPushButton(tr("Hold Display"))
        self.btn_pause.setCheckable(True)
        self.btn_pause.setToolTip(tr("Freeze the view while acquisition continues."))
        self.btn_pause.clicked.connect(self._on_pause_toggled)
        transport.addWidget(self.btn_start)
        transport.addWidget(self.btn_pause)
        transport.addStretch()
        left.addLayout(transport)

        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        self.status_label.setTextFormat(Qt.TextFormat.PlainText)
        self.status_label.setAccessibleName(tr("Acquisition status"))
        left.addWidget(self.status_label)

        self.plots = pg.GraphicsLayoutWidget()
        self.plot_ch1 = self.plots.addPlot(row=0, col=0)
        self.plot_ch2 = self.plots.addPlot(row=1, col=0)
        self.plot_ch2.setXLink(self.plot_ch1)
        self.plot_ch2.setYLink(self.plot_ch1)
        self._envelope_curves = []
        self._fills = []
        for plot in (self.plot_ch1, self.plot_ch2):
            plot.showGrid(x=True, y=True, alpha=0.15)
            plot.getAxis("left").setWidth(76)
            plot.getAxis("bottom").setHeight(40)
            plot.setMouseEnabled(x=False, y=False)
            plot.hideButtons()
            plot.setMenuEnabled(False)
            lower = plot.plot()
            upper = plot.plot()
            mean = plot.plot()
            fill = pg.FillBetweenItem(lower, upper)
            plot.addItem(fill)
            self._envelope_curves.append((lower, upper, mean))
            self._fills.append(fill)
        self.curve_ch1 = self._envelope_curves[0][2]
        self.curve_ch2 = self._envelope_curves[1][2]
        self.plot_ch1.getAxis("bottom").setStyle(showValues=False)
        self.plot_ch2.setLabel("bottom", tr("Time relative to latest sample"), units="s")
        left.addWidget(self.plots, 1)

        self.view_label = QLabel()
        self.view_label.setWordWrap(True)
        left.addWidget(self.view_label)
        self.unit_note = QLabel()
        self.unit_note.setWordWrap(True)
        left.addWidget(self.unit_note)
        root.addWidget(self.display_widget, stretch=1)

        self.right_widget = QGroupBox(tr("Display"))
        right = QVBoxLayout(self.right_widget)
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.combo_span = QComboBox()
        self._span_options = {"10 s": 10.0, "60 s": 60.0, "300 s": 300.0}
        for text, value in self._span_options.items():
            self.combo_span.addItem(text, value)
        self.combo_span.setCurrentIndex(max(0, self.combo_span.findData(self.module.time_span_s)))
        self.combo_span.currentTextChanged.connect(self._on_span_changed)
        form.addRow(tr("Time Span:"), self.combo_span)

        self.combo_v = QComboBox()
        self._vscale_options = {
            f"{value:g}×": value
            for value in (0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50, 100, 200, 500, 1000)
        }
        for text, value in self._vscale_options.items():
            self.combo_v.addItem(text, value)
        self.combo_v.setCurrentIndex(max(0, self.combo_v.findData(self.module.vscale)))
        self.combo_v.setToolTip(tr("Zoom changes the axis range, not the measured amplitude."))
        self.combo_v.currentTextChanged.connect(self._on_vscale_changed)
        form.addRow(tr("Vertical zoom:"), self.combo_v)
        right.addLayout(form)

        self.chk_volts = QCheckBox(tr("Show Volts"))
        self.chk_volts.setChecked(self.module.show_volts)
        self.chk_volts.toggled.connect(self._on_volts_toggled)
        right.addWidget(self.chk_volts)
        self.chk_dc = QCheckBox(tr("Show DC Offset"))
        self.chk_dc.setChecked(self.module.show_dc_offset)
        self.chk_dc.toggled.connect(self._on_dc_toggled)
        right.addWidget(self.chk_dc)
        self.lbl_dc_title = QLabel(tr("DC mean of displayed window"))
        self.lbl_dc_title.setWordWrap(True)
        self.lbl_dc_ch1 = QLabel()
        self.lbl_dc_ch2 = QLabel()
        for label in (self.lbl_dc_title, self.lbl_dc_ch1, self.lbl_dc_ch2):
            right.addWidget(label)
        right.addStretch()
        self.envelope_note = QLabel(
            tr("The envelope preserves peaks. Fine waveform detail is reduced over long time spans.")
        )
        self.envelope_note.setWordWrap(True)
        right.addWidget(self.envelope_note)
        root.addWidget(self.right_widget)
        self._apply_dc_visibility()
        self._apply_theme()

    def _input_sensitivity(self) -> float | None:
        try:
            value = float(self.module.audio_engine.calibration.input_sensitivity)
            return value if np.isfinite(value) and value > 0 else None
        except (AttributeError, TypeError, ValueError):
            return None

    def _get_unit_factor(self) -> float:
        if self.module.show_volts and (sensitivity := self._input_sensitivity()) is not None:
            return sensitivity
        return 1.0

    def _get_unit_label(self) -> str:
        return "V" if self.module.show_volts and self._input_sensitivity() is not None else "FS"

    def _format_amplitude(self, value: float) -> str:
        try:
            value = float(value)
        except (TypeError, ValueError):
            return "-"
        if not np.isfinite(value):
            return "-"
        return format_si(value, "V", sig_figs=4) if self._get_unit_label() == "V" else f"{value:.6g} FS"

    def _apply_unit_settings(self):
        unit = self._get_unit_label()
        for plot in (self.plot_ch1, self.plot_ch2):
            plot.setLabel("left", tr("Amplitude"), units=unit)
        calibrated = bool(getattr(self.module.audio_engine.calibration, "input_sensitivity_is_calibrated", False))
        if self._input_sensitivity() is None:
            self.unit_note.setText(tr("Input: Uncalibrated (FS)"))
        else:
            self.unit_note.setText(
                tr("Voltage uses the input calibration.")
                if calibrated
                else tr("Voltage is nominal; input calibration is not set.")
            )
        self.unit_note.setVisible(self.module.show_volts)

    def _apply_dc_visibility(self):
        for label in (self.lbl_dc_title, self.lbl_dc_ch1, self.lbl_dc_ch2):
            label.setVisible(self.module.show_dc_offset)

    def _on_start_toggled(self, checked: bool):
        try:
            if checked:
                self.module.start_analysis()
            else:
                self.module.stop_analysis()
        except Exception as exc:
            logger.exception("Raw time series acquisition failed")
            self.module.error_message = str(exc)
        self._update_plot()

    def _on_span_changed(self, key: str):
        self.module.time_span_s = self._span_options[key]
        self._update_plot()

    def _on_vscale_changed(self, key: str):
        self.module.vscale = self._vscale_options[key]
        self._update_plot()

    def _on_pause_toggled(self, checked: bool):
        self.module.set_display_hold(checked)
        self._update_plot()

    def _on_volts_toggled(self, checked: bool):
        self.module.show_volts = checked
        self._update_plot()

    def _on_dc_toggled(self, checked: bool):
        self.module.show_dc_offset = checked
        self._apply_dc_visibility()
        self._update_plot()

    def _apply_view_ranges(self):
        self.plot_ch1.setXRange(-self.module.time_span_s, 0, padding=0)
        bound = 1.1 * self._get_unit_factor() / self.module.vscale
        self.plot_ch1.setYRange(-bound, bound, padding=0)

    def _update_status(self):
        running = self.module.is_running
        with QSignalBlocker(self.btn_start), QSignalBlocker(self.btn_pause):
            self.btn_start.setChecked(running)
            self.btn_pause.setChecked(self.module.paused)
        self.btn_start.setText(tr("Stop") if running else tr("Start"))
        self.btn_pause.setText(tr("Resume Display") if self.module.paused else tr("Hold Display"))
        self.btn_pause.setEnabled(self.module.paused or (running and self.module._sample_count > 0))
        if self.module.error_message:
            text = tr("Acquisition stopped: {0}").format(self.module.error_message)
        elif self.module.paused:
            text = tr("Held — acquisition running") if running else tr("Stopped — display held")
        elif running:
            text = tr("Running") if self.module._sample_count else tr("Waiting for audio")
        else:
            text = tr("Stopped — last value") if self.module._sample_count else tr("Ready")
        self.status_label.setText(text)

    def _update_plot(self):
        if not self.module.is_running and self.module.callback_id is not None:
            try:
                self.module.stop_analysis()
            except Exception as exc:
                self.module.error_message = str(exc)
        self._update_status()
        source = id(self.module._held_frame) if self.module.paused else self.module.revision
        key = (
            source,
            self.module.paused,
            self.module.time_span_s,
            self.module.vscale,
            self.module.show_volts,
            self._get_unit_factor(),
            self._get_unit_label(),
            bool(getattr(self.module.audio_engine.calibration, "input_sensitivity_is_calibrated", False)),
            self.module.show_dc_offset,
        )
        if self._last_view_key == key:
            return
        self._last_view_key = key
        self._apply_unit_settings()
        self._last_frame = frame = self.module.get_display_frame(self.module.time_span_s)
        self._apply_view_ranges()
        if frame is None:
            for curves in self._envelope_curves:
                for curve in curves:
                    curve.clear()
            self.lbl_dc_ch1.setText("CH1: —")
            self.lbl_dc_ch2.setText("CH2: —")
            self.plot_ch2.setTitle(tr("CH2"), color=self._channel_colors[1])
            self.view_label.setText(tr("Start to capture a new history."))
            return

        unit_factor = self._get_unit_factor()
        times, values = frame.envelope(max_bins=2000)
        for channel, curves in enumerate(self._envelope_curves):
            for statistic, curve in enumerate(curves):
                curve.setData(times, values[:, statistic, channel] * unit_factor)
        dc = frame.dc_mean() * unit_factor
        self.lbl_dc_ch1.setText(f"CH1: {self._format_amplitude(dc[0])}")
        self.lbl_dc_ch2.setText(f"CH2: {self._format_amplitude(dc[1])}")
        self.view_label.setText(tr("Peak envelope · Displayed history: {0:.2f} s").format(frame.duration_s))
        self.plot_ch2.setTitle(
            tr("CH2") if frame.channels == 2 else tr("CH2 · mirrors mono input"), color=self._channel_colors[1]
        )

    def _apply_theme(self):
        palette = self.palette()
        dark = palette.color(QPalette.ColorRole.Window).lightness() < 128
        self._channel_colors = ("#59baff", "#ffc46b") if dark else ("#1264a3", "#a75508")
        self.plots.setBackground(palette.color(QPalette.ColorRole.Base))
        foreground = palette.color(QPalette.ColorRole.Text)
        for channel, plot in enumerate((self.plot_ch1, self.plot_ch2)):
            color = self._channel_colors[channel]
            plot.setTitle(tr("CH1") if channel == 0 else tr("CH2"), color=color)
            for orientation in ("left", "bottom"):
                plot.getAxis(orientation).setPen(foreground)
                plot.getAxis(orientation).setTextPen(foreground)
            for curve in self._envelope_curves[channel]:
                curve.setPen(pg.mkPen(color, width=1))
            fill = pg.mkColor(color)
            fill.setAlpha(45)
            self._fills[channel].setBrush(fill)
        self._last_view_key = None

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.PaletteChange and hasattr(self, "_envelope_curves"):
            self._apply_theme()

    def update_compact_layout(self):
        # Acquisition controls and state stay next to the plot even when split.
        if self.right_widget.parent() is self:
            self.right_widget.setHidden(self.is_compact_mode())

    def closeEvent(self, event):
        self.timer.stop()
        try:
            self.module.stop_analysis()
        except Exception:
            logger.exception("Failed to release raw time series callback")
        super().closeEvent(event)
