import numpy as np
from src.gui.widgets.oscilloscope import fast_histogram2d

def test_fast_histogram2d_basic():
    # Setup
    N = 1000
    t = np.linspace(0, 1.0, N)
    y = np.sin(2 * np.pi * 5 * t)

    w, h = 50, 40
    rng = [[0, 1.0], [-1.1, 1.1]]

    # Expected
    expected, _, _ = np.histogram2d(t, y, bins=[w, h], range=rng)

    # Actual
    actual = fast_histogram2d(t, y, bins=[w, h], range=rng)

    assert actual.shape == (w, h)
    assert np.array_equal(actual, expected)

def test_fast_histogram2d_with_outliers():
    # Points outside range should be ignored
    t = np.array([0.5, 1.5, -0.5]) # 1.5 and -0.5 are outside [0, 1.0]
    y = np.array([0.0, 0.0, 0.0])

    w, h = 10, 10
    rng = [[0, 1.0], [-1.0, 1.0]]

    expected, _, _ = np.histogram2d(t, y, bins=[w, h], range=rng)
    actual = fast_histogram2d(t, y, bins=[w, h], range=rng)

    assert np.array_equal(actual, expected)
    # Only middle point should be counted
    assert np.sum(actual) == 1

def test_fast_histogram2d_empty():
    t = np.array([])
    y = np.array([])

    w, h = 10, 10
    rng = [[0, 1.0], [-1.0, 1.0]]

    expected, _, _ = np.histogram2d(t, y, bins=[w, h], range=rng)
    actual = fast_histogram2d(t, y, bins=[w, h], range=rng)

    assert np.array_equal(actual, expected)
    assert np.sum(actual) == 0

def test_fast_histogram2d_edge_cases():
    # Points exactly on boundary
    # histogram2d: "All but the last (righthand-most) bin is half-open."
    # [min, max). Last bin is [min, max].

    t = np.array([0.0, 1.0])
    y = np.array([-1.0, 1.0])

    w, h = 2, 2
    rng = [[0, 1.0], [-1.0, 1.0]]

    # Bin edges X: [0, 0.5), [0.5, 1.0]
    # Bin edges Y: [-1.0, 0.0), [0.0, 1.0]

    expected, _, _ = np.histogram2d(t, y, bins=[w, h], range=rng)
    actual = fast_histogram2d(t, y, bins=[w, h], range=rng)

    # Note: My implementation uses floor(normalized * N).
    # For 1.0, (1.0 - 0)/(1-0) * 2 = 2. Index 2 is OOB (bins 0, 1).
    # np.histogram2d puts max value in last bin.
    # My simple implementation might discard it if it falls into index N.
    # Let's see if they match.

    # If they don't match, I might need to clamp the max value into the last bin.
    # But let's check first.

    assert np.array_equal(actual, expected)

def test_fast_histogram2d_random():
    np.random.seed(42)
    N = 10000
    t = np.random.uniform(0, 1.0, N)
    y = np.random.uniform(-1.0, 1.0, N)

    # Add some OOB
    t = np.append(t, [1.1, -0.1])
    y = np.append(y, [1.1, -1.1])

    w, h = 100, 80
    rng = [[0, 1.0], [-1.0, 1.0]]

    expected, _, _ = np.histogram2d(t, y, bins=[w, h], range=rng)
    actual = fast_histogram2d(t, y, bins=[w, h], range=rng)

    assert np.array_equal(actual, expected)
