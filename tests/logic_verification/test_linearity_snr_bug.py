
import sys
import os
import unittest
from unittest.mock import MagicMock, patch
import numpy as np

# Ensure src is in path
sys.path.append(os.getcwd())

from src.gui.widgets.linearity_analyzer import LinearitySweepWorker

class TestLinearitySnrBug(unittest.TestCase):
    def test_snr_calculation_on_silence(self):
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

        # Mock get_latest_buffer to return zeros
        mock_module.get_latest_buffer.return_value = np.zeros((1024, 2))

        # Instantiate Worker
        worker = LinearitySweepWorker(mock_module)

        # Mock AudioCalc to return 0 magnitude (silence)
        # We need to patch src.gui.widgets.linearity_analyzer.AudioCalc
        # because the module imports it.
        with patch('src.gui.widgets.linearity_analyzer.AudioCalc') as MockAudioCalc:
            # calculate_lockin_measurement returns (mag, phase)
            # First call is signal, Second call is noise
            # We want signal=0, noise=1e-9 (small but non-zero to avoid div/0 in noise check)

            # Side_effect to handle multiple calls
            def side_effect(*args, **kwargs):
                # Check frequency to distinguish signal vs noise measurement if needed
                # But simple sequence: 1. Sig, 2. Noise
                return 0.0, 0.0

            MockAudioCalc.calculate_lockin_measurement.side_effect = [
                (0.0, 0.0), # Signal: Magnitude 0
                (1e-9, 0.0) # Noise: Magnitude 1e-9
            ]

            # We capture the emitted result
            results = []
            worker.result_ready.connect(lambda res: results.append(res))

            # Run (synchronously for test, bypassing Thread.start)
            # We override sleep to speed up
            with patch('time.sleep', return_value=None):
                worker.run()

            self.assertTrue(len(results) > 0, "No results emitted")
            result = results[0]
            snr = result['snr']

            print(f"Calculated SNR: {snr}")

            # Check for finite value
            self.assertTrue(np.isfinite(snr), f"SNR should be finite, got {snr}")

            # Check that it is not -inf
            # If mag=0 and we don't add epsilon, log10(0) is -inf.
            # If we add epsilon 1e-15, snr = 20*log10(1e-15 / 1e-9) = 20*log10(1e-6) = -120 dB.
            # If we didn't fix it, it would be -inf.
            self.assertGreater(snr, -200.0, "SNR should be reasonable (approx -120dB), not -inf")

if __name__ == '__main__':
    unittest.main()
