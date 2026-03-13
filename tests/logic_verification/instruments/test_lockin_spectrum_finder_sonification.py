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

    def test_save_user_targets_secure_permissions(self):
        """Test that save_user_targets uses secure permissions for directory creation."""
        from unittest.mock import patch

        targets = {1000.0: "Test Note"}

        with patch("os.makedirs") as mock_makedirs, \
             patch("os.open") as mock_open, \
             patch("os.fdopen") as mock_fdopen:

            # Setup mock so we don't actually write to disk
            mock_open.return_value = 123
            mock_fdopen.return_value.__enter__.return_value = MagicMock()

            self.finder.save_user_targets(targets)

            mock_makedirs.assert_called_once()
            _, kwargs = mock_makedirs.call_args
            self.assertEqual(kwargs.get("mode"), 0o700, "Directory must be created with mode 0o700")
