
import sys
import numpy as np
from unittest.mock import MagicMock
import pytest

# Ensure sounddevice is mocked if not present
try:
    import sounddevice
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

    # Check input_data
    # Expectation: input_data should be filled with duplicated mono data
    last_samples = analyzer.input_data[-frames:]

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
    last_samples = analyzer.input_data[-frames:]

    assert np.allclose(last_samples, stereo_data), "Stereo input was not preserved correctly"
