"""Shared routing controls, infrastructure navigation and monitor shortcut."""

from dataclasses import replace
from unittest.mock import MagicMock

import pytest
import sounddevice as sd
from PyQt6.QtCore import QPoint
from PyQt6.QtWidgets import QLabel, QWidget

from src.core.audio_engine import AudioEngine
from src.core.localization import tr
from src.gui.main_window import MainWindow
from src.gui.widgets.routing import RoutingWidget
from src.gui.widgets.vst_dut import VstDutDialog


@pytest.fixture
def engine(monkeypatch):
    monkeypatch.setattr("src.core.monitor_output.sd", sd)
    engine = AudioEngine()
    engine.offline_mode = True
    info = {"name": "Test DAC", "hostapi": 0, "hostapi_name": "Test API", "max_output_channels": 2}
    engine.list_devices = MagicMock(return_value=[info])
    monkeypatch.setattr(sd, "query_devices", lambda *args: info)
    yield engine
    engine.monitor.enable(False)
    engine.vst_dut.close()


def test_monitor_widget_uses_common_route_and_waits_without_measurements(qtbot, engine):
    widget = RoutingWidget(engine)
    qtbot.addWidget(widget)
    widget.show()
    assert not widget.enabled.isEnabled()
    widget.source.setCurrentIndex(widget.source.findData("output_mix"))
    widget.source.activated.emit(widget.source.currentIndex())
    widget.device.setCurrentIndex(1)
    widget.device.activated.emit(1)
    assert widget.enabled.isEnabled()
    widget.enabled.click()
    assert engine.monitor.route.enabled
    assert engine.stream is None
    assert not engine.callbacks
    assert not widget.source.isEnabled()
    assert not widget.device.isEnabled()
    assert widget.status.text() == tr("Waiting")
    widget.volume.setValue(-12)
    assert engine.monitor.route.gain_db == -12
    widget.close()
    assert engine.monitor.route.enabled
    engine.set_monitor_enabled(False)
    widget.refresh()
    assert not widget.enabled.isChecked()


def test_route_list_and_shortcut_share_source_and_enabled_state(qtbot, engine):
    engine.vst_dut.path = "test.vst3"
    engine.configure_monitor(source="output_mix", device=0)
    page = RoutingWidget(engine)
    dialog = VstDutDialog(engine)
    qtbot.addWidget(page)
    qtbot.addWidget(dialog)
    dialog.monitor_button.setChecked(True)
    page.refresh()
    assert page.enabled.isChecked()
    assert page.source.currentData() == "output_mix"
    assert tr("Output mix") in dialog.monitor_button.toolTip()
    engine.set_monitor_enabled(False)
    dialog._refresh()
    assert not dialog.monitor_button.isChecked()


def test_unconfigured_shortcut_opens_routing_without_enabling(qtbot, engine):
    class Parent(QWidget):
        open_routing = MagicMock()

    parent = Parent()
    qtbot.addWidget(parent)
    dialog = VstDutDialog(engine, parent)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.monitor_button.setChecked(True)
    parent.open_routing.assert_called_once()
    assert not engine.monitor.route.enabled
    assert not dialog.isVisible()


def test_monitor_fault_display_and_invalid_configuration(qtbot, engine):
    engine.configure_monitor(source="output_mix", device=0)
    widget = RoutingWidget(engine)
    qtbot.addWidget(widget)
    engine.monitor.route = replace(engine.monitor.route, enabled=True)
    engine.monitor.error = "device disconnected"
    widget.refresh()
    assert widget.enabled.isChecked()
    assert "device disconnected" in widget.status.text()
    widget._configure(gain_db=9)
    assert engine.monitor.route.gain_db == -20
    assert widget.error.text()


def test_routing_navigation_and_legacy_output_menu_sync(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
    window.audio_engine.set_offline_mode(False)
    window.update_status()
    assert not window._routing_loaded
    assert window.sidebar.item(window._ROUTING_PAGE_INDEX).text() == tr("Routing")
    window.set_menu_only_mode(True)
    window.on_sidebar_item_double_clicked(window.sidebar.item(window._ROUTING_PAGE_INDEX))
    assert not window._menu_only_mode
    assert window._routing_loaded
    assert window.content_area.currentWidget() is window._routing_container
    widget = window.routing_widget
    widget.output.setCurrentIndex(widget.output.findData("loopback_mix"))
    widget.output.activated.emit(widget.output.currentIndex())
    window.update_status()
    assert window.output_dest_combo.currentData() == "loopback_mix"
    window.output_dest_combo.setCurrentIndex(window.output_dest_combo.findData("loopback_silent"))
    widget.refresh()
    assert widget.output.currentData() == "loopback_silent"
    assert window.audio_engine.loopback and window.audio_engine.mute_output
    assert window.modules == [None] * len(window._module_keys)
    assert window.sidebar.item(window._MODULE_PAGE_OFFSET).text() == tr(window._module_keys[0])


@pytest.mark.parametrize("language", ["de", "en", "es", "fr", "ja", "ko", "pt", "ru", "zh"])
def test_expanded_dut_and_error_layout_fits_all_languages(qtbot, engine, language):
    from src.core.localization import get_manager

    manager = get_manager()
    manager.load_language(language)
    try:
        engine.vst_dut.path = "example.vst3"
        engine.vst_dut.name = "Example plugin with a long descriptive name " * 4
        engine.vst_dut.return_routes = ("wet1", "dry2")
        engine.monitor.error = "Example driver error with diagnostic context " * 4
        engine.vst_dut.error = "Example plugin error with diagnostic context " * 4
        widget = RoutingWidget(engine)
        qtbot.addWidget(widget)
        widget.details_toggle.setChecked(True)
        widget.resize(1180, 690)
        widget.show()
        qtbot.waitUntil(widget.details.isVisible)
        assert widget.minimumSizeHint().width() <= 1180
        assert widget.minimumSizeHint().height() <= 690
        assert widget.connections.horizontalScrollBar().maximum() == 0
        for control in (widget.source, widget.device, widget.volume, widget.enabled, widget.status):
            assert control.isVisible()
            assert widget.rect().contains(control.mapTo(widget, QPoint(0, 0)))
            assert widget.rect().contains(control.mapTo(widget, control.rect().bottomRight()))
    finally:
        manager.load_language("en")


def test_monitor_branch_and_waiting_guidance_follow_shared_route(qtbot, engine):
    engine.configure_monitor(source="output_mix", device=0)
    widget = RoutingWidget(engine)
    qtbot.addWidget(widget)
    widget.show()
    widget.enabled.click()
    assert tr("Output mix") in widget.monitor_path.text()
    assert tr("Monitoring waits for a generator or measurement to start.") in widget.monitor_hint.text()
    assert tr("Turn monitoring off to change source or device.") in widget.monitor_hint.text()
    flow_labels = [label.text() for label in widget.connections.findChildren(QLabel)]
    assert tr("Measurement input") in flow_labels
    assert tr("Physical monitor") not in flow_labels
    widget.enabled.click()
    widget.source.setCurrentIndex(widget.source.findData("measurement_return"))
    widget.source.activated.emit(widget.source.currentIndex())
    assert tr("Measurement return") in widget.monitor_path.text()
    assert widget.monitor_hint.isHidden()


def test_backend_change_hides_virtual_path_and_explains_disabled_controls(qtbot, engine):
    engine.configure_monitor(source="output_mix", device=0)
    widget = RoutingWidget(engine)
    qtbot.addWidget(widget)
    widget.show()
    engine.offline_mode = False
    widget.refresh()
    assert widget.output_row.isVisible()
    assert widget.monitor_path.isHidden()
    assert not widget.volume.isEnabled()
    assert not widget.enabled.isEnabled()
    assert tr("Physical monitoring requires virtual audio.") in widget.status.text()
    assert widget.monitor_hint.isHidden()  # Do not repeat the status explanation.
    engine.offline_mode = True
    widget.refresh()
    assert widget.output_row.isHidden()
    assert widget.monitor_path.isVisible()
    assert widget.volume.isEnabled()
    assert widget.enabled.isEnabled()
