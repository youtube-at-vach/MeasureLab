from unittest.mock import MagicMock

import pytest

from src.core.audio_engine import AudioEngine
from src.core.localization import get_manager
from src.gui.widgets.vst_dut import VstDutDialog


@pytest.mark.parametrize("language", ["en", "ja", "de", "es", "fr", "ko", "pt", "ru", "zh"])
def test_dut_controls_and_size_in_all_languages(qtbot, language):
    manager = get_manager()
    manager.load_language(language)
    engine = AudioEngine()
    engine.offline_mode = True
    dialog = VstDutDialog(engine)
    qtbot.addWidget(dialog)
    try:
        dialog.show()
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
    try:
        assert dialog.value.value() == 0.25
        dialog.parameter.setCurrentIndex(1)
        assert dialog.value.value() == 0.75
        engine.vst_dut._request = MagicMock(return_value={"gain": 0.25, "cutoff": 0.5})
        dialog.value.setValue(0.49)
        dialog._apply_parameter()
        engine.vst_dut._request.assert_called_once_with("parameter", ("cutoff", 0.49))
        assert dialog.value.value() == 0.5
    finally:
        engine.vst_dut.close()
