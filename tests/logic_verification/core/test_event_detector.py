import numpy as np
import pytest

from src.core.event_detector import (
    DetectorConfig,
    DetectorState,
    EventDetectorCore,
    EventCompletion,
    EventPolarity,
)


def make_detector(
    *,
    polarity: EventPolarity = EventPolarity.BOTH,
    threshold: float = 0.5,
    hysteresis: float = 0.1,
    holdoff_seconds: float = 0.0,
    sample_rate: float = 1000.0,
) -> EventDetectorCore:
    detector = EventDetectorCore(
        DetectorConfig(
            sample_rate=sample_rate,
            threshold=threshold,
            polarity=polarity,
            hysteresis=hysteresis,
            holdoff_seconds=holdoff_seconds,
        )
    )
    detector.start()
    return detector


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"sample_rate": 0, "threshold": 0.5}, "sample_rate"),
        ({"sample_rate": 1000, "threshold": 0}, "threshold"),
        ({"sample_rate": 1000, "threshold": 0.5, "hysteresis": -0.1}, "hysteresis"),
        ({"sample_rate": 1000, "threshold": 0.5, "hysteresis": 0.5}, "hysteresis"),
        ({"sample_rate": 1000, "threshold": 0.5, "holdoff_seconds": -0.1}, "holdoff"),
        ({"sample_rate": 1000, "threshold": np.nan}, "finite"),
        ({"sample_rate": 1000, "threshold": 1.0, "clip_level": 1.0}, "clip_level"),
        (
            {"sample_rate": 1000, "threshold": 0.5, "clipping_invalidates_measurement": 1},
            "boolean",
        ),
    ],
)
def test_config_rejects_invalid_settings(kwargs, message):
    with pytest.raises(ValueError, match=message):
        DetectorConfig(**kwargs)


def test_config_allows_clip_event_threshold_above_full_scale():
    config = DetectorConfig(
        sample_rate=1000,
        threshold=1000.0,
        hysteresis=999.0,
        clipping_invalidates_measurement=False,
    )

    assert config.threshold == pytest.approx(1000.0)


def test_positive_events_record_count_peak_duration_and_interval():
    detector = make_detector(polarity=EventPolarity.POSITIVE)

    detector.process(np.array([0.0, 0.4, 0.5, 0.7, 0.4, 0.6, 0.3]))

    snapshot = detector.snapshot()
    events = detector.get_events()
    assert snapshot.state == DetectorState.ARMED
    assert snapshot.event_count == 2
    assert snapshot.processed_samples == 7
    assert snapshot.elapsed_seconds == pytest.approx(0.007)
    assert snapshot.event_rate_per_minute == pytest.approx(2 * 60 / 0.007)
    assert len(events) == 2
    assert events[0].start_sample == 2
    assert events[0].end_sample == 4
    assert events[0].peak == pytest.approx(0.7)
    assert events[0].duration_seconds == pytest.approx(0.002)
    assert events[0].interval_seconds is None
    assert events[1].interval_seconds == pytest.approx(0.003)


def test_negative_polarity_ignores_positive_crossings():
    detector = make_detector(polarity=EventPolarity.NEGATIVE)

    detector.process(np.array([0.0, 0.7, 0.0, -0.6, -0.8, -0.3]))

    events = detector.get_events()
    assert detector.snapshot().event_count == 1
    assert events[0].polarity == EventPolarity.NEGATIVE
    assert events[0].peak == pytest.approx(-0.8)


def test_both_polarities_are_counted_after_rearming():
    detector = make_detector(polarity=EventPolarity.BOTH)

    detector.process(np.array([0.0, 0.6, 0.3, 0.0, -0.7, -0.2]))

    events = detector.get_events()
    assert [event.polarity for event in events] == [EventPolarity.POSITIVE, EventPolarity.NEGATIVE]


def test_event_spanning_audio_blocks_is_counted_once():
    detector = make_detector(polarity=EventPolarity.POSITIVE)

    detector.process(np.array([0.0, 0.6, 0.8]))
    assert detector.snapshot().state == DetectorState.EVENT
    assert detector.snapshot().event_count == 1

    detector.process(np.array([0.7, 0.45, 0.39]))

    events = detector.get_events()
    assert detector.snapshot().state == DetectorState.ARMED
    assert detector.snapshot().event_count == 1
    assert len(events) == 1
    assert events[0].start_sample == 1
    assert events[0].end_sample == 5
    assert events[0].peak == pytest.approx(0.8)


def test_hysteresis_prevents_chatter_from_becoming_multiple_events():
    detector = make_detector(polarity=EventPolarity.POSITIVE)

    detector.process(np.array([0.0, 0.6, 0.45, 0.55, 0.41, 0.39]))

    assert detector.snapshot().event_count == 1
    assert len(detector.get_events()) == 1


def test_holdoff_ignores_crossings_then_rearms_on_current_samples():
    detector = make_detector(
        polarity=EventPolarity.POSITIVE,
        holdoff_seconds=0.003,
    )

    detector.process(np.array([0.0, 0.6, 0.3, 0.0, 0.7, 0.0, 0.6, 0.3]))

    events = detector.get_events()
    assert detector.snapshot().event_count == 2
    assert [event.start_sample for event in events] == [1, 6]


def test_signal_already_above_threshold_at_start_is_not_counted():
    detector = make_detector(polarity=EventPolarity.POSITIVE)

    detector.process(np.array([0.8, 0.7, 0.6]))
    assert detector.snapshot().event_count == 0

    detector.process(np.array([0.3, 0.7, 0.3]))
    assert detector.snapshot().event_count == 1


def test_chunking_does_not_change_detection_results():
    signal = np.array(
        [0.0, 0.6, 0.7, 0.3, 0.0, -0.8, -0.6, -0.2, 0.0, 0.55, 0.35],
        dtype=np.float32,
    )
    complete = make_detector(polarity=EventPolarity.BOTH, holdoff_seconds=0.001)
    chunked = make_detector(polarity=EventPolarity.BOTH, holdoff_seconds=0.001)

    complete.process(signal)
    for chunk in np.array_split(signal, [1, 3, 4, 7, 9]):
        chunked.process(chunk)

    assert chunked.snapshot() == complete.snapshot()
    assert chunked.get_events() == complete.get_events()


def test_stop_preserves_results_and_reset_clears_them():
    detector = make_detector(polarity=EventPolarity.POSITIVE)
    detector.process(np.array([0.0, 0.6, 0.3]), data_gap=True)
    detector.process(np.array([-1.0]))

    detector.stop()
    stopped = detector.snapshot()
    assert stopped.state == DetectorState.STOPPED
    assert stopped.event_count == 1
    assert stopped.clipping_detected
    assert stopped.data_gap_detected

    detector.process(np.array([0.0, 0.8, 0.0]))
    assert detector.snapshot().event_count == 1

    detector.reset()
    reset = detector.snapshot()
    assert reset.state == DetectorState.STOPPED
    assert reset.event_count == 0
    assert reset.elapsed_seconds == 0
    assert not reset.clipping_detected
    assert not reset.data_gap_detected

    detector.process(np.array([0.0]), data_gap=True)
    assert not detector.snapshot().data_gap_detected


def test_clipping_quality_policy_can_be_disabled_for_clip_measurements():
    invalidating = EventDetectorCore(DetectorConfig(sample_rate=1000, threshold=0.5))
    clip_measurement = EventDetectorCore(
        DetectorConfig(
            sample_rate=1000,
            threshold=0.5,
            clipping_invalidates_measurement=False,
        )
    )
    invalidating.start()
    clip_measurement.start()

    samples = np.array([0.0, 1.0, 0.0])
    invalidating.process(samples)
    clip_measurement.process(samples)

    assert invalidating.snapshot().clipping_detected
    assert not invalidating.snapshot().measurement_valid
    assert clip_measurement.snapshot().clipping_detected
    assert clip_measurement.snapshot().measurement_valid


def test_non_finite_input_latches_data_gap_and_breaks_crossing_continuity():
    detector = make_detector(polarity=EventPolarity.POSITIVE)

    detector.process(np.array([0.0, np.nan, 0.7]))
    detector.process(np.array([0.8, 0.3, 0.7, 0.3]))

    assert detector.snapshot().data_gap_detected
    assert detector.snapshot().event_count == 1


def test_detector_waits_for_release_band_before_first_event():
    detector = make_detector(polarity=EventPolarity.POSITIVE)

    detector.process(np.array([0.45, 0.6, 0.3]))

    assert detector.snapshot().event_count == 0
    assert detector.snapshot().state == DetectorState.ARMED

    detector.process(np.array([0.6, 0.3]))
    assert detector.snapshot().event_count == 1


def test_data_gap_does_not_invent_crossing_at_next_block_boundary():
    detector = make_detector(polarity=EventPolarity.POSITIVE)
    detector.process(np.array([0.0]))

    detector.process(np.array([0.6, 0.3]), data_gap=True)

    snapshot = detector.snapshot()
    assert snapshot.event_count == 0
    assert snapshot.data_gap_detected
    assert not snapshot.measurement_valid


def test_data_gap_censors_active_event_and_rearms_from_release_band():
    detector = make_detector(polarity=EventPolarity.POSITIVE)
    detector.process(np.array([0.0, 0.6]))

    detector.process(np.array([0.3]), data_gap=True)

    snapshot = detector.snapshot()
    events = detector.get_events()
    assert snapshot.event_count == 1
    assert snapshot.completed_event_count == 0
    assert snapshot.censored_event_count == 1
    assert snapshot.state == DetectorState.ARMED
    assert events[0].completion == EventCompletion.CENSORED_GAP


def test_gap_breaks_interarrival_and_quiet_time_continuity():
    detector = make_detector(polarity=EventPolarity.POSITIVE)
    detector.process(np.array([0.0, 0.6, 0.3]))
    detector.process(np.array([0.0]), data_gap=True)
    detector.process(np.array([0.6, 0.3]))

    second = detector.get_events()[1]
    assert second.interval_seconds is None
    assert second.quiet_time_seconds is None


def test_stop_censors_active_event_without_losing_start_count():
    detector = make_detector(polarity=EventPolarity.POSITIVE)
    detector.process(np.array([0.0, 0.6]))

    detector.stop()

    snapshot = detector.snapshot()
    assert snapshot.event_count == 1
    assert snapshot.censored_event_count == 1
    assert detector.get_events()[0].completion == EventCompletion.CENSORED_STOP


def test_both_polarity_direct_reversal_is_one_bipolar_excursion():
    detector = make_detector(polarity=EventPolarity.BOTH)

    detector.process(np.array([0.0, 0.6, -0.8, 0.0]))

    event = detector.get_events()[0]
    assert detector.snapshot().event_count == 1
    assert event.trigger_polarity == EventPolarity.POSITIVE
    assert event.peak_polarity == EventPolarity.NEGATIVE
    assert event.positive_peak == pytest.approx(0.6)
    assert event.negative_peak == pytest.approx(-0.8)
    assert event.peak == pytest.approx(-0.8)


def test_unobserved_opposite_polarity_peak_is_none():
    detector = make_detector(polarity=EventPolarity.BOTH)
    detector.process(np.array([0.0, 0.6, 0.3]))

    event = detector.get_events()[0]
    assert event.positive_peak == pytest.approx(0.6)
    assert event.negative_peak is None


def test_record_retention_limit_is_reported():
    detector = EventDetectorCore(
        DetectorConfig(sample_rate=1000, threshold=0.5, hysteresis=0.1),
        max_records=2,
    )
    detector.start()
    detector.process(np.array([0.0, 0.6, 0.3, 0.6, 0.3, 0.6, 0.3]))

    snapshot = detector.snapshot()
    assert snapshot.event_count == 3
    assert snapshot.retained_event_count == 2
    assert snapshot.dropped_record_count == 1
    assert not snapshot.measurement_valid
