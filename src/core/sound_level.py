"""Sample-clocked sound level history and streaming impulse time weighting.

The acquisition owner serializes writes and snapshot copies. Statistical work
uses detached snapshots, so sorting never holds the audio processing lock.
"""

import math
from dataclasses import dataclass
from functools import cached_property

import numpy as np


@dataclass(frozen=True)
class LevelHistorySnapshot:
    revision: int
    powers: np.ndarray
    interval_seconds: float

    @cached_property
    def levels_db(self) -> np.ndarray:
        return 10 * np.log10(self.powers + 1e-12)

    @cached_property
    def statistics(self) -> dict[str, float]:
        if not self.powers.size:
            return {}
        percentiles = np.percentile(self.levels_db, [95, 90, 50, 10, 5])
        return {
            **dict(zip(("L5", "L10", "L50", "L90", "L95"), map(float, percentiles), strict=True)),
            "Lhigh": float(np.max(self.levels_db)),
            "Llow": float(np.min(self.levels_db)),
            "Lave": float(10 * np.log10(np.mean(self.powers) + 1e-12)),
        }

    def histogram(self, bin_size: float = 0.5) -> tuple[np.ndarray, np.ndarray]:
        if not np.isfinite(bin_size) or bin_size <= 0:
            raise ValueError("Histogram bin size must be finite and positive")
        if not self.powers.size:
            return np.array([]), np.array([])
        start = np.floor(np.min(self.levels_db) / bin_size) * bin_size
        end = max(start + bin_size, np.ceil(np.max(self.levels_db) / bin_size) * bin_size)
        counts, edges = np.histogram(self.levels_db, bins=np.arange(start, end + bin_size, bin_size))
        return (edges[:-1] + edges[1:]) / 2, counts * (100.0 / self.powers.size)


class LevelHistory:
    """Retain the latest 10 hours of Lp samples at 100 ms boundaries."""

    def __init__(self, sample_rate: float, capacity: int = 360000):
        if sample_rate <= 0 or capacity <= 0:
            raise ValueError("Sample rate and history capacity must be positive")
        self.period = max(1, round(sample_rate * 0.1))
        self.interval_seconds = self.period / sample_rate
        self._powers = np.empty(capacity, dtype=np.float64)
        self.count = 0
        self.position = 0
        self.revision = 0
        self._write = 0

    def append(self, weighted_powers: np.ndarray) -> None:
        first = self.period - self.position % self.period - 1
        values = weighted_powers[first :: self.period]
        self.position += len(weighted_powers)
        if not values.size:
            return
        capacity = len(self._powers)
        if len(values) >= capacity:
            self._powers[:] = values[-capacity:]
            self._write = 0
        else:
            tail = min(len(values), capacity - self._write)
            self._powers[self._write : self._write + tail] = values[:tail]
            self._powers[: len(values) - tail] = values[tail:]
            self._write = (self._write + len(values)) % capacity
        self.count = min(capacity, self.count + len(values))
        self.revision += 1

    def snapshot(self) -> LevelHistorySnapshot:
        # Ordering is immaterial for percentiles and distributions.
        values = self._powers[: self.count].copy()
        values.flags.writeable = False
        return LevelHistorySnapshot(self.revision, values, self.interval_seconds)


class ImpulseTimeWeighting:
    """Asymmetric 35 ms rise / 1.5 s fall detector on each squared sample.

    Carry only the detector value between calls. No padding, pooling, or block
    approximation may change the result when callback boundaries move.
    """

    def __init__(self):
        self.value = 0.0

    def process(self, powers: np.ndarray, sample_rate: float) -> np.ndarray:
        rise = -math.expm1(-1 / (sample_rate * 0.035))
        fall = -math.expm1(-1 / (sample_rate * 1.5))
        value = self.value
        output = np.fromiter(
            (value := value + (rise if power > value else fall) * (power - value) for power in powers.tolist()),
            dtype=np.float64,
            count=len(powers),
        )
        self.value = value
        return output
