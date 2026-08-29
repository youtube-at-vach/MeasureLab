"""Versioned control and UDP packet protocol for MeasureLab network audio."""

from __future__ import annotations

import json
import socket
import struct
import zlib

import numpy as np


MAGIC = b"MLAU"
PROTOCOL_VERSION = 1
DIRECTION_CAPTURE = 1
DIRECTION_PLAYBACK = 2

FLAG_INPUT_XRUN = 1 << 0
FLAG_OUTPUT_XRUN = 1 << 1

MAX_DATAGRAM = 1200
PACKET_FRAMES = 128
MAX_CONTROL_MESSAGE = 64 * 1024
MAX_CHANNELS = 2

# magic, version, direction, flags, session, sequence, first sample,
# frames, channels, payload crc32
_HEADER = struct.Struct("!4sBBHQQQHHI")


class ProtocolError(ValueError):
    """Raised when an untrusted packet or control message is invalid."""


def control_int(message: dict[str, object], key: str, default: int | None = None) -> int:
    """Read a strict JSON integer without accepting booleans or coercions."""
    value = message.get(key, default)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ProtocolError(f"invalid control field: {key}")
    return value


def control_bool(message: dict[str, object], key: str, default: bool | None = None) -> bool:
    """Read a strict JSON boolean without accepting truthy values."""
    value = message.get(key, default)
    if not isinstance(value, bool):
        raise ProtocolError(f"invalid control field: {key}")
    return value


def encode_audio_packet(
    data: np.ndarray,
    *,
    direction: int,
    flags: int,
    session_id: int,
    sequence: int,
    sample_index: int,
) -> bytes:
    array = np.asarray(data, dtype="<f4")
    if array.ndim != 2:
        raise ProtocolError("audio payload must be two-dimensional")
    frames, channels = array.shape
    if frames <= 0 or frames > PACKET_FRAMES:
        raise ProtocolError("invalid audio frame count")
    if channels <= 0 or channels > MAX_CHANNELS:
        raise ProtocolError("invalid audio channel count")
    if direction not in (DIRECTION_CAPTURE, DIRECTION_PLAYBACK):
        raise ProtocolError("invalid audio direction")
    payload = np.ascontiguousarray(array, dtype="<f4").tobytes()
    crc = zlib.crc32(payload) & 0xFFFFFFFF
    header = _HEADER.pack(
        MAGIC,
        PROTOCOL_VERSION,
        direction,
        int(flags) & 0xFFFF,
        int(session_id) & 0xFFFFFFFFFFFFFFFF,
        int(sequence) & 0xFFFFFFFFFFFFFFFF,
        int(sample_index) & 0xFFFFFFFFFFFFFFFF,
        frames,
        channels,
        crc,
    )
    packet = header + payload
    if len(packet) > MAX_DATAGRAM:
        raise ProtocolError("audio packet exceeds datagram limit")
    return packet


def decode_audio_packet(packet: bytes) -> tuple[dict[str, int], np.ndarray]:
    if len(packet) < _HEADER.size or len(packet) > MAX_DATAGRAM:
        raise ProtocolError("invalid audio packet size")
    magic, version, direction, flags, session_id, sequence, sample_index, frames, channels, crc = _HEADER.unpack_from(
        packet
    )
    if magic != MAGIC or version != PROTOCOL_VERSION:
        raise ProtocolError("unsupported audio protocol")
    if direction not in (DIRECTION_CAPTURE, DIRECTION_PLAYBACK):
        raise ProtocolError("invalid audio direction")
    if frames <= 0 or frames > PACKET_FRAMES or channels <= 0 or channels > MAX_CHANNELS:
        raise ProtocolError("invalid audio format")
    payload = packet[_HEADER.size :]
    expected_size = frames * channels * np.dtype("<f4").itemsize
    if len(payload) != expected_size:
        raise ProtocolError("audio payload length mismatch")
    if (zlib.crc32(payload) & 0xFFFFFFFF) != crc:
        raise ProtocolError("audio payload checksum mismatch")
    data = np.frombuffer(payload, dtype="<f4").reshape(frames, channels).copy()
    return (
        {
            "direction": direction,
            "flags": flags,
            "session_id": session_id,
            "sequence": sequence,
            "sample_index": sample_index,
            "frames": frames,
            "channels": channels,
        },
        data,
    )


def packetize_audio(
    data: np.ndarray,
    *,
    direction: int,
    flags: int,
    session_id: int,
    first_sequence: int,
    sample_index: int,
) -> list[bytes]:
    array = np.asarray(data)
    if array.ndim != 2:
        raise ProtocolError("audio block must be two-dimensional")
    packets = []
    sequence = int(first_sequence)
    for offset in range(0, len(array), PACKET_FRAMES):
        chunk = array[offset : offset + PACKET_FRAMES]
        packets.append(
            encode_audio_packet(
                chunk,
                direction=direction,
                flags=flags,
                session_id=session_id,
                sequence=sequence,
                sample_index=sample_index + offset,
            )
        )
        sequence += 1
    return packets


def send_control(sock: socket.socket, message: dict[str, object]) -> None:
    payload = json.dumps(message, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    if not payload or len(payload) > MAX_CONTROL_MESSAGE:
        raise ProtocolError("invalid control message size")
    sock.sendall(struct.pack("!I", len(payload)) + payload)


def _recv_exact(sock: socket.socket, size: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        chunk = sock.recv(size - len(chunks))
        if not chunk:
            raise ConnectionError("control connection closed")
        chunks.extend(chunk)
    return bytes(chunks)


def recv_control(sock: socket.socket) -> dict[str, object]:
    size = struct.unpack("!I", _recv_exact(sock, 4))[0]
    if size <= 0 or size > MAX_CONTROL_MESSAGE:
        raise ProtocolError("invalid control message size")
    try:
        message = json.loads(_recv_exact(sock, size).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError("invalid control message") from exc
    if not isinstance(message, dict):
        raise ProtocolError("control message must be an object")
    return message
