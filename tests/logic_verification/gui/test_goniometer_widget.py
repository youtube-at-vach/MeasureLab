import time

import numpy as np
import pytest
from PyQt6.QtCore import QRectF
from PyQt6.QtWidgets import QApplication

from src.gui.widgets.goniometer import CorrelationMeter, Goniometer, GoniometerWidget


class MockAudioEngine:
    def __init__(self, *, fail_start: bool = False):
        self.sample_rate = 48000
        self.fail_start = fail_start
        self.callback = None
        self.unregistered: list[int] = []

    def register_callback(self, callback):
        if self.fail_start:
            raise RuntimeError("device unavailable")
        self.callback = callback
        return 11

    def unregister_callback(self, callback_id: int):
        self.unregistered.append(callback_id)


def _audio(left: np.ndarray, right: np.ndarray) -> np.ndarray:
    return np.column_stack((left, right))


def _invoke(module: Goniometer, data: np.ndarray) -> None:
    module._callback(data, np.zeros((len(data), 2)), len(data), None, None)


@pytest.fixture
def widget(qtbot):
    module = Goniometer(MockAudioEngine())
    result = GoniometerWidget(module)
    qtbot.addWidget(result)
    yield result
    result.timer.stop()
    module.stop_analysis()


def test_widget_restores_model_settings(qtbot):
    module = Goniometer(MockAudioEngine())
    module.manual_gain = 3.2
    module.effective_gain = 1.7
    module.auto_gain = True
    module.trace_mode = "Density"
    module.persistence_seconds = 1.25
    module.show_direction_guides = False
    module.show_axes = True
    module.show_grid = False

    widget = GoniometerWidget(module)
    qtbot.addWidget(widget)

    assert widget.gain_slider.value() == 32
    assert widget.gain_label.text() == "3.2x"
    assert widget.auto_gain_chk.isChecked()
    assert not widget.gain_slider.isEnabled()
    assert widget.trace_combo.currentData() == "Density"
    assert widget.persistence_label.text() == "1.25 s"
    assert not widget.direction_guides_chk.isChecked()
    assert widget.axes_chk.isChecked()
    assert not widget.grid_chk.isChecked()


def test_plot_guides_axes_and_grid_defaults_and_toggles(widget):
    plot_item = widget.plot_widget.getPlotItem()
    bottom_axis = plot_item.getAxis("bottom")
    left_axis = plot_item.getAxis("left")

    assert widget.direction_guides_chk.isChecked()
    assert len(widget._direction_labels) == 4
    assert not widget.axes_chk.isChecked()
    assert not bottom_axis.style["showValues"]
    assert not left_axis.style["showValues"]
    assert bottom_axis.labelText == ""
    assert left_axis.labelText == ""
    assert widget.grid_chk.isChecked()
    assert bottom_axis.grid
    assert left_axis.grid

    widget.direction_guides_chk.setChecked(False)
    widget.axes_chk.setChecked(True)
    widget.grid_chk.setChecked(False)

    assert widget._direction_labels == []
    assert bottom_axis.style["showValues"]
    assert left_axis.style["showValues"]
    assert bottom_axis.labelText == ""
    assert left_axis.labelText == ""
    assert not bottom_axis.grid
    assert not left_axis.grid


def test_ms_mapping_is_bounded_and_inversion_is_exact(widget):
    left = np.array([-1.0, -1.0, 1.0, 1.0])
    right = np.array([-1.0, 1.0, -1.0, 1.0])

    x, y = widget._compute_xy(left, right)

    assert np.max(np.abs(x)) <= 1.0
    assert np.max(np.abs(y)) <= 1.0
    widget.module.invert_x = True
    widget.module.invert_y = True
    inverted_x, inverted_y = widget._compute_xy(left, right)
    np.testing.assert_array_equal(inverted_x, -x)
    np.testing.assert_array_equal(inverted_y, -y)


def test_correlation_meter_maps_zero_to_center(qtbot):
    meter = CorrelationMeter()
    qtbot.addWidget(meter)
    rect = QRectF(10.0, 0.0, 200.0, 20.0)

    assert meter.value_to_x(-1.0, rect) == pytest.approx(10.0)
    assert meter.value_to_x(0.0, rect) == pytest.approx(110.0)
    assert meter.value_to_x(1.0, rect) == pytest.approx(210.0)
    meter.set_reading(None, None, None, "No signal")
    assert meter.accessibleDescription() == "No signal"


def test_start_failure_returns_button_to_idle(qtbot):
    module = Goniometer(MockAudioEngine(fail_start=True))
    widget = GoniometerWidget(module)
    qtbot.addWidget(widget)

    widget.toggle_btn.click()

    assert not widget.toggle_btn.isChecked()
    assert widget.toggle_btn.text() == "Start"
    assert "device unavailable" in widget.status_label.text()
    assert not widget.timer.isActive()


def test_hold_freezes_display_but_consumes_live_input(widget):
    widget.toggle_btn.click()
    tone = 0.5 * np.sin(np.linspace(0.0, 20.0, 1024))
    _invoke(widget.module, _audio(tone, tone))
    widget.update_display()
    before_x = widget.line_trace.xData.copy()
    first_total = widget._last_consumed_total

    widget.hold_btn.click()
    _invoke(widget.module, _audio(tone, -tone))
    widget.update_display()

    np.testing.assert_array_equal(widget.line_trace.xData, before_x)
    assert widget._last_consumed_total > first_total
    assert widget.status_label.text() == "Held — acquisition running"


def test_density_consumes_each_audio_block_once(widget):
    widget.module.trace_mode = "Density"
    widget._update_control_states()
    widget.toggle_btn.click()
    tone = 0.4 * np.sin(np.linspace(0.0, 20.0, 1024))
    _invoke(widget.module, _audio(tone, tone))

    widget.update_display()
    first_sum = float(np.sum(widget.module.heatmap))
    widget._last_display_time = time.monotonic() - 0.1
    widget.update_display()
    second_sum = float(np.sum(widget.module.heatmap))

    assert first_sum > 0.0
    assert second_sum < first_sum


def test_auto_gain_does_not_overwrite_manual_gain(widget):
    widget.module.manual_gain = 3.0
    widget.module.effective_gain = 3.0
    widget.auto_gain_chk.setChecked(True)
    x = np.array([-1.0, 1.0])
    y = np.array([-1.0, 1.0])

    effective = widget._update_auto_gain(x, y, 0.033)

    assert effective == pytest.approx(0.9)
    assert widget.module.manual_gain == pytest.approx(3.0)
    assert not widget.gain_slider.isEnabled()


def test_compact_mode_shows_only_main_plot(widget):
    widget.set_compact_mode(True)

    assert not hasattr(widget, "history_container")
    assert widget.controls_group.isHidden()
    assert widget.status_container.isHidden()
    assert widget.corr_container.isHidden()
    assert not widget.plot_widget.isHidden()
    margins = widget.layout().contentsMargins()
    assert (margins.left(), margins.top(), margins.right(), margins.bottom()) == (0, 0, 0, 0)
    assert widget.layout().spacing() == 0

    widget.set_compact_mode(False)

    assert not widget.controls_group.isHidden()
    assert not widget.status_container.isHidden()
    assert not widget.corr_container.isHidden()


def test_close_stops_timer_and_unregisters_callback(qtbot):
    engine = MockAudioEngine()
    module = Goniometer(engine)
    widget = GoniometerWidget(module)
    qtbot.addWidget(widget)
    widget.toggle_btn.click()
    assert widget.timer.isActive()

    widget.close()
    QApplication.processEvents()

    assert not widget.timer.isActive()
    assert not module.is_running
    assert engine.unregistered == [11]
