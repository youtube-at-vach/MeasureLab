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

def test_linearity_analyzer_sine_generation():
    """
    Verifies that the LinearityAnalyzer callback generates a continuous sine wave
    with the correct frequency and amplitude, even across buffer boundaries.
    """
    # Setup
    audio_engine = AudioEngine()
    # Mock register_callback to capture the callback function
    callback_capture = []
    audio_engine.register_callback = MagicMock(side_effect=lambda cb: callback_capture.append(cb) or 123)
    audio_engine.sample_rate = 48000

    analyzer = LinearityAnalyzer(audio_engine)
    analyzer.test_frequency = 1000.0
    analyzer.gen_amplitude = 0.5
    analyzer.output_channel = 0 # Left

    # Start analysis to register callback
    analyzer.start_analysis()

    assert len(callback_capture) == 1
    callback = callback_capture[0]

    # Run callback multiple times to simulate streaming
    frames = 1024
    sample_rate = 48000
    total_chunks = 10

    full_signal = []

    indata = np.zeros((frames, 2), dtype=np.float32)
    outdata = np.zeros((frames, 2), dtype=np.float32)

    for _ in range(total_chunks):
        callback(indata, outdata, frames, None, None)
        # Capture Left channel output
        full_signal.append(outdata[:, 0].copy())

    full_signal = np.concatenate(full_signal)

    # Verification
    # 1. Amplitude
    max_amp = np.max(np.abs(full_signal))
    assert np.isclose(max_amp, 0.5, atol=1e-5), f"Amplitude mismatch: expected 0.5, got {max_amp}"

    # 2. Frequency and Continuity
    # Check against ideal sine wave
    t = np.arange(len(full_signal)) / sample_rate
    ideal_signal = 0.5 * np.sin(2 * np.pi * 1000.0 * t)

    # Cross-correlation or direct difference?
    # Since phase starts at 0, it should match exactly if implemented correctly.
    # Note: If my optimization changes phase tracking (e.g. slight float drift vs ideal float64 array),
    # there might be a tiny error, but for 10 chunks it should be negligible.

    # Let's check the first few chunks match exactly
    diff = np.abs(full_signal - ideal_signal)
    max_diff = np.max(diff)

    # Allow small epsilon for float32/float64 differences if any
    assert max_diff < 1e-4, f"Signal deviation from ideal sine wave: max diff {max_diff}"

    # Check specifically for discontinuity at buffer boundaries
    # Calculate phase difference between last sample of chunk N and first sample of chunk N+1
    # We expect smooth transition.

    # Actually, comparison with ideal signal covers continuity.
    # If there was a phase jump, the error would grow or jump.

if __name__ == "__main__":
    test_linearity_analyzer_sine_generation()
