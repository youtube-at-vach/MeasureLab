import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../')))
import sys
import unittest
from unittest.mock import MagicMock
import numpy as np
import importlib

class TestLoopbackFinder(unittest.TestCase):
    def setUp(self):
        # Patch modules
        self._patched_modules = ["PyQt6.QtCore", "PyQt6.QtWidgets", "sounddevice"]
        self._original_modules = {}

        for mod in self._patched_modules:
            if mod in sys.modules:
                self._original_modules[mod] = sys.modules[mod]
            sys.modules[mod] = MagicMock()

        # Specific mocks for PyQt6 to support class definitions
        mock_qt_core = sys.modules["PyQt6.QtCore"]

        # Robust base class mock that accepts any arguments in __init__
        class MockBase:
            def __init__(self, *args, **kwargs):
                pass

        # Make QThread a type so it can be inherited
        mock_qt_core.QThread = type('QThread', (MockBase,), {})
        # pyqtSignal can be a function returning a mock
        mock_qt_core.pyqtSignal = MagicMock(return_value=MagicMock())

        # Mock QWidget
        mock_qt_widgets = sys.modules["PyQt6.QtWidgets"]
        mock_qt_widgets.QWidget = type('QWidget', (MockBase,), {})

        # Import/Reload module under test
        if 'src.gui.widgets.loopback_finder' in sys.modules:
            importlib.reload(sys.modules['src.gui.widgets.loopback_finder'])
        else:
            importlib.import_module('src.gui.widgets.loopback_finder')

        self.module_under_test = sys.modules['src.gui.widgets.loopback_finder']

        # Instantiate LoopbackFinder
        self.mock_audio_engine = MagicMock()
        self.finder = self.module_under_test.LoopbackFinder(self.mock_audio_engine)

    def tearDown(self):
        # Restore modules
        for mod in self._patched_modules:
            if mod in self._original_modules:
                sys.modules[mod] = self._original_modules[mod]
            else:
                if mod in sys.modules:
                    del sys.modules[mod]

        # Remove module under test to ensure clean slate
        if 'src.gui.widgets.loopback_finder' in sys.modules:
            del sys.modules['src.gui.widgets.loopback_finder']

    def test_perform_scan_success(self):
        # Setup mocks
        sd = sys.modules["sounddevice"]
        sd.query_devices.return_value = {"max_output_channels": 2, "max_input_channels": 2}

        # Create a test signal that matches what the finder expects
        # The finder sends 440Hz sine wave.
        sample_rate = 48000
        duration = 0.1
        t = np.linspace(0, duration, int(sample_rate * duration), False)
        test_signal = 0.5 * np.sin(2 * np.pi * 440 * t)

        # Prepare playrec return value
        # When output channel 0 is tested, return signal on input 0 (loopback found)
        # When output channel 1 is tested, return silence

        def playrec_side_effect(*args, **kwargs):
            # Extract arguments. LoopbackFinder calls:
            # sd.playrec(output_signal, samplerate=..., channels=..., device=..., blocking=...)

            outdata = args[0] if len(args) > 0 else kwargs.get('data')
            channels = kwargs.get('channels', 2) # Default to 2 if not specified, though logic should pass it

            # Check which output channel has signal
            frames = len(outdata)
            rec_data = np.zeros((frames, channels), dtype=np.float32)

            # Find active output channel
            active_ch = -1
            for ch in range(outdata.shape[1]):
                if np.max(np.abs(outdata[:, ch])) > 0:
                    active_ch = ch
                    break

            if active_ch == 0:
                # Simulate loopback from out 0 to in 0
                rec_data[:, 0] = test_signal

            return rec_data

        sd.playrec.side_effect = playrec_side_effect

        results = self.finder.perform_scan(device_id=0, sample_rate=sample_rate)

        # Expect loopback: Out 1 -> In 1 (indices 0->0)
        self.assertEqual(len(results), 1)
        out_ch, in_ch, mag = results[0]
        self.assertEqual(out_ch, 1) # 1-based index
        self.assertEqual(in_ch, 1) # 1-based index
        # Magnitude should be close to 0.5
        self.assertAlmostEqual(mag, 0.5, delta=0.05)

    def test_perform_scan_no_signal(self):
        sd = sys.modules["sounddevice"]
        sd.query_devices.return_value = {"max_output_channels": 2, "max_input_channels": 2}

        # Return silence always
        sd.playrec.return_value = np.zeros((4800, 2), dtype=np.float32)

        results = self.finder.perform_scan(device_id=0, sample_rate=48000)

        self.assertEqual(len(results), 0)

    def test_perform_scan_device_error(self):
        sd = sys.modules["sounddevice"]
        # Simulate device with 0 inputs
        sd.query_devices.return_value = {"max_output_channels": 2, "max_input_channels": 0}

        with self.assertRaises(Exception) as cm:
            self.finder.perform_scan(device_id=0, sample_rate=48000)
        self.assertIn("does not support both input and output", str(cm.exception))

    def test_perform_scan_playrec_error(self):
        sd = sys.modules["sounddevice"]
        sd.query_devices.return_value = {"max_output_channels": 2, "max_input_channels": 2}
        sd.playrec.side_effect = Exception("Audio Error")

        with self.assertRaises(Exception) as cm:
            self.finder.perform_scan(device_id=0, sample_rate=48000)
        self.assertIn("Error during playback/recording", str(cm.exception))

    def test_perform_scan_stop(self):
        sd = sys.modules["sounddevice"]
        sd.query_devices.return_value = {"max_output_channels": 10, "max_input_channels": 2}

        # Stop immediately
        check_stop = MagicMock(return_value=True)

        results = self.finder.perform_scan(device_id=0, sample_rate=48000, check_stop=check_stop)

        # Should break immediately, so no calls to playrec
        sd.playrec.assert_not_called()
        self.assertEqual(len(results), 0)

    def test_perform_scan_progress(self):
        sd = sys.modules["sounddevice"]
        sd.query_devices.return_value = {"max_output_channels": 2, "max_input_channels": 2}
        sd.playrec.return_value = np.zeros((4800, 2), dtype=np.float32)

        progress_cb = MagicMock()

        self.finder.perform_scan(device_id=0, sample_rate=48000, progress_callback=progress_cb)

        # Should be called 2 times (once per output channel)
        self.assertEqual(progress_cb.call_count, 2)

if __name__ == '__main__':
    unittest.main()
