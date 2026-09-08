"""Persistent user controls for the engine-owned I/O Bridge."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.core.audio_engine import AudioEngine
from src.core.io_bridge import IOBridgeRoute, IOBridgeSnapshot, IOBridgeState
from src.core.localization import tr
from src.core.module_constants import MODULE_IO_BRIDGE
from src.measurement_modules.base import MeasurementModule
from src.gui.widgets.compactable_interface import CompactableWidgetInterface

if TYPE_CHECKING:
    from src.core.config_manager import ConfigManager


class IOBridge(MeasurementModule):
    """Thin module facade around the AudioEngine-owned bridge controller."""

    def __init__(self, audio_engine: AudioEngine, config_manager: ConfigManager | None = None) -> None:
        self.audio_engine = audio_engine
        self.config_manager = config_manager
        self.controller = audio_engine.io_bridge
        self.is_running = False
        self._load_preferences()

    @property
    def name(self) -> str:
        return MODULE_IO_BRIDGE

    @property
    def description(self) -> str:
        return "Monitor the analysis input locally or send local input to Remote Audio I/O."

    def _load_preferences(self) -> None:
        if self.config_manager is None:
            return
        config = self.config_manager.get_io_bridge_config()
        try:
            self.controller.set_route(str(config.get("route", IOBridgeRoute.PHYSICAL.value)))
        except (RuntimeError, ValueError):
            self.controller.set_route(IOBridgeRoute.PHYSICAL)
        self.controller.set_gain_db(float(config.get("gain_db", self.controller.DEFAULT_GAIN_DB)))

    def _save_preferences(self) -> None:
        if self.config_manager is not None:
            self.config_manager.set_io_bridge_config(
                {
                    "route": self.controller.route.value,
                    "gain_db": self.controller.gain_db,
                }
            )

    def set_route(self, route: IOBridgeRoute | str) -> None:
        self.controller.set_route(route)
        self._save_preferences()

    def set_gain_db(self, gain_db: float) -> float:
        value = self.controller.set_gain_db(gain_db)
        self._save_preferences()
        return value

    def start(self) -> bool:
        started = self.controller.start()
        self.is_running = self.controller.snapshot().active
        return started

    def stop(self, reason: str | None = None) -> None:
        self.controller.stop(reason)
        self.is_running = False

    def toggle(self, enabled: bool) -> bool:
        if enabled:
            return self.start()
        self.stop()
        return True

    def snapshot(self) -> IOBridgeSnapshot:
        snapshot = self.controller.snapshot()
        self.is_running = snapshot.active
        return snapshot

    def get_widget(self) -> QWidget:
        return IOBridgeWidget(self)


class IOBridgeWidget(QWidget, CompactableWidgetInterface):
    """Compact, state-aware Bridge panel with one primary ON/OFF action."""

    def __init__(self, module: IOBridge, parent: QWidget | None = None) -> None:
        QWidget.__init__(self, parent)
        CompactableWidgetInterface.__init__(self)
        self.module = module
        self._updating = False
        self._build_ui()
        self._timer = QTimer(self)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self.refresh_status)
        self._timer.start()
        self.refresh_status()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        self.description_label = QLabel(
            tr("Monitor the analysis input locally or send local input to Remote Audio I/O.")
        )
        self.description_label.setWordWrap(True)
        layout.addWidget(self.description_label)

        status_group = QGroupBox(tr("Status"))
        status_form = QFormLayout(status_group)
        self.status_label = QLabel()
        self.status_label.setAccessibleName(tr("Status"))
        self.input_label = QLabel("-")
        self.output_label = QLabel("-")
        for label in (self.status_label, self.input_label, self.output_label):
            label.setWordWrap(True)
        status_form.addRow(tr("Status"), self.status_label)
        status_form.addRow(tr("Input:"), self.input_label)
        status_form.addRow(tr("Output:"), self.output_label)
        layout.addWidget(status_group)
        self.details_group = status_group

        controls = QGroupBox(tr("I/O Bridge"))
        form = QFormLayout(controls)
        self.route_combo = QComboBox()
        self.route_combo.addItem(tr("Physical"), IOBridgeRoute.PHYSICAL.value)
        self.route_combo.addItem(tr("Remote Output"), IOBridgeRoute.REMOTE_OUTPUT.value)
        self.route_combo.currentIndexChanged.connect(self._on_route_changed)
        self.route_combo.setToolTip(tr("Choose the Bridge output route. The route can only change while OFF."))
        form.addRow(tr("Output route"), self.route_combo)

        self.gain_spin = QDoubleSpinBox()
        self.gain_spin.setRange(-60.0, 0.0)
        self.gain_spin.setSingleStep(0.5)
        self.gain_spin.setDecimals(1)
        self.gain_spin.setSuffix(tr(" dB"))
        self.gain_spin.valueChanged.connect(self._on_gain_changed)
        self.gain_spin.setToolTip(tr("Bridge send level relative to full scale."))
        form.addRow(tr("Gain:"), self.gain_spin)
        layout.addWidget(controls)
        self.controls_group = controls

        self.toggle_btn = QPushButton(tr("OFF"))
        self.toggle_btn.setCheckable(True)
        self.toggle_btn.setAccessibleName(tr("I/O Bridge"))
        self.toggle_btn.clicked.connect(self._on_toggle)
        layout.addWidget(self.toggle_btn)

        self.reason_label = QLabel()
        self.reason_label.setWordWrap(True)
        self.reason_label.hide()
        layout.addWidget(self.reason_label)
        layout.addStretch(1)
        self.setMinimumSize(0, 0)

    def _on_route_changed(self, _index: int) -> None:
        if self._updating:
            return
        value = self.route_combo.currentData()
        try:
            self.module.set_route(str(value))
        except (RuntimeError, ValueError) as exc:
            self.reason_label.setText(f"{tr('Error')}: {exc}")
        self.refresh_status()

    def _on_gain_changed(self, value: float) -> None:
        if not self._updating:
            self.module.set_gain_db(value)

    def _on_toggle(self, enabled: bool) -> None:
        if self._updating:
            return
        success = self.module.toggle(enabled)
        if not success:
            self._updating = True
            try:
                self.toggle_btn.setChecked(False)
            finally:
                self._updating = False
        self.refresh_status()

    def _state_text(self, state: IOBridgeState) -> str:
        if state is IOBridgeState.STARTING:
            return tr("STARTING")
        if state is IOBridgeState.STOPPING:
            return tr("STOPPING")
        if state is IOBridgeState.ERROR:
            return tr("ERROR")
        return tr("ON") if state is IOBridgeState.ON else tr("OFF")

    def refresh_status(self) -> None:
        snapshot = self.module.snapshot()
        availability = self.module.controller.route_availability(snapshot.route)
        self._updating = True
        try:
            route_index = self.route_combo.findData(snapshot.route.value)
            if route_index >= 0 and route_index != self.route_combo.currentIndex():
                self.route_combo.setCurrentIndex(route_index)
            if abs(self.gain_spin.value() - snapshot.gain_db) > 1e-6:
                self.gain_spin.setValue(snapshot.gain_db)
            self.toggle_btn.setChecked(snapshot.active)
            self.toggle_btn.setText(tr("ON") if snapshot.active else tr("OFF"))
            transition = snapshot.state in (IOBridgeState.STARTING, IOBridgeState.STOPPING)
            self.toggle_btn.setEnabled(not transition)
            self.route_combo.setEnabled(not snapshot.active and not transition)
            self.gain_spin.setEnabled(not transition)
        finally:
            self._updating = False

        self.status_label.setText(self._state_text(snapshot.state))
        self.input_label.setText(snapshot.input_label or availability.input_label or "-")
        self.output_label.setText(snapshot.output_label or availability.output_label or "-")
        reason = snapshot.reason
        if reason is None and not availability.available:
            reason = availability.reason
        if reason:
            self.reason_label.setText(f"{tr('Unavailable')}: {reason}")
            self.reason_label.show()
        else:
            self.reason_label.clear()
            self.reason_label.hide()

    def update_compact_layout(self) -> None:
        # Keep the live route, level, and primary action visible in compact mode.
        self.description_label.setVisible(not self.is_compact_mode())

    def closeEvent(self, event) -> None:
        self._timer.stop()
        super().closeEvent(event)
