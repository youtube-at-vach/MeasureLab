import pytest
from PyQt6.QtCore import Qt
from src.core.audio_engine import AudioEngine
from src.gui.widgets.nonlinear_system_analyzer import NonlinearSystemAnalyzer, NonlinearSystemAnalyzerWidget


def test_nonlinear_analyzer_gui_start(qtbot):
    # Force offline mode to avoid accessing hardware sound devices
    audio_engine = AudioEngine()
    audio_engine.offline_mode = True

    analyzer = NonlinearSystemAnalyzer(audio_engine)
    widget = NonlinearSystemAnalyzerWidget(analyzer)
    qtbot.addWidget(widget)

    # We expect sweep_finished to be emitted eventually
    with qtbot.waitSignal(analyzer.signals.sweep_finished, timeout=10000):
        # Click start analysis
        widget.start_btn.click()

    # Once finished, button states should revert
    assert widget.start_btn.isEnabled()
    assert not widget.stop_btn.isEnabled()


