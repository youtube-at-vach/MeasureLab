"""Continuous threshold-event counter and statistics widget."""

from __future__ import annotations

import csv
import json
import logging
import math
import uuid
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from src.core.audio_engine import AudioEngine
from src.core.event_detector import (
    DetectorConfig,
    DetectorSnapshot,
    DetectorState,
    EventDetectorCore,
    EventCompletion,
    EventPolarity,
    EventRecord,
)
from src.core.event_statistics import (
    EventMetric,
    MetricSummary,
    build_histogram,
    build_rate_trend,
    summarize_events,
)
from src.core.localization import tr
from src.gui.styles import MONOSPACE_FONT_FAMILY
from src.gui.widgets.compactable_interface import CompactableWidgetInterface
from src.gui.widgets.splittable_interface import SplittableWidgetInterface
from src.measurement_modules.base import MeasurementModule

logger = logging.getLogger(__name__)


class EventDetector(MeasurementModule):
    """AudioEngine adapter for the sample-accurate event detector core."""

    THRESHOLD_UNITS = ("FS", "mV", "V")

    def __init__(self, audio_engine: AudioEngine):
        self.audio_engine = audio_engine
        self.is_running = False
        self.callback_id = None
        self.widget: EventDetectorWidget | None = None

        self.input_channel = 0
        self.threshold = 0.01
        self.threshold_unit = "FS"
        self.polarity = EventPolarity.BOTH
        self.hysteresis = 0.001
        self.holdoff_ms = 10.0
        self.target_duration: float | None = None

        self._core = EventDetectorCore(self._build_config())
        self._run_metadata: dict[str, object] | None = None
        self._run_stopped_at_utc: str | None = None
        self._run_stop_reason: str | None = None
        self._target_samples: int | None = None

    @property
    def name(self) -> str:
        return "Event Detector"

    @property
    def description(self) -> str:
        return "Counts and measures rare threshold-crossing events."

    def get_widget(self):
        if self.widget is None:
            self.widget = EventDetectorWidget(self)
        return self.widget

    def _build_config(self) -> DetectorConfig:
        return DetectorConfig(
            sample_rate=float(self.audio_engine.sample_rate),
            threshold=float(self.threshold),
            polarity=EventPolarity(self.polarity),
            hysteresis=float(self.hysteresis),
            holdoff_seconds=float(self.holdoff_ms) / 1000.0,
        )

    def set_target_duration(self, duration: float | None) -> None:
        """Set the duration for the next run, or ``None`` for continuous measurement."""
        if duration is None:
            self.target_duration = None
            return

        value = float(duration)
        if not math.isfinite(value) or value <= 0:
            raise ValueError("target duration must be a positive finite number of seconds")
        self.target_duration = value

    @staticmethod
    def _duration_to_samples(duration: float | None, sample_rate: float) -> int | None:
        if duration is None:
            return None
        return max(1, int(round(duration * sample_rate)))

    def start_analysis(self) -> None:
        if self.is_running:
            return

        config = self._build_config()
        self._core.start(config)
        self._target_samples = self._duration_to_samples(self.target_duration, config.sample_rate)
        self._capture_run_metadata(config)
        self.is_running = True

        try:
            self.callback_id = self.audio_engine.register_callback(self._audio_callback)
        except Exception:
            self.callback_id = None
            self.is_running = False
            self._core.stop()
            self._run_metadata = None
            self._run_stopped_at_utc = None
            self._run_stop_reason = None
            self._target_samples = None
            raise

    def stop_analysis(self) -> None:
        if not self.is_running and self.callback_id is None:
            return

        self.is_running = False
        callback_id = self.callback_id
        self.callback_id = None

        try:
            if callback_id is not None:
                self.audio_engine.unregister_callback(callback_id)
        finally:
            self._core.stop()
            if self._run_stopped_at_utc is None:
                self._run_stopped_at_utc = self._utc_now()
            if self._run_stop_reason is None:
                self._run_stop_reason = "manual_stop"

    def _complete_target_duration(self) -> None:
        """Finish an exact sample-count run from the audio callback.

        Callback unregistration is left to ``stop_analysis`` on the GUI thread,
        so a final callback never attempts to stop the underlying audio stream.
        """
        self.is_running = False
        self._core.stop()
        self._run_stopped_at_utc = self._utc_now()
        self._run_stop_reason = "target_duration_reached"

    def reset_measurement(self) -> None:
        self._core.reset()
        if self.is_running:
            self._target_samples = self._duration_to_samples(self.target_duration, self._core.config.sample_rate)
            self._capture_run_metadata(self._core.config)
        else:
            self._run_metadata = None
            self._run_stopped_at_utc = None
            self._run_stop_reason = None

    def get_snapshot(self) -> DetectorSnapshot:
        return self._core.snapshot()

    def get_events(self):
        """Expose completed event records for future statistics/export views."""
        return self._core.get_events()

    def get_data_gap_samples(self) -> tuple[int, ...]:
        return self._core.get_data_gap_samples()

    def get_run_sample_rate(self) -> float:
        return float(self._core.config.sample_rate)

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="milliseconds")

    def get_input_calibration_state(self) -> tuple[bool, float]:
        """Return whether input volts are calibrated and the Vpeak/FS scale."""
        calibration = getattr(self.audio_engine, "calibration", None)
        calibrated_flag = getattr(calibration, "input_sensitivity_is_calibrated", None)
        if not isinstance(calibrated_flag, (bool, np.bool_)):
            calibrated_flag = getattr(calibration, "is_calibrated", False)
        is_calibrated = isinstance(calibrated_flag, (bool, np.bool_)) and bool(calibrated_flag)
        try:
            sensitivity = float(getattr(calibration, "input_sensitivity", 1.0))
        except (TypeError, ValueError):
            sensitivity = 1.0
            is_calibrated = False
        if not math.isfinite(sensitivity) or sensitivity <= 0:
            sensitivity = 1.0
            is_calibrated = False
        return is_calibrated, sensitivity

    def get_threshold_display_scale(self, unit: str, *, sensitivity: float | None = None) -> float:
        """Return the display-unit value corresponding to one peak FS."""
        if unit == "FS":
            return 1.0
        if unit not in self.THRESHOLD_UNITS:
            raise ValueError(f"Unsupported threshold unit: {unit!r}")

        is_calibrated, current_sensitivity = self.get_input_calibration_state()
        if sensitivity is None:
            if not is_calibrated:
                raise ValueError("Input calibration is required for voltage thresholds")
            sensitivity = current_sensitivity
        if not math.isfinite(float(sensitivity)) or float(sensitivity) <= 0:
            raise ValueError("Invalid input sensitivity")
        return float(sensitivity) * (1000.0 if unit == "mV" else 1.0)

    def threshold_to_display(self, value_fs: float, unit: str, *, sensitivity: float | None = None) -> float:
        """Convert a peak full-scale threshold to the selected display unit."""
        return float(value_fs) * self.get_threshold_display_scale(unit, sensitivity=sensitivity)

    def threshold_from_display(self, value: float, unit: str, *, sensitivity: float | None = None) -> float:
        """Convert a threshold display value to peak full-scale units."""
        return float(value) / self.get_threshold_display_scale(unit, sensitivity=sensitivity)

    def _capture_run_metadata(self, config: DetectorConfig) -> None:
        is_calibrated, sensitivity = self.get_input_calibration_state()
        threshold_unit = self.threshold_unit
        if threshold_unit not in self.THRESHOLD_UNITS or (threshold_unit != "FS" and not is_calibrated):
            threshold_unit = "FS"
        threshold_scale = self.get_threshold_display_scale(
            threshold_unit,
            sensitivity=sensitivity if threshold_unit != "FS" else None,
        )

        input_device = getattr(self.audio_engine, "input_device", None)
        if not isinstance(input_device, (str, int, float, bool)) and input_device is not None:
            input_device = str(input_device)

        self._run_metadata = {
            "schema_version": "1.0",
            "run_id": str(uuid.uuid4()),
            "started_at_utc": self._utc_now(),
            "sample_rate_hz": float(config.sample_rate),
            "input_channel_index": int(self.input_channel),
            "input_channel": f"CH{self.input_channel + 1}",
            "input_channel_mode": str(getattr(self.audio_engine, "input_channel_mode", "unknown")),
            "input_device_id": input_device,
            "threshold_fs_peak": float(config.threshold),
            "hysteresis_fs_peak": float(config.hysteresis),
            "release_level_fs_peak": float(config.threshold - config.hysteresis),
            "threshold_display_unit": threshold_unit,
            "threshold_display_value": float(config.threshold * threshold_scale),
            "hysteresis_display_value": float(config.hysteresis * threshold_scale),
            "release_level_display_value": float((config.threshold - config.hysteresis) * threshold_scale),
            "polarity": config.polarity.value,
            "holdoff_seconds": float(config.holdoff_seconds),
            "clip_level_fs_peak": float(config.clip_level),
            "target_duration_seconds": self.target_duration,
            "target_sample_count": self._target_samples,
            "input_calibrated": is_calibrated,
            "input_sensitivity_v_peak_per_fs": sensitivity if is_calibrated else None,
        }
        self._run_stopped_at_utc = None
        self._run_stop_reason = None

    def get_run_metadata(self) -> dict[str, object] | None:
        if self._run_metadata is None:
            return None
        metadata = dict(self._run_metadata)
        metadata["stopped_at_utc"] = self._run_stopped_at_utc
        metadata["stop_reason"] = self._run_stop_reason
        snapshot = self.get_snapshot()
        metadata.update(
            {
                "processed_samples": snapshot.processed_samples,
                "elapsed_seconds": snapshot.elapsed_seconds,
                "event_start_count": snapshot.event_count,
                "completed_event_count": snapshot.completed_event_count,
                "censored_event_count": snapshot.censored_event_count,
                "clipping_detected": snapshot.clipping_detected,
                "data_gap_detected": snapshot.data_gap_detected,
                "data_gap_count": snapshot.data_gap_count,
                "configuration_changed_detected": snapshot.configuration_changed_detected,
                "dropped_record_count": snapshot.dropped_record_count,
                "measurement_valid": snapshot.measurement_valid,
            }
        )
        return metadata

    def get_amplitude_display(self) -> tuple[float, str]:
        metadata = self._run_metadata
        if metadata is not None and bool(metadata.get("input_calibrated", False)):
            sensitivity = metadata.get("input_sensitivity_v_peak_per_fs")
            if isinstance(sensitivity, (int, float)) and math.isfinite(float(sensitivity)) and sensitivity > 0:
                return float(sensitivity), "Vpeak"
        return 1.0, "FS peak"

    @staticmethod
    def _event_to_dict(event: EventRecord, sample_rate: float, amplitude_scale: float) -> dict[str, object]:
        return {
            "sequence_number": event.sequence_number,
            "start_sample": event.start_sample,
            "end_sample": event.end_sample,
            "start_seconds": event.start_sample / sample_rate,
            "end_seconds": event.end_sample / sample_rate,
            "polarity": event.polarity.value,
            "trigger_polarity": (event.trigger_polarity or event.polarity).value,
            "peak_polarity": (event.peak_polarity or event.polarity).value,
            "peak_fs": event.peak,
            "peak_absolute_fs": abs(event.peak),
            "peak_display": event.peak * amplitude_scale,
            "peak_absolute_display": abs(event.peak) * amplitude_scale,
            "positive_peak_fs": event.positive_peak,
            "negative_peak_fs": event.negative_peak,
            "duration_seconds": event.duration_seconds,
            "interarrival_seconds": event.interval_seconds,
            "quiet_time_seconds": event.quiet_time_seconds,
            "completion": event.completion.value,
        }

    @staticmethod
    def _sanitize_csv_field(value: object) -> object:
        if not isinstance(value, str):
            return value
        sanitized = value.replace("\r", " ").replace("\n", " ")
        if sanitized.startswith(("=", "+", "-", "@", "\t")):
            return f"'{sanitized}"
        return sanitized

    def export_events(self, filepath: str) -> None:
        """Export the current run and all retained event records to CSV or JSON."""
        path = Path(filepath)
        metadata = self.get_run_metadata()
        if metadata is None:
            raise ValueError("No Event Detector run is available for export")
        events = self.get_events()
        sample_rate = float(metadata["sample_rate_hz"])
        amplitude_scale, amplitude_unit = self.get_amplitude_display()
        event_rows = [self._event_to_dict(event, sample_rate, amplitude_scale) for event in events]

        if path.suffix.lower() == ".json":
            payload = {
                "schema": "measurelab.event_detector",
                "schema_version": "1.0",
                "run": metadata,
                "amplitude_display_unit": amplitude_unit,
                "events": event_rows,
            }
            with path.open("w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, ensure_ascii=False, allow_nan=False)
            return
        if path.suffix.lower() != ".csv":
            raise ValueError("Event export path must end in .csv or .json")

        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["# MeasureLab Event Detector Export"])
            for key, value in metadata.items():
                writer.writerow([f"# {self._sanitize_csv_field(key)}", self._sanitize_csv_field(value)])
            writer.writerow(["# amplitude_display_unit", amplitude_unit])
            writer.writerow([])
            headers = (
                list(event_rows[0])
                if event_rows
                else list(
                    self._event_to_dict(
                        EventRecord(0, 0, 0, EventPolarity.POSITIVE, 0.0, 0.0, None), sample_rate, amplitude_scale
                    )
                )
            )
            writer.writerow(headers)
            writer.writerows([self._sanitize_csv_field(row[key]) for key in headers] for row in event_rows)

    def _audio_callback(self, indata, outdata, frames, time_info, status) -> None:
        del frames, time_info
        outdata.fill(0)
        if not self.is_running:
            return
        if float(self.audio_engine.sample_rate) != float(self._core.config.sample_rate):
            self._core.mark_configuration_change()
            return
        if indata is None:
            self._core.mark_data_gap()
            return

        data = np.asarray(indata)
        if data.size == 0:
            return
        if data.ndim == 1:
            if self.input_channel != 0:
                self._core.mark_configuration_change()
                return
            samples = data
        elif data.ndim == 2:
            if self.input_channel >= data.shape[1]:
                self._core.mark_configuration_change()
                return
            samples = data[:, self.input_channel]
        else:
            self._core.mark_data_gap()
            return

        input_status = bool(getattr(status, "input_overflow", False) or getattr(status, "input_underflow", False))
        if status and not any(
            hasattr(status, name)
            for name in ("input_overflow", "input_underflow", "output_overflow", "output_underflow")
        ):
            input_status = True
        target_samples = self._target_samples
        if target_samples is not None:
            remaining = target_samples - self._core.snapshot().processed_samples
            if remaining <= 0:
                self._complete_target_duration()
                return
            samples = samples[:remaining]

        self._core.process(samples, data_gap=input_status)

        if target_samples is not None and self._core.snapshot().processed_samples >= target_samples:
            self._complete_target_duration()


class EventDetectorWidget(QWidget, CompactableWidgetInterface, SplittableWidgetInterface):
    """Statistics-first UI without duplicating the Raw Time Series display."""

    RATE_VIEW_BLOCK_BINS = 10
    AMPLITUDE_DISPLAY_DECIMALS = 3

    def __init__(self, module: EventDetector):
        QWidget.__init__(self)
        CompactableWidgetInterface.__init__(self)
        SplittableWidgetInterface.__init__(self)
        self.module = module

        self._init_ui()
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self._update_results)
        self._update_results()

    def get_display_widget(self) -> QWidget:
        return self.display_widget

    def get_control_widget(self) -> QWidget:
        return self.control_widget

    def restore_split_panels(self) -> None:
        layout = self.layout()
        if layout is None:
            return
        layout.addWidget(self.display_widget, stretch=1)
        layout.addWidget(self.control_widget)
        self.display_widget.show()
        self.control_widget.show()

    def _init_ui(self) -> None:
        root = QHBoxLayout(self)

        self.display_widget = QWidget()
        display = QVBoxLayout(self.display_widget)
        display.setContentsMargins(8, 8, 8, 8)
        display.setSpacing(8)

        status_row = QHBoxLayout()
        status_row.setSpacing(8)
        self.lbl_state = QLabel(tr("STOPPED"))
        self.lbl_state.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_state.setMinimumWidth(160)
        status_row.addWidget(self.lbl_state)
        status_row.addStretch(1)

        self.lbl_conditions = QLabel()
        self.lbl_conditions.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.lbl_conditions.setStyleSheet("padding: 6px 2px;")
        status_row.addWidget(self.lbl_conditions)
        display.addLayout(status_row)

        self.tabs = QTabWidget()

        summary_tab = QWidget()
        summary_layout = QVBoxLayout(summary_tab)
        summary_layout.setContentsMargins(6, 6, 6, 6)
        result_grid = QGridLayout()
        result_grid.setSpacing(8)
        result_grid.setColumnStretch(0, 1)
        result_grid.setColumnStretch(1, 1)
        result_grid.setRowStretch(0, 3)
        result_grid.setRowStretch(1, 1)

        self.count_group = QGroupBox(tr("Event Count"))
        self.count_group.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        count_layout = QVBoxLayout(self.count_group)
        self.lbl_count = QLabel("0")
        self.lbl_count.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_count.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.lbl_count.setStyleSheet("font-size: 42px; font-weight: bold;")
        count_layout.addWidget(self.lbl_count)
        result_grid.addWidget(self.count_group, 0, 0)

        self.rate_group = QGroupBox(tr("Event Rate"))
        self.rate_group.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        rate_layout = QVBoxLayout(self.rate_group)
        self.lbl_rate = QLabel(tr("0.000 events/min"))
        self.lbl_rate.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_rate.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.lbl_rate.setStyleSheet("font-size: 26px; font-weight: bold;")
        rate_layout.addWidget(self.lbl_rate)
        result_grid.addWidget(self.rate_group, 0, 1)

        self.time_group = QGroupBox(tr("Measurement Time"))
        self.time_group.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        time_layout = QVBoxLayout(self.time_group)
        self.lbl_elapsed = QLabel("00:00:00.0")
        self.lbl_elapsed.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_elapsed.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.lbl_elapsed.setStyleSheet(f"font-size: 22px; font-family: {MONOSPACE_FONT_FAMILY};")
        time_layout.addWidget(self.lbl_elapsed)
        result_grid.addWidget(self.time_group, 1, 0, 1, 2)
        summary_layout.addLayout(result_grid, stretch=1)

        self.lbl_last_event = QLabel(tr("Last event: —"))
        self.lbl_last_event.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_last_event.setWordWrap(True)
        self.lbl_last_event.setStyleSheet("padding: 6px;")
        summary_layout.addWidget(self.lbl_last_event)
        self.tabs.addTab(summary_tab, tr("Summary"))

        distributions_tab = QWidget()
        distributions_layout = QVBoxLayout(distributions_tab)
        distribution_controls = QHBoxLayout()
        distribution_controls.addWidget(QLabel(tr("Metric:")))
        self.combo_distribution_metric = QComboBox()
        self.combo_distribution_metric.addItem(tr("Peak Amplitude"), EventMetric.AMPLITUDE)
        self.combo_distribution_metric.addItem(tr("Duration"), EventMetric.DURATION)
        self.combo_distribution_metric.addItem(tr("Interarrival Time"), EventMetric.INTERARRIVAL)
        self.combo_distribution_metric.addItem(tr("Quiet Time"), EventMetric.QUIET_TIME)
        self.combo_distribution_metric.currentIndexChanged.connect(self._refresh_analysis_views)
        distribution_controls.addWidget(self.combo_distribution_metric)
        distribution_controls.addSpacing(12)
        self.lbl_distribution_unit = QLabel()
        distribution_controls.addWidget(self.lbl_distribution_unit)
        distribution_controls.addStretch(1)
        distributions_layout.addLayout(distribution_controls)

        distribution_stats_grid = QGridLayout()
        distribution_stats_grid.setContentsMargins(0, 0, 0, 4)
        distribution_stats_grid.setHorizontalSpacing(6)
        distribution_stats_grid.setVerticalSpacing(6)
        self.distribution_stat_cells: dict[str, QFrame] = {}
        self.distribution_stat_labels: dict[str, QLabel] = {}
        stat_specs = (
            ("count", tr("Samples")),
            ("minimum", tr("Min")),
            ("median", tr("Median")),
            ("mean", tr("Mean")),
            ("standard_deviation", tr("Std Dev")),
            ("percentile_95", tr("P95")),
            ("percentile_99", tr("P99")),
            ("maximum", tr("Max")),
        )
        for index, (key, title_text) in enumerate(stat_specs):
            row, column = divmod(index, 4)
            cell = QFrame()
            cell.setFrameShape(QFrame.Shape.StyledPanel)
            cell.setFrameShadow(QFrame.Shadow.Sunken)
            cell.setMinimumWidth(0)
            cell.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            cell_layout = QVBoxLayout(cell)
            cell_layout.setContentsMargins(6, 4, 6, 5)
            cell_layout.setSpacing(2)

            title = QLabel(title_text)
            title.setAlignment(Qt.AlignmentFlag.AlignCenter)
            title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            title.setStyleSheet("font-size: 11px; font-weight: bold;")
            cell_layout.addWidget(title)

            value = QLabel("—")
            value.setAlignment(Qt.AlignmentFlag.AlignCenter)
            value.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            value.setStyleSheet(f"font-family: {MONOSPACE_FONT_FAMILY}; font-size: 15px; font-weight: bold;")
            cell_layout.addWidget(value)

            distribution_stats_grid.addWidget(cell, row, column)
            self.distribution_stat_cells[key] = cell
            self.distribution_stat_labels[key] = value
        for column in range(4):
            distribution_stats_grid.setColumnStretch(column, 1)
        distributions_layout.addLayout(distribution_stats_grid)

        self.plot_distribution = pg.PlotWidget()
        self.plot_distribution.showGrid(x=True, y=True, alpha=0.25)
        self.plot_distribution.setLabel("left", tr("Event Count"))
        self.histogram_item = pg.BarGraphItem(x=[], height=[], width=1.0, brush=pg.mkBrush("#3daee9"))
        self.plot_distribution.addItem(self.histogram_item)
        distributions_layout.addWidget(self.plot_distribution, stretch=1)
        self.tabs.addTab(distributions_tab, tr("Distributions"))

        rate_tab = QWidget()
        rate_layout = QVBoxLayout(rate_tab)
        rate_controls = QHBoxLayout()
        rate_controls.addWidget(QLabel(tr("Time Bin:")))
        self.combo_rate_bin = QComboBox()
        for label, seconds in (
            (tr("1 second"), 1.0),
            (tr("10 seconds"), 10.0),
            (tr("1 minute"), 60.0),
            (tr("10 minutes"), 600.0),
            (tr("1 hour"), 3600.0),
        ):
            self.combo_rate_bin.addItem(label, seconds)
        self.combo_rate_bin.setCurrentIndex(2)
        self.combo_rate_bin.currentIndexChanged.connect(self._refresh_analysis_views)
        rate_controls.addWidget(self.combo_rate_bin)
        rate_controls.addStretch(1)
        rate_layout.addLayout(rate_controls)
        self.lbl_rate_trend_info = QLabel(tr("No rate bins are available."))
        self.lbl_rate_trend_info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        rate_layout.addWidget(self.lbl_rate_trend_info)
        self.plot_rate_trend = pg.PlotWidget()
        self.plot_rate_trend.showGrid(x=True, y=True, alpha=0.25)
        self.plot_rate_trend.setLabel("bottom", tr("Measurement Time"), units="s")
        self.plot_rate_trend.setLabel("left", tr("Event Rate"), units=tr("events/min"))
        self.rate_curve = self.plot_rate_trend.plot(
            pen=pg.mkPen("#e67e22", width=2.0),
            stepMode="center",
            connect="finite",
        )
        rate_layout.addWidget(self.plot_rate_trend, stretch=1)
        self.tabs.addTab(rate_tab, tr("Rate Trend"))

        events_tab = QWidget()
        events_layout = QVBoxLayout(events_tab)
        self.events_table = QTableWidget(0, 7)
        self.events_table.setHorizontalHeaderLabels(
            [
                tr("No."),
                tr("Start (s)"),
                tr("Duration (ms)"),
                tr("Polarity"),
                tr("Peak"),
                tr("Interval (s)"),
                tr("Status"),
            ]
        )
        self.events_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.events_table.verticalHeader().setVisible(False)
        header = self.events_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(True)
        events_layout.addWidget(self.events_table, stretch=1)
        export_row = QHBoxLayout()
        self.lbl_event_table_info = QLabel(tr("Showing 0 retained events."))
        export_row.addWidget(self.lbl_event_table_info)
        export_row.addStretch(1)
        self.btn_export_csv = QPushButton(tr("Export CSV..."))
        self.btn_export_csv.clicked.connect(lambda: self._export_events("csv"))
        export_row.addWidget(self.btn_export_csv)
        self.btn_export_json = QPushButton(tr("Export JSON..."))
        self.btn_export_json.clicked.connect(lambda: self._export_events("json"))
        export_row.addWidget(self.btn_export_json)
        events_layout.addLayout(export_row)
        self.tabs.addTab(events_tab, tr("Events"))

        display.addWidget(self.tabs, stretch=1)

        self.lbl_clipping = QLabel(tr("CLIPPING — results may be invalid."))
        self.lbl_clipping.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_clipping.setStyleSheet("color: #ff4040; font-weight: bold;")
        self.lbl_clipping.hide()
        display.addWidget(self.lbl_clipping)

        self.lbl_data_gap = QLabel(tr("I/O BUFFER ERROR — event count may be incomplete."))
        self.lbl_data_gap.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_data_gap.setStyleSheet("color: #ff9f1a; font-weight: bold;")
        self.lbl_data_gap.hide()
        display.addWidget(self.lbl_data_gap)

        self.lbl_config_change = QLabel(tr("ACQUISITION CONFIGURATION CHANGED — restart the measurement."))
        self.lbl_config_change.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_config_change.setStyleSheet("color: #ff9f1a; font-weight: bold;")
        self.lbl_config_change.hide()
        display.addWidget(self.lbl_config_change)

        self.lbl_record_limit = QLabel(tr("EVENT RECORD LIMIT — statistics and export are incomplete."))
        self.lbl_record_limit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_record_limit.setStyleSheet("color: #ff9f1a; font-weight: bold;")
        self.lbl_record_limit.hide()
        display.addWidget(self.lbl_record_limit)

        root.addWidget(self.display_widget, stretch=1)

        self.control_widget = QWidget()
        self.control_widget.setFixedWidth(260)
        controls = QVBoxLayout(self.control_widget)

        measurement_group = QGroupBox(tr("Measurement"))
        measurement_layout = QVBoxLayout(measurement_group)
        self.btn_start = QPushButton(tr("Start"))
        self.btn_start.setCheckable(True)
        self.btn_start.toggled.connect(self._on_start_toggled)
        measurement_layout.addWidget(self.btn_start)

        self.btn_reset = QPushButton(tr("Reset"))
        self.btn_reset.clicked.connect(self._on_reset)
        measurement_layout.addWidget(self.btn_reset)

        self.combo_duration = QComboBox()
        self.combo_duration.addItem(tr("Continuous"), None)
        for seconds in (1, 3, 5, 10, 20, 30):
            self.combo_duration.addItem(tr("{0} s").format(seconds), float(seconds))
        for minutes in (1, 2, 5, 10, 15, 30):
            self.combo_duration.addItem(tr("{0} min").format(minutes), float(minutes * 60))
        self.combo_duration.currentIndexChanged.connect(self._on_duration_changed)
        measurement_layout.addWidget(QLabel(tr("Duration:")))
        measurement_layout.addWidget(self.combo_duration)
        controls.addWidget(measurement_group)

        detection_group = QGroupBox(tr("Detection"))
        detection_form = QFormLayout(detection_group)

        self.combo_channel = QComboBox()
        self.combo_channel.addItem(tr("CH1"), 0)
        self.combo_channel.addItem(tr("CH2"), 1)
        self.combo_channel.currentIndexChanged.connect(self._on_channel_changed)
        detection_form.addRow(tr("Input Channel:"), self.combo_channel)

        self.spin_threshold = self._make_amplitude_spinbox(
            minimum=1e-9,
            maximum=0.999999999,
            value=self.module.threshold,
        )
        self.spin_threshold.valueChanged.connect(self._on_threshold_changed)
        self.combo_threshold_unit = QComboBox()
        threshold_row = QHBoxLayout()
        threshold_row.setContentsMargins(0, 0, 0, 0)
        threshold_row.addWidget(self.spin_threshold, stretch=1)
        threshold_row.addWidget(self.combo_threshold_unit)
        detection_form.addRow(tr("Threshold:"), threshold_row)

        self.combo_polarity = QComboBox()
        self.combo_polarity.addItem(tr("Positive"), EventPolarity.POSITIVE)
        self.combo_polarity.addItem(tr("Negative"), EventPolarity.NEGATIVE)
        self.combo_polarity.addItem(tr("Both polarities"), EventPolarity.BOTH)
        polarity_index = self.combo_polarity.findData(self.module.polarity)
        self.combo_polarity.setCurrentIndex(max(0, polarity_index))
        self.combo_polarity.currentIndexChanged.connect(self._on_polarity_changed)
        detection_form.addRow(tr("Polarity:"), self.combo_polarity)

        hysteresis_max = max(0.0, self.module.threshold - 1e-9)
        self.spin_hysteresis = self._make_amplitude_spinbox(
            minimum=0.0,
            maximum=hysteresis_max,
            value=self.module.hysteresis,
        )
        self.spin_hysteresis.valueChanged.connect(self._on_hysteresis_changed)
        detection_form.addRow(tr("Hysteresis:"), self.spin_hysteresis)

        self._threshold_calibration_state: tuple[bool, float] | None = None
        self.combo_threshold_unit.currentIndexChanged.connect(self._on_threshold_unit_changed)

        self.spin_holdoff = QDoubleSpinBox()
        self.spin_holdoff.setDecimals(3)
        self.spin_holdoff.setRange(0.0, 60_000.0)
        self.spin_holdoff.setSingleStep(1.0)
        self.spin_holdoff.setSuffix(" ms")
        self.spin_holdoff.setValue(self.module.holdoff_ms)
        self.spin_holdoff.setKeyboardTracking(False)
        self.spin_holdoff.valueChanged.connect(self._on_holdoff_changed)
        detection_form.addRow(tr("Holdoff:"), self.spin_holdoff)

        controls.addWidget(detection_group)

        info_group = QGroupBox(tr("Active Conditions"))
        info_layout = QVBoxLayout(info_group)
        self.lbl_release = QLabel()
        self.lbl_release.setWordWrap(True)
        info_layout.addWidget(self.lbl_release)
        self.lbl_locked_note = QLabel(tr("Detection settings are locked while measurement is running."))
        self.lbl_locked_note.setWordWrap(True)
        info_layout.addWidget(self.lbl_locked_note)
        controls.addWidget(info_group)
        controls.addStretch(1)

        root.addWidget(self.control_widget)
        self._settings_controls = [
            self.combo_channel,
            self.spin_threshold,
            self.combo_threshold_unit,
            self.combo_polarity,
            self.spin_hysteresis,
            self.spin_holdoff,
            self.combo_duration,
        ]
        self._last_analysis_key: tuple[int, int, int] | None = None
        self._rate_view_run_id: str | None = None
        self._rate_view_bin_seconds: float | None = None
        self._rate_view_y_max = 1.0
        self._refresh_threshold_unit_options(force=True)
        self._update_release_label()

    @staticmethod
    def _make_amplitude_spinbox(*, minimum: float, maximum: float, value: float) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setDecimals(EventDetectorWidget.AMPLITUDE_DISPLAY_DECIMALS)
        spin.setRange(minimum, maximum)
        spin.setSingleStep(0.001)
        spin.setValue(value)
        spin.setKeyboardTracking(False)
        return spin

    def _current_threshold_unit(self) -> str:
        unit = self.combo_threshold_unit.currentData()
        return str(unit) if unit in self.module.THRESHOLD_UNITS else "FS"

    def _configure_threshold_spins(self) -> None:
        unit = self._current_threshold_unit()
        scale = self.module.get_threshold_display_scale(unit)
        decimals = self.AMPLITUDE_DISPLAY_DECIMALS
        display_resolution = 10.0**-decimals
        minimum = max(scale * 1e-9, display_resolution)
        maximum = scale - max(scale * 1e-9, display_resolution)
        threshold_value = self.module.threshold_to_display(self.module.threshold, unit)
        hysteresis_value = self.module.threshold_to_display(self.module.hysteresis, unit)
        hysteresis_maximum = max(
            0.0,
            threshold_value - max(scale * 1e-9, display_resolution),
        )

        self.spin_threshold.blockSignals(True)
        self.spin_hysteresis.blockSignals(True)
        try:
            self.spin_threshold.setDecimals(decimals)
            self.spin_threshold.setRange(minimum, maximum)
            self.spin_threshold.setSingleStep(max(scale * 0.001, display_resolution))
            self.spin_threshold.setSuffix("")
            self.spin_threshold.setValue(threshold_value)

            self.spin_hysteresis.setDecimals(decimals)
            self.spin_hysteresis.setRange(0.0, hysteresis_maximum)
            self.spin_hysteresis.setSingleStep(max(scale * 0.001, display_resolution))
            self.spin_hysteresis.setSuffix(f" {unit}")
            self.spin_hysteresis.setValue(min(hysteresis_value, hysteresis_maximum))
        finally:
            self.spin_threshold.blockSignals(False)
            self.spin_hysteresis.blockSignals(False)

    def _refresh_threshold_unit_options(self, *, force: bool = False) -> None:
        calibration_state = self.module.get_input_calibration_state()
        if not force and calibration_state == self._threshold_calibration_state:
            return

        is_calibrated, _sensitivity = calibration_state
        available_units = ["FS", "mV", "V"] if is_calibrated else ["FS"]
        selected_unit = self.module.threshold_unit
        if selected_unit not in available_units:
            selected_unit = "FS"

        self.combo_threshold_unit.blockSignals(True)
        try:
            self.combo_threshold_unit.clear()
            for unit in available_units:
                self.combo_threshold_unit.addItem(unit, unit)
            self.combo_threshold_unit.setCurrentIndex(self.combo_threshold_unit.findData(selected_unit))
        finally:
            self.combo_threshold_unit.blockSignals(False)

        self.module.threshold_unit = selected_unit
        self._threshold_calibration_state = calibration_state
        self._configure_threshold_spins()

    def _on_threshold_unit_changed(self) -> None:
        self.module.threshold_unit = self._current_threshold_unit()
        self._configure_threshold_spins()
        self._update_release_label()
        self._update_condition_label()

    def _on_start_toggled(self, checked: bool) -> None:
        if checked:
            self._refresh_threshold_unit_options()
            try:
                self.module.start_analysis()
            except Exception as exc:
                logger.error("Failed to start Event Detector: %s", exc)
                self.btn_start.blockSignals(True)
                self.btn_start.setChecked(False)
                self.btn_start.blockSignals(False)
                QMessageBox.critical(self, tr("Error"), tr("Failed to start measurement: {0}").format(str(exc)))
                return

            self.btn_start.setText(tr("Stop"))
            self._set_settings_enabled(False)
            self._last_analysis_key = None
            self.timer.start()
        else:
            self.module.stop_analysis()
            self.btn_start.setText(tr("Start"))
            self._set_settings_enabled(True)
            self.timer.stop()
        self._update_results()

    def _on_reset(self) -> None:
        self.module.reset_measurement()
        self._last_analysis_key = None
        self._update_results()

    def _on_duration_changed(self) -> None:
        duration = self.combo_duration.currentData()
        self.module.set_target_duration(None if duration is None else float(duration))

    def _on_channel_changed(self) -> None:
        self.module.input_channel = int(self.combo_channel.currentData())
        self._update_condition_label()

    def _on_threshold_changed(self, value: float) -> None:
        unit = self._current_threshold_unit()
        self.module.threshold = self.module.threshold_from_display(value, unit)
        maximum_fs = max(0.0, self.module.threshold - 1e-9)
        maximum_display = self.module.threshold_to_display(maximum_fs, unit)
        self.spin_hysteresis.setMaximum(maximum_display)
        if self.module.hysteresis > maximum_fs:
            self.module.hysteresis = maximum_fs
            self.spin_hysteresis.blockSignals(True)
            self.spin_hysteresis.setValue(maximum_display)
            self.spin_hysteresis.blockSignals(False)
        self._update_release_label()
        self._update_condition_label()

    def _on_polarity_changed(self) -> None:
        self.module.polarity = EventPolarity(self.combo_polarity.currentData())
        self._update_release_label()
        self._update_condition_label()

    def _on_hysteresis_changed(self, value: float) -> None:
        self.module.hysteresis = self.module.threshold_from_display(value, self._current_threshold_unit())
        self._update_release_label()

    def _on_holdoff_changed(self, value: float) -> None:
        self.module.holdoff_ms = float(value)

    def _update_release_label(self) -> None:
        release = max(0.0, float(self.module.threshold) - float(self.module.hysteresis))
        unit = self._current_threshold_unit()
        release_display = self.module.threshold_to_display(release, unit)
        polarity = EventPolarity(self.module.polarity)
        if polarity == EventPolarity.POSITIVE:
            text = tr("Release level: +{0:.9g} {1}").format(release_display, unit)
        elif polarity == EventPolarity.NEGATIVE:
            text = tr("Release level: -{0:.9g} {1}").format(release_display, unit)
        else:
            text = tr("Release levels: ±{0:.9g} {1}").format(release_display, unit)
        self.lbl_release.setText(text)

    def _set_settings_enabled(self, enabled: bool) -> None:
        for control in self._settings_controls:
            control.setEnabled(enabled)

    def _update_condition_label(self) -> None:
        metadata = self.module.get_run_metadata()
        if metadata is None:
            channel = tr("CH1") if self.module.input_channel == 0 else tr("CH2")
            sample_rate = float(self.module.audio_engine.sample_rate)
            threshold_unit = self._current_threshold_unit()
            threshold = self.module.threshold_to_display(self.module.threshold, threshold_unit)
            polarity = EventPolarity(self.module.polarity)
        else:
            channel = str(metadata["input_channel"])
            sample_rate = float(metadata["sample_rate_hz"])
            threshold_unit = str(metadata.get("threshold_display_unit", "FS"))
            threshold = float(metadata.get("threshold_display_value", metadata["threshold_fs_peak"]))
            polarity = EventPolarity(str(metadata["polarity"]))

        polarity_symbol = {
            EventPolarity.POSITIVE: "+",
            EventPolarity.NEGATIVE: "−",
            EventPolarity.BOTH: "±",
        }[polarity]
        rate_text = tr("{0:g} kHz").format(sample_rate / 1000.0)
        if threshold_unit == "FS":
            threshold_text = tr("{0} FS").format(f"{polarity_symbol}{threshold:.9g}")
        else:
            threshold_text = f"{polarity_symbol}{threshold:.9g} {threshold_unit}"
        self.lbl_conditions.setText(f"{channel}  •  {threshold_text}  •  {rate_text}")

    @staticmethod
    def _format_optional(value: float | None, factor: float = 1.0) -> str:
        return "—" if value is None else f"{value * factor:.6g}"

    @staticmethod
    def _nice_rate_ceiling(rate: float) -> float:
        """Return a stable 1/2/5 ceiling with headroom for a non-negative rate."""
        target = max(1.0, float(rate) * 1.1)
        magnitude = 10.0 ** math.floor(math.log10(target))
        for multiple in (1.0, 2.0, 5.0, 10.0):
            ceiling = multiple * magnitude
            if target <= ceiling:
                return ceiling
        return 10.0 * magnitude

    def _update_distribution_stats(
        self,
        summary: MetricSummary,
        metric: EventMetric,
        amplitude_unit: str,
    ) -> None:
        factor = 1000.0 if metric == EventMetric.DURATION else 1.0
        if metric == EventMetric.AMPLITUDE:
            unit = amplitude_unit
        elif metric == EventMetric.DURATION:
            unit = "ms"
        else:
            unit = "s"
        self.lbl_distribution_unit.setText(f"{tr('Unit:')} {unit}")
        values = {
            "count": str(summary.count),
            "minimum": self._format_optional(summary.minimum, factor),
            "median": self._format_optional(summary.median, factor),
            "mean": self._format_optional(summary.mean, factor),
            "standard_deviation": self._format_optional(summary.standard_deviation, factor),
            "percentile_95": self._format_optional(summary.percentile_95, factor),
            "percentile_99": self._format_optional(summary.percentile_99, factor),
            "maximum": self._format_optional(summary.maximum, factor),
        }
        for key, text in values.items():
            self.distribution_stat_labels[key].setText(text)

    def _refresh_analysis_views(self, *_args) -> None:
        if _args:
            self._last_analysis_key = None
        snapshot = self.module.get_snapshot()
        key = (snapshot.retained_event_count, snapshot.dropped_record_count, int(snapshot.elapsed_seconds))
        if key == self._last_analysis_key:
            return
        self._last_analysis_key = key

        events = self.module.get_events()
        amplitude_scale, amplitude_unit = self.module.get_amplitude_display()
        statistics = summarize_events(events, amplitude_scale=amplitude_scale)
        metric = EventMetric(self.combo_distribution_metric.currentData())
        metric_summary = {
            EventMetric.AMPLITUDE: statistics.amplitude,
            EventMetric.DURATION: statistics.duration,
            EventMetric.INTERARRIVAL: statistics.interarrival,
            EventMetric.QUIET_TIME: statistics.quiet_time,
        }[metric]
        self._update_distribution_stats(metric_summary, metric, amplitude_unit)
        histogram = build_histogram(events, metric, amplitude_scale=amplitude_scale)
        if histogram.counts:
            edges = np.asarray(histogram.edges, dtype=np.float64)
            if metric == EventMetric.DURATION:
                edges *= 1000.0
            centers = (edges[:-1] + edges[1:]) / 2.0
            widths = np.diff(edges) * 0.9
            self.histogram_item.setOpts(
                x=centers,
                height=np.asarray(histogram.counts, dtype=np.float64),
                width=widths,
            )
            self.plot_distribution.enableAutoRange()
        else:
            self.histogram_item.setOpts(x=[], height=[], width=1.0)

        if metric == EventMetric.AMPLITUDE:
            self.plot_distribution.setLabel("bottom", tr("Peak Amplitude"), units=amplitude_unit)
        elif metric == EventMetric.DURATION:
            self.plot_distribution.setLabel("bottom", tr("Duration"), units="ms")
        elif metric == EventMetric.INTERARRIVAL:
            self.plot_distribution.setLabel("bottom", tr("Interarrival Time"), units="s")
        else:
            self.plot_distribution.setLabel("bottom", tr("Quiet Time"), units="s")

        bin_seconds = float(self.combo_rate_bin.currentData())
        metadata = self.module.get_run_metadata()
        run_id = str(metadata["run_id"]) if metadata is not None else None
        if run_id != self._rate_view_run_id or bin_seconds != self._rate_view_bin_seconds:
            self._rate_view_run_id = run_id
            self._rate_view_bin_seconds = bin_seconds
            self._rate_view_y_max = 1.0

        trend = build_rate_trend(
            events,
            elapsed_seconds=snapshot.elapsed_seconds,
            sample_rate=self.module.get_run_sample_rate(),
            bin_seconds=bin_seconds,
            data_gap_samples=self.module.get_data_gap_samples(),
        )
        if trend.event_counts:
            starts = np.asarray(trend.bin_starts_seconds, dtype=np.float64)
            ends = np.asarray(trend.bin_ends_seconds, dtype=np.float64)
            boundaries = np.concatenate((starts[:1], ends))
            rates = np.asarray(trend.rates_per_minute, dtype=np.float64)
            self.rate_curve.setData(boundaries, rates, connect="finite")
            invalid_count = sum(not valid for valid in trend.valid_bins)
            partial_text = tr(" • current bin is partial") if trend.partial_bins[-1] else ""
            self.lbl_rate_trend_info.setText(
                tr("Bins: {0} • Invalid bins: {1}{2}").format(
                    len(trend.event_counts),
                    invalid_count,
                    partial_text,
                )
            )
            finite_rates = rates[np.isfinite(rates)]
            rate_max = float(np.max(finite_rates)) if finite_rates.size else 0.0
            if rate_max * 1.1 > self._rate_view_y_max:
                self._rate_view_y_max = self._nice_rate_ceiling(rate_max)
        else:
            self.rate_curve.setData([], [])
            self.lbl_rate_trend_info.setText(tr("No rate bins are available."))

        x_block_seconds = bin_seconds * self.RATE_VIEW_BLOCK_BINS
        x_block_count = max(1, math.ceil(snapshot.elapsed_seconds / x_block_seconds))
        self.plot_rate_trend.setXRange(0.0, x_block_count * x_block_seconds, padding=0.0)
        self.plot_rate_trend.setYRange(0.0, self._rate_view_y_max, padding=0.0)

        visible_events = events[-500:]
        self.events_table.setRowCount(len(visible_events))
        for row_index, event in enumerate(visible_events):
            peak_value = event.peak * amplitude_scale
            interval_text = "—" if event.interval_seconds is None else f"{event.interval_seconds:.6g}"
            polarity_text = tr("Positive") if event.peak >= 0 else tr("Negative")
            completion_text = {
                EventCompletion.VALID: tr("Valid"),
                EventCompletion.CENSORED_STOP: tr("Censored at stop"),
                EventCompletion.CENSORED_GAP: tr("Censored by data gap"),
                EventCompletion.CENSORED_CONFIG_CHANGE: tr("Censored by configuration change"),
            }[event.completion]
            values = (
                str(event.sequence_number),
                f"{event.start_sample / self.module.get_run_sample_rate():.6f}",
                f"{event.duration_seconds * 1000.0:.6g}",
                polarity_text,
                f"{peak_value:.6g} {amplitude_unit}",
                interval_text,
                completion_text,
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column != 6:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.events_table.setItem(row_index, column, item)
        self.lbl_event_table_info.setText(
            tr("Showing {0} of {1} retained events.").format(len(visible_events), len(events))
        )

    def _export_events(self, export_format: str) -> None:
        metadata = self.module.get_run_metadata()
        if metadata is None:
            QMessageBox.information(self, tr("Event Export"), tr("No measurement run is available to export."))
            return
        extension = ".json" if export_format == "json" else ".csv"
        run_id = str(metadata.get("run_id", "run"))[:8]
        default_name = f"event_detector_{run_id}{extension}"
        file_filter = tr("JSON Files (*.json)") if export_format == "json" else tr("CSV Files (*.csv)")
        path, _ = QFileDialog.getSaveFileName(self, tr("Export Event Records"), default_name, file_filter)
        if not path:
            return
        if not path.lower().endswith(extension):
            path += extension
        try:
            self.module.export_events(path)
        except Exception as exc:
            logger.error("Failed to export Event Detector records: %s", exc, exc_info=True)
            QMessageBox.critical(self, tr("Error"), tr("Failed to export event records: {0}").format(str(exc)))
            return
        QMessageBox.information(self, tr("Event Export"), tr("Event records exported successfully."))

    @staticmethod
    def _format_elapsed(seconds: float) -> str:
        tenths = max(0, int(seconds * 10.0))
        hours, remainder = divmod(tenths, 36_000)
        minutes, remainder = divmod(remainder, 600)
        secs, tenth = divmod(remainder, 10)
        return f"{hours:02d}:{minutes:02d}:{secs:02d}.{tenth}"

    @staticmethod
    def _format_rate(rate: float) -> str:
        if rate < 1000.0:
            return tr("{0:.3f} events/min").format(rate)
        return tr("{0:,.1f} events/min").format(rate)

    def _update_results(self) -> None:
        if self.btn_start.isChecked() and not self.module.is_running:
            # A fixed-duration run has stopped in the audio callback. Complete
            # its cleanup from the GUI thread and restore the control state.
            self.module.stop_analysis()
            self.btn_start.blockSignals(True)
            self.btn_start.setChecked(False)
            self.btn_start.blockSignals(False)
            self.btn_start.setText(tr("Start"))
            self._set_settings_enabled(True)
            self.timer.stop()
        if not self.module.is_running:
            self._refresh_threshold_unit_options()
        snapshot = self.module.get_snapshot()
        self.lbl_count.setText(f"{snapshot.event_count:,}")
        self.lbl_rate.setText(
            self._format_rate(snapshot.event_rate_per_minute) if snapshot.measurement_valid else tr("INVALID")
        )
        self.lbl_elapsed.setText(self._format_elapsed(snapshot.elapsed_seconds))
        self.lbl_clipping.setVisible(snapshot.clipping_detected)
        self.lbl_data_gap.setVisible(snapshot.data_gap_detected)
        self.lbl_config_change.setVisible(snapshot.configuration_changed_detected)
        self.lbl_record_limit.setVisible(snapshot.dropped_record_count > 0)
        self.btn_export_csv.setEnabled(self.module.get_run_metadata() is not None)
        self.btn_export_json.setEnabled(self.module.get_run_metadata() is not None)
        self._update_condition_label()

        amplitude_scale, amplitude_unit = self.module.get_amplitude_display()
        if snapshot.last_event is None:
            self.lbl_last_event.setText(tr("Last event: —"))
        else:
            event = snapshot.last_event
            last_event_text = tr("Last event: #{0} • {1:.6g} {2} • {3:.6g} ms").format(
                event.sequence_number,
                event.peak * amplitude_scale,
                amplitude_unit,
                event.duration_seconds * 1000.0,
            )
            if event.completion != EventCompletion.VALID:
                last_event_text = f"{last_event_text}  •  {tr('Censored')}"
            self.lbl_last_event.setText(last_event_text)

        state_text = {
            DetectorState.STOPPED: tr("STOPPED"),
            DetectorState.WAITING_FOR_RELEASE: tr("WAITING FOR RELEASE"),
            DetectorState.ARMED: tr("ARMED"),
            DetectorState.EVENT: tr("EVENT"),
            DetectorState.HOLDOFF: tr("HOLDOFF"),
        }[snapshot.state]
        state_color = {
            DetectorState.STOPPED: "#888888",
            DetectorState.WAITING_FOR_RELEASE: "#3daee9",
            DetectorState.ARMED: "#32b85c",
            DetectorState.EVENT: "#ff4040",
            DetectorState.HOLDOFF: "#ff9f1a",
        }[snapshot.state]
        self.lbl_state.setText(state_text)
        self.lbl_state.setStyleSheet(
            f"font-size: 16px; font-weight: bold; color: {state_color}; "
            "background-color: rgba(128, 128, 128, 28); border-radius: 4px; padding: 6px 12px;"
        )
        self._refresh_analysis_views()

    def update_compact_layout(self) -> None:
        if not hasattr(self, "control_widget"):
            return
        is_split = self.control_widget.parent() is not self
        if not is_split:
            self.control_widget.setHidden(self.is_compact_mode())

    def closeEvent(self, event) -> None:
        self.timer.stop()
        self.module.stop_analysis()
        super().closeEvent(event)
