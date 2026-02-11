import unittest
from unittest.mock import MagicMock, patch
import sys
import importlib

class TestAudioEngineStartLogic(unittest.TestCase):
    def setUp(self):
        # Patch sys.modules to mock sounddevice
        self.patcher = patch.dict(sys.modules, {'sounddevice': MagicMock()})
        self.patcher.start()

        # Import and reload AudioEngine to use the mock
        import src.core.audio_engine
        importlib.reload(src.core.audio_engine)
        self.AudioEngineClass = src.core.audio_engine.AudioEngine

        self.engine = self.AudioEngineClass()
        # Mock logger to avoid clutter
        self.engine.logger = MagicMock()

    def tearDown(self):
        self.patcher.stop()

    def test_update_channel_modes_stereo(self):
        self.engine.input_channel_mode = "stereo"
        self.engine.output_channel_mode = "stereo"

        # Call the method
        hw_in, hw_out = self.engine._update_channel_modes()

        self.assertEqual(self.engine._current_in_mode, self.AudioEngineClass.MODE_STEREO)
        self.assertEqual(self.engine._current_out_mode, self.AudioEngineClass.MODE_STEREO)
        self.assertEqual(hw_in, 2)
        self.assertEqual(hw_out, 2)

    def test_update_channel_modes_left(self):
        self.engine.input_channel_mode = "left"
        self.engine.output_channel_mode = "left"

        hw_in, hw_out = self.engine._update_channel_modes()

        self.assertEqual(self.engine._current_in_mode, self.AudioEngineClass.MODE_LEFT)
        self.assertEqual(self.engine._current_out_mode, self.AudioEngineClass.MODE_LEFT)
        self.assertEqual(hw_in, 1)
        self.assertEqual(hw_out, 1)

    def test_update_channel_modes_right(self):
        self.engine.input_channel_mode = "right"
        self.engine.output_channel_mode = "right"

        hw_in, hw_out = self.engine._update_channel_modes()

        self.assertEqual(self.engine._current_in_mode, self.AudioEngineClass.MODE_RIGHT)
        self.assertEqual(self.engine._current_out_mode, self.AudioEngineClass.MODE_RIGHT)
        self.assertEqual(hw_in, 2)
        self.assertEqual(hw_out, 2)

    @patch('sounddevice.query_devices')
    @patch('sounddevice.query_hostapis')
    def test_get_jack_settings_with_jack(self, mock_hostapis, mock_devices):
        # NOTE: patching 'sounddevice.query_devices' patches the attribute on the mock object in sys.modules

        # Setup mocks to simulate a JACK device
        self.engine.output_device = 1
        self.engine.jack_client_name = "TestClient"

        # Mock device query return
        mock_devices.return_value = {"hostapi": 0} # Device 1 uses hostapi 0

        # Mock hostapi query return
        mock_hostapis.return_value = {"name": "JACK Audio Connection Kit"} # Hostapi 0 is JACK

        # Call method
        settings = self.engine._get_jack_settings()

        # Verify it returns a JackSettings object
        import sounddevice as sd
        # sd is the mock
        sd.JackSettings.assert_called_with(client_name="TestClient")
        self.assertEqual(settings, sd.JackSettings.return_value)

    @patch('sounddevice.query_devices')
    @patch('sounddevice.query_hostapis')
    def test_get_jack_settings_no_jack(self, mock_hostapis, mock_devices):
        self.engine.output_device = 1

        mock_devices.return_value = {"hostapi": 0}
        mock_hostapis.return_value = {"name": "ALSA"} # Not JACK

        settings = self.engine._get_jack_settings()

        self.assertIsNone(settings)

    @patch('sounddevice.query_devices')
    def test_get_jack_settings_no_device(self, mock_devices):
        self.engine.output_device = None

        import sounddevice as sd
        # Mock sd.default.device to return [0, 1]
        type(sd.default).device = unittest.mock.PropertyMock(return_value=[0, 1])

        # Mock device 1 as non-JACK
        mock_devices.return_value = {"hostapi": 0}

        settings = self.engine._get_jack_settings()
        self.assertIsNone(settings)
