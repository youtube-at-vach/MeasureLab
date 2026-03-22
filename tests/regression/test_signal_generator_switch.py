import unittest
import numpy as np
import sys
import os
from unittest.mock import MagicMock

# Mock sounddevice before importing anything that uses it
sys.modules["sounddevice"] = MagicMock()

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.gui.widgets.signal_generator import SignalGenerator  # noqa: E402


class TestSignalGeneratorBug(unittest.TestCase):
    def setUp(self):
        self.mock_engine = MagicMock()
        self.mock_engine.sample_rate = 48000
        self.mock_engine.calibration.output_gain = 1.0
        self.sg = SignalGenerator(self.mock_engine)

    def test_waveform_change_during_playback_sine_to_noise(self):
        # 1. Start with Sine
        self.sg.params_L.waveform = "sine"
        self.sg.params_L.frequency = 1000.0
        self.sg.start_generation()

        # Get callback
        args, _ = self.mock_engine.register_callback.call_args
        callback = args[0]

        # 2. Check output is Sine
        frames = 480
        outdata = np.zeros((frames, 2))
        callback(None, outdata, frames, None, None)

        # Verify it's not silent and looks like sine (simple check)
        self.assertFalse(np.all(outdata[:, 0] == 0))
        # Sine peak should be close to amplitude (0.5 default)
        self.assertAlmostEqual(np.max(np.abs(outdata[:, 0])), 0.5, delta=0.1)

        # 3. Change to Noise during playback
        # Simulate what UI does: use update_waveform
        self.sg.update_waveform(self.sg.params_L, "noise", 48000)

        # 4. Check output
        outdata.fill(0)
        callback(None, outdata, frames, None, None)

        # Expected: Noise (random)

        # Check if silent
        is_silent = np.all(outdata[:, 0] == 0)

        # If it's silent, that's a bug (user expects noise).
        self.assertFalse(is_silent, "Output should not be silent after switching to Noise")

    def test_waveform_change_during_playback_noise_to_sine(self):
        # 1. Start with Noise
        # Use update_waveform to ensure buffer is prepared (simulating correct usage)
        self.sg.update_waveform(self.sg.params_L, "noise", 48000)
        self.sg.start_generation()

        # Buffer should be generated
        self.assertIsNotNone(self.sg.params_L._buffer)

        args, _ = self.mock_engine.register_callback.call_args
        callback = args[0]

        # 2. Verify Noise
        frames = 480
        outdata = np.zeros((frames, 2))
        callback(None, outdata, frames, None, None)
        self.assertFalse(np.all(outdata[:, 0] == 0))

        # 3. Switch to Sine
        self.sg.update_waveform(self.sg.params_L, "sine", 48000)

        # 4. Check output
        outdata.fill(0)
        callback(None, outdata, frames, None, None)

        # Expected: Sine
        # Check if buffer is still being used

        # Easy check: if _buffer is None, buffer is cleared.
        self.assertIsNone(self.sg.params_L._buffer, "Buffer should be cleared after switching to Sine")


if __name__ == "__main__":
    unittest.main()
