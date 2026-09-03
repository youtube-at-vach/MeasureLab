"""Versioned UDP control and audio protocol for MeasureLab network audio."""

from __future__ import annotations

import json
import struct
import zlib

import numpy as np


MAGIC = b"MLAU"
PROTOCOL_VERSION = 2
DIRECTION_CAPTURE = 1
DIRECTION_PLAYBACK = 2

PACKET_DISCOVER_QUERY = 16
PACKET_DISCOVER_REPLY = 17
PACKET_CONNECT_REQUEST = 18
PACKET_CONNECT_OFFER = 19
PACKET_START = 20
PACKET_START_ACK = 21
PACKET_KEEPALIVE = 22
PACKET_KEEPALIVE_ACK = 23
PACKET_PLAYBACK_STATE = 24
PACKET_CONTROL_ACK = 25
PACKET_STOP = 26
PACKET_STOPPED = 27
PACKET_ERROR = 28
PACKET_AUDIO_NACK = 29
NACK_MAX_SEQUENCES = 32

CONTROL_PACKET_TYPES = frozenset(
    {
        PACKET_DISCOVER_QUERY,
        PACKET_DISCOVER_REPLY,
        PACKET_CONNECT_REQUEST,
        PACKET_CONNECT_OFFER,
        PACKET_START,
        PACKET_START_ACK,
        PACKET_KEEPALIVE,
        PACKET_KEEPALIVE_ACK,
        PACKET_PLAYBACK_STATE,
        PACKET_CONTROL_ACK,
        PACKET_STOP,
        PACKET_STOPPED,
        PACKET_ERROR,
        PACKET_AUDIO_NACK,
    }
)

FLAG_INPUT_XRUN = 1 << 0
FLAG_OUTPUT_XRUN = 1 << 1

MAX_DATAGRAM = 1200
PACKET_FRAMES = 128
MAX_CHANNELS = 2
CONTROL_HEARTBEAT_INTERVAL = 1.0
CONTROL_HEARTBEAT_TIMEOUT = 5.0

# magic, version, direction, flags, session, sequence, first sample,
# frames, channels, payload crc32
_HEADER = struct.Struct("!4sBBHQQQHHI")
# magic, version, packet type, JSON bytes, session, message ID, payload crc32
_CONTROL_HEADER = struct.Struct("!4sBBHQQI")


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


def control_str(message: dict[str, object], key: str, default: str | None = None, *, limit: int = 500) -> str:
    """Read a bounded control string without coercing untrusted values."""
    value = message.get(key, default)
    if not isinstance(value, str) or len(value) > limit:
        raise ProtocolError(f"invalid control field: {key}")
    return value


def decode_audio_nack(message: dict[str, object]) -> tuple[int, list[int]]:
    """Validate one bounded audio retransmission request."""
    direction = control_int(message, "direction")
    if direction not in (DIRECTION_CAPTURE, DIRECTION_PLAYBACK):
        raise ProtocolError("invalid NACK direction")
    values = message.get("sequences")
    if not isinstance(values, list) or not values or len(values) > NACK_MAX_SEQUENCES:
        raise ProtocolError("invalid NACK sequence list")
    sequences: list[int] = []
    seen: set[int] = set()
    for value in values:
        if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 0xFFFFFFFFFFFFFFFF:
            raise ProtocolError("invalid NACK sequence")
        if value not in seen:
            sequences.append(value)
            seen.add(value)
    return direction, sequences


def bounded_control_text(value: object, *, limit: int = 500) -> str:
    """Return text bounded by UTF-8 bytes so one control datagram stays atomic."""
    encoded = str(value).encode("utf-8")[: max(0, int(limit))]
    return encoded.decode("utf-8", errors="ignore")


def datagram_kind(packet: bytes) -> int:
    """Return the v2 packet type after validating the common prefix."""
    if len(packet) < 6:
        raise ProtocolError("invalid datagram size")
    magic, version, kind = struct.unpack_from("!4sBB", packet)
    if magic != MAGIC or version != PROTOCOL_VERSION:
        raise ProtocolError("unsupported network audio protocol")
    return kind


def encode_control_datagram(
    kind: int,
    message: dict[str, object],
    *,
    session_id: int = 0,
    message_id: int = 0,
) -> bytes:
    """Encode one bounded JSON control message into an atomic UDP datagram."""
    if kind not in CONTROL_PACKET_TYPES:
        raise ProtocolError("invalid control packet type")
    if not isinstance(message, dict):
        raise ProtocolError("control message must be an object")
    payload = json.dumps(message, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if len(payload) > MAX_DATAGRAM - _CONTROL_HEADER.size:
        raise ProtocolError("control message exceeds datagram limit")
    crc = zlib.crc32(payload) & 0xFFFFFFFF
    return (
        _CONTROL_HEADER.pack(
            MAGIC,
            PROTOCOL_VERSION,
            kind,
            len(payload),
            int(session_id) & 0xFFFFFFFFFFFFFFFF,
            int(message_id) & 0xFFFFFFFFFFFFFFFF,
            crc,
        )
        + payload
    )


def decode_control_datagram(packet: bytes) -> tuple[dict[str, int], dict[str, object]]:
    """Decode and validate one UDP control message."""
    if len(packet) < _CONTROL_HEADER.size or len(packet) > MAX_DATAGRAM:
        raise ProtocolError("invalid control datagram size")
    magic, version, kind, payload_size, session_id, message_id, crc = _CONTROL_HEADER.unpack_from(packet)
    if magic != MAGIC or version != PROTOCOL_VERSION:
        raise ProtocolError("unsupported network audio protocol")
    if kind not in CONTROL_PACKET_TYPES:
        raise ProtocolError("invalid control packet type")
    payload = packet[_CONTROL_HEADER.size :]
    if len(payload) != payload_size:
        raise ProtocolError("control payload length mismatch")
    if (zlib.crc32(payload) & 0xFFFFFFFF) != crc:
        raise ProtocolError("control payload checksum mismatch")
    try:
        message = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError("invalid control message") from exc
    if not isinstance(message, dict):
        raise ProtocolError("control message must be an object")
    return {"kind": kind, "session_id": session_id, "message_id": message_id}, message


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
    payload = memoryview(packet)[_HEADER.size :]
    expected_size = frames * channels * np.dtype("<f4").itemsize
    if len(payload) != expected_size:
        raise ProtocolError("audio payload length mismatch")
    if (zlib.crc32(payload) & 0xFFFFFFFF) != crc:
        raise ProtocolError("audio payload checksum mismatch")
    # recvfrom() returns immutable bytes. Keep a read-only view until the
    # indexed receive buffer performs the one required copy into its ring.
    data = np.frombuffer(packet, dtype="<f4", count=frames * channels, offset=_HEADER.size).reshape(frames, channels)
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
                # Status flags describe the source callback block, not every
                # UDP fragment. The first fragment is sufficient because loss
                # of that fragment is itself reported as missing audio.
                flags=flags if offset == 0 else 0,
                session_id=session_id,
                sequence=sequence,
                sample_index=sample_index + offset,
            )
        )
        sequence += 1
    return packets
