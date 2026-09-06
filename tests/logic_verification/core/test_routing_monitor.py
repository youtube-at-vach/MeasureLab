"""Monitor isolation, clock mismatch, route ownership and lifecycle contracts."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest
import sounddevice as sd

from src.core.audio_engine import AudioEngine, VirtualStream
from src.core.monitor_output import MonitorBuffer, MonitorOutput


class FakeOutput:
    instances = []
    fail_start = False

    def __init__(self, **settings):
        self.settings = settings
        self.active = False
        self.closed = False
        self.latency = 0.02
        self.instances.append(self)

    def start(self):
        if self.fail_start:
            raise RuntimeError("device failed")
        self.active = True

    def abort(self):
        self.active = False

    def close(self):
        self.active = False
        self.closed = True

    def render(self, frames=16):
        output = np.empty((frames, self.settings["channels"]), dtype=np.float32)
        self.settings["callback"](output, frames, None, sd.CallbackFlags())
        return output


@pytest.fixture
def hardware(monkeypatch):
    # Other legacy test modules replace sys.modules['sounddevice'] at import
    # time. Pin all three collaborators to the same backend for this fixture.
    monkeypatch.setattr("src.core.audio_engine.sd", sd)
    monkeypatch.setattr("src.core.monitor_output.sd", sd)
    monkeypatch.setattr("src.core.routing.sd", sd)
    monkeypatch.setattr(sd.default, "device", (0, 0))
    FakeOutput.instances = []
    FakeOutput.fail_start = False
    monkeypatch.setattr(sd, "OutputStream", FakeOutput)
    monkeypatch.setattr(sd, "query_devices", lambda *args: {"name": "Test DAC", "hostapi": 0, "max_output_channels": 2})
    monkeypatch.setattr(sd, "query_hostapis", lambda *args: {"name": "Test API"})
    monkeypatch.setattr(sd, "check_output_settings", MagicMock())
    yield
    for stream in FakeOutput.instances:
        stream.close()


@pytest.fixture
def engine(hardware):
    engine = AudioEngine()
    engine.offline_mode = True
    engine.sample_rate = 1000
    engine.block_size = 16
    engine.monitor.configure(device=0)
    engine.vst_dut.path = "test.vst3"
    engine.vst_dut._request = MagicMock(
        side_effect=lambda command, payload=None: payload[0] * 0.5 if command == "process" else None
    )
    yield engine
    engine.monitor.enable(False)
    engine.vst_dut.close()


def callbacks(engine):
    captured = []

    def generator(indata, outdata, *_):
        outdata[:, 0] = 0.4
        if outdata.shape[1] == 2:
            outdata[:, 1] = 0.8

    def instrument(indata, outdata, *_):
        captured.append(indata.copy())

    engine.callbacks = {0: generator, 1: instrument}
    engine._cached_callbacks = list(engine.callbacks.values())
    return captured


def block(engine):
    zeros = np.zeros((16, 2), dtype=np.float32)
    engine._master_callback(zeros, zeros.copy(), 16, None, sd.CallbackFlags())


def start_monitor(engine):
    engine.monitor.enable(True)
    engine.monitor.start(engine.sample_rate, engine.block_size)
    return FakeOutput.instances[-1]


@pytest.mark.parametrize("precision", [False, True])
@pytest.mark.parametrize("mode", ["stereo", "left", "right"])
@pytest.mark.parametrize(
    "source, expected",
    [
        ("dut_output", (0.2, 0.4)),
        ("measurement_return", (0.2, 0.8)),
        ("output_mix", (0.4, 0.8)),
    ],
)
def test_monitor_samples_and_measurement_are_independent(engine, precision, mode, source, expected):
    engine.audio_engine_64bit = precision
    engine.output_channel_mode = mode
    engine._update_channel_modes()
    engine.vst_dut.set_routes((0, 1), ("wet1", "dry2"))
    captured = callbacks(engine)
    engine.dithering_enabled = True
    block(engine)
    block(engine)
    before = captured[-1].copy()
    engine.configure_monitor(source=source)
    output = start_monitor(engine)
    for _ in range(20):
        block(engine)
    engine.configure_monitor(gain_db=0)
    result = output.render()
    if mode != "stereo":
        expected = {"dut_output": (0.2, 0.2), "measurement_return": (0.2, 0.4), "output_mix": (0.4, 0.4)}[source]
    np.testing.assert_allclose(result, np.broadcast_to(expected, result.shape))
    for observed in captured[2:]:
        np.testing.assert_array_equal(observed, before)
    assert sum(call.args[0] == "process" for call in engine.vst_dut._request.call_args_list) == 22
    engine.set_monitor_enabled(False)
    block(engine)
    np.testing.assert_array_equal(captured[-1], before)


def test_wet_mono_is_duplicated_independently_of_dry_reference(engine):
    engine.vst_dut.set_routes((1,), ("wet1", "dry1"))
    result = engine.vst_dut.process_buses(np.array([[0.2, 0.6]], dtype=np.float32), 1000, 1)
    np.testing.assert_allclose(result.wet, [[0.3, 0.3]])
    np.testing.assert_allclose(result.measurement, [[0.3, 0.2]])


def test_late_blocks_cannot_cross_activation_and_gain_does_not_restart(engine):
    callbacks(engine)
    first = start_monitor(engine)
    old = engine.monitor.session
    engine.set_monitor_enabled(False)
    second = start_monitor(engine)
    engine.configure_monitor(gain_db=-6)
    assert len(FakeOutput.instances) == 2
    engine.monitor.submit(old, np.ones((1000, 2)))
    assert engine.monitor.session.buffer.size == 0
    np.testing.assert_array_equal(second.render(), 0)
    assert first.closed
    np.testing.assert_array_equal(first.render(), 0)


@pytest.mark.parametrize("field", ["source", "device"])
def test_source_and_device_changes_require_off(engine, field):
    start_monitor(engine)
    with pytest.raises(RuntimeError, match="Turn off"):
        engine.configure_monitor(**{field: "output_mix" if field == "source" else 0})


@pytest.mark.parametrize("gain", [float("nan"), float("inf"), -61, 1])
def test_invalid_gain_rejected_without_changing_route(engine, gain):
    previous = engine.monitor.route
    with pytest.raises(ValueError):
        engine.configure_monitor(gain_db=gain)
    assert engine.monitor.route == previous


def test_buffer_overflow_keeps_newest_window_and_underflow_reprimes():
    ring = MonitorBuffer(1000, 10)
    values = np.arange(500, dtype=np.float32)
    ring.put(np.column_stack((values, values)))
    assert ring.size == ring.target == 100
    assert ring.dropped == 400
    output = np.empty((110, 2), dtype=np.float32)
    ring.read_into(output)
    np.testing.assert_array_equal(output[:100, 0], values[-100:])
    np.testing.assert_array_equal(output[100:], 0)
    assert ring.missing == 10
    ring.put(np.ones((50, 2)))
    ring.read_into(output)
    np.testing.assert_array_equal(output, 0)
    assert not ring.primed


def test_buffer_wraparound_and_mono_downmix():
    ring = MonitorBuffer(1000, 10)
    output = np.empty((100, 1), dtype=np.float32)
    for index in range(30):
        ring.put(np.tile([index, -index + 2], (100, 1)))
        ring.read_into(output)
        np.testing.assert_array_equal(output, 1)
    assert ring.dropped == ring.missing == 0


def test_buffer_competition_never_waits():
    ring = MonitorBuffer(1000, 10)
    with ring.lock:
        ring.put(np.ones((10, 2)))
        output = np.ones((10, 2))
        ring.read_into(output)
    assert ring.dropped == ring.missing == 10
    np.testing.assert_array_equal(output, 0)


@pytest.mark.parametrize("step", [9, 11])
def test_long_clock_mismatch_remains_bounded(step):
    ring = MonitorBuffer(1000, 10)
    allocation = ring.data
    source = np.ones((step, 2), dtype=np.float32)
    output = np.empty((10, 2), dtype=np.float32)
    # Thirty simulated minutes; no wall-clock sleeping or physical output.
    for _ in range(180000):
        ring.put(source)
        ring.read_into(output)
        assert 0 <= ring.size <= ring.capacity
    assert ring.data is allocation
    assert ring.dropped > 0 if step > 10 else ring.missing > 0


@pytest.mark.parametrize("failure", ["start", "format", "identity"])
def test_physical_failure_does_not_change_measurement(engine, monkeypatch, failure):
    captured = callbacks(engine)
    block(engine)
    block(engine)
    expected = captured[-1].copy()
    if failure == "start":
        FakeOutput.fail_start = True
    elif failure == "format":
        monkeypatch.setattr(sd, "check_output_settings", MagicMock(side_effect=ValueError("unsupported rate")))
    else:
        monkeypatch.setattr(sd, "query_devices", lambda *args: {"name": "Other DAC", "hostapi": 0})
    engine.monitor.enable(True)
    engine.monitor.start(1000, 16)
    assert engine.monitor.status().state == "error"
    assert engine.sample_rate == 1000
    block(engine)
    np.testing.assert_array_equal(captured[-1], expected)
    assert all(stream.closed for stream in FakeOutput.instances)


def test_dut_failure_gates_buffer_before_control_thread_cleanup(engine):
    captured = callbacks(engine)
    output = start_monitor(engine)
    for _ in range(10):
        block(engine)
    engine.vst_dut._request.side_effect = RuntimeError("host failed")
    block(engine)
    np.testing.assert_array_equal(output.render(), 0)
    block(engine)
    np.testing.assert_array_equal(captured[-1], 0)
    assert engine.monitor.status().state == "error"
    assert output.closed


def test_output_mix_monitor_survives_dut_failure(engine):
    callbacks(engine)
    engine.configure_monitor(source="output_mix")
    output = start_monitor(engine)
    engine.vst_dut._request.side_effect = RuntimeError("host failed")
    for _ in range(10):
        block(engine)
    assert np.any(output.render())


def test_stream_loss_is_latched_until_explicit_enable(engine):
    callbacks(engine)
    output = start_monitor(engine)
    output.active = False
    assert engine.monitor.status().state == "error"
    assert output.closed
    engine.monitor.start(1000, 16)
    assert len(FakeOutput.instances) == 1
    start_monitor(engine)
    assert engine.monitor.status().state == "waiting"


@pytest.mark.parametrize("change", ["close", "reset", "routes", "bypass", "format", "backend"])
def test_structural_changes_disable_monitor(engine, change):
    start_monitor(engine)
    if change == "routes":
        engine.vst_dut.set_routes((0,), ("wet1", "dry1"))
    elif change == "bypass":
        engine.vst_dut.set_bypassed(True)
    elif change == "format":
        engine.set_sample_rate(48000)
    elif change == "backend":
        engine.set_offline_mode(False)
    else:
        getattr(engine.vst_dut, change)()
    assert not engine.monitor.route.enabled
    assert FakeOutput.instances[-1].closed


def test_enable_does_not_register_callback_or_start_measurement(engine):
    engine.set_monitor_enabled(True)
    assert engine.stream is None
    assert not engine.callbacks
    assert not FakeOutput.instances
    assert engine.monitor.status().state == "waiting"


def test_monitor_follows_measurement_stop_and_start_with_resident_mode(engine, monkeypatch):
    monkeypatch.setattr(VirtualStream, "start", lambda self: setattr(self, "active", True))
    monkeypatch.setattr(VirtualStream, "stop", lambda self: setattr(self, "active", False))
    engine.pipewire_jack_resident = True
    engine.set_monitor_enabled(True)
    cid = engine.register_callback(lambda *args: None)
    first = FakeOutput.instances[-1]
    assert engine.monitor.session is not None
    engine.unregister_callback(cid)
    assert first.closed
    assert engine.stream.active
    cid = engine.register_callback(lambda *args: None)
    assert len(FakeOutput.instances) == 2
    engine.stop_stream()
    assert FakeOutput.instances[-1].closed
    assert engine.monitor.route.enabled
    engine.unregister_callback(cid)


def test_clipping_and_mono_device_do_not_modify_source(hardware, monkeypatch):
    monkeypatch.setattr(sd, "query_devices", lambda *args: {"name": "Test DAC", "hostapi": 0, "max_output_channels": 1})
    monitor = MonitorOutput()
    monitor.configure(device=0, gain_db=0)
    monitor.enable(True)
    monitor.start(1000, 10)
    source = np.tile([4.0, -1.0], (100, 1))
    original = source.copy()
    monitor.submit(monitor.session, source)
    np.testing.assert_array_equal(FakeOutput.instances[-1].render(100), 1)
    np.testing.assert_array_equal(source, original)
    monitor.enable(False)


def test_virtual_snapshot_fanout_and_dut_channel_details(engine):
    engine.vst_dut.set_routes((0, 1), ("wet1", "dry2"))
    engine.monitor.route = replace(engine.monitor.route, enabled=True)
    snapshot = engine.routing_snapshot()
    assert snapshot.clock == "virtual_timer"
    assert snapshot.dut_returns == ("wet1", "dry2")
    assert {c.destination for c in snapshot.connections if c.source == "dut_output"} == {
        "measurement_input",
        "physical_monitor",
    }
    assert not snapshot.output_editable


@pytest.mark.parametrize("duplex", [False, True])
def test_remote_snapshot_and_exclusive_monitor_policy(engine, duplex):
    engine.offline_mode = False
    engine.network_mode = True
    engine.network_client = SimpleNamespace(connected=True, duplex=duplex)
    snapshot = engine.routing_snapshot()
    assert snapshot.backend == "remote_client"
    assert snapshot.clock == "remote_device"
    output = next(c for c in snapshot.connections if c.destination == "remote_output")
    assert output.state == ("waiting" if duplex else "unavailable")
    with pytest.raises(RuntimeError, match="virtual"):
        engine.set_monitor_enabled(True)
    engine.network_client = None


@pytest.mark.parametrize(
    "connected,duplex,allow", [(False, False, False), (True, False, False), (True, True, True), (True, True, False)]
)
@pytest.mark.parametrize("playback_active", [False, True])
def test_provider_snapshot(engine, connected, duplex, allow, playback_active):
    engine.offline_mode = False
    engine._exclusive_owner = object()
    engine._exclusive_audio_role = "remote_provider"
    engine._exclusive_status_provider = lambda: {
        "client_address": "client" if connected else "",
        "duplex": duplex,
        "allow_output": allow,
        "playback_active": playback_active,
    }
    snapshot = engine.routing_snapshot()
    assert not snapshot.output_editable
    assert snapshot.connections[0].state == ("playing" if connected else "waiting")
    assert snapshot.connections[1].state == (
        ("playing" if playback_active else "waiting") if connected and duplex and allow else "off"
    )
    with pytest.raises(RuntimeError):
        engine.set_output_destination("physical")


@pytest.mark.parametrize(
    "mode,loopback,muted", [("physical", False, False), ("loopback_silent", True, True), ("loopback_mix", True, False)]
)
def test_common_output_selection_preserves_legacy_routes(engine, mode, loopback, muted):
    engine.offline_mode = False
    engine.set_output_destination(mode)
    assert (engine.loopback, engine.mute_output) == (loopback, muted)
    snapshot = engine.routing_snapshot()
    assert snapshot.output_destination == mode
    output = next(c for c in snapshot.connections if c.destination == "physical_output")
    assert output.state == ("off" if muted else "waiting")


def test_output_route_changes_take_effect_at_the_next_block(engine):
    engine.offline_mode = False
    observed = []

    def change_during_callback(indata, outdata, *_):
        observed.append(indata.copy())
        engine.set_output_destination("loopback_silent")
        outdata.fill(0.5)

    engine._cached_callbacks = [change_during_callback]
    output = np.zeros((16, 2), dtype=np.float32)
    engine._master_callback(np.ones_like(output), output, 16, None, sd.CallbackFlags())
    np.testing.assert_array_equal(output, 0.5)
    np.testing.assert_array_equal(observed[0], 1)
    engine._master_callback(np.ones_like(output), output, 16, None, sd.CallbackFlags())
    np.testing.assert_array_equal(output, 0)
    np.testing.assert_array_equal(observed[1], 0)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), 1e300])
def test_unrepresentable_monitor_samples_fail_without_touching_source(engine, value):
    output = start_monitor(engine)
    source = np.full((200, 2), value, dtype=np.float64)
    original = source.copy()
    engine.monitor.submit(engine.monitor.session, source)
    np.testing.assert_array_equal(output.render(), 0)
    assert engine.monitor.status().state == "error"
    np.testing.assert_array_equal(source, original)


def test_snapshot_does_not_consume_measurement_error_counters(engine):
    engine.callback_error_count = 3
    engine.last_callback_error = RuntimeError("measurement failure")
    engine.routing_snapshot()
    engine.routing_snapshot()
    assert engine.callback_error_count == 3
    assert str(engine.last_callback_error) == "measurement failure"


@pytest.mark.parametrize("field", ["active", "latency"])
def test_monitor_device_status_failure_stays_out_of_measurement_status(engine, monkeypatch, field):
    stream = start_monitor(engine)

    def disconnected(self):
        raise RuntimeError("device removed")

    monkeypatch.setattr(FakeOutput, field, property(disconnected, lambda self, value: None), raising=False)
    assert engine.routing_snapshot().monitor.state == "error"
    assert engine.get_status()["error_count"] == 0
    assert stream.closed


def test_failed_close_keeps_device_owned_until_cleanup_succeeds(engine, monkeypatch):
    stream = start_monitor(engine)
    original_close = stream.close
    monkeypatch.setattr(stream, "close", MagicMock(side_effect=RuntimeError("close failed")))
    engine.monitor.enable(False)
    assert engine.monitor.stream is stream
    assert engine.monitor.status().state == "error"
    engine.monitor.enable(True)
    engine.monitor.start(1000, 16)
    assert not engine.monitor.route.enabled
    assert len(FakeOutput.instances) == 1
    monkeypatch.setattr(stream, "close", original_close)
    start_monitor(engine)
    assert stream.closed
    assert len(FakeOutput.instances) == 2
