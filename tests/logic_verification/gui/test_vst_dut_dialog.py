import os
from pathlib import Path
import threading
from unittest.mock import MagicMock

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialogButtonBox

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
        for tab in range(dialog.tabs.count()):
            dialog.tabs.setCurrentIndex(tab)
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


def test_parameters_use_actual_host_value(qtbot):
    engine = AudioEngine()
    engine.offline_mode = True
    engine.vst_dut.path = "test.vst3"
    engine.vst_dut.parameters = {"gain": 0.25, "cutoff": 0.75}
    dialog = VstDutDialog(engine)
    qtbot.addWidget(dialog)
    qtbot.waitUntil(lambda: dialog.scanner is None)
    try:
        assert dialog.value.value() == 0.25
        dialog.parameter.setCurrentIndex(1)
        assert dialog.value.value() == 0.75
        engine.vst_dut._request = MagicMock(return_value={"gain": 0.25, "cutoff": 0.5})
        dialog.value.setValue(0.49)
        dialog._apply_parameter()
        engine.vst_dut._request.assert_called_once_with("parameter", ("cutoff", 0.49))
        assert dialog.value.value() == 0.5
        assert dialog.slider.value() == 500
        assert not dialog.apply.isEnabled()
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
    assert not dialog.value.isEnabled()
    assert not dialog.slider.isEnabled()
    assert not dialog.apply.isEnabled()
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


def test_parameter_search_slider_and_unload(qtbot):
    engine = AudioEngine()
    engine.offline_mode = True
    engine.vst_dut.path = "test.vst3"
    engine.vst_dut.name = "Test effect"
    engine.vst_dut.parameters = {"gain": 0.123456, "cutoff": 0.75}
    engine.vst_dut._request = MagicMock(return_value={"gain": 0.25, "cutoff": 0.75})
    dialog = VstDutDialog(engine)
    qtbot.addWidget(dialog)
    try:
        assert dialog.value.value() == 0.123456  # Slider must not quantize the host value.
        assert dialog.slider.value() == 123
        assert not dialog.apply.isEnabled()
        dialog.parameter_search.setText("GAIN")
        assert dialog.parameter.count() == 1
        dialog.slider.setValue(249)
        assert dialog.value.value() == 0.249
        engine.vst_dut._request.assert_not_called()  # Editing waits for Apply.
        dialog.apply.click()
        engine.vst_dut._request.assert_called_once_with("parameter", ("gain", 0.249))
        assert dialog.value.value() == 0.25
        assert not dialog.apply.isEnabled()
        dialog.parameter_search.setText("missing")
        assert dialog.parameter.count() == 0
        assert not dialog.value.isEnabled()
        assert not dialog.apply.isEnabled()
        dialog.parameter_search.clear()
        dialog.unload_button.click()
        assert not engine.vst_dut.loaded
        assert dialog.parameter.count() == 0
        assert not dialog.value.isEnabled()
        assert not dialog.apply.isEnabled()
        assert not dialog.bypass.isChecked()
        assert "Test effect" not in dialog.status.text()
    finally:
        engine.vst_dut.close()


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
        assert dialog.parameter.count() == len(engine.vst_dut.parameters)
    finally:
        engine.vst_dut.close()
