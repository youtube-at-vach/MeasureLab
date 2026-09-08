from types import SimpleNamespace

from src.core.audio_engine import AudioEngine
from src.core.io_bridge import IOBridgeState
from src.gui.widgets.io_bridge import IOBridge, IOBridgeWidget


def test_starting_bridge_keeps_off_action_available(qtbot, monkeypatch):
    engine = AudioEngine()
    engine.offline_mode = True
    engine.vst_dut = SimpleNamespace(loaded=True)
    module = IOBridge(engine)
    widget = IOBridgeWidget(module)
    qtbot.addWidget(widget)
    engine.io_bridge._state = IOBridgeState.STARTING
    widget.refresh_status()
    assert widget.toggle_btn.isChecked()
    assert widget.toggle_btn.isEnabled()
    assert not widget.route_combo.isEnabled()
    stopped = []
    monkeypatch.setattr(module, "stop", lambda: stopped.append(True))
    widget.toggle_btn.click()
    assert stopped == [True]
    engine.io_bridge._state = IOBridgeState.OFF


def test_unavailable_bridge_disables_start(qtbot):
    engine = AudioEngine()
    widget = IOBridgeWidget(IOBridge(engine))
    qtbot.addWidget(widget)
    assert not widget.toggle_btn.isEnabled()
    assert widget.reason_label.text()
