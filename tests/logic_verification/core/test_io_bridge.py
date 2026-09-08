from types import SimpleNamespace
import threading

import numpy as np
import pytest

from src.core.io_bridge import IOBridgeController, IOBridgeRoute, IOBridgeState
from src.core.io_bridge_stream import BoundedAudioBuffer, StreamingLinearResampler, map_audio_channels


class _FakeBridgeStream:
    instances = []

    def __init__(self, *_args, **_kwargs):
        self.active = False
        self.buffered_frames = 0
        self.underrun_count = 0
        self.overrun_count = 0
        self._source_buffer = SimpleNamespace(dropped_frames=0)
        self._destination_buffer = SimpleNamespace(dropped_frames=0)
        self.pushed = []
        self.stopped = False
        self.instances.append(self)

    def start(self):
        self.active = True

    def stop(self):
        self.active = False
        self.stopped = True

    def push(self, block):
        self.pushed.append(np.array(block, copy=True))
        return True

    def read_into(self, destination):
        destination.fill(0.25)
        return len(destination)


class _FakeEngine:
    sample_rate = 48_000
    block_size = 128
    input_device = "mic"
    output_device = "speakers"
    input_channel_mode = "stereo"
    output_channel_mode = "stereo"
    offline_mode = True
    network_mode = False
    network_client = None
    loopback = False
    mute_output = False
    callbacks = {}
    pipewire_jack_resident = False
    vst_dut = SimpleNamespace(loaded=True)

    def __init__(self):
        self.lock = threading.Lock()
        self.stream = None
        self.stopped_by = None

    def get_local_audio_config(self):
        return {
            "input_device": self.input_device,
            "output_device": self.output_device,
            "sample_rate": self.sample_rate,
            "block_size": self.block_size,
            "input_channels": self.input_channel_mode,
            "output_channels": self.output_channel_mode,
        }

    def ensure_stream_running(self):
        self.stream = SimpleNamespace(active=True)
        return True

    def stop_stream(self, *, owner=None):
        self.stopped_by = owner
        self.stream = None


def test_bounded_audio_buffer_drops_oldest_without_blocking():
    buffer = BoundedAudioBuffer(4, 1)
    assert buffer.write(np.arange(3, dtype=np.float32)[:, None])
    assert not buffer.write(np.arange(3, 6, dtype=np.float32)[:, None])

    output = np.empty((4, 1), dtype=np.float32)
    assert buffer.read_into(output) == 4
    np.testing.assert_allclose(output[:, 0], [2, 3, 4, 5])
    assert buffer.dropped_frames == 2


def test_channel_mapping_is_explicit_and_does_not_add_stereo_channels():
    stereo = np.array([[1.0, -1.0], [0.5, 0.25]], dtype=np.float32)
    np.testing.assert_allclose(map_audio_channels(stereo, 1), [[0.0], [0.375]])
    np.testing.assert_allclose(map_audio_channels(np.array([[0.5]], dtype=np.float32), 2), [[0.5, 0.5]])
    np.testing.assert_allclose(map_audio_channels(stereo, 1, "right"), [[-1.0], [0.25]])


def test_resampler_keeps_state_across_variable_blocks():
    converter = StreamingLinearResampler(44_100, 48_000, 1)
    first = converter.process(np.arange(5, dtype=np.float32)[:, None])
    second = converter.process(np.arange(5, 9, dtype=np.float32)[:, None])
    result = np.vstack((first, second))

    assert result.shape[1] == 1
    assert result.shape[0] >= 8
    assert np.isfinite(result).all()
    assert np.all(np.diff(result[:, 0]) >= 0)


def test_physical_bridge_starts_routes_input_and_stops(monkeypatch):
    _FakeBridgeStream.instances.clear()
    monkeypatch.setattr("src.core.io_bridge.IOBridgeStream", _FakeBridgeStream)
    engine = _FakeEngine()
    controller = IOBridgeController(engine)

    assert controller.start()
    assert controller.snapshot().state is IOBridgeState.ON
    assert controller.route is IOBridgeRoute.PHYSICAL

    source = np.ones((32, 2), dtype=np.float32)
    controller.push_physical_input(source)
    assert len(_FakeBridgeStream.instances[0].pushed) == 1

    controller.stop()
    assert controller.snapshot().state is IOBridgeState.OFF
    assert _FakeBridgeStream.instances[0].stopped


def test_remote_route_requires_duplex_and_applies_gain(monkeypatch):
    _FakeBridgeStream.instances.clear()
    monkeypatch.setattr("src.core.io_bridge.IOBridgeStream", _FakeBridgeStream)
    engine = _FakeEngine()
    engine.offline_mode = False
    engine.network_mode = True
    engine.network_client = SimpleNamespace(connected=True, duplex=True, output_device_name="Remote speakers")
    controller = IOBridgeController(engine)
    controller.set_route(IOBridgeRoute.REMOTE_OUTPUT)
    controller.set_gain_db(-6)

    assert controller.start()
    destination = np.empty((1024, 2), dtype=np.float32)
    controller.fill_remote_output(destination)
    assert np.all(np.isfinite(destination))
    assert destination[-1, 0] == pytest.approx(0.25 * 10 ** (-6 / 20), abs=1e-5)
    controller.stop()


def test_remote_route_does_not_take_over_an_output_callback(monkeypatch):
    _FakeBridgeStream.instances.clear()
    monkeypatch.setattr("src.core.io_bridge.IOBridgeStream", _FakeBridgeStream)
    engine = _FakeEngine()
    engine.offline_mode = False
    engine.network_mode = True
    engine.network_client = SimpleNamespace(connected=True, duplex=True, output_device_name="Remote speakers")
    engine._callback_output_intents = {7: "output"}
    controller = IOBridgeController(engine)
    controller.set_route(IOBridgeRoute.REMOTE_OUTPUT)

    assert not controller.start()
    assert controller.snapshot().state is IOBridgeState.ERROR
    assert "output-producing" in (controller.snapshot().reason or "")
    assert not _FakeBridgeStream.instances


def test_controller_rejects_unavailable_route_without_opening_stream(monkeypatch):
    _FakeBridgeStream.instances.clear()
    monkeypatch.setattr("src.core.io_bridge.IOBridgeStream", _FakeBridgeStream)
    engine = _FakeEngine()
    engine.vst_dut = SimpleNamespace(loaded=False)
    controller = IOBridgeController(engine)

    assert not controller.start()
    assert controller.snapshot().state is IOBridgeState.ERROR
    assert not _FakeBridgeStream.instances


def test_gain_is_bounded_and_nonfinite_values_are_rejected():
    controller = IOBridgeController(_FakeEngine())
    assert controller.set_gain_db(-100) == -60
    assert controller.set_gain_db(2) == 0
    with pytest.raises(ValueError):
        controller.set_gain_db(float("nan"))
