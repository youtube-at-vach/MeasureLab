import numpy as np
import pytest

from src.core.output_impedance import LoadCapture, PairedLoadStudy, SweepConditions


CONDITIONS = SweepConditions(48000, 20, 20000, 2.0, 0.2, 2, "L", "XFER", 0, 1)
FREQUENCIES = np.array([100.0, 500.0, 1000.0, 5000.0])


def capture(load, source, *, gain=1 + 0j, conditions=CONDITIONS, coherence=0.99):
    transfer = gain * load / (source + load)
    return LoadCapture.create(load, FREQUENCIES, transfer, np.full(len(FREQUENCIES), coherence), conditions)


def test_recovers_complex_impedance_and_predicts_third_load():
    source = np.array([8 + 2j, 9 + 4j, 10 + 6j, 11 - 3j])
    study = PairedLoadStudy()
    for _ in range(2):
        study.add("A", capture(32.0, source, gain=1.2 - 0.3j))
        study.add("B", capture(100.0, source, gain=1.2 - 0.3j))

    result = study.calculate(300.0)
    assert np.all(result.numerically_valid)
    assert np.all(result.repeat_resolved)
    assert np.allclose(result.source_ohms, source)
    expected = 20 * np.log10(np.abs((300 / (source + 300)) / (32 / (source + 32))))
    assert np.allclose(result.predicted_difference_db, expected)


def test_small_load_difference_is_unresolved_against_repeat_scatter():
    source = np.full(len(FREQUENCIES), 0.01 + 0j)
    study = PairedLoadStudy()
    for gain in (0.99, 1.01):
        study.add("A", capture(32, source, gain=gain))
        study.add("B", capture(100, source, gain=gain))

    result = study.calculate(300)
    assert np.all(result.numerically_valid)
    assert not np.any(result.repeat_resolved)
    assert np.all(np.isfinite(result.difference_db))


def test_phase_scatter_also_prevents_false_resolution():
    source = np.full(len(FREQUENCIES), 0.01 + 0j)
    study = PairedLoadStudy()
    for phase in (-0.1, 0.1):
        study.add("A", capture(32, source, gain=np.exp(1j * phase)))
        study.add("B", capture(100, source, gain=np.exp(1j * phase)))

    result = study.calculate(300)
    assert not np.any(result.repeat_resolved)


def test_large_impedance_needs_resolved_denominator():
    source = np.full(len(FREQUENCIES), 1_000_000 + 0j)
    study = PairedLoadStudy()
    for gain in (0.9999, 1.0001):
        study.add("A", capture(32, source, gain=gain))
        study.add("B", capture(100, source, gain=gain))

    result = study.calculate(300)
    assert np.all(result.numerically_valid)
    assert np.allclose(result.source_ohms, source)
    assert not np.any(result.repeat_resolved)


def test_single_pair_remains_provisional_and_marks_low_coherence():
    source = np.full(len(FREQUENCIES), 5 + 0j)
    study = PairedLoadStudy()
    study.add("A", capture(32, source))
    study.add("B", capture(100, source, coherence=0.5))

    result = study.calculate(300)
    assert not result.repeat_available
    assert not np.any(result.repeat_resolved)
    assert np.all(result.low_coherence)
    assert np.allclose(result.source_ohms, source)


def test_rejects_incompatible_or_invalid_captures_without_mutating_study():
    source = np.full(len(FREQUENCIES), 5 + 0j)
    study = PairedLoadStudy()
    first = capture(32, source)
    study.add("A", first)
    with pytest.raises(ValueError, match="different load"):
        study.add("B", capture(32, source))
    changed = SweepConditions(44100, 20, 20000, 2.0, 0.2, 2, "L", "XFER", 0, 1)
    with pytest.raises(ValueError, match="settings"):
        study.add("B", capture(100, source, conditions=changed))
    assert len(study.a) == 1 and not study.b
    with pytest.raises(ValueError, match="read-only"):
        first.transfer[0] = 0
    with pytest.raises(ValueError, match="positive"):
        capture(0, source)
