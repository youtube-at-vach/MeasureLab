"""Sample-accurate threshold event detection for continuous measurements."""

from __future__ import annotations

import math
import threading
from collections import deque
from dataclasses import dataclass
from enum import StrEnum

import numpy as np


class EventPolarity(StrEnum):
    """Threshold directions supported by the detector."""

    POSITIVE = "positive"
    NEGATIVE = "negative"
    BOTH = "both"


class DetectorState(StrEnum):
    """Externally visible detector states."""

    STOPPED = "stopped"
    ARMED = "armed"
    EVENT = "event"
    HOLDOFF = "holdoff"


@dataclass(frozen=True, slots=True)
class DetectorConfig:
    """Immutable detector settings for one measurement run."""

    sample_rate: float
    threshold: float
    polarity: EventPolarity = EventPolarity.BOTH
    hysteresis: float = 0.0
    holdoff_seconds: float = 0.0
    clip_level: float = 1.0

    def __post_init__(self) -> None:
        try:
            polarity = EventPolarity(self.polarity)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Unsupported event polarity: {self.polarity!r}") from exc
        object.__setattr__(self, "polarity", polarity)

        numeric_values = {
            "sample_rate": self.sample_rate,
            "threshold": self.threshold,
            "hysteresis": self.hysteresis,
            "holdoff_seconds": self.holdoff_seconds,
            "clip_level": self.clip_level,
        }
        for name, value in numeric_values.items():
            if not math.isfinite(float(value)):
                raise ValueError(f"{name} must be finite")

        if self.sample_rate <= 0:
            raise ValueError("sample_rate must be greater than zero")
        if self.threshold <= 0:
            raise ValueError("threshold must be greater than zero")
        if self.hysteresis < 0:
            raise ValueError("hysteresis must not be negative")
        if self.hysteresis >= self.threshold:
            raise ValueError("hysteresis must be smaller than threshold")
        if self.holdoff_seconds < 0:
            raise ValueError("holdoff_seconds must not be negative")
        if self.clip_level <= 0:
            raise ValueError("clip_level must be greater than zero")

    @property
    def holdoff_samples(self) -> int:
        """Holdoff rounded upward so it is never shorter than requested."""
        return int(math.ceil(self.holdoff_seconds * self.sample_rate))


@dataclass(frozen=True, slots=True)
class EventRecord:
    """A completed threshold event."""

    sequence_number: int
    start_sample: int
    end_sample: int
    polarity: EventPolarity
    peak: float
    duration_seconds: float
    interval_seconds: float | None


@dataclass(frozen=True, slots=True)
class DetectorSnapshot:
    """Thread-safe, immutable view consumed by the GUI."""

    state: DetectorState
    event_count: int
    processed_samples: int
    elapsed_seconds: float
    event_rate_per_minute: float
    clipping_detected: bool
    data_gap_detected: bool
    last_event: EventRecord | None


class EventDetectorCore:
    """Continuous detector whose state remains valid across audio blocks.

    The implementation searches transitions with NumPy and only iterates when
    the detector changes state. This keeps the common, event-free path light
    enough for an audio callback while preserving sample-level timestamps.
    """

    def __init__(self, config: DetectorConfig, max_records: int = 10_000):
        if max_records <= 0:
            raise ValueError("max_records must be greater than zero")

        self._lock = threading.Lock()
        self._config = config
        self._events: deque[EventRecord] = deque(maxlen=int(max_records))
        self._running = False
        self._state = DetectorState.STOPPED

        self._processed_samples = 0
        self._event_count = 0
        self._previous_sample: float | None = None
        self._holdoff_remaining = 0

        self._active_polarity: EventPolarity | None = None
        self._active_start_sample: int | None = None
        self._active_peak = 0.0
        self._active_interval_seconds: float | None = None
        self._last_event_start_sample: int | None = None

        self._clipping_detected = False
        self._data_gap_detected = False
        self._last_event: EventRecord | None = None

    @property
    def config(self) -> DetectorConfig:
        return self._config

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._running

    def start(self, config: DetectorConfig | None = None) -> None:
        """Start a new measurement and clear all previous results."""
        with self._lock:
            if config is not None:
                self._config = config
            self._reset_locked(running=True)

    def stop(self) -> None:
        """Stop measurement while preserving the current results."""
        with self._lock:
            self._running = False
            self._state = DetectorState.STOPPED

    def reset(self) -> None:
        """Clear results, retaining whether the detector is currently running."""
        with self._lock:
            self._reset_locked(running=self._running)

    def _reset_locked(self, running: bool) -> None:
        self._events.clear()
        self._running = running
        self._state = DetectorState.ARMED if running else DetectorState.STOPPED
        self._processed_samples = 0
        self._event_count = 0
        self._previous_sample = None
        self._holdoff_remaining = 0
        self._active_polarity = None
        self._active_start_sample = None
        self._active_peak = 0.0
        self._active_interval_seconds = None
        self._last_event_start_sample = None
        self._clipping_detected = False
        self._data_gap_detected = False
        self._last_event = None

    def mark_data_gap(self) -> None:
        """Latch a warning that some input samples may have been lost."""
        with self._lock:
            self._data_gap_detected = True

    def process(self, samples: np.ndarray, *, data_gap: bool = False) -> None:
        """Process a mono input block.

        Args:
            samples: One-dimensional samples in full-scale units.
            data_gap: True when the audio backend reports an under/overflow.
        """
        data = np.asarray(samples)
        if data.ndim != 1:
            raise ValueError("samples must be one-dimensional")

        with self._lock:
            if not self._running or data.size == 0:
                return
            if data_gap:
                self._data_gap_detected = True

            if not np.all(np.isfinite(data)):
                self._data_gap_detected = True
                # A non-finite sample breaks crossing continuity. Do not invent
                # a transition on either side of invalid input.
                finite_data = data[np.isfinite(data)]
                if finite_data.size:
                    self._latch_clipping(finite_data)
                self._processed_samples += int(data.size)
                self._previous_sample = None
                return

            self._latch_clipping(data)
            self._process_finite_block(data)

    def _latch_clipping(self, data: np.ndarray) -> None:
        if self._clipping_detected or data.size == 0:
            return
        clip_level = float(self._config.clip_level)
        if float(np.max(data)) >= clip_level or float(np.min(data)) <= -clip_level:
            self._clipping_detected = True

    def _process_finite_block(self, data: np.ndarray) -> None:
        block_start = self._processed_samples
        pos = 0
        size = int(data.size)

        while pos < size:
            if self._state == DetectorState.HOLDOFF:
                skipped = min(self._holdoff_remaining, size - pos)
                if skipped > 0:
                    self._previous_sample = float(data[pos + skipped - 1])
                    pos += skipped
                    self._holdoff_remaining -= skipped
                if self._holdoff_remaining == 0:
                    self._state = DetectorState.ARMED
                continue

            if self._state == DetectorState.EVENT:
                release_index = self._find_release(data, pos)
                end = size if release_index is None else release_index + 1
                self._update_active_peak(data[pos:end])

                if release_index is None:
                    self._previous_sample = float(data[-1])
                    pos = size
                    continue

                self._previous_sample = float(data[release_index])
                self._finish_event(block_start + release_index)
                pos = release_index + 1

                self._holdoff_remaining = self._config.holdoff_samples
                self._state = DetectorState.HOLDOFF if self._holdoff_remaining > 0 else DetectorState.ARMED
                continue

            crossing = self._find_first_crossing(data, pos)
            if crossing is None:
                self._previous_sample = float(data[-1])
                pos = size
                continue

            crossing_index, polarity = crossing
            self._start_event(block_start + crossing_index, polarity, float(data[crossing_index]))
            self._previous_sample = float(data[crossing_index])
            pos = crossing_index + 1

        self._processed_samples += size

    def _find_first_crossing(self, data: np.ndarray, pos: int) -> tuple[int, EventPolarity] | None:
        threshold = float(self._config.threshold)
        polarity = self._config.polarity
        positive_index: int | None = None
        negative_index: int | None = None

        if polarity in (EventPolarity.POSITIVE, EventPolarity.BOTH):
            positive_index = self._find_direction_crossing(
                data,
                pos,
                self._previous_sample,
                level=threshold,
                positive=True,
            )
        if polarity in (EventPolarity.NEGATIVE, EventPolarity.BOTH):
            negative_index = self._find_direction_crossing(
                data,
                pos,
                self._previous_sample,
                level=-threshold,
                positive=False,
            )

        if positive_index is None and negative_index is None:
            return None
        if positive_index is not None and (negative_index is None or positive_index <= negative_index):
            return positive_index, EventPolarity.POSITIVE
        if negative_index is not None:
            return negative_index, EventPolarity.NEGATIVE
        return None

    @staticmethod
    def _find_direction_crossing(
        data: np.ndarray,
        pos: int,
        previous: float | None,
        *,
        level: float,
        positive: bool,
    ) -> int | None:
        first = float(data[pos])
        if previous is not None:
            if positive and previous < level <= first:
                return pos
            if not positive and previous > level >= first:
                return pos

        segment = data[pos:]
        if segment.size < 2:
            return None

        if positive:
            crossings = np.flatnonzero((segment[:-1] < level) & (segment[1:] >= level))
        else:
            crossings = np.flatnonzero((segment[:-1] > level) & (segment[1:] <= level))
        if crossings.size == 0:
            return None
        return int(pos + crossings[0] + 1)

    def _find_release(self, data: np.ndarray, pos: int) -> int | None:
        release_level = float(self._config.threshold - self._config.hysteresis)
        segment = data[pos:]
        if self._active_polarity == EventPolarity.POSITIVE:
            releases = np.flatnonzero(segment <= release_level)
        else:
            releases = np.flatnonzero(segment >= -release_level)
        if releases.size == 0:
            return None
        return int(pos + releases[0])

    def _start_event(self, start_sample: int, polarity: EventPolarity, value: float) -> None:
        interval_seconds = None
        if self._last_event_start_sample is not None:
            interval_seconds = (start_sample - self._last_event_start_sample) / self._config.sample_rate

        self._event_count += 1
        self._state = DetectorState.EVENT
        self._active_polarity = polarity
        self._active_start_sample = start_sample
        self._active_peak = value
        self._active_interval_seconds = interval_seconds
        self._last_event_start_sample = start_sample

    def _update_active_peak(self, segment: np.ndarray) -> None:
        if segment.size == 0:
            return
        if self._active_polarity == EventPolarity.POSITIVE:
            self._active_peak = max(self._active_peak, float(np.max(segment)))
        else:
            self._active_peak = min(self._active_peak, float(np.min(segment)))

    def _finish_event(self, end_sample: int) -> None:
        if self._active_start_sample is None or self._active_polarity is None:
            return

        event = EventRecord(
            sequence_number=self._event_count,
            start_sample=self._active_start_sample,
            end_sample=end_sample,
            polarity=self._active_polarity,
            peak=self._active_peak,
            duration_seconds=(end_sample - self._active_start_sample) / self._config.sample_rate,
            interval_seconds=self._active_interval_seconds,
        )
        self._events.append(event)
        self._last_event = event
        self._active_polarity = None
        self._active_start_sample = None
        self._active_peak = 0.0
        self._active_interval_seconds = None

    def snapshot(self) -> DetectorSnapshot:
        """Return a consistent view without exposing mutable detector state."""
        with self._lock:
            elapsed = self._processed_samples / self._config.sample_rate
            rate = (self._event_count * 60.0 / elapsed) if elapsed > 0 else 0.0
            return DetectorSnapshot(
                state=self._state,
                event_count=self._event_count,
                processed_samples=self._processed_samples,
                elapsed_seconds=elapsed,
                event_rate_per_minute=rate,
                clipping_detected=self._clipping_detected,
                data_gap_detected=self._data_gap_detected,
                last_event=self._last_event,
            )

    def get_events(self) -> tuple[EventRecord, ...]:
        """Return retained completed events, oldest first."""
        with self._lock:
            return tuple(self._events)
