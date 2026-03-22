import sys
from unittest.mock import MagicMock

# Mock sounddevice before importing anything else that depends on it
mock_sd = MagicMock()
sys.modules["sounddevice"] = mock_sd

import unittest  # noqa: E402
import numpy as np  # noqa: E402

# Now we can safely import modules that use sounddevice
from src.gui.widgets.signal_generator import SignalGenerator  # noqa: E402
from src.core.audio_engine import AudioEngine  # noqa: E402


class TestSignalGeneratorUpdateBug(unittest.TestCase):
    def setUp(self):
        self.mock_engine = MagicMock(spec=AudioEngine)
        self.mock_engine.sample_rate = 48000
        # Need to ensure generator can import and use audio_engine without actual PortAudio
        self.generator = SignalGenerator(self.mock_engine)

    def test_noise_color_change_does_not_update_buffer_automatically(self):
        """
        Verify that changing noise_color via setattr (as UI does) fails to update the buffer.
        """
        params = self.generator.params_L
        params.waveform = "noise"
        params.noise_color = "white"

        # Initial buffer generation
        self.generator._prepare_buffer(params, 48000)
        initial_buffer = params._buffer.copy()

        # Change parameter
        self.generator.update_param(params, "noise_color", "pink")

        # Assert buffer IS changed
        with self.assertRaises(AssertionError):
            np.testing.assert_array_equal(params._buffer, initial_buffer)

    def test_multitone_count_change_bug(self):
        params = self.generator.params_L
        params.waveform = "multitone"
        params.multitone_count = 10
        params.start_freq = 100.0
        params.end_freq = 1000.0

        self.generator._prepare_buffer(params, 48000)
        initial_buffer = params._buffer.copy()

        self.generator.update_param(params, "multitone_count", 20)

        with self.assertRaises(AssertionError):
            np.testing.assert_array_equal(params._buffer, initial_buffer)
