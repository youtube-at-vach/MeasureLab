import numpy as np
import pytest

from src.core.event_detector import DetectorConfig, EventCompletion, EventDetectorCore, EventPolarity, EventRecord
from src.core.event_statistics import EventMetric, build_histogram, build_rate_trend, summarize_events


def make_completed_events():
    detector = EventDetectorCore(
        DetectorConfig(
            sample_rate=1000,
            threshold=0.5,
            hysteresis=0.1,
            polarity=EventPolarity.BOTH,
        )
    )
    detector.start()
    detector.process(np.array([0.0, 0.6, 0.3, 0.0, -0.8, -0.2, 0.0, 0.9, 0.3, 0.0]))
    return detector


def test_event_statistics_separate_polarity_and_metric_semantics():
    detector = make_completed_events()

    statistics = summarize_events(detector.get_events(), amplitude_scale=2.0)

    assert statistics.valid_event_count == 3
    assert statistics.censored_event_count == 0
    assert statistics.positive_event_count == 2
    assert statistics.negative_event_count == 1
    assert statistics.amplitude.minimum == pytest.approx(1.2)
    assert statistics.amplitude.median == pytest.approx(1.6)
    assert statistics.amplitude.maximum == pytest.approx(1.8)
    assert statistics.duration.mean == pytest.approx(0.001)
    assert statistics.interarrival.count == 2
    assert statistics.interarrival.mean == pytest.approx(0.003)
    assert statistics.quiet_time.mean == pytest.approx(0.002)


def test_histogram_contains_every_valid_event():
    detector = make_completed_events()

    histogram = build_histogram(detector.get_events(), EventMetric.AMPLITUDE, bins=4)

    assert len(histogram.edges) == 5
    assert sum(histogram.counts) == 3


def test_rate_trend_uses_partial_exposure_and_marks_gap_bin_invalid():
    detector = make_completed_events()

    trend = build_rate_trend(
        detector.get_events(),
        elapsed_seconds=0.012,
        sample_rate=1000,
        bin_seconds=0.005,
        data_gap_samples=(4,),
    )

    assert trend.event_counts == (2, 1, 0)
    assert np.isnan(trend.rates_per_minute[0])
    assert trend.rates_per_minute[1] == pytest.approx(12_000.0)
    assert trend.rates_per_minute[2] == pytest.approx(0.0)
    assert trend.valid_bins == (False, True, True)
    assert trend.partial_bins == (False, False, True)


def test_censored_event_is_excluded_from_distribution_statistics():
    detector = EventDetectorCore(
        DetectorConfig(sample_rate=1000, threshold=0.5, hysteresis=0.1, polarity=EventPolarity.POSITIVE)
    )
    detector.start()
    detector.process(np.array([0.0, 0.7]))
    detector.stop()

    statistics = summarize_events(detector.get_events())

    assert statistics.valid_event_count == 0
    assert statistics.censored_event_count == 1
    assert statistics.amplitude.count == 0


def test_rate_trend_excludes_censored_and_out_of_range_records():
    def event(start_sample, completion=EventCompletion.VALID):
        return EventRecord(
            sequence_number=0,
            start_sample=start_sample,
            end_sample=start_sample + 1,
            polarity=EventPolarity.POSITIVE,
            peak=1.0,
            duration_seconds=0.001,
            interval_seconds=None,
            completion=completion,
        )

    trend = build_rate_trend(
        (
            event(2),
            event(7),
            event(4, EventCompletion.CENSORED_GAP),
            event(-1),
            event(10),
        ),
        elapsed_seconds=0.01,
        sample_rate=1000,
        bin_seconds=0.005,
        data_gap_samples=(-1, 4, 10),
    )

    assert trend.event_counts == (1, 1)
    assert trend.valid_bins == (False, True)
