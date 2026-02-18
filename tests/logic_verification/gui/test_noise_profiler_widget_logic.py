import unittest
from unittest.mock import MagicMock, patch
import sys
import os
import numpy as np

# Ensure repo root is in path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

class TestNoiseProfilerLogicBase(unittest.TestCase):
    def setUp(self):
        # 1. Prepare Mocks
        self.mock_qt = MagicMock()

        # Define Mock Classes to replace Qt classes
        class MockQObject:
            def __init__(self, *args, **kwargs):
                pass

        class MockQRunnable:
            def __init__(self, *args, **kwargs):
                pass

        self.mock_qt.QtCore.QObject = MockQObject
        self.mock_qt.QtCore.QRunnable = MockQRunnable

        # Mock pyqtSignal to return a MagicMock (which has .emit which is also a MagicMock)
        # We use a side_effect that returns a NEW MagicMock each time
        self.mock_qt.QtCore.pyqtSignal.side_effect = lambda *args, **kwargs: MagicMock()

        # 2. Patch sys.modules
        # We mock dependencies that might be missing or that we want to control
        self.modules_patcher = patch.dict(sys.modules, {
            'PyQt6': self.mock_qt,
            'PyQt6.QtCore': self.mock_qt.QtCore,
            'PyQt6.QtWidgets': self.mock_qt.QtWidgets,
            'pyqtgraph': MagicMock(),
            'sounddevice': MagicMock(),
            'soundfile': MagicMock(),
            'scipy': MagicMock(),
            'scipy.signal': MagicMock(),
            'scipy.optimize': MagicMock(),
            'scipy.signal.windows': MagicMock(),
            'pywt': MagicMock()
        })
        self.modules_patcher.start()

        # 3. Force re-import of the module under test
        # This ensures it uses our Mocks, even if it was previously imported by another test
        if 'src.gui.widgets.noise_profiler' in sys.modules:
            del sys.modules['src.gui.widgets.noise_profiler']

        import src.gui.widgets.noise_profiler
        self.module_pkg = src.gui.widgets.noise_profiler
        self.NoiseProfiler = self.module_pkg.NoiseProfiler
        self.NoiseAnalysisWorker = self.module_pkg.NoiseAnalysisWorker

    def tearDown(self):
        # 1. Stop patching
        self.modules_patcher.stop()

        # 2. Clean up module from sys.modules
        # This prevents our mocked version from polluting subsequent tests
        for mod in ['src.gui.widgets.noise_profiler', 'src.core.analysis', 'src.core.fft_manager', 'src.core.audio_engine']:
            if mod in sys.modules:
                del sys.modules[mod]

class TestNoiseProfilerAverage(TestNoiseProfilerLogicBase):
    def setUp(self):
        super().setUp()
        self.engine = MagicMock()
        self.engine.sample_rate = 48000
        self.engine.calibration.get_input_offset_db.return_value = 0.0

        self.profiler = self.NoiseProfiler(self.engine)
        self.profiler.average_mode = True
        self.profiler.target_averages = 10
        self.profiler.current_avg_count = 0
        self.profiler.accumulated_magnitude = None
        self.profiler._avg_magnitude = None
        self.profiler.buffer_size = 1024
        self.profiler.input_data = np.zeros((1024, 2))

    def test_averaging_logic(self):
        mag1 = np.ones(513) * 1.0
        mag2 = np.ones(513) * 2.0
        mag3 = np.ones(513) * 3.0

        self.profiler.update_average(mag1)
        self.assertEqual(self.profiler.current_avg_count, 1)
        np.testing.assert_array_almost_equal(self.profiler._avg_magnitude, mag1)

        self.profiler.update_average(mag2)
        self.assertEqual(self.profiler.current_avg_count, 2)
        np.testing.assert_array_almost_equal(self.profiler._avg_magnitude, np.ones(513) * 1.5)

        self.profiler.update_average(mag3)
        self.assertEqual(self.profiler.current_avg_count, 3)
        np.testing.assert_array_almost_equal(self.profiler._avg_magnitude, np.ones(513) * 2.0)

class TestNoiseProfilerProcess(TestNoiseProfilerLogicBase):
    def setUp(self):
        super().setUp()
        self.engine = MagicMock()
        self.engine.sample_rate = 48000
        self.engine.calibration.get_input_offset_db.return_value = 0.0

        self.profiler = self.NoiseProfiler(self.engine)
        self.profiler.buffer_size = 1024
        self.profiler.input_data = np.random.rand(1024, 2)

    def test_process_data_smoke(self):
        # We need to ensure dependencies used inside process_data are also working (mocked or real)
        # process_data calls AudioCalc, fft_manager.
        # Since we mocked scipy/pywt at sys.modules level, imports inside core.analysis might fail or return mocks.
        # If they return mocks, calculations will produce mocks.

        # We might need to mock return values of fft_manager if we want meaningful output,
        # or just check that it runs without error.

        # Let's mock fft_manager.rfftfreq and rfft to return numpy arrays so logic continues
        with patch('src.core.fft_manager.fft_manager') as mock_fft:
            mock_fft.rfft.return_value = np.zeros(513)
            mock_fft.rfftfreq.return_value = np.zeros(513)

            # Also mock get_cached_window to return correct size (default buffer size 1024)
            with patch('src.gui.widgets.noise_profiler.get_cached_window') as mock_window:
                mock_window.return_value = np.ones(1024)
                output = self.profiler.process_data(0, "dBV", False)

            # Since rfft returns zeros, magnitude is zeros.
            # update_average returns zeros.
            # AudioCalc.calculate_noise_profile is called with zeros.

            self.assertIsNotNone(output)
            freqs, mag, results, raw_avg = output
            self.assertIsNotNone(results)

    def test_process_data_insufficient_data(self):
        self.profiler.input_data = np.zeros((100, 2))
        output = self.profiler.process_data(0, "dBV", False)
        self.assertIsNone(output)

class TestNoiseProfilerLogging(TestNoiseProfilerLogicBase):
    def test_worker_exception_logging(self):
        mock_engine = MagicMock()
        module = self.NoiseProfiler(mock_engine)

        test_exception = ValueError("Simulated Crash")
        module.process_data = MagicMock(side_effect=test_exception)

        worker = self.NoiseAnalysisWorker(module, channel_idx=0, unit_mode="dBV", apply_gain=False)

        # worker.signals.error is a MagicMock because pyqtSignal returned a MagicMock
        error_slot = MagicMock()
        worker.signals.error.connect(error_slot)

        # Mock the logger
        # Note: We need to patch the logger in the *re-imported* module
        with patch.object(self.module_pkg, 'logger') as mock_logger:
            worker.run()

            # Now this should work because worker.signals.error is a MagicMock, so .emit is a MagicMock
            worker.signals.error.emit.assert_called_once_with("Simulated Crash")

            assert mock_logger.error.called

class TestNoiseProfilerRingBuffer(TestNoiseProfilerLogicBase):
    def setUp(self):
        super().setUp()
        self.mock_engine = MagicMock()
        self.mock_engine.sample_rate = 48000
        self.mock_engine.calibration.get_input_offset_db.return_value = 0.0

        self.profiler = self.NoiseProfiler(self.mock_engine)
        self.profiler.set_buffer_size(10)

        self.callback = None
        def register_side_effect(cb):
            self.callback = cb
            return 1
        self.mock_engine.register_callback.side_effect = register_side_effect

        self.profiler.start_analysis()

    def test_callback_logic(self):
        data1 = np.ones((4, 2)) * 1
        self.callback(data1, np.zeros_like(data1), 4, None, None)

        self.assertEqual(self.profiler.buffer_ptr, 4)
        np.testing.assert_array_equal(self.profiler.input_data[:4], data1)

    def test_wrap_around(self):
        data = np.ones((8, 2)) * 1
        self.callback(data, np.zeros_like(data), 8, None, None)
        self.assertEqual(self.profiler.buffer_ptr, 8)

        data2 = np.ones((4, 2)) * 2
        self.callback(data2, np.zeros_like(data2), 4, None, None)

        self.assertEqual(self.profiler.buffer_ptr, 2)
        np.testing.assert_array_equal(self.profiler.input_data[8:], np.ones((2, 2)) * 2)
        np.testing.assert_array_equal(self.profiler.input_data[:2], np.ones((2, 2)) * 2)

    def test_buffer_overrun(self):
        data = np.ones((15, 2)) * 3
        self.callback(data, np.zeros_like(data), 15, None, None)

        self.assertEqual(self.profiler.buffer_ptr, 0)
        np.testing.assert_array_equal(self.profiler.input_data, np.ones((10, 2)) * 3)

if __name__ == '__main__':
    unittest.main()
