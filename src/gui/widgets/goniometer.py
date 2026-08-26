from __future__ import annotations

import logging
import math
import time
from collections import deque
from dataclasses import dataclass
from enum import IntFlag, StrEnum
from fractions import Fraction

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import QPointF, QRectF, QSize, Qt, QTimer
from PyQt6.QtGui import QColor, QCloseEvent, QPainter, QPen, QPolygonF
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from scipy.ndimage import gaussian_filter

from src.core.audio_engine import AudioEngine
from src.core.localization import tr
from src.gui.styles import STYLE_TOGGLE_BTN_DARK, STYLE_TOGGLE_BTN_LIGHT
from src.gui.widgets.compactable_interface import CompactableWidgetInterface
from src.gui.widgets.splittable_interface import SplittableWidgetInterface
from src.measurement_modules.base import MeasurementModule


logger = logging.getLogger(__name__)


class GoniometerRunState(StrEnum):
    IDLE = "idle"
    STARTING = "starting"
    RUNNING = "running"
    FAILED = "failed"


class CorrelationValidity(StrEnum):
    VALID = "valid"
    WAITING = "waiting"
    NO_SIGNAL = "no_signal"
    ONE_CHANNEL_LOW = "one_channel_low"
    MONO_INPUT = "mono_input"
    NONFINITE = "nonfinite"
    CLIPPED = "clipped"
    IO_ERROR = "io_error"


class GoniometerQualityFlag(IntFlag):
    NONE = 0
    CLIPPED_LEFT = 1 << 0
    CLIPPED_RIGHT = 1 << 1
    IO_ERROR = 1 << 2
    NONFINITE = 1 << 3


@dataclass(frozen=True, slots=True)
class GoniometerSnapshot:
    generation: int
    total_samples: int
    captured_at: float
    audio: np.ndarray
    new_sample_offset: int
    display_dropped_samples: int
    correlation: float | None
    correlation_validity: CorrelationValidity
    peak_left: float
    peak_right: float
    quality_flags: GoniometerQualityFlag
    run_state: GoniometerRunState
    error_message: str | None


class Goniometer(MeasurementModule):
    """Real-time stereo vectorscope model with a stable GUI snapshot boundary."""

    silence_threshold_dbfs = -80.0
    clip_threshold = 1.0

    def __init__(self, audio_engine: AudioEngine):
        self.audio_engine = audio_engine

        # User settings
        self.buffer_size = 4096
        self.manual_gain = 1.0
        self.auto_gain = False
        self.effective_gain = 1.0
        self.correlation_response_seconds = 0.300
        self.persistence_seconds = 0.500
        self.trace_mode = "Lines"
        self.color_palette = "Green"
        self.glow_amount = 0.0
        self.mapping_mode = "ms"
        self.invert_x = False
        self.invert_y = False
        self.show_direction_guides = True
        self.show_axes = False
        self.show_grid = True

        # Lifecycle state
        self.run_state = GoniometerRunState.IDLE
        self.is_running = False
        self.callback_id: int | None = None
        self.error_message: str | None = None

        # Single-producer ring buffer. The callback writes; the GUI only copies.
        self._ring = np.zeros((self.buffer_size, 2), dtype=np.float64)
        self._write_index = 0
        self._ring_count = 0
        self._total_samples = 0
        self._generation = 0
        self._captured_at = 0.0

        # Time-weighted correlation statistics
        self._energy_left = 0.0
        self._energy_right = 0.0
        self._cross_energy = 0.0
        self.correlation: float | None = None
        self.correlation_validity = CorrelationValidity.WAITING
        self.peak_left = 0.0
        self.peak_right = 0.0
        self.quality_flags = GoniometerQualityFlag.NONE
        self._invalid_until_sample = 0
        self._reset_requested = False

        # Display-owned accumulation is retained on the module so split/reattach
        # and widget recreation preserve a single authoritative display state.
        self.heatmap_size = 400
        self.heatmap = np.zeros((self.heatmap_size, self.heatmap_size), dtype=np.float64)

    @property
    def gain(self) -> float:
        """Compatibility alias for callers that used the former gain setting."""
        return self.manual_gain

    @gain.setter
    def gain(self, value: float) -> None:
        self.manual_gain = float(value)
        if not self.auto_gain:
            self.effective_gain = self.manual_gain

    @property
    def decay(self) -> float:
        """Compatibility view of persistence at the nominal 30 FPS update rate."""
        return math.exp(-(1.0 / 30.0) / max(self.persistence_seconds, 1e-6))

    @decay.setter
    def decay(self, value: float) -> None:
        bounded = min(max(float(value), 0.0), 0.999999)
        if bounded <= 0.0:
            self.persistence_seconds = 0.05
        else:
            self.persistence_seconds = min(max(-(1.0 / 30.0) / math.log(bounded), 0.05), 5.0)

    @property
    def display_mode(self) -> str:
        """Compatibility alias for the former Line/Phosphor setting."""
        return "Phosphor" if self.trace_mode == "Density" else "Line"

    @display_mode.setter
    def display_mode(self, value: str) -> None:
        self.trace_mode = "Density" if value == "Phosphor" else "Lines"

    @property
    def smooth_lines(self) -> bool:
        return self.trace_mode == "Lines"

    @smooth_lines.setter
    def smooth_lines(self, enabled: bool) -> None:
        if self.trace_mode != "Density":
            self.trace_mode = "Lines" if enabled else "Points"

    @property
    def audio_buffer(self) -> np.ndarray:
        snapshot = self.get_snapshot()
        if snapshot is None:
            return np.empty((0, 2), dtype=np.float64)
        return snapshot.audio

    @property
    def name(self) -> str:
        return "Goniometer"

    @property
    def description(self) -> str:
        return "Stereo image visualizer (Lissajous) and Phase Correlation."

    def get_widget(self):
        return GoniometerWidget(self)

    def _sample_rate(self) -> float:
        try:
            rate = float(self.audio_engine.sample_rate)
        except (AttributeError, TypeError, ValueError):
            return 48000.0
        return rate if rate > 0.0 else 48000.0

    def _reset_realtime_state(self) -> None:
        self._generation += 1
        self._ring.fill(0.0)
        self._write_index = 0
        self._ring_count = 0
        self._total_samples = 0
        self._captured_at = 0.0
        self._energy_left = 0.0
        self._energy_right = 0.0
        self._cross_energy = 0.0
        self.correlation = None
        self.correlation_validity = CorrelationValidity.WAITING
        self.peak_left = 0.0
        self.peak_right = 0.0
        self.quality_flags = GoniometerQualityFlag.NONE
        self._invalid_until_sample = 0
        self._reset_requested = False
        self._generation += 1

    def clear_measurement(self) -> None:
        self.heatmap.fill(0.0)
        if self.is_running:
            self._reset_requested = True
        else:
            self._reset_realtime_state()

    def start_analysis(self) -> bool:
        if self.is_running:
            return True

        self.run_state = GoniometerRunState.STARTING
        self.error_message = None
        self._reset_realtime_state()
        self.heatmap.fill(0.0)

        try:
            callback_id = self.audio_engine.register_callback(self._callback)
        except Exception as exc:
            self.callback_id = None
            self.is_running = False
            self.run_state = GoniometerRunState.FAILED
            self.error_message = str(exc)
            logger.error("Failed to start Goniometer: %s", exc)
            return False

        self.callback_id = callback_id
        self.is_running = True
        self.run_state = GoniometerRunState.RUNNING
        return True

    def stop_analysis(self) -> None:
        callback_id = self.callback_id
        self.callback_id = None
        if callback_id is not None:
            try:
                self.audio_engine.unregister_callback(callback_id)
            except Exception:
                logger.exception("Failed to unregister Goniometer callback")
        self.is_running = False
        if self.run_state is not GoniometerRunState.FAILED:
            self.run_state = GoniometerRunState.IDLE

    @staticmethod
    def _input_status_is_invalid(status) -> bool:
        if not status:
            return False
        known = False
        for name in ("input_underflow", "input_overflow"):
            if hasattr(status, name):
                known = True
                if bool(getattr(status, name)):
                    return True
        return not known

    def _write_ring(self, left: np.ndarray, right: np.ndarray, frames: int) -> None:
        input_frames = frames
        if frames >= self.buffer_size:
            left = left[-self.buffer_size :]
            right = right[-self.buffer_size :]
            frames = self.buffer_size

        first = min(frames, self.buffer_size - self._write_index)
        stop = self._write_index + first
        self._ring[self._write_index : stop, 0] = left[:first]
        self._ring[self._write_index : stop, 1] = right[:first]

        remaining = frames - first
        if remaining:
            self._ring[:remaining, 0] = left[first : first + remaining]
            self._ring[:remaining, 1] = right[first : first + remaining]

        self._write_index = (self._write_index + frames) % self.buffer_size
        self._ring_count = min(self.buffer_size, self._ring_count + frames)
        self._total_samples += input_frames

    def _callback(self, indata, outdata, frames, time_info, status) -> None:
        del time_info
        outdata.fill(0)

        if self._reset_requested:
            self._reset_realtime_state()

        if indata.ndim != 2 or indata.shape[0] == 0 or indata.shape[1] == 0:
            return

        sample_count = min(int(frames), int(indata.shape[0]))
        if sample_count <= 0:
            return

        left = indata[:sample_count, 0]
        mono_input = indata.shape[1] < 2
        right = left if mono_input else indata[:sample_count, 1]

        min_left = float(np.min(left))
        max_left = float(np.max(left))
        min_right = float(np.min(right))
        max_right = float(np.max(right))
        peak_left = max(abs(min_left), abs(max_left))
        peak_right = max(abs(min_right), abs(max_right))

        energy_left = float(np.dot(left, left)) / sample_count
        energy_right = float(np.dot(right, right)) / sample_count
        cross_energy = float(np.dot(left, right)) / sample_count
        finite = all(math.isfinite(value) for value in (peak_left, peak_right, energy_left, energy_right, cross_energy))

        self._generation += 1
        if not finite:
            self.quality_flags |= GoniometerQualityFlag.NONFINITE
            self.correlation = None
            self.correlation_validity = CorrelationValidity.NONFINITE
            self._captured_at = time.monotonic()
            self._generation += 1
            return

        self._write_ring(left, right, sample_count)
        self.peak_left = peak_left
        self.peak_right = peak_right
        self._captured_at = time.monotonic()

        clipped_left = peak_left >= self.clip_threshold
        clipped_right = peak_right >= self.clip_threshold
        if clipped_left:
            self.quality_flags |= GoniometerQualityFlag.CLIPPED_LEFT
        if clipped_right:
            self.quality_flags |= GoniometerQualityFlag.CLIPPED_RIGHT

        io_invalid = self._input_status_is_invalid(status)
        if io_invalid:
            self.quality_flags |= GoniometerQualityFlag.IO_ERROR

        if clipped_left or clipped_right or io_invalid:
            invalid_samples = max(1, int(self.correlation_response_seconds * self._sample_rate()))
            self._invalid_until_sample = max(
                self._invalid_until_sample,
                self._total_samples + invalid_samples,
            )

        tau = max(self.correlation_response_seconds, 0.001)
        alpha = math.exp(-sample_count / (self._sample_rate() * tau))
        one_minus_alpha = 1.0 - alpha
        self._energy_left = alpha * self._energy_left + one_minus_alpha * energy_left
        self._energy_right = alpha * self._energy_right + one_minus_alpha * energy_right
        self._cross_energy = alpha * self._cross_energy + one_minus_alpha * cross_energy

        threshold_power = 10.0 ** (self.silence_threshold_dbfs / 10.0)
        left_present = self._energy_left >= threshold_power
        right_present = self._energy_right >= threshold_power

        if mono_input:
            self.correlation = None
            self.correlation_validity = CorrelationValidity.MONO_INPUT
        elif not left_present and not right_present:
            self.correlation = None
            self.correlation_validity = CorrelationValidity.NO_SIGNAL
        elif left_present != right_present:
            self.correlation = None
            self.correlation_validity = CorrelationValidity.ONE_CHANNEL_LOW
        elif self._total_samples < self._invalid_until_sample:
            self.correlation = None
            if io_invalid:
                self.correlation_validity = CorrelationValidity.IO_ERROR
            else:
                self.correlation_validity = CorrelationValidity.CLIPPED
        else:
            denominator = math.sqrt(self._energy_left * self._energy_right)
            if denominator > 0.0:
                self.correlation = float(np.clip(self._cross_energy / denominator, -1.0, 1.0))
                self.correlation_validity = CorrelationValidity.VALID
            else:
                self.correlation = None
                self.correlation_validity = CorrelationValidity.NO_SIGNAL

        self._generation += 1

    def _copy_ring_chronological(self, count: int, write_index: int) -> np.ndarray:
        result = np.empty((count, 2), dtype=np.float64)
        if count == 0:
            return result

        start = (write_index - count) % self.buffer_size
        first = min(count, self.buffer_size - start)
        result[:first] = self._ring[start : start + first]
        if first < count:
            result[first:] = self._ring[: count - first]
        return result

    def get_snapshot(self, since_total_samples: int | None = None) -> GoniometerSnapshot | None:
        """Return a coherent, chronological copy without blocking the audio callback."""
        for _attempt in range(3):
            generation_before = self._generation
            if generation_before & 1:
                continue

            total_samples = self._total_samples
            ring_count = self._ring_count
            write_index = self._write_index
            captured_at = self._captured_at
            correlation = self.correlation
            validity = self.correlation_validity
            peak_left = self.peak_left
            peak_right = self.peak_right
            quality_flags = self.quality_flags
            run_state = self.run_state
            error_message = self.error_message
            audio = self._copy_ring_chronological(ring_count, write_index)

            generation_after = self._generation
            if generation_before != generation_after or generation_after & 1:
                continue

            oldest_sample = total_samples - ring_count
            if since_total_samples is None:
                new_start = oldest_sample
                dropped = 0
            else:
                dropped = max(0, oldest_sample - since_total_samples)
                new_start = max(oldest_sample, min(since_total_samples, total_samples))

            return GoniometerSnapshot(
                generation=generation_after,
                total_samples=total_samples,
                captured_at=captured_at,
                audio=audio,
                new_sample_offset=new_start - oldest_sample,
                display_dropped_samples=dropped,
                correlation=correlation,
                correlation_validity=validity,
                peak_left=peak_left,
                peak_right=peak_right,
                quality_flags=quality_flags,
                run_state=run_state,
                error_message=error_message,
            )

        return None


class CorrelationMeter(QWidget):
    """A true bipolar correlation meter with accessible numeric output."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.current_value: float | None = None
        self.minimum_value: float | None = None
        self.maximum_value: float | None = None
        self.invalid_reason = tr("Waiting for audio")
        self.setMinimumHeight(58)
        self.setAccessibleName(tr("Correlation"))
        self._update_accessible_description()

    def sizeHint(self) -> QSize:
        return QSize(320, 64)

    def value_to_x(self, value: float, rect: QRectF | None = None) -> float:
        meter_rect = rect or QRectF(self.rect()).adjusted(18.0, 8.0, -18.0, -22.0)
        bounded = min(max(float(value), -1.0), 1.0)
        return meter_rect.left() + ((bounded + 1.0) * 0.5 * meter_rect.width())

    def set_reading(
        self,
        current: float | None,
        minimum: float | None,
        maximum: float | None,
        invalid_reason: str = "",
    ) -> None:
        self.current_value = current
        self.minimum_value = minimum
        self.maximum_value = maximum
        self.invalid_reason = invalid_reason
        self._update_accessible_description()
        self.update()

    def _update_accessible_description(self) -> None:
        if self.current_value is None:
            description = self.invalid_reason or tr("Waiting for audio")
        else:
            description = f"{self.current_value:+.2f}"
        self.setAccessibleDescription(description)

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        palette = self.palette()
        meter_rect = QRectF(self.rect()).adjusted(18.0, 8.0, -18.0, -22.0)
        painter.fillRect(meter_rect, palette.color(palette.ColorRole.Base))

        border = QPen(palette.color(palette.ColorRole.Mid), 1)
        painter.setPen(border)
        painter.drawRect(meter_rect)

        zero_x = self.value_to_x(0.0, meter_rect)
        painter.setPen(QPen(palette.color(palette.ColorRole.Text), 1))
        painter.drawLine(QPointF(zero_x, meter_rect.top()), QPointF(zero_x, meter_rect.bottom()))

        for value, label in ((-1.0, "-1"), (0.0, "0"), (1.0, "+1")):
            x = self.value_to_x(value, meter_rect)
            painter.drawLine(QPointF(x, meter_rect.bottom()), QPointF(x, meter_rect.bottom() + 4.0))
            painter.drawText(QPointF(x - 8.0, meter_rect.bottom() + 17.0), label)

        marker_color = QColor("#00897b")
        hold_color = QColor("#d84315")
        if self.minimum_value is not None:
            x = self.value_to_x(self.minimum_value, meter_rect)
            painter.setPen(QPen(hold_color, 2))
            painter.drawLine(QPointF(x, meter_rect.top()), QPointF(x, meter_rect.top() + 8.0))
        if self.maximum_value is not None:
            x = self.value_to_x(self.maximum_value, meter_rect)
            painter.setPen(QPen(hold_color, 2))
            painter.drawLine(QPointF(x, meter_rect.bottom() - 8.0), QPointF(x, meter_rect.bottom()))

        painter.setPen(QPen(marker_color, 2))
        painter.setBrush(marker_color)
        if self.current_value is None:
            painter.drawText(meter_rect, Qt.AlignmentFlag.AlignCenter, "—")
        else:
            x = self.value_to_x(self.current_value, meter_rect)
            triangle = QPolygonF(
                [
                    QPointF(x, meter_rect.top() + 2.0),
                    QPointF(x - 6.0, meter_rect.top() + 12.0),
                    QPointF(x + 6.0, meter_rect.top() + 12.0),
                ]
            )
            painter.drawPolygon(triangle)
            painter.drawText(
                QRectF(x - 32.0, meter_rect.top() + 12.0, 64.0, meter_rect.height() - 12.0),
                Qt.AlignmentFlag.AlignCenter,
                f"{self.current_value:+.2f}",
            )


class GoniometerWidget(QWidget, CompactableWidgetInterface, SplittableWidgetInterface):
    min_max_hold_seconds = 3.0
    line_cycle_count = 3
    line_trace_fallback_samples = 1024
    line_trace_max_points_per_gate = 384
    line_trace_period_tolerance = 0.20
    line_trace_ratio_max_denominator = 8
    line_trace_ratio_tolerance = 0.02
    line_trace_alphas = (72, 255)

    def __init__(self, module: Goniometer):
        QWidget.__init__(self)
        CompactableWidgetInterface.__init__(self)
        SplittableWidgetInterface.__init__(self)
        self.module = module
        self._display_held = False
        self._last_consumed_total = 0
        self._last_display_time = time.monotonic()
        self._recent_valid: deque[tuple[float, float]] = deque(maxlen=300)
        self._direction_labels: list[pg.TextItem] = []

        self.init_ui()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_display)
        self.timer.setInterval(33)

        self.update_palette()
        self._update_reference_lines()
        self._update_control_states()
        self._update_status(None)

    def init_ui(self) -> None:
        layout = QHBoxLayout(self)

        self.display_widget = QWidget(self)
        display_layout = QVBoxLayout(self.display_widget)
        display_layout.setContentsMargins(0, 0, 0, 0)

        self.status_container = QWidget(self.display_widget)
        status_layout = QHBoxLayout(self.status_container)
        status_layout.setContentsMargins(0, 0, 0, 0)
        self.status_label = QLabel(tr("Idle"))
        self.status_label.setWordWrap(True)
        self.status_label.setAccessibleName(tr("Status"))
        status_layout.addWidget(self.status_label)
        display_layout.addWidget(self.status_container)

        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setAspectLocked(True)
        self.plot_widget.setXRange(-1.1, 1.1, padding=0.0)
        self.plot_widget.setYRange(-1.1, 1.1, padding=0.0)
        self.plot_widget.setMouseEnabled(x=False, y=False)
        self.plot_widget.setBackground("#111111")
        self.plot_widget.setFrameShape(QFrame.Shape.NoFrame)
        self.plot_widget.setStyleSheet("border: none;")
        self.plot_widget.getPlotItem().layout.setContentsMargins(0, 0, 0, 0)

        self.ref_line_a = pg.InfiniteLine(
            pos=(0, 0),
            angle=90,
            pen=pg.mkPen("#777777", style=Qt.PenStyle.DashLine),
        )
        self.ref_line_b = pg.InfiniteLine(
            pos=(0, 0),
            angle=0,
            pen=pg.mkPen("#777777", style=Qt.PenStyle.DashLine),
        )
        self.plot_widget.addItem(self.ref_line_a)
        self.plot_widget.addItem(self.ref_line_b)

        self.line_traces = [self.plot_widget.plot(pen=pg.mkPen("#00cc66", width=1)) for _ in self.line_trace_alphas]
        # Compatibility alias for callers and tests that inspect the newest trace.
        self.line_trace = self.line_traces[-1]
        self.point_trace = pg.ScatterPlotItem(size=2.5, pen=None, brush=pg.mkBrush("#00cc66"))
        self.plot_widget.addItem(self.point_trace)

        self.img_item = pg.ImageItem()
        self.img_item.setImage(self.module.heatmap.T, autoLevels=False, levels=[0.0, 1.0])
        self.img_item.setRect(QRectF(-1.1, -1.1, 2.2, 2.2))
        self.img_item.setZValue(-1)
        self.plot_widget.addItem(self.img_item)
        display_layout.addWidget(self.plot_widget, stretch=1)

        self.corr_container = QWidget(self.display_widget)
        corr_layout = QVBoxLayout(self.corr_container)
        corr_layout.setContentsMargins(0, 0, 0, 0)
        self.corr_meter = CorrelationMeter(self.corr_container)
        corr_layout.addWidget(self.corr_meter)
        display_layout.addWidget(self.corr_container)

        layout.addWidget(self.display_widget, stretch=3)

        self.controls_group = QGroupBox(tr("Controls"), self)
        controls_layout = QVBoxLayout(self.controls_group)
        self.controls_tabs = QTabWidget(self.controls_group)
        self.controls_tabs.addTab(self._create_basic_tab(), tr("Basic"))
        self.controls_tabs.addTab(self._create_appearance_tab(), tr("Appearance"))
        controls_layout.addWidget(self.controls_tabs)
        layout.addWidget(self.controls_group, stretch=1)

        self.app = QApplication.instance()
        if self.app is not None and hasattr(self.app, "theme_manager"):
            self.app.theme_manager.theme_changed.connect(self.apply_theme)
            self.apply_theme(self.app.theme_manager.get_current_theme())

    def _create_basic_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        self.toggle_btn = QPushButton(tr("Start Measurement"), tab)
        self.toggle_btn.setCheckable(True)
        self.toggle_btn.setMinimumHeight(48)
        toggle_font = self.toggle_btn.font()
        toggle_font.setBold(True)
        toggle_font.setPointSize(toggle_font.pointSize() + 1)
        self.toggle_btn.setFont(toggle_font)
        self.toggle_btn.setStyleSheet(STYLE_TOGGLE_BTN_LIGHT)
        self.toggle_btn.clicked.connect(self.on_toggle)
        layout.addWidget(self.toggle_btn)

        secondary_actions = QHBoxLayout()
        secondary_actions.setContentsMargins(0, 0, 0, 0)

        self.hold_btn = QPushButton(tr("Hold Display"), tab)
        self.hold_btn.setCheckable(True)
        self.hold_btn.setMinimumHeight(36)
        self.hold_btn.toggled.connect(self.on_hold_changed)
        secondary_actions.addWidget(self.hold_btn)

        self.clear_btn = QPushButton(tr("Clear"), tab)
        self.clear_btn.setMinimumHeight(36)
        self.clear_btn.clicked.connect(self.on_clear)
        secondary_actions.addWidget(self.clear_btn)
        layout.addLayout(secondary_actions)

        layout.addWidget(QLabel(tr("Mapping:")))
        self.mapping_combo = QComboBox()
        self.mapping_combo.addItem(tr("Mid/Side (M/S)"), "ms")
        self.mapping_combo.addItem(tr("Left/Right (L/R)"), "lr")
        self.mapping_combo.setCurrentIndex(0 if self.module.mapping_mode == "ms" else 1)
        self.mapping_combo.currentIndexChanged.connect(self.on_mapping_changed)
        layout.addWidget(self.mapping_combo)

        layout.addWidget(QLabel(tr("Gain:")))
        self.gain_slider = QSlider(Qt.Orientation.Horizontal)
        self.gain_slider.setRange(1, 100)
        self.gain_slider.setValue(int(round(self.module.manual_gain * 10.0)))
        self.gain_slider.valueChanged.connect(self.on_gain_changed)
        layout.addWidget(self.gain_slider)

        self.gain_label = QLabel(f"{self.module.manual_gain:.1f}x")
        self.gain_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self.gain_label)

        self.auto_gain_chk = QCheckBox(tr("Auto Gain"))
        self.auto_gain_chk.setChecked(self.module.auto_gain)
        self.auto_gain_chk.toggled.connect(self.on_auto_gain_changed)
        layout.addWidget(self.auto_gain_chk)

        self.effective_gain_label = QLabel(tr("Effective Gain: {0:.2f}x").format(self.module.effective_gain))
        self.effective_gain_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self.effective_gain_label)

        layout.addWidget(QLabel(tr("Correlation Response:")))
        self.response_slider = QSlider(Qt.Orientation.Horizontal)
        self.response_slider.setRange(50, 2000)
        self.response_slider.setValue(int(round(self.module.correlation_response_seconds * 1000.0)))
        self.response_slider.valueChanged.connect(self.on_response_changed)
        layout.addWidget(self.response_slider)
        self.response_label = QLabel(f"{self.module.correlation_response_seconds * 1000.0:.0f} ms")
        self.response_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self.response_label)

        layout.addStretch()
        return tab

    def _create_appearance_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        layout.addWidget(QLabel(tr("Trace Mode:")))
        self.trace_combo = QComboBox()
        self.trace_combo.addItem(tr("Points"), "Points")
        self.trace_combo.addItem(tr("Lines"), "Lines")
        self.trace_combo.addItem(tr("Density"), "Density")
        trace_index = self.trace_combo.findData(self.module.trace_mode)
        self.trace_combo.setCurrentIndex(trace_index if trace_index >= 0 else 1)
        self.trace_combo.currentIndexChanged.connect(self.on_trace_mode_changed)
        layout.addWidget(self.trace_combo)

        layout.addWidget(QLabel(tr("Color Palette:")))
        self.palette_combo = QComboBox()
        self.palette_combo.addItem(tr("Green"), "Green")
        self.palette_combo.addItem(tr("Fire"), "Fire")
        self.palette_combo.addItem(tr("Ice"), "Ice")
        self.palette_combo.addItem(tr("Viridis"), "Viridis")
        palette_index = self.palette_combo.findData(self.module.color_palette)
        self.palette_combo.setCurrentIndex(palette_index if palette_index >= 0 else 0)
        self.palette_combo.currentIndexChanged.connect(self.on_palette_changed)
        layout.addWidget(self.palette_combo)

        layout.addWidget(QLabel(tr("Persistence:")))
        self.persistence_slider = QSlider(Qt.Orientation.Horizontal)
        self.persistence_slider.setRange(0, 100)
        self.persistence_slider.setValue(self._seconds_to_persistence_slider(self.module.persistence_seconds))
        self.persistence_slider.valueChanged.connect(self.on_persistence_changed)
        layout.addWidget(self.persistence_slider)
        self.persistence_label = QLabel(f"{self.module.persistence_seconds:.2f} s")
        self.persistence_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self.persistence_label)

        layout.addWidget(QLabel(tr("Glow:")))
        self.glow_slider = QSlider(Qt.Orientation.Horizontal)
        self.glow_slider.setRange(0, 50)
        self.glow_slider.setValue(int(round(self.module.glow_amount * 10.0)))
        self.glow_slider.valueChanged.connect(self.on_glow_changed)
        layout.addWidget(self.glow_slider)
        self.glow_label = QLabel(f"{self.module.glow_amount:.1f}")
        self.glow_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self.glow_label)

        self.invert_x_chk = QCheckBox(tr("Invert X"))
        self.invert_x_chk.setChecked(self.module.invert_x)
        self.invert_x_chk.toggled.connect(self.on_invert_x_changed)
        layout.addWidget(self.invert_x_chk)

        self.invert_y_chk = QCheckBox(tr("Invert Y"))
        self.invert_y_chk.setChecked(self.module.invert_y)
        self.invert_y_chk.toggled.connect(self.on_invert_y_changed)
        layout.addWidget(self.invert_y_chk)

        self.direction_guides_chk = QCheckBox(tr("Show Direction Guides"))
        self.direction_guides_chk.setChecked(self.module.show_direction_guides)
        self.direction_guides_chk.toggled.connect(self.on_direction_guides_changed)
        layout.addWidget(self.direction_guides_chk)

        self.axes_chk = QCheckBox(tr("Show Axes"))
        self.axes_chk.setChecked(self.module.show_axes)
        self.axes_chk.toggled.connect(self.on_axes_changed)
        layout.addWidget(self.axes_chk)

        self.grid_chk = QCheckBox(tr("Show Grid"))
        self.grid_chk.setChecked(self.module.show_grid)
        self.grid_chk.toggled.connect(self.on_grid_changed)
        layout.addWidget(self.grid_chk)

        layout.addStretch()
        return tab

    @staticmethod
    def _persistence_slider_to_seconds(value: int) -> float:
        return 0.05 * (100.0 ** (min(max(value, 0), 100) / 100.0))

    @staticmethod
    def _seconds_to_persistence_slider(seconds: float) -> int:
        bounded = min(max(float(seconds), 0.05), 5.0)
        return int(round(100.0 * math.log(bounded / 0.05, 100.0)))

    def _clear_direction_labels(self) -> None:
        for label in self._direction_labels:
            self.plot_widget.removeItem(label)
        self._direction_labels.clear()

    def _add_direction_label(self, text: str, x: float, y: float, anchor: tuple[float, float]) -> None:
        label = pg.TextItem(text=text, color="#bbbbbb", anchor=anchor)
        label.setPos(x, y)
        self.plot_widget.addItem(label)
        self._direction_labels.append(label)

    def _reset_density(self) -> None:
        self.module.heatmap.fill(0.0)
        self.img_item.setImage(self.module.heatmap.T, autoLevels=False, levels=[0.0, 1.0])

    def on_mapping_changed(self, _index: int) -> None:
        mode = self.mapping_combo.currentData()
        self.module.mapping_mode = mode if mode in ("ms", "lr") else "ms"
        self._reset_density()
        self._update_reference_lines()

    def on_invert_x_changed(self, checked: bool) -> None:
        self.module.invert_x = bool(checked)
        self._reset_density()
        self._update_reference_lines()

    def on_invert_y_changed(self, checked: bool) -> None:
        self.module.invert_y = bool(checked)
        self._reset_density()
        self._update_reference_lines()

    def on_direction_guides_changed(self, checked: bool) -> None:
        self.module.show_direction_guides = bool(checked)
        self._update_reference_lines()

    def on_axes_changed(self, checked: bool) -> None:
        self.module.show_axes = bool(checked)
        self._update_axis_display()

    def on_grid_changed(self, checked: bool) -> None:
        self.module.show_grid = bool(checked)
        self._update_grid_display()

    def _update_axis_display(self) -> None:
        show_axes = self.module.show_axes
        plot_item = self.plot_widget.getPlotItem()
        bottom_axis = plot_item.getAxis("bottom")
        left_axis = plot_item.getAxis("left")
        foreground = pg.getConfigOption("foreground")

        for axis in (bottom_axis, left_axis):
            axis.setLabel("")
            axis.setStyle(showValues=show_axes)
            axis.setPen(foreground if show_axes else None)
            axis.setTickPen(foreground)

        bottom_axis.setHeight(None if show_axes else 0)
        left_axis.setWidth(None if show_axes else 0)

    def _update_grid_display(self) -> None:
        enabled = self.module.show_grid
        self.plot_widget.showGrid(x=enabled, y=enabled, alpha=0.25)

    def _update_reference_lines(self) -> None:
        self._clear_direction_labels()
        if self.module.mapping_mode == "lr":
            sx = -1 if self.module.invert_x else 1
            sy = -1 if self.module.invert_y else 1
            self.ref_line_a.setAngle(45 if sy == sx else -45)
            self.ref_line_b.setAngle(-45 if sy == sx else 45)
            if self.module.show_direction_guides:
                self._add_direction_label(tr("Mono"), 0.78 * sx, 0.78 * sy, (0.5, 0.5))
                self._add_direction_label(tr("Anti-phase"), -0.78 * sx, 0.78 * sy, (0.5, 0.5))
        else:
            self.ref_line_a.setAngle(90)
            self.ref_line_b.setAngle(0)
            y_sign = -1.0 if self.module.invert_y else 1.0
            x_sign = -1.0 if self.module.invert_x else 1.0
            if self.module.show_direction_guides:
                self._add_direction_label(tr("Mono"), 0.0, 1.02 * y_sign, (0.5, 0.5))
                self._add_direction_label(tr("Anti-phase"), 0.92 * x_sign, 0.0, (0.5, 0.5))
                self._add_direction_label(tr("Left"), -0.72 * x_sign, 0.72 * y_sign, (0.5, 0.5))
                self._add_direction_label(tr("Right"), 0.72 * x_sign, 0.72 * y_sign, (0.5, 0.5))

        self._update_axis_display()
        self._update_grid_display()

    def _compute_xy(self, left: np.ndarray, right: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        if self.module.mapping_mode == "lr":
            x = left
            y = right
        else:
            x = (right - left) * 0.5
            y = (left + right) * 0.5

        if self.module.invert_x:
            x = -x
        if self.module.invert_y:
            y = -y
        return x, y

    def on_toggle(self, checked: bool) -> None:
        if checked:
            self._clear_display_state()
            if self.module.start_analysis():
                self.timer.start()
                self.toggle_btn.setText(tr("Stop Measurement"))
            else:
                self.toggle_btn.blockSignals(True)
                self.toggle_btn.setChecked(False)
                self.toggle_btn.blockSignals(False)
                self.toggle_btn.setText(tr("Start Measurement"))
                self.timer.stop()
        else:
            self.module.stop_analysis()
            self.timer.stop()
            self.toggle_btn.setText(tr("Start Measurement"))
        self._update_status(self.module.get_snapshot(self._last_consumed_total))

    def on_hold_changed(self, checked: bool) -> None:
        self._display_held = bool(checked)
        self.hold_btn.setText(tr("Resume Display") if checked else tr("Hold Display"))
        self._update_status(self.module.get_snapshot(self._last_consumed_total))

    def on_clear(self) -> None:
        self.module.clear_measurement()
        self._clear_display_state()
        self._update_status(self.module.get_snapshot())

    def _clear_display_state(self) -> None:
        self._recent_valid.clear()
        self._last_consumed_total = 0
        self._last_display_time = time.monotonic()
        for trace in self.line_traces:
            trace.setData([], [])
        self.point_trace.setData([], [])
        self.corr_meter.set_reading(None, None, None, tr("Waiting for audio"))
        self._reset_density()

    def on_gain_changed(self, value: int) -> None:
        self.module.manual_gain = value / 10.0
        if not self.module.auto_gain:
            self.module.effective_gain = self.module.manual_gain
        self.gain_label.setText(f"{self.module.manual_gain:.1f}x")

    def on_auto_gain_changed(self, checked: bool) -> None:
        self.module.auto_gain = bool(checked)
        if not checked:
            self.module.effective_gain = self.module.manual_gain
        self._update_control_states()

    def on_response_changed(self, value: int) -> None:
        self.module.correlation_response_seconds = value / 1000.0
        self.response_label.setText(f"{value} ms")

    def on_trace_mode_changed(self, _index: int) -> None:
        mode = self.trace_combo.currentData()
        self.module.trace_mode = mode if mode in ("Points", "Lines", "Density") else "Lines"
        self._reset_density()
        self._update_control_states()

    def on_palette_changed(self, _index: int) -> None:
        palette = self.palette_combo.currentData()
        self.module.color_palette = palette if palette in ("Green", "Fire", "Ice", "Viridis") else "Green"
        self.update_palette()

    def on_persistence_changed(self, value: int) -> None:
        seconds = self._persistence_slider_to_seconds(value)
        self.module.persistence_seconds = seconds
        self.persistence_label.setText(f"{seconds:.2f} s")

    def on_glow_changed(self, value: int) -> None:
        self.module.glow_amount = value / 10.0
        self.glow_label.setText(f"{self.module.glow_amount:.1f}")

    def _update_control_states(self) -> None:
        self.gain_slider.setEnabled(not self.module.auto_gain)
        density = self.module.trace_mode == "Density"
        lines = self.module.trace_mode == "Lines"
        self.persistence_slider.setEnabled(density)
        self.glow_slider.setEnabled(density)
        for trace in self.line_traces:
            trace.setVisible(lines)
        self.point_trace.setVisible(self.module.trace_mode == "Points")
        self.img_item.setVisible(density)

    @staticmethod
    def _interpolated_colormap(stops: list[tuple[float, tuple[int, int, int]]]) -> np.ndarray:
        positions = np.linspace(0.0, 1.0, 256)
        stop_positions = np.array([stop[0] for stop in stops], dtype=np.float64)
        stop_colors = np.array([stop[1] for stop in stops], dtype=np.float64)
        colors = np.zeros((256, 4), dtype=np.ubyte)
        for channel in range(3):
            colors[:, channel] = np.interp(positions, stop_positions, stop_colors[:, channel]).astype(np.ubyte)
        colors[:, 3] = 255
        return colors

    def update_palette(self) -> None:
        palettes = {
            "Green": [(0.0, (0, 0, 0)), (0.75, (0, 210, 90)), (1.0, (255, 255, 255))],
            "Fire": [(0.0, (0, 0, 0)), (0.4, (180, 25, 0)), (0.8, (255, 210, 0)), (1.0, (255, 255, 255))],
            "Ice": [(0.0, (0, 0, 0)), (0.55, (0, 90, 210)), (0.85, (0, 230, 255)), (1.0, (255, 255, 255))],
            "Viridis": [(0.0, (68, 1, 84)), (0.33, (49, 104, 142)), (0.66, (53, 183, 121)), (1.0, (253, 231, 37))],
        }
        colors = self._interpolated_colormap(palettes[self.module.color_palette])
        self.img_item.setLookupTable(colors)

        trace_colors = {
            "Green": "#00a85a",
            "Fire": "#e64a19",
            "Ice": "#0088cc",
            "Viridis": "#2a9d8f",
        }
        color = trace_colors[self.module.color_palette]
        for trace, alpha in zip(self.line_traces, self.line_trace_alphas, strict=True):
            trace_color = QColor(color)
            trace_color.setAlpha(alpha)
            width = 1.2 if alpha == 255 else 1.0
            trace.setPen(pg.mkPen(trace_color, width=width))
        self.point_trace.setBrush(pg.mkBrush(color))

    def _update_auto_gain(self, x: np.ndarray, y: np.ndarray, elapsed: float) -> float:
        if not self.module.auto_gain:
            self.module.effective_gain = self.module.manual_gain
            return self.module.effective_gain

        if len(x) == 0:
            return self.module.effective_gain
        peak = max(float(np.max(np.abs(x))), float(np.max(np.abs(y))))
        if not math.isfinite(peak) or peak <= 1e-12:
            return self.module.effective_gain

        target = min(10.0, max(0.1, 0.9 / peak))
        current = max(self.module.effective_gain, 0.1)
        if target < current:
            current = target
        elif target > current * 1.05:
            alpha = 1.0 - math.exp(-max(elapsed, 0.0) / 1.5)
            current += alpha * (target - current)
        self.module.effective_gain = min(max(current, 0.1), 10.0)
        return self.module.effective_gain

    def _validity_text(self, validity: CorrelationValidity) -> str:
        return {
            CorrelationValidity.VALID: "",
            CorrelationValidity.WAITING: tr("Waiting for audio"),
            CorrelationValidity.NO_SIGNAL: tr("No signal"),
            CorrelationValidity.ONE_CHANNEL_LOW: tr("One channel below threshold"),
            CorrelationValidity.MONO_INPUT: tr("Mono input — stereo correlation unavailable"),
            CorrelationValidity.NONFINITE: tr("Non-finite input — result invalid"),
            CorrelationValidity.CLIPPED: tr("Input clipping — result invalid"),
            CorrelationValidity.IO_ERROR: tr("Audio I/O error — result invalid"),
        }[validity]

    def _quality_text(self, flags: GoniometerQualityFlag) -> str:
        messages: list[str] = []
        clipped_channels: list[str] = []
        if flags & GoniometerQualityFlag.CLIPPED_LEFT:
            clipped_channels.append("L")
        if flags & GoniometerQualityFlag.CLIPPED_RIGHT:
            clipped_channels.append("R")
        if clipped_channels:
            messages.append(tr("Clipping latched: {0}").format("/".join(clipped_channels)))
        if flags & GoniometerQualityFlag.IO_ERROR:
            messages.append(tr("Audio I/O error latched"))
        if flags & GoniometerQualityFlag.NONFINITE:
            messages.append(tr("Non-finite input latched"))
        return " · ".join(messages)

    def _update_status(self, snapshot: GoniometerSnapshot | None) -> None:
        if self.module.run_state is GoniometerRunState.FAILED:
            detail = self.module.error_message or tr("Unknown error")
            self.status_label.setText(tr("Failed: {0}").format(detail))
            return
        if self._display_held and self.module.is_running:
            self.status_label.setText(tr("Held — acquisition running"))
            return
        if not self.module.is_running:
            if snapshot is not None and snapshot.total_samples > 0:
                self.status_label.setText(tr("Stopped — last value"))
            else:
                self.status_label.setText(tr("Idle"))
            return
        if snapshot is None or snapshot.total_samples == 0:
            self.status_label.setText(tr("Waiting for audio"))
            return

        messages: list[str] = []
        validity_text = self._validity_text(snapshot.correlation_validity)
        if validity_text:
            messages.append(validity_text)
        quality_text = self._quality_text(snapshot.quality_flags)
        if quality_text:
            messages.append(quality_text)
        if snapshot.display_dropped_samples:
            messages.append(tr("Display skipped {0} samples").format(snapshot.display_dropped_samples))
        self.status_label.setText(" · ".join(messages) if messages else tr("Running"))

    def _update_recent_extrema(self, now: float, correlation: float | None) -> tuple[float | None, float | None]:
        if correlation is not None:
            self._recent_valid.append((now, correlation))
        while self._recent_valid and now - self._recent_valid[0][0] > self.min_max_hold_seconds:
            self._recent_valid.popleft()

        if not self._recent_valid:
            return None, None
        values = [item[1] for item in self._recent_valid]
        return min(values), max(values)

    def _stable_period(self, signal: np.ndarray) -> tuple[np.ndarray, float] | None:
        if len(signal) < 3:
            return None

        reference = signal - float(np.mean(signal))
        if float(np.max(reference) - np.min(reference)) <= 1e-9:
            return None

        crossings = np.flatnonzero((reference[:-1] <= 0.0) & (reference[1:] > 0.0)) + 1
        if len(crossings) < 2:
            return None

        periods = np.diff(crossings)
        stability_window = self.line_trace_ratio_max_denominator + 3
        recent_periods = periods[-min(len(periods), stability_window) :]
        median_period = float(np.median(recent_periods))
        if median_period < 3.0:
            return None
        if len(recent_periods) >= 3:
            relative_error = np.max(np.abs(recent_periods - median_period)) / median_period
            if relative_error > self.line_trace_period_tolerance:
                return None
        return crossings, median_period

    def _ranges_from_crossings(self, crossings: np.ndarray, cycles_per_gate: int) -> list[tuple[int, int]]:
        available_gates = (len(crossings) - 1) // cycles_per_gate
        gate_count = min(self.line_cycle_count, available_gates)
        if gate_count <= 0:
            return []

        final_crossing = len(crossings) - 1
        first_crossing = final_crossing - gate_count * cycles_per_gate
        boundary_indices = range(first_crossing, final_crossing + 1, cycles_per_gate)
        boundaries = crossings[list(boundary_indices)]
        return [(int(start), int(stop) + 1) for start, stop in zip(boundaries[:-1], boundaries[1:], strict=True)]

    def _periodic_trace_ranges(self, left: np.ndarray, right: np.ndarray) -> list[tuple[int, int]]:
        """Return gates that cover the short common period of both inputs."""
        left_period = self._stable_period(left)
        right_period = self._stable_period(right)
        if left_period is None and right_period is None:
            return []

        cycles_per_gate = 1
        if left_period is None:
            crossings, _period = right_period
        elif right_period is None:
            crossings, _period = left_period
        else:
            left_crossings, left_samples = left_period
            right_crossings, right_samples = right_period
            if left_samples >= right_samples:
                crossings = left_crossings
                slower_period = left_samples
                faster_period = right_samples
            else:
                crossings = right_crossings
                slower_period = right_samples
                faster_period = left_samples

            frequency_ratio = slower_period / faster_period
            approximate_ratio = Fraction(frequency_ratio).limit_denominator(self.line_trace_ratio_max_denominator)
            ratio_error = abs(float(approximate_ratio) - frequency_ratio) / frequency_ratio
            if ratio_error <= self.line_trace_ratio_tolerance:
                cycles_per_gate = approximate_ratio.denominator

        ranges = self._ranges_from_crossings(crossings, cycles_per_gate)
        if ranges or cycles_per_gate == 1:
            return ranges
        return self._ranges_from_crossings(crossings, 1)

    def _limit_gate_points(self, x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        if len(x) <= self.line_trace_max_points_per_gate:
            return x, y
        indices = np.linspace(
            0,
            len(x) - 1,
            self.line_trace_max_points_per_gate,
            dtype=np.intp,
        )
        return x[indices], y[indices]

    def _fallback_line_segments(self, x: np.ndarray, y: np.ndarray) -> list[tuple[np.ndarray, np.ndarray]]:
        sample_count = min(len(x), self.line_trace_fallback_samples)
        if sample_count == 0:
            return []

        start = len(x) - sample_count
        segment_count = min(len(self.line_traces), sample_count)
        edges = np.linspace(start, len(x), segment_count + 1, dtype=np.intp)
        segments: list[tuple[np.ndarray, np.ndarray]] = []
        for index in range(segment_count):
            segment_start = int(edges[index])
            if index > 0:
                segment_start -= 1
            segment_stop = int(edges[index + 1])
            segments.append((x[segment_start:segment_stop], y[segment_start:segment_stop]))
        return segments

    def _line_segments(
        self,
        left: np.ndarray,
        right: np.ndarray,
        x: np.ndarray,
        y: np.ndarray,
    ) -> list[tuple[np.ndarray, np.ndarray]]:
        ranges = self._periodic_trace_ranges(left, right)
        if not ranges:
            return self._fallback_line_segments(x, y)
        return [self._limit_gate_points(x[start:stop], y[start:stop]) for start, stop in ranges]

    def _update_line_trail(
        self,
        left: np.ndarray,
        right: np.ndarray,
        x: np.ndarray,
        y: np.ndarray,
    ) -> None:
        segments = self._line_segments(left, right, x, y)
        if len(segments) > len(self.line_traces):
            older_x = np.concatenate([segment_x for segment_x, _segment_y in segments[:-1]])
            older_y = np.concatenate([segment_y for _segment_x, segment_y in segments[:-1]])
            segments = [(older_x, older_y), segments[-1]]

        padding = len(self.line_traces) - len(segments)
        padded_segments: list[tuple[np.ndarray, np.ndarray] | None] = [None] * padding + segments
        for trace, segment in zip(self.line_traces, padded_segments, strict=True):
            if segment is None:
                trace.setData([], [])
            else:
                segment_x, segment_y = segment
                trace.setData(segment_x, segment_y, skipFiniteCheck=True)

    def _update_density(self, x: np.ndarray, y: np.ndarray, elapsed: float) -> None:
        decay = math.exp(-max(elapsed, 0.0) / max(self.module.persistence_seconds, 0.05))
        self.module.heatmap *= decay
        if len(x):
            histogram, _, _ = np.histogram2d(
                x,
                y,
                bins=self.module.heatmap_size,
                range=[[-1.1, 1.1], [-1.1, 1.1]],
            )
            self.module.heatmap += histogram

        display_data = np.log1p(self.module.heatmap.T)
        if self.module.glow_amount > 0.0:
            display_data = gaussian_filter(display_data, sigma=self.module.glow_amount)
        positive = display_data[display_data > 0.0]
        upper = max(1.0, float(np.percentile(positive, 99.5))) if positive.size else 1.0
        self.img_item.setImage(display_data, autoLevels=False, levels=[0.0, upper])

    def update_display(self) -> None:
        if not self.module.is_running:
            return

        snapshot = self.module.get_snapshot(self._last_consumed_total)
        if snapshot is None:
            return

        if self._display_held:
            self._last_consumed_total = snapshot.total_samples
            self._update_status(snapshot)
            return

        now = time.monotonic()
        elapsed = now - self._last_display_time
        self._last_display_time = now

        audio = snapshot.audio
        display_out_of_range = False
        if len(audio):
            base_x, base_y = self._compute_xy(audio[:, 0], audio[:, 1])
            gain = self._update_auto_gain(base_x, base_y, elapsed)
            x = base_x * gain
            y = base_y * gain
            display_out_of_range = bool(np.any((np.abs(x) > 1.1) | (np.abs(y) > 1.1)))

            if self.module.trace_mode == "Lines":
                self._update_line_trail(audio[:, 0], audio[:, 1], x, y)
            elif self.module.trace_mode == "Points":
                self.point_trace.setData(x=x, y=y)
            else:
                new_audio = audio[snapshot.new_sample_offset :]
                new_x, new_y = self._compute_xy(new_audio[:, 0], new_audio[:, 1])
                self._update_density(new_x * gain, new_y * gain, elapsed)

            self.effective_gain_label.setText(tr("Effective Gain: {0:.2f}x").format(gain))

        self._last_consumed_total = snapshot.total_samples
        minimum, maximum = self._update_recent_extrema(now, snapshot.correlation)
        invalid_reason = self._validity_text(snapshot.correlation_validity)
        self.corr_meter.set_reading(snapshot.correlation, minimum, maximum, invalid_reason)
        self._update_status(snapshot)
        if display_out_of_range:
            current = self.status_label.text()
            warning = tr("Display out of range")
            self.status_label.setText(f"{current} · {warning}" if current else warning)

    def apply_theme(self, theme_name: str) -> None:
        if theme_name == "system" and self.app is not None and hasattr(self.app, "theme_manager"):
            theme_name = self.app.theme_manager.get_effective_theme()
        background = "#111111" if theme_name == "dark" else "#fafafa"
        self.plot_widget.setBackground(background)
        self.toggle_btn.setStyleSheet(STYLE_TOGGLE_BTN_DARK if theme_name == "dark" else STYLE_TOGGLE_BTN_LIGHT)
        label_color = "#bbbbbb" if theme_name == "dark" else "#444444"
        for label in self._direction_labels:
            label.setColor(label_color)
        self.update_palette()

    def get_display_widget(self) -> QWidget:
        return self.display_widget

    def get_control_widget(self) -> QWidget:
        return self.controls_group

    def restore_split_panels(self) -> None:
        layout = self.layout()
        if layout is None:
            return
        layout.addWidget(self.display_widget, stretch=3)
        layout.addWidget(self.controls_group, stretch=1)
        self.display_widget.show()
        self.controls_group.show()
        self.update_compact_layout()

    def update_compact_layout(self) -> None:
        compact = self.is_compact_mode()
        layout = self.layout()
        if layout is not None:
            if compact:
                if not hasattr(self, "_normal_layout_margins"):
                    self._normal_layout_margins = layout.contentsMargins()
                    self._normal_layout_spacing = layout.spacing()
                layout.setContentsMargins(0, 0, 0, 0)
                layout.setSpacing(0)
            elif hasattr(self, "_normal_layout_margins"):
                margins = self._normal_layout_margins
                layout.setContentsMargins(margins.left(), margins.top(), margins.right(), margins.bottom())
                layout.setSpacing(self._normal_layout_spacing)

        if hasattr(self, "status_container"):
            self.status_container.setHidden(compact)
        if hasattr(self, "corr_container"):
            self.corr_container.setHidden(compact)
        if hasattr(self, "controls_group"):
            is_split = self.controls_group.parent() is not self
            if not is_split:
                self.controls_group.setHidden(compact)

    def closeEvent(self, event: QCloseEvent) -> None:
        self.timer.stop()
        self.module.stop_analysis()
        super().closeEvent(event)
