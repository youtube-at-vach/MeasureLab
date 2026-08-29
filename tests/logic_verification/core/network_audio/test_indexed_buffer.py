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


def test_stream_start_skips_old_connection_idle_history():
    buffer = IndexedAudioBuffer(capacity_frames=4096, channels=1)
    for start in range(0, 2048, 128):
        buffer.put(start, np.zeros((128, 1), dtype=np.float32))

    start = buffer.stream_start_sample(jitter_frames=256, block_size=128, timeout=0.0)

    assert start == 1664
