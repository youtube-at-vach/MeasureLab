import unittest
from unittest.mock import patch
import sys
import os

# Ensure the repository root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from src.core.audio_engine import AudioEngine

class TestAudioDeviceListing(unittest.TestCase):
    def setUp(self):
        # We patch 'src.core.audio_engine.sd' so that AudioEngine uses our mock
        self.sd_patcher = patch('src.core.audio_engine.sd')
        self.mock_sd = self.sd_patcher.start()

        # Configure default mock behaviors
        self.mock_sd.query_devices.return_value = []
        self.mock_sd.query_hostapis.return_value = []
        # AudioEngine.__init__ calls sd.CallbackFlags()
        self.mock_sd.CallbackFlags.return_value = 0

        self.engine = AudioEngine()

    def tearDown(self):
        self.sd_patcher.stop()

    def test_list_devices_basic(self):
        """Test basic successful device listing with host API name."""
        self.mock_sd.query_devices.return_value = [
            {'name': 'Speaker', 'hostapi': 0, 'max_input_channels': 0, 'max_output_channels': 2},
            {'name': 'Microphone', 'hostapi': 1, 'max_input_channels': 1, 'max_output_channels': 0}
        ]
        self.mock_sd.query_hostapis.return_value = [
            {'name': 'MME'},
            {'name': 'ASIO'}
        ]

        devices = self.engine.list_devices()

        self.assertEqual(len(devices), 2)
        self.assertEqual(devices[0]['name'], 'Speaker')
        self.assertEqual(devices[0]['hostapi_name'], 'MME')
        self.assertEqual(devices[1]['name'], 'Microphone')
        self.assertEqual(devices[1]['hostapi_name'], 'ASIO')

    def test_list_devices_no_hostapi_support(self):
        """Test behavior when query_hostapis raises an exception."""
        self.mock_sd.query_devices.return_value = [
            {'name': 'Speaker', 'hostapi': 0}
        ]
        self.mock_sd.query_hostapis.side_effect = RuntimeError("Host APIs not supported")

        devices = self.engine.list_devices()

        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0]['name'], 'Speaker')
        self.assertNotIn('hostapi_name', devices[0])

    def test_list_devices_invalid_hostapi_index(self):
        """Test behavior when hostapi index is out of range."""
        self.mock_sd.query_devices.return_value = [
            {'name': 'Speaker', 'hostapi': 99}
        ]
        self.mock_sd.query_hostapis.return_value = [
            {'name': 'MME'}
        ]

        devices = self.engine.list_devices()

        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0]['name'], 'Speaker')
        self.assertNotIn('hostapi_name', devices[0])

    def test_list_devices_hostapi_lookup_failure(self):
        """Test behavior when hostapi lookup fails internally (e.g. malformed hostapi entry)."""
        self.mock_sd.query_devices.return_value = [
            {'name': 'Speaker', 'hostapi': 0}
        ]
        # Return something that causes access failure or 'name' retrieval failure
        # For example, return None in the list, or an object without .get()
        # The code does: hostapis[int(hostapi_idx)].get("name")
        # If hostapis[0] is None, None.get() raises AttributeError
        self.mock_sd.query_hostapis.return_value = [None]

        devices = self.engine.list_devices()

        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0]['name'], 'Speaker')
        self.assertNotIn('hostapi_name', devices[0])

    def test_list_devices_device_without_hostapi_key(self):
        """Test behavior when device dict is missing 'hostapi' key."""
        self.mock_sd.query_devices.return_value = [
            {'name': 'Speaker'} # Missing hostapi
        ]
        self.mock_sd.query_hostapis.return_value = [
            {'name': 'MME'}
        ]

        devices = self.engine.list_devices()

        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0]['name'], 'Speaker')
        self.assertNotIn('hostapi_name', devices[0])

if __name__ == '__main__':
    unittest.main()
