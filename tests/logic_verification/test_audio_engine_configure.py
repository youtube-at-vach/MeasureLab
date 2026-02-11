import unittest
from unittest.mock import MagicMock
import sys

# Mock sounddevice and numpy before importing AudioEngine
sys.modules['sounddevice'] = MagicMock()
sys.modules['numpy'] = MagicMock()

from src.core.audio_engine import AudioEngine, _NOT_SET  # noqa: E402

class TestAudioEngineConfigure(unittest.TestCase):
    def setUp(self):
        # We need to recreate AudioEngine for each test or just use one
        # AudioEngine uses logging, so we mock it
        self.engine = AudioEngine()
        self.engine.stream = MagicMock() # Mock stream
        self.engine.stream.active = False # Default inactive
        self.engine.logger = MagicMock()
        self.engine._restart_stream = MagicMock()

        # Set initial state
        self.engine.input_device = 1
        self.engine.output_device = 2
        self.engine.sample_rate = 44100
        self.engine.block_size = 512
        self.engine.input_channel_mode = "stereo"
        self.engine.output_channel_mode = "stereo"

    def test_configure_updates_attributes(self):
        self.engine.configure(
            input_device=10,
            output_device=20,
            sample_rate=48000,
            block_size=1024,
            input_channel_mode="left",
            output_channel_mode="right"
        )

        self.assertEqual(self.engine.input_device, 10)
        self.assertEqual(self.engine.output_device, 20)
        self.assertEqual(self.engine.sample_rate, 48000)
        self.assertEqual(self.engine.block_size, 1024)
        self.assertEqual(self.engine.input_channel_mode, "left")
        self.assertEqual(self.engine.output_channel_mode, "right")

    def test_configure_no_restart_if_inactive(self):
        self.engine.stream = None # Inactive

        self.engine.configure(sample_rate=96000)

        self.assertEqual(self.engine.sample_rate, 96000)
        self.engine._restart_stream.assert_not_called()

    def test_configure_restarts_if_active_and_changed(self):
        self.engine.stream.active = True

        self.engine.configure(sample_rate=96000)

        self.assertEqual(self.engine.sample_rate, 96000)
        self.engine._restart_stream.assert_called_once()

    def test_configure_no_restart_if_active_but_unchanged(self):
        self.engine.stream.active = True

        # Configure with same values
        self.engine.configure(
            input_device=1,
            sample_rate=44100
        )

        self.engine._restart_stream.assert_not_called()

    def test_configure_handles_none_device(self):
        # Initial state is 1 (from setUp)

        # 1. Set to None (changed) -> expect update
        self.engine.configure(input_device=None)
        self.assertIsNone(self.engine.input_device)

        # If we were active, it would trigger restart. Let's verify that.
        self.engine.stream.active = True
        self.engine.input_device = 1 # Reset to non-None
        self.engine._restart_stream.reset_mock()

        self.engine.configure(input_device=None)
        self.engine._restart_stream.assert_called_once()

        # 2. Set to None again (unchanged) -> expect no restart
        self.engine._restart_stream.reset_mock()
        self.engine.configure(input_device=None)
        self.engine._restart_stream.assert_not_called()

    def test_configure_ignores_not_set(self):
        self.engine.stream.active = True
        self.engine._restart_stream.reset_mock()

        # Call with no args
        self.engine.configure()
        self.engine._restart_stream.assert_not_called()

        # Explicit _NOT_SET
        self.engine.configure(sample_rate=_NOT_SET)
        self.engine._restart_stream.assert_not_called()

if __name__ == '__main__':
    unittest.main()
