import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pytest

from src.core.audio_engine import AudioEngine
from src.core.calibration import CalibrationManager
from src.core.imd_sweep import BandPlan, SweepSettings, snapshot_copy
from src.core.imd_sweep_acquisition import StepCapture, SweepAcquisition
from src.core.settings_generation import SettingsGeneration
from src.gui.widgets.distortion_analyzer import DistortionAnalyzer, DistortionAnalyzerWidget
from src.gui.widgets.imd_sweep_worker import IMDSweepWorker
from src.gui.widgets.imd_sweep_ui import IMDExportWorker


class FakeEngine(SettingsGeneration):
    _measurement_fields = AudioEngine._measurement_fields

    def __init__(self, tmp_path):
        self.sample_rate = 48000
        self.block_size = 480
        self.input_channel_mode = self.output_channel_mode = "stereo"
        self.input_device = self.output_device = None
        self.offline_mode = True
        self.network_mode = False
        self.loopback = True
        self.dithering_enabled = False
        self.dithering_bit_depth = "24"
        self.mute_output = False
        self.output_overload_events = 0
        self.callback_error_count = 0
        self.calibration = CalibrationManager(str(tmp_path / "cal.json"))
        self.thread = None
        self.running = True
        self.hook = lambda *args: None
        self.tick = 0
        self.registered = 0

    def is_active(self):
        return self.running

    def ensure_stream_running(self):
        return self.running

    def register_callback(self, callback):
        self.registered += 1

        def pump():
            n = 0
            while self.running:
                t = (np.arange(480) + n) / 48000
                wave = (
                    0.4 * np.sin(2 * np.pi * 60 * t)
                    + 0.1 * np.sin(2 * np.pi * 7000 * t)
                    + 0.001 * np.sin(2 * np.pi * 6940 * t)
                )
                data = np.column_stack((wave, wave))
                out = np.zeros_like(data)
                status = SimpleNamespace(input_overflow=False)
                self.tick += 1
                self.hook(self, data, status)
                callback(data, out, 480, None, status)
                n += 480
                time.sleep(0.001)

        self.thread = threading.Thread(target=pump)
        self.thread.start()
        return 1

    def unregister_callback(self, cid):
        self.running = False
        if self.thread:
            self.thread.join(2)


@pytest.fixture
def setup(tmp_path):
    engine = FakeEngine(tmp_path)
    module = DistortionAnalyzer(engine)
    worker = IMDSweepWorker(module, SweepSettings(steps=2, settling_ms=100, capture_ms=200, averages=2))
    yield engine, module, worker
    worker.stop()
    engine.running = False
    if engine.thread:
        engine.thread.join(2)


def test_completed_snapshot_and_contiguous_records(setup):
    engine, module, worker = setup
    worker.run()
    result = worker.snapshot
    assert result["status"] == "completed" and result["complete"]
    assert result["quality"] == "qualified"
    assert not module.is_running
    for step in result["steps"]:
        assert step["percent"] == pytest.approx(1, abs=0.001)
        assert step["record_count"] == 2
        assert step["sample_end"] - step["sample_start"] == 19200
        assert step["sample_start"] >= 5760
        assert step["output_clipping"] is None
    assert result["metadata"]["calibration"]["input_sensitivity_Vpeak_per_FS"] is None


@pytest.mark.parametrize(
    "fault",
    [
        "clip",
        "nan",
        "mute_restore",
        "cal_restore",
        "rate_restore",
        "module_restore",
        "overload",
        "exception",
        "cancel",
        "xrun",
        "missing",
    ],
)
def test_failure_policies_and_previous_steps(setup, fault):
    engine, module, worker = setup
    triggered = False

    def hook(e, data, status):
        nonlocal triggered
        command = worker.acquisition.command
        if command is None or command.identity[1] != 1 or command.settling > 0 or triggered:
            return
        triggered = True
        if fault == "clip":
            data[0, 0] = 1
        elif fault == "nan":
            data[0, 0] = np.nan
        elif fault == "mute_restore":
            e.mute_output = True
            e.mute_output = False
        elif fault == "cal_restore":
            e.calibration.input_sensitivity = 2
            e.calibration.input_sensitivity = 1
        elif fault == "rate_restore":
            e.sample_rate = 96000
            e.sample_rate = 48000
        elif fault == "module_restore":
            module.input_channel = 1
            module.input_channel = 0
        elif fault == "overload":
            e.output_overload_events += 1
        elif fault == "exception":
            e.callback_error_count += 1
        elif fault == "cancel":
            worker.stop()
        elif fault == "xrun":
            status.input_overflow = True
        elif fault == "missing":
            worker.acquisition.command.flags.add("input_discontinuity")

    engine.hook = hook
    worker.run()
    result = worker.snapshot
    assert triggered
    assert len(result["steps"]) == 2
    assert result["steps"][0]["validity"] == "qualified"
    assert result["steps"][0]["percent"] == pytest.approx(1, abs=0.001)
    assert result["steps"][1]["validity"] == "invalid" and result["steps"][1]["ratio"] is None
    assert result["quality"] == "invalid"
    assert result["status"] == (
        "cancelled" if fault == "cancel" else "completed" if fault in ("xrun", "missing") else "failed"
    )
    assert not result["complete"]


@pytest.mark.parametrize("fault", ["muted", "channel", "rate", "calibration", "start"])
def test_preflight_never_registers_output(setup, fault):
    engine, module, worker = setup
    if fault == "muted":
        engine.mute_output = True
    if fault == "channel":
        module.input_channel = 2
    if fault == "rate":
        engine.sample_rate = 12000
    if fault == "calibration":
        engine.calibration.input_sensitivity = np.nan
    if fault == "start":
        engine.running = False
    worker.run()
    assert worker.snapshot["status"] == "failed" and not worker.snapshot["steps"]
    assert engine.registered == 0


def test_timeout_and_no_stale_average(setup):
    engine, module, worker = setup

    def register(callback):
        return 1

    engine.register_callback = register
    worker.run()
    assert worker.snapshot["reason"] == "capture_timeout"
    assert worker.snapshot["steps"][0]["record_count"] == 0
    assert worker.snapshot["steps"][0]["ratio"] is None


def test_callback_record_identity_overflow_and_fade(tmp_path):
    engine = FakeEngine(tmp_path)
    plan = BandPlan(SweepSettings(steps=2, settling_ms=100, capture_ms=200, averages=5), 48000)
    acq = SweepAcquisition(engine, plan, 0, 0, engine.settings_generation, engine.calibration.settings_generation)
    capture = StepCapture("run", 0, -3, plan)
    acq.command = capture
    inp = np.zeros((480, 2))
    out = np.zeros_like(inp)
    for _ in range(100):
        acq.callback(inp, out, 480, None, None)
    assert len(capture.ready) == 3
    assert capture.flags == {"input_discontinuity"}
    assert all(entry[0] == ("run", 0) for entry in capture.ready)
    assert capture.ready[0][3] == 5760
    assert np.max(abs(out)) <= 10 ** (-3 / 20)
    phase = (acq.phase1, acq.phase2)
    acq.stopping = True
    acq.callback(inp, out, 480, None, None)
    assert not acq.silent
    acq.callback(inp, out, 480, None, None)
    assert acq.silent and (acq.phase1, acq.phase2) != phase


def test_widget_retains_snapshot_compare_reset_and_export(qtbot, setup, tmp_path):
    engine, module, worker = setup
    worker.run()
    module.imd_snapshot = snapshot_copy(worker.snapshot)
    widget = DistortionAnalyzerWidget(module)
    qtbot.addWidget(widget)
    widget.mode_combo.setCurrentIndex(3)
    traces = widget.get_comparable_data()
    assert len(traces) == 1 and traces[0].x_axis.base_unit == "dBFS_peak_sum"
    engine.calibration.input_sensitivity = 9
    widget.sweep_start_spin.setValue(-80)
    assert traces[0].metadata["metadata"]["calibration"]["input_sensitivity_Vpeak_per_FS"] is None
    assert list(traces[0].x_data) == [-40, -3]
    widget._reset_imd()
    assert module.imd_snapshot is None and len(traces[0].metadata["steps"]) == 2
    export = IMDExportWorker(worker.snapshot, str(tmp_path / "out.json"), "json")
    saved = []
    failed = []
    export.saved.connect(saved.append)
    export.failed.connect(failed.append)
    export.run()
    assert saved and not failed
    with patch("os.replace", side_effect=OSError("disk error")):
        export.run()
    assert failed == ["disk error"]
    assert worker.snapshot["steps"][0]["ratio"] is not None
    assert len(list(tmp_path.glob("tmp*"))) == 0


def test_gui_cancel_is_async_and_settings_locked(qtbot, setup):
    engine, module, unused = setup
    widget = DistortionAnalyzerWidget(module)
    qtbot.addWidget(widget)
    widget.mode_combo.setCurrentIndex(3)
    widget.imd_settling.setValue(30000)
    widget.action_btn.click()
    assert not widget.settings_tabs.isEnabled()
    qtbot.waitUntil(lambda: engine.registered == 1)
    start = time.monotonic()
    widget.action_btn.click()
    assert time.monotonic() - start < 0.1
    qtbot.waitUntil(lambda: widget.action_btn.isEnabled(), timeout=3000)
    assert module.imd_snapshot["status"] == "cancelled"
    assert widget.settings_tabs.isEnabled()


def test_stale_record_is_rejected(setup):
    engine, module, worker = setup
    original_add = StepCapture.feed

    def stale(capture, data, start, plan):
        original_add(capture, data, start, plan)
        if capture.ready:
            identity, record, slot, first, last = capture.ready.popleft()
            capture.ready.appendleft((("old-run", identity[1]), record, slot, first, last))

    with patch.object(StepCapture, "feed", stale):
        worker.run()
    assert worker.snapshot["reason"] == "input_discontinuity"
    assert worker.snapshot["steps"][0]["ratio"] is None


def test_rejected_nonfinite_settings_can_be_saved(setup):
    from dataclasses import replace
    from src.core.imd_sweep import serialize

    engine, module, worker = setup
    worker.settings = replace(worker.settings, start_dbfs=np.nan)
    worker.run()
    assert worker.snapshot["status"] == "failed"
    assert '"start_dbfs": null' in serialize(worker.snapshot, "json")


def test_close_cancels_without_destroying_running_thread(qtbot, setup):
    engine, module, unused = setup
    widget = DistortionAnalyzerWidget(module)
    qtbot.addWidget(widget)
    widget.show()
    widget.mode_combo.setCurrentIndex(3)
    widget.imd_settling.setValue(30000)
    widget.action_btn.click()
    qtbot.waitUntil(lambda: engine.registered == 1)
    widget.close()
    qtbot.waitUntil(lambda: not widget.imd_worker.isRunning(), timeout=3000)
    qtbot.waitUntil(lambda: not widget.isVisible())
    assert module.imd_snapshot["status"] == "cancelled"


def test_new_run_keeps_previous_snapshot_independent(setup):
    engine, module, worker = setup
    worker.run()
    previous = snapshot_copy(worker.snapshot)
    engine.running = True
    second = IMDSweepWorker(module, worker.settings)
    second.run()
    assert second.run_id != previous["run_id"]
    second.snapshot["steps"][0]["flags"].append("changed")
    assert previous == snapshot_copy(worker.snapshot)
    assert len(previous["steps"]) == 2


def test_imd_controls_and_axes_are_unambiguous(qtbot, setup):
    from PyQt6.QtCore import Qt

    engine, module, unused = setup
    widget = DistortionAnalyzerWidget(module)
    qtbot.addWidget(widget)
    widget.show()
    widget.mode_combo.setCurrentIndex(3)
    assert not widget.settings_tabs.isTabEnabled(0)
    assert not widget.filter_combo.isEnabled()
    assert not widget.avg_spin.isEnabled()
    assert not widget.imd_advanced.isVisible()
    widget.imd_advanced_toggle.setFocus()
    qtbot.keyClick(widget.imd_advanced_toggle, Qt.Key.Key_Space)
    assert widget.imd_advanced.isVisible()
    assert widget.sweep_axis.autoSIPrefixScale == 1
    assert widget.sweep_axis.labelUnitPrefix == ""
    assert widget.sweep_plot.getPlotItem().getAxis("left").labelText == "FFT IMD"
    assert "SMPTE" in widget.imd_profile_combo.currentText()
    assert len(widget.imd_info.text()) < len(widget.imd_info.toolTip())
    widget.mode_combo.setCurrentIndex(1)
    assert widget.settings_tabs.isTabEnabled(0)
    assert widget.filter_combo.isEnabled()
    assert module.signal_type == "sine"


def test_comparison_keeps_db_values_below_render_floor(setup, qtbot):
    engine, module, worker = setup
    worker.run()
    module.imd_snapshot = snapshot_copy(worker.snapshot)
    step = module.imd_snapshot["steps"][0]
    step.update(ratio=1e-10, percent=1e-8, relative_dB=-200)
    widget = DistortionAnalyzerWidget(module)
    qtbot.addWidget(widget)
    widget.mode_combo.setCurrentIndex(3)
    trace = widget.get_comparable_data()[0]
    assert trace.y_data[0] == -200
    assert trace.y_axis.display_unit == "dB"
    assert widget.sweep_curve.yData[0] == -160
    widget._imd_show_point(step)
    assert "-200.000" in widget.imd_readout.text()
