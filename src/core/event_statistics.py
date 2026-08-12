"""Statistical views derived from Event Detector records."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable

import numpy as np

from src.core.event_detector import EventCompletion, EventPolarity, EventRecord


class EventMetric(StrEnum):
    """Metrics available to summary and histogram views."""

    AMPLITUDE = "amplitude"
    DURATION = "duration"
    INTERARRIVAL = "interarrival"
    QUIET_TIME = "quiet_time"


@dataclass(frozen=True, slots=True)
class MetricSummary:
    count: int
    minimum: float | None
    median: float | None
    mean: float | None
    standard_deviation: float | None
    percentile_95: float | None
    percentile_99: float | None
    maximum: float | None


@dataclass(frozen=True, slots=True)
class EventStatisticsSnapshot:
    valid_event_count: int
    censored_event_count: int
    positive_event_count: int
    negative_event_count: int
    amplitude: MetricSummary
    duration: MetricSummary
    interarrival: MetricSummary
    quiet_time: MetricSummary


@dataclass(frozen=True, slots=True)
class HistogramData:
    edges: tuple[float, ...]
    counts: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class RateTrendData:
    bin_starts_seconds: tuple[float, ...]
    bin_ends_seconds: tuple[float, ...]
    rates_per_minute: tuple[float, ...]
    event_counts: tuple[int, ...]
    valid_bins: tuple[bool, ...]
    partial_bins: tuple[bool, ...]


def valid_events(events: Iterable[EventRecord]) -> tuple[EventRecord, ...]:
    """Return completed, non-censored events in acquisition order."""
    return tuple(event for event in events if event.completion == EventCompletion.VALID)


def metric_values(
    events: Iterable[EventRecord],
    metric: EventMetric | str,
    *,
    amplitude_scale: float = 1.0,
) -> np.ndarray:
    """Extract one finite metric from valid event records."""
    selected = EventMetric(metric)
    values: list[float] = []
    for event in events:
        if event.completion != EventCompletion.VALID:
            continue
        value: float | None
        if selected == EventMetric.AMPLITUDE:
            value = abs(float(event.peak)) * amplitude_scale
        elif selected == EventMetric.DURATION:
            value = float(event.duration_seconds)
        elif selected == EventMetric.INTERARRIVAL:
            value = event.interval_seconds
        else:
            value = event.quiet_time_seconds
        if value is not None and math.isfinite(float(value)):
            values.append(float(value))
    return np.asarray(values, dtype=np.float64)


def summarize_metric(values: np.ndarray | Iterable[float]) -> MetricSummary:
    """Calculate deterministic descriptive statistics for one metric."""
    data = np.asarray(tuple(values) if not isinstance(values, np.ndarray) else values, dtype=np.float64)
    data = data[np.isfinite(data)]
    count = int(data.size)
    if count == 0:
        return MetricSummary(0, None, None, None, None, None, None, None)
    std = float(np.std(data, ddof=1)) if count > 1 else 0.0
    return MetricSummary(
        count=count,
        minimum=float(np.min(data)),
        median=float(np.median(data)),
        mean=float(np.mean(data)),
        standard_deviation=std,
        percentile_95=float(np.percentile(data, 95)),
        percentile_99=float(np.percentile(data, 99)),
        maximum=float(np.max(data)),
    )


def summarize_events(events: Iterable[EventRecord], *, amplitude_scale: float = 1.0) -> EventStatisticsSnapshot:
    """Build all summary statistics from one stable event-record snapshot."""
    records = tuple(events)
    completed = valid_events(records)
    positive = sum((event.peak_polarity or event.polarity) == EventPolarity.POSITIVE for event in completed)
    negative = sum((event.peak_polarity or event.polarity) == EventPolarity.NEGATIVE for event in completed)
    censored = sum(event.completion != EventCompletion.VALID for event in records)
    return EventStatisticsSnapshot(
        valid_event_count=len(completed),
        censored_event_count=censored,
        positive_event_count=positive,
        negative_event_count=negative,
        amplitude=summarize_metric(metric_values(completed, EventMetric.AMPLITUDE, amplitude_scale=amplitude_scale)),
        duration=summarize_metric(metric_values(completed, EventMetric.DURATION)),
        interarrival=summarize_metric(metric_values(completed, EventMetric.INTERARRIVAL)),
        quiet_time=summarize_metric(metric_values(completed, EventMetric.QUIET_TIME)),
    )


def build_histogram(
    events: Iterable[EventRecord],
    metric: EventMetric | str,
    *,
    bins: int | None = None,
    amplitude_scale: float = 1.0,
) -> HistogramData:
    """Build a stable finite histogram for a selected event metric."""
    values = metric_values(events, metric, amplitude_scale=amplitude_scale)
    if values.size == 0:
        return HistogramData((), ())
    bin_count = int(bins) if bins is not None else min(50, max(5, int(math.ceil(math.sqrt(values.size)))))
    if bin_count <= 0:
        raise ValueError("bins must be greater than zero")

    value_min = float(np.min(values))
    value_max = float(np.max(values))
    histogram_range = None
    if value_min == value_max:
        delta = max(abs(value_min) * 0.05, 1e-12)
        histogram_range = (value_min - delta, value_max + delta)
    counts, edges = np.histogram(values, bins=bin_count, range=histogram_range)
    return HistogramData(tuple(float(value) for value in edges), tuple(int(value) for value in counts))


def build_rate_trend(
    events: Iterable[EventRecord],
    *,
    elapsed_seconds: float,
    sample_rate: float,
    bin_seconds: float,
    data_gap_samples: Iterable[int] = (),
) -> RateTrendData:
    """Calculate non-overlapping event-rate bins and mark bins containing gaps."""
    if not math.isfinite(float(elapsed_seconds)) or elapsed_seconds < 0:
        raise ValueError("elapsed_seconds must be finite and non-negative")
    if not math.isfinite(float(sample_rate)) or sample_rate <= 0:
        raise ValueError("sample_rate must be finite and greater than zero")
    if not math.isfinite(float(bin_seconds)) or bin_seconds <= 0:
        raise ValueError("bin_seconds must be finite and greater than zero")
    if elapsed_seconds == 0:
        return RateTrendData((), (), (), (), (), ())

    bin_count = max(1, int(math.ceil(elapsed_seconds / bin_seconds)))
    counts = np.zeros(bin_count, dtype=np.int64)
    for event in events:
        start_seconds = float(event.start_sample) / sample_rate
        index = min(bin_count - 1, max(0, int(start_seconds // bin_seconds)))
        counts[index] += 1

    starts = np.arange(bin_count, dtype=np.float64) * bin_seconds
    ends = np.minimum(starts + bin_seconds, elapsed_seconds)
    exposure = ends - starts
    rates = np.divide(counts * 60.0, exposure, out=np.zeros(bin_count, dtype=np.float64), where=exposure > 0)
    valid = np.ones(bin_count, dtype=np.bool_)
    for sample in data_gap_samples:
        gap_seconds = max(0.0, float(sample) / sample_rate)
        index = min(bin_count - 1, int(gap_seconds // bin_seconds))
        valid[index] = False
    rates[~valid] = np.nan
    partial = exposure < (bin_seconds - max(1e-12, bin_seconds * 1e-12))

    return RateTrendData(
        tuple(float(value) for value in starts),
        tuple(float(value) for value in ends),
        tuple(float(value) for value in rates),
        tuple(int(value) for value in counts),
        tuple(bool(value) for value in valid),
        tuple(bool(value) for value in partial),
    )
