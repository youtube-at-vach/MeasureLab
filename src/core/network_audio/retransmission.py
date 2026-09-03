"""Bounded packet history and loss tracking for optional UDP retransmission."""

from __future__ import annotations

from collections import OrderedDict, deque
from dataclasses import dataclass
import math
import threading
import time

from src.core.network_audio.protocol import NACK_MAX_SEQUENCES, PACKET_FRAMES

NACK_MAX_PENDING = 128
RETRANSMIT_MAX_ATTEMPTS = 3
RETRANSMIT_MIN_INTERVAL = 0.01
RETRANSMIT_MAX_INTERVAL = 0.05
REORDER_DELAY = 0.005
RETRANSMIT_RATE_WINDOW = 0.1
RETRANSMIT_MAX_PER_WINDOW = 64


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
    detected_at: float
    expires_at: float
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

    def reset(self, expected_sequence: int | None = 0) -> None:
        self._highest_sequence = None if expected_sequence is None else int(expected_sequence) - 1
        self._missing.clear()
        self._srtt = RETRANSMIT_MIN_INTERVAL

    def observe(self, sequence: int, *, now: float | None = None) -> bool:
        """Record an arrival and report whether a requested packet was recovered."""
        timestamp = time.monotonic() if now is None else float(now)
        sequence = int(sequence)
        missing = self._missing.pop(sequence, None)
        recovered = missing is not None and missing.attempts > 0
        if recovered and missing is not None and missing.last_request_at:
            sample = max(0.0, timestamp - missing.last_request_at)
            self._srtt = 0.875 * self._srtt + 0.125 * sample

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
                    detected_at=timestamp,
                    expires_at=timestamp + self.window_seconds,
                )
        self._highest_sequence = sequence
        return recovered

    def poll(self, *, now: float | None = None) -> tuple[list[int], int]:
        """Return due sequence numbers and the count that expired this poll."""
        timestamp = time.monotonic() if now is None else float(now)
        retry_interval = min(
            RETRANSMIT_MAX_INTERVAL,
            max(RETRANSMIT_MIN_INTERVAL, self._srtt * 1.5),
        )
        due: list[int] = []
        expired = 0
        for sequence, missing in list(self._missing.items()):
            if timestamp >= missing.expires_at:
                self._missing.pop(sequence, None)
                expired += 1
                continue
            if missing.attempts >= RETRANSMIT_MAX_ATTEMPTS:
                if timestamp - missing.last_request_at >= retry_interval:
                    self._missing.pop(sequence, None)
                    expired += 1
                continue
            if timestamp - missing.detected_at < self.reorder_delay:
                continue
            if missing.attempts and timestamp - missing.last_request_at < retry_interval:
                continue
            missing.last_request_at = timestamp
            missing.attempts += 1
            due.append(sequence)
            if len(due) >= NACK_MAX_SEQUENCES:
                break
        return due, expired

    def pending_count(self) -> int:
        return len(self._missing)
