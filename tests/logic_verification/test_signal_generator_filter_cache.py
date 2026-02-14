
import sys
import os
import unittest
from unittest.mock import MagicMock, patch
import numpy as np

# Add src to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from src.gui.widgets.signal_generator import SignalGenerator

class TestSignalGeneratorFilterCache(unittest.TestCase):
    def setUp(self):
        self.mock_audio_engine = MagicMock()
        self.mock_audio_engine.sample_rate = 48000
        self.sg = SignalGenerator(self.mock_audio_engine)

    def test_lpf_caching(self):
        # Setup LPF
        self.sg.params_L.lpf_enabled = True
        self.sg.params_L.lpf_freq = 1000.0
        self.sg.params_L.lpf_order = 4

        with patch('scipy.signal.butter') as mock_butter:
            # Setup mock return value
            mock_butter.return_value = np.zeros((2, 6))

            # First call - should calculate
            sos1 = self.sg._get_filter_sos(self.sg.params_L, "low", 48000)
            mock_butter.assert_called_once()
            mock_butter.reset_mock()

            # Second call - same params - should cache hit
            sos2 = self.sg._get_filter_sos(self.sg.params_L, "low", 48000)
            mock_butter.assert_not_called()
            self.assertIs(sos1, sos2)

            # Third call - change params - should calculate
            self.sg.params_L.lpf_freq = 2000.0
            self.sg._get_filter_sos(self.sg.params_L, "low", 48000)
            mock_butter.assert_called_once()

    def test_hpf_caching(self):
        # Setup HPF
        self.sg.params_L.hpf_enabled = True
        self.sg.params_L.hpf_freq = 1000.0
        self.sg.params_L.hpf_order = 4

        with patch('scipy.signal.butter') as mock_butter:
            # Setup mock return value
            mock_butter.return_value = np.zeros((2, 6))

            # First call - should calculate
            sos1 = self.sg._get_filter_sos(self.sg.params_L, "high", 48000)
            mock_butter.assert_called_once()
            mock_butter.reset_mock()

            # Second call - same params - should cache hit
            sos2 = self.sg._get_filter_sos(self.sg.params_L, "high", 48000)
            mock_butter.assert_not_called()
            self.assertIs(sos1, sos2)

            # Third call - change params - should calculate
            self.sg.params_L.hpf_order = 2
            self.sg._get_filter_sos(self.sg.params_L, "high", 48000)
            mock_butter.assert_called_once()

    def test_independent_caches(self):
        # Ensure LPF and HPF caches are independent
        self.sg.params_L.lpf_enabled = True
        self.sg.params_L.lpf_freq = 1000.0
        self.sg.params_L.hpf_enabled = True
        self.sg.params_L.hpf_freq = 2000.0

        with patch('scipy.signal.butter') as mock_butter:
            # Setup mock return value
            mock_butter.return_value = np.zeros((2, 6))

            # Calculate LPF
            self.sg._get_filter_sos(self.sg.params_L, "low", 48000)
            mock_butter.assert_called_once()
            mock_butter.reset_mock()

            # Calculate HPF
            self.sg._get_filter_sos(self.sg.params_L, "high", 48000)
            mock_butter.assert_called_once()
            mock_butter.reset_mock()

            # Call LPF again - should be cached
            self.sg._get_filter_sos(self.sg.params_L, "low", 48000)
            mock_butter.assert_not_called()

            # Call HPF again - should be cached
            self.sg._get_filter_sos(self.sg.params_L, "high", 48000)
            mock_butter.assert_not_called()

if __name__ == '__main__':
    unittest.main()
