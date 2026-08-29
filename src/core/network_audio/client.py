"""Client session and AudioEngine-compatible stream for remote audio I/O."""

from __future__ import annotations

import logging
import queue
import socket
import threading
import time
from typing import Callable

import numpy as np

from src.core.network_audio.indexed_buffer import IndexedAudioBuffer
from src.core.network_audio.models import NetworkAudioStats, NetworkStatusFlags, NetworkStreamTime
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


class NetworkAudioClient:
    """Connected control/data session to one MeasureLab provider."""

    def __init__(self, host: str, port: int, *, jitter_ms: int = 100, duplex: bool = True) -> None:
        self.host = str(host).strip()
        self.port = int(port)
        self.jitter_ms = max(20, min(2000, int(jitter_ms)))
        self.duplex = bool(duplex)
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

        self._control_socket: socket.socket | None = None
        self._udp_socket: socket.socket | None = None
        self._provider_udp: tuple[str, int] | None = None
        self._capture_buffer: IndexedAudioBuffer | None = None
        self._stop_event = threading.Event()
        self._receiver_thread: threading.Thread | None = None
        self._control_thread: threading.Thread | None = None
        self._sender_thread: threading.Thread | None = None
        self._playback_queue: queue.Queue[tuple[int, np.ndarray, int]] = queue.Queue(maxsize=64)
        self._send_sequence = 0
        self._pending_remote_input_xrun = False
        self._pending_remote_output_xrun = False
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected and not self._stop_event.is_set()

    def connect(self, timeout: float = 5.0) -> None:
        if self.connected:
            return
        if not self.host or not 1 <= self.port <= 65535:
            raise ValueError("invalid network audio endpoint")
        if self._control_socket is not None or self._udp_socket is not None:
            self.close()

        udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        control_socket: socket.socket | None = None
        try:
            udp_socket.bind(("0.0.0.0", 0))
            udp_socket.settimeout(0.5)
            control_socket = socket.create_connection((self.host, self.port), timeout=max(0.1, float(timeout)))
            control_socket.settimeout(max(0.1, float(timeout)))
            send_control(
                control_socket,
                {
                    "type": "hello",
                    "protocol": PROTOCOL_VERSION,
                    "udp_port": udp_socket.getsockname()[1],
                    "duplex": self.duplex,
                },
            )
            offer = recv_control(control_socket)
            if offer.get("type") != "offer" or control_int(offer, "protocol", -1) != PROTOCOL_VERSION:
                raise ProtocolError(str(offer.get("error", "provider rejected connection")))
            self._apply_offer(offer)
            provider_ip = control_socket.getpeername()[0]
            provider_udp_port = control_int(offer, "udp_port")
            if not 1 <= provider_udp_port <= 65535:
                raise ProtocolError("provider UDP port is invalid")
            self._provider_udp = (provider_ip, provider_udp_port)
            self._capture_buffer = IndexedAudioBuffer(
                capacity_frames=max(self.sample_rate * 4, self.block_size * 16),
                channels=self.input_channels,
            )
            self._control_socket = control_socket
            self._udp_socket = udp_socket
            self._stop_event.clear()
            self._connected = True
            self._playback_queue = queue.Queue(maxsize=64)
            self._send_sequence = 0
            self._pending_remote_input_xrun = False
            self._pending_remote_output_xrun = False
            self.stats.jitter_frames = self.jitter_frames
            self.stats.set_state("connected")
            self._receiver_thread = threading.Thread(target=self._receive_loop, name="NetworkAudioRx", daemon=True)
            self._sender_thread = threading.Thread(target=self._send_loop, name="NetworkAudioTx", daemon=True)
            self._receiver_thread.start()
            self._sender_thread.start()
            send_control(control_socket, {"type": "start", "session_id": self.session_id})
        except Exception:
            if self._control_socket is None:
                if control_socket is not None:
                    control_socket.close()
                udp_socket.close()
            else:
                self.close()
            raise

        assert control_socket is not None
        control_socket.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        control_socket.settimeout(None)
        self._control_thread = threading.Thread(target=self._control_loop, name="NetworkAudioControl", daemon=True)
        self._control_thread.start()

    def _apply_offer(self, offer: dict[str, object]) -> None:
        self.session_id = control_int(offer, "session_id")
        if not 1 <= self.session_id <= 0xFFFFFFFFFFFFFFFF:
            raise ProtocolError("provider session ID is invalid")
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
        self.provider_name = str(offer.get("provider_name", "Remote MeasureLab"))[:200]
        self.input_device_name = str(offer.get("input_device_name", "Remote Input"))[:500]
        self.output_device_name = str(offer.get("output_device_name", "Remote Output"))[:500]
        self.duplex = self.duplex and control_bool(offer, "duplex", False)
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
            try:
                packet, address = udp_socket.recvfrom(2048)
            except TimeoutError:
                continue
            except OSError as exc:
                if not self._stop_event.is_set():
                    self._fail(f"audio receive failed: {exc}")
                return
            if self._provider_udp is None or address != self._provider_udp:
                continue
            try:
                header, data = decode_audio_packet(packet)
                if header["session_id"] != self.session_id or header["direction"] != DIRECTION_CAPTURE:
                    continue
                result = capture_buffer.put(header["sample_index"], data)
                if result == "duplicate":
                    self.stats.record_duplicate()
                elif result == "late":
                    self.stats.record_late()
                else:
                    self.stats.record_rx(len(packet))
                    self.stats.set_buffered_frames(capture_buffer.buffered_frames())
                flags = header["flags"]
                if flags & FLAG_INPUT_XRUN:
                    self.stats.record_remote_xrun(input_xrun=True)
                    self._pending_remote_input_xrun = True
                if flags & FLAG_OUTPUT_XRUN:
                    self.stats.record_remote_xrun(output_xrun=True)
                    self._pending_remote_output_xrun = True
            except (ProtocolError, ValueError) as exc:
                self.stats.record_corrupt(str(exc))

    def _send_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                sample_index, block, flags = self._playback_queue.get(timeout=0.25)
            except queue.Empty:
                continue
            udp_socket = self._udp_socket
            provider = self._provider_udp
            if udp_socket is None or provider is None:
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
                self._send_sequence += len(packets)
                for packet in packets:
                    udp_socket.sendto(packet, provider)
                    self.stats.record_tx(len(packet))
            except (OSError, ProtocolError) as exc:
                if not self._stop_event.is_set():
                    self._fail(f"audio send failed: {exc}")
                return

    def _control_loop(self) -> None:
        control_socket = self._control_socket
        if control_socket is None:
            return
        while not self._stop_event.is_set():
            try:
                message = recv_control(control_socket)
            except TimeoutError:
                continue
            except (ConnectionError, OSError, ProtocolError) as exc:
                if not self._stop_event.is_set():
                    self._fail(f"control connection lost: {exc}")
                return
            if message.get("type") == "error":
                self._fail(str(message.get("message", "remote provider error")))
                return
            if message.get("type") == "stopped":
                self._fail("remote provider stopped the session")
                return

    def enqueue_playback(self, sample_index: int, block: np.ndarray, flags: int = 0) -> None:
        if not self.duplex or not self.connected:
            return
        try:
            self._playback_queue.put_nowait((int(sample_index), np.asarray(block, dtype=np.float32).copy(), int(flags)))
        except queue.Full:
            self.stats.record_queue_overflow("playback", sample_index, len(block))

    def first_capture_sample(self, timeout: float) -> int | None:
        buffer = self._capture_buffer
        if buffer is None:
            return None
        return buffer.stream_start_sample(self.jitter_frames, self.block_size, timeout)

    def read_capture(self, sample_index: int, frames: int) -> tuple[np.ndarray, NetworkStatusFlags]:
        buffer = self._capture_buffer
        if buffer is None:
            raise RuntimeError("network capture buffer is unavailable")
        target = sample_index + frames + self.jitter_frames
        buffer.wait_until_buffered(target, max(0.25, frames / self.sample_rate * 4.0))
        data, missing = buffer.read(sample_index, frames)
        status = NetworkStatusFlags()
        for missing_start, missing_frames in missing:
            status.input_overflow = True
            self.stats.record_loss("capture", missing_start, missing_frames)
        if self._pending_remote_input_xrun:
            status.input_overflow = True
            self._pending_remote_input_xrun = False
        if self._pending_remote_output_xrun:
            status.output_underflow = True
            self._pending_remote_output_xrun = False
        self.stats.set_buffered_frames(buffer.buffered_frames())
        return data, status

    def _fail(self, message: str) -> None:
        self.logger.warning(message)
        self.stats.set_state("error", message)
        self._connected = False
        self._stop_event.set()

    def close(self) -> None:
        if self._control_socket is not None and self._connected:
            try:
                send_control(self._control_socket, {"type": "stop", "session_id": self.session_id})
            except (OSError, ProtocolError):
                pass
        self._connected = False
        self._stop_event.set()
        for sock in (self._control_socket, self._udp_socket):
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass
        current = threading.current_thread()
        for thread in (self._receiver_thread, self._sender_thread, self._control_thread):
            if thread is not None and thread is not current:
                thread.join(timeout=1.0)
        self._control_socket = None
        self._udp_socket = None
        self.stats.set_state("disconnected")

    def status_snapshot(self) -> dict[str, object]:
        snapshot = self.stats.snapshot()
        snapshot.update(
            {
                "provider_name": self.provider_name,
                "input_device_name": self.input_device_name,
                "output_device_name": self.output_device_name,
                "duplex": self.duplex,
                "jitter_ms": self.jitter_ms,
                "playout_delay_frames": self.playout_delay_frames,
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
        input_latency = client.jitter_frames / client.sample_rate
        output_latency = client.playout_delay_frames / client.sample_rate
        self.latency = (input_latency, output_latency)
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._time_origin = time.monotonic()

    def start(self) -> None:
        if self.active:
            return
        if not self.client.connected:
            raise RuntimeError("network audio client is disconnected")
        self.active = True
        self._stop_event.clear()
        self.client.stats.set_state("priming")
        self._thread = threading.Thread(target=self._run, name="NetworkAudioCallback", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        expected = self.client.first_capture_sample(timeout=5.0)
        if expected is None:
            self.client._fail("timed out waiting for remote audio")
            self.active = False
            return
        self.client.stats.set_state("streaming")
        interval = self.blocksize / self.samplerate
        while self.active and not self._stop_event.is_set() and self.client.connected:
            started = time.perf_counter()
            indata, status = self.client.read_capture(expected, self.blocksize)
            outdata = np.zeros((self.blocksize, self.channels[1]), dtype=np.float32)
            current_time = self._time_origin + expected / self.samplerate
            time_info = NetworkStreamTime(
                inputBufferAdcTime=current_time,
                outputBufferDacTime=current_time + self.client.playout_delay_frames / self.samplerate,
                currentTime=current_time,
            )
            try:
                self.callback(indata, outdata, self.blocksize, time_info, status)
            except Exception as exc:
                self.client._fail(f"network audio callback failed: {exc}")
                break
            if self.client.duplex:
                self.client.enqueue_playback(expected + self.client.playout_delay_frames, outdata)
            elapsed = time.perf_counter() - started
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

    def close(self) -> None:
        self.stop()
