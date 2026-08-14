import os
import threading
from unittest.mock import MagicMock

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.gui.widgets import loopback_finder as loopback_module  # noqa: E402


class _CallbackStop(Exception):
    pass


class _CallbackAbort(Exception):
    pass


@pytest.fixture(autouse=True)
def _restore_sounddevice_callback_exceptions(monkeypatch):
    """Keep these tests independent of AudioEngine's module-level sd mock."""
    monkeypatch.setattr(loopback_module.sd, "CallbackStop", _CallbackStop)
    monkeypatch.setattr(loopback_module.sd, "CallbackAbort", _CallbackAbort)


def _device_engine():
    engine = MagicMock()
    engine.input_device = 0
    engine.output_device = 1
    engine.sample_rate = 48_000
    engine.offline_mode = False
    engine.is_active.return_value = False
    devices = [
        {"name": "Test Input", "max_input_channels": 2, "max_output_channels": 0},
        {"name": "Test Output", "max_input_channels": 0, "max_output_channels": 2},
    ]
    engine._get_cached_audio_info.return_value = (devices, ())
    return engine


class _Status:
    input_underflow = False
    input_overflow = False
    output_underflow = False
    output_overflow = False


class _SimulatedStream:
    def __init__(self, *, loopbacks=None, clip=False, input_overflow=False, **kwargs):
        self.callback = kwargs["callback"]
        self.finished_callback = kwargs["finished_callback"]
        self.input_channels, self.output_channels = kwargs["channels"]
        self.sample_rate = int(kwargs["samplerate"])
        self.loopbacks = loopbacks or {}
        self.clip = clip
        self.input_overflow = input_overflow
        self.active = True

    def __enter__(self):
        frames = 480
        previous_output = np.zeros((frames, self.output_channels), dtype=np.float32)
        status = _Status()
        status.input_overflow = self.input_overflow
        try:
            for _ in range(1000):
                if not self.active:
                    break
                indata = np.zeros((frames, self.input_channels), dtype=np.float32)
                for output_index, input_index in self.loopbacks.items():
                    indata[:, input_index] += previous_output[:, output_index]
                if self.clip:
                    indata[:, 0] = 1.0
                outdata = np.zeros((frames, self.output_channels), dtype=np.float32)
                self.callback(indata, outdata, frames, None, status)
                previous_output = outdata.copy()
        except loopback_module.sd.CallbackStop:
            self.active = False
        except loopback_module.sd.CallbackAbort:
            self.active = False
        self.finished_callback()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.active = False

    def abort(self):
        self.active = False
        self.finished_callback()


def _run_scan(monkeypatch, *, loopbacks=None, clip=False, input_overflow=False, cancelled=False):
    engine = _device_engine()
    finder = loopback_module.LoopbackFinder(engine)

    def stream_factory(**kwargs):
        return _SimulatedStream(
            loopbacks=loopbacks,
            clip=clip,
            input_overflow=input_overflow,
            **kwargs,
        )

    monkeypatch.setattr(loopback_module.sd, "Stream", stream_factory)
    cancel_event = threading.Event()
    if cancelled:
        cancel_event.set()
    progress = MagicMock()
    result = finder.perform_scan(
        (0, 1),
        engine.sample_rate,
        finder.profile,
        cancel_event,
        progress,
    )
    return finder, result, progress


def test_scan_detects_only_the_simulated_routes(monkeypatch):
    _, result, progress = _run_scan(monkeypatch, loopbacks={0: 0, 1: 1})

    assert result.state == loopback_module.ScanTerminalState.COMPLETED
    assert result.detected_count == 2
    detected_pairs = {
        (item.output_channel, item.input_channel)
        for item in result.measurements
        if item.verdict == loopback_module.PairVerdict.DETECTED
    }
    assert detected_pairs == {(1, 1), (2, 2)}
    assert progress.call_count == 3


def test_scan_reports_a_valid_no_path_result(monkeypatch):
    _, result, _ = _run_scan(monkeypatch)

    assert result.state == loopback_module.ScanTerminalState.COMPLETED
    assert result.detected_count == 0
    assert all(item.verdict == loopback_module.PairVerdict.NOT_DETECTED for item in result.measurements)


def test_steady_tone_present_in_baseline_is_not_accepted_as_a_route():
    engine = _device_engine()
    finder = loopback_module.LoopbackFinder(engine)
    profile = finder.profile
    sample_rate = 48_000
    baseline_frames = int(sample_rate * profile.baseline_duration_s)
    tone_frames = int(sample_rate * profile.tone_duration_s)
    step_frames = int(
        sample_rate * (profile.baseline_duration_s + profile.tone_duration_s + profile.tail_duration_s)
    )
    phase = np.arange(step_frames)
    ambient = 0.1 * np.sin(2 * np.pi * profile.frequency_hz * phase / sample_rate)
    buffer = ambient.astype(np.float32)[:, np.newaxis]
    reference = np.exp(-2j * np.pi * profile.frequency_hz * np.arange(tone_frames) / sample_rate)

    measurements, _ = finder._analyze_output_buffer(
        buffer,
        1,
        sample_rate,
        profile,
        reference,
        baseline_frames,
        tone_frames,
    )

    assert measurements[0].level_dbfs > profile.absolute_threshold_dbfs
    assert measurements[0].margin_db < profile.minimum_margin_db
    assert measurements[0].verdict == loopback_module.PairVerdict.UNCERTAIN


def test_clipping_invalidates_the_affected_input_column(monkeypatch):
    _, result, _ = _run_scan(monkeypatch, loopbacks={1: 1}, clip=True)

    assert result.state == loopback_module.ScanTerminalState.INVALID
    assert result.clipped_inputs == (1,)
    assert all(
        item.verdict == loopback_module.PairVerdict.INVALID
        for item in result.measurements
        if item.input_channel == 1
    )
    assert any(
        item.verdict == loopback_module.PairVerdict.DETECTED
        for item in result.measurements
        if item.input_channel == 2
    )


def test_xrun_invalidates_all_measurements(monkeypatch):
    _, result, _ = _run_scan(monkeypatch, loopbacks={0: 0}, input_overflow=True)

    assert result.state == loopback_module.ScanTerminalState.INVALID
    assert result.io_errors == ("input_overflow",)
    assert all(item.verdict == loopback_module.PairVerdict.INVALID for item in result.measurements)


def test_analysis_queue_overrun_is_reported_as_invalid_io(monkeypatch):
    engine = _device_engine()
    engine._get_cached_audio_info.return_value[0][1]["max_output_channels"] = 4
    finder = loopback_module.LoopbackFinder(engine)
    monkeypatch.setattr(loopback_module.sd, "Stream", lambda **kwargs: _SimulatedStream(**kwargs))

    result = finder.perform_scan((0, 1), 48_000, finder.profile, threading.Event())

    assert result.state == loopback_module.ScanTerminalState.INVALID
    assert result.completed_outputs == 3
    assert result.io_errors == ("analysis_buffer_overrun",)


def test_cancelled_scan_does_not_report_partial_data_as_complete(monkeypatch):
    _, result, _ = _run_scan(monkeypatch, loopbacks={0: 0}, cancelled=True)

    assert result.state == loopback_module.ScanTerminalState.CANCELLED
    assert result.completed_outputs == 0
    assert result.detected_count == 0


def test_invalid_device_configuration_is_rejected(monkeypatch):
    engine = _device_engine()
    engine._get_cached_audio_info.return_value = (
        [
            {"name": "Output only", "max_input_channels": 0, "max_output_channels": 2},
            {"name": "Output", "max_input_channels": 0, "max_output_channels": 2},
        ],
        (),
    )
    finder = loopback_module.LoopbackFinder(engine)

    with np.testing.assert_raises_regex(ValueError, "at least one input"):
        finder.perform_scan((0, 1), 48_000, finder.profile, threading.Event())


def test_connection_matrix_uses_text_and_color_independent_symbols(qtbot):
    engine = _device_engine()
    finder = loopback_module.LoopbackFinder(engine)
    widget = loopback_module.LoopbackFinderWidget(finder)
    qtbot.addWidget(widget)
    measurement = loopback_module.PairMeasurement(
        output_channel=1,
        input_channel=2,
        level_dbfs=-6.1,
        baseline_dbfs=-90.0,
        margin_db=83.9,
        verdict=loopback_module.PairVerdict.DETECTED,
    )
    result = loopback_module.ScanResult(
        state=loopback_module.ScanTerminalState.COMPLETED,
        measurements=(measurement,),
        profile=finder.profile,
        input_device_name="Test Input",
        output_device_name="Test Output",
        sample_rate=48_000,
        input_channels=2,
        output_channels=2,
        completed_outputs=2,
    )

    widget._on_scan_completed(result)

    assert widget.results_table.rowCount() == 2
    assert widget.results_table.columnCount() == 2
    assert widget.results_table.item(0, 1).text().startswith("✓")
    assert widget.results_table.item(0, 0).text() == "—"
    assert widget.validity_label.text() == "VALID"
    assert "1" in widget.summary_label.text()


def test_virtual_mode_disables_physical_scan(qtbot):
    engine = _device_engine()
    engine.offline_mode = True
    finder = loopback_module.LoopbackFinder(engine)
    widget = loopback_module.LoopbackFinderWidget(finder)
    qtbot.addWidget(widget)

    assert not widget.start_btn.isEnabled()
    assert "Virtual" in widget.status_label.text()
