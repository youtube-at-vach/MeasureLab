import unittest
from unittest.mock import MagicMock
import sys
import os

# Ensure src is in path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

# Mock sounddevice
sys.modules['sounddevice'] = MagicMock()

try:
    from src.gui.widgets.impedance_analyzer import ImpedanceAnalyzer
except ImportError:
    ImpedanceAnalyzer = None

class TestImpedanceAnalyzerDynamicBuffer(unittest.TestCase):
    def setUp(self):
        if ImpedanceAnalyzer is None:
            self.skipTest("ImpedanceAnalyzer could not be imported")

        self.mock_audio_engine = MagicMock()
        self.mock_audio_engine.sample_rate = 48000
        self.analyzer = ImpedanceAnalyzer(self.mock_audio_engine)

        # Reset defaults for predictability
        self.analyzer.base_buffer_size = 4096
        self.analyzer.max_buffer_multiplier = 8
        self.analyzer.dynamic_buffer_threshold_hz = 100.0
        self.analyzer.dynamic_buffer_min_cycles = 8.0

    def test_high_frequency_no_multiplier(self):
        """Frequencies above threshold should use multiplier 1."""
        # Threshold is 100.0 by default
        self.assertEqual(self.analyzer._desired_buffer_multiplier(100.0), 1)
        self.assertEqual(self.analyzer._desired_buffer_multiplier(1000.0), 1)
        self.assertEqual(self.analyzer._desired_buffer_multiplier(20000.0), 1)

    def test_low_frequency_multiplier_calculation(self):
        """
        Frequencies below threshold should increase multiplier.
        Formula:
        req_samples = (min_cycles * sr) / freq
        mul = ceil(req_samples / base)
        """
        # Case: 50 Hz
        # req = (8 * 48000) / 50 = 7680
        # mul = ceil(7680 / 4096) = ceil(1.875) = 2
        self.assertEqual(self.analyzer._desired_buffer_multiplier(50.0), 2)

        # Case: 25 Hz
        # req = (8 * 48000) / 25 = 15360
        # mul = ceil(15360 / 4096) = ceil(3.75) = 4
        self.assertEqual(self.analyzer._desired_buffer_multiplier(25.0), 4)

    def test_multiplier_cap(self):
        """Multiplier should not exceed max_buffer_multiplier."""
        # Case: 10 Hz
        # req = (8 * 48000) / 10 = 38400
        # mul = ceil(38400 / 4096) = ceil(9.375) = 10
        # But max is 8
        self.assertEqual(self.analyzer._desired_buffer_multiplier(10.0), 8)

        # Case: 1 Hz
        # req = 384000
        # mul = 94 -> capped at 8
        self.assertEqual(self.analyzer._desired_buffer_multiplier(1.0), 8)

    def test_invalid_frequencies(self):
        """Invalid frequencies should return 1 to avoid errors."""
        self.assertEqual(self.analyzer._desired_buffer_multiplier(0.0), 1)
        self.assertEqual(self.analyzer._desired_buffer_multiplier(-100.0), 1)
        self.assertEqual(self.analyzer._desired_buffer_multiplier(float('inf')), 1)
        self.assertEqual(self.analyzer._desired_buffer_multiplier(float('nan')), 1)

    def test_custom_configuration(self):
        """Verify logic respects configuration changes."""
        self.analyzer.base_buffer_size = 1024
        self.analyzer.max_buffer_multiplier = 16
        self.analyzer.dynamic_buffer_threshold_hz = 200.0
        self.analyzer.dynamic_buffer_min_cycles = 4.0

        # Let's pick a lower freq to force multiplier > 1
        # Freq = 50 Hz
        # req = (4 * 48000) / 50 = 3840
        # mul = ceil(3840 / 1024) = ceil(3.75) = 4
        self.assertEqual(self.analyzer._desired_buffer_multiplier(50.0), 4)

        # Test increased max_mul
        # Freq = 10 Hz
        # req = (4 * 48000) / 10 = 19200
        # mul = ceil(19200 / 1024) = ceil(18.75) = 19
        # Capped at 16
        self.assertEqual(self.analyzer._desired_buffer_multiplier(10.0), 16)

    def test_sample_rate_dependency(self):
        """Verify logic respects sample rate changes."""
        self.analyzer.audio_engine.sample_rate = 96000
        # 50 Hz
        # req = (8 * 96000) / 50 = 15360
        # mul = ceil(15360 / 4096) = ceil(3.75) = 4 (was 2 at 48k)
        self.assertEqual(self.analyzer._desired_buffer_multiplier(50.0), 4)

    def test_invalid_configuration_attributes(self):
        """Robustness against bad config values (e.g. from UI or file)."""
        # Zero base buffer -> Fallback to default (4096), so 50Hz gives mul=2
        self.analyzer.base_buffer_size = 0
        self.assertEqual(self.analyzer._desired_buffer_multiplier(50.0), 2)

        # Negative base buffer -> Should return 1 (safety check)
        self.analyzer.base_buffer_size = -4096
        self.assertEqual(self.analyzer._desired_buffer_multiplier(50.0), 1)

        self.analyzer.base_buffer_size = 4096

        # Zero max multiplier -> Fallback to default (8), so 50Hz gives mul=2
        self.analyzer.max_buffer_multiplier = 0
        self.assertEqual(self.analyzer._desired_buffer_multiplier(50.0), 2)

        # Negative max multiplier -> Should return 1 (safety check)
        self.analyzer.max_buffer_multiplier = -8
        self.assertEqual(self.analyzer._desired_buffer_multiplier(50.0), 1)

        self.analyzer.max_buffer_multiplier = 8
        # Zero sample rate -> Should return 1
        self.analyzer.audio_engine.sample_rate = 0
        self.assertEqual(self.analyzer._desired_buffer_multiplier(50.0), 1)

if __name__ == '__main__':
    unittest.main()
