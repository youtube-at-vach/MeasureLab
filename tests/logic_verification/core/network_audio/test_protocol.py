import numpy as np
import pytest

from src.core.network_audio.protocol import (
    DIRECTION_CAPTURE,
    MAX_DATAGRAM,
    PACKET_CONNECT_REQUEST,
    PACKET_FRAMES,
    ProtocolError,
    bounded_control_text,
    control_bool,
    control_int,
    datagram_kind,
    decode_audio_packet,
    decode_control_datagram,
    encode_control_datagram,
    encode_audio_packet,
    packetize_audio,
)


def test_audio_packet_round_trip_is_float32_bit_exact():
    data = np.linspace(-1.0, 1.0, 64 * 2, dtype=np.float32).reshape(64, 2)
    packet = encode_audio_packet(
        data,
        direction=DIRECTION_CAPTURE,
        flags=3,
        session_id=123,
        sequence=9,
        sample_index=4096,
    )

    header, decoded = decode_audio_packet(packet)

    assert header == {
        "direction": DIRECTION_CAPTURE,
        "flags": 3,
        "session_id": 123,
        "sequence": 9,
        "sample_index": 4096,
        "frames": 64,
        "channels": 2,
    }
    assert decoded.dtype == np.float32
    assert np.array_equal(decoded.view(np.uint32), data.view(np.uint32))
    assert not decoded.flags.owndata
    assert not decoded.flags.writeable


def test_packetizer_preserves_absolute_sample_positions():
    data = np.arange((PACKET_FRAMES * 2 + 17) * 2, dtype=np.float32).reshape(-1, 2)
    packets = packetize_audio(
        data,
        direction=DIRECTION_CAPTURE,
        flags=0,
        session_id=10,
        first_sequence=20,
        sample_index=1000,
    )

    decoded = [decode_audio_packet(packet) for packet in packets]
    assert [header["sequence"] for header, _ in decoded] == [20, 21, 22]
    assert [header["sample_index"] for header, _ in decoded] == [1000, 1128, 1256]
    assert np.array_equal(np.vstack([chunk for _, chunk in decoded]), data)


def test_packetizer_reports_callback_status_once_per_fragmented_block():
    data = np.zeros((PACKET_FRAMES * 2 + 1, 1), dtype=np.float32)
    packets = packetize_audio(
        data,
        direction=DIRECTION_CAPTURE,
        flags=3,
        session_id=10,
        first_sequence=20,
        sample_index=1000,
    )

    assert [decode_audio_packet(packet)[0]["flags"] for packet in packets] == [3, 0, 0]


def test_corrupt_payload_is_rejected():
    packet = bytearray(
        encode_audio_packet(
            np.ones((16, 1), dtype=np.float32),
            direction=DIRECTION_CAPTURE,
            flags=0,
            session_id=1,
            sequence=1,
            sample_index=0,
        )
    )
    packet[-1] ^= 0xFF

    with pytest.raises(ProtocolError, match="checksum"):
        decode_audio_packet(bytes(packet))


def test_control_scalars_do_not_accept_python_bool_integer_coercions():
    assert control_int({"value": 3}, "value") == 3
    assert control_bool({"value": False}, "value") is False

    with pytest.raises(ProtocolError, match="value"):
        control_int({"value": True}, "value")
    with pytest.raises(ProtocolError, match="value"):
        control_bool({"value": 1}, "value")


def test_udp_control_datagram_round_trip_preserves_envelope_and_json():
    packet = encode_control_datagram(
        PACKET_CONNECT_REQUEST,
        {"protocol": 2, "duplex": True},
        session_id=12,
        message_id=34,
    )

    header, message = decode_control_datagram(packet)

    assert datagram_kind(packet) == PACKET_CONNECT_REQUEST
    assert header == {"kind": PACKET_CONNECT_REQUEST, "session_id": 12, "message_id": 34}
    assert message == {"protocol": 2, "duplex": True}


def test_udp_control_datagram_preserves_bounded_unicode_text():
    value = bounded_control_text("測定🎧" * 200, limit=280)

    packet = encode_control_datagram(PACKET_CONNECT_REQUEST, {"name": value}, message_id=1)
    _header, message = decode_control_datagram(packet)

    assert message == {"name": value}
    assert len(value.encode("utf-8")) <= 280


def test_udp_control_datagram_rejects_corruption_and_fragment_sized_payloads():
    packet = bytearray(encode_control_datagram(PACKET_CONNECT_REQUEST, {"nonce": "valid"}, message_id=1))
    packet[-1] ^= 0xFF
    with pytest.raises(ProtocolError, match="checksum"):
        decode_control_datagram(bytes(packet))

    with pytest.raises(ProtocolError, match="datagram limit"):
        encode_control_datagram(PACKET_CONNECT_REQUEST, {"value": "x" * MAX_DATAGRAM}, message_id=1)


@pytest.mark.parametrize(
    "data",
    [
        np.empty((0, 2), dtype=np.float32),
        np.empty((PACKET_FRAMES + 1, 2), dtype=np.float32),
        np.empty((8, 3), dtype=np.float32),
        np.empty((8,), dtype=np.float32),
    ],
)
def test_invalid_audio_shapes_are_rejected(data):
    with pytest.raises(ProtocolError):
        encode_audio_packet(
            data,
            direction=DIRECTION_CAPTURE,
            flags=0,
            session_id=1,
            sequence=1,
            sample_index=0,
        )
