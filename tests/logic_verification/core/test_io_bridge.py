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


def test_buffer_callbacks_do_not_wait_on_worker_lock():
    buffer = BoundedAudioBuffer(8, 1)
    destination = np.ones((4, 1), dtype=np.float32)
    with buffer._lock:
        assert not buffer.write(destination)
        assert buffer.read_into(destination) == 0
    assert not destination.any()
    assert buffer.dropped_frames == 4


def test_full_capacity_write_counts_only_discarded_frames():
    buffer = BoundedAudioBuffer(4, 1)
    assert buffer.write(np.ones((4, 1)))
    assert buffer.dropped_frames == 0
    assert not buffer.write(np.ones((7, 1)))
    assert buffer.dropped_frames == 7


@pytest.mark.parametrize("source_rate,target_rate", [(48000, 44100), (96000, 44100)])
def test_resampler_single_frame_blocks_match_contiguous_conversion(source_rate, target_rate):
    signal = np.arange(200, dtype=np.float32)[:, None]
    whole = StreamingLinearResampler(source_rate, target_rate, 1).process(signal)
    converter = StreamingLinearResampler(source_rate, target_rate, 1)
    split = np.concatenate([converter.process(frame[None, :]) for frame in signal])
    np.testing.assert_allclose(split, whole, atol=2e-5)


def test_gain_ramp_spans_ten_milliseconds_across_callbacks():
    controller = IOBridgeController(_FakeEngine())
    controller.set_gain_db(0)
    outputs = []
    for _ in range(4):
        block = np.ones((128, 1), dtype=np.float32)
        controller._apply_gain(block)
        outputs.append(block)
    result = np.concatenate(outputs)[:, 0]
    assert result[127] == pytest.approx(128 / 480)
    assert result[478] < 1
    assert result[479] == pytest.approx(1)
    assert np.all(np.diff(result) >= 0)


def test_remote_stream_uses_saved_input_and_remote_output_format(monkeypatch):
    from src.core.io_bridge_stream import IOBridgeStream

    captured = []

    def capture(*args, **kwargs):
        stream = IOBridgeStream(*args, **kwargs)
        captured.append(stream)
        return stream

    monkeypatch.setattr("src.core.io_bridge.IOBridgeStream", capture)
    monkeypatch.setattr(IOBridgeStream, "start", lambda self: None)
    engine = _FakeEngine()
    engine.offline_mode = False
    engine.network_mode = True
    engine.network_client = SimpleNamespace(connected=True, duplex=True, output_channels=2)
    engine.sample_rate = 48000
    engine.get_local_audio_config = lambda: {
        "sample_rate": 44100,
        "block_size": 128,
        "input_device": 3,
        "input_channels": "right",
        "output_channels": "stereo",
    }
    controller = IOBridgeController(engine)
    assert controller.start(IOBridgeRoute.REMOTE_OUTPUT)
    stream = captured[0]
    assert (stream.sample_rate, stream.target_rate, stream.hardware_channels) == (44100, 48000, 2)
    source = np.tile([0.8, 0.2], (3000, 1)).astype(np.float32)
    stream._convert_block(source)
    output = np.empty((480, 2), dtype=np.float32)
    stream.read_into(output)
    np.testing.assert_allclose(output[-1], 0.2, atol=1e-6)
    np.testing.assert_allclose(output[:, 0], output[:, 1])
    controller.stop()


def test_physical_right_output_leaves_left_terminal_silent():
    from src.core.io_bridge_stream import IOBridgeStream

    stream = IOBridgeStream(
        "output",
        device=1,
        sample_rate=48000,
        block_size=128,
        channels=1,
        source_rate=48000,
        source_channels=2,
        channel_mode="right",
        hardware_channels=2,
    )
    stream._convert_block(np.tile([0.2, 0.6], (3000, 1)).astype(np.float32))
    output = np.empty((128, 2), dtype=np.float32)
    stream._output_callback(output, 128, None, None)
    np.testing.assert_allclose(output[:, 0], 0)
    np.testing.assert_allclose(output[:, 1], 0.4 * np.arange(1, 129) / 480, atol=1e-6)


@pytest.mark.parametrize("ppm", [-200, 200])
@pytest.mark.parametrize("source_rate,target_rate", [(44100, 48000), (48000, 44100)])
def test_independent_clocks_keep_latency_bounded(ppm, source_rate, target_rate):
    from src.core.io_bridge_stream import IOBridgeStream

    stream = IOBridgeStream(
        "input",
        device=1,
        sample_rate=source_rate,
        target_rate=target_rate,
        block_size=512,
        channels=1,
        source_rate=source_rate,
        source_channels=1,
    )
    source_position = 0.0
    written = 0
    levels = []
    for index in range(6000):  # More than a minute of variable callback sizes.
        frames = (128, 512, 384)[index % 3]
        source_position += frames * source_rate / target_rate * (1 + ppm / 1e6)
        count = int(source_position) - written
        written += count
        stream._convert_block(np.full((count, 1), 0.25, dtype=np.float32))
        output = np.empty((frames, 1), dtype=np.float32)
        stream.read_into(output)
        if index > 500:
            levels.append(stream.buffered_frames / target_rate)
    assert stream.overrun_count == 0
    assert stream.underrun_count == 0
    assert min(levels) > 0.01
    assert max(levels) < 0.08


def test_last_analysis_callback_does_not_stop_bridge(monkeypatch):
    from src.core.audio_engine import AudioEngine

    monkeypatch.setattr("src.core.io_bridge.IOBridgeStream", _FakeBridgeStream)
    engine = AudioEngine()
    engine.offline_mode = True
    engine.vst_dut = SimpleNamespace(loaded=True)
    stream = SimpleNamespace(active=True, stop=lambda: None, close=lambda: None)
    engine.stream = stream
    callback_id = engine.register_callback(lambda *args: None, output_intent="analysis")
    assert engine.io_bridge.start()
    engine.unregister_callback(callback_id)
    assert engine.stream is stream
    assert engine.io_bridge.is_active()
    engine.io_bridge.stop()
    assert engine.stream is None


def test_physical_monitor_preserves_existing_remote_playback():
    from src.core.network_audio.client import NetworkClientStream

    engine = _FakeEngine()
    engine.io_bridge = IOBridgeController(engine)
    engine.io_bridge._state = IOBridgeState.ON
    driver = object.__new__(NetworkClientStream)
    driver.callback = engine.ensure_stream_running
    assert driver._playback_mode() == "normal"


def test_cancel_background_start_closes_delayed_device(monkeypatch):
    entered = threading.Event()
    release = threading.Event()

    class DelayedStream(_FakeBridgeStream):
        def start(self):
            entered.set()
            assert release.wait(2)
            super().start()

    monkeypatch.setattr("src.core.io_bridge.IOBridgeStream", DelayedStream)
    engine = _FakeEngine()
    controller = IOBridgeController(engine)
    assert controller.start(background=True)
    assert entered.wait(2)
    controller.stop(background=True)
    assert controller.snapshot().state is IOBridgeState.STOPPING
    release.set()
    import time

    deadline = time.monotonic() + 2
    while controller.snapshot().state is IOBridgeState.STOPPING and time.monotonic() < deadline:
        time.sleep(0.005)
    assert controller.snapshot().state is IOBridgeState.OFF
    assert DelayedStream.instances[-1].stopped
    assert engine.stream is None


def test_remote_stop_fades_to_silence_before_releasing_stream(monkeypatch):
    import time

    monkeypatch.setattr("src.core.io_bridge.IOBridgeStream", _FakeBridgeStream)
    engine = _FakeEngine()
    engine.offline_mode = False
    engine.network_mode = True
    engine.network_client = SimpleNamespace(connected=True, duplex=True)
    controller = IOBridgeController(engine)
    controller.set_gain_db(0)
    assert controller.start(IOBridgeRoute.REMOTE_OUTPUT)
    controller.fill_remote_output(np.empty((512, 2), dtype=np.float32))
    controller.stop(background=True)
    output = np.empty((512, 2), dtype=np.float32)
    controller.fill_remote_output(output)
    assert output[0, 0] > 0.2
    assert output[479, 0] == pytest.approx(0)
    assert np.all(np.diff(output[:, 0]) <= 0)
    deadline = time.monotonic() + 2
    while controller.is_active() and time.monotonic() < deadline:
        time.sleep(0.005)
    assert controller.snapshot().state is IOBridgeState.OFF


def test_vst_unload_stops_bridge_before_changing_dut(monkeypatch):
    from src.core.audio_engine import AudioEngine

    engine = AudioEngine()
    engine.io_bridge._state = IOBridgeState.ON
    observed = []
    monkeypatch.setattr(engine.vst_dut, "_close_locked", lambda: observed.append(engine.io_bridge.is_active()))
    engine.vst_dut.close()
    assert observed == [False]


def test_device_stall_is_reported_from_worker():
    from src.core.io_bridge_stream import IOBridgeStream

    errors = []
    stream = IOBridgeStream(
        "output",
        device=1,
        sample_rate=48000,
        block_size=128,
        channels=1,
        source_rate=48000,
        source_channels=1,
        on_error=errors.append,
    )
    stream._stream = SimpleNamespace(active=False)
    stream._started = True
    stream._worker_loop()
    assert len(errors) == 1
    assert "stopped" in errors[0]


def test_single_xrun_recovers_but_persistent_status_fails():
    from src.core.io_bridge_stream import IOBridgeStream

    errors = []
    stream = IOBridgeStream(
        "input",
        device=1,
        sample_rate=48000,
        block_size=128,
        channels=1,
        source_rate=48000,
        source_channels=1,
        on_error=errors.append,
    )
    stream._record_status("overflow")
    stream._record_status(None)
    assert not errors
    for _ in range(20):
        stream._record_status("overflow")
    assert len(errors) == 1
    assert stream.overrun_count == 21
