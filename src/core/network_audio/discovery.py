"""Active IPv4 LAN discovery for MeasureLab UDP audio providers."""

from __future__ import annotations

from dataclasses import dataclass
import secrets
import socket
import threading
import time
from typing import Iterable

from src.core.network_audio.protocol import (
    PACKET_DISCOVER_QUERY,
    PACKET_DISCOVER_REPLY,
    PROTOCOL_VERSION,
    ProtocolError,
    control_bool,
    control_int,
    control_str,
    datagram_kind,
    decode_control_datagram,
    encode_control_datagram,
)


DISCOVERY_INTERVAL = 2.0
DISCOVERY_TTL = 6.0


@dataclass(frozen=True, slots=True)
class DiscoveredProvider:
    """One provider observed through an active discovery response."""

    instance_id: str
    host: str
    port: int
    provider_name: str
    input_device_name: str
    output_device_name: str
    sample_rate: int
    block_size: int
    input_channels: int
    output_channels: int
    duplex: bool
    busy: bool
    last_seen: float


class NetworkAudioDiscovery:
    """Send discovery queries and collect unicast provider responses."""

    def __init__(
        self,
        port: int = 40100,
        *,
        broadcast_addresses: Iterable[str] = ("255.255.255.255",),
        interval: float = DISCOVERY_INTERVAL,
        ttl: float = DISCOVERY_TTL,
    ) -> None:
        self.port = int(port)
        self.broadcast_addresses = tuple(dict.fromkeys(str(value) for value in broadcast_addresses if value)) or (
            "255.255.255.255",
        )
        self.interval = max(0.2, float(interval))
        self.ttl = max(self.interval * 2.0, float(ttl))
        self._nonce = secrets.token_hex(16)
        self._socket: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._providers: dict[str, DiscoveredProvider] = {}
        self.last_error = ""

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        if not 1 <= self.port <= 65535:
            raise ValueError("invalid discovery port")
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("0.0.0.0", 0))
            sock.settimeout(0.2)
        except Exception:
            sock.close()
            raise
        self._socket = sock
        self._stop_event.clear()
        self.last_error = ""
        self._thread = threading.Thread(target=self._run, name="NetworkAudioDiscovery", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        next_query = 0.0
        while not self._stop_event.is_set():
            now = time.monotonic()
            if now >= next_query:
                self._send_query()
                next_query = now + self.interval
                self._expire(now)
            sock = self._socket
            if sock is None:
                return
            try:
                packet, address = sock.recvfrom(2048)
            except TimeoutError:
                continue
            except OSError as exc:
                if not self._stop_event.is_set():
                    self.last_error = str(exc)[:500]
                    continue
                return
            self._accept_response(packet, address)

    def _send_query(self) -> None:
        sock = self._socket
        if sock is None:
            return
        message_id = secrets.randbits(63) or 1
        packet = encode_control_datagram(
            PACKET_DISCOVER_QUERY,
            {"protocol": PROTOCOL_VERSION, "nonce": self._nonce},
            message_id=message_id,
        )
        sent = False
        for host in self.broadcast_addresses:
            try:
                sock.sendto(packet, (host, self.port))
                sent = True
            except OSError as exc:
                self.last_error = str(exc)[:500]
        if sent:
            self.last_error = ""

    def _accept_response(self, packet: bytes, address: tuple[str, int]) -> None:
        try:
            if datagram_kind(packet) != PACKET_DISCOVER_REPLY:
                return
            header, message = decode_control_datagram(packet)
            if header["session_id"] != 0:
                return
            if control_int(message, "protocol", -1) != PROTOCOL_VERSION:
                return
            if control_str(message, "nonce", "", limit=64) != self._nonce:
                return
            instance_id = control_str(message, "instance_id", "", limit=64)
            if not instance_id:
                return
            service_port = control_int(message, "service_port")
            if not 1 <= service_port <= 65535:
                raise ProtocolError("invalid discovery service port")
            provider = DiscoveredProvider(
                instance_id=instance_id,
                host=str(address[0]),
                port=service_port,
                provider_name=control_str(message, "provider_name", "MeasureLab", limit=200),
                input_device_name=control_str(message, "input_device_name", "-", limit=500),
                output_device_name=control_str(message, "output_device_name", "-", limit=500),
                sample_rate=control_int(message, "sample_rate"),
                block_size=control_int(message, "block_size"),
                input_channels=control_int(message, "input_channels"),
                output_channels=control_int(message, "output_channels"),
                duplex=control_bool(message, "duplex", False),
                busy=control_bool(message, "busy", False),
                last_seen=time.monotonic(),
            )
            if not 1000 <= provider.sample_rate <= 768000:
                raise ProtocolError("invalid discovery sample rate")
            if not 16 <= provider.block_size <= 262144:
                raise ProtocolError("invalid discovery block size")
            if provider.input_channels not in (1, 2) or provider.output_channels not in (1, 2):
                raise ProtocolError("invalid discovery channel count")
        except (ProtocolError, TypeError, ValueError):
            return
        with self._lock:
            self._providers[provider.instance_id] = provider

    def _expire(self, now: float) -> None:
        with self._lock:
            expired = [key for key, provider in self._providers.items() if now - provider.last_seen > self.ttl]
            for key in expired:
                self._providers.pop(key, None)

    def snapshot(self) -> tuple[DiscoveredProvider, ...]:
        self._expire(time.monotonic())
        with self._lock:
            providers = tuple(self._providers.values())
        return tuple(sorted(providers, key=lambda item: (item.provider_name.casefold(), item.host, item.port)))

    def stop(self) -> None:
        self._stop_event.set()
        sock = self._socket
        self._socket = None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=1.0)
        self._thread = None
