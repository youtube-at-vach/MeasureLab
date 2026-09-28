from types import SimpleNamespace
from threading import Thread

import numpy as np
import pytest

from src.gui.widgets.raw_time_series import RawTimeSeries, RawTimeSeriesWidget
from src.core.localization import get_manager
from src.core.module_constants import MODULE_RAW_TIME_SERIES
from src.gui.module_registry import MODULE_REGISTRY
from src.gui.widgets.detachable_wrapper import DetachableWidgetWrapper


class AudioEngine:
    def __init__(self, sample_rate=48000):
        self.sample_rate = sample_rate
        self.calibration = SimpleNamespace(input_sensitivity=2.5, input_sensitivity_is_calibrated=True)
        self.callbacks = {}
        self.next_id = 0

    def register_callback(self, callback):
        self.next_id += 1
        self.callbacks[self.next_id] = callback
        return self.next_id

    def unregister_callback(self, callback_id):
        self.callbacks.pop(callback_id)

    def feed(self, data, status=None):
        for callback in tuple(self.callbacks.values()):
            output = np.ones_like(data)
            callback(data, output, len(data), None, status)
            assert not output.any()


@pytest.fixture
def meter():
    model = RawTimeSeries(AudioEngine())
    yield model
    model.stop_analysis()


@pytest.fixture
def widget(qtbot, meter):
    view = RawTimeSeriesWidget(meter)
    qtbot.addWidget(view)
    return view


@pytest.mark.parametrize("sample_rate", [44100, 48000, 96000])
@pytest.mark.parametrize("block_size", [17, 257, 1024, 65536])
def test_sample_clock_and_extrema_do_not_depend_on_callback_size(sample_rate, block_size):
    engine = AudioEngine(sample_rate)
    meter = RawTimeSeries(engine)
    meter.start_analysis()
    try:
        rng = np.random.default_rng(14)
        data = rng.uniform(-0.7, 0.7, size=(sample_rate + 13, 2)).astype(np.float32)
        data[7, 0] = 0.99
        data[-80, 1] = -0.98
        for start in range(0, len(data), block_size):
            engine.feed(data[start : start + block_size])
        frame = meter.get_display_frame(10)
        size = meter._bucket_size
        count = len(data) // size
        groups = data[: count * size].reshape(count, size, 2)
        np.testing.assert_array_equal(frame.values[:count, 0], groups.min(axis=1))
        np.testing.assert_array_equal(frame.values[:count, 1], groups.max(axis=1))
        np.testing.assert_allclose(frame.values[:count, 2], groups.mean(axis=1, dtype=np.float64), atol=2e-8)
        expected_times = (np.arange(1, count + 1) * size - len(data)) / sample_rate
        if len(data) % size:
            np.testing.assert_array_equal(frame.values[-1, 0], data[count * size :].min(axis=0))
            np.testing.assert_array_equal(frame.values[-1, 1], data[count * size :].max(axis=0))
            expected_times = np.append(expected_times, 0.0)
        np.testing.assert_allclose(frame.times, expected_times, atol=2e-16)
        np.testing.assert_allclose(frame.dc_mean(), data.mean(axis=0, dtype=np.float64), atol=1e-8)
        assert frame.duration_s == pytest.approx(len(data) / sample_rate)
        assert frame.values[:, 1, 0].max() == np.float32(0.99)
        assert frame.values[:, 0, 1].min() == np.float32(-0.98)
    finally:
        meter.stop_analysis()


def test_ring_wrap_and_oversized_block_keep_latest_history(meter):
    meter.max_span_s = 0.01
    meter.start_analysis()
    data = np.arange(2400 * 2, dtype=np.float32).reshape(-1, 2)
    meter.audio_engine.feed(data[:240])
    meter.audio_engine.feed(data[240:])
    frame = meter.get_display_frame(0.01)
    groups = data[-480:].reshape(20, 24, 2)
    np.testing.assert_array_equal(frame.values[:, 0], groups.min(axis=1))
    np.testing.assert_array_equal(frame.values[:, 1], groups.max(axis=1))
    assert len(frame.times) == 20
    storage_bytes = sum(chunk.nbytes for chunk in meter._chunks) + meter._chunk.nbytes
    assert storage_bytes <= (meter._capacity + 2 * meter._chunk_size) * 3 * 2 * 4
    assert not frame.values.flags.writeable
    assert meter.get_display_frame(0) is None


def test_plot_reduction_preserves_both_polarities_last_bucket_and_dc(meter):
    meter.start_analysis()
    data = np.full((240024, 2), 0.125, dtype=np.float32)
    data[31, 0] = 0.93
    data[73, 1] = -0.87
    data[-1, 0] = 0.99
    meter.audio_engine.feed(data)
    frame = meter.get_display_frame(10)
    times, values = frame.envelope(2000)
    assert len(times) <= 2000
    assert values[:, 1, 0].max() == np.float32(0.99)
    assert values[:, 0, 1].min() == np.float32(-0.87)
    assert values[-1, 1, 0] == np.float32(0.99)
    np.testing.assert_allclose(frame.values[:, 2].mean(axis=0, dtype=np.float64), data.mean(axis=0, dtype=np.float64))


@pytest.mark.parametrize("frames", [1, 25, 48001])
def test_partial_final_bucket_preserves_last_peak_and_weighted_dc(meter, frames):
    meter.start_analysis()
    data = np.zeros((frames, 2), dtype=np.float32)
    data[-1] = [0.9, -0.8]
    meter.audio_engine.feed(data)
    meter.stop_analysis()
    frame = meter.get_display_frame(10)
    np.testing.assert_array_equal(frame.values[-1, 1], [np.float32(0.9), np.float32(-0.8)])
    np.testing.assert_allclose(frame.dc_mean(), data.mean(axis=0, dtype=np.float64), rtol=1e-7)
    times, reduced = frame.envelope(1)
    np.testing.assert_allclose(reduced[-1, 2], data.mean(axis=0, dtype=np.float64), rtol=1e-7)
    assert len(times) == 1
    assert frame.times[-1] == 0
    assert frame.duration_s == pytest.approx(frames / meter.audio_engine.sample_rate)


def test_zoom_and_units_rerender_stopped_data_without_changing_amplitude(widget, meter):
    widget.btn_start.click()
    meter.audio_engine.feed(np.full((4800, 2), 0.05, dtype=np.float32))
    widget.btn_start.click()
    widget.chk_dc.setChecked(True)
    original = widget.curve_ch1.yData.copy()
    widget.combo_v.setCurrentIndex(widget.combo_v.findData(10.0))
    np.testing.assert_array_equal(widget.curve_ch1.yData, original)
    np.testing.assert_allclose(widget.plot_ch1.viewRange()[1], [-0.11, 0.11])
    assert "0.05 FS" in widget.lbl_dc_ch1.text()
    widget.chk_volts.setChecked(True)
    np.testing.assert_allclose(widget.curve_ch1.yData, original * 2.5)
    np.testing.assert_allclose(widget.plot_ch1.viewRange()[1], [-0.275, 0.275])
    assert "125" in widget.lbl_dc_ch1.text()
    assert "mV" in widget.lbl_dc_ch1.text()
    assert "last value" in widget.status_label.text()


def test_hold_freezes_history_but_allows_view_changes_and_resume(widget, meter):
    widget.btn_start.click()
    meter.audio_engine.feed(np.full((4800, 2), 0.1, dtype=np.float32))
    widget._update_plot()
    widget.btn_pause.click()
    frozen = meter.get_display_frame(10)
    meter.audio_engine.feed(np.full((4800, 2), 0.8, dtype=np.float32))
    widget.combo_span.setCurrentIndex(widget.combo_span.findData(60.0))
    widget.chk_dc.setChecked(True)
    np.testing.assert_array_equal(meter.get_display_frame(60).values, frozen.values)
    np.testing.assert_allclose(widget.curve_ch1.yData, 0.1)
    assert "acquisition running" in widget.status_label.text()
    assert "0.1 FS" in widget.lbl_dc_ch1.text()
    widget.btn_pause.click()
    assert widget.curve_ch1.yData[-1] == np.float32(0.8)
    assert widget.btn_pause.text() == "Hold Display"


def test_restart_clears_held_plot_and_old_callback_cannot_write(widget, meter):
    widget.btn_start.click()
    previous_callback = next(iter(meter.audio_engine.callbacks.values()))
    meter.audio_engine.feed(np.full((480, 2), 0.5, dtype=np.float32))
    widget._update_plot()
    widget.btn_pause.click()
    widget.btn_start.click()
    assert "display held" in widget.status_label.text()
    widget.btn_start.click()
    assert not meter.paused
    assert widget.curve_ch1.xData is None or not len(widget.curve_ch1.xData)
    previous_callback(np.ones((480, 2)), None, 480, None, None)
    assert meter.get_display_frame(10) is None
    assert "Waiting" in widget.status_label.text()


def test_start_failure_does_not_show_running_and_can_retry(widget, meter, monkeypatch):
    original = meter.audio_engine.register_callback

    def fail(callback):
        raise RuntimeError("Device unavailable")

    monkeypatch.setattr(meter.audio_engine, "register_callback", fail)
    widget.btn_start.click()
    assert not meter.is_running
    assert not widget.btn_start.isChecked()
    assert meter.callback_id is None
    assert "Device unavailable" in widget.status_label.text()
    monkeypatch.setattr(meter.audio_engine, "register_callback", original)
    widget.btn_start.click()
    assert meter.is_running
    assert not meter.error_message


@pytest.mark.parametrize("reason", ["rate", "overflow", "channels", "nan"])
def test_input_discontinuity_stops_without_relabelling_old_history(widget, meter, reason):
    widget.btn_start.click()
    meter.audio_engine.feed(np.full((480, 2), 0.5, dtype=np.float32))
    before = meter.get_display_frame(10)
    data = np.full((480, 2), 0.8, dtype=np.float32)
    status = None
    if reason == "rate":
        meter.audio_engine.sample_rate = 44100
    elif reason == "overflow":
        status = SimpleNamespace(input_overflow=True)
    elif reason == "channels":
        data = data[:, :1]
    else:
        data[17, 0] = np.nan
    meter.audio_engine.feed(data, status)
    widget._update_plot()
    assert not meter.is_running
    assert not meter.audio_engine.callbacks
    assert not widget.btn_start.isChecked()
    assert "Acquisition stopped:" in widget.status_label.text()
    np.testing.assert_array_equal(meter.get_display_frame(10).values, before.values)


def test_mono_input_is_explicit_and_compact_hides_controls(widget, meter):
    widget.show()
    widget.btn_start.click()
    meter.audio_engine.feed(np.full((480, 1), 0.25, dtype=np.float32))
    widget._update_plot()
    assert "mono" in widget.plot_ch2.titleLabel.text
    np.testing.assert_array_equal(widget.curve_ch1.yData, widget.curve_ch2.yData)
    widget.set_compact_mode(True)
    assert widget.right_widget.isHidden()
    assert not widget.btn_start.isVisible()
    assert not widget.btn_pause.isVisible()
    assert widget.status_label.isVisible()
    assert widget.view_label.isHidden()
    widget.set_compact_mode(False)
    assert widget.btn_start.isVisible()
    assert widget.btn_pause.isVisible()
    assert widget.view_label.isVisible()
    widget.close()
    assert not widget.timer.isActive()
    assert not meter.audio_engine.callbacks


def test_split_keeps_all_operations_in_control_window(qtbot, meter):
    widget = RawTimeSeriesWidget(meter)
    wrapper = DetachableWidgetWrapper(
        widget, "Raw Time Series", capabilities=MODULE_REGISTRY[MODULE_RAW_TIME_SERIES].capabilities
    )
    qtbot.addWidget(wrapper)
    wrapper.show()
    wrapper.split()
    assert not widget.display_widget.findChildren(type(widget.btn_start))
    for control in (widget.btn_start, widget.btn_pause, widget.combo_span, widget.chk_volts, widget.chk_dc):
        assert widget.right_widget.isAncestorOf(control)
        assert control.window() is wrapper.split_control_window

    widget.btn_start.click()
    meter.audio_engine.feed(np.full((480, 2), 0.25, dtype=np.float32))
    widget._update_plot()
    widget.btn_pause.click()
    wrapper.toggle_compact(True)
    assert widget.btn_start.isVisible()
    assert widget.btn_pause.isVisible()
    assert widget.status_label.isVisible()
    assert "acquisition running" in widget.status_label.text()
    widget.btn_start.click()
    assert not meter.is_running
    assert not meter.audio_engine.callbacks

    wrapper.reattach_all()
    assert widget.btn_start.window() is wrapper
    assert widget.btn_start.isVisible()
    assert widget.btn_pause.isVisible()
    assert not widget.is_compact_mode()


@pytest.mark.parametrize("language", sorted(get_manager().available_languages))
@pytest.mark.parametrize("mode", ["normal", "compact", "split", "split_compact"])
def test_display_options_preserve_plot_geometry_and_waveform_scale(qtbot, meter, language, mode):
    manager = get_manager()
    manager.load_language(language)
    try:
        widget = RawTimeSeriesWidget(meter)
        wrapper = DetachableWidgetWrapper(
            widget, "Raw Time Series", capabilities=MODULE_REGISTRY[MODULE_RAW_TIME_SERIES].capabilities
        )
        qtbot.addWidget(wrapper)
        wrapper.resize(1000, 650)
        wrapper.show()
        widget.btn_start.click()
        meter.audio_engine.feed(np.full((480, 2), 0.25, dtype=np.float32))
        widget._update_plot()
        if mode.startswith("split"):
            wrapper.split()
        if "compact" in mode:
            wrapper.toggle_compact(True)

        def geometry():
            qtbot.wait(30)
            return [plot.vb.sceneBoundingRect() for plot in (widget.plot_ch1, widget.plot_ch2)]

        original_geometry = geometry()
        original_waveform = widget.curve_ch1.yData / widget.plot_ch1.viewRange()[1][1]
        for volts, dc, sensitivity in (
            (True, False, 2.5),
            (True, True, 1e9),
            (False, True, 1e9),
            (True, True, float("nan")),
            (False, False, 2.5),
        ):
            meter.audio_engine.calibration.input_sensitivity = sensitivity
            meter.audio_engine.calibration.input_sensitivity_is_calibrated = False
            widget.chk_volts.setChecked(volts)
            widget.chk_dc.setChecked(dc)
            widget._update_plot()
            assert geometry() == original_geometry
            np.testing.assert_allclose(
                widget.curve_ch1.yData / widget.plot_ch1.viewRange()[1][1], original_waveform, rtol=1e-6
            )
        widget.btn_pause.click()
        assert geometry() == original_geometry
        widget.btn_start.click()
        assert geometry() == original_geometry
        widget.btn_pause.click()
        assert geometry() == original_geometry
        if mode.startswith("split"):
            wrapper.reattach_all()
    finally:
        manager.load_language("en")


def test_recreated_view_restores_settings_and_frozen_frame(qtbot, widget, meter):
    widget.btn_start.click()
    meter.audio_engine.feed(np.full((480, 2), 0.25, dtype=np.float32))
    widget.combo_span.setCurrentIndex(widget.combo_span.findData(60.0))
    widget.combo_v.setCurrentIndex(widget.combo_v.findData(2.0))
    widget._update_plot()
    widget.btn_pause.click()
    meter.audio_engine.feed(np.full((480, 2), 0.8, dtype=np.float32))
    other = RawTimeSeriesWidget(meter)
    qtbot.addWidget(other)
    assert other.combo_span.currentData() == 60.0
    assert other.combo_v.currentData() == 2.0
    assert other.btn_pause.isChecked()
    np.testing.assert_allclose(other.curve_ch1.yData, 0.25)


def test_frame_assembly_does_not_lock_out_audio_or_mutate_published_chunks(meter, monkeypatch):
    meter.max_span_s = 0.025
    meter.start_analysis()
    meter.audio_engine.feed(np.full((2400, 2), 0.25, dtype=np.float32))
    expected = meter.get_display_frame(0.025)
    concatenate = np.concatenate

    def assemble_after_new_audio(parts, *args, **kwargs):
        writer = Thread(target=meter.audio_engine.feed, args=(np.full((4800, 2), 0.8, dtype=np.float32),))
        writer.start()
        writer.join(timeout=1)
        assert not writer.is_alive(), "Audio must not wait for history concatenation"
        return concatenate(parts, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(np, "concatenate", assemble_after_new_audio)
        snapshot = meter.get_display_frame(0.025)
    np.testing.assert_array_equal(snapshot.values, expected.values)
    np.testing.assert_allclose(meter.get_display_frame(0.025).values, 0.8)


def test_nominal_voltage_notice_survives_compact_mode_and_invalid_calibration(widget, meter):
    widget.show()
    widget.btn_start.click()
    meter.audio_engine.feed(np.full((480, 2), 0.25, dtype=np.float32))
    meter.audio_engine.calibration.input_sensitivity = 1.0
    meter.audio_engine.calibration.input_sensitivity_is_calibrated = False
    widget.chk_volts.setChecked(True)
    widget.chk_dc.setChecked(True)
    widget.set_compact_mode(True)
    assert widget.unit_note.isVisible()
    assert "nominal" in widget.unit_note.text()
    meter.audio_engine.calibration.input_sensitivity = float("nan")
    widget._update_plot()
    assert widget._get_unit_label() == "FS"
    assert widget.plot_ch1.getAxis("left").labelUnits == "FS"
    assert "FS" in widget.lbl_dc_ch1.text()
    assert "FS" in widget.unit_note.text()
