import unittest
from unittest.mock import MagicMock, patch
import sys
import os
import queue

# Ensure src is in path
sys.path.append(os.getcwd())

# Mock modules BEFORE importing the module under test
mock_numpy = MagicMock()
mock_numpy.float64 = float
mock_numpy.nan = float('nan')
mock_numpy.zeros.return_value = MagicMock()
mock_numpy.array.return_value = MagicMock()
mock_numpy.mean.return_value = 0.0
mock_numpy.std.return_value = 0.0
mock_numpy.min.return_value = 0.0
mock_numpy.max.return_value = 0.0
mock_numpy.median.return_value = 0.0
mock_numpy.abs.return_value = MagicMock()

# Mock PyQt6
mock_qt_core = MagicMock()
mock_qt_widgets = MagicMock()
mock_pyqtgraph = MagicMock()

# Mock audio libraries
mock_sd = MagicMock()
mock_sf = MagicMock()

# Apply mocks to sys.modules
sys.modules['numpy'] = mock_numpy
sys.modules['sounddevice'] = mock_sd
sys.modules['soundfile'] = mock_sf
sys.modules['PyQt6'] = MagicMock()
sys.modules['PyQt6.QtCore'] = mock_qt_core
sys.modules['PyQt6.QtWidgets'] = mock_qt_widgets
sys.modules['pyqtgraph'] = mock_pyqtgraph

# Now import the module under test
from src.gui.widgets.one_pps_monitor import OnePPSMonitor

class TestOnePPSDoS(unittest.TestCase):
    def setUp(self):
        # Reset queue default if it was modified globally (unlikely but safe)
        pass

    def test_queue_bound_and_overflow(self):
        # Patch threading.Thread so start_analysis doesn't actually start a thread
        with patch('threading.Thread') as mock_thread_cls:
            # Setup
            audio_engine = MagicMock()
            audio_engine.sample_rate = 48000

            monitor = OnePPSMonitor(audio_engine)

            # Capture the callback
            captured_callback = None
            def register_side_effect(cb):
                nonlocal captured_callback
                captured_callback = cb
                return 1

            audio_engine.register_callback.side_effect = register_side_effect

            monitor.start_analysis()

            if captured_callback is None:
                 self.fail("Callback was not registered during start_analysis()")

            # 1. Verify queue is bounded
            # Queue maxsize of 0 means infinite. We want it > 0 to prevent DoS.
            if monitor.data_queue.maxsize <= 0:
                self.fail("Queue is unbounded (maxsize=0). Vulnerable to DoS.")

            # 2. Verify behavior when full
            # Fill the queue to its limit
            current_size = monitor.data_queue.qsize()
            max_size = monitor.data_queue.maxsize

            # Fill it up
            for _ in range(max_size - current_size):
                monitor.data_queue.put_nowait((MagicMock(), 10))

            self.assertTrue(monitor.data_queue.full(), "Queue should be full now")

            # Call callback again - should not block or raise exception
            indata = MagicMock()
            indata.shape = (100, 2)
            col_mock = MagicMock()
            col_mock.copy.return_value = MagicMock()
            indata.__getitem__.return_value = col_mock

            outdata = MagicMock()

            try:
                captured_callback(indata, outdata, 100, None, None)
            except queue.Full:
                 self.fail("Callback raised queue.Full exception instead of handling it gracefully.")
            except Exception as e:
                self.fail(f"Callback raised unexpected exception: {e}")

            # Ensure queue is still full (new data was dropped)
            self.assertTrue(monitor.data_queue.full())

            # DRAIN QUEUE to avoid blocking stop_analysis
            while not monitor.data_queue.empty():
                monitor.data_queue.get_nowait()

            monitor.stop_analysis()

if __name__ == '__main__':
    unittest.main()
