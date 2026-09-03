import pytest

from src.core.network_audio.retransmission import (
    NackTracker,
    RetransmitHistory,
    effective_retransmit_window_ms,
    history_packet_capacity,
)


def test_retransmit_window_covers_the_effective_two_block_jitter_floor():
    assert effective_retransmit_window_ms(8000, 128, 20) == 32
    assert effective_retransmit_window_ms(48000, 128, 100) == 102
    assert effective_retransmit_window_ms(1000, 256, 20) == 250


def test_nack_tracker_waits_for_reordering_and_recovers_requested_gap():
    tracker = NackTracker(0.1, expected_sequence=0, reorder_delay=0.005)

    assert not tracker.observe(0, now=1.0)
    assert not tracker.observe(2, now=1.001)
    assert tracker.poll(now=1.004) == ([], 0)
    assert tracker.poll(now=1.006) == ([1], 0)
    assert tracker.observe(1, now=1.01)
    assert tracker.pending_count() == 0


def test_nack_tracker_bounds_large_gaps_and_expires_requests():
    tracker = NackTracker(0.02, expected_sequence=0, reorder_delay=0.0)

    tracker.observe(500, now=2.0)
    assert tracker.pending_count() == 0

    tracker.observe(502, now=2.001)
    assert tracker.poll(now=2.002) == ([501], 0)
    assert tracker.poll(now=2.03) == ([], 1)


def test_nack_tracker_retries_a_lost_request_before_expiring():
    tracker = NackTracker(0.1, expected_sequence=0, reorder_delay=0.0)
    tracker.observe(2, now=4.0)

    assert tracker.poll(now=4.001) == ([0, 1], 0)
    assert tracker.poll(now=4.003) == ([], 0)
    assert tracker.poll(now=4.005) == ([0, 1], 0)
    assert tracker.poll(now=4.013) == ([0, 1], 0)
    # Retry requests back off, but entries remain recoverable for the complete
    # negotiated deadline instead of expiring as soon as early attempts end.
    assert tracker.pending_count() == 2
    assert tracker.observe(0, now=4.09)
    assert tracker.poll(now=4.1) == ([], 1)


def test_nack_tracker_stops_at_the_actual_playout_sample_deadline():
    tracker = NackTracker(0.25, expected_sequence=0, reorder_delay=0.0)
    tracker.observe(2, sample_index=256, now=5.0)

    assert tracker.poll(now=5.001, playout_sample=255) == ([0, 1], 0)
    assert tracker.poll(now=5.002, playout_sample=256) == ([], 2)
    assert tracker.pending_count() == 0


def test_nack_tracker_exposes_the_next_retry_deadline_without_fixed_polling():
    tracker = NackTracker(0.1, expected_sequence=0, reorder_delay=0.001)
    tracker.observe(1, now=6.0)

    assert tracker.next_poll_delay(0.2, now=6.0) == pytest.approx(0.001)
    assert tracker.poll(now=6.001) == ([0], 0)
    assert tracker.next_poll_delay(0.2, now=6.001) == pytest.approx(0.004)


def test_minimum_window_keeps_five_request_opportunities_before_deadline():
    tracker = NackTracker(0.02, expected_sequence=0, reorder_delay=0.001)
    tracker.observe(1, now=10.0)
    now = 10.0
    requests = 0

    while tracker.pending_count():
        now += tracker.next_poll_delay(1.0, now=now)
        due, _expired = tracker.poll(now=now)
        requests += len(due)

    assert requests == 5
    assert now == pytest.approx(10.02)


def test_retransmit_history_is_time_bounded_and_limits_repeat_sends():
    history = RetransmitHistory(0.1)
    history.add(7, b"packet", now=3.0)

    assert history.take_for_retransmit([7, 8], now=3.01) == ([b"packet"], 1)
    assert history.take_for_retransmit([7], now=3.012) == ([], 0)
    assert history.take_for_retransmit([7], now=3.015) == ([b"packet"], 0)
    assert history.take_for_retransmit([7], now=3.2) == ([], 1)


def test_retransmit_history_rate_limits_many_valid_requests():
    history = RetransmitHistory(0.5)
    for sequence in range(70):
        history.add(sequence, str(sequence).encode(), now=5.0)

    first, _misses = history.take_for_retransmit(list(range(32)), now=5.01)
    second, _misses = history.take_for_retransmit(list(range(32, 64)), now=5.01)
    limited, _misses = history.take_for_retransmit(list(range(64, 70)), now=5.01)
    resumed, _misses = history.take_for_retransmit(list(range(64, 70)), now=5.12)

    assert len(first) == 32
    assert len(second) == 32
    assert not limited
    assert len(resumed) == 6


def test_retransmit_history_capacity_preserves_negotiated_window_at_high_packet_rate():
    sample_rate = 384000
    block_size = 16
    retention_seconds = 0.25
    packet_rate = sample_rate / block_size
    capacity = history_packet_capacity(sample_rate, block_size, retention_seconds)
    history = RetransmitHistory(retention_seconds, max_packets=capacity)

    for sequence in range(4097):
        history.add(sequence, str(sequence).encode(), now=sequence / packet_rate)

    packets, misses = history.take_for_retransmit([0], now=4096 / packet_rate)

    assert capacity >= 6001
    assert packets == [b"0"]
    assert misses == 0


def test_retransmit_history_adds_consecutive_callback_batch():
    history = RetransmitHistory(0.1)

    history.add_many(10, [b"ten", b"eleven", b"twelve"], now=6.0)

    packets, misses = history.take_for_retransmit([10, 11, 12, 13], now=6.01)
    assert packets == [b"ten", b"eleven", b"twelve"]
    assert misses == 1
