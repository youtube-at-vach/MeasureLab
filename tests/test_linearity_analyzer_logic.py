
import sys
import numpy as np
from unittest.mock import MagicMock

# Ensure sounddevice is mocked if not present
try:
    import sounddevice # noqa: F401
except ImportError:
    sys.modules["sounddevice"] = MagicMock()

from src.gui.widgets.linearity_analyzer import LinearityAnalyzer
from src.core.audio_engine import AudioEngine

def test_linearity_analyzer_mono_input():
    """Verifies that mono input is correctly duplicated to stereo in the input buffer."""
    # Setup
    audio_engine = AudioEngine()
    audio_engine.register_callback = MagicMock(side_effect=lambda cb: 1)

    analyzer = LinearityAnalyzer(audio_engine)
    analyzer.start_analysis()

    args = audio_engine.register_callback.call_args[0]
    callback_func = args[0]

    # Create mono data (N, 1)
    frames = 100
    val = 0.5
    mono_data = np.ones((frames, 1), dtype=np.float32) * val
    out_data = np.zeros((frames, 2), dtype=np.float32)

    # Call callback
    callback_func(mono_data, out_data, frames, 0, 0)

    # Check input_data using the new accessor
    # Expectation: input_data should be filled with duplicated mono data
    # get_latest_buffer returns ordered data. Since we only pushed 100 frames into a zero buffer,
    # the last 100 frames should be our data.
    buffer = analyzer.get_latest_buffer()
    last_samples = buffer[-frames:]

    assert not np.all(last_samples == 0), "Mono input resulted in all-zeros buffer"
    assert np.allclose(last_samples[:, 0], val), "Left channel not matching mono input"
    assert np.allclose(last_samples[:, 1], val), "Right channel not matching mono input"

def test_linearity_analyzer_stereo_input():
    """Verifies that stereo input is correctly mapped to the input buffer."""
    # Setup
    audio_engine = AudioEngine()
    audio_engine.register_callback = MagicMock(side_effect=lambda cb: 1)

    analyzer = LinearityAnalyzer(audio_engine)
    analyzer.start_analysis()

    args = audio_engine.register_callback.call_args[0]
    callback_func = args[0]

    # Create stereo data (N, 2)
    frames = 100
    stereo_data = np.zeros((frames, 2), dtype=np.float32)
    stereo_data[:, 0] = 0.8 # Left
    stereo_data[:, 1] = 0.3 # Right
    out_data = np.zeros((frames, 2), dtype=np.float32)

    # Call callback
    callback_func(stereo_data, out_data, frames, 0, 0)

    # Check input_data
    buffer = analyzer.get_latest_buffer()
    last_samples = buffer[-frames:]

    assert np.allclose(last_samples, stereo_data), "Stereo input was not preserved correctly"

def test_linearity_analyzer_ring_buffer_wrap():
    """Verifies that the ring buffer logic correctly handles wrapping around."""
    # Setup
    audio_engine = AudioEngine()
    audio_engine.register_callback = MagicMock(side_effect=lambda cb: 1)

    analyzer = LinearityAnalyzer(audio_engine)
    # Manually resize buffer for easy testing
    analyzer.buffer_size = 100
    analyzer.input_data = np.zeros((analyzer.buffer_size, 2))
    analyzer.start_analysis()

    args = audio_engine.register_callback.call_args[0]
    callback_func = args[0]

    # 1. Fill first 60 frames (Index becomes 60)
    data1 = np.ones((60, 2), dtype=np.float32) * 1.0
    out_data = np.zeros((60, 2), dtype=np.float32)
    callback_func(data1, out_data, 60, 0, 0)

    # 2. Fill next 60 frames (Should wrap: 40 at end, 20 at start. Index becomes 20)
    data2 = np.ones((60, 2), dtype=np.float32) * 2.0
    callback_func(data2, out_data, 60, 0, 0)

    # Check
    buffer = analyzer.get_latest_buffer()

    # The buffer should contain last 100 samples.
    # Total sent: 120 samples.
    # Expected: last 40 of data1 (val=1.0) and all 60 of data2 (val=2.0)
    # buffer[0:40] should be 1.0
    # buffer[40:100] should be 2.0

    assert np.allclose(buffer[:40], 1.0), "First part of buffer (history) is incorrect"
    assert np.allclose(buffer[40:], 2.0), "Second part of buffer (latest) is incorrect"
