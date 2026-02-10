import os
import sys
from unittest.mock import MagicMock

import numpy as np

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

# Mock sounddevice before importing anything that uses it
sys.modules['sounddevice'] = MagicMock()

# Now import SignalGenerator
from src.gui.widgets.signal_generator import SignalGenerator  # noqa: E402


def test_independent_channels():
    # Mock AudioEngine
    mock_engine = MagicMock()
    mock_engine.sample_rate = 48000
    mock_engine.calibration.output_gain = 1.0

    sg = SignalGenerator(mock_engine)

    # Configure L: Sine 1000Hz
    sg.params_L.waveform = 'sine'
    sg.params_L.frequency = 1000.0
    sg.params_L.amplitude = 1.0

    # Configure R: Square 500Hz
    sg.params_R.waveform = 'square'
    sg.params_R.frequency = 500.0
    sg.params_R.amplitude = 0.5

    # Start generation
    sg.start_generation()

    # Simulate callback
    frames = 480
    outdata = np.zeros((frames, 2))

    # We need to access the callback that was registered
    # In the code: self.callback_id = self.audio_engine.register_callback(callback)
    # We can inspect the mock to get the callback
    args, _ = mock_engine.register_callback.call_args
    callback = args[0]

    callback(None, outdata, frames, None, None)

    # Analyze output
    sig_l = outdata[:, 0]
    sig_r = outdata[:, 1]

    # Check L (Sine)
    t = np.arange(frames) / 48000
    expected_l = np.sin(2 * np.pi * 1000 * t)

    # Check R (Square)
    expected_r = 0.5 * np.sign(np.sin(2 * np.pi * 500 * t))

    # Verify
    np.testing.assert_allclose(sig_l, expected_l, atol=1e-5, err_msg="Left Channel (Sine 1000Hz) mismatch")
    np.testing.assert_allclose(sig_r, expected_r, atol=1e-5, err_msg="Right Channel (Square 500Hz) mismatch")

    # Test Output Routing
    sg.output_mode = 'L'
    outdata.fill(0)
    callback(None, outdata, frames, None, None)
    assert np.all(outdata[:, 1] == 0), "Routing L: Right channel should be silent"
    assert not np.all(outdata[:, 0] == 0), "Routing L: Left channel should have signal"

    sg.output_mode = 'R'
    outdata.fill(0)
    callback(None, outdata, frames, None, None)
    assert np.all(outdata[:, 0] == 0), "Routing R: Left channel should be silent"
    assert not np.all(outdata[:, 1] == 0), "Routing R: Right channel should have signal"

if __name__ == "__main__":
    test_independent_channels()
