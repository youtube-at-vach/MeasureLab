from src.core.audio_engine import AudioEngine
from src.gui.widgets.nonlinear_system_analyzer import NonlinearSystemAnalyzer, NonlinearSystemAnalyzerWidget


def test_nonlinear_analyzer_gui_start(qtbot):
    # Force offline mode to avoid accessing hardware sound devices
    audio_engine = AudioEngine()
    audio_engine.offline_mode = True

    analyzer = NonlinearSystemAnalyzer(audio_engine)
    # Configure short parameters so the mock measurement runs within timeout limits
    analyzer.sweep_duration = 0.1
    analyzer.averages = 1
    analyzer.num_amplitudes = 5

    widget = NonlinearSystemAnalyzerWidget(analyzer)
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
    analyzer = NonlinearSystemAnalyzer(audio_engine)
    widget = NonlinearSystemAnalyzerWidget(analyzer)
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



