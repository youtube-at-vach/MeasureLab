"""Dedicated controls and integrity monitoring for network-backed audio I/O."""

from __future__ import annotations

import logging
import threading

from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.core.audio_engine import AudioEngine
from src.core.config_manager import ConfigManager
from src.core.localization import tr
from src.core.network_audio import NetworkAudioClient, NetworkAudioProvider


class _RemoteAudioSignals(QObject):
    connected = pyqtSignal(object)
    failed = pyqtSignal(str)


class RemoteAudioIOWidget(QWidget):
    """Connect to or provide one MeasureLab audio endpoint on a LAN."""

    def __init__(self, audio_engine: AudioEngine, config_manager: ConfigManager, parent=None) -> None:
        super().__init__(parent)
        self.audio_engine = audio_engine
        self.config_manager = config_manager
        self.logger = logging.getLogger(__name__)
        self.client: NetworkAudioClient | None = None
        self.provider: NetworkAudioProvider | None = None
        self._connecting = False
        self._shutting_down = False
        self._signals = _RemoteAudioSignals(self)
        self._signals.connected.connect(self._on_client_connected)
        self._signals.failed.connect(self._on_client_failed)
        self._build_ui()
        self._load_config()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh_status)
        self._timer.start(500)
        self.refresh_status()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        heading = QLabel(tr("Remote Audio I/O"))
        heading.setStyleSheet("font-size: 20px; font-weight: bold;")
        layout.addWidget(heading)
        description = QLabel(
            tr(
                "Use another MeasureLab computer's audio device as a measurement input/output. "
                "Remote audio uses unencrypted LAN transport; enable the provider only on trusted networks."
            )
        )
        description.setWordWrap(True)
        layout.addWidget(description)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_client_tab(), tr("Use Remote I/O"))
        self.tabs.addTab(self._build_provider_tab(), tr("Provide Local I/O"))
        layout.addWidget(self.tabs)

        monitor = QGroupBox(tr("Connection Integrity"))
        monitor_layout = QVBoxLayout(monitor)
        self.integrity_label = QLabel(tr("Disconnected"))
        self.integrity_label.setStyleSheet("font-weight: bold; color: #888;")
        self.stats_label = QLabel("")
        self.stats_label.setWordWrap(True)
        monitor_layout.addWidget(self.integrity_label)
        monitor_layout.addWidget(self.stats_label)
        self.incident_table = QTableWidget(0, 4)
        self.incident_table.setHorizontalHeaderLabels([tr("Direction"), tr("Sample"), tr("Frames"), tr("Reason")])
        self.incident_table.setMaximumHeight(180)
        monitor_layout.addWidget(self.incident_table)
        layout.addWidget(monitor)

    def _build_client_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.host_edit = QLineEdit()
        self.host_edit.setPlaceholderText("192.168.1.10")
        form.addRow(tr("Remote host:"), self.host_edit)
        self.client_port_spin = QSpinBox()
        self.client_port_spin.setRange(1, 65535)
        self.client_port_spin.valueChanged.connect(self._sync_provider_port)
        form.addRow(tr("Control port:"), self.client_port_spin)
        self.jitter_spin = QSpinBox()
        self.jitter_spin.setRange(20, 2000)
        self.jitter_spin.setSuffix(" ms")
        form.addRow(tr("Fixed network buffer:"), self.jitter_spin)
        self.duplex_check = QCheckBox(tr("Request remote output (duplex)"))
        form.addRow(self.duplex_check)
        buttons = QWidget()
        buttons_layout = QHBoxLayout(buttons)
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        self.connect_button = QPushButton(tr("Connect"))
        self.disconnect_button = QPushButton(tr("Disconnect"))
        self.connect_button.clicked.connect(self.connect_client)
        self.disconnect_button.clicked.connect(self.disconnect_client)
        buttons_layout.addWidget(self.connect_button)
        buttons_layout.addWidget(self.disconnect_button)
        buttons_layout.addStretch()
        form.addRow(buttons)
        self.remote_details_label = QLabel(tr("No remote provider connected."))
        self.remote_details_label.setWordWrap(True)
        form.addRow(self.remote_details_label)
        return page

    def _build_provider_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.bind_edit = QLineEdit()
        self.bind_edit.setPlaceholderText("0.0.0.0")
        form.addRow(tr("Listen address:"), self.bind_edit)
        self.provider_port_spin = QSpinBox()
        self.provider_port_spin.setRange(1, 65535)
        self.provider_port_spin.valueChanged.connect(self._sync_client_port)
        form.addRow(tr("Control port:"), self.provider_port_spin)
        self.allow_output_check = QCheckBox(tr("Allow remote playback"))
        self.allow_output_check.setChecked(False)
        self.allow_output_check.setToolTip(tr("Keep disabled unless the remote computer is trusted."))
        self.allow_output_check.toggled.connect(self._on_allow_output_changed)
        form.addRow(self.allow_output_check)
        buttons = QWidget()
        buttons_layout = QHBoxLayout(buttons)
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        self.provider_button = QPushButton(tr("Start Provider"))
        self.stop_provider_button = QPushButton(tr("Stop Provider"))
        self.provider_button.clicked.connect(self.start_provider)
        self.stop_provider_button.clicked.connect(self.stop_provider)
        buttons_layout.addWidget(self.provider_button)
        buttons_layout.addWidget(self.stop_provider_button)
        buttons_layout.addStretch()
        form.addRow(buttons)
        self.provider_details_label = QLabel(tr("Provider is stopped."))
        self.provider_details_label.setWordWrap(True)
        form.addRow(self.provider_details_label)
        return page

    def _sync_provider_port(self, value: int) -> None:
        if self.provider_port_spin.value() != value:
            self.provider_port_spin.setValue(value)

    def _sync_client_port(self, value: int) -> None:
        if self.client_port_spin.value() != value:
            self.client_port_spin.setValue(value)

    def _load_config(self) -> None:
        config = self.config_manager.get_network_audio_config()
        self.host_edit.setText(str(config.get("host", "")))
        port = int(config.get("port", 40100))
        self.client_port_spin.setValue(port)
        self.provider_port_spin.setValue(port)
        self.jitter_spin.setValue(int(config.get("jitter_ms", 100)))
        self.duplex_check.setChecked(bool(config.get("duplex", True)))
        self.bind_edit.setText(str(config.get("bind_host", "0.0.0.0")))

    def _save_config(self) -> None:
        self.config_manager.set_network_audio_config(
            {
                "host": self.host_edit.text().strip(),
                "port": self.client_port_spin.value(),
                "jitter_ms": self.jitter_spin.value(),
                "duplex": self.duplex_check.isChecked(),
                "bind_host": self.bind_edit.text().strip() or "0.0.0.0",
            }
        )

    def connect_client(self) -> None:
        if self._connecting or self.client is not None or getattr(self.audio_engine, "network_mode", False):
            return
        if self.provider is not None and self.provider.running:
            QMessageBox.warning(self, tr("Remote Audio I/O"), tr("Stop the local provider before connecting."))
            return
        if self.audio_engine.get_status().get("active_clients", 0):
            QMessageBox.warning(
                self,
                tr("Remote Audio I/O"),
                tr("Stop active audio measurements before connecting remote audio."),
            )
            return
        host = self.host_edit.text().strip()
        if not host:
            QMessageBox.warning(self, tr("Remote Audio I/O"), tr("Enter a remote host name or IP address."))
            return
        self._save_config()
        self._connecting = True
        self.connect_button.setEnabled(False)
        self.integrity_label.setText(tr("Connecting..."))
        port = self.client_port_spin.value()
        jitter_ms = self.jitter_spin.value()
        duplex = self.duplex_check.isChecked()

        def worker() -> None:
            client = NetworkAudioClient(
                host,
                port,
                jitter_ms=jitter_ms,
                duplex=duplex,
            )
            try:
                client.connect()
            except Exception as exc:
                client.close()
                self._signals.failed.emit(str(exc))
                return
            self._signals.connected.emit(client)

        threading.Thread(target=worker, name="RemoteAudioConnect", daemon=True).start()

    def _on_client_connected(self, client: NetworkAudioClient) -> None:
        self._connecting = False
        if self._shutting_down:
            client.close()
            return
        try:
            self.audio_engine.configure_network_client(client)
        except Exception as exc:
            client.close()
            self._on_client_failed(str(exc))
            return
        self.client = client
        self.connect_button.setEnabled(False)
        self.disconnect_button.setEnabled(True)
        mode = tr("Duplex") if client.duplex else tr("Input only")
        self.remote_details_label.setText(
            tr("Provider: {0}\nInput: {1}\nOutput: {2}\nFormat: {3} Hz, {4} frames, {5}").format(
                client.provider_name,
                client.input_device_name,
                client.output_device_name,
                client.sample_rate,
                client.block_size,
                mode,
            )
        )
        self.refresh_status()

    def _on_client_failed(self, message: str) -> None:
        self._connecting = False
        if self._shutting_down:
            return
        self.connect_button.setEnabled(True)
        self.disconnect_button.setEnabled(False)
        self.integrity_label.setText(tr("Connection failed"))
        self.integrity_label.setStyleSheet("font-weight: bold; color: red;")
        self.stats_label.setText(str(message))
        QMessageBox.critical(self, tr("Remote Audio I/O"), tr("Failed to connect: {0}").format(message))

    def disconnect_client(self) -> None:
        if self.audio_engine.get_status().get("active_clients", 0):
            QMessageBox.warning(
                self,
                tr("Remote Audio I/O"),
                tr("Stop active audio measurements before disconnecting remote audio."),
            )
            return
        self.audio_engine.disconnect_network_client()
        self.client = None
        self.remote_details_label.setText(tr("No remote provider connected."))
        self.connect_button.setEnabled(True)
        self.disconnect_button.setEnabled(False)
        self.refresh_status()

    def start_provider(self) -> None:
        if self.provider is not None and self.provider.running:
            return
        if getattr(self.audio_engine, "network_mode", False):
            QMessageBox.warning(self, tr("Remote Audio I/O"), tr("Disconnect remote audio before providing local I/O."))
            return
        self._save_config()
        provider = NetworkAudioProvider(
            self.audio_engine,
            self.bind_edit.text().strip() or "0.0.0.0",
            self.provider_port_spin.value(),
            allow_output=self.allow_output_check.isChecked(),
        )
        try:
            provider.start()
        except Exception as exc:
            provider.stop()
            QMessageBox.critical(self, tr("Remote Audio I/O"), tr("Failed to start provider: {0}").format(exc))
            return
        self.provider = provider
        self.provider_button.setEnabled(False)
        self.stop_provider_button.setEnabled(True)
        self.refresh_status()

    def stop_provider(self) -> None:
        if self.provider is not None:
            self.provider.stop()
        self.provider = None
        self.provider_button.setEnabled(True)
        self.stop_provider_button.setEnabled(False)
        self.provider_details_label.setText(tr("Provider is stopped."))
        self.refresh_status()

    def _on_allow_output_changed(self, enabled: bool) -> None:
        if self.provider is not None:
            self.provider.set_allow_output(enabled)

    def refresh_status(self) -> None:
        snapshot: dict[str, object] | None = None
        if self.client is not None:
            snapshot = self.client.status_snapshot()
            if not self.client.connected and getattr(self.audio_engine, "network_mode", False):
                self.connect_button.setEnabled(False)
                self.disconnect_button.setEnabled(True)
        elif self.provider is not None:
            snapshot = self.provider.status_snapshot()
            address = str(snapshot.get("client_address") or tr("waiting"))
            output_active = (
                bool(snapshot.get("duplex")) if snapshot.get("client_address") else self.allow_output_check.isChecked()
            )
            output_state = tr("armed") if output_active else tr("muted")
            self.provider_details_label.setText(
                tr("Listening on {0}:{1}\nClient: {2}\nRemote output: {3}").format(
                    snapshot.get("bind_host"), snapshot.get("port"), address, output_state
                )
            )

        if snapshot is None:
            self.integrity_label.setText(tr("Disconnected"))
            self.integrity_label.setStyleSheet("font-weight: bold; color: #888;")
            self.stats_label.setText("")
            self._set_incidents([])
            self.disconnect_button.setEnabled(False)
            self.stop_provider_button.setEnabled(False)
            return

        loss = int(snapshot.get("lost_frames", 0) or 0)
        corrupt = int(snapshot.get("corrupt_packets", 0) or 0)
        queue_overflows = int(snapshot.get("local_queue_overflows", 0) or 0)
        state = str(snapshot.get("state", "disconnected"))
        damaged = loss > 0 or corrupt > 0 or queue_overflows > 0 or state == "error"
        if damaged:
            self.integrity_label.setText(tr("DATA LOSS DETECTED"))
            self.integrity_label.setStyleSheet("font-weight: bold; color: red;")
        else:
            self.integrity_label.setText(tr("Integrity OK ({0})").format(state))
            self.integrity_label.setStyleSheet("font-weight: bold; color: green;")
        self.stats_label.setText(
            tr(
                "Rx: {0} packets / Tx: {1} packets | Lost: {2} frames | Late: {3} | "
                "Duplicate: {4} | Corrupt: {5} | Buffered: {6} frames"
            ).format(
                snapshot.get("rx_packets", 0),
                snapshot.get("tx_packets", 0),
                loss,
                snapshot.get("late_packets", 0),
                snapshot.get("duplicate_packets", 0),
                corrupt,
                snapshot.get("buffered_frames", 0),
            )
        )
        self._set_incidents(list(snapshot.get("incidents", [])))

    def _set_incidents(self, incidents: list[object]) -> None:
        recent = [item for item in incidents[-20:] if isinstance(item, dict)]
        self.incident_table.setRowCount(len(recent))
        for row, incident in enumerate(reversed(recent)):
            values = (
                incident.get("direction", ""),
                incident.get("sample_index", ""),
                incident.get("frames", ""),
                incident.get("reason", ""),
            )
            for column, value in enumerate(values):
                self.incident_table.setItem(row, column, QTableWidgetItem(str(value)))

    def shutdown(self) -> None:
        self._shutting_down = True
        self._timer.stop()
        if self.provider is not None:
            self.provider.stop()
            self.provider = None
        if getattr(self.audio_engine, "network_mode", False):
            self.audio_engine.disconnect_network_client(force=True)
        elif self.client is not None:
            self.client.close()
        self.client = None

    def closeEvent(self, event) -> None:
        self.shutdown()
        super().closeEvent(event)
