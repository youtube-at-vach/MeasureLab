import numpy as np
from src.core.audio_engine import AudioEngine
from src.gui.widgets.nonlinear_analyzer import NonlinearAnalyzer, NonlinearAnalyzerWidget


def test_nonlinear_analyzer_gui_start(qtbot):
    # Force offline mode to avoid accessing hardware sound devices
    audio_engine = AudioEngine()
    audio_engine.offline_mode = True

    analyzer = NonlinearAnalyzer(audio_engine)
    # Configure short parameters so the mock measurement runs within timeout limits
    analyzer.sweep_duration = 0.1
    analyzer.averages = 1
    analyzer.num_amplitudes = 5

    # Mock play_rec directly to avoid audio driver timeout issues
    analyzer.run_play_rec = lambda out_data, **kwargs: np.zeros((len(out_data), 2), dtype=np.float32)

    widget = NonlinearAnalyzerWidget(analyzer)
    qtbot.addWidget(widget)

    # We expect sweep_finished to be emitted eventually
    with qtbot.waitSignal(analyzer.signals.sweep_finished, timeout=10000):
        # Click start analysis
        widget.start_btn.click()

    # Once finished, button states should revert
    assert widget.start_btn.isEnabled()
    assert not widget.stop_btn.isEnabled()


def test_nonlinear_analyzer_routing(qtbot):
    audio_engine = AudioEngine()
    analyzer = NonlinearAnalyzer(audio_engine)
    widget = NonlinearAnalyzerWidget(analyzer)
    qtbot.addWidget(widget)

    # 1. Check default XFER_REV / Stereo routing
    assert widget.in_mode_combo.currentData() == "XFER_REV"
    assert widget.out_combo.currentData() == "STEREO"
    assert analyzer.input_mode == "XFER_REV"
    assert analyzer.output_channel == "STEREO"
    assert analyzer.ref_channel_index == 1
    assert analyzer.meas_channel_index == 0
    assert not widget.cal_btn.isEnabled()

    # 2. Switch to Left (Ch1) Mode
    widget.in_mode_combo.setCurrentIndex(widget.in_mode_combo.findData("L"))
    assert analyzer.input_mode == "L"
    assert analyzer.ref_channel_index == 0
    assert analyzer.meas_channel_index == 0
    assert widget.cal_btn.isEnabled()

    # 3. Switch to Right (Ch2) Mode
    widget.in_mode_combo.setCurrentIndex(widget.in_mode_combo.findData("R"))
    assert analyzer.input_mode == "R"
    assert analyzer.ref_channel_index == 1
    assert analyzer.meas_channel_index == 1
    assert widget.cal_btn.isEnabled()

    # 4. Switch to Normal XFER Mode
    widget.in_mode_combo.setCurrentIndex(widget.in_mode_combo.findData("XFER"))
    assert analyzer.input_mode == "XFER"
    assert analyzer.ref_channel_index == 0
    assert analyzer.meas_channel_index == 1
    assert not widget.cal_btn.isEnabled()

    # 5. Modify Output Channel to Right
    widget.out_combo.setCurrentIndex(widget.out_combo.findData("R"))
    assert analyzer.output_channel == "R"


def test_nonlinear_analyzer_gui_stop(qtbot, monkeypatch):
    # Setup dummy audio engine in offline mode
    audio_engine = AudioEngine()
    audio_engine.offline_mode = True

    analyzer = NonlinearAnalyzer(audio_engine)
    # Set longer parameters to give enough time to click stop
    analyzer.sweep_duration = 2.0
    analyzer.averages = 1
    analyzer.num_amplitudes = 5

    # Mock play_rec directly to avoid audio driver timeout issues
    analyzer.run_play_rec = lambda out_data, **kwargs: np.zeros((len(out_data), 2), dtype=np.float32)

    widget = NonlinearAnalyzerWidget(analyzer)
    qtbot.addWidget(widget)

    # Mock QMessageBox.critical to verify it is NOT called (no error dialogs on user abort)
    critical_called = False

    def mock_critical(*args, **kwargs):
        nonlocal critical_called
        critical_called = True

    from PyQt6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "critical", mock_critical)

    # Click start analysis
    widget.start_btn.click()

    # Wait for the worker to start and stop button to become active
    qtbot.waitUntil(lambda: widget.stop_btn.isEnabled(), timeout=1000)
    assert not widget.start_btn.isEnabled()

    # Click stop
    widget.stop_btn.click()

    # The worker should stop quickly
    qtbot.waitUntil(lambda: widget.start_btn.isEnabled() and not widget.stop_btn.isEnabled(), timeout=2000)

    # QMessageBox.critical should not have been called
    assert not critical_called
