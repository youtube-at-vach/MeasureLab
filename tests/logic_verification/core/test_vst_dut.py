"""DUT transport, failure isolation, streaming and existing mixer integration."""

import os
import threading
import multiprocessing
import sys
from types import SimpleNamespace
import time
from unittest.mock import MagicMock

import numpy as np
import pytest
import sounddevice as sd

from src.core.audio_engine import AudioEngine
from src.core.vst_dut import VstDut, _plugin_worker


@pytest.fixture
def dut():
    instance = VstDut()
    yield instance
    instance.close()


def fake_host(dut, transform):
    dut.path = "test.vst3"
    dut._request = MagicMock(
        side_effect=lambda command, payload=None: transform(*payload) if command == "process" else None
    )


def test_routes_and_bypass(dut):
    source = np.column_stack((np.arange(16), -np.arange(16))).astype(np.float32)
    fake_host(dut, lambda audio, rate, block: audio * 0.25)
    dut.set_routes((1,), ("wet1", "dry1"))
    result = dut.process(source, 48000, 16)
    np.testing.assert_array_equal(result[:, 0], source[:, 1] * 0.25)
    np.testing.assert_array_equal(result[:, 1], source[:, 0])
    dut.set_bypassed(True)
    dut._request.reset_mock()
    result = dut.process(source, 48000, 16)
    np.testing.assert_array_equal(result[:, 0], source[:, 1])
    dut._request.assert_not_called()


def test_mono_source_is_duplicated_and_disconnected_inputs_are_silent(dut):
    fake_host(dut, lambda audio, rate, block: audio)
    dut.set_routes((1, -1), ("wet1", "wet2"))
    result = dut.process(np.ones((32, 1)), 44100, 32)
    np.testing.assert_array_equal(result[:, 0], 1)
    np.testing.assert_array_equal(result[:, 1], 0)


def test_partial_plugin_output_is_delayed_without_resetting_state(dut):
    calls = 0

    def latency_plugin(audio, rate, block):
        nonlocal calls
        calls += 1
        return audio[:, 3:] if calls == 1 else audio

    fake_host(dut, latency_plugin)
    source = np.ones((16, 2))
    first = dut.process(source, 48000, 16)
    np.testing.assert_array_equal(first[:3], 0)
    np.testing.assert_array_equal(first[3:], 1)
    np.testing.assert_array_equal(dut.process(source, 48000, 16), 1)
    assert dut.padded_samples == 3
    assert [call.args[0] for call in dut._request.call_args_list] == ["process", "process"]


@pytest.mark.parametrize("result", [np.full((2, 16), np.nan), np.ones((3, 16)), np.ones((2, 17))])
def test_bad_plugin_output_latches_silence_including_reference(dut, result):
    fake_host(dut, lambda *_: result)
    dut.set_routes((0, 1), ("wet1", "dry1"))
    np.testing.assert_array_equal(dut.process(np.ones((16, 2)), 48000, 16), 0)
    assert dut.error
    assert dut.loaded
    dut._request.reset_mock()
    np.testing.assert_array_equal(dut.process(np.ones((16, 2)), 48000, 16), 0)
    dut._request.assert_not_called()


def test_dead_host_disconnect_latches_error(dut):
    dut.path = "test.vst3"
    dut._connection = MagicMock()
    dut._connection.recv.side_effect = EOFError
    with pytest.raises(RuntimeError, match="disconnected"):
        dut._request("process", None)
    assert dut._connection is None
    assert dut.loaded


def test_hung_host_times_out(dut):
    dut.path = "test.vst3"
    dut._connection = MagicMock()
    dut._connection.poll.return_value = False
    with pytest.raises(RuntimeError, match="responding"):
        dut._request("process", None, timeout=0.01)
    assert dut.error


def test_invalid_routes_and_parameters(dut):
    with pytest.raises(ValueError):
        dut.set_routes((0,), ("wet1", "wet2"))
    with pytest.raises(ValueError):
        dut.set_routes((0, 1, 2), ("wet1", "wet2"))
    with pytest.raises(ValueError):
        dut.set_parameter("gain", float("nan"))


@pytest.mark.parametrize("editor_error", ["", "Plugin has no available editor UI."])
def test_worker_processes_live_edits_and_resets_with_editor_open(monkeypatch, editor_error):
    parameter = SimpleNamespace(raw_value=0.25)
    plugin = SimpleNamespace(is_effect=True, name="Effect", parameters={"gain": parameter})
    event = threading.Event()
    showing = threading.Event()
    change_gain = threading.Event()
    changed = threading.Event()
    parent, child = multiprocessing.Pipe()
    editor_parent, editor_child = multiprocessing.Pipe(duplex=False)
    audio = np.ones((2, 16), dtype=np.float32)
    failures = []
    opens = []

    def show_editor(close_event):
        assert threading.current_thread() is threading.main_thread()
        if editor_error:
            raise RuntimeError(editor_error)
        if not opens:
            parameter.raw_value = 0.75
        opens.append(True)
        showing.set()
        try:
            while not close_event.is_set():
                if change_gain.is_set():
                    parameter.raw_value = 0.5
                    changed.set()
                time.sleep(0.001)
        finally:
            showing.clear()

    def reset():
        assert threading.current_thread() is threading.main_thread()
        assert not showing.is_set()  # Reset may destroy/recreate the plugin.

    def process(audio, *args, **kwargs):
        assert threading.current_thread() is not threading.main_thread()
        return audio * parameter.raw_value

    def read(connection):
        assert connection.poll(5), "Worker reply timed out"
        success, result = connection.recv()
        assert success, result
        return result

    def request(command, payload=None):
        parent.send((command, payload))
        return read(parent)

    def client():
        try:
            read(parent)
            np.testing.assert_array_equal(request("process", (audio, 48000, 16)), audio * 0.25)
            request("editor")
            if editor_error:
                assert editor_error in read(editor_parent)["error"]
            else:
                assert showing.wait(5)
            np.testing.assert_array_equal(
                request("process", (audio, 48000, 16)), audio * (0.25 if editor_error else 0.75)
            )
            if not editor_error:
                change_gain.set()
                assert changed.wait(5)
                np.testing.assert_array_equal(request("process", (audio, 48000, 16)), audio * 0.5)
                assert showing.is_set()
            request("reset")
            if not editor_error:
                assert showing.wait(5)
                assert not editor_parent.poll()  # Reset suspends, then reopens the session.
                assert len(opens) >= 2
                event.set()
                assert read(editor_parent)["parameters"] == {"gain": 0.5}
            np.testing.assert_array_equal(
                request("process", (audio, 48000, 16)), audio * (0.25 if editor_error else 0.5)
            )
        except Exception as exc:
            failures.append(exc)
        finally:
            event.set()
            parent.send(("close", None))

    plugin.show_editor, plugin.reset, plugin.process = show_editor, reset, process
    factory = MagicMock(return_value=plugin)
    monkeypatch.setitem(sys.modules, "pedalboard", SimpleNamespace(VST3Plugin=factory))
    client_thread = threading.Thread(target=client)
    client_thread.start()
    try:
        _plugin_worker(child, "Effect.vst3", None, event, editor_child)
        client_thread.join(5)
        assert not client_thread.is_alive()
        assert not failures
        factory.assert_called_once()
    finally:
        parent.close()
        editor_parent.close()


def editor_host(dut):
    dut.path = "test.vst3"
    dut._connection = MagicMock()
    dut._editor_close = MagicMock()
    dut._editor_connection = MagicMock()
    dut._editor_connection.poll.return_value = False
    dut._connection.recv.return_value = (True, None)
    dut.open_editor()
    assert dut.editor_open
    dut._connection.send.assert_called_once_with(("editor", None))
    dut._connection.reset_mock()
    return dut._editor_connection


def test_editor_wait_does_not_use_audio_timeout_or_open_duplicate(dut):
    connection = editor_host(dut)
    connection.poll.return_value = False
    dut.open_editor()
    assert not dut.poll_editor()
    assert dut.editor_open and not dut.error
    connection.send.assert_not_called()
    connection.recv.assert_not_called()


def test_editor_manual_close_collects_values_and_allows_reopen(dut):
    connection = editor_host(dut)
    connection.poll.return_value = True
    connection.recv.return_value = (True, {"parameters": {"gain": 0.8}, "error": ""})
    assert dut.poll_editor()
    assert not dut.editor_open
    assert dut.parameters == {"gain": 0.8}
    assert not dut.poll_editor()  # Consume the completion reply only once.
    connection.recv.return_value = (True, None)
    dut.open_editor()
    assert dut.editor_open
    assert dut._editor_close.clear.call_count == 2


@pytest.mark.parametrize("editor_closed", [False, True])
def test_processing_and_editor_completion_use_separate_connections(dut, editor_closed):
    events = editor_host(dut)
    events.poll.return_value = editor_closed
    events.recv.return_value = (True, {"parameters": {"gain": 0.5}, "error": ""})
    dut._connection.recv.return_value = (True, np.full((2, 16), 0.5, dtype=np.float32))
    np.testing.assert_array_equal(dut.process(np.ones((16, 2)), 48000, 16), 0.5)
    dut._editor_close.set.assert_not_called()
    assert dut.editor_open != editor_closed
    assert not dut.error
    assert dut._connection.send.call_args.args[0][0] == "process"
    assert events.recv.call_count == int(editor_closed)


@pytest.mark.parametrize("failure", ["timeout", "crash"])
def test_editor_failure_latches_silence_and_unload_clears_state(dut, failure):
    connection = editor_host(dut)
    if failure == "timeout":
        connection.poll.return_value = False
    else:
        connection.poll.return_value = True
        connection.recv.side_effect = EOFError
    with pytest.raises(RuntimeError):
        dut.close_editor()
    assert dut.loaded and dut.error and not dut.editor_open
    np.testing.assert_array_equal(dut.process(np.ones((16, 2)), 48000, 16), 0)
    dut.close()
    assert not dut.loaded and not dut.error


def test_mixer_returns_dut_and_reference_to_all_measurement_clients(dut):
    engine = AudioEngine()
    engine.vst_dut.close()
    engine.vst_dut = dut
    engine.offline_mode = True
    fake_host(dut, lambda audio, rate, block: audio * 0.5)
    dut.set_routes((0,), ("wet1", "dry1"))
    captured = []

    def generator(indata, outdata, *_):
        outdata.fill(0.4)

    def instrument(indata, outdata, *_):
        captured.append(indata.copy())

    engine._cached_callbacks = [generator, instrument]
    zeros = np.zeros((32, 2), dtype=np.float32)
    for _ in range(3):
        engine._master_callback(zeros, zeros.copy(), 32, None, sd.CallbackFlags())
    np.testing.assert_array_equal(captured[0], 0)
    np.testing.assert_allclose(captured[1][:, 0], 0.2)
    np.testing.assert_allclose(captured[1][:, 1], 0.4)
    np.testing.assert_array_equal(captured[1], captured[2])
    engine.offline_mode = False
    engine.loopback = True
    dut._request.reset_mock()
    engine._master_callback(zeros, zeros.copy(), 32, None, sd.CallbackFlags())
    dut._request.assert_not_called()


@pytest.mark.skipif(
    not os.environ.get("MEASURELAB_TEST_VST3"), reason="Set MEASURELAB_TEST_VST3 to a native VST3 effect"
)
def test_real_native_editor_reopen_process_and_unload(dut):
    dut.load(os.environ["MEASURELAB_TEST_VST3"])
    pid = dut._process.pid
    for _ in range(2):
        dut.open_editor()
        time.sleep(0.5)  # Exercise window creation and its event loop.
        assert not dut.poll_editor()
        assert dut.editor_open
        dut.close_editor()
        assert not dut.editor_error
        assert dut._process.pid == pid
    dut.open_editor()
    time.sleep(0.5)
    for rate, block in [(48000, 256), (44100, 512), (96000, 256)]:
        dut.reset()
        for _ in range(20):
            output = dut.process(np.ones((block, 2), dtype=np.float32) * 0.1, rate, block)
            assert not dut.error and not dut.editor_error and dut.editor_open
            assert np.isfinite(output).all()
            time.sleep(0.01)
        assert not dut.poll_editor()
        assert dut.editor_open
    dut.open_editor()
    time.sleep(0.5)
    started = time.monotonic()
    dut.close()
    assert time.monotonic() - started < 2
    assert not dut.editor_open and dut._process is None


@pytest.mark.skipif(
    not os.environ.get("MEASURELAB_TEST_VST3"), reason="Set MEASURELAB_TEST_VST3 to a native VST3 effect"
)
def test_real_vst3_streaming_and_virtual_measurement(dut):
    """Opt-in integration with a real native plugin, no audio hardware required."""
    dut.load(os.environ["MEASURELAB_TEST_VST3"])
    assert dut.loaded and dut.name
    if dut.parameters:
        key, value = next(iter(dut.parameters.items()))
        dut.set_parameter(key, value)
    for rate, block in [(44100, 256), (48000, 1024), (96000, 512)]:
        dut.reset()
        outputs = []
        for index in range(24):
            signal = 0.2 * np.sin(2 * np.pi * 1000 * (np.arange(block) + index * block) / rate)
            source = np.column_stack((signal, signal)).astype(np.float32)
            outputs.append(dut.process(source, rate, block))
        assert not dut.error
        assert np.max(np.abs(np.concatenate(outputs)[block * 4 :])) > 0.001

    engine = AudioEngine()
    engine.vst_dut.close()
    engine.vst_dut = dut
    engine.offline_mode = True
    dut.set_routes((0, 1), ("wet1", "dry1"))
    captured = []
    finished = threading.Event()
    phase = 0

    def instrument(indata, outdata, frames, *_):
        nonlocal phase
        captured.append(indata.copy())
        signal = 0.2 * np.sin(2 * np.pi * 1000 * (np.arange(frames) + phase) / engine.sample_rate)
        outdata[:] = signal[:, None]
        phase += frames
        if len(captured) >= 30:
            finished.set()

    dut.open_editor()
    time.sleep(0.3)
    callback_id = engine.register_callback(instrument)
    try:
        assert finished.wait(10)
        assert not dut.error
        assert not dut.poll_editor()
        assert dut.editor_open
        recorded = np.concatenate(captured[4:])
        assert np.max(np.abs(recorded[:, 0])) > 0.001
        assert np.max(np.abs(recorded[:, 1])) > 0.1
        spectrum = np.abs(np.fft.rfft(recorded[:, 0]))
        peak_hz = np.argmax(spectrum) * engine.sample_rate / len(recorded)
        assert abs(peak_hz - 1000) < 10
    finally:
        engine.unregister_callback(callback_id)
        dut.close_editor()

    # Network Analyzer uses this same finite play/record session for sweeps.
    # In bypass, verify the exact one-block delay and reference relationship.
    from src.gui.widgets.network_analyzer import PlayRecSession

    dut.set_bypassed(True)
    signal = 0.2 * np.sin(2 * np.pi * 1000 * np.arange(engine.block_size * 8) / engine.sample_rate)
    stimulus = np.column_stack((signal, signal)).astype(np.float32)
    session = PlayRecSession(engine, stimulus, input_channels=2)
    session.start()
    try:
        session.wait(5)
        np.testing.assert_allclose(session.input_data[engine.block_size :], stimulus[: -engine.block_size])
    finally:
        session.stop()

    # Simulate a native host crash. The main process remains alive and latches
    # silence, then loading a replacement restores the host.
    dut.set_bypassed(False)
    dut._process.terminate()
    dut._process.join(timeout=1)
    np.testing.assert_array_equal(dut.process(stimulus[:1024], 48000, 1024), 0)
    assert dut.error and dut.loaded
    dut.load(os.environ["MEASURELAB_TEST_VST3"])
    assert not dut.error
    started = time.monotonic()
    dut.close()
    assert time.monotonic() - started < 2
