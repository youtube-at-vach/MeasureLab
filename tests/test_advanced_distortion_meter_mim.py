
import os
import sys
from unittest.mock import MagicMock, patch

# Mock sounddevice BEFORE importing any module that uses it
sys.modules['sounddevice'] = MagicMock()

import numpy as np  # noqa: E402

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.gui.widgets.advanced_distortion_meter import AdvancedDistortionMeter  # noqa: E402


def reference_mim(module, frames, sample_rate, fixed_phases):
    """Reference loop implementation for MIM generation."""
    bin_width = sample_rate / frames
    raw_freqs = np.logspace(np.log10(module.mim_min_freq), np.log10(module.mim_max_freq), module.mim_tone_count)
    mim_freqs = np.round(raw_freqs / bin_width) * bin_width

    phases = fixed_phases
    amp_per_tone = module.gen_amplitude / np.sqrt(module.mim_tone_count)

    signal = np.zeros(frames)
    t = np.arange(frames) / sample_rate

    for i, f in enumerate(mim_freqs):
        signal += amp_per_tone * np.sin(2 * np.pi * f * t + phases[i])

    return signal


def test_mim_generation_correctness():
    mock_engine = MagicMock()
    mock_engine.sample_rate = 48000
    mock_engine.calibration.output_gain = 1.0

    adm = AdvancedDistortionMeter(mock_engine)
    adm.mim_tone_count = 31
    adm.mim_min_freq = 20.0
    adm.mim_max_freq = 20000.0
    adm.gen_amplitude = 1.0  # Linear

    frames = 65536
    sample_rate = 48000

    # Fix phases
    fixed_phases = np.linspace(0, np.pi, adm.mim_tone_count)

    # Run optimized version
    # We need to mock np.random.uniform to return our fixed phases
    # The code calls np.random.uniform(0, 2*pi, count)
    with patch('numpy.random.uniform', return_value=fixed_phases):
        optimized_signal = adm._generate_mim(frames, sample_rate)

    # Run reference version
    reference_signal = reference_mim(adm, frames, sample_rate, fixed_phases)

    # Verify
    assert np.allclose(optimized_signal, reference_signal, atol=1e-9), "MIM output mismatch"
    max_diff = np.max(np.abs(optimized_signal - reference_signal))
    print(f"MIM Max Diff: {max_diff}")


def test_mim_zero_count():
    """Test that zero tone count results in silence and no crash."""
    mock_engine = MagicMock()
    mock_engine.sample_rate = 48000
    adm = AdvancedDistortionMeter(mock_engine)
    adm.mim_tone_count = 0

    signal = adm._generate_mim(65536, 48000)
    assert np.all(signal == 0), "Zero count should produce silence"


if __name__ == "__main__":
    try:
        test_mim_generation_correctness()
        test_mim_zero_count()
        print("All MIM tests passed!")
    except AssertionError as e:
        print(f"Test FAILED: {e}")
        sys.exit(1)
