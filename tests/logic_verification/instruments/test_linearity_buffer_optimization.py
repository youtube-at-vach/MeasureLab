import sys
import numpy as np
from unittest.mock import MagicMock

# Ensure sounddevice is mocked if not present
try:
    import sounddevice  # noqa: F401
except ImportError:
    sys.modules["sounddevice"] = MagicMock()

from src.gui.widgets.linearity_analyzer import LinearityAnalyzer


def test_linearity_analyzer_get_latest_buffer_into_correctness():
    """Verifies that get_latest_buffer_into returns the same data as get_latest_buffer."""
    # Setup
    mock_audio_engine = MagicMock()
    mock_audio_engine.sample_rate = 48000
    analyzer = LinearityAnalyzer(mock_audio_engine)

    # Configure buffer
    analyzer.buffer_size = 100
    analyzer.input_data = np.random.rand(analyzer.buffer_size, 2)
    # Set an arbitrary index to test wrapping
    analyzer.input_index = 37

    # Expected result using legacy method
    expected = analyzer.get_latest_buffer()

    # Actual result using new method
    out = np.zeros_like(analyzer.input_data)
    analyzer.get_latest_buffer_into(out)

    assert np.array_equal(out, expected), "get_latest_buffer_into result does not match get_latest_buffer"


def test_linearity_analyzer_get_latest_buffer_into_wrapping():
    """Verifies ring buffer wrapping logic specifically for the new method."""
    mock_audio_engine = MagicMock()
    analyzer = LinearityAnalyzer(mock_audio_engine)
    analyzer.buffer_size = 10
    analyzer.input_data = np.arange(20).reshape(10, 2)  # 0..19
    # If index is 3:
    # Buffer: [0, 1, 2, 3, 4, 5, 6, 7, 8, 9] (rows)
    # Oldest data starts at index 3: [3, 4, 5, 6, 7, 8, 9]
    # Newest data ends at index 3: [0, 1, 2]
    # Result should be: [3, 4, 5, 6, 7, 8, 9, 0, 1, 2]
    analyzer.input_index = 3

    out = np.zeros((10, 2))
    analyzer.get_latest_buffer_into(out)

    expected_part1 = analyzer.input_data[3:]
    expected_part2 = analyzer.input_data[:3]
    expected = np.concatenate((expected_part1, expected_part2))

    assert np.array_equal(out, expected)
