from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pytest
from PyQt6 import sip
from PyQt6.QtWidgets import QWidget

from src.core.config_manager import ConfigManager
from src.core.module_constants import MODULE_LOCKIN_SPECTRUM_FINDER
from src.gui.module_registry import MODULE_REGISTRY
from src.gui.widgets.compactable_interface import CompactableWidgetInterface
from src.gui.widgets.detachable_wrapper import DetachableWidgetWrapper
from src.gui.widgets.lockin_spectrum_finder import LockInSpectrumFinder, LockInSpectrumFinderWidget
from src.gui.widgets.splittable_interface import SplittableWidgetInterface


@pytest.fixture
def lockin_widget(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(ConfigManager, "get_user_data_dir", lambda: str(tmp_path))

    engine = MagicMock()
    engine.sample_rate = 48000
    engine.calibration = MagicMock()
    engine.calibration.get_input_offset_db.return_value = 0.0
    engine.calibration.get_spl_offset_db.return_value = None
    engine.register_callback.return_value = 1

    module = LockInSpectrumFinder(engine)
    widget = LockInSpectrumFinderWidget(module)
    yield widget

    widget.timer.stop()
    module.stop_analysis()
    module.executor.shutdown(wait=True, cancel_futures=True)
    module.io_executor.shutdown(wait=True, cancel_futures=True)
    if not sip.isdeleted(widget):
        widget.close()
        widget.deleteLater()
    qapp.processEvents()


@pytest.fixture
def lockin_wrapper(lockin_widget, qapp):
    wrapper = DetachableWidgetWrapper(
        lockin_widget,
        "Lock-in Spectrum Finder",
        capabilities=MODULE_REGISTRY[MODULE_LOCKIN_SPECTRUM_FINDER].capabilities,
    )
    wrapper.show()
    yield wrapper

    if not sip.isdeleted(wrapper):
        if wrapper.is_split:
            wrapper.reattach_all()
        elif wrapper.is_detached:
            wrapper.reattach()
        lockin_widget.setParent(None)
        wrapper.close()
        wrapper.deleteLater()
    qapp.processEvents()


def _stateful_objects(widget: LockInSpectrumFinderWidget) -> dict[str, object]:
    return {
        name: getattr(widget, name)
        for name in (
            "timer",
            "tabs",
            "lbl_status",
            "plot",
            "curve",
            "scatter",
            "controls_widget",
            "display_widget",
        )
    }


def test_lockin_finder_implements_split_interface(lockin_widget):
    assert isinstance(lockin_widget, SplittableWidgetInterface)
    assert isinstance(lockin_widget.get_display_widget(), QWidget)
    assert isinstance(lockin_widget.get_control_widget(), QWidget)
    assert lockin_widget.get_display_widget() is lockin_widget.display_widget
    assert lockin_widget.get_control_widget() is lockin_widget.controls_widget


def test_compact_mode_keeps_only_right_plot_zone(lockin_widget):
    assert isinstance(lockin_widget, CompactableWidgetInterface)
    assert not lockin_widget.controls_widget.isHidden()
    assert not lockin_widget.display_widget.isHidden()

    lockin_widget.set_compact_mode(True)

    assert lockin_widget.is_compact_mode()
    assert lockin_widget.controls_widget.isHidden()
    assert not lockin_widget.display_widget.isHidden()

    lockin_widget.set_compact_mode(False)

    assert not lockin_widget.is_compact_mode()
    assert not lockin_widget.controls_widget.isHidden()
    assert not lockin_widget.display_widget.isHidden()


def test_split_compact_mode_leaves_control_window_available(lockin_widget, lockin_wrapper, qtbot):
    lockin_wrapper.split()
    qtbot.wait(1)

    lockin_wrapper.toggle_compact(True)

    assert lockin_widget.is_compact_mode()
    assert not lockin_widget.controls_widget.isHidden()
    assert not lockin_widget.display_widget.isHidden()


def test_split_live_update_and_reattach_preserve_state(lockin_widget, lockin_wrapper, qtbot):
    wrapper = lockin_wrapper
    original_layout = lockin_widget.layout()
    objects_before = _stateful_objects(lockin_widget)

    lockin_widget.timer.start()
    wrapper.split()
    qtbot.wait(1)

    assert wrapper.is_split
    assert wrapper.split_btn is not None
    assert lockin_widget.display_widget.parent() is wrapper.split_display_window
    assert lockin_widget.controls_widget.parent() is wrapper.split_control_window
    assert lockin_widget.timer.isActive()
    assert _stateful_objects(lockin_widget) == objects_before

    lockin_widget.spin_points.setValue(320)
    assert lockin_widget.module.points == 320

    freqs = np.array([100.0, 200.0, 300.0, 400.0])
    mags = np.array([-60.0, -50.0, -40.0, -30.0])
    phases = np.zeros(4)
    lockin_widget.on_sweep_started((freqs, [200.0]))
    lockin_widget.on_progress_update(0, len(freqs), freqs, mags, phases)

    assert lockin_widget.curve.xData is not None
    assert np.array_equal(lockin_widget.curve.xData, freqs)
    assert "Calculating" in lockin_widget.lbl_status.text()

    wrapper.reattach_all()
    qtbot.wait(1)

    assert not wrapper.is_split
    assert lockin_widget.timer.isActive()
    assert _stateful_objects(lockin_widget) == objects_before
    assert lockin_widget.controls_widget.parent() is lockin_widget
    assert lockin_widget.display_widget.parent() is lockin_widget
    assert original_layout.itemAt(0).widget() is lockin_widget.controls_widget
    assert original_layout.itemAt(1).widget() is lockin_widget.display_widget
    assert original_layout.stretch(0) == 1
    assert original_layout.stretch(1) == 3


def test_closing_one_split_window_restores_state_a(lockin_widget, lockin_wrapper, qtbot):
    wrapper = lockin_wrapper
    wrapper.split()
    qtbot.wait(1)

    wrapper.split_control_window.close()
    qtbot.wait(1)

    assert not wrapper.is_split
    assert wrapper.split_display_window is None
    assert wrapper.split_control_window is None
    assert lockin_widget.controls_widget.parent() is lockin_widget
    assert lockin_widget.display_widget.parent() is lockin_widget


def test_detached_state_can_transition_to_split(lockin_widget, lockin_wrapper, qtbot):
    wrapper = lockin_wrapper
    wrapper.detach()
    qtbot.wait(1)
    assert wrapper.is_detached

    wrapper.split()
    qtbot.wait(1)

    assert not wrapper.is_detached
    assert wrapper.is_split
    assert lockin_widget.display_widget.parent() is wrapper.split_display_window
    assert lockin_widget.controls_widget.parent() is wrapper.split_control_window

    wrapper.reattach_all()
    assert lockin_widget.layout().itemAt(0).widget() is lockin_widget.controls_widget
    assert lockin_widget.layout().itemAt(1).widget() is lockin_widget.display_widget


def test_settings_pages_preserve_controls_and_leave_plot_room(lockin_widget, qapp):
    widget = lockin_widget
    widget.resize(1000, 600)
    widget.show()
    qapp.processEvents()
    widget.spin_points.setValue(320)
    for index in range(widget.tabs.count()):
        widget.section_selector.setCurrentIndex(index)
        qapp.processEvents()
        assert widget.tabs.currentIndex() == index
        assert widget.btn_toggle.isVisible()
        assert widget.display_widget.width() > widget.width() * 0.6
        assert widget.tabs.currentWidget().horizontalScrollBar().maximum() == 0
        assert widget.module.points == 320


@pytest.mark.parametrize("mode", ["Scan", "Zoom"])
def test_measurement_and_acquisition_controls_fit_together(lockin_widget, qapp, mode):
    widget = lockin_widget
    widget.resize(1000, 600)
    widget.combo_mode.setCurrentIndex(widget.combo_mode.findData(mode))
    widget.show()
    qapp.processEvents()
    for control in (
        widget.combo_mode,
        widget.combo_input_ch,
        widget.spin_points,
        widget.spin_averages,
        widget.combo_buffer,
        widget.combo_window,
        widget.combo_unit,
    ):
        assert control.isVisible()
    page = widget.tabs.currentWidget()
    assert page.horizontalScrollBar().maximum() == 0
    assert page.verticalScrollBar().maximum() == 0


def test_mode_specific_fields_and_status_in_compact_display(lockin_widget, qapp):
    widget = lockin_widget
    widget.show()
    widget.combo_spacing.setCurrentIndex(widget.combo_spacing.findData("1/3 Octave"))
    assert not widget.spin_octave_ref.isHidden()
    widget.combo_spacing.setCurrentIndex(widget.combo_spacing.findData("Scan List Only"))
    assert widget.spin_octave_ref.isHidden()
    assert not widget.chk_log_axis.isHidden()
    widget.combo_mode.setCurrentIndex(widget.combo_mode.findData("Zoom"))
    assert widget.spin_start_f.isHidden()
    assert widget.chk_log_axis.isHidden()
    assert not widget.spin_zoom_center.isHidden()
    widget.set_compact_mode(True)
    widget.lbl_status.setText("Calculating... 50%")
    qapp.processEvents()
    assert widget.lbl_status.isVisible()
    assert widget.display_widget.isAncestorOf(widget.lbl_status)


def test_console_action_runs_from_any_page_and_compact_mode(lockin_widget, lockin_wrapper, qapp, monkeypatch):
    from src.gui.measurement_console import InstrumentDockWidget, PrimaryActionStopResult

    theme = MagicMock()
    theme.get_current_theme.return_value = "dark"
    monkeypatch.setattr(qapp, "theme_manager", theme, raising=False)
    dock = InstrumentDockWidget("Finder", 0, "lockin_spectrum_finder")
    dock.set_instrument_widget(lockin_wrapper)
    try:
        lockin_widget.section_selector.setCurrentIndex(lockin_widget.tabs.count() - 1)
        lockin_widget.set_compact_mode(True)
        assert dock._primary_button is not None
        dock._primary_button.click()
        assert lockin_widget.module.is_running
        assert lockin_widget.timer.isActive()
        assert lockin_widget.lbl_status.text() == "Buffering..."
        assert dock.stop_primary_action() == PrimaryActionStopResult.STOPPED
        assert not lockin_widget.module.is_running
        assert not lockin_widget.timer.isActive()
        assert lockin_widget.lbl_status.text() == "Stopped"
    finally:
        dock.take_instrument_widget()
        dock.close()
        dock.deleteLater()
