import unittest
from unittest.mock import MagicMock, patch
import sys
import os
import queue
import importlib

# Ensure src is in path
sys.path.append(os.getcwd())

class TestOnePPSDoS(unittest.TestCase):
    def setUp(self):
        # Mocks
        self.mock_numpy = MagicMock()
        self.mock_numpy.float64 = float
        self.mock_numpy.nan = float('nan')
        self.mock_numpy.zeros.return_value = MagicMock()
        self.mock_numpy.array.return_value = MagicMock()
        self.mock_numpy.mean.return_value = 0.0
        self.mock_numpy.std.return_value = 0.0
        self.mock_numpy.min.return_value = 0.0
        self.mock_numpy.max.return_value = 0.0
        self.mock_numpy.median.return_value = 0.0
        self.mock_numpy.abs.return_value = MagicMock()

        self.mock_qt_core = MagicMock()
        self.mock_qt_widgets = MagicMock()
        self.mock_pyqtgraph = MagicMock()
        self.mock_sd = MagicMock()
        self.mock_sf = MagicMock()

        self.modules_patcher = patch.dict('sys.modules', {
            'numpy': self.mock_numpy,
            'sounddevice': self.mock_sd,
            'soundfile': self.mock_sf,
            'PyQt6': MagicMock(),
            'PyQt6.QtCore': self.mock_qt_core,
            'PyQt6.QtWidgets': self.mock_qt_widgets,
            'pyqtgraph': self.mock_pyqtgraph
        })
        self.modules_patcher.start()

        # Import inside setUp to use mocked modules
        # We must ensure previous imports don't cache the real modules or different mocks
        if 'src.gui.widgets.one_pps_monitor' in sys.modules:
            del sys.modules['src.gui.widgets.one_pps_monitor']

        import src.gui.widgets.one_pps_monitor
        importlib.reload(src.gui.widgets.one_pps_monitor)
        self.OnePPSMonitor = src.gui.widgets.one_pps_monitor.OnePPSMonitor

    def tearDown(self):
        self.modules_patcher.stop()
        # Clean up the module we imported so it doesn't leave traces
        if 'src.gui.widgets.one_pps_monitor' in sys.modules:
            del sys.modules['src.gui.widgets.one_pps_monitor']

    def test_queue_bound_and_overflow(self):
        # Patch threading.Thread so start_analysis doesn't actually start a thread
        with patch('threading.Thread'):
            # Setup
            audio_engine = MagicMock()
            audio_engine.sample_rate = 48000

            monitor = self.OnePPSMonitor(audio_engine)

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
