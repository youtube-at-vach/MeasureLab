
import os
import sys
from unittest.mock import MagicMock

# Mock sounddevice BEFORE importing any module that uses it

import numpy as np  # noqa: E402

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from src.gui.widgets.signal_generator import SignalGenerator  # noqa: E402


def reference_multitone(params, sample_rate):
    """Reference implementation using the slow loop method (original code)."""
    if params.start_freq >= params.end_freq:
        freqs = np.array([params.start_freq])
    else:
        freqs = np.logspace(np.log10(params.start_freq), np.log10(params.end_freq), params.multitone_count)

    N = int(sample_rate)
    bin_width = sample_rate / N
    freqs = np.round(freqs / bin_width) * bin_width

    phases = np.pi * (np.arange(len(freqs)) ** 2) / len(freqs)

    t = np.arange(N) / sample_rate
    signal = np.zeros(N)

    # Original loop implementation
    for f, p in zip(freqs, phases, strict=False):
        signal += np.sin(2 * np.pi * f * t + p)

    max_val = np.max(np.abs(signal))
    if max_val > 0:
        signal /= max_val

    return signal


def test_multitone_correctness():
    # Mock AudioEngine
    mock_engine = MagicMock()
    mock_engine.sample_rate = 48000
    mock_engine.calibration.output_gain = 1.0

    sg = SignalGenerator(mock_engine)

    # Configure parameters
    sg.params_L.waveform = 'multitone'
    sg.params_L.multitone_count = 31
    sg.params_L.start_freq = 20.0
    sg.params_L.end_freq = 20000.0

    # Generate using optimized method (IFFT)
    optimized_signal = sg._generate_multitone(sg.params_L, 48000)

    # Generate reference
    reference_signal = reference_multitone(sg.params_L, 48000)

    # Verify correctness
    # The logic is mathematically equivalent, diffs are float errors.
    assert np.allclose(optimized_signal, reference_signal, atol=1e-9), "Multitone output mismatch"

    max_diff = np.max(np.abs(optimized_signal - reference_signal))
    print(f"Max Diff (31 tones): {max_diff}")


def test_multitone_high_count():
    mock_engine = MagicMock()
    mock_engine.sample_rate = 48000
    sg = SignalGenerator(mock_engine)

    sg.params_L.multitone_count = 100
    sg.params_L.start_freq = 20.0
    sg.params_L.end_freq = 20000.0

    optimized_signal = sg._generate_multitone(sg.params_L, 48000)
    reference_signal = reference_multitone(sg.params_L, 48000)

    assert np.allclose(optimized_signal, reference_signal, atol=1e-9), "Multitone high count mismatch"
    max_diff = np.max(np.abs(optimized_signal - reference_signal))
    print(f"Max Diff (100 tones): {max_diff}")


def test_multitone_dc_nyquist_handling():
    """Test edge cases with manually constructed params to hit DC and Nyquist bins."""
    mock_engine = MagicMock()
    mock_engine.sample_rate = 100  # Low sample rate for easier manual check
    sg = SignalGenerator(mock_engine)

    # N = 100. Nyquist = 50 Hz.
    # Use 40 Hz and 50 Hz.
    # Count = 2.
    # This ensures 50Hz has non-zero phase (pi/2) -> non-zero signal.

    sg.params_L.multitone_count = 2
    sg.params_L.start_freq = 40.0
    sg.params_L.end_freq = 50.0

    optimized_signal = sg._generate_multitone(sg.params_L, 100)
    reference_signal = reference_multitone(sg.params_L, 100)

    assert np.allclose(optimized_signal, reference_signal, atol=1e-9), "Nyquist mismatch"
    max_diff = np.max(np.abs(optimized_signal - reference_signal))
    print(f"Max Diff (Nyquist test): {max_diff}")


def test_multitone_zero_count():
    """Test that zero tone count results in silence and no crash."""
    mock_engine = MagicMock()
    mock_engine.sample_rate = 48000
    sg = SignalGenerator(mock_engine)

    sg.params_L.multitone_count = 0
    sg.params_L.start_freq = 20.0
    sg.params_L.end_freq = 20000.0

    signal = sg._generate_multitone(sg.params_L, 48000)
    assert np.all(signal == 0), "Zero count should produce silence"


if __name__ == "__main__":
    try:
        test_multitone_correctness()
        test_multitone_high_count()
        test_multitone_dc_nyquist_handling()
        test_multitone_zero_count()
        print("All multitone tests passed!")
    except AssertionError as e:
        print(f"Test FAILED: {e}")
        sys.exit(1)
