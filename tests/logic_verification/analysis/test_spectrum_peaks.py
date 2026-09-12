import numpy as np
import pytest

from src.core.spectrum_peaks import MAX_PEAK_MARKERS, detect_spectrum_peaks


def test_prominence_floor_and_hz_spacing_select_strongest():
    f = np.arange(9) * 10.0
    y = np.array([-100, -30, -100, -20, -100, -80, -100, -95, -100.0])
    assert detect_spectrum_peaks(f, y, 6, 25, -90) == [(30.0, -20.0)]
    assert detect_spectrum_peaks(f, y, 6, 20, -90) == [(30.0, -20.0), (10.0, -30.0), (50.0, -80.0)]
    assert detect_spectrum_peaks(f, y, 75, 0, -90) == [(30.0, -20.0)]


def test_flat_endpoint_and_plateau_behavior():
    assert detect_spectrum_peaks(np.arange(10), np.zeros(10)) == []
    assert detect_spectrum_peaks(np.arange(5), [0, -100, -100, -100, 0]) == []
    assert detect_spectrum_peaks(np.arange(5), [-100, -20, -20, -20, -100]) == [(2.0, -20.0)]


@pytest.mark.parametrize("invalid", [np.nan, np.inf, -np.inf])
def test_nonfinite_points_do_not_become_peaks_or_prominence_bases(invalid):
    assert detect_spectrum_peaks(np.arange(5), [-100, invalid, -10, -100, -100]) == []
    peaks = detect_spectrum_peaks(np.arange(9), [-100, invalid, -100, -100, -20, -100, -100, -100, -100])
    assert peaks == [(4.0, -20.0)]


@pytest.mark.parametrize(
    "f,y",
    [
        ([], []),
        ([1, 2], [0, 1]),
        ([1, 2, 3], [1]),
        ([1, np.nan, 3], [-100, -20, -100]),
        ([3, 2, 1], [-100, -20, -100]),
        ([1, 2, 3], [[0], [1], [0]]),
    ],
)
def test_invalid_shapes_or_frequencies_return_no_peaks(f, y):
    assert detect_spectrum_peaks(f, y) == []


@pytest.mark.parametrize("kwargs", [dict(prominence=np.nan), dict(spacing_hz=-1), dict(noise_floor=np.inf)])
def test_invalid_settings(kwargs):
    assert detect_spectrum_peaks(np.arange(5), [-100, -20, -100, -30, -100], **kwargs) == []


def test_display_envelope_uses_maxima_without_artificial_min_max_peaks():
    f = np.repeat([100, 200, 300, 400, 500], 2)
    y = [-110, -100, -100, -20, -110, -100, -105, -95, -110, -100]
    assert detect_spectrum_peaks(f, y) == [(200.0, -20.0)]


def test_noisy_large_spectrum_is_bounded_and_deterministic():
    f = np.arange(100001, dtype=float)
    y = np.full(len(f), -100.0)
    y[1::2] = -20
    first = detect_spectrum_peaks(f, y, spacing_hz=0)
    assert len(first) == MAX_PEAK_MARKERS
    assert first == detect_spectrum_peaks(f, y, spacing_hz=0)


def test_local_prominence_does_not_scan_an_unbounded_basin():
    f = np.arange(10001)
    y = -100 + 80 * np.maximum(0, 1 - abs(f - 5000) / 5000)
    assert detect_spectrum_peaks(f, y, prominence=30) == []
    assert detect_spectrum_peaks(f, y, prominence=10) == [(5000.0, -20.0)]


def test_out_of_view_strong_peaks_cannot_consume_visible_marker_budget():
    f = np.arange(31, dtype=float)
    y = np.full(31, -100.0)
    y[1:16:2] = -10
    y[21] = -40
    assert detect_spectrum_peaks(f, y, spacing_hz=0, frequency_range=(20, 30)) == [(21.0, -40.0)]
    assert detect_spectrum_peaks(f, y, spacing_hz=0, level_range=(-90, -20)) == [(21.0, -40.0)]


@pytest.mark.parametrize("prominence", [0, 6, 40, 79, 81])
@pytest.mark.parametrize("kind", ["noise", "comb", "ramp"])
def test_optimized_selection_matches_full_scipy_prominence(prominence, kind):
    from scipy.signal import find_peaks
    from src.core.spectrum_peaks import PROMINENCE_WINDOW

    f = np.arange(10001, dtype=float) * 0.73
    y = np.random.default_rng(24).uniform(-100, -20, len(f))
    if kind == "comb":
        y[:] = -100
        y[1::2] = -20
    elif kind == "ramp":
        y = np.linspace(-100, -20, len(f)) + 0.3 * np.sin(f)
    indices, _ = find_peaks(y, height=-90, prominence=prominence, wlen=PROMINENCE_WINDOW)
    remaining = sorted(indices, key=lambda i: (-y[i], i))
    expected = []
    for i in remaining:
        if all(abs(f[i] - hz) >= 100 for hz, _ in expected):
            expected.append((f[i], y[i]))
            if len(expected) == MAX_PEAK_MARKERS:
                break
    assert detect_spectrum_peaks(f, y, prominence=prominence) == expected
