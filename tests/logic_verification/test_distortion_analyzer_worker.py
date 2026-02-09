import unittest
from unittest.mock import MagicMock, patch
import numpy as np
import sys
import os

# Adjust path to find src
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

# Mock sounddevice before importing anything that uses it
sys.modules["sounddevice"] = MagicMock()

class TestRealtimeAnalysisWorker(unittest.TestCase):
    def setUp(self):
        # Patch modules where RealtimeAnalysisWorker will be imported from
        self.audio_calc_patcher = patch('src.gui.widgets.distortion_analyzer.AudioCalc')
        self.fft_manager_patcher = patch('src.gui.widgets.distortion_analyzer.fft_manager')
        self.get_window_patcher = patch('src.gui.widgets.distortion_analyzer.get_cached_window')

        self.mock_audio_calc = self.audio_calc_patcher.start()
        self.mock_fft_manager = self.fft_manager_patcher.start()
        self.mock_get_window = self.get_window_patcher.start()

    def tearDown(self):
        self.audio_calc_patcher.stop()
        self.fft_manager_patcher.stop()
        self.get_window_patcher.stop()

    def test_process_harmonics(self):
        try:
            from src.gui.widgets.distortion_analyzer import RealtimeAnalysisWorker
        except ImportError:
            self.skipTest("RealtimeAnalysisWorker not implemented yet")

        # Create worker
        # We need to mock QObject if we don't want to rely on PyQt6 being fully functional in headless without qpa
        # But RealtimeAnalysisWorker inherits QObject.
        # We can just instantiate it.

        worker = RealtimeAnalysisWorker()

        # Mock the signal
        # Since result_ready is a pyqtSignal, we can connect a mock to it or mock the emit method.
        # Mocking emit is easier if we can access the bound signal.
        mock_slot = MagicMock()
        worker.result_ready.connect(mock_slot)

        data = np.zeros(1024)
        settings = {
            "signal_type": "sine",
            "window_type": "hann",
            "sample_rate": 48000,
            "gen_frequency": 1000,
            "imd_f1": 60,
            "imd_f2": 7000,
            "buffer_size": 1024
        }

        # Setup mocks
        self.mock_audio_calc.analyze_harmonics.return_value = {"thd": 0.1, "fft_data": np.zeros(513), "basic_wave": {}}

        worker.process(data, settings)

        self.mock_audio_calc.analyze_harmonics.assert_called_once()
        mock_slot.assert_called_once()
        args, _ = mock_slot.call_args
        result = args[0]
        self.assertEqual(result["thd"], 0.1)
        # Check if type is included (helper for receiver)
        self.assertEqual(result.get("type"), "harmonics")

    def test_process_imd(self):
        try:
            from src.gui.widgets.distortion_analyzer import RealtimeAnalysisWorker
        except ImportError:
            self.skipTest("RealtimeAnalysisWorker not implemented yet")

        worker = RealtimeAnalysisWorker()
        mock_slot = MagicMock()
        worker.result_ready.connect(mock_slot)

        data = np.zeros(1024)
        settings = {
            "signal_type": "smpte",
            "window_type": "hann",
            "sample_rate": 48000,
            "gen_frequency": 1000,
            "imd_f1": 60,
            "imd_f2": 7000,
            "buffer_size": 1024
        }

        # Setup mocks
        self.mock_get_window.return_value = np.ones(1024)
        self.mock_fft_manager.rfft.return_value = np.zeros(513, dtype=complex)
        self.mock_fft_manager.rfftfreq.return_value = np.linspace(0, 24000, 513)
        self.mock_audio_calc.calculate_imd_smpte.return_value = {"imd": 0.05}

        worker.process(data, settings)

        self.mock_audio_calc.calculate_imd_smpte.assert_called_once()
        mock_slot.assert_called_once()
        args, _ = mock_slot.call_args
        result = args[0]
        self.assertEqual(result["imd"], 0.05)
        self.assertEqual(result.get("type"), "imd")

if __name__ == "__main__":
    unittest.main()
