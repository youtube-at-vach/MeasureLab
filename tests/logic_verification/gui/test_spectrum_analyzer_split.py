from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pytest
from PyQt6 import sip
from PyQt6.QtWidgets import QHBoxLayout, QWidget

from src.core.module_constants import MODULE_SPECTRUM_ANALYZER
from src.gui.module_registry import MODULE_REGISTRY
from src.gui.widgets.detachable_wrapper import DetachableWidgetWrapper
from src.gui.widgets.spectrum_analyzer import SpectrumAnalyzer, SpectrumAnalyzerWidget
from src.gui.widgets.splittable_interface import SplittableWidgetInterface


@pytest.fixture
def spectrum_widget(qapp):
    engine = MagicMock()
    engine.sample_rate = 48000
    engine.calibration = MagicMock()
    engine.calibration.input_sensitivity = 1.0
    engine.calibration.output_gain = 1.0
    engine.calibration.get_input_offset_db.return_value = 0.0
    engine.calibration.get_spl_offset_db.return_value = None
    engine.register_callback.return_value = 1

    widget = SpectrumAnalyzerWidget(SpectrumAnalyzer(engine))
    yield widget
    if not sip.isdeleted(widget):
        widget.timer.stop()
        widget.close()
        widget.deleteLater()
    qapp.processEvents()


@pytest.fixture
def spectrum_wrapper(spectrum_widget, qapp):
    wrapper = DetachableWidgetWrapper(
        spectrum_widget,
        "Spectrum Analyzer",
        capabilities=MODULE_REGISTRY[MODULE_SPECTRUM_ANALYZER].capabilities,
    )
    wrapper.show()
    yield wrapper
    if not sip.isdeleted(wrapper):
        if wrapper.is_split:
            wrapper.reattach_all()
        elif wrapper.is_detached:
            wrapper.reattach()
        spectrum_widget.setParent(None)
        wrapper.close()
        wrapper.deleteLater()
    qapp.processEvents()


def _performance_objects(widget: SpectrumAnalyzerWidget) -> dict[str, object]:
    names = (
        "timer",
        "plot_widget",
        "proxy",
        "v_line",
        "h_line",
        "plot_curve",
        "plot_curve_2",
        "peak_curve",
        "rta_bar_main",
        "rta_bar_left",
        "rta_bar_right",
        "controls_group",
        "display_widget",
    )
    return {name: getattr(widget, name) for name in names}


def _configure_live_result(widget: SpectrumAnalyzerWidget) -> None:
    freqs = np.linspace(0.0, 24000.0, 4097)
    magnitude = -60.0 + 4.0 * np.sin(np.linspace(0.0, 20.0, len(freqs)))
    widget.module.is_running = True
    widget.module.process_queue = MagicMock()
    widget.module.compute_spectrum = MagicMock(
        return_value={
            "freqs": freqs,
            "magnitude": magnitude,
            "overall_weighted_db": -24.0,
            "peak_magnitude": None,
        }
    )


def test_spectrum_analyzer_implements_split_interface(spectrum_widget):
    assert isinstance(spectrum_widget, SplittableWidgetInterface)
    assert isinstance(spectrum_widget.get_display_widget(), QWidget)
    assert isinstance(spectrum_widget.get_control_widget(), QWidget)
    assert spectrum_widget.get_display_widget() is spectrum_widget.display_widget
    assert spectrum_widget.get_control_widget() is spectrum_widget.controls_group


def test_spectrum_analyzer_controls_use_two_rows(spectrum_widget):
    controls_layout = spectrum_widget.controls_group.layout()

    assert controls_layout.count() == 2
    assert isinstance(controls_layout.itemAt(0).layout(), QHBoxLayout)
    assert isinstance(controls_layout.itemAt(1).layout(), QHBoxLayout)


def test_split_live_update_and_reattach_preserve_rendering_objects(spectrum_widget, spectrum_wrapper, qtbot):
    wrapper = spectrum_wrapper
    objects_before = _performance_objects(spectrum_widget)
    original_layout = spectrum_widget.layout()

    spectrum_widget.timer.start()
    assert spectrum_widget.timer.isActive()

    wrapper.split()
    qtbot.wait(1)

    assert wrapper.is_split
    assert spectrum_widget.display_widget.parent() is wrapper.split_display_window
    assert spectrum_widget.controls_group.parent() is wrapper.split_control_window
    assert spectrum_widget.timer.isActive()
    assert _performance_objects(spectrum_widget) == objects_before

    spectrum_widget.set_compact_mode(True)
    assert not spectrum_widget.controls_group.isHidden()
    assert spectrum_widget.overall_label.isHidden()
    assert spectrum_widget.cursor_label.isHidden()

    spectrum_widget.avg_slider.setValue(50)
    assert spectrum_widget.module.averaging == pytest.approx(0.5)

    _configure_live_result(spectrum_widget)
    spectrum_widget.update_plot()
    spectrum_widget.module.process_queue.assert_called_once_with()
    spectrum_widget.module.compute_spectrum.assert_called_once_with()
    assert spectrum_widget.plot_curve.xData is not None
    assert len(spectrum_widget.plot_curve.xData) > 0

    wrapper.reattach_all()
    qtbot.wait(1)

    assert not wrapper.is_split
    assert spectrum_widget.timer.isActive()
    assert _performance_objects(spectrum_widget) == objects_before
    assert spectrum_widget.display_widget.parent() is spectrum_widget
    assert spectrum_widget.controls_group.parent() is spectrum_widget
    assert original_layout.itemAt(0).widget() is spectrum_widget.controls_group
    assert original_layout.itemAt(1).widget() is spectrum_widget.display_widget
    assert not spectrum_widget.is_compact_mode()
    assert not spectrum_widget.overall_label.isHidden()
    assert not spectrum_widget.cursor_label.isHidden()


def test_split_compact_resizes_display_window(spectrum_widget, spectrum_wrapper, qtbot):
    wrapper = spectrum_wrapper
    wrapper.split()
    qtbot.wait(1)

    display_window = wrapper.split_display_window
    display_window.resize(800, 600)
    qtbot.wait(1)
    size_before = display_window.size()
    adjust_size = MagicMock(wraps=display_window.adjustSize)
    display_window.adjustSize = adjust_size

    wrapper.toggle_compact(True)
    qtbot.wait(10)

    assert spectrum_widget.is_compact_mode()
    adjust_size.assert_called()
    assert display_window.width() < size_before.width() or display_window.height() < size_before.height()


def test_closing_one_split_window_restores_state_a(spectrum_widget, spectrum_wrapper, qtbot):
    wrapper = spectrum_wrapper
    wrapper.split()
    qtbot.wait(1)

    wrapper.split_control_window.close()
    qtbot.wait(1)

    assert not wrapper.is_split
    assert wrapper.split_display_window is None
    assert wrapper.split_control_window is None
    assert spectrum_widget.controls_group.parent() is spectrum_widget
    assert spectrum_widget.display_widget.parent() is spectrum_widget


def test_detached_state_can_transition_to_split(spectrum_widget, spectrum_wrapper, qtbot):
    wrapper = spectrum_wrapper

    wrapper.detach()
    qtbot.wait(1)
    assert wrapper.is_detached

    wrapper.split()
    qtbot.wait(1)

    assert not wrapper.is_detached
    assert wrapper.is_split
    assert spectrum_widget.display_widget.parent() is wrapper.split_display_window
    assert spectrum_widget.controls_group.parent() is wrapper.split_control_window

    wrapper.reattach_all()
    spectrum_widget.last_freqs = np.array([20.0, 1000.0])
    spectrum_widget.last_mags = np.array([-40.0, -20.0])
    assert spectrum_widget.get_comparable_data()
