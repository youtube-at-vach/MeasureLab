"""Dedicated controls and integrity monitoring for network-backed audio I/O."""

from __future__ import annotations

import ipaddress
import logging
import threading

from PyQt6.QtCore import QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtNetwork import QAbstractSocket, QNetworkInterface
from PyQt6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QStyle,
    QTabWidget,
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
        self._connect_cancel = threading.Event()
        self._shutting_down = False
        self._last_error: str | None = None
        self._integrity_source: object | None = None
        self._last_damage_events: int | None = None
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
        layout.setSpacing(12)
        heading = QLabel(tr("Remote Audio I/O"))
        heading_font = heading.font()
        heading_font.setBold(True)
        heading_font.setPointSizeF(heading_font.pointSizeF() * 1.35)
        heading.setFont(heading_font)
        layout.addWidget(heading)
        description = QLabel(tr("Use another MeasureLab computer's audio device over a trusted LAN."))
        description.setWordWrap(True)
        layout.addWidget(description)

        status_panel = QFrame()
        status_panel.setFrameShape(QFrame.Shape.StyledPanel)
        status_layout = QHBoxLayout(status_panel)

        activity_layout = QVBoxLayout()
        activity_heading = QLabel(tr("Status"))
        activity_heading_font = activity_heading.font()
        activity_heading_font.setBold(True)
        activity_heading.setFont(activity_heading_font)
        activity_layout.addWidget(activity_heading)

        activity_state_layout = QHBoxLayout()
        self.activity_icon = QLabel()
        self.activity_icon.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.activity_label = QLabel(tr("Disconnected"))
        activity_font = self.activity_label.font()
        activity_font.setBold(True)
        self.activity_label.setFont(activity_font)
        self.activity_label.setAccessibleName(tr("Status"))
        activity_state_layout.addWidget(self.activity_icon)
        activity_state_layout.addWidget(self.activity_label, 1)
        activity_layout.addLayout(activity_state_layout)
        self.activity_details_label = QLabel(tr("Enter the remote computer's address and connect."))
        self.activity_details_label.setWordWrap(True)
        self._reserve_status_lines(self.activity_details_label)
        activity_layout.addWidget(self.activity_details_label)
        status_layout.addLayout(activity_layout, 3)

        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.VLine)
        divider.setFrameShadow(QFrame.Shadow.Sunken)
        status_layout.addWidget(divider)

        integrity_layout = QVBoxLayout()
        integrity_heading = QLabel(tr("Connection quality"))
        integrity_heading_font = integrity_heading.font()
        integrity_heading_font.setBold(True)
        integrity_heading.setFont(integrity_heading_font)
        integrity_layout.addWidget(integrity_heading)

        integrity_state_layout = QHBoxLayout()
        self.integrity_icon = QLabel()
        self.integrity_icon.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.integrity_label = QLabel(tr("Disconnected"))
        integrity_font = self.integrity_label.font()
        integrity_font.setBold(True)
        self.integrity_label.setFont(integrity_font)
        self.integrity_label.setAccessibleName(tr("Connection quality"))
        integrity_state_layout.addWidget(self.integrity_icon)
        integrity_state_layout.addWidget(self.integrity_label, 1)
        integrity_layout.addLayout(integrity_state_layout)
        self.stats_label = QLabel(tr("Monitoring starts after connection."))
        self.stats_label.setWordWrap(True)
        self._reserve_status_lines(self.stats_label)
        integrity_layout.addWidget(self.stats_label)
        status_layout.addLayout(integrity_layout, 2)
        layout.addWidget(status_panel)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_client_tab(), tr("Connect to another computer"))
        self.tabs.addTab(self._build_provider_tab(), tr("Share this computer's audio"))
        self.tabs.currentChanged.connect(self.refresh_status)
        self.tabs.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        layout.addWidget(self.tabs)
        layout.addStretch(1)

    def _build_client_tab(self) -> QWidget:
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setSpacing(10)

        summary = QLabel(tr("Enter the remote computer's address and connect."))
        summary.setWordWrap(True)
        page_layout.addWidget(summary)

        settings_layout = QHBoxLayout()
        connection_group = QGroupBox(tr("Configuration"))
        form = QFormLayout(connection_group)
        self.host_edit = QLineEdit()
        self.host_edit.setPlaceholderText("192.168.1.10")
        self.host_edit.setAccessibleName(tr("Remote host:"))
        host_label = QLabel(tr("Remote host:"))
        host_label.setBuddy(self.host_edit)
        form.addRow(host_label, self.host_edit)
        self.client_port_spin = QSpinBox()
        self.client_port_spin.setRange(1, 65535)
        self.client_port_spin.valueChanged.connect(self._sync_provider_port)
        self.client_port_spin.setAccessibleName(tr("Control port:"))
        port_label = QLabel(tr("Control port:"))
        port_label.setBuddy(self.client_port_spin)
        form.addRow(port_label, self.client_port_spin)
        settings_layout.addWidget(connection_group, 3)

        options_group = QGroupBox(tr("Advanced"))
        options_form = QFormLayout(options_group)
        self.jitter_spin = QSpinBox()
        self.jitter_spin.setRange(20, 2000)
        self.jitter_spin.setSuffix(" ms")
        self.jitter_spin.setAccessibleName(tr("Fixed network buffer:"))
        buffer_label = QLabel(tr("Fixed network buffer:"))
        buffer_label.setBuddy(self.jitter_spin)
        options_form.addRow(buffer_label, self.jitter_spin)
        self.duplex_check = QCheckBox(tr("Request remote output (duplex)"))
        options_form.addRow(self.duplex_check)
        settings_layout.addWidget(options_group, 2)
        page_layout.addLayout(settings_layout)

        buttons_layout = QHBoxLayout()
        self.connect_button = QPushButton(tr("Connect"))
        self.disconnect_button = QPushButton(tr("Disconnect"))
        self.connect_button.clicked.connect(self.connect_client)
        self.disconnect_button.clicked.connect(self.disconnect_client)
        buttons_layout.addWidget(self.connect_button)
        buttons_layout.addWidget(self.disconnect_button)
        buttons_layout.addStretch()
        page_layout.addLayout(buttons_layout)

        details_group = QGroupBox(tr("Details"))
        details_layout = QVBoxLayout(details_group)
        self.remote_details_label = QLabel(tr("No remote provider connected."))
        self.remote_details_label.setWordWrap(True)
        self.remote_details_label.setAccessibleName(tr("Details"))
        details_layout.addWidget(self.remote_details_label)
        page_layout.addWidget(details_group)
        page_layout.addStretch(1)
        return page

    def _build_provider_tab(self) -> QWidget:
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setSpacing(10)

        summary = QLabel(tr("Choose a listen address and start sharing."))
        summary.setWordWrap(True)
        page_layout.addWidget(summary)

        settings_layout = QHBoxLayout()
        access_group = QGroupBox(tr("Configuration"))
        form = QFormLayout(access_group)
        self.bind_edit = QLineEdit()
        self.bind_edit.setPlaceholderText("0.0.0.0")
        self.bind_edit.setAccessibleName(tr("Listen address:"))
        bind_label = QLabel(tr("Listen address:"))
        bind_label.setBuddy(self.bind_edit)
        form.addRow(bind_label, self.bind_edit)
        self.provider_port_spin = QSpinBox()
        self.provider_port_spin.setRange(1, 65535)
        self.provider_port_spin.valueChanged.connect(self._sync_client_port)
        self.provider_port_spin.setAccessibleName(tr("Control port:"))
        port_label = QLabel(tr("Control port:"))
        port_label.setBuddy(self.provider_port_spin)
        form.addRow(port_label, self.provider_port_spin)
        settings_layout.addWidget(access_group, 3)

        playback_group = QGroupBox(tr("Playback"))
        playback_layout = QVBoxLayout(playback_group)
        self.allow_output_check = QCheckBox(tr("Allow remote playback"))
        self.allow_output_check.setChecked(False)
        self.allow_output_check.setToolTip(tr("Keep disabled unless the remote computer is trusted."))
        self.allow_output_check.toggled.connect(self._on_allow_output_changed)
        playback_layout.addWidget(self.allow_output_check)
        playback_help = QLabel(tr("Allows a trusted remote computer to use this computer's audio output."))
        playback_help.setWordWrap(True)
        playback_layout.addWidget(playback_help)
        playback_layout.addStretch(1)
        settings_layout.addWidget(playback_group, 2)
        page_layout.addLayout(settings_layout)

        buttons_layout = QHBoxLayout()
        self.provider_button = QPushButton(tr("Start sharing"))
        self.stop_provider_button = QPushButton(tr("Stop sharing"))
        self.provider_button.clicked.connect(self.start_provider)
        self.stop_provider_button.clicked.connect(self.stop_provider)
        buttons_layout.addWidget(self.provider_button)
        buttons_layout.addWidget(self.stop_provider_button)
        buttons_layout.addStretch()
        page_layout.addLayout(buttons_layout)

        details_group = QGroupBox(tr("Details"))
        details_layout = QVBoxLayout(details_group)
        self.provider_details_label = QLabel(tr("Provider is stopped."))
        self.provider_details_label.setWordWrap(True)
        self.provider_details_label.setAccessibleName(tr("Details"))
        details_layout.addWidget(self.provider_details_label)
        page_layout.addWidget(details_group)
        page_layout.addStretch(1)
        return page

    def _set_status_icon(self, label: QLabel, icon: QStyle.StandardPixmap) -> None:
        label.setPixmap(self.style().standardIcon(icon).pixmap(18, 18))

    @staticmethod
    def _reserve_status_lines(label: QLabel, lines: int = 5) -> None:
        """Keep the status panel stable and leave room for one wrapped line."""
        label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        label.setFixedHeight(label.fontMetrics().lineSpacing() * lines)

    def _sync_provider_port(self, value: int) -> None:
        if self.provider_port_spin.value() != value:
            self.provider_port_spin.setValue(value)

    def _sync_client_port(self, value: int) -> None:
        if self.client_port_spin.value() != value:
            self.client_port_spin.setValue(value)

    @staticmethod
    def _lan_ipv4_addresses() -> tuple[str, ...]:
        """Return IPv4 addresses that another computer may use to connect."""
        addresses: set[str] = set()
        for interface in QNetworkInterface.allInterfaces():
            flags = interface.flags()
            if not flags & QNetworkInterface.InterfaceFlag.IsUp:
                continue
            if flags & QNetworkInterface.InterfaceFlag.IsLoopBack:
                continue
            for entry in interface.addressEntries():
                address = entry.ip()
                if address.protocol() != QAbstractSocket.NetworkLayerProtocol.IPv4Protocol:
                    continue
                value = address.toString()
                if value and not address.isLoopback() and value != "0.0.0.0":
                    addresses.add(value)
        return tuple(sorted(addresses, key=ipaddress.IPv4Address))

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
        self._last_error = None
        self._connecting = True
        self._connect_cancel.clear()
        port = self.client_port_spin.value()
        jitter_ms = self.jitter_spin.value()
        duplex = self.duplex_check.isChecked()
        self.refresh_status()

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
                if not self._connect_cancel.is_set():
                    self._signals.failed.emit(str(exc))
                return
            if self._connect_cancel.is_set():
                client.close()
                return
            self._signals.connected.emit(client)

        threading.Thread(target=worker, name="RemoteAudioConnect", daemon=True).start()

    def _on_client_connected(self, client: NetworkAudioClient) -> None:
        self._connecting = False
        if self._shutting_down or self._connect_cancel.is_set():
            client.close()
            if not self._shutting_down:
                self.refresh_status()
            return
        try:
            self.audio_engine.configure_network_client(client)
        except Exception as exc:
            client.close()
            self._on_client_failed(str(exc))
            return
        self.client = client
        self._last_error = None
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
        if self._connect_cancel.is_set():
            self.refresh_status()
            return
        self._last_error = str(message)
        self.refresh_status()
        QMessageBox.critical(self, tr("Remote Audio I/O"), tr("Failed to connect: {0}").format(message))

    def disconnect_client(self) -> None:
        if self._connecting:
            self._connect_cancel.set()
            self._connecting = False
            self._last_error = None
            self.refresh_status()
            return
        if self.audio_engine.get_status().get("active_clients", 0):
            QMessageBox.warning(
                self,
                tr("Remote Audio I/O"),
                tr("Stop active audio measurements before disconnecting remote audio."),
            )
            return
        try:
            self.audio_engine.disconnect_network_client()
        except RuntimeError:
            QMessageBox.warning(
                self,
                tr("Remote Audio I/O"),
                tr("Stop active audio measurements before disconnecting remote audio."),
            )
            return
        self.client = None
        self._last_error = None
        self.remote_details_label.setText(tr("No remote provider connected."))
        self.refresh_status()

    def start_provider(self) -> None:
        if self.provider is not None and self.provider.running:
            return
        if getattr(self.audio_engine, "network_mode", False):
            QMessageBox.warning(self, tr("Remote Audio I/O"), tr("Disconnect remote audio before providing local I/O."))
            return
        self._save_config()
        self._last_error = None
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
            self._last_error = str(exc)
            self.refresh_status()
            QMessageBox.critical(self, tr("Remote Audio I/O"), tr("Failed to start provider: {0}").format(exc))
            return
        self.provider = provider
        self.refresh_status()

    def stop_provider(self) -> None:
        if self.provider is not None:
            self.provider.stop()
        self.provider = None
        self._last_error = None
        self.provider_details_label.setText(tr("Provider is stopped."))
        self.refresh_status()

    def _on_allow_output_changed(self, enabled: bool) -> None:
        if self.provider is not None:
            self.provider.set_allow_output(enabled)

    def _refresh_control_states(self) -> None:
        network_mode = bool(getattr(self.audio_engine, "network_mode", False))
        client_active = self.client is not None or network_mode
        provider_active = self.provider is not None and self.provider.running
        measurements_active = bool(self.audio_engine.get_status().get("active_clients", 0))

        client_settings_enabled = not self._connecting and not client_active and not provider_active
        self.host_edit.setEnabled(client_settings_enabled)
        self.client_port_spin.setEnabled(client_settings_enabled)
        self.jitter_spin.setEnabled(client_settings_enabled)
        self.duplex_check.setEnabled(client_settings_enabled)

        self.connect_button.setEnabled(client_settings_enabled and not measurements_active)
        self.disconnect_button.setText(tr("Cancel") if self._connecting else tr("Disconnect"))
        self.disconnect_button.setEnabled(self._connecting or (client_active and not measurements_active))
        if measurements_active and client_active:
            self.disconnect_button.setToolTip(tr("Stop active audio measurements before disconnecting remote audio."))
        else:
            self.disconnect_button.setToolTip("")

        provider_settings_enabled = not provider_active and not client_active and not self._connecting
        self.bind_edit.setEnabled(provider_settings_enabled)
        self.provider_port_spin.setEnabled(provider_settings_enabled)
        self.allow_output_check.setEnabled(provider_settings_enabled or provider_active)
        self.provider_button.setEnabled(provider_settings_enabled and not measurements_active)
        self.stop_provider_button.setEnabled(provider_active)

        if measurements_active and not client_active and not provider_active:
            reason = tr("Stop active audio measurements before connecting remote audio.")
            self.connect_button.setToolTip(reason)
            self.provider_button.setToolTip(reason)
        elif provider_active:
            self.connect_button.setToolTip(tr("Stop the local provider before connecting."))
            self.provider_button.setToolTip("")
        elif client_active:
            self.connect_button.setToolTip("")
            self.provider_button.setToolTip(tr("Disconnect remote audio before providing local I/O."))
        else:
            self.connect_button.setToolTip("")
            self.provider_button.setToolTip("")

    def refresh_status(self) -> None:
        snapshot: dict[str, object] | None = None
        source: object | None = None
        if self.client is not None:
            source = self.client
            snapshot = self.client.status_snapshot()
            client_state = str(snapshot.get("state", "disconnected"))
            client_connected = bool(getattr(self.client, "connected", client_state != "disconnected"))
            if client_state == "error" or not client_connected:
                error = str(snapshot.get("last_error") or tr("Disconnected"))
                self.activity_label.setText(tr("Connection failed"))
                self.activity_details_label.setText(
                    tr("Connection error: {0}. Disconnect and reconnect.").format(error)
                )
                self._set_status_icon(self.activity_icon, QStyle.StandardPixmap.SP_MessageBoxCritical)
            else:
                self.activity_label.setText(tr("Use Remote I/O"))
                self.activity_details_label.setText(self.remote_details_label.text())
                self._set_status_icon(self.activity_icon, QStyle.StandardPixmap.SP_DialogApplyButton)
        elif self.provider is not None:
            source = self.provider
            snapshot = self.provider.status_snapshot()
            address = str(snapshot.get("client_address") or tr("waiting"))
            bind_host = str(snapshot.get("bind_host") or "0.0.0.0")
            port = int(snapshot.get("port") or self.provider_port_spin.value())
            if bind_host == "0.0.0.0":
                endpoints = ", ".join(f"{host}:{port}" for host in self._lan_ipv4_addresses())
                remote_endpoint = endpoints or tr("Not available")
            else:
                remote_endpoint = f"{bind_host}:{port}"
            output_active = (
                bool(snapshot.get("duplex")) if snapshot.get("client_address") else self.allow_output_check.isChecked()
            )
            output_state = tr("armed") if output_active else tr("muted")
            self.provider_details_label.setText(
                tr("Listening on {0}:{1}\nConnect from another computer: {2}\nClient: {3}\nRemote output: {4}").format(
                    bind_host,
                    port,
                    remote_endpoint,
                    address,
                    output_state,
                )
            )
            if snapshot.get("state") == "error":
                error = str(snapshot.get("last_error") or tr("Disconnected"))
                self.activity_label.setText(tr("Connection failed"))
                self.activity_details_label.setText(tr("Check the settings and try again. Details: {0}").format(error))
                self._set_status_icon(self.activity_icon, QStyle.StandardPixmap.SP_MessageBoxCritical)
            elif snapshot.get("client_address"):
                self.activity_label.setText(tr("Provide Local I/O"))
                self.activity_details_label.setText(self.provider_details_label.text())
                self._set_status_icon(self.activity_icon, QStyle.StandardPixmap.SP_DialogApplyButton)
            else:
                self.activity_label.setText(tr("Provide Local I/O"))
                self.activity_details_label.setText(self.provider_details_label.text())
                self._set_status_icon(self.activity_icon, QStyle.StandardPixmap.SP_MessageBoxInformation)

        if snapshot is None:
            if self._connecting:
                self.activity_label.setText(tr("Connecting..."))
                self.activity_details_label.setText(f"{self.host_edit.text().strip()}:{self.client_port_spin.value()}")
                self._set_status_icon(self.activity_icon, QStyle.StandardPixmap.SP_BrowserReload)
            elif self._last_error:
                self.activity_label.setText(tr("Connection failed"))
                self.activity_details_label.setText(
                    tr("Check the settings and try again. Details: {0}").format(self._last_error)
                )
                self._set_status_icon(self.activity_icon, QStyle.StandardPixmap.SP_MessageBoxCritical)
            else:
                self.activity_label.setText(tr("Disconnected"))
                if self.tabs.currentIndex() == 0:
                    self.activity_details_label.setText(tr("Enter the remote computer's address and connect."))
                else:
                    self.activity_details_label.setText(tr("Choose a listen address and start sharing."))
                self._set_status_icon(self.activity_icon, QStyle.StandardPixmap.SP_MessageBoxInformation)
            self.integrity_label.setText(tr("Disconnected"))
            self._set_status_icon(self.integrity_icon, QStyle.StandardPixmap.SP_MessageBoxInformation)
            self.stats_label.setText(tr("Monitoring starts after connection."))
            self._integrity_source = None
            self._last_damage_events = None
            self._refresh_control_states()
            return

        if source is self.provider and snapshot.get("state") != "error" and not snapshot.get("client_address"):
            self.integrity_label.setText(tr("waiting"))
            self._set_status_icon(self.integrity_icon, QStyle.StandardPixmap.SP_MessageBoxInformation)
            self.stats_label.setText(tr("Monitoring starts after connection."))
            self._integrity_source = None
            self._last_damage_events = None
            self._refresh_control_states()
            return

        loss = int(snapshot.get("lost_frames", 0) or 0)
        corrupt = int(snapshot.get("corrupt_packets", 0) or 0)
        queue_overflows = int(snapshot.get("local_queue_overflows", 0) or 0)
        loss_events = int(snapshot.get("lost_packets", 0) or 0) + corrupt + queue_overflows
        state = str(snapshot.get("state", "disconnected"))
        loss_increasing = (
            source is self._integrity_source
            and self._last_damage_events is not None
            and loss_events > self._last_damage_events
        )
        self._integrity_source = source
        self._last_damage_events = loss_events

        if state == "error":
            self.integrity_label.setText(tr("Connection failed"))
            self._set_status_icon(self.integrity_icon, QStyle.StandardPixmap.SP_MessageBoxCritical)
        elif loss_increasing:
            self.integrity_label.setText(tr("Data loss is increasing"))
            self._set_status_icon(self.integrity_icon, QStyle.StandardPixmap.SP_MessageBoxCritical)
        elif loss_events:
            self.integrity_label.setText(tr("Data loss is not increasing"))
            self._set_status_icon(self.integrity_icon, QStyle.StandardPixmap.SP_MessageBoxWarning)
        else:
            self.integrity_label.setText(tr("No data loss ({0})").format(state))
            self._set_status_icon(self.integrity_icon, QStyle.StandardPixmap.SP_DialogApplyButton)
        if state == "error" and snapshot.get("last_error"):
            self.stats_label.setText(
                tr("Connection error: {0}. Disconnect and reconnect.").format(snapshot["last_error"])
            )
        else:
            self.stats_label.setText(
                tr("Dropped: {0} frames ({1} events)").format(
                    loss,
                    loss_events,
                )
            )
        self._refresh_control_states()

    def shutdown(self) -> None:
        self._shutting_down = True
        self._connect_cancel.set()
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
