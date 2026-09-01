from __future__ import annotations

import threading
import time
import socket

import numpy as np
import pytest

import src.core.network_audio.client as client_module
import src.core.network_audio.provider as provider_module
from src.core.network_audio.client import NetworkAudioClient, NetworkClientStream
from src.core.network_audio.discovery import NetworkAudioDiscovery
from src.core.network_audio.indexed_buffer import IndexedAudioBuffer
from src.core.network_audio.models import NetworkAudioStats
from src.core.network_audio.provider import NetworkAudioProvider
from src.core.network_audio.protocol import (
    PACKET_CONNECT_OFFER,
    PACKET_CONNECT_REQUEST,
    PACKET_START_ACK,
    PROTOCOL_VERSION,
    datagram_kind,
    encode_control_datagram,
)


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
        self.offline_mode = False
        self._callback = None
        self._owner = None
        self._role = None
        self._status_provider = None

    def get_status(self):
        return {"active_clients": int(self._callback is not None)}

    def _update_channel_modes(self):
        return 2, 2

    def list_devices(self):
        return []

    def acquire_exclusive_audio(self, owner, *, role="reserved", status_provider=None):
        assert self._owner is None
        self._owner = owner
        self._role = role
        self._status_provider = status_provider

    def release_exclusive_audio(self, owner):
        if self._owner is owner:
            self._owner = None
            self._role = None
            self._status_provider = None

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
    assert provider._udp_socket is not None
    assert provider._udp_socket.getsockname()[1] == provider.port
    client = NetworkAudioClient("127.0.0.1", provider.port, jitter_ms=20, duplex=False)
    client.connect()
    assert client._udp_socket is not None
    assert client._udp_socket.getsockname()[0] == "127.0.0.1"
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
        assert engine._role == "remote_provider"
        assert engine._status_provider is not None
        waiting_status = engine._status_provider()
        assert waiting_status["state"] == "listening"
        assert waiting_status["provider_name"]
        assert waiting_status["sample_rate"] == engine.sample_rate
        assert waiting_status["block_size"] == engine.block_size
        client.connect()
        assert _wait_until(lambda: engine._callback is not None)
        streaming_status = engine._status_provider()
        assert streaming_status["client_address"] == "127.0.0.1"
        assert not streaming_status["duplex"]
        client.close()
        assert _wait_until(lambda: engine._callback is None)
        assert engine._owner is provider
    finally:
        client.close()
        provider.stop()

    assert engine._owner is None
    assert engine._role is None
    assert engine._status_provider is None


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


def test_stopping_client_playback_does_not_create_unbounded_provider_loss():
    engine = _FakeEngine()
    provider = NetworkAudioProvider(engine, "127.0.0.1", 0, allow_output=True)
    provider.start()
    client = NetworkAudioClient("127.0.0.1", provider.port, jitter_ms=20, duplex=True)
    client.connect()
    stream = NetworkClientStream(client, lambda _indata, outdata, *_args: outdata.fill(0.25))
    stream.start()

    try:
        assert _wait_until(lambda: engine._callback is not None)
        for _block_index in range(16):
            indata = np.zeros((128, 2), dtype=np.float32)
            outdata = np.empty((128, 2), dtype=np.float32)
            engine._callback(indata, outdata, 128, None, _Status())
            time.sleep(0.02)
        assert _wait_until(lambda: provider._playback_started_at is not None)

        stream.stop()
        assert _wait_until(lambda: not provider._playback_active.is_set())
        lost_at_stop = provider.status_snapshot()["lost_frames"]
        for _block_index in range(16):
            indata = np.zeros((128, 2), dtype=np.float32)
            outdata = np.empty((128, 2), dtype=np.float32)
            engine._callback(indata, outdata, 128, None, _Status())

        assert provider.status_snapshot()["lost_frames"] == lost_at_stop
    finally:
        stream.close()
        client.close()
        provider.stop()


def test_network_stats_do_not_retain_incident_details():
    stats = NetworkAudioStats()

    stats.record_loss(128)
    stats.record_queue_overflow(64)
    snapshot = stats.snapshot()

    assert snapshot["lost_frames"] == 192
    assert snapshot["lost_packets"] == 1
    assert snapshot["local_queue_overflows"] == 1
    assert "incidents" not in snapshot


def test_network_stream_stop_cancels_capture_priming_without_late_error():
    client = NetworkAudioClient("127.0.0.1", 40100, jitter_ms=20, duplex=False)
    client.sample_rate = 8000
    client.block_size = 128
    client.input_channels = 2
    client.output_channels = 2
    client.jitter_frames = 256
    client.playout_delay_frames = 512
    client._capture_buffer = IndexedAudioBuffer(capacity_frames=4096, channels=2)
    client._stop_event.clear()
    client._connected = True
    stream = NetworkClientStream(client, lambda *_args: None)

    stream.start()
    assert _wait_until(lambda: client.status_snapshot()["state"] == "priming")
    started = time.monotonic()
    stream.stop()

    assert time.monotonic() - started < 0.5
    assert stream._thread is None
    assert client.status_snapshot()["state"] == "connected"
    client.close()


def test_network_stream_cpu_load_excludes_remote_capture_wait():
    client = NetworkAudioClient("127.0.0.1", 40100, jitter_ms=20, duplex=False)
    client.sample_rate = 6400
    client.block_size = 128
    client.input_channels = 2
    client.output_channels = 2
    client.jitter_frames = 256
    client.playout_delay_frames = 512
    client._stop_event.clear()
    client._connected = True
    callback_count = 0

    client.first_capture_sample = lambda **_kwargs: 0

    def paced_capture(_sample_index, frames, cancel_event=None):
        del cancel_event
        time.sleep(frames / client.sample_rate)
        return np.zeros((frames, client.input_channels), dtype=np.float32), _Status()

    client.read_capture = paced_capture

    def callback(*_args):
        nonlocal callback_count
        callback_count += 1

    stream = NetworkClientStream(client, callback)
    stream.start()
    try:
        assert _wait_until(lambda: callback_count >= 20)
        # The 20 ms network pacing wait is the whole block interval.  It must
        # not be presented as audio processing work.
        assert stream.cpu_load < 0.25
    finally:
        stream.close()
        client.close()


def test_provider_rejects_virtual_audio_as_a_local_hardware_endpoint():
    engine = _FakeEngine()
    engine.offline_mode = True
    provider = NetworkAudioProvider(engine, "127.0.0.1", 0)

    try:
        try:
            provider.start()
        except RuntimeError as exc:
            assert "offline mode" in str(exc)
        else:
            raise AssertionError("provider unexpectedly started with offline audio")
    finally:
        provider.stop()


def test_provider_releases_session_when_connected_client_stops_answering_heartbeats(monkeypatch):
    monkeypatch.setattr(client_module, "CONTROL_HEARTBEAT_INTERVAL", 0.02)
    monkeypatch.setattr(client_module, "CONTROL_HEARTBEAT_TIMEOUT", 0.15)
    monkeypatch.setattr(provider_module, "CONTROL_HEARTBEAT_TIMEOUT", 0.15)
    engine = _FakeEngine()
    provider = NetworkAudioProvider(engine, "127.0.0.1", 0)
    provider.start()
    client = NetworkAudioClient("127.0.0.1", provider.port, jitter_ms=20, duplex=False)
    client.connect()

    try:
        assert _wait_until(lambda: engine._callback is not None)
        client._stop_event.set()

        assert _wait_until(
            lambda: engine._callback is None and provider.status_snapshot()["state"] == "listening",
            timeout=1.0,
        )
    finally:
        client.close()
        provider.stop()


def test_provider_stop_interrupts_a_client_stalled_during_negotiation():
    engine = _FakeEngine()
    provider = NetworkAudioProvider(engine, "127.0.0.1", 0)
    provider.start()
    stalled_client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    stalled_client.connect(("127.0.0.1", provider.port))
    stalled_client.send(
        encode_control_datagram(
            PACKET_CONNECT_REQUEST,
            {"protocol": PROTOCOL_VERSION, "client_nonce": "stalled", "duplex": False},
            message_id=1,
        )
    )

    try:
        assert _wait_until(lambda: provider._client_udp is not None)
        started = time.monotonic()
        provider.stop()

        assert time.monotonic() - started < 0.75
        assert provider._receiver_thread is None or not provider._receiver_thread.is_alive()
    finally:
        stalled_client.close()
        provider.stop()


def test_provider_has_no_tcp_listener():
    engine = _FakeEngine()
    provider = NetworkAudioProvider(engine, "127.0.0.1", 0)
    provider.start()
    try:
        with pytest.raises(OSError):
            socket.create_connection(("127.0.0.1", provider.port), timeout=0.2)
    finally:
        provider.stop()


def test_active_discovery_finds_provider_without_manual_address_entry():
    engine = _FakeEngine()
    provider = NetworkAudioProvider(engine, "127.0.0.1", 0, discoverable=True)
    provider.start()
    discovery = NetworkAudioDiscovery(
        provider.port,
        broadcast_addresses=("127.0.0.1",),
        interval=0.1,
        ttl=0.5,
    )
    discovery.start()
    try:
        assert _wait_until(lambda: len(discovery.snapshot()) == 1)
        found = discovery.snapshot()[0]
        assert found.host == "127.0.0.1"
        assert found.port == provider.port
        assert found.provider_name
        assert not found.busy
    finally:
        discovery.stop()
        provider.stop()


def test_provider_can_disable_and_reenable_automatic_discovery():
    engine = _FakeEngine()
    provider = NetworkAudioProvider(engine, "127.0.0.1", 0, discoverable=False)
    provider.start()
    discovery = NetworkAudioDiscovery(
        provider.port,
        broadcast_addresses=("127.0.0.1",),
        interval=0.1,
        ttl=0.5,
    )
    discovery.start()
    try:
        time.sleep(0.3)
        assert discovery.snapshot() == ()
        provider.set_discoverable(True)
        assert _wait_until(lambda: len(discovery.snapshot()) == 1)
    finally:
        discovery.stop()
        provider.stop()


@pytest.mark.parametrize("dropped_kind", [PACKET_CONNECT_OFFER, PACKET_START_ACK])
def test_client_retries_udp_connect_control_when_first_response_is_lost(monkeypatch, dropped_kind):
    engine = _FakeEngine()
    provider = NetworkAudioProvider(engine, "127.0.0.1", 0)
    provider.start()
    original_send = provider._send_packet
    dropped_response = False

    def drop_first_response(packet, address):
        nonlocal dropped_response
        if not dropped_response and datagram_kind(packet) == dropped_kind:
            dropped_response = True
            return
        original_send(packet, address)

    monkeypatch.setattr(provider, "_send_packet", drop_first_response)
    client = NetworkAudioClient("127.0.0.1", provider.port, jitter_ms=20, duplex=False)
    try:
        client.connect(timeout=2.0)
        assert dropped_response
        assert client.connected
        assert provider.status_snapshot()["state"] == "streaming"
    finally:
        client.close()
        provider.stop()
