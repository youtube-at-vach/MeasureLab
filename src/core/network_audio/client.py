"""Client session and AudioEngine-compatible stream for UDP remote audio I/O."""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
import queue
import secrets
import socket
import threading
import time
from typing import Callable

import numpy as np

from src.core.network_audio.indexed_buffer import IndexedAudioBuffer
from src.core.network_audio.models import NetworkAudioStats, NetworkStatusFlags, NetworkStreamTime
from src.core.network_audio.protocol import (
    CONTROL_HEARTBEAT_INTERVAL,
    CONTROL_HEARTBEAT_TIMEOUT,
    DIRECTION_CAPTURE,
    DIRECTION_PLAYBACK,
    FLAG_INPUT_XRUN,
    FLAG_OUTPUT_XRUN,
    PACKET_AUDIO_NACK,
    PACKET_CONNECT_OFFER,
    PACKET_CONNECT_REQUEST,
    PACKET_CONTROL_ACK,
    PACKET_ERROR,
    PACKET_KEEPALIVE,
    PACKET_PLAYBACK_STATE,
    PACKET_START,
    PACKET_START_ACK,
    PACKET_STOP,
    PACKET_STOPPED,
    PROTOCOL_VERSION,
    ProtocolError,
    control_bool,
    control_int,
    control_str,
    datagram_kind,
    decode_audio_nack,
    decode_audio_packet,
    decode_control_datagram,
    encode_control_datagram,
    packetize_audio,
)
from src.core.network_audio.retransmission import NackTracker, RetransmitHistory, history_packet_capacity


@dataclass(slots=True)
class _PendingControl:
    expected_kind: int
    event: threading.Event = field(default_factory=threading.Event)
    header: dict[str, int] | None = None
    message: dict[str, object] | None = None
    error: str = ""


class NetworkAudioClient:
    """Connected UDP control/data session to one MeasureLab provider."""

    def __init__(
        self,
        host: str,
        port: int,
        *,
        jitter_ms: int = 100,
        duplex: bool = True,
        retransmission: bool = True,
    ) -> None:
        self.host = str(host).strip()
        self.port = int(port)
        self.jitter_ms = max(20, min(2000, int(jitter_ms)))
        self.duplex = bool(duplex)
        self.retransmission = bool(retransmission)
        self.retransmission_active = False
        self.logger = logging.getLogger(__name__)
        self.stats = NetworkAudioStats()

        self.sample_rate = 0
        self.block_size = 0
        self.input_channels = 0
        self.output_channels = 0
        self.session_id = 0
        self.provider_name = ""
        self.input_device_name = ""
        self.output_device_name = ""
        self.jitter_frames = 0
        self.playout_delay_frames = 0

        self._udp_socket: socket.socket | None = None
        self._provider_udp: tuple[str, int] | None = None
        self._capture_buffer: IndexedAudioBuffer | None = None
        self._stop_event = threading.Event()
        self._send_lock = threading.Lock()
        self._pending_lock = threading.Lock()
        self._pending: dict[int, _PendingControl] = {}
        self._receiver_thread: threading.Thread | None = None
        self._heartbeat_thread: threading.Thread | None = None
        self._sender_thread: threading.Thread | None = None
        self._playback_queue: queue.Queue[tuple[int, np.ndarray, int]] = queue.Queue(maxsize=64)
        self._capture_nacks: NackTracker | None = None
        self._playback_history: RetransmitHistory | None = None
        self._retransmit_window_seconds = 0.0
        self._send_sequence = 0
        self._pending_remote_input_xrun = False
        self._pending_remote_output_xrun = False
        self._playback_active = False
        self._last_control_received = 0.0
        self._closing = False
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected and not self._stop_event.is_set()

    def connect(self, timeout: float = 5.0) -> None:
        if self.connected:
            return
        if not self.host or not 1 <= self.port <= 65535:
            raise ValueError("invalid network audio endpoint")
        if self._udp_socket is not None:
            self.close()

        addresses = socket.getaddrinfo(self.host, self.port, socket.AF_INET, socket.SOCK_DGRAM)
        if not addresses:
            raise OSError("remote provider address was not found")
        provider = (str(addresses[0][4][0]), int(addresses[0][4][1]))
        udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        client_nonce = secrets.token_hex(16)
        try:
            udp_socket.connect(provider)
            udp_socket.settimeout(min(0.5, max(0.1, float(timeout))))
            offer_header, offer = self._exchange_before_start(
                udp_socket,
                PACKET_CONNECT_REQUEST,
                {
                    "protocol": PROTOCOL_VERSION,
                    "client_nonce": client_nonce,
                    "duplex": self.duplex,
                    "retransmission": self.retransmission,
                    "retransmit_window_ms": min(250, self.jitter_ms),
                },
                PACKET_CONNECT_OFFER,
                session_id=0,
                timeout=timeout,
            )
            self._apply_offer(offer_header, offer, client_nonce)
            self._capture_buffer = IndexedAudioBuffer(
                capacity_frames=max(self.sample_rate * 4, self.block_size * 16),
                channels=self.input_channels,
            )
            if self.retransmission_active:
                self._capture_nacks = NackTracker(self._retransmit_window_seconds, expected_sequence=0)
                self._playback_history = RetransmitHistory(
                    self._retransmit_window_seconds,
                    max_packets=history_packet_capacity(
                        self.sample_rate,
                        self.block_size,
                        self._retransmit_window_seconds,
                    ),
                )
            else:
                self._capture_nacks = None
                self._playback_history = None
            self._exchange_before_start(
                udp_socket,
                PACKET_START,
                {},
                PACKET_START_ACK,
                session_id=self.session_id,
                timeout=timeout,
            )
            udp_socket.settimeout(0.2)
            self._provider_udp = provider
            self._udp_socket = udp_socket
            self._stop_event.clear()
            self._closing = False
            self._connected = True
            self._playback_queue = queue.Queue(maxsize=64)
            self._send_sequence = 0
            self._pending_remote_input_xrun = False
            self._pending_remote_output_xrun = False
            self._playback_active = False
            self._last_control_received = time.monotonic()
            self.stats.jitter_frames = self.jitter_frames
            self.stats.set_state("connected")
            self._receiver_thread = threading.Thread(target=self._receive_loop, name="NetworkAudioRx", daemon=True)
            self._sender_thread = threading.Thread(target=self._send_loop, name="NetworkAudioTx", daemon=True)
            self._heartbeat_thread = threading.Thread(
                target=self._heartbeat_loop,
                name="NetworkAudioHeartbeat",
                daemon=True,
            )
            self._receiver_thread.start()
            self._sender_thread.start()
            self._heartbeat_thread.start()
        except Exception:
            if self.session_id:
                try:
                    udp_socket.send(
                        encode_control_datagram(
                            PACKET_STOP,
                            {},
                            session_id=self.session_id,
                            message_id=secrets.randbits(63) or 1,
                        )
                    )
                except (OSError, ProtocolError):
                    pass
            udp_socket.close()
            self._capture_buffer = None
            self._capture_nacks = None
            self._playback_history = None
            self.retransmission_active = False
            self.session_id = 0
            raise

    def _exchange_before_start(
        self,
        udp_socket: socket.socket,
        request_kind: int,
        message: dict[str, object],
        expected_kind: int,
        *,
        session_id: int,
        timeout: float,
    ) -> tuple[dict[str, int], dict[str, object]]:
        message_id = secrets.randbits(63) or 1
        packet = encode_control_datagram(
            request_kind,
            message,
            session_id=session_id,
            message_id=message_id,
        )
        deadline = time.monotonic() + max(0.2, float(timeout))
        wait = 0.2
        while time.monotonic() < deadline:
            udp_socket.send(packet)
            attempt_deadline = min(deadline, time.monotonic() + wait)
            while time.monotonic() < attempt_deadline:
                udp_socket.settimeout(max(0.01, attempt_deadline - time.monotonic()))
                try:
                    response = udp_socket.recv(2048)
                except TimeoutError:
                    break
                try:
                    kind = datagram_kind(response)
                    if kind in (DIRECTION_CAPTURE, DIRECTION_PLAYBACK):
                        continue
                    header, payload = decode_control_datagram(response)
                except ProtocolError:
                    continue
                if header["message_id"] != message_id:
                    continue
                if request_kind != PACKET_CONNECT_REQUEST and header["session_id"] != session_id:
                    continue
                if kind == PACKET_ERROR:
                    raise ProtocolError(control_str(payload, "error", "provider rejected connection", limit=500))
                if kind == expected_kind:
                    return header, payload
            wait = min(wait * 2.0, 1.0)
        raise TimeoutError("remote provider did not answer UDP control request")

    def _apply_offer(self, header: dict[str, int], offer: dict[str, object], client_nonce: str) -> None:
        self.session_id = control_int(offer, "session_id")
        if self.session_id != header["session_id"] or not 1 <= self.session_id <= 0xFFFFFFFFFFFFFFFF:
            raise ProtocolError("provider session ID is invalid")
        if control_int(offer, "protocol", -1) != PROTOCOL_VERSION:
            raise ProtocolError("provider protocol is unsupported")
        if control_str(offer, "client_nonce", "", limit=64) != client_nonce:
            raise ProtocolError("provider returned an invalid client nonce")
        self.sample_rate = control_int(offer, "sample_rate")
        self.block_size = control_int(offer, "block_size")
        self.input_channels = control_int(offer, "input_channels")
        self.output_channels = control_int(offer, "output_channels")
        if self.sample_rate < 1000 or self.sample_rate > 768000:
            raise ProtocolError("provider sample rate is invalid")
        if self.block_size < 16 or self.block_size > 262144:
            raise ProtocolError("provider block size is invalid")
        if self.input_channels not in (1, 2) or self.output_channels not in (1, 2):
            raise ProtocolError("provider channel count is unsupported")
        self.provider_name = control_str(offer, "provider_name", "Remote MeasureLab", limit=200)
        self.input_device_name = control_str(offer, "input_device_name", "Remote Input", limit=500)
        self.output_device_name = control_str(offer, "output_device_name", "Remote Output", limit=500)
        self.duplex = self.duplex and control_bool(offer, "duplex", False)
        offered_retransmission = control_bool(offer, "retransmission", False)
        self.retransmission_active = self.retransmission and offered_retransmission
        retransmit_window_ms = min(250, self.jitter_ms)
        if self.retransmission_active:
            retransmit_window_ms = control_int(offer, "retransmit_window_ms", retransmit_window_ms)
            if not 20 <= retransmit_window_ms <= 250:
                raise ProtocolError("provider retransmission window is invalid")
        self._retransmit_window_seconds = retransmit_window_ms / 1000.0
        self.jitter_frames = max(
            self.block_size * 2,
            int(round(self.sample_rate * self.jitter_ms / 1000.0 / self.block_size)) * self.block_size,
        )
        self.playout_delay_frames = max(self.jitter_frames * 2, self.block_size * 4)

    def _receive_loop(self) -> None:
        udp_socket = self._udp_socket
        capture_buffer = self._capture_buffer
        if udp_socket is None or capture_buffer is None:
            return
        while not self._stop_event.is_set():
            self._poll_capture_nacks()
            timeout = 0.2
            tracker = self._capture_nacks
            if tracker is not None:
                timeout = tracker.next_poll_delay(
                    timeout,
                    playout_sample=capture_buffer.consumed_until(),
                )
            try:
                udp_socket.settimeout(max(0.001, timeout))
                packet = udp_socket.recv(2048)
            except TimeoutError:
                continue
            except OSError as exc:
                if not self._stop_event.is_set():
                    self._fail(f"audio receive failed: {exc}")
                return
            try:
                kind = datagram_kind(packet)
                if kind == DIRECTION_CAPTURE:
                    self._accept_capture_audio(packet, capture_buffer)
                elif kind != DIRECTION_PLAYBACK:
                    header, message = decode_control_datagram(packet)
                    self._accept_control(header, message)
            except (ProtocolError, ValueError) as exc:
                self.stats.record_corrupt(str(exc))

    def _accept_capture_audio(self, packet: bytes, capture_buffer: IndexedAudioBuffer) -> None:
        header, data = decode_audio_packet(packet)
        if header["session_id"] != self.session_id or header["direction"] != DIRECTION_CAPTURE:
            return
        result = capture_buffer.put(header["sample_index"], data)
        recovered = False
        if self._capture_nacks is not None:
            recovered = self._capture_nacks.observe(
                header["sequence"],
                sample_index=header["sample_index"],
            )
        if result == "duplicate":
            self.stats.record_duplicate()
        elif result == "late":
            self.stats.record_late()
            if recovered:
                self.stats.record_retransmit_expired(1)
        else:
            self.stats.record_rx(len(packet))
            self.stats.set_buffered_frames(capture_buffer.buffered_frames())
            if recovered:
                self.stats.record_recovery(len(data))
        flags = header["flags"]
        if flags & FLAG_INPUT_XRUN:
            self.stats.record_remote_xrun(input_xrun=True)
            self._pending_remote_input_xrun = True
        if flags & FLAG_OUTPUT_XRUN:
            self.stats.record_remote_xrun(output_xrun=True)
            self._pending_remote_output_xrun = True

    def _accept_control(self, header: dict[str, int], message: dict[str, object]) -> None:
        if header["session_id"] != self.session_id:
            return
        self._last_control_received = time.monotonic()
        if header["kind"] == PACKET_AUDIO_NACK:
            self._handle_audio_nack(message)
            return
        with self._pending_lock:
            pending = self._pending.get(header["message_id"])
            if pending is not None and (header["kind"] == pending.expected_kind or header["kind"] == PACKET_ERROR):
                pending.header = header
                pending.message = message
                if header["kind"] == PACKET_ERROR:
                    pending.error = control_str(message, "error", "remote provider error", limit=500)
                pending.event.set()
                return
        if header["kind"] == PACKET_ERROR:
            self._fail(control_str(message, "error", "remote provider error", limit=500))
        elif header["kind"] == PACKET_STOPPED and not self._closing:
            self._fail(control_str(message, "reason", "remote provider stopped the session", limit=500))

    def _handle_audio_nack(self, message: dict[str, object]) -> None:
        history = self._playback_history
        if not self.retransmission_active or history is None:
            return
        direction, sequences = decode_audio_nack(message)
        if direction != DIRECTION_PLAYBACK:
            raise ProtocolError("invalid client NACK direction")
        packets, misses = history.take_for_retransmit(sequences)
        self.stats.record_retransmit_cache_misses(misses)
        for packet in packets:
            self._send_packet(packet)
            self.stats.record_tx(len(packet))
            self.stats.record_retransmit()

    def _poll_capture_nacks(self) -> None:
        tracker = self._capture_nacks
        if not self.retransmission_active or tracker is None or not self.connected:
            return
        capture_buffer = self._capture_buffer
        playout_sample = capture_buffer.consumed_until() if capture_buffer is not None else None
        sequences, expired = tracker.poll(playout_sample=playout_sample)
        self.stats.record_retransmit_expired(expired)
        if not sequences:
            return
        try:
            packet = encode_control_datagram(
                PACKET_AUDIO_NACK,
                {"direction": DIRECTION_CAPTURE, "sequences": sequences},
                session_id=self.session_id,
                message_id=secrets.randbits(63) or 1,
            )
            self._send_packet(packet)
            self.stats.record_nack_sent(len(sequences))
        except (OSError, ProtocolError) as exc:
            if not self._stop_event.is_set():
                self._fail(f"audio retransmission request failed: {exc}")

    def _send_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                sample_index, block, flags = self._playback_queue.get(timeout=0.25)
            except queue.Empty:
                continue
            udp_socket = self._udp_socket
            if udp_socket is None:
                continue
            try:
                packets = packetize_audio(
                    block,
                    direction=DIRECTION_PLAYBACK,
                    flags=flags,
                    session_id=self.session_id,
                    first_sequence=self._send_sequence,
                    sample_index=sample_index,
                )
                first_sequence = self._send_sequence
                self._send_sequence += len(packets)
                history = self._playback_history
                if history is not None:
                    history.add_many(first_sequence, packets)
                sent_packets = 0
                sent_bytes = 0
                try:
                    for packet in packets:
                        self._send_packet(packet)
                        sent_packets += 1
                        sent_bytes += len(packet)
                finally:
                    self.stats.record_tx_batch(sent_packets, sent_bytes)
            except (OSError, ProtocolError) as exc:
                if not self._stop_event.is_set():
                    self._fail(f"audio send failed: {exc}")
                return

    def _heartbeat_loop(self) -> None:
        while not self._stop_event.wait(CONTROL_HEARTBEAT_INTERVAL):
            if time.monotonic() - self._last_control_received >= CONTROL_HEARTBEAT_TIMEOUT:
                self._fail("control heartbeat timed out")
                return
            try:
                self._send_control_once(PACKET_KEEPALIVE, {})
            except (OSError, ProtocolError) as exc:
                if not self._stop_event.is_set():
                    self._fail(f"control connection lost: {exc}")
                return

    def _send_control_once(self, kind: int, message: dict[str, object]) -> None:
        packet = encode_control_datagram(
            kind,
            message,
            session_id=self.session_id,
            message_id=secrets.randbits(63) or 1,
        )
        self._send_packet(packet)

    def _request_control(
        self,
        kind: int,
        message: dict[str, object],
        expected_kind: int,
        *,
        timeout: float = 3.0,
    ) -> tuple[dict[str, int], dict[str, object]]:
        if self._udp_socket is None or not self.connected:
            raise ConnectionError("network audio client is disconnected")
        message_id = secrets.randbits(63) or 1
        pending = _PendingControl(expected_kind)
        with self._pending_lock:
            self._pending[message_id] = pending
        packet = encode_control_datagram(kind, message, session_id=self.session_id, message_id=message_id)
        deadline = time.monotonic() + max(0.2, timeout)
        wait = 0.2
        try:
            while time.monotonic() < deadline and not self._stop_event.is_set():
                self._send_packet(packet)
                if pending.event.wait(min(wait, max(0.0, deadline - time.monotonic()))):
                    if pending.error:
                        raise ProtocolError(pending.error)
                    if pending.header is None or pending.message is None:
                        raise ConnectionError("empty control response")
                    return pending.header, pending.message
                wait = min(wait * 2.0, 1.0)
            raise TimeoutError("remote provider did not acknowledge UDP control request")
        finally:
            with self._pending_lock:
                self._pending.pop(message_id, None)

    def _send_packet(self, packet: bytes) -> None:
        udp_socket = self._udp_socket
        if udp_socket is None:
            raise OSError("client UDP socket is unavailable")
        with self._send_lock:
            udp_socket.send(packet)

    def enqueue_playback(self, sample_index: int, block: np.ndarray, flags: int = 0) -> None:
        if not self.duplex or not self.connected:
            return
        try:
            self._playback_queue.put_nowait((int(sample_index), np.asarray(block, dtype=np.float32).copy(), int(flags)))
        except queue.Full:
            self.stats.record_queue_overflow(len(block))

    def set_playback_active(self, active: bool) -> None:
        """Reliably tell the provider whether playback packets are expected."""
        active = bool(active and self.duplex)
        if active == self._playback_active:
            return
        if not self.connected:
            self._playback_active = False
            return
        try:
            self._request_control(
                PACKET_PLAYBACK_STATE,
                {"active": active, "next_sequence": self._send_sequence},
                PACKET_CONTROL_ACK,
            )
        except (ConnectionError, OSError, ProtocolError, TimeoutError) as exc:
            self._fail(f"control connection lost: {exc}")
            return
        self._playback_active = active

    def first_capture_sample(self, timeout: float, cancel_event: threading.Event | None = None) -> int | None:
        buffer = self._capture_buffer
        if buffer is None:
            return None
        return buffer.stream_start_sample(self.jitter_frames, self.block_size, timeout, cancel_event)

    def read_capture(
        self,
        sample_index: int,
        frames: int,
        cancel_event: threading.Event | None = None,
    ) -> tuple[np.ndarray, NetworkStatusFlags] | None:
        buffer = self._capture_buffer
        if buffer is None:
            raise RuntimeError("network capture buffer is unavailable")
        target = sample_index + frames + self.jitter_frames
        # The future watermark paces callbacks against the provider clock.  A
        # network stall may consume the fixed jitter reserve, but it must not
        # add an unrelated 250 ms wait to every callback deadline.
        buffer.wait_until_buffered(
            target,
            frames / self.sample_rate,
            cancel_event,
        )
        if cancel_event is not None and cancel_event.is_set():
            return None
        data, missing = buffer.read(sample_index, frames)
        status = NetworkStatusFlags()
        for _missing_start, missing_frames in missing:
            status.input_overflow = True
            self.stats.record_loss(missing_frames)
        if self._pending_remote_input_xrun:
            status.input_overflow = True
            self._pending_remote_input_xrun = False
        if self._pending_remote_output_xrun:
            status.output_underflow = True
            self._pending_remote_output_xrun = False
        self.stats.set_buffered_frames(buffer.buffered_frames())
        return data, status

    def _fail(self, message: str) -> None:
        if self._stop_event.is_set():
            return
        self.logger.warning(message)
        self.stats.set_state("error", message)
        self._connected = False
        self._stop_event.set()
        self._playback_active = False
        with self._pending_lock:
            for pending in self._pending.values():
                pending.error = message
                pending.event.set()

    def close(self) -> None:
        send_stop = self.connected
        self._closing = True
        if send_stop:
            try:
                self._request_control(PACKET_STOP, {}, PACKET_STOPPED, timeout=1.5)
            except (ConnectionError, OSError, ProtocolError, TimeoutError):
                pass
        self._connected = False
        self._stop_event.set()
        udp_socket = self._udp_socket
        self._udp_socket = None
        if udp_socket is not None:
            try:
                udp_socket.close()
            except OSError:
                pass
        current = threading.current_thread()
        for thread in (self._receiver_thread, self._sender_thread, self._heartbeat_thread):
            if thread is not None and thread is not current:
                thread.join(timeout=1.0)
        self._receiver_thread = None
        self._sender_thread = None
        self._heartbeat_thread = None
        with self._pending_lock:
            self._pending.clear()
        self._provider_udp = None
        if self._playback_history is not None:
            self._playback_history.clear()
        self._playback_history = None
        self._capture_nacks = None
        self.retransmission_active = False
        self._closing = False
        self.stats.set_state("disconnected")

    def status_snapshot(self) -> dict[str, object]:
        snapshot = self.stats.snapshot()
        if self.sample_rate > 0:
            input_latency_ms = (self.jitter_frames + self.block_size) * 1000.0 / self.sample_rate
            output_latency_ms = (
                max(0, self.playout_delay_frames - self.jitter_frames - self.block_size) * 1000.0 / self.sample_rate
            )
        else:
            input_latency_ms = 0.0
            output_latency_ms = 0.0
        snapshot.update(
            {
                "provider_name": self.provider_name,
                "input_device_name": self.input_device_name,
                "output_device_name": self.output_device_name,
                "duplex": self.duplex,
                "retransmission_requested": self.retransmission,
                "retransmission_active": self.retransmission_active,
                "jitter_ms": self.jitter_ms,
                "playout_delay_frames": self.playout_delay_frames,
                "input_latency_ms": input_latency_ms,
                "output_latency_ms": output_latency_ms,
                "protocol": PROTOCOL_VERSION,
            }
        )
        return snapshot


class NetworkClientStream:
    """A ``sounddevice.Stream``-like driver paced by remote capture samples."""

    def __init__(
        self,
        client: NetworkAudioClient,
        callback: Callable[[np.ndarray, np.ndarray, int, NetworkStreamTime, NetworkStatusFlags], None],
    ) -> None:
        self.client = client
        self.callback = callback
        self.samplerate = client.sample_rate
        self.blocksize = client.block_size
        self.channels = (client.input_channels, client.output_channels)
        self.active = False
        self.cpu_load = 0.0
        input_latency = (client.jitter_frames + client.block_size) / client.sample_rate
        output_latency = max(
            0.0,
            (client.playout_delay_frames - client.jitter_frames - client.block_size) / client.sample_rate,
        )
        self.latency = (input_latency, output_latency)
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._sample_time_origin: float | None = None

    def start(self) -> None:
        if self.active:
            return
        if not self.client.connected:
            raise RuntimeError("network audio client is disconnected")
        self.active = True
        self._stop_event.clear()
        self._sample_time_origin = None
        self.client.stats.set_state("priming")
        self.client.set_playback_active(True)
        self._thread = threading.Thread(target=self._run, name="NetworkAudioCallback", daemon=True)
        self._thread.start()

    def _time_info_for_sample(self, sample_index: int) -> NetworkStreamTime:
        """Map remote sample positions onto one stable local monotonic timebase."""
        # read_capture() deliberately keeps the first sample of each callback
        # one callback block plus the configured jitter buffer behind the live
        # remote sample position.  Treating that sample as ``currentTime``
        # silently reports zero input latency to timing-sensitive instruments.
        current_sample = int(sample_index) + self.blocksize + self.client.jitter_frames
        if self._sample_time_origin is None:
            self._sample_time_origin = time.monotonic() - current_sample / self.samplerate

        input_time = self._sample_time_origin + int(sample_index) / self.samplerate
        return NetworkStreamTime(
            inputBufferAdcTime=input_time,
            currentTime=self._sample_time_origin + current_sample / self.samplerate,
            outputBufferDacTime=(
                self._sample_time_origin + (int(sample_index) + self.client.playout_delay_frames) / self.samplerate
            ),
        )

    def _run(self) -> None:
        expected = self.client.first_capture_sample(timeout=5.0, cancel_event=self._stop_event)
        if expected is None:
            if not self._stop_event.is_set() and self.client.connected:
                self.client._fail("timed out waiting for remote audio")
            self.active = False
            return
        self.client.stats.set_state("streaming")
        interval = self.blocksize / self.samplerate
        outdata = np.empty((self.blocksize, self.channels[1]), dtype=np.float32)
        while self.active and not self._stop_event.is_set() and self.client.connected:
            started = time.thread_time()
            capture = self.client.read_capture(expected, self.blocksize, cancel_event=self._stop_event)
            if capture is None or not self.active or self._stop_event.is_set():
                break
            indata, status = capture
            outdata.fill(0)
            time_info = self._time_info_for_sample(expected)
            try:
                self.callback(indata, outdata, self.blocksize, time_info, status)
            except Exception as exc:
                self.client._fail(f"network audio callback failed: {exc}")
                break
            if self.client.duplex:
                self.client.enqueue_playback(expected + self.client.playout_delay_frames, outdata)
            elapsed = time.thread_time() - started
            load = elapsed / interval if interval > 0 else 0.0
            self.cpu_load = 0.9 * self.cpu_load + 0.1 * load
            expected += self.blocksize
        self.active = False

    def stop(self) -> None:
        self.active = False
        self._stop_event.set()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=1.0)
        self._thread = None
        self.client.set_playback_active(False)
        if self.client.connected:
            self.client.stats.set_state("connected")

    def close(self) -> None:
        self.stop()
