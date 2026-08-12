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
    QGroupBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
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
from src.gui.widgets.compactable_interface import CompactableWidgetInterface
from src.gui.widgets.splittable_interface import SplittableWidgetInterface
from src.measurement_modules.base import MeasurementModule

logger = logging.getLogger(__name__)


class EventDetector(MeasurementModule):
    """AudioEngine adapter for the sample-accurate event detector core."""

    def __init__(self, audio_engine: AudioEngine):
        self.audio_engine = audio_engine
        self.is_running = False
        self.callback_id = None
        self.widget: EventDetectorWidget | None = None

        self.input_channel = 0
        self.threshold = 0.01
        self.polarity = EventPolarity.BOTH
        self.hysteresis = 0.001
        self.holdoff_ms = 10.0

        self._core = EventDetectorCore(self._build_config())
        self._run_metadata: dict[str, object] | None = None
        self._run_stopped_at_utc: str | None = None

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

    def start_analysis(self) -> None:
        if self.is_running:
            return

        config = self._build_config()
        self._core.start(config)
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
            self._run_stopped_at_utc = self._utc_now()

    def reset_measurement(self) -> None:
        self._core.reset()
        if self.is_running:
            self._capture_run_metadata(self._core.config)
        else:
            self._run_metadata = None
            self._run_stopped_at_utc = None

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

    def _capture_run_metadata(self, config: DetectorConfig) -> None:
        calibration = getattr(self.audio_engine, "calibration", None)
        calibrated_flag = getattr(calibration, "input_sensitivity_is_calibrated", False)
        is_calibrated = isinstance(calibrated_flag, (bool, np.bool_)) and bool(calibrated_flag)
        try:
            sensitivity = float(getattr(calibration, "input_sensitivity", 1.0))
        except (TypeError, ValueError):
            sensitivity = 1.0
            is_calibrated = False
        if not math.isfinite(sensitivity) or sensitivity <= 0:
            sensitivity = 1.0
            is_calibrated = False

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
            "polarity": config.polarity.value,
            "holdoff_seconds": float(config.holdoff_seconds),
            "clip_level_fs_peak": float(config.clip_level),
            "input_calibrated": is_calibrated,
            "input_sensitivity_v_peak_per_fs": sensitivity if is_calibrated else None,
        }
        self._run_stopped_at_utc = None

    def get_run_metadata(self) -> dict[str, object] | None:
        if self._run_metadata is None:
            return None
        metadata = dict(self._run_metadata)
        metadata["stopped_at_utc"] = self._run_stopped_at_utc
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
        self._core.process(samples, data_gap=input_status)


class EventDetectorWidget(QWidget, CompactableWidgetInterface, SplittableWidgetInterface):
    """Statistics-first UI without duplicating the Raw Time Series display."""

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

        self.lbl_conditions = QLabel(tr("No active measurement run."))
        self.lbl_conditions.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_conditions.setWordWrap(True)
        self.lbl_conditions.setStyleSheet("font-weight: bold; padding: 4px;")
        display.addWidget(self.lbl_conditions)

        state_group = QGroupBox(tr("Detector State"))
        state_layout = QVBoxLayout(state_group)
        self.lbl_state = QLabel(tr("STOPPED"))
        self.lbl_state.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_state.setStyleSheet("font-size: 18px; font-weight: bold; color: #888888;")
        state_layout.addWidget(self.lbl_state)
        display.addWidget(state_group)

        self.tabs = QTabWidget()

        summary_tab = QWidget()
        summary_layout = QVBoxLayout(summary_tab)
        summary_layout.setContentsMargins(6, 6, 6, 6)
        result_row = QHBoxLayout()
        count_group = QGroupBox(tr("Event Count"))
        count_layout = QVBoxLayout(count_group)
        self.lbl_count = QLabel("0")
        self.lbl_count.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_count.setStyleSheet("font-size: 42px; font-weight: bold;")
        count_layout.addWidget(self.lbl_count)
        result_row.addWidget(count_group, stretch=1)

        rate_group = QGroupBox(tr("Event Rate"))
        rate_layout = QVBoxLayout(rate_group)
        self.lbl_rate = QLabel(tr("0.000 events/min"))
        self.lbl_rate.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_rate.setStyleSheet("font-size: 26px; font-weight: bold;")
        rate_layout.addWidget(self.lbl_rate)
        result_row.addWidget(rate_group, stretch=1)
        summary_layout.addLayout(result_row, stretch=1)

        time_group = QGroupBox(tr("Measurement Time"))
        time_layout = QVBoxLayout(time_group)
        self.lbl_elapsed = QLabel("00:00:00.0")
        self.lbl_elapsed.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_elapsed.setStyleSheet("font-size: 22px; font-family: monospace;")
        time_layout.addWidget(self.lbl_elapsed)
        summary_layout.addWidget(time_group)

        self.lbl_polarity_counts = QLabel(tr("Valid: 0  •  Positive: 0  •  Negative: 0  •  Censored: 0"))
        self.lbl_polarity_counts.setAlignment(Qt.AlignmentFlag.AlignCenter)
        summary_layout.addWidget(self.lbl_polarity_counts)

        self.lbl_last_event = QLabel(tr("Last event: —"))
        self.lbl_last_event.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_last_event.setWordWrap(True)
        summary_layout.addWidget(self.lbl_last_event)

        self.lbl_definition = QLabel(
            tr("An event is counted after the signal returns to the release band and crosses the threshold.")
        )
        self.lbl_definition.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_definition.setWordWrap(True)
        summary_layout.addWidget(self.lbl_definition)
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
        distribution_controls.addStretch(1)
        distributions_layout.addLayout(distribution_controls)
        self.lbl_distribution_stats = QLabel(tr("No valid completed events."))
        self.lbl_distribution_stats.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_distribution_stats.setWordWrap(True)
        distributions_layout.addWidget(self.lbl_distribution_stats)
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
            symbol="o",
            symbolSize=6,
            symbolBrush=pg.mkBrush("#e67e22"),
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
        detection_form.addRow(tr("Threshold:"), self.spin_threshold)

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
            self.combo_polarity,
            self.spin_hysteresis,
            self.spin_holdoff,
        ]
        self._last_analysis_key: tuple[int, int, int] | None = None
        self._update_release_label()

    @staticmethod
    def _make_amplitude_spinbox(*, minimum: float, maximum: float, value: float) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setDecimals(9)
        spin.setRange(minimum, maximum)
        spin.setSingleStep(0.001)
        spin.setSuffix(" FS")
        spin.setValue(value)
        spin.setKeyboardTracking(False)
        return spin

    def _on_start_toggled(self, checked: bool) -> None:
        if checked:
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

    def _on_channel_changed(self) -> None:
        self.module.input_channel = int(self.combo_channel.currentData())

    def _on_threshold_changed(self, value: float) -> None:
        self.module.threshold = float(value)
        maximum = max(0.0, float(value) - 1e-9)
        self.spin_hysteresis.setMaximum(maximum)
        if self.module.hysteresis > maximum:
            self.module.hysteresis = maximum
        self._update_release_label()

    def _on_polarity_changed(self) -> None:
        self.module.polarity = EventPolarity(self.combo_polarity.currentData())
        self._update_release_label()

    def _on_hysteresis_changed(self, value: float) -> None:
        self.module.hysteresis = float(value)
        self._update_release_label()

    def _on_holdoff_changed(self, value: float) -> None:
        self.module.holdoff_ms = float(value)

    def _update_release_label(self) -> None:
        release = max(0.0, float(self.module.threshold) - float(self.module.hysteresis))
        polarity = EventPolarity(self.module.polarity)
        if polarity == EventPolarity.POSITIVE:
            text = tr("Release level: +{0:.9g} FS").format(release)
        elif polarity == EventPolarity.NEGATIVE:
            text = tr("Release level: -{0:.9g} FS").format(release)
        else:
            text = tr("Release levels: ±{0:.9g} FS").format(release)
        self.lbl_release.setText(text)

    def _set_settings_enabled(self, enabled: bool) -> None:
        for control in self._settings_controls:
            control.setEnabled(enabled)

    def _update_condition_label(self) -> None:
        metadata = self.module.get_run_metadata()
        if metadata is None:
            self.lbl_conditions.setText(tr("No active measurement run."))
            return
        calibrated = tr("calibrated") if metadata["input_calibrated"] else tr("uncalibrated")
        polarity = (
            tr("Both polarities")
            if metadata["polarity"] == EventPolarity.BOTH.value
            else tr(str(metadata["polarity"]).capitalize())
        )
        self.lbl_conditions.setText(
            tr("{0} • {1:g} Hz • Threshold {2:.9g} FS • Release {3:.9g} FS • {4} • Holdoff {5:g} ms • {6}").format(
                metadata["input_channel"],
                float(metadata["sample_rate_hz"]),
                float(metadata["threshold_fs_peak"]),
                float(metadata["release_level_fs_peak"]),
                polarity,
                float(metadata["holdoff_seconds"]) * 1000.0,
                calibrated,
            )
        )

    @staticmethod
    def _format_optional(value: float | None, factor: float = 1.0) -> str:
        return "—" if value is None else f"{value * factor:.6g}"

    def _format_metric_summary(self, summary: MetricSummary, metric: EventMetric, amplitude_unit: str) -> str:
        if summary.count == 0:
            return tr("No valid completed events.")
        factor = 1000.0 if metric == EventMetric.DURATION else 1.0
        if metric == EventMetric.AMPLITUDE:
            unit = amplitude_unit
        elif metric == EventMetric.DURATION:
            unit = "ms"
        else:
            unit = "s"
        return tr("N={0} • Min {1} • Median {2} • Mean {3} • Std {4} • P95 {5} • P99 {6} • Max {7} {8}").format(
            summary.count,
            self._format_optional(summary.minimum, factor),
            self._format_optional(summary.median, factor),
            self._format_optional(summary.mean, factor),
            self._format_optional(summary.standard_deviation, factor),
            self._format_optional(summary.percentile_95, factor),
            self._format_optional(summary.percentile_99, factor),
            self._format_optional(summary.maximum, factor),
            unit,
        )

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
        self.lbl_polarity_counts.setText(
            tr("Valid: {0}  •  Positive: {1}  •  Negative: {2}  •  Censored: {3}").format(
                statistics.valid_event_count,
                statistics.positive_event_count,
                statistics.negative_event_count,
                statistics.censored_event_count,
            )
        )

        metric = EventMetric(self.combo_distribution_metric.currentData())
        metric_summary = {
            EventMetric.AMPLITUDE: statistics.amplitude,
            EventMetric.DURATION: statistics.duration,
            EventMetric.INTERARRIVAL: statistics.interarrival,
            EventMetric.QUIET_TIME: statistics.quiet_time,
        }[metric]
        self.lbl_distribution_stats.setText(self._format_metric_summary(metric_summary, metric, amplitude_unit))
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
            centers = (starts + ends) / 2.0
            rates = np.asarray(trend.rates_per_minute, dtype=np.float64)
            self.rate_curve.setData(centers, rates, connect="finite")
            invalid_count = sum(not valid for valid in trend.valid_bins)
            partial_text = tr(" • current bin is partial") if trend.partial_bins[-1] else ""
            self.lbl_rate_trend_info.setText(
                tr("Bins: {0} • Invalid bins: {1}{2}").format(
                    len(trend.event_counts),
                    invalid_count,
                    partial_text,
                )
            )
            self.plot_rate_trend.enableAutoRange()
        else:
            self.rate_curve.setData([], [])
            self.lbl_rate_trend_info.setText(tr("No rate bins are available."))

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
            self.lbl_last_event.setText(
                tr("Last event: #{0} • {1:.6g} {2} • {3:.6g} ms • {4}").format(
                    event.sequence_number,
                    event.peak * amplitude_scale,
                    amplitude_unit,
                    event.duration_seconds * 1000.0,
                    tr("Valid") if event.completion == EventCompletion.VALID else tr("Censored"),
                )
            )

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
        self.lbl_state.setStyleSheet(f"font-size: 18px; font-weight: bold; color: {state_color};")
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
