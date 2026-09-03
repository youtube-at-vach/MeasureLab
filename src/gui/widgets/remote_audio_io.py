"""Dedicated controls and integrity monitoring for network-backed audio I/O."""

from __future__ import annotations

import ipaddress
import logging
import sys
import threading

from PyQt6.QtCore import QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtNetwork import QAbstractSocket, QNetworkInterface
from PyQt6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QStyle,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from src.core.audio_engine import AudioEngine
from src.core.config_manager import ConfigManager
from src.core.localization import tr
from src.core.network_audio import DiscoveredProvider, NetworkAudioClient, NetworkAudioDiscovery, NetworkAudioProvider


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
        self._connecting_target_label = ""
        self._connect_cancel = threading.Event()
        self._shutting_down = False
        self._last_error: str | None = None
        self._integrity_source: object | None = None
        self._last_damage_events: int | None = None
        self.discovery: NetworkAudioDiscovery | None = None
        self._discovery_started = False
        self._discovery_signature: tuple[object, ...] | None = None
        self._signals = _RemoteAudioSignals(self)
        self._signals.connected.connect(self._on_client_connected)
        self._signals.failed.connect(self._on_client_failed)
        self._build_ui()
        self._load_config()
        self.discovery = self._new_discovery()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh_status)
        self._timer.start(500)
        self.refresh_status()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        heading = QLabel(tr("Remote Audio I/O"))
        heading_font = heading.font()
        heading_font.setBold(True)
        heading_font.setPointSizeF(heading_font.pointSizeF() * 1.35)
        heading.setFont(heading_font)
        layout.addWidget(heading)
        description = QLabel(tr("Use or share audio devices with another MeasureLab computer on a trusted LAN."))
        description.setWordWrap(True)
        layout.addWidget(description)

        status_panel = QFrame()
        status_panel.setFrameShape(QFrame.Shape.StyledPanel)
        status_layout = QGridLayout(status_panel)
        self.activity_icon = QLabel()
        self.activity_icon.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.activity_label = QLabel(tr("Disconnected"))
        activity_font = self.activity_label.font()
        activity_font.setBold(True)
        self.activity_label.setFont(activity_font)
        self.activity_label.setAccessibleName(tr("Status"))
        status_layout.addWidget(self.activity_icon, 0, 0)
        status_layout.addWidget(self.activity_label, 0, 1)
        status_layout.setColumnStretch(2, 1)

        self.integrity_panel = QWidget()
        integrity_layout = QHBoxLayout(self.integrity_panel)
        integrity_layout.setContentsMargins(0, 0, 0, 0)
        integrity_heading = QLabel(tr("Connection quality"))
        integrity_layout.addWidget(integrity_heading)
        self.integrity_icon = QLabel()
        self.integrity_icon.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        integrity_layout.addWidget(self.integrity_icon)
        self.integrity_label = QLabel(tr("Disconnected"))
        integrity_font = self.integrity_label.font()
        integrity_font.setBold(True)
        self.integrity_label.setFont(integrity_font)
        self.integrity_label.setAccessibleName(tr("Connection quality"))
        integrity_layout.addWidget(self.integrity_label)
        status_layout.addWidget(self.integrity_panel, 0, 3)

        self.activity_details_label = QLabel()
        self.activity_details_label.setWordWrap(True)
        status_layout.addWidget(self.activity_details_label, 1, 1, 1, 2)
        self.stats_label = QLabel()
        self.stats_label.setWordWrap(True)
        self.stats_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        status_layout.addWidget(self.stats_label, 1, 3)
        self.integrity_panel.hide()
        self.activity_details_label.hide()
        self.stats_label.hide()
        layout.addWidget(status_panel)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_client_tab(), tr("Connect to another computer"))
        self.tabs.addTab(self._build_provider_tab(), tr("Share this computer's audio"))
        self.tabs.currentChanged.connect(self.refresh_status)
        self.tabs.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(self.tabs, 1)

    def _build_client_tab(self) -> QWidget:
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setSpacing(10)

        discovery_group = QGroupBox(tr("Available MeasureLab computers"))
        discovery_layout = QVBoxLayout(discovery_group)
        self.discovery_status_label = QLabel(tr("Searching this LAN..."))
        self.discovery_status_label.setWordWrap(True)
        discovery_layout.addWidget(self.discovery_status_label)
        self.discovery_list = QListWidget()
        self.discovery_list.setAccessibleName(tr("Available MeasureLab computers"))
        # Provider entries use two text lines. Query the active style instead of
        # assuming a pixel height so two entries fit on every platform and font.
        sample_item = QListWidgetItem("\n")
        self.discovery_list.addItem(sample_item)
        discovery_row_height = max(1, self.discovery_list.sizeHintForRow(0))
        self.discovery_list.takeItem(0)
        discovery_viewport_height = discovery_row_height * 2
        self.discovery_list.setFixedHeight(discovery_viewport_height + self.discovery_list.frameWidth() * 2)
        self.discovery_list.currentItemChanged.connect(self._on_discovery_selection_changed)
        self.discovery_list.itemDoubleClicked.connect(lambda _item: self.connect_selected_provider())
        discovery_layout.addWidget(self.discovery_list)
        page_layout.addWidget(discovery_group)

        buttons_layout = QHBoxLayout()
        self.discovered_connect_button = QPushButton(tr("Connect selected"))
        self.discovered_connect_button.clicked.connect(self.connect_selected_provider)
        self.disconnect_button = QPushButton(tr("Disconnect"))
        self.disconnect_button.clicked.connect(self.disconnect_client)
        buttons_layout.addWidget(self.discovered_connect_button)
        buttons_layout.addWidget(self.disconnect_button)
        buttons_layout.addStretch()
        self.client_options_button = QToolButton()
        self.client_options_button.setText(tr("Advanced"))
        self.client_options_button.setCheckable(True)
        self.client_options_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.client_options_button.setArrowType(Qt.ArrowType.RightArrow)
        buttons_layout.addWidget(self.client_options_button)
        page_layout.addLayout(buttons_layout)

        self.client_options_panel = QFrame()
        self.client_options_panel.setFrameShape(QFrame.Shape.StyledPanel)
        form = QFormLayout(self.client_options_panel)
        self.host_edit = QLineEdit()
        self.host_edit.setPlaceholderText("192.168.1.10")
        self.host_edit.setAccessibleName(tr("Remote host:"))
        host_label = QLabel(tr("Remote host:"))
        host_label.setBuddy(self.host_edit)
        form.addRow(host_label, self.host_edit)
        self.client_port_spin = QSpinBox()
        self.client_port_spin.setRange(1, 65535)
        self.client_port_spin.valueChanged.connect(self._sync_provider_port)
        self.client_port_spin.setAccessibleName(tr("UDP port:"))
        port_label = QLabel(tr("UDP port:"))
        port_label.setBuddy(self.client_port_spin)
        form.addRow(port_label, self.client_port_spin)
        self.jitter_spin = QSpinBox()
        self.jitter_spin.setRange(20, 2000)
        self.jitter_spin.setSuffix(" ms")
        self.jitter_spin.setAccessibleName(tr("Fixed network buffer:"))
        buffer_label = QLabel(tr("Fixed network buffer:"))
        buffer_label.setBuddy(self.jitter_spin)
        form.addRow(buffer_label, self.jitter_spin)
        self.duplex_check = QCheckBox(tr("Request remote output (duplex)"))
        form.addRow(self.duplex_check)
        self.retransmission_check = QCheckBox(tr("Recover lost network packets"))
        self.retransmission_check.setToolTip(tr("Request time-limited retransmission when both computers support it."))
        form.addRow(self.retransmission_check)
        self.connect_button = QPushButton(tr("Connect by address"))
        self.connect_button.clicked.connect(self.connect_client)
        form.addRow(self.connect_button)
        self.remote_details_label = QLabel(tr("No remote provider connected."))
        self.remote_details_label.setWordWrap(True)
        self.remote_details_label.setAccessibleName(tr("Details"))
        form.addRow(QLabel(tr("Details")), self.remote_details_label)
        self.client_options_button.toggled.connect(
            lambda visible: self._set_options_visible(
                self.client_options_button,
                self.client_options_panel,
                visible,
            )
        )
        self.client_options_panel.hide()
        page_layout.addWidget(self.client_options_panel)
        page_layout.addStretch(1)
        return page

    def _build_provider_tab(self) -> QWidget:
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setSpacing(10)

        self.windows_firewall_notice = QLabel()
        self.windows_firewall_notice.setWordWrap(True)
        self.windows_firewall_notice.setVisible(sys.platform == "win32")
        page_layout.addWidget(self.windows_firewall_notice)

        self.allow_output_check = QCheckBox(tr("Allow remote playback"))
        self.allow_output_check.setChecked(False)
        self.allow_output_check.setToolTip(tr("Keep disabled unless the remote computer is trusted."))
        self.allow_output_check.toggled.connect(self._on_allow_output_changed)
        page_layout.addWidget(self.allow_output_check)

        buttons_layout = QHBoxLayout()
        self.provider_button = QPushButton(tr("Start sharing"))
        self.stop_provider_button = QPushButton(tr("Stop sharing"))
        self.provider_button.clicked.connect(self.start_provider)
        self.stop_provider_button.clicked.connect(self.stop_provider)
        buttons_layout.addWidget(self.provider_button)
        buttons_layout.addWidget(self.stop_provider_button)
        buttons_layout.addStretch()
        self.provider_options_button = QToolButton()
        self.provider_options_button.setText(tr("Advanced"))
        self.provider_options_button.setCheckable(True)
        self.provider_options_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.provider_options_button.setArrowType(Qt.ArrowType.RightArrow)
        buttons_layout.addWidget(self.provider_options_button)
        page_layout.addLayout(buttons_layout)

        self.provider_options_panel = QFrame()
        self.provider_options_panel.setFrameShape(QFrame.Shape.StyledPanel)
        form = QFormLayout(self.provider_options_panel)
        self.bind_edit = QLineEdit()
        self.bind_edit.setPlaceholderText("0.0.0.0")
        self.bind_edit.setAccessibleName(tr("Listen address:"))
        bind_label = QLabel(tr("Listen address:"))
        bind_label.setBuddy(self.bind_edit)
        form.addRow(bind_label, self.bind_edit)
        self.provider_port_spin = QSpinBox()
        self.provider_port_spin.setRange(1, 65535)
        self.provider_port_spin.valueChanged.connect(self._sync_client_port)
        self.provider_port_spin.valueChanged.connect(self._update_windows_firewall_notice)
        self.provider_port_spin.setAccessibleName(tr("UDP port:"))
        port_label = QLabel(tr("UDP port:"))
        port_label.setBuddy(self.provider_port_spin)
        form.addRow(port_label, self.provider_port_spin)
        self.discoverable_check = QCheckBox(tr("Allow automatic discovery"))
        self.discoverable_check.setToolTip(tr("Other MeasureLab computers can find this provider automatically."))
        self.discoverable_check.toggled.connect(self._on_discoverable_changed)
        form.addRow(self.discoverable_check)
        self.provider_details_label = QLabel(tr("Provider is stopped."))
        self.provider_details_label.setWordWrap(True)
        self.provider_details_label.setAccessibleName(tr("Details"))
        form.addRow(QLabel(tr("Details")), self.provider_details_label)
        self.provider_options_button.toggled.connect(
            lambda visible: self._set_options_visible(
                self.provider_options_button,
                self.provider_options_panel,
                visible,
            )
        )
        self.provider_options_panel.hide()
        page_layout.addWidget(self.provider_options_panel)
        page_layout.addStretch(1)
        self._update_windows_firewall_notice(self.provider_port_spin.value())
        return page

    def _set_status_icon(self, label: QLabel, icon: QStyle.StandardPixmap) -> None:
        label.setPixmap(self.style().standardIcon(icon).pixmap(18, 18))

    @staticmethod
    def _set_options_visible(button: QToolButton, panel: QWidget, visible: bool) -> None:
        panel.setVisible(visible)
        button.setArrowType(Qt.ArrowType.DownArrow if visible else Qt.ArrowType.RightArrow)

    @staticmethod
    def _set_optional_text(label: QLabel, text: str) -> None:
        label.setText(text)
        label.setVisible(bool(text))

    def _sync_provider_port(self, value: int) -> None:
        if self.provider_port_spin.value() != value:
            self.provider_port_spin.setValue(value)
        discovery = getattr(self, "discovery", None)
        if discovery is not None and discovery.port != value:
            self._restart_discovery()

    def _sync_client_port(self, value: int) -> None:
        if self.client_port_spin.value() != value:
            self.client_port_spin.setValue(value)

    def _update_windows_firewall_notice(self, port: int) -> None:
        self.windows_firewall_notice.setText(
            "⚠ "
            + tr(
                "On Windows, allow inbound UDP connections to port {0} in Windows Defender Firewall before sharing."
            ).format(port)
        )

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

    @staticmethod
    def _lan_ipv4_broadcast_addresses() -> tuple[str, ...]:
        """Return directed IPv4 broadcast targets for active discovery."""
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
                broadcast = entry.broadcast().toString()
                if broadcast and broadcast != "0.0.0.0":
                    addresses.add(broadcast)
        return tuple(sorted(addresses, key=ipaddress.IPv4Address)) or ("255.255.255.255",)

    def _new_discovery(self) -> NetworkAudioDiscovery:
        return NetworkAudioDiscovery(
            self.client_port_spin.value(),
            broadcast_addresses=self._lan_ipv4_broadcast_addresses(),
        )

    def _start_discovery(self) -> None:
        if self._discovery_started or self._shutting_down:
            return
        self._discovery_started = True
        try:
            if self.discovery is not None:
                self.discovery.start()
        except (OSError, ValueError) as exc:
            self.logger.warning("Remote audio discovery could not start: %s", exc)

    def _restart_discovery(self) -> None:
        old = self.discovery
        if old is not None:
            old.stop()
        self.discovery = self._new_discovery()
        self._discovery_signature = None
        if self._discovery_started and not self._shutting_down:
            try:
                self.discovery.start()
            except (OSError, ValueError) as exc:
                self.logger.warning("Remote audio discovery could not restart: %s", exc)

    def _refresh_discovery_list(self) -> None:
        discovery = self.discovery
        providers = discovery.snapshot() if discovery is not None else ()
        signature: tuple[object, ...] = tuple(
            (
                provider.instance_id,
                provider.host,
                provider.port,
                provider.provider_name,
                provider.sample_rate,
                provider.input_channels,
                provider.output_channels,
                provider.busy,
            )
            for provider in providers
        )
        if signature == self._discovery_signature:
            return
        current = self.discovery_list.currentItem()
        selected_key = None
        if current is not None:
            selected = current.data(Qt.ItemDataRole.UserRole)
            if isinstance(selected, DiscoveredProvider):
                selected_key = selected.instance_id
        self.discovery_list.clear()
        selected_row = -1
        for row, provider in enumerate(providers):
            text = tr("{0}\n{1} Hz, {2} input / {3} output").format(
                provider.provider_name,
                provider.sample_rate,
                provider.input_channels,
                provider.output_channels,
            )
            if provider.busy:
                text += " — " + tr("busy")
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, provider)
            item.setToolTip(
                tr("Input: {0}\nOutput: {1}").format(
                    provider.input_device_name,
                    provider.output_device_name,
                )
            )
            self.discovery_list.addItem(item)
            if selected_key == provider.instance_id:
                selected_row = row
        if selected_row >= 0:
            self.discovery_list.setCurrentRow(selected_row)
        self.discovery_status_label.setText(
            tr("No available MeasureLab computers found.") if not providers else tr("Select a computer to connect.")
        )
        self._discovery_signature = signature

    def _on_discovery_selection_changed(self, _current=None, _previous=None) -> None:
        self._refresh_control_states()

    def showEvent(self, event) -> None:
        self._start_discovery()
        super().showEvent(event)

    def _load_config(self) -> None:
        config = self.config_manager.get_network_audio_config()
        self.host_edit.setText(str(config.get("host", "")))
        port = int(config.get("port", 40100))
        self.client_port_spin.setValue(port)
        self.provider_port_spin.setValue(port)
        self.jitter_spin.setValue(int(config.get("jitter_ms", 100)))
        self.duplex_check.setChecked(bool(config.get("duplex", True)))
        self.retransmission_check.setChecked(bool(config.get("retransmission", True)))
        self.bind_edit.setText(str(config.get("bind_host", "0.0.0.0")))
        self.discoverable_check.setChecked(bool(config.get("discoverable", True)))

    def _save_config(self) -> None:
        self.config_manager.set_network_audio_config(
            {
                "host": self.host_edit.text().strip(),
                "port": self.client_port_spin.value(),
                "jitter_ms": self.jitter_spin.value(),
                "duplex": self.duplex_check.isChecked(),
                "retransmission": self.retransmission_check.isChecked(),
                "bind_host": self.bind_edit.text().strip() or "0.0.0.0",
                "discoverable": self.discoverable_check.isChecked(),
            }
        )

    def connect_client(self) -> None:
        host = self.host_edit.text().strip()
        if not host:
            QMessageBox.warning(self, tr("Remote Audio I/O"), tr("Enter a remote host name or IP address."))
            return
        self._begin_connect(host, self.client_port_spin.value(), f"{host}:{self.client_port_spin.value()}")

    def connect_selected_provider(self) -> None:
        item = self.discovery_list.currentItem()
        provider = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        if not isinstance(provider, DiscoveredProvider) or provider.busy:
            return
        self._begin_connect(provider.host, provider.port, provider.provider_name)

    def _begin_connect(self, host: str, port: int, target_label: str) -> None:
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
        self._save_config()
        self._last_error = None
        self._connecting = True
        self._connecting_target_label = str(target_label)
        self._connect_cancel.clear()
        jitter_ms = self.jitter_spin.value()
        duplex = self.duplex_check.isChecked()
        retransmission = self.retransmission_check.isChecked()
        self.refresh_status()

        def worker() -> None:
            client = NetworkAudioClient(
                host,
                port,
                jitter_ms=jitter_ms,
                duplex=duplex,
                retransmission=retransmission,
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
        self._connecting_target_label = ""
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
        self._connecting_target_label = ""
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
            self._connecting_target_label = ""
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
            discoverable=self.discoverable_check.isChecked(),
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
        self._restart_discovery()
        self._last_error = None
        self.provider_details_label.setText(tr("Provider is stopped."))
        self.refresh_status()

    def _on_allow_output_changed(self, enabled: bool) -> None:
        if self.provider is not None:
            self.provider.set_allow_output(enabled)

    def _on_discoverable_changed(self, enabled: bool) -> None:
        if self.provider is not None:
            self.provider.set_discoverable(enabled)
            self._save_config()

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
        self.retransmission_check.setEnabled(client_settings_enabled)
        self.discovery_list.setEnabled(client_settings_enabled)

        self.connect_button.setEnabled(client_settings_enabled and not measurements_active)
        selected_item = self.discovery_list.currentItem()
        selected_provider = selected_item.data(Qt.ItemDataRole.UserRole) if selected_item is not None else None
        self.discovered_connect_button.setEnabled(
            client_settings_enabled
            and not measurements_active
            and isinstance(selected_provider, DiscoveredProvider)
            and not selected_provider.busy
        )
        self.disconnect_button.setText(tr("Cancel") if self._connecting else tr("Disconnect"))
        self.disconnect_button.setEnabled(self._connecting or (client_active and not measurements_active))
        if measurements_active and client_active:
            self.disconnect_button.setToolTip(tr("Stop active audio measurements before disconnecting remote audio."))
        else:
            self.disconnect_button.setToolTip("")

        provider_settings_enabled = not provider_active and not client_active and not self._connecting
        self.bind_edit.setEnabled(provider_settings_enabled)
        self.provider_port_spin.setEnabled(provider_settings_enabled)
        self.discoverable_check.setEnabled(provider_settings_enabled or provider_active)
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
        self._refresh_discovery_list()
        self._set_optional_text(self.activity_details_label, "")
        self._set_optional_text(self.stats_label, "")
        self.integrity_panel.hide()
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
                self._set_optional_text(
                    self.activity_details_label, tr("Connection error: {0}. Disconnect and reconnect.").format(error)
                )
                self._set_status_icon(self.activity_icon, QStyle.StandardPixmap.SP_MessageBoxCritical)
            else:
                self.activity_label.setText(tr("Use Remote I/O"))
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
                self._set_optional_text(
                    self.activity_details_label,
                    tr("Check the settings and try again. Details: {0}").format(error),
                )
                self._set_status_icon(self.activity_icon, QStyle.StandardPixmap.SP_MessageBoxCritical)
            elif snapshot.get("client_address"):
                self.activity_label.setText(tr("Provide Local I/O"))
                self._set_status_icon(self.activity_icon, QStyle.StandardPixmap.SP_DialogApplyButton)
            else:
                self.activity_label.setText(tr("Provide Local I/O"))
                self._set_status_icon(self.activity_icon, QStyle.StandardPixmap.SP_MessageBoxInformation)

        if snapshot is None:
            if self._connecting:
                self.activity_label.setText(tr("Connecting..."))
                self._set_optional_text(self.activity_details_label, self._connecting_target_label)
                self._set_status_icon(self.activity_icon, QStyle.StandardPixmap.SP_BrowserReload)
            elif self._last_error:
                self.activity_label.setText(tr("Connection failed"))
                self._set_optional_text(
                    self.activity_details_label,
                    tr("Check the settings and try again. Details: {0}").format(self._last_error),
                )
                self._set_status_icon(self.activity_icon, QStyle.StandardPixmap.SP_MessageBoxCritical)
            else:
                self.activity_label.setText(tr("Disconnected"))
                self._set_status_icon(self.activity_icon, QStyle.StandardPixmap.SP_MessageBoxInformation)
            self.integrity_label.setText(tr("Disconnected"))
            self._set_status_icon(self.integrity_icon, QStyle.StandardPixmap.SP_MessageBoxInformation)
            self._integrity_source = None
            self._last_damage_events = None
            self._refresh_control_states()
            return

        self.integrity_panel.show()
        if source is self.provider and snapshot.get("state") != "error" and not snapshot.get("client_address"):
            self.integrity_label.setText(tr("waiting"))
            self._set_status_icon(self.integrity_icon, QStyle.StandardPixmap.SP_MessageBoxInformation)
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
        if state != "error":
            recovered = int(snapshot.get("recovered_frames", 0) or 0)
            retransmitted = int(snapshot.get("retransmitted_packets", 0) or 0)
            self._set_optional_text(
                self.stats_label,
                (
                    tr("Dropped: {0} frames ({1} events); recovered: {2} frames; retransmitted: {3} packets").format(
                        loss,
                        loss_events,
                        recovered,
                        retransmitted,
                    )
                    if snapshot.get("retransmission_active")
                    else tr("Dropped: {0} frames ({1} events)").format(loss, loss_events)
                ),
            )
        self._refresh_control_states()

    def shutdown(self) -> None:
        self._shutting_down = True
        self._connect_cancel.set()
        self._timer.stop()
        if self.discovery is not None:
            self.discovery.stop()
        self._discovery_started = False
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
