"""Bounded packet buffer indexed by remote hardware sample position."""

from __future__ import annotations

from collections.abc import Iterator
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
        # Audio and validity live in fixed-size rings. The previous
        # dictionary representation copied every packet into a separate
        # ndarray and scanned every buffered packet on each callback read.
        # Ring positions are unambiguous inside the retained absolute-sample
        # window, so no per-sample absolute index array is required.
        self._data = np.empty((self.capacity_frames, self.channels), dtype=np.float32)
        self._valid = np.zeros(self.capacity_frames, dtype=bool)
        self._highest_end = 0
        self._consumed_until = 0
        self._condition = threading.Condition()

    def clear(self) -> None:
        with self._condition:
            self._valid.fill(False)
            self._highest_end = 0
            self._consumed_until = 0
            self._condition.notify_all()

    def put(self, sample_index: int, data: np.ndarray) -> str:
        sample_index = int(sample_index)
        array = np.asarray(data, dtype=np.float32)
        if array.ndim != 2 or array.shape[1] != self.channels or len(array) <= 0:
            raise ValueError("packet shape does not match indexed buffer")
        if len(array) > self.capacity_frames:
            raise ValueError("packet exceeds indexed buffer capacity")
        sample_end = sample_index + len(array)
        with self._condition:
            retained_start = max(self._consumed_until, self._highest_end - self.capacity_frames)
            if sample_index < retained_start:
                return "late"

            extends_buffer = sample_end > self._highest_end
            if extends_buffer:
                # The packet overwrites its own ring range. Only an absolute
                # gap before it needs invalidation to prevent samples from an
                # earlier wrap being mistaken for new audio.
                if sample_index > self._highest_end:
                    self._invalidate_range(self._highest_end, sample_index)
                self._highest_end = sample_end
            elif self._range_is_valid(sample_index, len(array)):
                return "duplicate"
            self._write_range(sample_index, array)
            self._condition.notify_all()
            return "accepted"

    def first_sample(self, timeout: float, cancel_event: threading.Event | None = None) -> int | None:
        deadline = time.monotonic() + max(0.0, float(timeout))
        with self._condition:
            while not np.any(self._valid):
                if cancel_event is not None and cancel_event.is_set():
                    return None
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._condition.wait(min(remaining, 0.05) if cancel_event is not None else remaining)
            if cancel_event is not None and cancel_event.is_set():
                return None
            return self._first_valid_sample()

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
        end = sample_index + frames
        with self._condition:
            retained_start = max(self._consumed_until, self._highest_end - self.capacity_frames)
            overlap_start = max(sample_index, retained_start)
            overlap_end = min(end, self._highest_end)
            fully_buffered = (
                frames <= self.capacity_frames
                and overlap_start == sample_index
                and overlap_end == end
                and self._range_is_valid(sample_index, frames)
            )
            if fully_buffered:
                # The steady-state path has no packet loss. Copy directly from
                # the ring without allocating and populating a second boolean
                # array solely to prove that every sample was present.
                result = self._copy_valid_range(sample_index, frames)
                valid = None
            else:
                result = np.zeros((frames, self.channels), dtype=np.float32)
                valid = np.zeros(frames, dtype=bool)
                if overlap_start < overlap_end:
                    self._copy_range(
                        overlap_start,
                        overlap_end - overlap_start,
                        result,
                        valid,
                        overlap_start - sample_index,
                    )

            previous_consumed = self._consumed_until
            self._consumed_until = max(self._consumed_until, end)
            invalidate_start = max(previous_consumed, self._highest_end - self.capacity_frames)
            invalidate_end = min(self._consumed_until, self._highest_end)
            if invalidate_start < invalidate_end:
                self._invalidate_range(invalidate_start, invalidate_end)

        if valid is None:
            return result, []
        missing_mask = ~valid
        if not np.any(missing_mask):
            return result, []
        transitions = np.flatnonzero(np.diff(np.pad(missing_mask, 1)))
        missing = [(sample_index + int(start), int(stop - start)) for start, stop in transitions.reshape(-1, 2)]
        return result, missing

    def buffered_frames(self) -> int:
        with self._condition:
            return max(0, self._highest_end - self._consumed_until)

    def consumed_until(self) -> int:
        """Return the first sample that can still meet its playout deadline."""
        with self._condition:
            return self._consumed_until

    def _ring_segments(self, sample_index: int, frames: int) -> Iterator[tuple[slice, int, int]]:
        ring_start = sample_index % self.capacity_frames
        first_frames = min(frames, self.capacity_frames - ring_start)
        yield slice(ring_start, ring_start + first_frames), 0, first_frames
        if first_frames < frames:
            yield slice(0, frames - first_frames), first_frames, frames

    def _invalidate_range(self, sample_start: int, sample_end: int) -> None:
        frames = max(0, sample_end - sample_start)
        if frames >= self.capacity_frames:
            self._valid.fill(False)
            return
        ring_start = sample_start % self.capacity_frames
        first_frames = min(frames, self.capacity_frames - ring_start)
        self._valid[ring_start : ring_start + first_frames] = False
        if first_frames < frames:
            self._valid[: frames - first_frames] = False

    def _range_is_valid(self, sample_index: int, frames: int) -> bool:
        ring_start = sample_index % self.capacity_frames
        first_frames = min(frames, self.capacity_frames - ring_start)
        if not np.all(self._valid[ring_start : ring_start + first_frames]):
            return False
        return first_frames == frames or bool(np.all(self._valid[: frames - first_frames]))

    def _write_range(self, sample_index: int, data: np.ndarray) -> None:
        frames = len(data)
        ring_start = sample_index % self.capacity_frames
        first_frames = min(frames, self.capacity_frames - ring_start)
        self._data[ring_start : ring_start + first_frames] = data[:first_frames]
        self._valid[ring_start : ring_start + first_frames] = True
        if first_frames < frames:
            remaining = frames - first_frames
            self._data[:remaining] = data[first_frames:]
            self._valid[:remaining] = True

    def _copy_range(
        self,
        sample_index: int,
        frames: int,
        result: np.ndarray,
        valid: np.ndarray,
        result_start: int,
    ) -> None:
        ring_start = sample_index % self.capacity_frames
        first_frames = min(frames, self.capacity_frames - ring_start)
        destination = slice(result_start, result_start + first_frames)
        ring_slice = slice(ring_start, ring_start + first_frames)
        ring_valid = self._valid[ring_slice]
        result[destination] = self._data[ring_slice]
        result[destination][~ring_valid] = 0
        valid[destination] = ring_valid
        if first_frames < frames:
            remaining = frames - first_frames
            destination = slice(result_start + first_frames, result_start + frames)
            ring_valid = self._valid[:remaining]
            result[destination] = self._data[:remaining]
            result[destination][~ring_valid] = 0
            valid[destination] = ring_valid

    def _copy_valid_range(self, sample_index: int, frames: int) -> np.ndarray:
        """Copy one range known to be fully valid from the ring."""
        ring_start = sample_index % self.capacity_frames
        first_frames = min(frames, self.capacity_frames - ring_start)
        if first_frames == frames:
            return self._data[ring_start : ring_start + frames].copy()
        result = np.empty((frames, self.channels), dtype=np.float32)
        result[:first_frames] = self._data[ring_start : ring_start + first_frames]
        result[first_frames:] = self._data[: frames - first_frames]
        return result

    def _first_valid_sample(self) -> int:
        retained_start = max(self._consumed_until, self._highest_end - self.capacity_frames)
        retained_frames = self._highest_end - retained_start
        for ring_slice, source_start, _source_end in self._ring_segments(retained_start, retained_frames):
            valid_positions = np.flatnonzero(self._valid[ring_slice])
            if len(valid_positions):
                return retained_start + source_start + int(valid_positions[0])
        raise RuntimeError("indexed buffer validity state is inconsistent")
