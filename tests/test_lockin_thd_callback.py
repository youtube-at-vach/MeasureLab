
import unittest
import numpy as np
from unittest.mock import MagicMock
import sys
import os

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.gui.widgets.lockin_thd_analyzer import LockInTHDAnalyzer

# We rely on conftest.py or the environment to handle sounddevice.
# But if we want to be safe in isolation:
try:
    import sounddevice
except (OSError, ImportError):
    # This block might be redundant if conftest.py ran, but harmless
    pass

class MockCalibration:
    def __init__(self):
        self.output_gain = 1.0
        self.input_sensitivity = 1.0
        self.input_offset = 0.0
        self.get_input_offset_db = MagicMock(return_value=0.0)

class MockAudioEngine:
    def __init__(self):
        self.sample_rate = 48000
        self.calibration = MockCalibration()
        self.callbacks = {}
        self.next_id = 0

    def register_callback(self, cb):
        cid = self.next_id
        self.next_id += 1
        self.callbacks[cid] = cb
        return cid

    def unregister_callback(self, cid):
        if cid in self.callbacks:
            del self.callbacks[cid]

class TestLockInTHDCallback(unittest.TestCase):
    def test_callback_does_not_print_status(self):
        engine = MockAudioEngine()
        analyzer = LockInTHDAnalyzer(engine)

        # Start analysis to register callback
        analyzer.start_analysis()

        # Get the registered callback
        self.assertTrue(len(engine.callbacks) > 0)
        callback = engine.callbacks[analyzer.callback_id]

        # Prepare dummy data
        frames = 128
        indata = np.zeros((frames, 2), dtype='float32')
        outdata = np.zeros((frames, 2), dtype='float32')
        time_info = MagicMock()

        class MockStatus:
            def __str__(self):
                return "Mock Error Status"
            def __bool__(self):
                return True

        status = MockStatus()

        # Run callback
        # We capture stdout to verify if it printed
        from io import StringIO
        captured_output = StringIO()
        sys.stdout = captured_output

        try:
            callback(indata, outdata, frames, time_info, status)
        finally:
            sys.stdout = sys.__stdout__
            analyzer.stop_analysis()

        output = captured_output.getvalue()

        self.assertEqual(output, "", "Callback should not print to stdout")

if __name__ == '__main__':
    unittest.main()
