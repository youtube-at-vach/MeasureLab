
import unittest
from unittest.mock import MagicMock
import numpy as np
import sys
import os

# Mock sounddevice before importing anything that uses it
sys.modules['sounddevice'] = MagicMock()

# Ensure src is in path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.gui.widgets.spectrum_analyzer import SpectrumAnalyzer

class MockAudioEngine:
    def __init__(self):
        self.sample_rate = 48000
        self.calibration = MagicMock()
        self.calibration.get_input_offset_db.return_value = 0.0
        self.calibration.get_spl_offset_db.return_value = 0.0
        self.registered_callback = None
        self.callbacks = {}
        self._callback_counter = 0

    def register_callback(self, callback):
        cid = self._callback_counter
        self.callbacks[cid] = callback
        self.registered_callback = callback
        self._callback_counter += 1
        return cid

    def unregister_callback(self, cid):
        if cid in self.callbacks:
            del self.callbacks[cid]
            if self.registered_callback == self.callbacks.get(cid):
                self.registered_callback = None

class TestSpectrumAnalyzerRingBuffer(unittest.TestCase):
    def setUp(self):
        # We need to mock QApplication because SpectrumAnalyzerWidget might be instantiated?
        # SpectrumAnalyzer is the logic class (MeasurementModule), SpectrumAnalyzerWidget is the GUI.
        # SpectrumAnalyzer.__init__ does not require GUI.
        self.engine = MockAudioEngine()
        self.sa = SpectrumAnalyzer(self.engine)
        self.sa.buffer_size = 100 # Small buffer for testing
        self.sa.set_buffer_size(100)
        self.sa.start_analysis()
        self.callback = self.engine.registered_callback

    def tearDown(self):
        self.sa.stop_analysis()

    def test_verify_reconstruction(self):
        """
        Feed data that causes wrap around, and verify we can reconstruct the linear sequence.
        This tests the PROPOSED implementation logic.
        """
        # Feed 80 samples: 0..79
        chunk1 = np.arange(80).reshape(80, 1)
        chunk1 = np.column_stack((chunk1, chunk1))
        outdata1 = np.zeros((80, 2))

        self.callback(chunk1, outdata1, 80, None, None)

        # Feed 40 samples: 80..119
        chunk2 = np.arange(80, 120).reshape(40, 1)
        chunk2 = np.column_stack((chunk2, chunk2))
        outdata2 = np.zeros((40, 2))

        self.callback(chunk2, outdata2, 40, None, None)

        # Total fed: 120. Buffer size: 100.
        # Expected content in buffer (logical): 20..119.
        expected_values = np.arange(20, 120)

        # Check if we are running optimized code or original code
        if self.sa.write_head == 0 and self.sa.input_data[0,0] == 20:
            print("Detected Original Implementation")
            reconstructed = self.sa.input_data
        else:
            print(f"Detected Ring Buffer Implementation (write_head={self.sa.write_head})")
            head = self.sa.write_head
            reconstructed = np.concatenate((self.sa.input_data[head:], self.sa.input_data[:head]))

        reconstructed_ch0 = reconstructed[:, 0]

        np.testing.assert_allclose(reconstructed_ch0, expected_values, err_msg="Reconstructed buffer does not match expected sequence")

if __name__ == '__main__':
    unittest.main()
