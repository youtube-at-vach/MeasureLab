import unittest
import numpy as np
from unittest.mock import MagicMock

# Use real imports to avoid global sys.modules pollution, or mock locally if needed.
# PyQt/PyQtGraph is heavy but we are running in an environment where we can import it.
# For headless environments, QT_QPA_PLATFORM=offscreen should be used.

from src.gui.widgets.lockin_spectrum_finder import LockInSpectrumFinder
from src.core.sonifier import Sonifier

class MockCalibration:
    def get_input_offset_db(self):
        return 0.0
    def get_spl_offset_db(self):
        return 0.0

class MockAudioEngine:
    def __init__(self):
        self.sample_rate = 48000
        self.block_size = 1024
        self.calibration = MockCalibration()
        self.callbacks = {}
        self.next_id = 0

    def register_callback(self, callback):
        cid = self.next_id
        self.next_id += 1
        self.callbacks[cid] = callback
        return cid

    def unregister_callback(self, cid):
        if cid in self.callbacks:
            del self.callbacks[cid]

class TestLockInSpectrumFinderSonification(unittest.TestCase):
    def setUp(self):
        self.audio_engine = MockAudioEngine()
        self.finder = LockInSpectrumFinder(self.audio_engine)
        self.finder.start_analysis()
        self.callback = self.audio_engine.callbacks[self.finder.callback_id]

    def test_sonifier_integration_in_callback(self):
        """Test that the callback method invokes the sonifier process method."""
        # Enable sonification
        self.finder.sonifier.set_enabled(True)
        self.finder.sonifier.set_mode(Sonifier.MODE_LEVEL_MONITOR)

        # Fake a parameter update to give it something to synthesize
        self.finder.sonifier.update_parameters(scan_freq=1000.0, mag_db=-30.0)

        indata = np.zeros((1024, 2))
        outdata = np.zeros((1024, 2))

        self.callback(indata, outdata, 1024, None, None)

        # If the sonifier was called, outdata should have non-zero elements
        self.assertTrue(np.any(outdata != 0.0))

    def test_do_calculation_updates_sonifier(self):
        """Test that _do_calculation pushes parameters to the sonifier."""
        # Setup fake data
        fs = 48000
        N = 4096
        # Generate a 1kHz tone at ~ -20 dBFS
        t = np.arange(N) / fs
        sig = 0.1 * np.sin(2 * np.pi * 1000.0 * t)

        # Replace the sonifier with a mock to check if update_parameters is called
        original_sonifier = self.finder.sonifier
        mock_sonifier = MagicMock(spec=Sonifier)
        mock_sonifier.manual_freq = 1000.0
        self.finder.sonifier = mock_sonifier

        # Run calculation
        self.finder._do_calculation(
            sig=sig,
            fs=fs,
            start_f=900.0,
            stop_f=1100.0,
            points=10,
            spacing="Lin",
            display_unit="dBFS",
            offset_dbv=0.0,
            offset_spl=0.0
        )

        # Verify update_parameters was called at least once
        self.assertTrue(mock_sonifier.update_parameters.called)

        # Verify manual tuner update was called (since manual_freq was 1000 and sweep was 900-1100)
        self.assertTrue(mock_sonifier.update_manual_tuner_mag.called)

        self.finder.sonifier = original_sonifier

    def test_start_analysis_syncs_sonifier_sample_rate(self):
        self.finder.stop_analysis()
        self.audio_engine.sample_rate = 96000

        self.finder.start_analysis()

        self.assertEqual(self.finder.sonifier.sample_rate, 96000)

    def test_trigger_calculation_allows_initial_partial_buffer(self):
        self.finder.buffer_size = 262144
        self.finder.input_data = np.zeros((self.finder.buffer_size, 2), dtype=np.float32)
        self.finder.input_buffer_pos = 0
        self.finder.buffer_filled_samples = 0
        self.finder._analysis_warmed_up = False

        min_samples = self.finder._get_min_analysis_samples()
        self.finder.input_data[:min_samples, 0] = 1.0
        self.finder.buffer_filled_samples = min_samples
        self.finder.input_buffer_pos = min_samples

        self.finder.executor = MagicMock()
        self.finder.executor.submit.return_value = MagicMock(done=lambda: False)

        self.finder.trigger_calculation()

        self.finder.executor.submit.assert_called_once()
        submitted_sig = self.finder.executor.submit.call_args.args[1]
        self.assertEqual(len(submitted_sig), min_samples)
        self.assertEqual(self.finder.buffer_filled_samples, 0)
        self.assertTrue(self.finder._analysis_warmed_up)

    def test_trigger_calculation_keeps_buffer_while_worker_busy(self):
        self.finder.buffer_size = 32768
        self.finder.input_data = np.ones((self.finder.buffer_size, 2), dtype=np.float32)
        self.finder.input_buffer_pos = 0
        self.finder.buffer_filled_samples = self.finder.buffer_size
        self.finder._analysis_warmed_up = True
        self.finder._calculation_future = MagicMock(done=lambda: False)

        self.finder.trigger_calculation()

        self.assertEqual(self.finder.buffer_filled_samples, self.finder.buffer_size)
        np.testing.assert_array_equal(self.finder.input_data, np.ones((self.finder.buffer_size, 2), dtype=np.float32))
