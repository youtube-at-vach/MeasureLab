"""Expose a local MeasureLab AudioEngine to one LAN client."""

from __future__ import annotations

import logging
import platform
import queue
import secrets
import socket
import threading
from typing import TYPE_CHECKING

import numpy as np

from src.core.network_audio.indexed_buffer import IndexedAudioBuffer
from src.core.network_audio.models import NetworkAudioStats
from src.core.network_audio.protocol import (
    DIRECTION_CAPTURE,
    DIRECTION_PLAYBACK,
    FLAG_INPUT_XRUN,
    FLAG_OUTPUT_XRUN,
    PROTOCOL_VERSION,
    ProtocolError,
    control_bool,
    control_int,
    decode_audio_packet,
    packetize_audio,
    recv_control,
    send_control,
)

if TYPE_CHECKING:
    from src.core.audio_engine import AudioEngine


class NetworkAudioProvider:
    """TCP control server plus UDP bridge to a local AudioEngine."""

    def __init__(
        self,
        audio_engine: AudioEngine,
        bind_host: str = "0.0.0.0",
        port: int = 40100,
        *,
        allow_output: bool = False,
    ) -> None:
        self.audio_engine = audio_engine
        self.bind_host = str(bind_host).strip() or "0.0.0.0"
        self.port = int(port)
        self.logger = logging.getLogger(__name__)
        self.stats = NetworkAudioStats()
        self.running = False
        self.client_address = ""
        self.allow_output = bool(allow_output)

        self._tcp_socket: socket.socket | None = None
        self._udp_socket: socket.socket | None = None
        self._control_socket: socket.socket | None = None
        self._client_udp: tuple[str, int] | None = None
        self._session_id = 0
        self._client_requested_duplex = False
        self._duplex_negotiated = False
        self._duplex = False
        self._callback_id: int | None = None
        self._sample_index = 0
        self._capture_queue: queue.Queue[tuple[int, np.ndarray, int]] = queue.Queue(maxsize=64)
        self._playback_buffer: IndexedAudioBuffer | None = None
        self._playback_started_at: int | None = None
        self._stop_event = threading.Event()
        self._accept_thread: threading.Thread | None = None
        self._receive_thread: threading.Thread | None = None
        self._send_thread: threading.Thread | None = None

    def start(self) -> None:
        if self.running:
            return
        if not 0 <= self.port <= 65535:
            raise ValueError("invalid provider port")
        if getattr(self.audio_engine, "network_mode", False):
            raise RuntimeError("a network client cannot also provide local audio")
        if self.audio_engine.get_status().get("active_clients", 0):
            raise RuntimeError("stop active audio measurements before starting the provider")

        tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            tcp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            tcp_socket.bind((self.bind_host, self.port))
            tcp_socket.listen(1)
            tcp_socket.settimeout(0.5)
            udp_socket.bind((self.bind_host, 0))
            udp_socket.settimeout(0.5)
            self.audio_engine.acquire_exclusive_audio(self)
        except Exception:
            tcp_socket.close()
            udp_socket.close()
            raise
        self._tcp_socket = tcp_socket
        self.port = int(tcp_socket.getsockname()[1])
        self._udp_socket = udp_socket
        self._stop_event.clear()
        self.running = True
        self.stats.set_state("listening")
        self._accept_thread = threading.Thread(target=self._accept_loop, name="NetworkAudioAccept", daemon=True)
        self._accept_thread.start()

    def _accept_loop(self) -> None:
        tcp_socket = self._tcp_socket
        if tcp_socket is None:
            return
        while not self._stop_event.is_set():
            try:
                control, address = tcp_socket.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            if self._control_socket is not None:
                try:
                    send_control(control, {"type": "error", "error": "provider is already in use"})
                except OSError:
                    pass
                control.close()
                continue
            try:
                self._serve_client(control, address)
            except (OSError, ValueError, ProtocolError, RuntimeError) as exc:
                self.logger.warning("Network audio client rejected: %s", exc)
                try:
                    send_control(control, {"type": "error", "error": str(exc)[:500]})
                except OSError:
                    pass
                control.close()
                self._end_session()

    def _serve_client(self, control: socket.socket, address: tuple[str, int]) -> None:
        control.settimeout(5.0)
        hello = recv_control(control)
        if hello.get("type") != "hello" or control_int(hello, "protocol", -1) != PROTOCOL_VERSION:
            raise ProtocolError("unsupported client protocol")
        client_udp_port = control_int(hello, "udp_port", 0)
        if not 1 <= client_udp_port <= 65535:
            raise ProtocolError("invalid client UDP port")
        if self.audio_engine.get_status().get("active_clients", 0):
            raise RuntimeError("local audio engine became busy")

        self._session_id = secrets.randbits(63) or 1
        self._client_requested_duplex = control_bool(hello, "duplex", False)
        self._duplex_negotiated = self._client_requested_duplex and self.allow_output
        self._duplex = self._duplex_negotiated
        self._control_socket = control
        self._client_udp = (address[0], client_udp_port)
        self.client_address = address[0]
        in_channels, out_channels = self.audio_engine._update_channel_modes()
        self._playback_buffer = IndexedAudioBuffer(
            capacity_frames=max(int(self.audio_engine.sample_rate) * 4, int(self.audio_engine.block_size) * 16),
            channels=out_channels,
        )
        udp_socket = self._udp_socket
        if udp_socket is None:
            raise RuntimeError("provider UDP socket is unavailable")
        send_control(
            control,
            {
                "type": "offer",
                "protocol": PROTOCOL_VERSION,
                "session_id": self._session_id,
                "udp_port": udp_socket.getsockname()[1],
                "sample_rate": int(self.audio_engine.sample_rate),
                "block_size": int(self.audio_engine.block_size),
                "input_channels": in_channels,
                "output_channels": out_channels,
                "provider_name": platform.node() or "MeasureLab",
                "input_device_name": self._device_name(self.audio_engine.input_device, True),
                "output_device_name": self._device_name(self.audio_engine.output_device, False),
                "duplex": self._duplex,
            },
        )
        start = recv_control(control)
        if start.get("type") != "start" or control_int(start, "session_id", 0) != self._session_id:
            raise ProtocolError("client did not start negotiated session")

        control.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        control.settimeout(None)
        self._sample_index = 0
        self._capture_queue = queue.Queue(maxsize=64)
        self._playback_started_at = None
        self._callback_id = self.audio_engine.register_callback(self._audio_callback, owner=self)
        self.stats.set_state("streaming")
        self._receive_thread = threading.Thread(
            target=self._receive_loop,
            args=(self._session_id, control, self._playback_buffer, self._client_udp),
            name="NetworkProviderRx",
            daemon=True,
        )
        self._send_thread = threading.Thread(
            target=self._send_loop,
            args=(self._session_id, control, self._capture_queue, self._client_udp),
            name="NetworkProviderTx",
            daemon=True,
        )
        self._receive_thread.start()
        self._send_thread.start()

        while not self._stop_event.is_set() and self._control_socket is control:
            try:
                message = recv_control(control)
            except TimeoutError:
                continue
            if message.get("type") == "stop":
                try:
                    send_control(control, {"type": "stopped"})
                except OSError:
                    pass
                break
        self._end_session()

    def _device_name(self, device_id, is_input: bool) -> str:
        try:
            devices = self.audio_engine.list_devices()
            if device_id is None:
                return "System Default Input" if is_input else "System Default Output"
            index = int(device_id)
            if 0 <= index < len(devices):
                return str(devices[index].get("name", device_id))[:500]
        except (OSError, TypeError, ValueError):
            pass
        return str(device_id or "System Default")[:500]

    def set_allow_output(self, enabled: bool) -> None:
        """Arm or immediately mute remote playback."""
        self.allow_output = bool(enabled)
        self._duplex = self._duplex_negotiated and self.allow_output

    def _audio_callback(self, indata, outdata, frames, time_info, status) -> None:
        del time_info
        sample_index = self._sample_index
        flags = 0
        if getattr(status, "input_overflow", False) or getattr(status, "input_underflow", False):
            flags |= FLAG_INPUT_XRUN
        if getattr(status, "output_overflow", False) or getattr(status, "output_underflow", False):
            flags |= FLAG_OUTPUT_XRUN

        outdata.fill(0)
        if self._duplex and self._playback_buffer is not None:
            playback, missing = self._playback_buffer.read(sample_index, frames)
            if self._playback_started_at is not None and sample_index >= self._playback_started_at and missing:
                flags |= FLAG_OUTPUT_XRUN
                for missing_start, missing_frames in missing:
                    self.stats.record_loss("playback", missing_start, missing_frames)
            channels = min(outdata.shape[1], playback.shape[1])
            outdata[:, :channels] = playback[:, :channels]

        capture = np.asarray(indata, dtype=np.float32)
        try:
            self._capture_queue.put_nowait((sample_index, capture.copy(), flags))
        except queue.Full:
            self.stats.record_queue_overflow("capture", sample_index, frames)
        self._sample_index += frames

    def _receive_loop(
        self,
        session_id: int,
        control: socket.socket,
        playback: IndexedAudioBuffer,
        client_udp: tuple[str, int],
    ) -> None:
        udp_socket = self._udp_socket
        if udp_socket is None:
            return
        while not self._stop_event.is_set() and self._control_socket is control:
            try:
                packet, address = udp_socket.recvfrom(2048)
            except TimeoutError:
                continue
            except OSError:
                return
            if address != client_udp:
                continue
            try:
                header, data = decode_audio_packet(packet)
                if header["session_id"] != session_id or header["direction"] != DIRECTION_PLAYBACK:
                    continue
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
            except (ProtocolError, ValueError) as exc:
                self.stats.record_corrupt(str(exc))

    def _send_loop(
        self,
        session_id: int,
        control: socket.socket,
        capture_queue: queue.Queue[tuple[int, np.ndarray, int]],
        client_udp: tuple[str, int],
    ) -> None:
        send_sequence = 0
        while not self._stop_event.is_set() and self._control_socket is control:
            try:
                sample_index, block, flags = capture_queue.get(timeout=0.25)
            except queue.Empty:
                continue
            udp_socket = self._udp_socket
            if udp_socket is None:
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
                send_sequence += len(packets)
                for packet in packets:
                    udp_socket.sendto(packet, client_udp)
                    self.stats.record_tx(len(packet))
            except (OSError, ProtocolError) as exc:
                self.stats.set_state("error", str(exc))
                return

    def _end_session(self) -> None:
        callback_id = self._callback_id
        self._callback_id = None
        if callback_id is not None:
            self.audio_engine.unregister_callback(callback_id)
        control = self._control_socket
        self._control_socket = None
        if control is not None:
            try:
                control.close()
            except OSError:
                pass
        current = threading.current_thread()
        for thread in (self._receive_thread, self._send_thread):
            if thread is not None and thread is not current:
                thread.join(timeout=1.0)
        self._receive_thread = None
        self._send_thread = None
        self._client_udp = None
        self.client_address = ""
        self._client_requested_duplex = False
        self._duplex_negotiated = False
        self._duplex = False
        self._playback_buffer = None
        self._playback_started_at = None
        if self.running:
            self.stats.set_state("listening")

    def stop(self) -> None:
        self.running = False
        self._stop_event.set()
        control = self._control_socket
        if control is not None:
            try:
                send_control(control, {"type": "stopped"})
            except (OSError, ProtocolError):
                pass
        for sock in (control, self._tcp_socket, self._udp_socket):
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass
        self._end_session()
        current = threading.current_thread()
        for thread in (self._accept_thread, self._receive_thread, self._send_thread):
            if thread is not None and thread is not current:
                thread.join(timeout=1.0)
        self._tcp_socket = None
        self._udp_socket = None
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
            }
        )
        return snapshot
