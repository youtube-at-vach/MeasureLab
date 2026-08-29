"""Bounded packet buffer indexed by remote hardware sample position."""

from __future__ import annotations

import threading
import time

import numpy as np


class IndexedAudioBuffer:
    """Reorders packets without ever hiding missing sample positions."""

    def __init__(self, capacity_frames: int, channels: int) -> None:
        if capacity_frames <= 0 or channels <= 0:
            raise ValueError("buffer dimensions must be positive")
        self.capacity_frames = int(capacity_frames)
        self.channels = int(channels)
        self._packets: dict[int, np.ndarray] = {}
        self._highest_end = 0
        self._consumed_until = 0
        self._condition = threading.Condition()

    def clear(self) -> None:
        with self._condition:
            self._packets.clear()
            self._highest_end = 0
            self._consumed_until = 0
            self._condition.notify_all()

    def put(self, sample_index: int, data: np.ndarray) -> str:
        sample_index = int(sample_index)
        array = np.asarray(data, dtype=np.float32)
        if array.ndim != 2 or array.shape[1] != self.channels or len(array) <= 0:
            raise ValueError("packet shape does not match indexed buffer")
        with self._condition:
            if sample_index < self._consumed_until:
                return "late"
            if sample_index in self._packets:
                return "duplicate"
            self._packets[sample_index] = array.copy()
            self._highest_end = max(self._highest_end, sample_index + len(array))
            cutoff = max(self._consumed_until, self._highest_end - self.capacity_frames)
            for start in tuple(self._packets):
                if start + len(self._packets[start]) <= cutoff:
                    del self._packets[start]
            self._condition.notify_all()
            return "accepted"

    def first_sample(self, timeout: float, cancel_event: threading.Event | None = None) -> int | None:
        deadline = time.monotonic() + max(0.0, float(timeout))
        with self._condition:
            while not self._packets:
                if cancel_event is not None and cancel_event.is_set():
                    return None
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._condition.wait(min(remaining, 0.05) if cancel_event is not None else remaining)
            if cancel_event is not None and cancel_event.is_set():
                return None
            return min(self._packets)

    def stream_start_sample(
        self,
        jitter_frames: int,
        block_size: int,
        timeout: float,
        cancel_event: threading.Event | None = None,
    ) -> int | None:
        """Choose a block-aligned start near live data after connection idle time."""
        first = self.first_sample(timeout, cancel_event)
        if first is None:
            return None
        with self._condition:
            if cancel_event is not None and cancel_event.is_set():
                return None
            near_live = max(0, self._highest_end - max(0, int(jitter_frames)) - int(block_size))
            aligned = near_live - near_live % int(block_size)
            return max(0, aligned)

    def wait_until_buffered(
        self,
        sample_end: int,
        timeout: float,
        cancel_event: threading.Event | None = None,
    ) -> bool:
        deadline = time.monotonic() + max(0.0, float(timeout))
        with self._condition:
            while self._highest_end < sample_end:
                if cancel_event is not None and cancel_event.is_set():
                    return False
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(min(remaining, 0.05) if cancel_event is not None else remaining)
            return cancel_event is None or not cancel_event.is_set()

    def read(self, sample_index: int, frames: int) -> tuple[np.ndarray, list[tuple[int, int]]]:
        """Return exact-position data plus missing ``(start, frames)`` ranges."""
        sample_index = int(sample_index)
        frames = int(frames)
        if frames <= 0:
            raise ValueError("frames must be positive")
        result = np.zeros((frames, self.channels), dtype=np.float32)
        valid = np.zeros(frames, dtype=bool)
        end = sample_index + frames
        with self._condition:
            for start, packet in tuple(self._packets.items()):
                packet_end = start + len(packet)
                overlap_start = max(start, sample_index)
                overlap_end = min(packet_end, end)
                if overlap_start < overlap_end:
                    dst_start = overlap_start - sample_index
                    src_start = overlap_start - start
                    count = overlap_end - overlap_start
                    result[dst_start : dst_start + count] = packet[src_start : src_start + count]
                    valid[dst_start : dst_start + count] = True
                if packet_end <= end:
                    del self._packets[start]
            self._consumed_until = max(self._consumed_until, end)

        missing: list[tuple[int, int]] = []
        position = 0
        while position < frames:
            if valid[position]:
                position += 1
                continue
            start = position
            while position < frames and not valid[position]:
                position += 1
            missing.append((sample_index + start, position - start))
        return result, missing

    def buffered_frames(self) -> int:
        with self._condition:
            return max(0, self._highest_end - self._consumed_until)
