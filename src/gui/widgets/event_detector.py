"""Continuous threshold-event counter and statistics widget."""

from __future__ import annotations

import logging

import numpy as np
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.core.audio_engine import AudioEngine
from src.core.event_detector import (
    DetectorConfig,
    DetectorSnapshot,
    DetectorState,
    EventDetectorCore,
    EventPolarity,
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
        self.is_running = True

        try:
            self.callback_id = self.audio_engine.register_callback(self._audio_callback)
        except Exception:
            self.callback_id = None
            self.is_running = False
            self._core.stop()
            raise

    def stop_analysis(self) -> None:
        if not self.is_running and self.callback_id is None:
            return

        self.is_running = False
        callback_id = self.callback_id
        self.callback_id = None

        if callback_id is not None:
            self.audio_engine.unregister_callback(callback_id)
        self._core.stop()

    def reset_measurement(self) -> None:
        self._core.reset()

    def get_snapshot(self) -> DetectorSnapshot:
        return self._core.snapshot()

    def get_events(self):
        """Expose completed event records for future statistics/export views."""
        return self._core.get_events()

    def _audio_callback(self, indata, outdata, frames, time_info, status) -> None:
        del frames, time_info
        outdata.fill(0)
        if not self.is_running:
            return
        if indata is None:
            self._core.mark_data_gap()
            return

        data = np.asarray(indata)
        if data.size == 0:
            return
        if data.ndim == 1:
            samples = data
        elif data.ndim == 2:
            channel = self.input_channel if self.input_channel < data.shape[1] else 0
            samples = data[:, channel]
        else:
            self._core.mark_data_gap()
            return

        self._core.process(samples, data_gap=bool(status))


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
        display.setSpacing(16)

        state_group = QGroupBox(tr("Detector State"))
        state_layout = QVBoxLayout(state_group)
        self.lbl_state = QLabel(tr("STOPPED"))
        self.lbl_state.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_state.setStyleSheet("font-size: 24px; font-weight: bold; color: #888888;")
        state_layout.addWidget(self.lbl_state)
        display.addWidget(state_group)

        result_row = QHBoxLayout()
        count_group = QGroupBox(tr("Event Count"))
        count_layout = QVBoxLayout(count_group)
        self.lbl_count = QLabel("0")
        self.lbl_count.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_count.setStyleSheet("font-size: 52px; font-weight: bold;")
        count_layout.addWidget(self.lbl_count)
        result_row.addWidget(count_group, stretch=1)

        rate_group = QGroupBox(tr("Event Rate"))
        rate_layout = QVBoxLayout(rate_group)
        self.lbl_rate = QLabel(tr("0.000 events/min"))
        self.lbl_rate.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_rate.setStyleSheet("font-size: 34px; font-weight: bold;")
        rate_layout.addWidget(self.lbl_rate)
        result_row.addWidget(rate_group, stretch=1)
        display.addLayout(result_row, stretch=1)

        time_group = QGroupBox(tr("Measurement Time"))
        time_layout = QVBoxLayout(time_group)
        self.lbl_elapsed = QLabel("00:00:00.0")
        self.lbl_elapsed.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_elapsed.setStyleSheet("font-size: 28px; font-family: monospace;")
        time_layout.addWidget(self.lbl_elapsed)
        display.addWidget(time_group)

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

        self.lbl_definition = QLabel(
            tr("An event is counted when the signal crosses the threshold after returning to the release level.")
        )
        self.lbl_definition.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_definition.setWordWrap(True)
        display.addWidget(self.lbl_definition)

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

        self.spin_threshold = self._make_amplitude_spinbox(minimum=1e-9, maximum=10.0, value=self.module.threshold)
        self.spin_threshold.valueChanged.connect(self._on_threshold_changed)
        detection_form.addRow(tr("Threshold:"), self.spin_threshold)

        self.combo_polarity = QComboBox()
        self.combo_polarity.addItem(tr("Positive"), EventPolarity.POSITIVE)
        self.combo_polarity.addItem(tr("Negative"), EventPolarity.NEGATIVE)
        self.combo_polarity.addItem(tr("Both"), EventPolarity.BOTH)
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
            self.timer.start()
        else:
            self.module.stop_analysis()
            self.btn_start.setText(tr("Start"))
            self._set_settings_enabled(True)
            self.timer.stop()
        self._update_results()

    def _on_reset(self) -> None:
        self.module.reset_measurement()
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
        self.lbl_rate.setText(self._format_rate(snapshot.event_rate_per_minute))
        self.lbl_elapsed.setText(self._format_elapsed(snapshot.elapsed_seconds))
        self.lbl_clipping.setVisible(snapshot.clipping_detected)
        self.lbl_data_gap.setVisible(snapshot.data_gap_detected)

        state_text = {
            DetectorState.STOPPED: tr("STOPPED"),
            DetectorState.ARMED: tr("ARMED"),
            DetectorState.EVENT: tr("EVENT"),
            DetectorState.HOLDOFF: tr("HOLDOFF"),
        }[snapshot.state]
        state_color = {
            DetectorState.STOPPED: "#888888",
            DetectorState.ARMED: "#32b85c",
            DetectorState.EVENT: "#ff4040",
            DetectorState.HOLDOFF: "#ff9f1a",
        }[snapshot.state]
        self.lbl_state.setText(state_text)
        self.lbl_state.setStyleSheet(f"font-size: 24px; font-weight: bold; color: {state_color};")

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
