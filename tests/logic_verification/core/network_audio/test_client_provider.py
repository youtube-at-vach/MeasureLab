from __future__ import annotations

import threading
import time

import numpy as np

from src.core.network_audio.client import NetworkAudioClient, NetworkClientStream
from src.core.network_audio.provider import NetworkAudioProvider


class _Status:
    input_overflow = False
    input_underflow = False
    output_overflow = False
    output_underflow = False

    def __bool__(self):
        return False


class _FakeEngine:
    def __init__(self):
        self.sample_rate = 8000
        self.block_size = 128
        self.input_device = None
        self.output_device = None
        self.network_mode = False
        self._callback = None
        self._owner = None

    def get_status(self):
        return {"active_clients": int(self._callback is not None)}

    def _update_channel_modes(self):
        return 2, 2

    def list_devices(self):
        return []

    def acquire_exclusive_audio(self, owner):
        assert self._owner is None
        self._owner = owner

    def release_exclusive_audio(self, owner):
        if self._owner is owner:
            self._owner = None

    def register_callback(self, callback, *, owner=None):
        assert owner is self._owner
        self._callback = callback
        return 1

    def unregister_callback(self, callback_id):
        assert callback_id == 1
        self._callback = None


def _wait_until(predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_localhost_capture_paces_network_stream_and_preserves_samples():
    engine = _FakeEngine()
    provider = NetworkAudioProvider(engine, "127.0.0.1", 0)
    provider.start()
    client = NetworkAudioClient("127.0.0.1", provider.port, jitter_ms=20, duplex=False)
    client.connect()
    received = []
    callback_event = threading.Event()

    def callback(indata, outdata, frames, time_info, status):
        del outdata, time_info
        received.append((indata.copy(), frames, status))
        callback_event.set()

    stream = NetworkClientStream(client, callback)
    stream.start()
    try:
        assert _wait_until(lambda: engine._callback is not None)
        for block_index in range(8):
            value = np.float32(block_index / 8.0)
            indata = np.full((128, 2), value, dtype=np.float32)
            outdata = np.empty((128, 2), dtype=np.float32)
            engine._callback(indata, outdata, 128, None, _Status())
            time.sleep(0.01)
        assert callback_event.wait(3.0)
        assert received[0][1] == 128
        assert np.array_equal(received[0][0], np.zeros((128, 2), dtype=np.float32))
        assert not received[0][2]
    finally:
        stream.close()
        client.close()
        provider.stop()


def test_provider_defaults_to_capture_only_even_when_client_requests_duplex():
    engine = _FakeEngine()
    provider = NetworkAudioProvider(engine, "127.0.0.1", 0, allow_output=False)
    provider.start()
    client = NetworkAudioClient("127.0.0.1", provider.port, jitter_ms=20, duplex=True)
    try:
        client.connect()
        assert not client.duplex
        provider.set_allow_output(True)
        assert not provider.status_snapshot()["duplex"]
    finally:
        client.close()
        provider.stop()


def test_provider_holds_audio_exclusivity_until_provider_is_stopped():
    engine = _FakeEngine()
    provider = NetworkAudioProvider(engine, "127.0.0.1", 0)
    provider.start()
    client = NetworkAudioClient("127.0.0.1", provider.port, jitter_ms=20, duplex=False)
    try:
        assert engine._owner is provider
        client.connect()
        assert _wait_until(lambda: engine._callback is not None)
        client.close()
        assert _wait_until(lambda: engine._callback is None)
        assert engine._owner is provider
    finally:
        client.close()
        provider.stop()

    assert engine._owner is None


def test_provider_accepts_a_second_session_without_reusing_first_session_threads():
    engine = _FakeEngine()
    provider = NetworkAudioProvider(engine, "127.0.0.1", 0)
    provider.start()
    first = NetworkAudioClient("127.0.0.1", provider.port, jitter_ms=20, duplex=False)
    second = NetworkAudioClient("127.0.0.1", provider.port, jitter_ms=20, duplex=False)
    first.connect()
    first_session = first.session_id
    try:
        assert _wait_until(lambda: engine._callback is not None)
        first.close()
        assert _wait_until(lambda: engine._callback is None)

        second.connect()
        assert _wait_until(lambda: engine._callback is not None)
        assert second.session_id != first_session

        indata = np.full((128, 2), 0.5, dtype=np.float32)
        outdata = np.empty((128, 2), dtype=np.float32)
        engine._callback(indata, outdata, 128, None, _Status())
        capture = second._capture_buffer
        assert capture is not None
        assert _wait_until(lambda: capture.buffered_frames() >= 128)
        block, missing = capture.read(0, 128)
        assert not missing
        assert np.all(block == np.float32(0.5))
    finally:
        first.close()
        second.close()
        provider.stop()


def test_localhost_duplex_plays_client_output_at_a_future_sample_position():
    engine = _FakeEngine()
    provider = NetworkAudioProvider(engine, "127.0.0.1", 0, allow_output=True)
    provider.start()
    client = NetworkAudioClient("127.0.0.1", provider.port, jitter_ms=20, duplex=True)
    client.connect()

    def callback(indata, outdata, frames, time_info, status):
        del indata, frames, time_info, status
        outdata.fill(0.25)

    stream = NetworkClientStream(client, callback)
    stream.start()
    provider_outputs = []
    try:
        assert client.duplex
        assert _wait_until(lambda: engine._callback is not None)
        provider.set_allow_output(False)
        assert not provider.status_snapshot()["duplex"]
        provider.set_allow_output(True)
        assert provider.status_snapshot()["duplex"]
        for _block_index in range(16):
            indata = np.zeros((128, 2), dtype=np.float32)
            outdata = np.empty((128, 2), dtype=np.float32)
            engine._callback(indata, outdata, 128, None, _Status())
            provider_outputs.append(outdata.copy())
            time.sleep(0.02)

        assert any(np.all(block == np.float32(0.25)) for block in provider_outputs[4:])
    finally:
        stream.close()
        client.close()
        provider.stop()
