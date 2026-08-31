import threading
import time

import numpy as np

from src.core.network_audio.indexed_buffer import IndexedAudioBuffer


def test_reordered_packets_are_read_in_absolute_sample_order():
    buffer = IndexedAudioBuffer(capacity_frames=64, channels=1)
    assert buffer.put(8, np.arange(8, 16, dtype=np.float32)[:, None]) == "accepted"
    assert buffer.put(0, np.arange(0, 8, dtype=np.float32)[:, None]) == "accepted"

    data, missing = buffer.read(0, 16)

    assert missing == []
    assert np.array_equal(data[:, 0], np.arange(16, dtype=np.float32))


def test_missing_samples_are_zero_filled_without_closing_the_gap():
    buffer = IndexedAudioBuffer(capacity_frames=64, channels=1)
    buffer.put(0, np.ones((4, 1), dtype=np.float32))
    buffer.put(8, np.full((4, 1), 2.0, dtype=np.float32))

    data, missing = buffer.read(0, 12)

    assert missing == [(4, 4)]
    assert np.array_equal(data[:, 0], [1, 1, 1, 1, 0, 0, 0, 0, 2, 2, 2, 2])


def test_duplicate_and_late_packets_are_reported():
    buffer = IndexedAudioBuffer(capacity_frames=32, channels=1)
    packet = np.ones((8, 1), dtype=np.float32)
    assert buffer.put(0, packet) == "accepted"
    assert buffer.put(0, packet) == "duplicate"
    buffer.read(0, 8)
    assert buffer.put(0, packet) == "late"


def test_partial_packet_overlap_is_copied_at_the_correct_position():
    buffer = IndexedAudioBuffer(capacity_frames=64, channels=1)
    buffer.put(4, np.arange(4, 12, dtype=np.float32)[:, None])

    data, missing = buffer.read(8, 4)

    assert missing == []
    assert np.array_equal(data[:, 0], [8, 9, 10, 11])


def test_partial_read_preserves_the_unread_packet_tail():
    buffer = IndexedAudioBuffer(capacity_frames=16, channels=1)
    buffer.put(4, np.arange(4, 12, dtype=np.float32)[:, None])

    first, first_missing = buffer.read(4, 4)
    second, second_missing = buffer.read(8, 4)

    assert first_missing == []
    assert second_missing == []
    assert np.array_equal(first[:, 0], [4, 5, 6, 7])
    assert np.array_equal(second[:, 0], [8, 9, 10, 11])


def test_reordered_packets_survive_ring_wrap():
    buffer = IndexedAudioBuffer(capacity_frames=16, channels=1)
    buffer.put(16, np.arange(16, 24, dtype=np.float32)[:, None])
    buffer.put(8, np.arange(8, 16, dtype=np.float32)[:, None])

    data, missing = buffer.read(8, 16)

    assert missing == []
    assert np.array_equal(data[:, 0], np.arange(8, 24, dtype=np.float32))


def test_expired_ring_data_is_not_replayed_after_wrap():
    buffer = IndexedAudioBuffer(capacity_frames=16, channels=1)
    buffer.put(0, np.ones((8, 1), dtype=np.float32))
    buffer.put(24, np.full((8, 1), 2.0, dtype=np.float32))

    data, missing = buffer.read(16, 16)

    assert missing == [(16, 8)]
    assert np.array_equal(data[:, 0], [0] * 8 + [2] * 8)


def test_gap_after_ring_wrap_does_not_expose_stale_samples():
    buffer = IndexedAudioBuffer(capacity_frames=16, channels=1)
    buffer.put(0, np.ones((8, 1), dtype=np.float32))
    buffer.put(16, np.full((4, 1), 2.0, dtype=np.float32))

    data, missing = buffer.read(8, 12)

    assert missing == [(8, 8)]
    assert np.array_equal(data[:, 0], [0] * 8 + [2] * 4)


def test_packet_larger_than_ring_capacity_is_rejected():
    buffer = IndexedAudioBuffer(capacity_frames=4, channels=1)

    try:
        buffer.put(0, np.ones((8, 1), dtype=np.float32))
    except ValueError as exc:
        assert "capacity" in str(exc)
    else:
        raise AssertionError("oversized packet was accepted")


def test_clear_removes_ring_validity_and_resets_sample_origin():
    buffer = IndexedAudioBuffer(capacity_frames=16, channels=1)
    buffer.put(16, np.ones((8, 1), dtype=np.float32))

    buffer.clear()
    assert buffer.first_sample(timeout=0.0) is None
    assert buffer.put(0, np.full((4, 1), 3.0, dtype=np.float32)) == "accepted"
    data, missing = buffer.read(0, 4)

    assert missing == []
    assert np.array_equal(data[:, 0], [3, 3, 3, 3])


def test_stream_start_skips_old_connection_idle_history():
    buffer = IndexedAudioBuffer(capacity_frames=4096, channels=1)
    for start in range(0, 2048, 128):
        buffer.put(start, np.zeros((128, 1), dtype=np.float32))

    start = buffer.stream_start_sample(jitter_frames=256, block_size=128, timeout=0.0)

    assert start == 1664


def test_buffer_wait_can_be_cancelled_without_waiting_for_the_full_timeout():
    buffer = IndexedAudioBuffer(capacity_frames=64, channels=1)
    cancel_event = threading.Event()
    result = []

    waiter = threading.Thread(
        target=lambda: result.append(buffer.wait_until_buffered(64, 30.0, cancel_event)),
    )
    waiter.start()
    time.sleep(0.05)
    cancel_event.set()
    waiter.join(timeout=0.5)

    assert not waiter.is_alive()
    assert result == [False]
