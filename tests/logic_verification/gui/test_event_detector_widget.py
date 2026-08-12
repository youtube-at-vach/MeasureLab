from unittest.mock import MagicMock

import numpy as np
from PyQt6.QtWidgets import QWidget

from src.core.event_detector import DetectorState, EventPolarity
from src.core.module_constants import ALL_MODULE_KEYS, MODULE_EVENT_DETECTOR, MODULE_RAW_TIME_SERIES
from src.gui.main_window import MODULE_REGISTRY, _load_module_class
from src.gui.widgets.detachable_wrapper import DetachableWidgetWrapper
from src.gui.widgets.event_detector import EventDetector, EventDetectorWidget
from src.gui.widgets.splittable_interface import SplittableWidgetInterface


def make_module(sample_rate=1000):
    callbacks = []
    engine = MagicMock()
    engine.sample_rate = sample_rate

    def register(callback):
        callbacks.append(callback)
        return 23

    engine.register_callback.side_effect = register
    return EventDetector(engine), callbacks


def test_event_detector_is_registered_after_raw_time_series():
    raw_index = ALL_MODULE_KEYS.index(MODULE_RAW_TIME_SERIES)
    assert ALL_MODULE_KEYS[raw_index + 1] == MODULE_EVENT_DETECTOR
    assert MODULE_REGISTRY[MODULE_EVENT_DETECTOR] == (
        "src.gui.widgets.event_detector",
        "EventDetector",
    )
    assert _load_module_class(MODULE_EVENT_DETECTOR) is EventDetector


def test_module_registers_callback_detects_selected_channel_and_stops():
    module, callbacks = make_module()
    module.input_channel = 1
    module.threshold = 0.5
    module.hysteresis = 0.1
    module.holdoff_ms = 0
    module.polarity = EventPolarity.POSITIVE

    module.start_analysis()
    assert module.is_running
    assert module.callback_id == 23
    assert len(callbacks) == 1

    indata = np.array([[0.8, 0.0], [0.9, 0.6], [0.9, 0.3]])
    outdata = np.ones((3, 2))
    callbacks[0](indata, outdata, 3, None, False)

    assert np.all(outdata == 0)
    assert module.get_snapshot().event_count == 1
    assert module.get_events()[0].polarity == EventPolarity.POSITIVE

    module.stop_analysis()
    assert not module.is_running
    assert module.callback_id is None
    assert module.get_snapshot().state == DetectorState.STOPPED
    module.audio_engine.unregister_callback.assert_called_once_with(23)

    module.stop_analysis()
    module.audio_engine.unregister_callback.assert_called_once()


def test_callback_falls_back_to_mono_and_latches_quality_warnings():
    module, callbacks = make_module()
    module.threshold = 0.5
    module.hysteresis = 0.1
    module.holdoff_ms = 0
    module.start_analysis()

    outdata = np.ones((3, 2))
    callbacks[0](np.array([0.0, 1.0, 0.0]), outdata, 3, None, True)

    snapshot = module.get_snapshot()
    assert snapshot.event_count == 1
    assert snapshot.clipping_detected
    assert snapshot.data_gap_detected


def test_widget_start_reset_stop_and_result_refresh(qtbot):
    module, callbacks = make_module()
    widget = EventDetectorWidget(module)
    qtbot.addWidget(widget)

    widget.spin_threshold.setValue(0.5)
    widget.spin_hysteresis.setValue(0.1)
    widget.spin_holdoff.setValue(0.0)
    widget.combo_polarity.setCurrentIndex(widget.combo_polarity.findData(EventPolarity.POSITIVE))
    widget.btn_start.click()

    assert module.is_running
    assert widget.timer.isActive()
    assert not widget.spin_threshold.isEnabled()
    assert widget.btn_start.text() == "Stop"

    outdata = np.zeros((3, 2))
    callbacks[0](np.array([[0.0, 0.0], [0.7, 0.0], [0.3, 0.0]]), outdata, 3, None, False)
    widget._update_results()
    assert widget.lbl_count.text() == "1"
    assert widget.lbl_state.text() == "ARMED"

    widget.btn_reset.click()
    assert widget.lbl_count.text() == "0"
    assert module.is_running

    widget.btn_start.click()
    assert not module.is_running
    assert not widget.timer.isActive()
    assert widget.spin_threshold.isEnabled()
    assert widget.lbl_state.text() == "STOPPED"


def test_widget_exposes_compact_and_split_panels(qtbot):
    module, _callbacks = make_module()
    widget = EventDetectorWidget(module)
    qtbot.addWidget(widget)

    assert isinstance(widget, SplittableWidgetInterface)
    assert isinstance(widget.get_display_widget(), QWidget)
    assert isinstance(widget.get_control_widget(), QWidget)

    widget.set_compact_mode(True)
    assert widget.control_widget.isHidden()
    widget.set_compact_mode(False)
    assert not widget.control_widget.isHidden()

    wrapper = DetachableWidgetWrapper(widget, "Event Detector")
    qtbot.addWidget(wrapper)
    wrapper.split()
    assert wrapper.is_split
    assert widget.display_widget.parent() is not widget
    assert widget.control_widget.parent() is not widget

    wrapper.reattach_all()
    assert not wrapper.is_split
    assert widget.display_widget.parent() is widget
    assert widget.control_widget.parent() is widget
