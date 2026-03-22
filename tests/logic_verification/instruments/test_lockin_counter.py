import sys
import unittest
import numpy as np
from unittest.mock import MagicMock, patch

# Mock PyQt6 and pyqtgraph before importing the widget
# This is necessary because the module imports PyQt6 widgets at the top level
mock_qt_widgets = MagicMock()
mock_qt_core = MagicMock()
mock_pyqtgraph = MagicMock()


# Create a dummy QWidget class for inheritance
class DummyQWidget:
    def __init__(self, *args, **kwargs):
        pass


mock_qt_widgets.QWidget = DummyQWidget
mock_qt_core.Qt = MagicMock()

# Patch sys.modules
with patch.dict(
    sys.modules,
    {
        "PyQt6.QtWidgets": mock_qt_widgets,
        "PyQt6.QtCore": mock_qt_core,
        "pyqtgraph": mock_pyqtgraph,
    },
):
    from src.gui.widgets.lock_in_frequency_counter import LockInFrequencyCounter


class TestLockInFrequencyCounter(unittest.TestCase):
    def setUp(self):
        self.mock_audio_engine = MagicMock()
        self.mock_audio_engine.sample_rate = 48000
        self.counter = LockInFrequencyCounter(self.mock_audio_engine)
        self.counter.gen_frequency = 1000.0
        self.counter.buffer_size = 4096

        # Helper for creating signals
        self.fs = 48000
        self.t = np.arange(self.counter.buffer_size) / self.fs

    def create_signal(self, freq, amplitude=1.0, phase=0.0):
        return amplitude * np.cos(2 * np.pi * freq * self.t + phase)

    def test_frequency_calculation_steady_state(self):
        """Test accurate frequency deviation measurement."""
        # 1001 Hz signal (1 Hz deviation from 1000 Hz NCO)
        sig = self.create_signal(1001.0)

        self.counter.input_data[:, 0] = sig
        self.counter.signal_channel = 0
        self.counter.is_running = True

        # Bypass transient suppression manually for this test
        self.counter._samples_received = 0
        self.counter._discard_initial_estimates = 0

        self.counter.process_data()

        self.assertTrue(self.counter.signal_present)
        # Allow small error (0.05 Hz) due to windowing/segmentation
        self.assertAlmostEqual(self.counter.current_freq_dev, 1.0, delta=0.05)

    def test_startup_transient_suppression(self):
        """Test that initial estimates are discarded on startup."""
        self.counter.start_analysis()  # Sets _discard_initial_estimates = 3

        # 1001 Hz signal
        sig = self.create_signal(1001.0)
        self.counter.input_data[:, 0] = sig

        # 1st call - should be discarded
        self.counter.process_data()
        self.assertEqual(self.counter.current_freq_dev, 0.0)
        self.assertEqual(self.counter._estimates_discarded, 1)

        # 2nd call - should be discarded
        self.counter.process_data()
        self.assertEqual(self.counter.current_freq_dev, 0.0)
        self.assertEqual(self.counter._estimates_discarded, 2)

        # 3rd call - should be discarded
        self.counter.process_data()
        self.assertEqual(self.counter.current_freq_dev, 0.0)
        self.assertEqual(self.counter._estimates_discarded, 3)

        # 4th call - should process
        self.counter.process_data()
        self.assertNotEqual(self.counter.current_freq_dev, 0.0)
        self.assertAlmostEqual(self.counter.current_freq_dev, 1.0, delta=0.05)

    def test_signal_gate(self):
        """Test that low amplitude signals are ignored."""
        self.counter.is_running = True
        self.counter._discard_initial_estimates = 0

        # Very weak signal (-80 dB)
        amp_db = -80.0
        amp_lin = 10 ** (amp_db / 20.0)
        sig = self.create_signal(1000.0, amplitude=amp_lin)

        self.counter.input_data[:, 0] = sig
        self.counter.gate_threshold_db = -60.0

        self.counter.process_data()

        self.assertFalse(self.counter.signal_present)

        # Strong signal (-40 dB)
        amp_db = -40.0
        amp_lin = 10 ** (amp_db / 20.0)
        sig = self.create_signal(1000.0, amplitude=amp_lin)

        self.counter.input_data[:, 0] = sig
        self.counter.process_data()

        self.assertTrue(self.counter.signal_present)

    def test_pid_lock_behavior(self):
        """Test that PID controller updates NCO frequency when locked."""
        self.counter.locked = True
        self.counter.is_running = True
        self.counter._discard_initial_estimates = 0
        self.counter.gen_frequency = 1000.0

        # Input signal at 1005 Hz (Error = +5 Hz)
        sig = self.create_signal(1005.0)
        self.counter.input_data[:, 0] = sig

        # First iteration
        self.counter.process_data()

        # PID should have adjusted gen_frequency towards 1005 Hz
        # With Kp=0.5, error=5.0, P-term = 2.5
        # New freq should be around 1002.5 + I/D terms
        self.assertNotEqual(self.counter.gen_frequency, 1000.0)
        self.assertTrue(self.counter.gen_frequency > 1000.0)


if __name__ == "__main__":
    unittest.main()
