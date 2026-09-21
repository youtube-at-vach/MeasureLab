from unittest.mock import MagicMock, patch
import pytest
import numpy as np
from PyQt6.QtCore import Qt
from src.gui.widgets.lufs_meter import LufsMeter, LufsMeterWidget


class MockAudioEngine:
    def __init__(self):
        self.sample_rate = 48000
        self.calibration = MagicMock()
        self.calibration.get_spl_offset_db.return_value = None

    def register_callback(self, callback):
        self.callback = callback
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

    widget.on_toggle(True)
    mono = 0.1 * np.sin(2 * np.pi * 997 * np.arange(24000) / engine.sample_rate)
    block = np.column_stack((mono, mono))
    engine.callback(block, None, len(block), None, None)
    widget.update_display()
    assert module.get_loudness_history().momentary.count == 2
    assert widget.card_m_min["label"].text() != "---"

    qtbot.mouseClick(widget.reset_stats_btn, Qt.MouseButton.LeftButton)

    assert module.get_loudness_history().momentary.count == 0
    assert module.get_loudness_history().points == ()
    assert widget.card_m_min["label"].text() == "---"
    assert widget.m_curve.xData is None or len(widget.m_curve.xData) == 0


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
    assert widget.tabs.isHidden()
    assert not widget.profile_details.isVisible()
    assert not widget.readouts_panel.isHidden()
    assert widget.tabs.currentIndex() == 0
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


def test_histogram_scale_fits_music_without_jitter_and_recovers_from_silence(qtbot):
    from src.core.peak_profiler import PeakProfiler

    module = LufsMeter(MockAudioEngine())
    core = PeakProfiler(48000)
    core.channels = 2
    core.frames = 1_000_000
    module.get_peak_profile = core.snapshot
    widget = LufsMeterWidget(module)
    qtbot.addWidget(widget)

    def distribution(channel, peak_percent):
        counts = core.histogram[channel]
        peak_count = round(peak_percent * 10_000)
        other_count, remainder = divmod(1_000_000 - peak_count, len(counts) - 1)
        counts[:] = other_count
        counts[0] = peak_count
        counts[1 : remainder + 1] += 1

    def upper():
        widget.update_peak_profile()
        low, high = widget.histogram_plot.getViewBox().viewRange()[1]
        assert low == 0
        assert all(curve.yData.max() <= high for curve in widget.histogram_curves[: core.channels])
        return high

    distribution(0, 4.2)
    distribution(1, 3.1)
    assert upper() == 5
    distribution(0, 5.5)
    expanded = upper()
    assert expanded == 8
    for peak in (5.4, 5.3, 5.5, 5.2):
        distribution(0, peak)
        assert upper() == expanded
    core.histogram *= 100
    core.frames *= 100
    assert upper() == expanded

    # Either channel (including the silence/end bin) must remain fully visible.
    distribution(1, 100)
    assert upper() == 100
    distribution(0, 4.2)
    distribution(1, 3.1)
    assert upper() == 6
    core.histogram[:] = 0
    core.frames = 0
    assert upper() == 5

    # An absent channel cannot determine the visible channel's scale.
    core.channels = 1
    distribution(0, 4.2)
    distribution(1, 100)
    assert upper() == 5


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


@pytest.mark.parametrize("tab_index", range(4))
def test_compact_shows_only_meters_and_restores_selected_tab(qtbot, tab_index):
    widget = LufsMeterWidget(LufsMeter(MockAudioEngine()))
    qtbot.addWidget(widget)
    widget.show()
    widget.tabs.setCurrentIndex(tab_index)
    widget.set_compact_mode(True)
    qtbot.wait(80)
    assert not widget.tabs.isVisible()
    assert widget.readouts_panel.isVisible()
    assert widget.disp_i["label"].isVisible()
    assert widget.l_bar.isVisible()
    assert not widget.profile_status.isVisible()
    assert not widget.profile_summary.isVisible()
    assert not widget.profile_acquisition.isVisible()
    assert not widget.event_note.isVisible()
    widget.set_compact_mode(False)
    qtbot.wait(80)
    assert widget.tabs.isVisible()
    assert widget.tabs.currentIndex() == tab_index
    assert widget.tabs.currentWidget().isVisible()
    assert widget.readouts_panel.isVisible()
    assert widget.profile_status.isVisible() == (tab_index == 3)
    assert widget.profile_summary.isVisible() == (tab_index == 3)
    assert widget.profile_acquisition.isVisible() == (tab_index == 3)
    assert widget.event_note.isVisible() == (tab_index == 3)


def test_loudness_repaints_and_stop_preserve_acquired_history(qtbot):
    engine = MockAudioEngine()
    module = LufsMeter(engine)
    widget = LufsMeterWidget(module)
    qtbot.addWidget(widget)
    widget.on_toggle(True)
    # Acquire without painting. Include a partial final interval to verify
    # x=0 means the latest acquired sample, not the latest timer invocation.
    signal = 0.1 * np.sin(2 * np.pi * 997 * np.arange(25200) / engine.sample_rate)
    block = np.column_stack((signal, signal))
    engine.callback(block, None, len(block), None, None)
    before = module.get_loudness_history()
    assert before.momentary.count == 2
    for _ in range(5):
        widget.update_display(force=True)
    assert module.get_loudness_history() == before
    np.testing.assert_allclose(widget.m_curve.xData, [-0.125, -0.025])
    np.testing.assert_allclose(widget.m_curve.yData, [p.momentary for p in before.points])
    assert widget.card_s_avg["label"].text() == "---"
    widget.on_toggle(False)
    for _ in range(3):
        widget.update_display(force=True)
    assert module.get_loudness_history() == before

    # A freshly created view can reconstruct results without having observed
    # the original acquisition. Starting again clears the previous run.
    other = LufsMeterWidget(module)
    qtbot.addWidget(other)
    other.update_display(force=True)
    np.testing.assert_array_equal(other.m_curve.yData, widget.m_curve.yData)
    assert other.card_m_avg["label"].text() == widget.card_m_avg["label"].text()
    widget.on_toggle(True)
    assert module.get_loudness_history().points == ()
    assert widget.card_m_avg["label"].text() == "---"
    assert widget.m_curve.xData is None or len(widget.m_curve.xData) == 0


def test_invalid_loudness_does_not_leave_a_valid_looking_graph(qtbot):
    engine = MockAudioEngine()
    module = LufsMeter(engine)
    widget = LufsMeterWidget(module)
    qtbot.addWidget(widget)
    widget.on_toggle(True)
    mono = 0.1 * np.sin(2 * np.pi * 997 * np.arange(24000) / engine.sample_rate)
    block = np.column_stack((mono, mono))
    engine.callback(block, None, len(block), None, None)
    widget.update_display()
    assert len(widget.m_curve.xData) == 2
    before = module.get_loudness_history().momentary
    engine.callback(np.full((100, 2), np.nan), None, 100, None, None)
    engine.callback(block, None, len(block), None, None)
    widget.update_display()
    assert widget.card_m_avg["label"].text() == "INVALID"
    assert widget.m_curve.xData is None or len(widget.m_curve.xData) == 0
    assert module.get_loudness_history().momentary == before
