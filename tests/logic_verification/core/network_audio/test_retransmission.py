from src.core.network_audio.retransmission import NackTracker, RetransmitHistory


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
    assert tracker.poll(now=4.009) == ([], 0)
    assert tracker.poll(now=4.02) == ([0, 1], 0)
    assert tracker.poll(now=4.04) == ([0, 1], 0)
    assert tracker.poll(now=4.06) == ([], 2)


def test_retransmit_history_is_time_bounded_and_limits_repeat_sends():
    history = RetransmitHistory(0.1)
    history.add(7, b"packet", now=3.0)

    assert history.take_for_retransmit([7, 8], now=3.01) == ([b"packet"], 1)
    assert history.take_for_retransmit([7], now=3.015) == ([], 0)
    assert history.take_for_retransmit([7], now=3.03) == ([b"packet"], 0)
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
