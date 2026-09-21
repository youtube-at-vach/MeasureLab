import numpy as np
import pytest

from src.core.sound_level import ImpulseTimeWeighting, LevelHistory


@pytest.mark.parametrize("sample_rate", [44100, 48000])
def test_history_samples_every_boundary_across_arbitrary_blocks(sample_rate):
    period = sample_rate // 10
    powers = np.arange(sample_rate + 57, dtype=float)
    history = LevelHistory(sample_rate)
    for block in np.array_split(powers, 131):
        history.append(block)
    np.testing.assert_array_equal(history.snapshot().powers, powers[period - 1 :: period])
    assert history.position == len(powers)


def test_wrapped_history_and_detached_snapshot():
    history = LevelHistory(100, capacity=3)
    history.append(np.repeat([1e-6, 1e-5, 1e-4], 10))
    original = history.snapshot()
    assert original.statistics["L50"] == pytest.approx(-50, abs=0.001)
    history.append(np.repeat([0.01, 0.1], 10))
    wrapped = history.snapshot()
    np.testing.assert_allclose(np.sort(wrapped.powers), [1e-4, 0.01, 0.1])
    assert wrapped.statistics["L50"] == pytest.approx(-20, abs=0.001)
    assert wrapped.revision != original.revision
    assert original.statistics["L50"] == pytest.approx(-50, abs=0.001)
    with pytest.raises(ValueError):
        original.powers[0] = 1
    history.append(np.repeat([0.2, 0.3, 0.4, 0.5, 0.6], 10))
    np.testing.assert_allclose(history.snapshot().powers, [0.4, 0.5, 0.6])


def test_exceedance_percentiles_energy_average_and_histogram_agree():
    history = LevelHistory(100)
    levels = np.linspace(-80, -20, 101)
    powers = 10 ** (levels / 10)
    history.append(np.repeat(powers, 10))
    snapshot = history.snapshot()
    for name, expected in [("L5", -23), ("L10", -26), ("L50", -50), ("L90", -74), ("L95", -77)]:
        assert snapshot.statistics[name] == pytest.approx(expected, abs=0.001)
    assert snapshot.statistics["Lave"] == pytest.approx(10 * np.log10(np.mean(powers)), abs=0.001)
    _, probabilities = snapshot.histogram()
    assert probabilities.sum() == pytest.approx(100)


@pytest.mark.parametrize("sample_rate", [44100, 48000])
def test_impulse_response_survives_partial_blocks(sample_rate):
    powers = np.random.default_rng(72).random(10003) ** 2
    powers[19:150] = 0
    reference = ImpulseTimeWeighting().process(powers, sample_rate)
    detector = ImpulseTimeWeighting()
    actual = np.concatenate([detector.process(block, sample_rate) for block in np.array_split(powers, 213)])
    np.testing.assert_array_equal(actual, reference)
    assert actual[0] == pytest.approx(powers[0] * (1 - np.exp(-1 / (sample_rate * 0.035))))


@pytest.mark.parametrize("sample_rate", [44100, 48000])
def test_impulse_rise_and_fall_follow_time_constants(sample_rate):
    detector = ImpulseTimeWeighting()
    rise = detector.process(np.ones(sample_rate), sample_rate)
    t = np.arange(1, sample_rate + 1) / sample_rate
    np.testing.assert_allclose(rise, 1 - np.exp(-t / 0.035), atol=1e-12)
    fall = detector.process(np.zeros(sample_rate), sample_rate)
    np.testing.assert_allclose(fall, rise[-1] * np.exp(-t / 1.5), atol=1e-12)
