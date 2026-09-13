from unittest.mock import MagicMock, patch
import pytest
from PyQt6.QtCore import Qt
from src.gui.widgets.lufs_meter import LufsMeter, LufsMeterWidget


class MockAudioEngine:
    def __init__(self):
        self.sample_rate = 48000
        self.calibration = MagicMock()
        self.calibration.get_spl_offset_db.return_value = None

    def register_callback(self, callback):
        return 1

    def unregister_callback(self, callback_id):
        pass


def test_lufs_meter_widget_initialization(qtbot):
    engine = MockAudioEngine()
    module = LufsMeter(engine)
    widget = LufsMeterWidget(module)
    qtbot.addWidget(widget)

    # Verify initial states
    assert "-INF" in widget.m_val_label.text()
    assert "-INF" in widget.s_val_label.text()
    assert widget.target_spin.value() == -23.0
    assert widget.timer.isActive() is False


def test_lufs_meter_widget_toggle(qtbot):
    engine = MockAudioEngine()
    module = LufsMeter(engine)
    widget = LufsMeterWidget(module)
    qtbot.addWidget(widget)

    # Initially not running
    assert not widget.module.is_running
    assert not widget.timer.isActive()

    # Click toggle
    qtbot.mouseClick(widget.toggle_btn, Qt.MouseButton.LeftButton)
    assert widget.module.is_running
    assert widget.timer.isActive()

    # Click toggle again
    qtbot.mouseClick(widget.toggle_btn, Qt.MouseButton.LeftButton)
    assert not widget.module.is_running
    assert not widget.timer.isActive()


def test_lufs_meter_widget_recovers_from_stream_start_failure(qtbot):
    engine = MockAudioEngine()
    engine.register_callback = MagicMock(side_effect=RuntimeError("device unavailable"))
    module = LufsMeter(engine)
    widget = LufsMeterWidget(module)
    qtbot.addWidget(widget)

    with patch("src.gui.widgets.lufs_meter.QMessageBox") as message_box:
        qtbot.mouseClick(widget.toggle_btn, Qt.MouseButton.LeftButton)

    assert not module.is_running
    assert module.callback_id is None
    assert not widget.toggle_btn.isChecked()
    assert not widget.timer.isActive()
    assert widget.toggle_btn.text() == "Start Metering"
    message_box.critical.assert_called_once()


def test_lufs_meter_widget_update_display(qtbot):
    engine = MockAudioEngine()
    module = LufsMeter(engine)
    widget = LufsMeterWidget(module)
    qtbot.addWidget(widget)

    # Needs to be running to update display
    widget.on_toggle(True)

    module.momentary_lufs = -15.0
    module.short_term_lufs = -18.0
    module.rms_l = -10.0
    module.rms_r = -10.0

    widget.update_display()

    # Check that labels were updated correctly
    assert "-15.0" in widget.m_val_label.text()
    assert "-18.0" in widget.s_val_label.text()
    assert "-10.0" in widget.l_val_label.text()
    assert "dBFS" in widget.l_val_label.text()
    assert "-10.0" in widget.r_val_label.text()
    assert "dBFS" in widget.r_val_label.text()


def test_lufs_meter_widget_never_presents_invalid_run_as_measurement(qtbot):
    engine = MockAudioEngine()
    module = LufsMeter(engine)
    widget = LufsMeterWidget(module)
    qtbot.addWidget(widget)
    widget.on_toggle(True)
    module.measurement_valid = False

    widget.update_display()

    assert widget.m_val_label.text() == "INVALID"
    assert widget.s_val_label.text() == "INVALID"
    assert widget.disp_i["label"].text() == "INVALID"
    assert widget.disp_s["label"].text() == "INVALID"
    assert widget.card_threshold["label"].text() == "INVALID"


def test_lufs_meter_widget_reset_stats(qtbot):
    engine = MockAudioEngine()
    module = LufsMeter(engine)
    widget = LufsMeterWidget(module)
    qtbot.addWidget(widget)

    # Simulate some stats
    widget._m_min = -20.0
    widget._m_max = -5.0
    widget._m_sum = -100.0
    widget._m_n = 5

    # Reset stats
    qtbot.mouseClick(widget.reset_stats_btn, Qt.MouseButton.LeftButton)

    assert widget._m_min is None
    assert widget._m_max is None
    assert widget._m_sum == 0.0
    assert widget._m_n == 0


def test_lufs_meter_widget_target_changed(qtbot):
    engine = MockAudioEngine()
    module = LufsMeter(engine)
    widget = LufsMeterWidget(module)
    qtbot.addWidget(widget)

    widget.target_spin.setValue(-14.0)

    assert module.target_lufs == -14.0
    # Also test the visual line placement
    assert widget.target_line.value() == -14.0


def test_peak_profile_compact_status_and_stopped_reset(qtbot):
    import numpy as np

    engine = MockAudioEngine()
    engine.register_callback = MagicMock(return_value=1)
    module = LufsMeter(engine)
    widget = LufsMeterWidget(module)
    qtbot.addWidget(widget)
    widget.on_toggle(True)
    callback = engine.register_callback.call_args.args[0]
    callback(np.ones((100, 2)), None, 100, None, None)
    widget.on_toggle(False)
    widget.set_compact_mode(True)
    assert not widget.tabs.isHidden()
    assert widget.profile_details.isHidden()
    assert widget.readouts_panel.isHidden()
    assert widget.tabs.currentWidget() is widget.histogram_plot
    assert "latched" in widget.profile_status.text()
    assert "SP 100" in widget.profile_summary.text()
    widget.reset_btn.click()
    assert "-INF" in widget.l_peak_label.text()
    assert "latched" in widget.profile_status.text()
    widget.on_reset_stats()
    assert "no data" in widget.profile_status.text()
    assert all(curve.xData is None or len(curve.xData) == 0 for curve in widget.event_curves)


def test_peak_profile_settings_and_anomalies(qtbot):
    module = LufsMeter(MockAudioEngine())
    widget = LufsMeterWidget(module)
    qtbot.addWidget(widget)
    widget.peak_threshold_spin.setValue(2)
    assert module.peak_threshold_db == 2
    assert widget.histogram_threshold.value() == 2
    widget.on_toggle(True)
    module._profile.mark_gap("queue_overflow")
    widget.update_display()
    assert "INCOMPLETE" in widget.profile_status.text()
    widget.on_toggle(False)
    widget.on_reset_stats()
    assert "INCOMPLETE" not in widget.profile_status.text()


def test_histogram_is_normalized_per_channel_and_keeps_raw_totals(qtbot):
    import numpy as np
    from src.core.peak_profiler import PeakProfiler

    module = LufsMeter(MockAudioEngine())
    core = PeakProfiler(48000)
    core.channels = 2
    core.frames = 4
    core.histogram[0, :2] = [1, 3]
    core.histogram[1, :2] = [1, 1]
    module.get_peak_profile = core.snapshot
    widget = LufsMeterWidget(module)
    qtbot.addWidget(widget)
    expected = [curve.yData.copy() for curve in widget.histogram_curves]
    np.testing.assert_allclose(expected[0][:2], [25, 75])
    np.testing.assert_allclose(expected[1][:2], [50, 50])
    for curve in widget.histogram_curves:
        assert curve.yData.sum() == 100
    core.histogram *= 12000
    core.frames *= 12000
    widget.update_peak_profile()
    for curve, frequencies in zip(widget.histogram_curves, expected, strict=True):
        np.testing.assert_allclose(curve.yData, frequencies)
    assert "48000 frames / 1.000 s" in widget.profile_acquisition.text()
    assert core.histogram[0, 1] == 36000
    assert widget.histogram_plot.getViewBox().viewRange()[1] == [0, 100]
    core.histogram[:] = 0
    core.frames = 0
    widget.update_peak_profile()
    assert all(np.isfinite(curve.yData).all() and not curve.yData.any() for curve in widget.histogram_curves)


@pytest.fixture(params=["en", "ja", "de", "es", "fr", "ko", "pt", "ru", "zh"])
def profile_language(request):
    from src.core.localization import get_manager

    manager = get_manager()
    previous = manager.language
    manager.load_language(request.param)
    yield request.param
    manager.load_language(previous)


def test_live_profile_text_and_axis_ticks_do_not_resize_plot(qtbot, profile_language):
    from src.core.peak_profiler import PeakEvent, PeakProfiler

    module = LufsMeter(MockAudioEngine())
    core = PeakProfiler(48000)
    module.get_peak_profile = core.snapshot
    widget = LufsMeterWidget(module)
    qtbot.addWidget(widget)
    widget.resize(1180, 690)
    widget.show()
    widget.update_display(force=True)

    def view_rect(plot):
        # Flush plot-axis layout updates before comparing drawing bounds.
        for _ in range(3):
            plot.repaint()
            qtbot.wait(10)
        return plot.getViewBox().sceneBoundingRect()

    for tab, plot in ((2, widget.histogram_plot), (3, widget.event_plot)):
        widget.tabs.setCurrentIndex(tab)
        original = view_rect(plot)
        core.channels = 2
        core.frames = 10**12
        core.histogram[:, -1] = core.frames
        core.exceedances[:] = core.frames
        core.events_started[:] = core.frames
        core.longest_frames[:] = core.frames
        core.flags.update({"data_gap", "configuration_changed", "queue_overflow", "processing_error"})
        core.active[0, 0] = PeakEvent(0, 0, 10**12, 10**12 + 48000, 1.2)
        widget.update_display(force=True)
        updated = view_rect(plot)
        assert updated == original
        assert widget.profile_details.horizontalScrollBar().maximum() == 0
        core = PeakProfiler(48000)
        module.get_peak_profile = core.snapshot
        widget.update_display(force=True)
        assert view_rect(plot) == original


def test_compact_keeps_selected_plot_and_hides_all_profile_text(qtbot):
    widget = LufsMeterWidget(LufsMeter(MockAudioEngine()))
    qtbot.addWidget(widget)
    widget.show()
    widget.tabs.setCurrentIndex(3)
    widget.set_compact_mode(True)
    qtbot.wait(80)
    assert widget.event_plot.isVisible()
    assert not widget.readouts_panel.isVisible()
    assert not widget.profile_status.isVisible()
    assert not widget.profile_summary.isVisible()
    assert not widget.profile_acquisition.isVisible()
    assert not widget.event_note.isVisible()
    widget.set_compact_mode(False)
    qtbot.wait(80)
    assert widget.event_plot.isVisible()
    assert widget.readouts_panel.isVisible()
    assert widget.profile_status.isVisible()
    assert widget.event_note.isVisible()
