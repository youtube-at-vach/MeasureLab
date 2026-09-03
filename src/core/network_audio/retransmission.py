"""Bounded packet history and loss tracking for optional UDP retransmission."""

from __future__ import annotations

from collections import OrderedDict, deque
from collections.abc import Sequence
from dataclasses import dataclass
import math
import threading
import time

from src.core.network_audio.protocol import NACK_MAX_SEQUENCES, PACKET_FRAMES

NACK_MAX_PENDING = 128
RETRANSMIT_MAX_ATTEMPTS = 3
NACK_MAX_ATTEMPTS = 8
RETRANSMIT_MIN_INTERVAL = 0.004
RETRANSMIT_MAX_INTERVAL = 0.05
REORDER_DELAY = 0.001
RETRANSMIT_RATE_WINDOW = 0.1
RETRANSMIT_MAX_PER_WINDOW = 64


def effective_retransmit_window_ms(sample_rate: int, block_size: int, requested_ms: int) -> int:
    """Cover the client's effective jitter floor without exceeding protocol bounds."""
    sample_rate = max(1, int(sample_rate))
    block_size = max(1, int(block_size))
    requested_ms = max(20, min(250, int(requested_ms)))
    jitter_frames = max(
        block_size * 2,
        int(round(sample_rate * requested_ms / 1000.0 / block_size)) * block_size,
    )
    effective_ms = math.ceil(jitter_frames * 1000.0 / sample_rate)
    return min(250, max(requested_ms, effective_ms))


def history_packet_capacity(sample_rate: int, block_size: int, retention_seconds: float) -> int:
    """Return enough entries to retain every packet in the negotiated window."""
    sample_rate = max(1, int(sample_rate))
    block_size = max(1, int(block_size))
    retention_seconds = max(0.02, float(retention_seconds))
    packets_per_block = math.ceil(block_size / PACKET_FRAMES)
    retained_blocks = math.ceil(sample_rate * retention_seconds / block_size)
    # Keep one extra callback block so count eviction cannot shorten the time
    # window at a callback boundary.
    return max(1, (retained_blocks + 1) * packets_per_block)


@dataclass(slots=True)
class _HistoryEntry:
    created_at: float
    packet: bytes
    last_retransmitted_at: float = 0.0
    retransmissions: int = 0


class RetransmitHistory:
    """Keep recently transmitted datagrams in a time- and count-bounded cache."""

    def __init__(self, retention_seconds: float, *, max_packets: int = 4096) -> None:
        self.retention_seconds = max(0.02, float(retention_seconds))
        self.max_packets = max(1, int(max_packets))
        self._entries: OrderedDict[int, _HistoryEntry] = OrderedDict()
        self._retransmit_times: deque[float] = deque()
        self._lock = threading.Lock()

    def add(self, sequence: int, packet: bytes, *, now: float | None = None) -> None:
        timestamp = time.monotonic() if now is None else float(now)
        sequence = int(sequence)
        with self._lock:
            self._evict(timestamp)
            self._entries[sequence] = _HistoryEntry(timestamp, bytes(packet))
            self._entries.move_to_end(sequence)
            while len(self._entries) > self.max_packets:
                self._entries.popitem(last=False)

    def add_many(self, first_sequence: int, packets: Sequence[bytes], *, now: float | None = None) -> None:
        """Add one callback block of consecutive packets under a single lock."""
        if not packets:
            return
        timestamp = time.monotonic() if now is None else float(now)
        first_sequence = int(first_sequence)
        with self._lock:
            self._evict(timestamp)
            for offset, packet in enumerate(packets):
                sequence = first_sequence + offset
                self._entries[sequence] = _HistoryEntry(timestamp, bytes(packet))
                self._entries.move_to_end(sequence)
            while len(self._entries) > self.max_packets:
                self._entries.popitem(last=False)

    def take_for_retransmit(
        self,
        sequences: list[int],
        *,
        now: float | None = None,
    ) -> tuple[list[bytes], int]:
        """Return eligible packets and the number absent from the retained history."""
        timestamp = time.monotonic() if now is None else float(now)
        packets: list[bytes] = []
        misses = 0
        with self._lock:
            self._evict(timestamp)
            rate_cutoff = timestamp - RETRANSMIT_RATE_WINDOW
            while self._retransmit_times and self._retransmit_times[0] <= rate_cutoff:
                self._retransmit_times.popleft()
            for sequence in sequences[:NACK_MAX_SEQUENCES]:
                if len(self._retransmit_times) >= RETRANSMIT_MAX_PER_WINDOW:
                    break
                entry = self._entries.get(int(sequence))
                if entry is None:
                    misses += 1
                    continue
                if entry.retransmissions >= RETRANSMIT_MAX_ATTEMPTS:
                    continue
                if entry.last_retransmitted_at and timestamp - entry.last_retransmitted_at < RETRANSMIT_MIN_INTERVAL:
                    continue
                entry.last_retransmitted_at = timestamp
                entry.retransmissions += 1
                self._retransmit_times.append(timestamp)
                packets.append(entry.packet)
        return packets, misses

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._retransmit_times.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def _evict(self, now: float) -> None:
        cutoff = now - self.retention_seconds
        while self._entries:
            _sequence, entry = next(iter(self._entries.items()))
            if entry.created_at >= cutoff:
                break
            self._entries.popitem(last=False)


@dataclass(slots=True)
class _MissingPacket:
    expires_at: float
    expires_before_sample: int | None = None
    next_request_at: float = 0.0
    last_request_at: float = 0.0
    attempts: int = 0


class NackTracker:
    """Track bounded sequence gaps and schedule deadline-aware NACK requests."""

    def __init__(
        self,
        window_seconds: float,
        *,
        expected_sequence: int | None = 0,
        reorder_delay: float = REORDER_DELAY,
    ) -> None:
        self.window_seconds = max(0.02, float(window_seconds))
        self.reorder_delay = max(0.0, float(reorder_delay))
        self._highest_sequence = None if expected_sequence is None else int(expected_sequence) - 1
        self._missing: OrderedDict[int, _MissingPacket] = OrderedDict()
        self._srtt = RETRANSMIT_MIN_INTERVAL
        self._rtt_variance = 0.0
        self._has_rtt_sample = False
        self._lock = threading.Lock()

    def reset(self, expected_sequence: int | None = 0) -> None:
        with self._lock:
            self._highest_sequence = None if expected_sequence is None else int(expected_sequence) - 1
            self._missing.clear()
            self._srtt = RETRANSMIT_MIN_INTERVAL
            self._rtt_variance = 0.0
            self._has_rtt_sample = False

    def observe(
        self,
        sequence: int,
        *,
        sample_index: int | None = None,
        now: float | None = None,
    ) -> bool:
        """Record an arrival and report whether a requested packet was recovered."""
        timestamp = time.monotonic() if now is None else float(now)
        sequence = int(sequence)
        deadline_sample = None if sample_index is None else max(0, int(sample_index))
        with self._lock:
            missing = self._missing.pop(sequence, None)
            recovered = missing is not None and missing.attempts > 0
            # A response after more than one request is ambiguous.  Applying it
            # to the RTT estimator can make the next retry timeout far too
            # small (Karn's rule), so only sample an unambiguous first request.
            if recovered and missing is not None and missing.attempts == 1 and missing.last_request_at:
                self._record_rtt(max(0.0, timestamp - missing.last_request_at))

            if self._highest_sequence is None:
                self._highest_sequence = sequence
                return recovered
            if sequence <= self._highest_sequence:
                return recovered

            gap = sequence - self._highest_sequence - 1
            if gap > NACK_MAX_PENDING:
                self._missing.clear()
            elif gap:
                for missing_sequence in range(self._highest_sequence + 1, sequence):
                    if len(self._missing) >= NACK_MAX_PENDING:
                        break
                    self._missing[missing_sequence] = _MissingPacket(
                        expires_at=timestamp + self.window_seconds,
                        expires_before_sample=deadline_sample,
                        next_request_at=timestamp + self.reorder_delay,
                    )
            self._highest_sequence = sequence
            return recovered

    def poll(
        self,
        *,
        now: float | None = None,
        playout_sample: int | None = None,
    ) -> tuple[list[int], int]:
        """Return due sequence numbers and the count that expired this poll."""
        timestamp = time.monotonic() if now is None else float(now)
        consumed = None if playout_sample is None else max(0, int(playout_sample))
        with self._lock:
            due: list[int] = []
            expired = 0
            for sequence, missing in list(self._missing.items()):
                if self._is_expired(missing, timestamp, consumed):
                    self._missing.pop(sequence, None)
                    expired += 1
                    continue
                if missing.attempts >= NACK_MAX_ATTEMPTS or timestamp < missing.next_request_at:
                    continue
                missing.last_request_at = timestamp
                missing.attempts += 1
                missing.next_request_at = timestamp + self._retry_interval(missing, timestamp)
                due.append(sequence)
                if len(due) >= NACK_MAX_SEQUENCES:
                    break
            return due, expired

    def next_poll_delay(
        self,
        maximum: float,
        *,
        now: float | None = None,
        playout_sample: int | None = None,
    ) -> float:
        """Return when the next retry or expiry needs service, bounded by ``maximum``."""
        timestamp = time.monotonic() if now is None else float(now)
        consumed = None if playout_sample is None else max(0, int(playout_sample))
        delay = max(0.0, float(maximum))
        with self._lock:
            for missing in self._missing.values():
                if self._is_expired(missing, timestamp, consumed):
                    return 0.0
                next_event = missing.expires_at
                if missing.attempts < NACK_MAX_ATTEMPTS:
                    next_event = min(next_event, missing.next_request_at)
                delay = min(delay, max(0.0, next_event - timestamp))
        return delay

    def pending_count(self) -> int:
        with self._lock:
            return len(self._missing)

    @staticmethod
    def _is_expired(missing: _MissingPacket, now: float, playout_sample: int | None) -> bool:
        return now >= missing.expires_at or (
            playout_sample is not None
            and missing.expires_before_sample is not None
            and playout_sample >= missing.expires_before_sample
        )

    def _record_rtt(self, sample: float) -> None:
        sample = max(0.000_001, float(sample))
        if not self._has_rtt_sample:
            self._srtt = sample
            self._rtt_variance = sample / 2.0
            self._has_rtt_sample = True
            return
        self._rtt_variance = 0.75 * self._rtt_variance + 0.25 * abs(self._srtt - sample)
        self._srtt = 0.875 * self._srtt + 0.125 * sample

    def _base_retry_interval(self) -> float:
        return min(
            RETRANSMIT_MAX_INTERVAL,
            max(RETRANSMIT_MIN_INTERVAL, self._srtt + 4.0 * self._rtt_variance),
        )

    def _retry_interval(self, missing: _MissingPacket, now: float) -> float:
        """Back off while still fitting every remaining request before the deadline."""
        backoff = min(
            RETRANSMIT_MAX_INTERVAL,
            self._base_retry_interval() * (2 ** max(0, missing.attempts - 1)),
        )
        requests_left = NACK_MAX_ATTEMPTS - missing.attempts
        if requests_left <= 0:
            return max(0.0, missing.expires_at - now)
        # Reserve one minimum RTT after the final request for its audio packet
        # to arrive.  Short windows compress the retry spacing rather than
        # silently reducing the number of useful attempts.
        scheduling_budget = max(
            0.0,
            missing.expires_at - now - RETRANSMIT_MIN_INTERVAL,
        )
        deadline_spacing = scheduling_budget / requests_left
        return min(backoff, max(RETRANSMIT_MIN_INTERVAL, deadline_spacing))
