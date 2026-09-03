"""Expose a local MeasureLab AudioEngine to one LAN client over UDP."""

from __future__ import annotations

import logging
import platform
import queue
import secrets
import socket
import threading
import time
from typing import TYPE_CHECKING

import numpy as np

from src.core.network_audio.indexed_buffer import IndexedAudioBuffer
from src.core.network_audio.models import NetworkAudioStats
from src.core.network_audio.protocol import (
    CONTROL_HEARTBEAT_TIMEOUT,
    DIRECTION_CAPTURE,
    DIRECTION_PLAYBACK,
    FLAG_INPUT_XRUN,
    FLAG_OUTPUT_XRUN,
    PACKET_AUDIO_NACK,
    PACKET_CONNECT_OFFER,
    PACKET_CONNECT_REQUEST,
    PACKET_CONTROL_ACK,
    PACKET_DISCOVER_QUERY,
    PACKET_DISCOVER_REPLY,
    PACKET_ERROR,
    PACKET_KEEPALIVE,
    PACKET_KEEPALIVE_ACK,
    PACKET_PLAYBACK_STATE,
    PACKET_START,
    PACKET_START_ACK,
    PACKET_STOP,
    PACKET_STOPPED,
    PROTOCOL_VERSION,
    ProtocolError,
    bounded_control_text,
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
from src.core.network_audio.retransmission import NackTracker, RetransmitHistory

if TYPE_CHECKING:
    from src.core.audio_engine import AudioEngine


_RESPONSE_CACHE_TTL = 10.0
_RESPONSE_CACHE_MAX = 256


class NetworkAudioProvider:
    """Single-port UDP control and audio bridge to a local AudioEngine."""

    def __init__(
        self,
        audio_engine: AudioEngine,
        bind_host: str = "0.0.0.0",
        port: int = 40100,
        *,
        allow_output: bool = False,
        discoverable: bool = True,
    ) -> None:
        self.audio_engine = audio_engine
        self.bind_host = str(bind_host).strip() or "0.0.0.0"
        self.port = int(port)
        self.logger = logging.getLogger(__name__)
        self.stats = NetworkAudioStats()
        self.running = False
        self.client_address = ""
        self.allow_output = bool(allow_output)
        self.discoverable = bool(discoverable)

        self._udp_socket: socket.socket | None = None
        self._client_udp: tuple[str, int] | None = None
        self._session_id = 0
        self._session_active = False
        self._last_control_received = 0.0
        self._client_requested_duplex = False
        self._client_playback_active = False
        self._duplex_negotiated = False
        self._duplex = False
        self._retransmission_negotiated = False
        self._retransmit_window_seconds = 0.0
        self._callback_id: int | None = None
        self._sample_index = 0
        self._capture_queue: queue.Queue[tuple[int, np.ndarray, int]] = queue.Queue(maxsize=64)
        self._playback_buffer: IndexedAudioBuffer | None = None
        self._capture_history: RetransmitHistory | None = None
        self._playback_nacks: NackTracker | None = None
        self._playback_active = threading.Event()
        self._playback_started_at: int | None = None
        self._stop_event = threading.Event()
        self._state_lock = threading.Lock()
        self._send_lock = threading.Lock()
        self._response_cache_lock = threading.Lock()
        self._receiver_thread: threading.Thread | None = None
        self._send_thread: threading.Thread | None = None
        self._response_cache: dict[tuple[tuple[str, int], int, int], tuple[float, bytes]] = {}
        self._instance_id = secrets.token_hex(16)
        self._provider_name = bounded_control_text(platform.node() or "MeasureLab", limit=120)
        self._input_device_name = "-"
        self._output_device_name = "-"
        self._input_channels = 0
        self._output_channels = 0

    def start(self) -> None:
        if self.running:
            return
        if not 0 <= self.port <= 65535:
            raise ValueError("invalid provider port")
        if getattr(self.audio_engine, "network_mode", False):
            raise RuntimeError("a network client cannot also provide local audio")
        if getattr(self.audio_engine, "offline_mode", False):
            raise RuntimeError("disable offline mode before providing local audio")
        if self.audio_engine.get_status().get("active_clients", 0):
            raise RuntimeError("stop active audio measurements before starting the provider")

        udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        acquired = False
        try:
            udp_socket.bind((self.bind_host, self.port))
            udp_socket.settimeout(0.2)
            self._input_device_name = self._device_name(self.audio_engine.input_device, True)
            self._output_device_name = self._device_name(self.audio_engine.output_device, False)
            self._input_channels, self._output_channels = self.audio_engine._update_channel_modes()
            self.audio_engine.acquire_exclusive_audio(
                self,
                role="remote_provider",
                status_provider=self.status_snapshot,
            )
            acquired = True
        except Exception:
            udp_socket.close()
            if acquired:
                self.audio_engine.release_exclusive_audio(self)
            raise
        self._udp_socket = udp_socket
        self.port = int(udp_socket.getsockname()[1])
        with self._response_cache_lock:
            self._response_cache.clear()
        self._stop_event.clear()
        self.running = True
        self.stats.set_state("listening")
        self._receiver_thread = threading.Thread(target=self._receive_loop, name="NetworkProviderRx", daemon=True)
        self._receiver_thread.start()

    def _receive_loop(self) -> None:
        while not self._stop_event.is_set():
            udp_socket = self._udp_socket
            if udp_socket is None:
                return
            try:
                packet, address = udp_socket.recvfrom(2048)
            except TimeoutError:
                self._expire_session()
                self._poll_playback_nacks()
                continue
            except OSError:
                return
            try:
                kind = datagram_kind(packet)
                if kind == DIRECTION_PLAYBACK:
                    self._handle_playback_audio(packet, address)
                    self._poll_playback_nacks()
                    continue
                header, message = decode_control_datagram(packet)
                cached = self._cached_response(address, header["kind"], header["message_id"])
                if cached is not None:
                    self._send_packet(cached, address)
                    continue
                self._handle_control(header, message, address)
                self._poll_playback_nacks()
            except (ProtocolError, TypeError, ValueError) as exc:
                if address == self._client_udp:
                    self.stats.record_corrupt(str(exc))
            except OSError as exc:
                if self._stop_event.is_set():
                    return
                self.logger.warning("Network audio UDP response failed: %s", exc)
            self._expire_session()

    def _handle_control(
        self,
        header: dict[str, int],
        message: dict[str, object],
        address: tuple[str, int],
    ) -> None:
        kind = header["kind"]
        message_id = header["message_id"]
        if message_id == 0:
            raise ProtocolError("control message ID is required")
        if kind == PACKET_DISCOVER_QUERY:
            self._handle_discover(header, message, address)
        elif kind == PACKET_CONNECT_REQUEST:
            self._handle_connect(header, message, address)
        elif kind == PACKET_START:
            self._handle_start(header, address)
        elif kind == PACKET_KEEPALIVE:
            self._handle_keepalive(header, address)
        elif kind == PACKET_PLAYBACK_STATE:
            self._handle_playback_state(header, message, address)
        elif kind == PACKET_STOP:
            self._handle_stop(header, address)
        elif kind == PACKET_AUDIO_NACK:
            self._handle_audio_nack(header, message, address)

    def _handle_discover(
        self,
        header: dict[str, int],
        message: dict[str, object],
        address: tuple[str, int],
    ) -> None:
        if not self.discoverable or header["session_id"] != 0:
            return
        if control_int(message, "protocol", -1) != PROTOCOL_VERSION:
            return
        nonce = control_str(message, "nonce", "", limit=64)
        if not nonce:
            return
        response = self._send_control(
            PACKET_DISCOVER_REPLY,
            {
                "protocol": PROTOCOL_VERSION,
                "nonce": nonce,
                "instance_id": self._instance_id,
                "service_port": self.port,
                "provider_name": self._provider_name,
                "input_device_name": self._input_device_name,
                "output_device_name": self._output_device_name,
                "sample_rate": int(self.audio_engine.sample_rate),
                "block_size": int(self.audio_engine.block_size),
                "input_channels": self._input_channels,
                "output_channels": self._output_channels,
                "duplex": self.allow_output,
                "busy": self._client_udp is not None,
            },
            address,
            message_id=header["message_id"],
        )
        self._remember_response(address, header["kind"], header["message_id"], response)

    def _handle_connect(
        self,
        header: dict[str, int],
        message: dict[str, object],
        address: tuple[str, int],
    ) -> None:
        if header["session_id"] != 0:
            raise ProtocolError("connect request must not have a session")
        if control_int(message, "protocol", -1) != PROTOCOL_VERSION:
            self._send_error("unsupported client protocol", address, header["message_id"])
            return
        client_nonce = control_str(message, "client_nonce", "", limit=64)
        if not client_nonce:
            raise ProtocolError("client nonce is required")
        requested_duplex = control_bool(message, "duplex", False)
        requested_retransmission = control_bool(message, "retransmission", False)
        retransmit_window_ms = 100
        if requested_retransmission:
            retransmit_window_ms = control_int(message, "retransmit_window_ms", 100)
            if not 20 <= retransmit_window_ms <= 250:
                raise ProtocolError("client retransmission window is invalid")
        with self._state_lock:
            if not self.running or self._stop_event.is_set():
                return
            if self._client_udp is not None:
                self._send_error("provider is already in use", address, header["message_id"])
                return
            self._session_id = secrets.randbits(63) or 1
            self._client_udp = address
            self._last_control_received = time.monotonic()
            self._client_requested_duplex = requested_duplex
            self._duplex_negotiated = requested_duplex and self.allow_output
            self._duplex = self._duplex_negotiated
            self._retransmission_negotiated = requested_retransmission
            self._retransmit_window_seconds = retransmit_window_ms / 1000.0
            self._playback_buffer = IndexedAudioBuffer(
                capacity_frames=max(int(self.audio_engine.sample_rate) * 4, int(self.audio_engine.block_size) * 16),
                channels=self._output_channels,
            )
            session_id = self._session_id
        response = self._send_control(
            PACKET_CONNECT_OFFER,
            {
                "protocol": PROTOCOL_VERSION,
                "client_nonce": client_nonce,
                "session_id": session_id,
                "sample_rate": int(self.audio_engine.sample_rate),
                "block_size": int(self.audio_engine.block_size),
                "input_channels": self._input_channels,
                "output_channels": self._output_channels,
                "provider_name": self._provider_name,
                "input_device_name": self._input_device_name,
                "output_device_name": self._output_device_name,
                "duplex": self._duplex,
                "retransmission": self._retransmission_negotiated,
                "retransmit_window_ms": retransmit_window_ms,
            },
            address,
            session_id=session_id,
            message_id=header["message_id"],
        )
        self._remember_response(address, header["kind"], header["message_id"], response)

    def _handle_start(self, header: dict[str, int], address: tuple[str, int]) -> None:
        try:
            with self._state_lock:
                if (
                    not self.running
                    or self._stop_event.is_set()
                    or not self._matches_session(header, address)
                    or self._session_active
                ):
                    return
                self._sample_index = 0
                self._capture_queue = queue.Queue(maxsize=64)
                if self._retransmission_negotiated:
                    self._capture_history = RetransmitHistory(self._retransmit_window_seconds)
                    self._playback_nacks = NackTracker(
                        self._retransmit_window_seconds,
                        expected_sequence=None,
                    )
                    if self._udp_socket is not None:
                        self._udp_socket.settimeout(0.01)
                else:
                    self._capture_history = None
                    self._playback_nacks = None
                self._client_playback_active = False
                self._playback_active.clear()
                self._playback_started_at = None
                self._callback_id = self.audio_engine.register_callback(self._audio_callback, owner=self)
                self._session_active = True
                self.client_address = address[0]
                self._last_control_received = time.monotonic()
                self.stats.set_state("streaming")
            response = self._send_control(
                PACKET_START_ACK,
                {},
                address,
                session_id=self._session_id,
                message_id=header["message_id"],
            )
            self._remember_response(address, header["kind"], header["message_id"], response)
            self._send_thread = threading.Thread(
                target=self._send_loop,
                args=(self._session_id, self._capture_queue, address),
                name="NetworkProviderTx",
                daemon=True,
            )
            self._send_thread.start()
        except Exception as exc:
            try:
                self._send_error(str(exc), address, header["message_id"], session_id=header["session_id"])
            except OSError:
                pass
            finally:
                self._end_session()

    def _handle_keepalive(self, header: dict[str, int], address: tuple[str, int]) -> None:
        if not self._matches_session(header, address) or not self._session_active:
            return
        self._last_control_received = time.monotonic()
        response = self._send_control(
            PACKET_KEEPALIVE_ACK,
            {},
            address,
            session_id=self._session_id,
            message_id=header["message_id"],
        )
        self._remember_response(address, header["kind"], header["message_id"], response)

    def _handle_playback_state(
        self,
        header: dict[str, int],
        message: dict[str, object],
        address: tuple[str, int],
    ) -> None:
        if not self._matches_session(header, address) or not self._session_active:
            return
        self._last_control_received = time.monotonic()
        active = control_bool(message, "active", False)
        expected_sequence: int | None = None
        if active and "next_sequence" in message:
            expected_sequence = control_int(message, "next_sequence")
            if not 0 <= expected_sequence <= 0xFFFFFFFFFFFFFFFF:
                raise ProtocolError("invalid playback sequence")
        self._set_client_playback_active(active, expected_sequence)
        response = self._send_control(
            PACKET_CONTROL_ACK,
            {"request_kind": PACKET_PLAYBACK_STATE},
            address,
            session_id=self._session_id,
            message_id=header["message_id"],
        )
        self._remember_response(address, header["kind"], header["message_id"], response)

    def _handle_stop(self, header: dict[str, int], address: tuple[str, int]) -> None:
        if not self._matches_session(header, address):
            return
        response = self._send_control(
            PACKET_STOPPED,
            {},
            address,
            session_id=self._session_id,
            message_id=header["message_id"],
        )
        self._remember_response(address, header["kind"], header["message_id"], response)
        self._end_session()

    def _matches_session(self, header: dict[str, int], address: tuple[str, int]) -> bool:
        return address == self._client_udp and header["session_id"] == self._session_id and self._session_id != 0

    def _handle_audio_nack(
        self,
        header: dict[str, int],
        message: dict[str, object],
        address: tuple[str, int],
    ) -> None:
        history = self._capture_history
        if (
            not self._retransmission_negotiated
            or history is None
            or not self._session_active
            or not self._matches_session(header, address)
        ):
            return
        self._last_control_received = time.monotonic()
        direction, sequences = decode_audio_nack(message)
        if direction != DIRECTION_CAPTURE:
            raise ProtocolError("invalid provider NACK direction")
        packets, misses = history.take_for_retransmit(sequences)
        self.stats.record_retransmit_cache_misses(misses)
        for packet in packets:
            self._send_packet(packet, address)
            self.stats.record_tx(len(packet))
            self.stats.record_retransmit()

    def _handle_playback_audio(self, packet: bytes, address: tuple[str, int]) -> None:
        playback = self._playback_buffer
        if not self._session_active or address != self._client_udp or playback is None:
            return
        header, data = decode_audio_packet(packet)
        if header["session_id"] != self._session_id or header["direction"] != DIRECTION_PLAYBACK:
            return
        if not self._playback_active.is_set():
            return
        recovered = False
        if self._playback_nacks is not None:
            recovered = self._playback_nacks.observe(header["sequence"])
        if header["sample_index"] + len(data) <= self._sample_index:
            self.stats.record_late()
            return
        result = playback.put(header["sample_index"], data)
        if result == "duplicate":
            self.stats.record_duplicate()
        elif result == "late":
            self.stats.record_late()
        else:
            if self._playback_started_at is None:
                self._playback_started_at = header["sample_index"]
            self.stats.record_rx(len(packet))
            self.stats.set_buffered_frames(playback.buffered_frames())
            if recovered:
                self.stats.record_recovery(len(data))

    def _poll_playback_nacks(self) -> None:
        tracker = self._playback_nacks
        address = self._client_udp
        if (
            not self._retransmission_negotiated
            or tracker is None
            or address is None
            or not self._session_active
            or not self._playback_active.is_set()
        ):
            return
        sequences, expired = tracker.poll()
        self.stats.record_retransmit_expired(expired)
        if not sequences:
            return
        try:
            packet = encode_control_datagram(
                PACKET_AUDIO_NACK,
                {"direction": DIRECTION_PLAYBACK, "sequences": sequences},
                session_id=self._session_id,
                message_id=secrets.randbits(63) or 1,
            )
            self._send_packet(packet, address)
            self.stats.record_nack_sent(len(sequences))
        except (OSError, ProtocolError) as exc:
            if not self._stop_event.is_set():
                self.stats.set_state("error", f"audio retransmission request failed: {exc}")

    def _send_control(
        self,
        kind: int,
        message: dict[str, object],
        address: tuple[str, int],
        *,
        session_id: int = 0,
        message_id: int,
    ) -> bytes:
        packet = encode_control_datagram(kind, message, session_id=session_id, message_id=message_id)
        self._send_packet(packet, address)
        return packet

    def _send_error(
        self,
        error: str,
        address: tuple[str, int],
        message_id: int,
        *,
        session_id: int = 0,
    ) -> None:
        self._send_control(
            PACKET_ERROR,
            {"error": bounded_control_text(error, limit=800)},
            address,
            session_id=session_id,
            message_id=message_id,
        )

    def _send_packet(self, packet: bytes, address: tuple[str, int]) -> None:
        udp_socket = self._udp_socket
        if udp_socket is None:
            raise OSError("provider UDP socket is unavailable")
        with self._send_lock:
            udp_socket.sendto(packet, address)

    def _remember_response(
        self,
        address: tuple[str, int],
        request_kind: int,
        message_id: int,
        response: bytes,
    ) -> None:
        with self._response_cache_lock:
            if len(self._response_cache) >= _RESPONSE_CACHE_MAX:
                oldest = min(self._response_cache, key=lambda key: self._response_cache[key][0])
                self._response_cache.pop(oldest, None)
            self._response_cache[(address, request_kind, message_id)] = (time.monotonic(), response)

    def _cached_response(self, address: tuple[str, int], request_kind: int, message_id: int) -> bytes | None:
        now = time.monotonic()
        with self._response_cache_lock:
            expired = [
                key for key, (created, _packet) in self._response_cache.items() if now - created > _RESPONSE_CACHE_TTL
            ]
            for key in expired:
                self._response_cache.pop(key, None)
            cached = self._response_cache.get((address, request_kind, message_id))
        return cached[1] if cached is not None else None

    def _expire_session(self) -> None:
        if self._client_udp is None:
            return
        if time.monotonic() - self._last_control_received >= CONTROL_HEARTBEAT_TIMEOUT:
            self._end_session()

    def _device_name(self, device_id, is_input: bool) -> str:
        try:
            devices = self.audio_engine.list_devices()
            if device_id is None:
                return "System Default Input" if is_input else "System Default Output"
            index = int(device_id)
            if 0 <= index < len(devices):
                return bounded_control_text(devices[index].get("name", device_id), limit=280)
        except (OSError, TypeError, ValueError):
            pass
        return bounded_control_text(device_id or "System Default", limit=280)

    def set_allow_output(self, enabled: bool) -> None:
        """Arm or immediately mute remote playback."""
        self.allow_output = bool(enabled)
        self._duplex = self._duplex_negotiated and self.allow_output
        self._set_playback_active(self._client_playback_active)

    def set_discoverable(self, enabled: bool) -> None:
        self.discoverable = bool(enabled)

    def _set_client_playback_active(self, active: bool, expected_sequence: int | None = None) -> None:
        self._client_playback_active = bool(active)
        self._set_playback_active(self._client_playback_active, expected_sequence)

    def _set_playback_active(self, active: bool, expected_sequence: int | None = None) -> None:
        playback_buffer = self._playback_buffer
        active = bool(active and self._duplex)
        if active:
            if self._playback_active.is_set():
                return
            if playback_buffer is not None:
                playback_buffer.clear()
            if self._playback_nacks is not None:
                self._playback_nacks.reset(expected_sequence)
            self._playback_started_at = None
            self._playback_active.set()
            return
        self._playback_active.clear()
        self._playback_started_at = None
        if playback_buffer is not None:
            playback_buffer.clear()
        if self._playback_nacks is not None:
            self._playback_nacks.reset(None)

    def _audio_callback(self, indata, outdata, frames, time_info, status) -> None:
        del time_info
        sample_index = self._sample_index
        flags = 0
        if getattr(status, "input_overflow", False) or getattr(status, "input_underflow", False):
            flags |= FLAG_INPUT_XRUN
        if getattr(status, "output_overflow", False) or getattr(status, "output_underflow", False):
            flags |= FLAG_OUTPUT_XRUN

        outdata.fill(0)
        playback_buffer = self._playback_buffer
        if self._duplex and self._playback_active.is_set() and playback_buffer is not None:
            playback, missing = playback_buffer.read(sample_index, frames)
            if self._playback_started_at is not None and sample_index >= self._playback_started_at and missing:
                flags |= FLAG_OUTPUT_XRUN
                for _missing_start, missing_frames in missing:
                    self.stats.record_loss(missing_frames)
            channels = min(outdata.shape[1], playback.shape[1])
            outdata[:, :channels] = playback[:, :channels]

        capture = np.asarray(indata, dtype=np.float32)
        try:
            self._capture_queue.put_nowait((sample_index, capture.copy(), flags))
        except queue.Full:
            self.stats.record_queue_overflow(frames)
        self._sample_index += frames

    def _send_loop(
        self,
        session_id: int,
        capture_queue: queue.Queue[tuple[int, np.ndarray, int]],
        client_udp: tuple[str, int],
    ) -> None:
        send_sequence = 0
        while not self._stop_event.is_set() and self._session_active and self._session_id == session_id:
            try:
                sample_index, block, flags = capture_queue.get(timeout=0.25)
            except queue.Empty:
                continue
            try:
                packets = packetize_audio(
                    block,
                    direction=DIRECTION_CAPTURE,
                    flags=flags,
                    session_id=session_id,
                    first_sequence=send_sequence,
                    sample_index=sample_index,
                )
                first_sequence = send_sequence
                send_sequence += len(packets)
                history = self._capture_history
                for offset, packet in enumerate(packets):
                    if history is not None:
                        history.add(first_sequence + offset, packet)
                    self._send_packet(packet, client_udp)
                    self.stats.record_tx(len(packet))
            except (OSError, ProtocolError) as exc:
                if not self._stop_event.is_set() and self._session_id == session_id:
                    self.stats.set_state("error", str(exc))
                return

    def _end_session(self) -> None:
        with self._state_lock:
            callback_id = self._callback_id
            self._callback_id = None
            self._session_active = False
            self._session_id = 0
            self._client_udp = None
            # A late retry must not revive a CONNECT/START response for a
            # session that has already ended. Keep STOPPED briefly so a lost
            # shutdown acknowledgement can still be recovered.
            with self._response_cache_lock:
                self._response_cache = {
                    key: value for key, value in self._response_cache.items() if key[1] == PACKET_STOP
                }
        if callback_id is not None:
            self.audio_engine.unregister_callback(callback_id)
        current = threading.current_thread()
        send_thread = self._send_thread
        if send_thread is not None and send_thread is not current:
            send_thread.join(timeout=1.0)
        self._send_thread = None
        self.client_address = ""
        self._client_requested_duplex = False
        self._client_playback_active = False
        self._duplex_negotiated = False
        self._duplex = False
        self._retransmission_negotiated = False
        self._playback_active.clear()
        self._playback_buffer = None
        if self._capture_history is not None:
            self._capture_history.clear()
        self._capture_history = None
        self._playback_nacks = None
        self._playback_started_at = None
        self._last_control_received = 0.0
        if self._udp_socket is not None:
            self._udp_socket.settimeout(0.2)
        if self.running:
            self.stats.set_state("listening")

    def stop(self) -> None:
        with self._state_lock:
            self.running = False
            self._stop_event.set()
            address = self._client_udp
            session_id = self._session_id
        if address is not None and session_id:
            try:
                self._send_control(
                    PACKET_STOPPED,
                    {"reason": "provider stopped"},
                    address,
                    session_id=session_id,
                    message_id=secrets.randbits(63) or 1,
                )
            except (OSError, ProtocolError):
                pass
        udp_socket = self._udp_socket
        self._udp_socket = None
        if udp_socket is not None:
            try:
                udp_socket.close()
            except OSError:
                pass
        self._end_session()
        current = threading.current_thread()
        receiver_thread = self._receiver_thread
        if receiver_thread is not None and receiver_thread is not current:
            receiver_thread.join(timeout=1.0)
        self._receiver_thread = None
        self.audio_engine.release_exclusive_audio(self)
        self.stats.set_state("stopped")

    def status_snapshot(self) -> dict[str, object]:
        snapshot = self.stats.snapshot()
        snapshot.update(
            {
                "running": self.running,
                "bind_host": self.bind_host,
                "port": self.port,
                "client_address": self.client_address,
                "duplex": self._duplex,
                "retransmission_active": self._retransmission_negotiated,
                "allow_output": self.allow_output,
                "discoverable": self.discoverable,
                "playback_active": self._playback_active.is_set(),
                "provider_name": self._provider_name,
                "input_device_name": self._input_device_name,
                "output_device_name": self._output_device_name,
                "sample_rate": int(self.audio_engine.sample_rate),
                "block_size": int(self.audio_engine.block_size),
                "protocol": PROTOCOL_VERSION,
            }
        )
        return snapshot
