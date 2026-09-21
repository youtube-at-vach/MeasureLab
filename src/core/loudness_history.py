"""Acquisition-clock loudness history and session statistics, independent of Qt."""

from collections import deque
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class LoudnessStatistics:
    count: int = 0
    minimum: float | None = None
    maximum: float | None = None
    average: float | None = None

    def include(self, value: float | None) -> "LoudnessStatistics":
        # The meter's -100 sentinel represents silence, not a finite reading.
        if value is None or not math.isfinite(value) or value <= -99.9:
            return self
        count = self.count + 1
        return LoudnessStatistics(
            count,
            value if self.minimum is None else min(self.minimum, value),
            value if self.maximum is None else max(self.maximum, value),
            value if self.average is None else self.average + (value - self.average) / count,
        )


@dataclass(frozen=True)
class LoudnessPoint:
    sample: int
    momentary: float
    short_term: float | None


@dataclass(frozen=True)
class LoudnessHistorySnapshot:
    sample_rate: float
    sample_count: int
    points: tuple[LoudnessPoint, ...]
    momentary: LoudnessStatistics
    short_term: LoudnessStatistics


class LoudnessHistory:
    """Record complete windows at the meter's existing 100 ms boundaries.

    Keep only 20 seconds of plot data, while min/max/arithmetic mean in LUFS
    cover the whole session. The owner serializes append and snapshot calls.
    """

    HISTORY_SECONDS = 20

    def __init__(self, sample_rate: float, step_samples: int):
        self.sample_rate = sample_rate
        self._span_samples = round(self.HISTORY_SECONDS * sample_rate)
        self._points: deque[LoudnessPoint] = deque(maxlen=math.ceil(self._span_samples / step_samples) + 1)
        self._momentary = LoudnessStatistics()
        self._short_term = LoudnessStatistics()

    def append(self, sample: int, momentary: float, short_term: float | None) -> None:
        self._points.append(LoudnessPoint(sample, momentary, short_term))
        self._momentary = self._momentary.include(momentary)
        self._short_term = self._short_term.include(short_term)

    def snapshot(self, sample_count: int) -> LoudnessHistorySnapshot:
        cutoff = sample_count - self._span_samples
        return LoudnessHistorySnapshot(
            self.sample_rate,
            sample_count,
            tuple(point for point in self._points if point.sample >= cutoff),
            self._momentary,
            self._short_term,
        )
