import pytest

from src.core.loudness_history import LoudnessHistory


def test_history_is_bounded_but_statistics_cover_the_session():
    history = LoudnessHistory(48000, 4800)
    history.append(19200, -60.0, None)
    old = history.snapshot(19200)
    for sample in range(24000, 1440001, 4800):
        history.append(sample, -20.0, -25.0 if sample >= 144000 else None)
    snapshot = history.snapshot(1440000)

    assert len(snapshot.points) == 201
    assert snapshot.points[0].sample == 480000
    assert snapshot.points[-1].sample == 1440000
    assert snapshot.momentary.count == 297
    assert snapshot.momentary.minimum == -60.0
    assert snapshot.momentary.maximum == -20.0
    assert snapshot.momentary.average == pytest.approx((-60.0 - 296 * 20.0) / 297)
    assert snapshot.short_term.count == 271
    assert snapshot.short_term.average == -25.0
    assert old.momentary.count == 1
    assert len(old.points) == 1
    # A partial acquisition interval must not extend the 20-second viewport.
    assert len(history.snapshot(1440001).points) == 200


def test_silence_is_visible_in_history_but_not_a_finite_statistic():
    history = LoudnessHistory(48000, 4800)
    history.append(19200, -100.0, None)
    history.append(24000, -20.0, None)
    history.append(28800, -40.0, None)
    result = history.snapshot(28800)
    assert result.points[0].momentary == -100.0
    assert result.momentary.count == 2
    assert result.momentary.average == -30.0
    assert result.short_term.count == 0
    assert result.short_term.average is None
