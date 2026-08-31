from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src.core.localization import tr
from src.core.windows_firewall import FirewallAssessment, FirewallOperationResult, FirewallState
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
    assert not widget.allow_output_check.isChecked()
    assert not widget.disconnect_button.isEnabled()
    assert not widget.stop_provider_button.isEnabled()
    assert widget.activity_label.text() == tr("Disconnected")
    assert widget.integrity_label.text() == tr("Disconnected")
    assert widget.tabs.tabText(0) == tr("Connect to another computer")
    assert widget.tabs.tabText(1) == tr("Share this computer's audio")
    assert widget.provider_button.text() == tr("Start sharing")
    assert widget.stop_provider_button.text() == tr("Stop sharing")

    widget.tabs.setCurrentIndex(1)
    assert widget.activity_details_label.text() == tr("Choose a listen address and start sharing.")


def test_remote_audio_widget_keeps_controls_stable_when_status_grows(qtbot):
    widget = RemoteAudioIOWidget(_engine(), _Config())
    qtbot.addWidget(widget)
    widget.resize(1180, 690)
    widget.tabs.setCurrentIndex(1)
    widget.show()
    qtbot.wait(10)
    initial_button_y = widget.provider_button.mapTo(widget, widget.provider_button.rect().topLeft()).y()
    initial_status_height = widget.activity_details_label.height()

    widget.provider = SimpleNamespace(
        running=True,
        status_snapshot=lambda: {
            "state": "listening",
            "bind_host": "0.0.0.0",
            "port": 41000,
            "client_address": None,
            "duplex": False,
        },
    )
    with patch.object(widget, "_lan_ipv4_addresses", return_value=("192.168.1.10",)):
        widget.refresh_status()
    widget.layout().activate()

    assert widget.activity_details_label.text().count("\n") == 3
    assert widget.activity_details_label.height() == initial_status_height
    assert widget.provider_button.mapTo(widget, widget.provider_button.rect().topLeft()).y() == initial_button_y


def test_remote_audio_widget_reserves_room_for_wrapped_provider_status(qtbot):
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
    )

    with patch.object(
        widget,
        "_lan_ipv4_addresses",
        return_value=("10.0.0.2", "192.168.1.10"),
    ):
        widget.refresh_status()
    widget.layout().activate()

    label = widget.activity_details_label
    assert label.height() >= label.heightForWidth(label.width())


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
    widget.client = SimpleNamespace(status_snapshot=lambda: snapshot, connected=True)

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
    }


def test_remote_audio_widget_keeps_client_and_provider_ports_in_sync(qtbot):
    widget = RemoteAudioIOWidget(_engine(), _Config())
    qtbot.addWidget(widget)

    widget.client_port_spin.setValue(43000)
    assert widget.provider_port_spin.value() == 43000

    widget.provider_port_spin.setValue(44000)
    assert widget.client_port_spin.value() == 44000


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


def test_remote_audio_widget_checks_firewall_only_when_provider_is_started(qtbot):
    widget = RemoteAudioIOWidget(_engine(), _Config())
    qtbot.addWidget(widget)
    manager = MagicMock()
    manager.supported = True
    manager.requires_permission.return_value = True
    manager.assess.return_value = FirewallAssessment(FirewallState.READY)
    widget.firewall_manager = manager

    def mark_started(_settings):
        widget._configuring_firewall = False
        widget._pending_provider_start = None

    with patch.object(widget, "_start_provider_now", side_effect=mark_started) as start_provider:
        assert manager.assess.call_count == 0
        widget.start_provider()
        qtbot.waitUntil(lambda: start_provider.call_count == 1)

    manager.assess.assert_called_once_with("0.0.0.0", 41000)
    assert not widget._configuring_firewall


def test_remote_audio_widget_does_not_start_after_uac_is_canceled(qtbot):
    widget = RemoteAudioIOWidget(_engine(), _Config())
    qtbot.addWidget(widget)
    widget._configuring_firewall = True
    widget._pending_provider_start = ("0.0.0.0", 41000, False)

    with (
        patch.object(widget, "_start_provider_now") as start_provider,
        patch("src.gui.widgets.remote_audio_io.QMessageBox.information") as information,
    ):
        widget._on_firewall_configured(
            (FirewallOperationResult(success=False, canceled=True), None),
        )

    start_provider.assert_not_called()
    information.assert_called_once()
    assert not widget._configuring_firewall
    assert widget._pending_provider_start is None


def test_remote_audio_widget_refuses_to_open_provider_on_public_network(qtbot):
    widget = RemoteAudioIOWidget(_engine(), _Config())
    qtbot.addWidget(widget)
    widget._configuring_firewall = True
    widget._pending_provider_start = ("0.0.0.0", 41000, False)

    with (
        patch.object(widget, "_start_provider_now") as start_provider,
        patch("src.gui.widgets.remote_audio_io.QMessageBox.warning") as warning,
    ):
        widget._on_firewall_assessed(FirewallAssessment(FirewallState.PUBLIC_NETWORK))

    start_provider.assert_not_called()
    warning.assert_called_once()
    assert widget._pending_provider_start is None


def test_remote_audio_widget_disables_network_controls_during_firewall_check(qtbot):
    widget = RemoteAudioIOWidget(_engine(), _Config())
    qtbot.addWidget(widget)
    widget._configuring_firewall = True

    widget.refresh_status()

    assert widget.activity_label.text() == tr("Checking Windows Firewall...")
    assert not widget.connect_button.isEnabled()
    assert not widget.provider_button.isEnabled()
    assert not widget.bind_edit.isEnabled()
