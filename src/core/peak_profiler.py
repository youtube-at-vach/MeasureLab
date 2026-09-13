"""Bounded, sample-clock peak statistics and callback-to-worker transport.

The histogram counts input-frame envelopes, not callback maxima. TP uses the
maximum of four FIR phases and the aligned sample peak: duration resolution is
one input frame. This is an interpolated estimate, not a compliance claim.
"""

from dataclasses import dataclass
import threading

import numpy as np


@dataclass(frozen=True)
class PeakEvent:
    channel: int
    kind: int  # 0: sample peak; 1: true peak envelope
    start: int
    end: int  # exclusive, in input frames
    peak: float
    censored: bool = False


@dataclass(frozen=True)
class PeakProfileSnapshot:
    threshold_db: float
    sample_rate: float
    frames: int
    histogram: np.ndarray
    exceedances: np.ndarray
    events_started: np.ndarray
    longest_frames: np.ndarray
    events: tuple[PeakEvent, ...]
    evicted_events: int
    flags: frozenset[str]
    channels: int


class PeakProfiler:
    """Single-owner accumulator. Caller synchronizes processing and snapshots."""

    EDGES = np.arange(-60.0, 7.0)  # 1 dB bins plus explicit under/overflow
    MAX_EVENTS = 512
    EVENT_DTYPE = np.dtype(
        [
            ("channel", "i1"),
            ("kind", "i1"),
            ("start", "i8"),
            ("end", "i8"),
            ("peak", "f8"),
            ("censored", "?"),
        ]
    )

    def __init__(self, sample_rate: float, threshold_db: float = -1.0):
        if not np.isfinite(sample_rate) or sample_rate <= 0:
            raise ValueError("sample rate must be finite and positive")
        if not np.isfinite(threshold_db) or not -60 <= threshold_db <= 6:
            raise ValueError("peak threshold must be between -60 and +6 dBFS")
        self.sample_rate = sample_rate
        self.threshold_db = threshold_db
        self.threshold = 10 ** (threshold_db / 20)
        self.histogram = np.zeros((2, len(self.EDGES) + 1), dtype=np.int64)
        self.exceedances = np.zeros((2, 2), dtype=np.int64)
        self.events_started = np.zeros((2, 2), dtype=np.int64)
        self.longest_frames = np.zeros((2, 2), dtype=np.int64)
        # Reserve four slots for ongoing channel/kind intervals. Retain by
        # source end time, not the order in which channel loops execute.
        self._events = np.empty(0, dtype=self.EVENT_DTYPE)
        self.active: dict[tuple[int, int], PeakEvent] = {}
        self.evicted_events = 0
        self.flags: set[str] = set()
        self.frames = 0
        self.channels = 0
        self._pending = np.empty((0, 2))
        self._warmup = 10
        self._next = 0

    def _retain(self, event: PeakEvent) -> None:
        self._retain_batch(
            np.array(
                [(event.channel, event.kind, event.start, event.end, event.peak, event.censored)],
                dtype=self.EVENT_DTYPE,
            )
        )

    def _retain_batch(self, events: np.ndarray) -> None:
        merged = np.concatenate((self._events, events))
        limit = self.MAX_EVENTS - 4
        self.evicted_events += max(0, len(merged) - limit)
        # Stable sorting also makes simultaneous events deterministic. Sorting
        # a bounded batch in NumPy avoids one Python allocation/heap operation
        # per crossing in the worker, which would monopolize the GIL.
        order = np.argsort(merged["end"], kind="stable")[-limit:]
        self._events = merged[order]

    def break_continuity(self, flag: str = "data_gap") -> None:
        self.flags.add(flag)
        for event in self.active.values():
            self._retain(PeakEvent(event.channel, event.kind, event.start, event.end, event.peak, True))
        self.active.clear()
        self._pending = np.empty((0, 2))
        self._warmup = 10

    def process(self, samples: np.ndarray, envelope: np.ndarray, start: int, channels: int) -> None:
        if self.channels and self.channels != channels:
            self.break_continuity("configuration_changed")
        if start != self._next:
            self.break_continuity()
        self.channels = channels
        self._next = start + len(samples)
        pending = np.concatenate((self._pending, np.abs(samples)))
        skip = min(self._warmup, len(envelope))
        self._warmup -= skip
        tp = envelope[skip:]
        count = len(tp)
        sp = pending[:count]
        self._pending = pending[count:]
        if count:
            self._accumulate(sp, np.maximum(sp, tp), start + skip - 10, channels)

    def finish(self, envelope: np.ndarray) -> None:
        """Drain only source frames awaiting FIR delay; do not count padding."""
        tp = envelope[self._warmup : self._warmup + len(self._pending)]
        if len(tp):
            self._accumulate(
                self._pending[: len(tp)],
                np.maximum(self._pending[: len(tp)], tp),
                self._next - len(self._pending),
                self.channels,
            )
        self._pending = np.empty((0, 2))
        for event in self.active.values():
            self._retain(PeakEvent(event.channel, event.kind, event.start, event.end, event.peak, True))
        self.active.clear()

    def _accumulate(self, sp: np.ndarray, tp: np.ndarray, start: int, channels: int) -> None:
        self.frames += len(sp)
        batches = []
        for ch in range(channels):
            db = 20 * np.log10(np.maximum(tp[:, ch], 1e-200))
            bins = np.searchsorted(self.EDGES, db, side="right")
            self.histogram[ch] += np.bincount(bins, minlength=len(self.EDGES) + 1)
            for kind, values in enumerate((sp[:, ch], tp[:, ch])):
                mask = values >= self.threshold
                self.exceedances[ch, kind] += np.count_nonzero(mask)
                edges = np.diff(np.concatenate(([False], mask, [False])).astype(np.int8))
                starts = np.flatnonzero(edges == 1)
                ends = np.flatnonzero(edges == -1)
                previous = self.active.pop((ch, kind), None)
                continuation = previous is not None and bool(mask[0])
                self.events_started[ch, kind] += len(starts) - int(continuation)
                if previous is not None and not continuation:
                    self._retain(previous)
                if not len(starts):
                    continue
                lengths = ends - starts
                if continuation:
                    assert previous is not None
                    lengths[0] += previous.end - previous.start
                self.longest_frames[ch, kind] = max(self.longest_frames[ch, kind], int(lengths.max()))
                # Count every event but retain at most MAX_EVENTS per block.
                omitted = max(0, len(starts) - self.MAX_EVENTS)
                self.evicted_events += omitted
                # Values between runs are below threshold, so reduceat from
                # one run start to the next gives the same maxima as reducing
                # only the above-threshold sections.
                peaks = np.maximum.reduceat(values, starts)
                event_starts = start + starts
                if continuation:
                    assert previous is not None
                    event_starts[0] = previous.start
                    peaks[0] = max(peaks[0], previous.peak)
                retained: np.ndarray = np.empty(len(starts) - omitted, dtype=self.EVENT_DTYPE)
                retained["channel"] = ch
                retained["kind"] = kind
                retained["start"] = event_starts[omitted:]
                retained["end"] = start + ends[omitted:]
                retained["peak"] = peaks[omitted:]
                retained["censored"] = False
                if ends[-1] == len(values):
                    self.active[ch, kind] = PeakEvent(
                        ch, kind, int(event_starts[-1]), start + int(ends[-1]), float(peaks[-1])
                    )
                    retained = retained[:-1]
                batches.append(retained)
        if batches:
            self._retain_batch(np.concatenate(batches))

    def snapshot(self, flags: set[str] | None = None) -> PeakProfileSnapshot:
        arrays = [a.copy() for a in (self.histogram, self.exceedances, self.events_started, self.longest_frames)]
        for array in arrays:
            array.flags.writeable = False
        # Active intervals are included and explicitly censored at the observation edge.
        active = tuple(PeakEvent(e.channel, e.kind, e.start, e.end, e.peak, True) for e in self.active.values())
        completed = tuple(
            PeakEvent(
                int(e["channel"]), int(e["kind"]), int(e["start"]), int(e["end"]), float(e["peak"]), bool(e["censored"])
            )
            for e in self._events
        )
        events = tuple(sorted((*completed, *active), key=lambda e: (e.start, e.channel, e.kind)))
        return PeakProfileSnapshot(
            self.threshold_db,
            self.sample_rate,
            self.frames,
            arrays[0],
            arrays[1],
            arrays[2],
            arrays[3],
            events,
            self.evicted_events,
            frozenset(self.flags | (flags or set())),
            self.channels,
        )


class PeakProfileSession:
    """SPSC preallocated mailbox; producer never waits on worker/GUI locks.

    CPython publication is the final integer write after a slot copy. The
    consumer advances its index only after owning a copy. Full queues drop the
    new block and latch loss, preserving source positions across that gap.
    """

    CAPACITY = 32
    MAX_FRAMES = 65536

    def __init__(self, sample_rate: float, threshold_db: float):
        self.core = PeakProfiler(sample_rate, threshold_db)
        self._slots = np.empty((self.CAPACITY, self.MAX_FRAMES, 4), dtype=np.float64)
        self._metadata = [(0, 0, 0, False)] * self.CAPACITY
        self.written = 0
        self.read = 0
        self.position = 0
        self.flags: set[str] = set()
        self._gap = False
        self.callback_gap = False
        self._lock = threading.Lock()  # worker and GUI only
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="LUFS peak profiler", daemon=True)
        self._tail: np.ndarray | None = None
        self._thread.start()

    def mark_gap(self, flag: str) -> None:
        self.flags.add(flag)
        self._gap = True

    def submit(self, samples: np.ndarray, envelope: np.ndarray, channels: int) -> None:
        count = len(samples)
        start = self.position
        self.position += count
        if count > self.MAX_FRAMES or self.written - self.read >= self.CAPACITY:
            self.mark_gap("queue_overflow")
            return
        slot = self.written % self.CAPACITY
        self._slots[slot, :count, :2] = samples
        self._slots[slot, :count, 2:] = envelope
        self._metadata[slot] = (count, start, channels, self._gap)
        self._gap = False
        self.written += 1

    def _run(self) -> None:
        try:
            while not self._stop.is_set() or self.read < self.written:
                if self.read == self.written:
                    self._stop.wait(0.001)
                    continue
                slot = self.read % self.CAPACITY
                count, start, channels, gap = self._metadata[slot]
                data = self._slots[slot, :count].copy()
                with self._lock:
                    if gap:
                        self.core.break_continuity()
                    self.core.process(data[:, :2], data[:, 2:], start, channels)
                self.read += 1
            with self._lock:
                if self._tail is not None and not self._gap:
                    self.core.finish(self._tail)
                else:
                    self.core.break_continuity("data_gap")
        except Exception:
            # Worker failure is visible even when no further callback arrives.
            self.flags.add("processing_error")

    def snapshot(self) -> PeakProfileSnapshot:
        with self._lock:
            return self.core.snapshot(self.flags.copy())

    def close(self, tail: np.ndarray | None = None) -> None:
        self._tail = tail
        self._stop.set()
        self._thread.join(timeout=2.0)
        if self._thread.is_alive():
            self.flags.add("processing_error")
