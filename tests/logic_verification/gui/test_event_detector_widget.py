import csv
import json
import threading
from unittest.mock import MagicMock

import numpy as np
import pytest
from PyQt6.QtWidgets import QWidget

from src.core.event_detector import DetectorState, EventDetectionMode, EventPolarity
from src.core.module_constants import ALL_MODULE_KEYS, MODULE_EVENT_DETECTOR, MODULE_RAW_TIME_SERIES
from src.gui.main_window import MODULE_REGISTRY, _load_module_class
from src.gui.styles import MONOSPACE_FONT_FAMILY
from src.gui.widgets.detachable_wrapper import DetachableWidgetWrapper
from src.gui.widgets.event_detector import EventDetector, EventDetectorWidget
from src.gui.widgets.splittable_interface import SplittableWidgetInterface


def make_module(
    sample_rate=1000,
    *,
    input_sensitivity=1.0,
    input_calibrated=False,
    detection_mode=EventDetectionMode.THRESHOLD_EVENTS,
):
    callbacks = []
    engine = MagicMock()
    engine.sample_rate = sample_rate
    engine.block_size = 1024
    engine.input_device = 1
    engine.output_device = 2
    engine.input_channel_mode = "stereo"
    engine.output_channel_mode = "stereo"
    engine.offline_mode = False
    engine.loopback = False
    engine.audio_engine_64bit = False
    engine.active_dtype = "float32"
    engine.is_active.return_value = True
    engine.calibration.input_sensitivity = input_sensitivity
    engine.calibration.input_sensitivity_is_calibrated = input_calibrated

    def register(callback):
        callbacks.append(callback)
        return 23

    engine.register_callback.side_effect = register
    module = EventDetector(engine)
    if detection_mode is not None:
        module.set_detection_mode(detection_mode)
    return module, callbacks


def test_event_detector_is_registered_after_raw_time_series():
    raw_index = ALL_MODULE_KEYS.index(MODULE_RAW_TIME_SERIES)
    assert ALL_MODULE_KEYS[raw_index + 1] == MODULE_EVENT_DETECTOR
    assert MODULE_REGISTRY[MODULE_EVENT_DETECTOR] == (
        "src.gui.widgets.event_detector",
        "EventDetector",
    )
    assert _load_module_class(MODULE_EVENT_DETECTOR) is EventDetector


def test_module_defaults_to_practical_clip_event_detection():
    module, callbacks = make_module(detection_mode=None)

    assert module.detection_mode == EventDetectionMode.CLIP_EVENTS
    assert module.fs_to_dbfs(module.threshold) == pytest.approx(-0.1)
    assert module.fs_to_dbfs(module.threshold - module.hysteresis) == pytest.approx(-1.0)
    assert module.polarity == EventPolarity.BOTH
    assert module.holdoff_ms == pytest.approx(10.0)

    module.start_analysis()
    samples = np.array([0.0, 0.99, 0.8, *([0.0] * 11), -1.0, -0.8])
    callbacks[0](samples, np.zeros_like(samples), len(samples), None, False)
    snapshot = module.get_snapshot()
    metadata = module.get_run_metadata()

    assert snapshot.event_count == 2
    assert snapshot.clipping_detected
    assert snapshot.measurement_valid
    assert metadata is not None
    assert metadata["detection_mode"] == "clip_events"
    assert metadata["clip_threshold_dbfs"] == pytest.approx(-0.1)
    assert metadata["clip_rearm_dbfs"] == pytest.approx(-1.0)
    assert metadata["clipping_invalidates_measurement"] is False


def test_widget_defaults_to_clip_mode_and_preserves_each_mode_profile(qtbot):
    module, _callbacks = make_module(detection_mode=None)
    widget = EventDetectorWidget(module)
    qtbot.addWidget(widget)

    assert widget.combo_mode.currentData() == EventDetectionMode.CLIP_EVENTS
    assert widget.spin_threshold.value() == pytest.approx(-0.1)
    assert widget.spin_hysteresis.value() == pytest.approx(-1.0)
    assert widget.combo_threshold_unit.isHidden()
    assert widget.combo_polarity.isHidden()
    assert widget.count_group.title() == "Clip Event Count"
    assert widget.rate_group.title() == "Clip Event Rate"
    assert widget.lbl_conditions.text() == "CH1  •  Clip ≥ -0.10 dBFS  •  1 kHz"

    widget.combo_mode.setCurrentIndex(widget.combo_mode.findData(EventDetectionMode.THRESHOLD_EVENTS))
    assert widget.spin_threshold.value() == pytest.approx(0.01)
    assert widget.spin_hysteresis.value() == pytest.approx(0.001)
    assert not widget.combo_threshold_unit.isHidden()
    assert not widget.combo_polarity.isHidden()
    widget.spin_threshold.setValue(0.5)

    widget.combo_mode.setCurrentIndex(widget.combo_mode.findData(EventDetectionMode.CLIP_EVENTS))
    assert widget.spin_threshold.value() == pytest.approx(-0.1)
    widget.combo_mode.setCurrentIndex(widget.combo_mode.findData(EventDetectionMode.THRESHOLD_EVENTS))
    assert widget.spin_threshold.value() == pytest.approx(0.5)


def test_widget_reports_detected_clips_without_invalidating_clip_measurement(qtbot):
    module, callbacks = make_module(detection_mode=None)
    widget = EventDetectorWidget(module)
    qtbot.addWidget(widget)
    widget.btn_start.click()

    samples = np.array([0.0, 1.0, 0.8])
    callbacks[0](samples, np.zeros_like(samples), len(samples), None, False)
    widget._update_results()

    assert widget.lbl_count.text() == "1"
    assert widget.lbl_rate.text().endswith(" clips/min")
    assert widget.lbl_clipping.isHidden()
    assert widget.lbl_last_event.text().startswith("Last clip event: #1")


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


def test_module_rejects_a_callback_registration_when_stream_is_inactive():
    module, callbacks = make_module()
    module.audio_engine.is_active.return_value = False

    with pytest.raises(RuntimeError, match="Audio stream failed to start"):
        module.start_analysis()

    assert len(callbacks) == 1
    assert not module.is_running
    assert module.callback_id is None
    assert module.get_run_metadata() is None
    assert module.get_snapshot().state == DetectorState.STOPPED
    module.audio_engine.unregister_callback.assert_called_once_with(23)


def test_module_fixed_duration_stops_at_an_exact_sample_count():
    module, callbacks = make_module(sample_rate=1000)
    module.set_target_duration(0.005)
    module.start_analysis()

    callbacks[0](np.zeros((3, 2)), np.zeros((3, 2)), 3, None, False)
    assert module.is_running
    assert module.get_snapshot().elapsed_seconds == pytest.approx(0.003)

    callbacks[0](np.zeros((5, 2)), np.zeros((5, 2)), 5, None, False)
    snapshot = module.get_snapshot()
    metadata = module.get_run_metadata()

    assert not module.is_running
    assert snapshot.state == DetectorState.STOPPED
    assert snapshot.processed_samples == 5
    assert snapshot.elapsed_seconds == pytest.approx(0.005)
    assert metadata is not None
    assert metadata["target_duration_seconds"] == pytest.approx(0.005)
    assert metadata["target_sample_count"] == 5
    assert metadata["stop_reason"] == "target_duration_reached"

    # Cleanup is intentionally completed outside the audio callback.
    module.stop_analysis()
    module.audio_engine.unregister_callback.assert_called_once_with(23)


def test_module_rejects_invalid_fixed_duration():
    module, _callbacks = make_module()

    with pytest.raises(ValueError, match="target duration"):
        module.set_target_duration(0)


def test_callback_processes_mono_ch1_and_latches_quality_warnings():
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


def test_callback_latches_a_gap_when_reported_frame_count_disagrees_with_input():
    module, callbacks = make_module()
    module.start_analysis()

    callbacks[0](np.zeros((3, 2)), np.zeros((3, 2)), 4, None, False)

    snapshot = module.get_snapshot()
    assert snapshot.processed_samples == 3
    assert snapshot.data_gap_detected
    assert not snapshot.measurement_valid


@pytest.mark.parametrize(
    "invalid_input",
    [
        np.array([0.0 + 0.0j, 0.7 + 0.1j, 0.0 + 0.0j]),
        np.array(["0.0", "0.7", "0.0"], dtype=object),
    ],
)
def test_callback_invalidates_unsupported_sample_types_without_escaping(invalid_input):
    module, callbacks = make_module()
    module.start_analysis()

    callbacks[0](invalid_input, np.zeros(3), len(invalid_input), None, False)

    snapshot = module.get_snapshot()
    assert snapshot.processed_samples == 0
    assert snapshot.data_gap_detected
    assert not snapshot.measurement_valid


def test_callback_invalidates_unreadable_sample_rate_instead_of_raising():
    module, callbacks = make_module()
    module.start_analysis()
    module.audio_engine.sample_rate = None

    callbacks[0](np.zeros((3, 2)), np.zeros((3, 2)), 3, None, False)

    snapshot = module.get_snapshot()
    assert snapshot.configuration_changed_detected
    assert not snapshot.measurement_valid


def test_running_measurement_keeps_its_frozen_input_channel():
    module, callbacks = make_module()
    module.threshold = 0.5
    module.hysteresis = 0.1
    module.holdoff_ms = 0
    module.polarity = EventPolarity.POSITIVE
    module.start_analysis()
    module.input_channel = 1

    callbacks[0](
        np.array([[0.0, 0.0], [0.0, 0.7], [0.0, 0.3]]),
        np.zeros((3, 2)),
        3,
        None,
        False,
    )

    assert module.get_snapshot().event_count == 0
    metadata = module.get_run_metadata()
    assert metadata is not None
    assert metadata["input_channel_index"] == 0
    assert metadata["input_channel"] == "CH1"


@pytest.mark.parametrize(
    ("attribute", "changed_value"),
    [
        ("input_device", 9),
        ("input_channel_mode", "left"),
        ("offline_mode", True),
        ("loopback", True),
        ("audio_engine_64bit", True),
        ("block_size", 256),
    ],
)
def test_stream_reroute_or_restart_invalidates_active_run(attribute, changed_value):
    module, callbacks = make_module()
    module.start_analysis()
    setattr(module.audio_engine, attribute, changed_value)

    callbacks[0](np.zeros((3, 2)), np.zeros((3, 2)), 3, None, False)

    snapshot = module.get_snapshot()
    assert snapshot.processed_samples == 0
    assert snapshot.configuration_changed_detected
    assert not snapshot.measurement_valid


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


def test_widget_flashes_event_activity_for_count_increase(qtbot):
    module, callbacks = make_module()
    widget = EventDetectorWidget(module)
    qtbot.addWidget(widget)

    widget.spin_threshold.setValue(0.5)
    widget.spin_hysteresis.setValue(0.1)
    widget.spin_holdoff.setValue(0.0)
    widget.combo_polarity.setCurrentIndex(widget.combo_polarity.findData(EventPolarity.POSITIVE))
    widget.btn_start.click()

    callbacks[0](
        np.array([[0.0, 0.0], [0.7, 0.0], [0.3, 0.0], [0.8, 0.0], [0.2, 0.0]]),
        np.zeros((5, 2)),
        5,
        None,
        False,
    )
    widget._update_results()

    assert widget.lbl_event_indicator.property("active") is True
    assert widget.lbl_event_delta.text() == "+2"
    assert widget.event_indicator_timer.isActive()
    assert widget.event_delta_timer.isActive()

    widget._turn_off_event_indicator()
    widget.event_indicator_timer.stop()
    widget._update_results()
    assert widget.lbl_event_indicator.property("active") is False

    widget._clear_event_delta()
    assert widget.lbl_event_delta.text() == ""


def test_widget_reset_and_manual_stop_clear_event_activity(qtbot):
    module, callbacks = make_module()
    widget = EventDetectorWidget(module)
    qtbot.addWidget(widget)
    widget.spin_threshold.setValue(0.5)
    widget.spin_hysteresis.setValue(0.1)
    widget.spin_holdoff.setValue(0.0)
    widget.btn_start.click()

    callbacks[0](
        np.array([[0.0, 0.0], [0.7, 0.0], [0.3, 0.0]]),
        np.zeros((3, 2)),
        3,
        None,
        False,
    )
    widget._update_results()
    assert widget.lbl_event_indicator.property("active") is True

    widget.btn_reset.click()
    assert widget.lbl_event_indicator.property("active") is False
    assert widget.lbl_event_delta.text() == ""
    assert widget._last_event_count == 0

    callbacks[0](
        np.array([[0.0, 0.0], [0.7, 0.0], [0.3, 0.0]]),
        np.zeros((3, 2)),
        3,
        None,
        False,
    )
    widget._update_results()
    assert widget.lbl_event_indicator.property("active") is True

    widget.btn_start.click()
    assert widget.lbl_event_indicator.property("active") is False
    assert widget.lbl_event_delta.text() == ""
    assert not widget.event_indicator_timer.isActive()
    assert not widget.event_delta_timer.isActive()


def test_widget_returns_to_idle_when_fixed_duration_completes(qtbot):
    module, callbacks = make_module(sample_rate=1000)
    widget = EventDetectorWidget(module)
    qtbot.addWidget(widget)
    widget.combo_duration.setCurrentIndex(widget.combo_duration.findData(1.0))
    widget.btn_start.click()

    callbacks[0](np.zeros((1000, 2)), np.zeros((1000, 2)), 1000, None, False)
    widget._update_results()

    assert not module.is_running
    assert not widget.btn_start.isChecked()
    assert widget.btn_start.text() == "Start"
    assert widget.spin_threshold.isEnabled()
    assert not widget.timer.isActive()
    module.audio_engine.unregister_callback.assert_called_once_with(23)


def test_widget_invalidates_and_stops_when_audio_stream_disappears(qtbot):
    module, _callbacks = make_module()
    widget = EventDetectorWidget(module)
    qtbot.addWidget(widget)
    widget.btn_start.click()
    module.audio_engine.is_active.return_value = False

    widget._update_results()

    snapshot = module.get_snapshot()
    metadata = module.get_run_metadata()
    assert not module.is_running
    assert not widget.btn_start.isChecked()
    assert not widget.timer.isActive()
    assert snapshot.data_gap_detected
    assert not snapshot.measurement_valid
    assert widget.lbl_count.text() == "INVALID"
    assert not widget.lbl_data_gap.isHidden()
    assert metadata is not None
    assert metadata["stop_reason"] == "audio_stream_inactive"
    module.audio_engine.unregister_callback.assert_called_once_with(23)


def test_widget_threshold_units_use_input_calibration_and_preserve_fs_values(qtbot):
    module, _callbacks = make_module(input_sensitivity=2.0, input_calibrated=True)
    widget = EventDetectorWidget(module)
    qtbot.addWidget(widget)

    assert [widget.combo_threshold_unit.itemData(i) for i in range(widget.combo_threshold_unit.count())] == [
        "FS",
        "mV",
        "V",
    ]

    widget.combo_threshold_unit.setCurrentIndex(widget.combo_threshold_unit.findData("V"))
    assert widget.spin_threshold.value() == pytest.approx(0.02)
    assert widget.spin_hysteresis.value() == pytest.approx(0.002)
    assert widget.spin_hysteresis.suffix() == " V"
    assert module.get_amplitude_display() == (2.0, "V")

    widget.spin_threshold.setValue(1.0)
    widget.spin_hysteresis.setValue(0.2)
    assert module.threshold == pytest.approx(0.5)
    assert module.hysteresis == pytest.approx(0.1)
    assert widget.lbl_conditions.text() == "CH1  •  ±1 V  •  1 kHz"
    assert widget.lbl_release.text() == "Release levels: ±0.8 V"

    widget.combo_threshold_unit.setCurrentIndex(widget.combo_threshold_unit.findData("mV"))
    assert widget.spin_threshold.value() == pytest.approx(1000.0)
    assert widget.spin_hysteresis.value() == pytest.approx(200.0)
    assert module.threshold == pytest.approx(0.5)
    assert module.hysteresis == pytest.approx(0.1)
    assert module.get_amplitude_display() == (2000.0, "mV")


def test_widget_amplitude_inputs_use_compact_display_precision(qtbot):
    module, _callbacks = make_module(input_sensitivity=0.25, input_calibrated=True)
    widget = EventDetectorWidget(module)
    qtbot.addWidget(widget)

    widget.combo_threshold_unit.setCurrentIndex(widget.combo_threshold_unit.findData("mV"))

    assert widget.spin_threshold.decimals() == 3
    assert widget.spin_hysteresis.decimals() == 3
    assert widget.spin_threshold.text() == "2.500"
    assert widget.spin_hysteresis.text() == "0.250 mV"


def test_widget_hides_voltage_threshold_units_without_input_calibration(qtbot):
    module, _callbacks = make_module(input_sensitivity=2.0, input_calibrated=False)
    widget = EventDetectorWidget(module)
    qtbot.addWidget(widget)

    assert [widget.combo_threshold_unit.itemData(i) for i in range(widget.combo_threshold_unit.count())] == ["FS"]
    assert module.get_amplitude_display() == (1.0, "FS")
    assert widget.lbl_calibration_status.text() == "Input: Uncalibrated (FS)"

    module.audio_engine.calibration.input_sensitivity_is_calibrated = True
    widget._update_results()
    assert [widget.combo_threshold_unit.itemData(i) for i in range(widget.combo_threshold_unit.count())] == [
        "FS",
        "mV",
        "V",
    ]


def test_voltage_threshold_is_normalized_to_fs_and_frozen_in_run_metadata(qtbot):
    module, callbacks = make_module(input_sensitivity=2.0, input_calibrated=True)
    widget = EventDetectorWidget(module)
    qtbot.addWidget(widget)
    widget.combo_threshold_unit.setCurrentIndex(widget.combo_threshold_unit.findData("mV"))
    widget.spin_threshold.setValue(1000.0)
    widget.spin_hysteresis.setValue(200.0)
    widget.spin_holdoff.setValue(0.0)
    widget.btn_start.click()

    callbacks[0](
        np.array([[0.0, 0.0], [0.7, 0.0], [0.3, 0.0]]),
        np.zeros((3, 2)),
        3,
        None,
        False,
    )
    metadata = module.get_run_metadata()
    assert metadata is not None
    assert metadata["threshold_fs_peak"] == pytest.approx(0.5)
    assert metadata["hysteresis_fs_peak"] == pytest.approx(0.1)
    assert metadata["threshold_display_unit"] == "mV"
    assert metadata["threshold_display_value"] == pytest.approx(1000.0)
    assert metadata["hysteresis_display_value"] == pytest.approx(200.0)
    assert module.get_snapshot().event_count == 1
    assert module.get_amplitude_display() == (2000.0, "mV")
    assert metadata["input_source"] == "hardware"
    assert metadata["audio_block_size_frames"] == 1024
    assert metadata["audio_engine_64bit_requested"] is False
    assert metadata["audio_stream_dtype"] == "float32"

    module.audio_engine.calibration.input_sensitivity = 4.0
    widget._update_results()
    assert widget.lbl_conditions.text() == "CH1  •  ±1000 mV  •  1 kHz"
    assert widget.lbl_calibration_status.text() == "Input: Calibrated (2 Vpeak/FS)"
    assert widget.lbl_distribution_unit.text() == "Unit: mV"
    assert widget.lbl_last_event.text().startswith("Last event: #1 • 1400 mV •")
    assert widget.events_table.item(0, 4).text() == "1400 mV"


def test_widget_summary_keeps_only_primary_measurement_information(qtbot):
    module, callbacks = make_module(sample_rate=48_000)
    widget = EventDetectorWidget(module)
    qtbot.addWidget(widget)

    assert widget.lbl_conditions.text() == "CH1  •  ±0.01 FS  •  48 kHz"
    assert not hasattr(widget, "lbl_definition")
    assert not hasattr(widget, "lbl_polarity_counts")

    widget.combo_channel.setCurrentIndex(widget.combo_channel.findData(1))
    widget.spin_threshold.setValue(0.5)
    widget.combo_polarity.setCurrentIndex(widget.combo_polarity.findData(EventPolarity.POSITIVE))
    assert widget.lbl_conditions.text() == "CH2  •  +0.5 FS  •  48 kHz"

    widget.spin_hysteresis.setValue(0.1)
    widget.spin_holdoff.setValue(0.0)
    widget.btn_start.click()
    callbacks[0](
        np.array([[0.0, 0.0], [0.0, 0.7], [0.0, 0.3]]),
        np.zeros((3, 2)),
        3,
        None,
        False,
    )
    widget._update_results()

    assert widget.lbl_last_event.text().startswith("Last event: #1 • 0.7 FS •")
    assert "Valid" not in widget.lbl_last_event.text()


def test_widget_elapsed_time_uses_platform_monospace_fonts(qtbot):
    module, _callbacks = make_module()
    widget = EventDetectorWidget(module)
    qtbot.addWidget(widget)

    assert f"font-family: {MONOSPACE_FONT_FAMILY};" in widget.lbl_elapsed.styleSheet()
    assert "font-family: monospace;" not in widget.lbl_elapsed.styleSheet()


def test_widget_summary_frames_do_not_move_with_display_digits(qtbot):
    module, _callbacks = make_module(sample_rate=48_000)
    widget = EventDetectorWidget(module)
    qtbot.addWidget(widget)
    widget.resize(1200, 700)
    widget.show()
    qtbot.wait(10)

    initial_geometries = (
        widget.count_group.geometry(),
        widget.rate_group.geometry(),
        widget.time_group.geometry(),
    )
    assert initial_geometries[0].width() == initial_geometries[1].width()
    assert initial_geometries[2].top() > initial_geometries[0].bottom()

    widget.lbl_count.setText("999,999,999,999")
    widget.lbl_rate.setText("999,999,999.9 events/min")
    widget.lbl_elapsed.setText("999999:59:59.9")
    widget.tabs.currentWidget().layout().activate()
    qtbot.wait(10)

    assert (
        widget.count_group.geometry(),
        widget.rate_group.geometry(),
        widget.time_group.geometry(),
    ) == initial_geometries


def test_widget_distribution_metrics_keep_fixed_cells_for_long_values(qtbot):
    module, _callbacks = make_module(sample_rate=48_000)
    widget = EventDetectorWidget(module)
    qtbot.addWidget(widget)
    widget.resize(1200, 700)
    widget.tabs.setCurrentIndex(1)
    widget.show()
    qtbot.wait(10)

    assert list(widget.distribution_stat_labels) == [
        "count",
        "minimum",
        "median",
        "mean",
        "standard_deviation",
        "percentile_95",
        "percentile_99",
        "maximum",
    ]
    initial_geometries = {key: cell.geometry() for key, cell in widget.distribution_stat_cells.items()}
    first_row_widths = {initial_geometries[key].width() for key in ("count", "minimum", "median", "mean")}
    assert len(first_row_widths) == 1
    assert initial_geometries["standard_deviation"].top() > initial_geometries["count"].bottom()

    for label in widget.distribution_stat_labels.values():
        label.setText("-999999999.999999")
    widget.tabs.currentWidget().layout().activate()
    qtbot.wait(10)

    assert {key: cell.geometry() for key, cell in widget.distribution_stat_cells.items()} == initial_geometries


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


def test_module_exports_auditable_csv_and_json_records(tmp_path):
    module, callbacks = make_module()
    module.threshold = 0.5
    module.hysteresis = 0.1
    module.holdoff_ms = 0
    module.polarity = EventPolarity.POSITIVE
    module.start_analysis()
    callbacks[0](
        np.array([[0.0, 0.0], [0.7, 0.0], [0.3, 0.0]]),
        np.zeros((3, 2)),
        3,
        None,
        False,
    )
    module.stop_analysis()

    csv_path = tmp_path / "events.csv"
    json_path = tmp_path / "events.json"
    module.export_events(str(csv_path))
    module.export_events(str(json_path))

    with csv_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))
    assert ["# MeasureLab Event Detector Export"] in rows
    assert any(row and row[0] == "sequence_number" for row in rows)

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["schema"] == "measurelab.event_detector"
    assert payload["run"]["measurement_valid"] is True
    assert payload["events"][0]["completion"] == "valid"
    assert payload["events"][0]["peak_fs"] == 0.7
    assert payload["amplitude_display_unit"] == "FS"
    assert payload["events"][0]["peak_display"] == 0.7


def test_export_captures_metadata_and_events_at_one_acquisition_boundary(tmp_path):
    module, callbacks = make_module()
    module.threshold = 0.5
    module.hysteresis = 0.1
    module.holdoff_ms = 0
    module.polarity = EventPolarity.POSITIVE
    module.start_analysis()

    export_reached_events = threading.Event()
    release_export = threading.Event()
    callback_started = threading.Event()
    callback_finished = threading.Event()
    original_get_events = module.get_events

    def delayed_get_events():
        export_reached_events.set()
        assert release_export.wait(timeout=2.0)
        return original_get_events()

    module.get_events = delayed_get_events
    export_errors = []
    export_path = tmp_path / "atomic-events.json"

    def run_export():
        try:
            module.export_events(str(export_path))
        except Exception as exc:  # pragma: no cover - asserted below
            export_errors.append(exc)

    def run_callback():
        callback_started.set()
        callbacks[0](
            np.array([[0.0, 0.0], [0.7, 0.0], [0.3, 0.0]]),
            np.zeros((3, 2)),
            3,
            None,
            False,
        )
        callback_finished.set()

    export_thread = threading.Thread(target=run_export)
    export_thread.start()
    assert export_reached_events.wait(timeout=2.0)

    callback_thread = threading.Thread(target=run_callback)
    callback_thread.start()
    assert callback_started.wait(timeout=2.0)
    callback_finished.wait(timeout=0.05)
    release_export.set()

    export_thread.join(timeout=2.0)
    callback_thread.join(timeout=2.0)
    assert not export_thread.is_alive()
    assert not callback_thread.is_alive()
    assert not export_errors

    payload = json.loads(export_path.read_text(encoding="utf-8"))
    recorded_count = payload["run"]["completed_event_count"] + payload["run"]["censored_event_count"]
    assert payload["run"]["retained_event_count"] == len(payload["events"])
    assert recorded_count == len(payload["events"])


def test_widget_shows_invalid_rate_after_input_gap(qtbot):
    module, callbacks = make_module()
    widget = EventDetectorWidget(module)
    qtbot.addWidget(widget)
    widget.spin_threshold.setValue(0.5)
    widget.spin_hysteresis.setValue(0.1)
    widget.btn_start.click()

    callbacks[0](np.zeros((3, 2)), np.zeros((3, 2)), 3, None, True)
    widget._update_results()

    assert widget.lbl_count.text() == "INVALID"
    assert widget.lbl_rate.text() == "INVALID"
    assert not widget.lbl_data_gap.isHidden()


def test_widget_plots_rate_bins_as_time_spans_instead_of_center_points(qtbot):
    module, callbacks = make_module(sample_rate=1000)
    widget = EventDetectorWidget(module)
    qtbot.addWidget(widget)
    widget.combo_rate_bin.setCurrentIndex(widget.combo_rate_bin.findData(10.0))
    widget.spin_threshold.setValue(0.5)
    widget.spin_hysteresis.setValue(0.1)
    widget.spin_holdoff.setValue(0.0)
    widget.btn_start.click()

    samples = np.zeros((12_000, 2))
    for start_sample in (1_000, 6_000, 11_000):
        samples[start_sample, 0] = 0.7
        samples[start_sample + 1, 0] = 0.3
    callbacks[0](samples, np.zeros_like(samples), len(samples), None, False)
    widget._refresh_analysis_views()

    x_data, y_data = widget.rate_curve.getData()
    assert widget.rate_curve.opts["stepMode"] == "center"
    assert x_data == pytest.approx([0.0, 10.0, 12.0])
    assert y_data == pytest.approx([12.0, 30.0])
    x_range, y_range = widget.plot_rate_trend.getViewBox().viewRange()
    assert x_range == pytest.approx([0.0, 100.0])
    assert y_range == pytest.approx([0.0, 50.0])

    callbacks[0](np.zeros((8_000, 2)), np.zeros((8_000, 2)), 8_000, None, False)
    widget._refresh_analysis_views()

    stable_x_range, stable_y_range = widget.plot_rate_trend.getViewBox().viewRange()
    assert stable_x_range == pytest.approx(x_range)
    assert stable_y_range == pytest.approx(y_range)

    widget.btn_reset.click()
    reset_x_range, reset_y_range = widget.plot_rate_trend.getViewBox().viewRange()
    assert reset_x_range == pytest.approx([0.0, 100.0])
    assert reset_y_range == pytest.approx([0.0, 1.0])


def test_sample_rate_change_invalidates_active_run():
    module, callbacks = make_module(sample_rate=1000)
    module.start_analysis()
    module.audio_engine.sample_rate = 2000

    callbacks[0](np.zeros((3, 2)), np.zeros((3, 2)), 3, None, False)

    snapshot = module.get_snapshot()
    assert snapshot.configuration_changed_detected
    assert not snapshot.measurement_valid
