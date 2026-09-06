import os
from pathlib import Path
import threading
from unittest.mock import MagicMock

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialogButtonBox, QDoubleSpinBox, QSlider, QTabWidget

from src.core.audio_engine import AudioEngine
from src.core.localization import get_manager
from src.core.vst_discovery import VstScanResult, discover_vst3
from src.gui.widgets.vst_dut import VstDutDialog


@pytest.fixture(autouse=True)
def isolated_discovery(monkeypatch):
    monkeypatch.setattr("src.gui.widgets.vst_dut.discover_vst3", lambda **kwargs: VstScanResult())


@pytest.mark.parametrize("language", ["en", "ja", "de", "es", "fr", "ko", "pt", "ru", "zh"])
def test_dut_controls_and_size_in_all_languages(qtbot, language):
    manager = get_manager()
    manager.load_language(language)
    engine = AudioEngine()
    engine.offline_mode = True
    dialog = VstDutDialog(engine)
    qtbot.addWidget(dialog)
    qtbot.waitUntil(lambda: dialog.scanner is None)
    try:
        dialog.show()
        dialog.advanced.setChecked(True)
        assert dialog.minimumSizeHint().width() <= 1180
        assert dialog.minimumSizeHint().height() <= 690
        dialog.routing_toggle.setChecked(True)
        assert dialog.minimumSizeHint().width() <= 1180
        assert dialog.minimumSizeHint().height() <= 690
        assert dialog.controls.isEnabled()
        dialog.channels.setCurrentIndex(0)
        assert engine.vst_dut.input_routes == (0,)
        assert engine.vst_dut.return_routes == ("wet1", "wet1")
        assert not dialog.inputs[1].isEnabled()
        dialog.returns[1].setCurrentIndex(2)
        assert engine.vst_dut.return_routes == ("wet1", "dry1")
        engine.callbacks[1] = MagicMock()
        dialog._refresh()
        assert not dialog.controls.isEnabled()
        engine.callbacks.clear()
        engine.network_mode = True
        dialog._refresh()
        assert not dialog.controls.isEnabled()
    finally:
        engine.vst_dut.close()
        manager.load_language("en")


def test_launcher_uses_only_native_editor_and_collapses_advanced_controls(qtbot):
    engine = AudioEngine()
    engine.offline_mode = True
    dialog = VstDutDialog(engine)
    qtbot.addWidget(dialog)
    try:
        dialog.show()
        assert not dialog.manual.isVisible()
        assert not dialog.routing.isVisible()
        assert not dialog.findChildren(QDoubleSpinBox)
        assert not dialog.findChildren(QSlider)
        assert not dialog.findChildren(QTabWidget)
        assert not dialog.editor_button.isEnabled()
        dialog.advanced.setChecked(True)
        dialog.routing_toggle.setChecked(True)
        assert dialog.path.isVisible()
        assert dialog.plugin_name.isVisible()
        assert dialog.routing.isVisible()
    finally:
        engine.vst_dut.close()


def test_empty_controls_and_keyboard_do_not_load_or_apply(qtbot):
    engine = AudioEngine()
    engine.offline_mode = True
    engine.vst_dut.load = MagicMock()
    engine.vst_dut.set_parameter = MagicMock()
    dialog = VstDutDialog(engine)
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitUntil(lambda: dialog.scanner is None)
    assert not dialog.load_button.isEnabled()
    assert not dialog.editor_button.isEnabled()
    assert not dialog.plugins.isEnabled()
    dialog.path.setText("test.vst3")
    assert dialog.load_button.isEnabled()
    qtbot.keyClick(dialog.path, Qt.Key.Key_Return)
    qtbot.keyClick(dialog.plugin_search, Qt.Key.Key_Return)
    engine.vst_dut.load.assert_not_called()
    engine.vst_dut.set_parameter.assert_not_called()
    assert dialog.isVisible()
    dialog.close_buttons.button(QDialogButtonBox.StandardButton.Close).click()
    assert not dialog.isVisible()


def test_native_editor_open_close_unload_and_dialog_exit(qtbot):
    engine = AudioEngine()
    engine.offline_mode = True
    dut = engine.vst_dut
    dut.path = "test.vst3"
    dut.name = "Test effect"
    dut.open_editor = MagicMock(side_effect=lambda: setattr(dut, "editor_open", True))
    dut.close_editor = MagicMock(side_effect=lambda: setattr(dut, "editor_open", False))
    dialog = VstDutDialog(engine)
    qtbot.addWidget(dialog)
    try:
        dialog.show()
        dialog.editor_button.click()
        dut.open_editor.assert_called_once()
        assert dut.editor_open
        assert dialog.editor_button.text() == "Close plugin editor"
        assert not dialog.routing.isEnabled()
        dialog.editor_button.click()
        assert not dut.editor_open
        assert dialog.editor_button.text() == "Open plugin editor"
        dialog.editor_button.click()
        dialog.reject()
        assert not dut.editor_open
        dialog.show()
        dialog.unload_button.click()
        assert not dut.loaded
        assert not dialog.editor_button.isEnabled()
    finally:
        dut.close()


def test_editor_completion_error_is_reported_once_without_disabling_host(qtbot, monkeypatch):
    engine = AudioEngine()
    engine.offline_mode = True
    dut = engine.vst_dut
    dut.path = "test.vst3"
    dialog = VstDutDialog(engine)
    qtbot.addWidget(dialog)
    errors = []
    monkeypatch.setattr(dialog, "_error", errors.append)
    dut.poll_editor = MagicMock(side_effect=[True, False])
    dut.editor_error = "Plugin has no available editor UI."
    try:
        dialog._refresh()
        dialog._refresh()
        assert len(errors) == 1
        assert dut.editor_error in errors[0]
        assert dut.loaded and not dut.error
        assert dialog.editor_button.isEnabled()
    finally:
        dut.close()


def test_measurement_start_closes_native_editor(qtbot):
    engine = AudioEngine()
    engine.offline_mode = True
    dut = engine.vst_dut
    dut.path = "test.vst3"
    dut.close_editor = MagicMock(side_effect=lambda: setattr(dut, "editor_open", False))
    dialog = VstDutDialog(engine)
    qtbot.addWidget(dialog)
    try:
        dut.editor_open = True
        engine.callbacks[1] = MagicMock()
        dialog._refresh()
        dut.close_editor.assert_called_once()
        assert not dut.editor_open
        assert not dialog.editor_button.isEnabled()
    finally:
        engine.callbacks.clear()
        dut.close()


@pytest.mark.parametrize("succeeded", [True, False])
def test_load_opens_native_editor_only_on_success(qtbot, monkeypatch, succeeded):
    engine = AudioEngine()
    engine.offline_mode = True
    dut = engine.vst_dut
    dut.path = "test.vst3"
    dut.open_editor = MagicMock()

    def load(*args):
        if not succeeded:
            raise RuntimeError("Load failed")

    dut.load = MagicMock(side_effect=load)
    dialog = VstDutDialog(engine)
    qtbot.addWidget(dialog)
    monkeypatch.setattr(dialog, "_error", MagicMock())
    try:
        dialog.load_button.click()
        qtbot.waitUntil(lambda: dialog.loader is None)
        assert dut.open_editor.call_count == int(succeeded)
    finally:
        dut.close()


def test_loaded_identity_remains_visible_during_measurement(qtbot):
    engine = AudioEngine()
    engine.offline_mode = True
    engine.vst_dut.path = "test.vst3"
    engine.vst_dut.name = "Test <effect>"
    engine.vst_dut.bypassed = True
    dialog = VstDutDialog(engine)
    qtbot.addWidget(dialog)
    try:
        engine.callbacks[1] = MagicMock()
        dialog._refresh()
        assert not dialog.controls.isEnabled()
        assert "Test <effect>" in dialog.status.text()
        assert "Bypass" in dialog.status.text()
        assert dialog.status.textFormat() == Qt.TextFormat.PlainText
        assert "Stop measurements" in dialog.notice.text()
        assert dialog.close_buttons.isEnabled()
    finally:
        engine.callbacks.clear()
        engine.vst_dut.close()


def test_plugin_selection_filter_rescan_and_loading(qtbot, tmp_path, monkeypatch):
    first = tmp_path / "Vendor/Effect.vst3"
    second = tmp_path / "Other/Effect.vst3"
    third = tmp_path / "Delay.vst3"
    results = [first, second, third]
    monkeypatch.setattr("src.gui.widgets.vst_dut.discover_vst3", lambda **kwargs: VstScanResult(list(results)))
    engine = AudioEngine()
    engine.offline_mode = True
    engine.vst_dut.load = MagicMock()
    dialog = VstDutDialog(engine)
    qtbot.addWidget(dialog)
    try:
        qtbot.waitUntil(lambda: dialog.scanner is None)
        assert dialog.plugins.count() == 4
        assert dialog.path.text() == ""  # Discovery never changes or loads the DUT.
        engine.vst_dut.load.assert_not_called()
        assert dialog.plugins.itemText(1) != dialog.plugins.itemText(2)
        dialog.plugin_name.setText("Old bundle member")
        dialog.plugins.setCurrentIndex(2)
        dialog.plugins.activated.emit(2)
        assert dialog.path.text() == str(second)
        assert dialog.plugin_name.text() == ""
        dialog.plugin_name.setText("Stale bundle member")
        dialog.path.setText(str(third))
        assert dialog.plugins.currentData() == str(third)
        assert dialog.plugin_name.text() == ""
        dialog.path.setText(str(second))
        dialog.plugin_search.setText("dElAy")
        assert dialog.plugins.count() == 2
        assert dialog.path.text() == str(second)
        dialog.plugin_search.clear()
        assert dialog.plugins.currentData() == str(second)
        results.remove(first)
        dialog.rescan_button.click()
        qtbot.waitUntil(lambda: dialog.scanner is None)
        assert dialog.plugins.count() == 3
        assert dialog.plugins.currentData() == str(second)
        dialog.load_button.click()
        qtbot.waitUntil(lambda: dialog.loader is None)
        engine.vst_dut.load.assert_called_once_with(str(second), None)
    finally:
        engine.vst_dut.close()


def test_scan_access_error_is_visible(qtbot, monkeypatch):
    monkeypatch.setattr(
        "src.gui.widgets.vst_dut.discover_vst3", lambda **kwargs: VstScanResult(errors=["/denied: permission denied"])
    )
    engine = AudioEngine()
    dialog = VstDutDialog(engine)
    qtbot.addWidget(dialog)
    qtbot.waitUntil(lambda: dialog.scanner is None)
    assert "Some folders could not be scanned" in dialog.scan_status.text()
    assert "/denied" in dialog.scan_status.toolTip()
    engine.vst_dut.close()


def test_dialog_can_close_during_slow_scan(qtbot, monkeypatch):
    release = threading.Event()

    def scan(**kwargs):
        release.wait(5)
        return VstScanResult()

    monkeypatch.setattr("src.gui.widgets.vst_dut.discover_vst3", scan)
    engine = AudioEngine()
    engine.offline_mode = True
    dialog = VstDutDialog(engine)
    qtbot.addWidget(dialog)
    try:
        dialog.show()
        worker = dialog.scanner
        assert worker is not None
        assert not dialog.rescan_button.isEnabled()
        dialog.plugin_search.setText("Can still type while scanning")
        dialog.reject()
        assert not dialog.isVisible()
        assert worker.cancelled.is_set()
    finally:
        release.set()
        qtbot.waitUntil(lambda: dialog.scanner is None)
        engine.vst_dut.close()


@pytest.mark.skipif(not os.environ.get("MEASURELAB_TEST_VST3"), reason="Set MEASURELAB_TEST_VST3 to an installed VST3")
def test_installed_plugin_discovery_and_load(qtbot, monkeypatch):
    monkeypatch.setattr("src.gui.widgets.vst_dut.discover_vst3", discover_vst3)
    target = Path(os.environ["MEASURELAB_TEST_VST3"]).resolve()
    engine = AudioEngine()
    engine.offline_mode = True
    dialog = VstDutDialog(engine)
    qtbot.addWidget(dialog)
    errors = []
    monkeypatch.setattr(dialog, "_error", errors.append)
    try:
        qtbot.waitUntil(lambda: dialog.scanner is None, timeout=10000)
        matches = [
            index
            for index in range(1, dialog.plugins.count())
            if Path(dialog.plugins.itemData(index)).resolve() == target
        ]
        assert len(matches) == 1
        dialog.plugins.setCurrentIndex(matches[0])
        dialog.plugins.activated.emit(matches[0])
        dialog.load_button.click()
        qtbot.waitUntil(lambda: dialog.loader is None, timeout=35000)
        assert not errors
        assert engine.vst_dut.loaded
        assert Path(engine.vst_dut.path) == target
        assert engine.vst_dut.name
        assert engine.vst_dut.editor_open
        qtbot.wait(500)  # Allow the native window to be created before closing it.
        engine.vst_dut.close_editor()
        assert not engine.vst_dut.editor_error
    finally:
        engine.vst_dut.close()
