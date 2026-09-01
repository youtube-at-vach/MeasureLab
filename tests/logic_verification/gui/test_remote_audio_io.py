import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from PyQt6.QtCore import Qt

from src.core.localization import tr
from src.core.network_audio import DiscoveredProvider
from src.gui.widgets.remote_audio_io import RemoteAudioIOWidget


class _Config:
    def __init__(self):
        self.saved = None

    def get_network_audio_config(self):
        return {
            "host": "192.168.1.20",
            "port": 41000,
            "jitter_ms": 120,
            "duplex": True,
            "bind_host": "0.0.0.0",
            "discoverable": True,
        }

    def set_network_audio_config(self, value):
        self.saved = value


def _engine():
    engine = MagicMock()
    engine.network_mode = False
    engine.get_status.return_value = {"active_clients": 0}
    return engine


def test_remote_audio_widget_loads_endpoint_and_starts_safe(qtbot):
    config = _Config()
    widget = RemoteAudioIOWidget(_engine(), config)
    qtbot.addWidget(widget)

    assert widget.host_edit.text() == "192.168.1.20"
    assert widget.client_port_spin.value() == 41000
    assert widget.jitter_spin.value() == 120
    assert widget.duplex_check.isChecked()
    assert widget.discoverable_check.isChecked()
    assert not widget.allow_output_check.isChecked()
    assert not widget.disconnect_button.isEnabled()
    assert not widget.stop_provider_button.isEnabled()
    assert widget.activity_label.text() == tr("Disconnected")
    assert widget.integrity_label.text() == tr("Disconnected")
    assert widget.tabs.tabText(0) == tr("Connect to another computer")
    assert widget.tabs.tabText(1) == tr("Share this computer's audio")
    assert widget.provider_button.text() == tr("Start sharing")
    assert widget.stop_provider_button.text() == tr("Stop sharing")
    assert widget.client_options_panel.isHidden()
    assert widget.provider_options_panel.isHidden()
    assert widget.integrity_panel.isHidden()
    assert widget.activity_details_label.isHidden()

    widget.tabs.setCurrentIndex(1)
    assert widget.activity_details_label.text() == ""


def test_remote_audio_widget_reveals_advanced_settings_on_request(qtbot):
    widget = RemoteAudioIOWidget(_engine(), _Config())
    qtbot.addWidget(widget)
    widget.resize(1180, 690)
    widget.show()

    assert widget.client_options_panel.isHidden()
    assert not widget.host_edit.isVisible()
    widget.client_options_button.click()
    expanded_tab_geometry = widget.tabs.geometry()
    expanded_panel_geometry = widget.client_options_panel.geometry()
    assert widget.client_options_button.arrowType() == Qt.ArrowType.DownArrow
    assert widget.client_options_panel.isVisible()
    assert widget.host_edit.isVisible()
    qtbot.wait(1)
    assert widget.tabs.geometry() == expanded_tab_geometry
    assert widget.client_options_panel.geometry() == expanded_panel_geometry

    widget.tabs.setCurrentIndex(1)
    assert widget.provider_options_panel.isHidden()
    assert not widget.bind_edit.isVisible()
    widget.provider_options_button.click()
    assert widget.provider_options_button.arrowType() == Qt.ArrowType.DownArrow
    assert widget.provider_options_panel.isVisible()
    assert widget.bind_edit.isVisible()


def test_remote_audio_widget_discovery_list_shows_two_computer_rows(qtbot):
    widget = RemoteAudioIOWidget(_engine(), _Config())
    qtbot.addWidget(widget)
    widget.discovery_list.addItems(
        [
            "Computer 1\n48000 Hz, 2 input / 2 output",
            "Computer 2\n48000 Hz, 2 input / 2 output",
            "Computer 3\n48000 Hz, 2 input / 2 output",
        ]
    )
    widget.resize(1180, 690)
    widget.show()
    qtbot.wait(1)

    row_height = widget.discovery_list.sizeHintForRow(0)
    assert widget.discovery_list.viewport().height() == row_height * 2


def test_remote_audio_widget_keeps_provider_details_out_of_primary_status(qtbot):
    widget = RemoteAudioIOWidget(_engine(), _Config())
    qtbot.addWidget(widget)
    widget.resize(1180, 690)
    widget.tabs.setCurrentIndex(1)
    widget.show()
    qtbot.wait(10)
    initial_button_y = widget.provider_button.mapTo(widget, widget.provider_button.rect().topLeft()).y()

    widget.provider = SimpleNamespace(
        running=True,
        status_snapshot=lambda: {
            "state": "listening",
            "bind_host": "0.0.0.0",
            "port": 41000,
            "client_address": None,
            "duplex": False,
        },
        stop=lambda: None,
    )
    with patch.object(widget, "_lan_ipv4_addresses", return_value=("192.168.1.10",)):
        widget.refresh_status()
    widget.layout().activate()

    assert widget.provider_details_label.text().count("\n") == 3
    assert widget.activity_details_label.isHidden()
    assert widget.provider_options_panel.isHidden()
    assert widget.provider_button.mapTo(widget, widget.provider_button.rect().topLeft()).y() == initial_button_y


def test_remote_audio_widget_shows_provider_endpoints_in_advanced_details(qtbot):
    widget = RemoteAudioIOWidget(_engine(), _Config())
    qtbot.addWidget(widget)
    widget.resize(700, 690)
    widget.tabs.setCurrentIndex(1)
    widget.show()
    widget.provider = SimpleNamespace(
        running=True,
        status_snapshot=lambda: {
            "state": "listening",
            "bind_host": "0.0.0.0",
            "port": 41000,
            "client_address": None,
            "duplex": False,
        },
        stop=lambda: None,
    )

    with patch.object(
        widget,
        "_lan_ipv4_addresses",
        return_value=("10.0.0.2", "192.168.1.10"),
    ):
        widget.refresh_status()
    widget.layout().activate()

    assert widget.provider_options_panel.isHidden()
    assert "10.0.0.2:41000" in widget.provider_details_label.text()
    assert "192.168.1.10:41000" in widget.provider_details_label.text()
    widget.provider_options_button.click()
    assert widget.provider_options_panel.isVisible()


def test_remote_audio_widget_displays_whether_integrity_loss_is_still_increasing(qtbot):
    widget = RemoteAudioIOWidget(_engine(), _Config())
    qtbot.addWidget(widget)
    snapshot = {
        "state": "streaming",
        "rx_packets": 10,
        "tx_packets": 9,
        "lost_packets": 0,
        "lost_frames": 0,
        "late_packets": 1,
        "duplicate_packets": 0,
        "corrupt_packets": 0,
        "buffered_frames": 512,
        "local_queue_overflows": 0,
    }
    widget.client = SimpleNamespace(status_snapshot=lambda: snapshot, connected=True, close=lambda: None)

    widget.refresh_status()
    assert widget.integrity_label.text() == tr("No data loss ({0})").format("streaming")
    assert not widget.host_edit.isEnabled()
    assert not widget.provider_button.isEnabled()
    assert widget.disconnect_button.isEnabled()

    snapshot["lost_packets"] = 1
    snapshot["lost_frames"] = 128
    widget.refresh_status()
    assert widget.integrity_label.text() == tr("Data loss is increasing")
    assert "128" in widget.stats_label.text()

    widget.refresh_status()
    assert widget.integrity_label.text() == tr("Data loss is not increasing")
    assert "128" in widget.stats_label.text()
    assert not hasattr(widget, "incident_table")


def test_remote_audio_widget_saves_preferences(qtbot):
    config = _Config()
    widget = RemoteAudioIOWidget(_engine(), config)
    qtbot.addWidget(widget)
    widget.host_edit.setText("remote-room.local")
    widget.client_port_spin.setValue(42000)
    widget.jitter_spin.setValue(200)
    widget.duplex_check.setChecked(False)

    widget._save_config()

    assert config.saved == {
        "host": "remote-room.local",
        "port": 42000,
        "jitter_ms": 200,
        "duplex": False,
        "bind_host": "0.0.0.0",
        "discoverable": True,
    }


def test_remote_audio_widget_keeps_client_and_provider_ports_in_sync(qtbot):
    widget = RemoteAudioIOWidget(_engine(), _Config())
    qtbot.addWidget(widget)

    widget.client_port_spin.setValue(43000)
    assert widget.provider_port_spin.value() == 43000

    widget.provider_port_spin.setValue(44000)
    assert widget.client_port_spin.value() == 44000


def test_remote_audio_widget_connects_to_discovered_provider_without_showing_address(qtbot):
    widget = RemoteAudioIOWidget(_engine(), _Config())
    qtbot.addWidget(widget)
    found = DiscoveredProvider(
        instance_id="provider-1",
        host="192.168.1.25",
        port=41000,
        provider_name="Studio MeasureLab",
        input_device_name="USB Input",
        output_device_name="USB Output",
        sample_rate=48000,
        block_size=256,
        input_channels=2,
        output_channels=2,
        duplex=True,
        busy=False,
        last_seen=time.monotonic(),
    )
    widget.discovery = SimpleNamespace(
        port=41000,
        snapshot=lambda: (found,),
        stop=lambda: None,
    )
    widget._discovery_signature = None

    widget.refresh_status()

    assert widget.discovery_list.count() == 1
    item = widget.discovery_list.item(0)
    assert "Studio MeasureLab" in item.text()
    assert "192.168.1.25" not in item.text()
    assert "41000" not in item.text()
    widget.discovery_list.setCurrentRow(0)
    with patch.object(widget, "_begin_connect") as begin_connect:
        widget.connect_selected_provider()
    begin_connect.assert_called_once_with("192.168.1.25", 41000, "Studio MeasureLab")


def test_remote_audio_widget_shows_current_firewall_port_on_windows(qtbot):
    with patch("src.gui.widgets.remote_audio_io.sys.platform", "win32"):
        widget = RemoteAudioIOWidget(_engine(), _Config())
    qtbot.addWidget(widget)

    assert not widget.windows_firewall_notice.isHidden()
    assert "41000" in widget.windows_firewall_notice.text()
    assert "Windows Defender Firewall" in widget.windows_firewall_notice.text()

    widget.provider_port_spin.setValue(42000)

    assert "42000" in widget.windows_firewall_notice.text()
    assert "41000" not in widget.windows_firewall_notice.text()


def test_remote_audio_widget_hides_firewall_notice_outside_windows(qtbot):
    with patch("src.gui.widgets.remote_audio_io.sys.platform", "linux"):
        widget = RemoteAudioIOWidget(_engine(), _Config())
    qtbot.addWidget(widget)

    assert widget.windows_firewall_notice.isHidden()


def test_remote_audio_widget_provider_waiting_is_not_reported_as_healthy_connection(qtbot):
    widget = RemoteAudioIOWidget(_engine(), _Config())
    qtbot.addWidget(widget)
    widget.provider = SimpleNamespace(
        running=True,
        status_snapshot=lambda: {
            "state": "listening",
            "bind_host": "0.0.0.0",
            "port": 41000,
            "client_address": None,
            "duplex": False,
        },
        stop=lambda: None,
    )

    with patch.object(
        widget,
        "_lan_ipv4_addresses",
        return_value=("10.0.0.2", "192.168.1.10"),
    ):
        widget.refresh_status()

    assert widget.activity_label.text() == tr("Provide Local I/O")
    assert widget.integrity_label.text() == tr("waiting")
    assert "0.0.0.0:41000" in widget.provider_details_label.text()
    assert "10.0.0.2:41000, 192.168.1.10:41000" in widget.provider_details_label.text()
    assert not widget.provider_port_spin.isEnabled()
    assert widget.stop_provider_button.isEnabled()


def test_remote_audio_widget_reports_when_no_lan_address_is_available(qtbot):
    widget = RemoteAudioIOWidget(_engine(), _Config())
    qtbot.addWidget(widget)
    widget.provider = SimpleNamespace(
        running=True,
        status_snapshot=lambda: {
            "state": "listening",
            "bind_host": "0.0.0.0",
            "port": 41000,
            "client_address": None,
            "duplex": False,
        },
        stop=lambda: None,
    )

    with patch.object(widget, "_lan_ipv4_addresses", return_value=()):
        widget.refresh_status()

    assert tr("Not available") in widget.provider_details_label.text()


def test_remote_audio_widget_can_cancel_connection_attempt(qtbot):
    widget = RemoteAudioIOWidget(_engine(), _Config())
    qtbot.addWidget(widget)
    widget._connecting = True
    widget._connect_cancel.clear()

    widget.refresh_status()

    assert widget.activity_label.text() == tr("Connecting...")
    assert widget.disconnect_button.text() == tr("Cancel")
    assert widget.disconnect_button.isEnabled()
    assert not widget.host_edit.isEnabled()

    widget.disconnect_client()

    assert widget._connect_cancel.is_set()
    assert not widget._connecting
    assert widget.activity_label.text() == tr("Disconnected")


def test_remote_audio_widget_ignores_connection_that_finishes_after_cancel(qtbot):
    engine = _engine()
    widget = RemoteAudioIOWidget(engine, _Config())
    qtbot.addWidget(widget)
    client = MagicMock()
    widget._connect_cancel.set()

    widget._on_client_connected(client)

    client.close.assert_called_once_with()
    engine.configure_network_client.assert_not_called()
    assert widget.client is None
