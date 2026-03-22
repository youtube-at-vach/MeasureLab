import sys
import numpy as np
from unittest.mock import MagicMock, patch

# Ensure sounddevice is mocked if not present
try:
    import sounddevice  # noqa: F401
except ImportError:
    sys.modules["sounddevice"] = MagicMock()

from src.gui.widgets.linearity_analyzer import LinearityAnalyzer, calculate_hysteresis, LinearitySweepWorker
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
    stereo_data[:, 0] = 0.8  # Left
    stereo_data[:, 1] = 0.3  # Right
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


def test_calculate_hysteresis_standard():
    """Verifies that the hysteresis calculation is correct and robust."""
    # Setup synthetic results
    # Forward sweep: 0 to -10 dB
    x_fwd = np.linspace(0, -10, 11)  # 0, -1, ..., -10
    g_fwd = np.zeros_like(x_fwd)  # Gain 0

    # Reverse sweep: -10 to 0 dB
    x_rev = x_fwd[::-1]
    g_rev = np.zeros_like(x_rev)

    # Add hysteresis: at -5dB, gain is 1.0 in reverse (diff = 1.0)
    # x_rev is [-10, -9, ..., -5, ..., 0]
    # index 5 is -5.0
    g_rev[5] = 1.0

    directions = ["fwd"] * len(x_fwd) + ["rev"] * len(x_rev)
    x_data = list(np.concatenate((x_fwd, x_rev)))
    gain_data = list(np.concatenate((g_fwd, g_rev)))

    hyst = calculate_hysteresis(x_data, gain_data, directions)

    # Should be 1.000 dB
    assert abs(hyst - 1.0) < 1e-6


def test_calculate_hysteresis_no_match():
    """Verifies behavior when fwd and rev sweeps don't match exactly (but close)."""
    # Fwd: [0, -1]
    # Rev: [-1.0000001, 0] (should match due to rounding)

    x_fwd = [0.0, -1.0]
    g_fwd = [0.0, 0.0]

    x_rev = [-1.0000001, 0.0]
    g_rev = [0.5, 0.0]  # 0.5 diff at -1.0

    x_data = x_fwd + x_rev
    gain_data = g_fwd + g_rev
    directions = ["fwd"] * 2 + ["rev"] * 2

    hyst = calculate_hysteresis(x_data, gain_data, directions)

    # Should find the 0.5 diff
    assert abs(hyst - 0.5) < 1e-6


def test_calculate_hysteresis_disjoint():
    """Verifies behavior when sweeps are disjoint."""
    x_fwd = [0.0, -1.0]
    g_fwd = [0.0, 0.0]

    x_rev = [-2.0, -3.0]  # No overlap
    g_rev = [0.5, 0.5]

    x_data = x_fwd + x_rev
    gain_data = g_fwd + g_rev
    directions = ["fwd"] * 2 + ["rev"] * 2

    hyst = calculate_hysteresis(x_data, gain_data, directions)

    # Should be 0.000 dB (or 0.0 returned as float)
    assert hyst == 0.0


def test_calculate_hysteresis_duplicates():
    """Verifies that duplicate handling mimics 'Last-Win' for Fwd and 'Check-All' for Rev."""
    # 1. Forward Sweep Duplicates (Last-Win)
    # x: 0, 0 (first has gain 10, second has gain 20)
    # Dictionary logic would overwrite 10 with 20.
    x_fwd = [0.0, 0.0]
    g_fwd = [10.0, 20.0]

    # 2. Reverse Sweep Duplicates (Check-All)
    # x: 0, 0 (first has gain 25, second has gain 22)
    # Should compare both against the "Last" forward gain (20).
    # Diff 1: |25 - 20| = 5.0
    # Diff 2: |22 - 20| = 2.0
    # Max hysteresis should be 5.0.

    x_rev = [0.0, 0.0]
    g_rev = [25.0, 22.0]

    # Add a stabilizing point to avoid polyfit error (not needed here but good for structure)
    x_fwd = [-100.0] + x_fwd
    g_fwd = [0.0] + g_fwd
    x_rev = [-100.0] + x_rev
    g_rev = [0.0] + g_rev

    x_data = x_fwd + x_rev
    gain_data = g_fwd + g_rev
    directions = ["fwd"] * len(x_fwd) + ["rev"] * len(x_rev)

    hyst = calculate_hysteresis(x_data, gain_data, directions)

    # Should be 5.000 dB exactly
    assert abs(hyst - 5.0) < 1e-6


def test_calculate_hysteresis_empty_fwd():
    """Verifies robustness when forward sweep is missing."""
    x_rev = [0.0, -1.0]
    g_rev = [10.0, 20.0]

    x_data = x_rev
    gain_data = g_rev
    directions = ["rev"] * 2

    # Logic: if "rev" in dirs... but x_fwd is empty.
    # The function splits by mask. x_fwd will be empty.
    # xf_clean size will be 0.
    # max_hyst should be 0.0 (or None returned? No, logic returns 0.0 if xf_clean is empty)

    hyst = calculate_hysteresis(x_data, gain_data, directions)

    assert hyst == 0.0


def test_snr_calculation_on_silence():
    """
    Verifies that SNR calculation handles silence (mag=0) gracefully
    without producing -inf or raising warnings, by returning a low finite value.
    """
    # Mock Module and Engine
    mock_engine = MagicMock()
    mock_engine.sample_rate = 48000
    mock_module = MagicMock()
    mock_module.audio_engine = mock_engine
    mock_module.start_level = -10
    mock_module.end_level = -10
    mock_module.steps = 1
    mock_module.test_frequency = 1000
    mock_module.input_channel = 0
    mock_module.buffer_size = 1024
    mock_module.averaging_count = 1
    mock_module.hysteresis_mode = False

    # Mock input_data for zeros_like
    mock_module.input_data = np.zeros((1024, 2))

    # Mock get_latest_buffer_into to be a no-op (buffer remains zeros)
    mock_module.get_latest_buffer_into = MagicMock()

    # Instantiate Worker
    worker = LinearitySweepWorker(mock_module)

    # Mock AudioCalc to return 0 magnitude (silence)
    # We need to patch src.gui.widgets.linearity_analyzer.AudioCalc
    # because the module imports it.
    with patch("src.gui.widgets.linearity_analyzer.AudioCalc") as MockAudioCalc:
        # calculate_lockin_measurement returns (mag, phase)
        # First call is signal, Second call is noise
        # We want signal=0, noise=1e-9 (small but non-zero to avoid div/0 in noise check)

        # Side_effect to handle multiple calls
        def side_effect(*args, **kwargs):
            # Check frequency to distinguish signal vs noise measurement if needed
            # But simple sequence: 1. Sig, 2. Noise
            return 0.0, 0.0

        MockAudioCalc.calculate_lockin_measurement.side_effect = [
            (0.0, 0.0),  # Signal: Magnitude 0
            (1e-9, 0.0),  # Noise: Magnitude 1e-9
        ]

        # We capture the emitted result
        results = []
        worker.result_ready.connect(lambda res: results.append(res))

        # Run (synchronously for test, bypassing Thread.start)
        # We override sleep to speed up
        with patch("time.sleep", return_value=None):
            worker.run()

        assert len(results) > 0, "No results emitted"
        result = results[0]
        snr = result["snr"]

        print(f"Calculated SNR: {snr}")

        # Check for finite value
        assert np.isfinite(snr), f"SNR should be finite, got {snr}"

        # Check that it is not -inf
        # If mag=0 and we don't add epsilon, log10(0) is -inf.
        # If we add epsilon 1e-15, snr = 20*log10(1e-15 / 1e-9) = 20*log10(1e-6) = -120 dB.
        # If we didn't fix it, it would be -inf.
        assert snr > -200.0, "SNR should be reasonable (approx -120dB), not -inf"
