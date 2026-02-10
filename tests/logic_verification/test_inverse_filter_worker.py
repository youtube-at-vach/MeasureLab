import sys
import unittest
from unittest.mock import MagicMock, patch
import numpy as np

# Mock modules to avoid GUI dependency issues
class MockQThread:
    def __init__(self):
        pass

mock_qt_core = MagicMock()
mock_qt_core.QThread = MockQThread
mock_qt_core.pyqtSignal = MagicMock()
mock_qt_core.Qt = MagicMock()

sys.modules['PyQt6.QtCore'] = mock_qt_core
sys.modules['PyQt6.QtWidgets'] = MagicMock()
sys.modules['pyqtgraph'] = MagicMock()

# Now import the worker
from src.gui.widgets.inverse_filter import ProcessingWorker

class TestInverseFilterWorker(unittest.TestCase):
    def setUp(self):
        self.mock_calibration = [(100, 1.0, 0.0), (1000, 1.0, 0.0)]

    @patch('src.gui.widgets.inverse_filter.sf')
    @patch('src.gui.widgets.inverse_filter.signal')
    @patch('src.gui.widgets.inverse_filter.fft_manager')
    def test_large_file_uses_chunked_processing(self, mock_fft, mock_signal, mock_sf):
        """Verify that large files trigger chunked processing path."""
        # Setup huge file simulation (3GB)
        sr = 192000
        channels = 8
        duration = 9 * 60
        frames = int(duration * sr)

        mock_info = MagicMock()
        mock_info.frames = frames
        mock_info.channels = channels
        mock_info.samplerate = sr
        mock_sf.info.return_value = mock_info

        mock_infile = MagicMock()
        mock_infile.channels = channels
        mock_sf.SoundFile.return_value.__enter__.return_value = mock_infile

        # Mocks for reads
        dummy_chunk = np.zeros((100, channels), dtype='float32')
        empty_chunk = np.zeros((0, channels), dtype='float32')

        # side_effect for read:
        # 1. Preview (RMS estimation check)
        # 2. Chunk 1
        # 3. Chunk 2 (EOF)
        mock_infile.read.side_effect = [dummy_chunk, dummy_chunk, empty_chunk]

        mock_fft.irfft.return_value = np.zeros(8192, dtype='float32')
        mock_signal.windows.hamming.return_value = np.zeros(8192, dtype='float32')

        def fftconvolve_side_effect(in1, in2, mode=None):
            l = len(in1) + len(in2) - 1
            return np.zeros(l, dtype='float32')

        mock_signal.fftconvolve.side_effect = fftconvolve_side_effect

        worker = ProcessingWorker(
            input_path="dummy.wav",
            output_path="out.wav",
            calibration_map=self.mock_calibration,
            max_gain_db=20,
            taps=8192,
            smoothing=0,
            normalize_rms=False
        )

        worker.progress = MagicMock()
        worker.finished = MagicMock()

        # Run
        worker.run()

        # Verify calls
        calls = mock_infile.read.call_args_list
        has_chunked_read = False
        has_full_read = False

        for call in calls:
            args, kwargs = call
            frames = kwargs.get('frames')
            if frames and frames > 0:
                has_chunked_read = True
            if not frames or frames == -1:
                has_full_read = True

        self.assertTrue(has_chunked_read, "Should have used chunked reading")
        self.assertFalse(has_full_read, "Should not have tried to read full file")

    @patch('src.gui.widgets.inverse_filter.sf')
    @patch('src.gui.widgets.inverse_filter.signal')
    @patch('src.gui.widgets.inverse_filter.fft_manager')
    def test_small_file_uses_fast_path(self, mock_fft, mock_signal, mock_sf):
        """Verify that small files use fast path (load all)."""
        # Setup small file (1MB)
        sr = 48000
        channels = 2
        duration = 10
        frames = int(duration * sr)

        mock_info = MagicMock()
        mock_info.frames = frames
        mock_info.channels = channels
        mock_info.samplerate = sr
        mock_sf.info.return_value = mock_info

        mock_infile = MagicMock()
        mock_infile.channels = channels
        mock_sf.SoundFile.return_value.__enter__.return_value = mock_infile

        full_data = np.zeros((frames, channels), dtype='float32')
        mock_infile.read.return_value = full_data

        mock_fft.irfft.return_value = np.zeros(8192, dtype='float32')
        mock_signal.windows.hamming.return_value = np.zeros(8192, dtype='float32')

        # oaconvolve mock for fast path
        mock_signal.oaconvolve.return_value = np.zeros((frames, channels), dtype='float32')

        worker = ProcessingWorker(
            input_path="dummy_small.wav",
            output_path="out_small.wav",
            calibration_map=self.mock_calibration,
            max_gain_db=20,
            taps=8192,
            smoothing=0,
            normalize_rms=False
        )

        worker.progress = MagicMock()
        worker.finished = MagicMock()

        worker.run()

        # Verify read call
        calls = mock_infile.read.call_args_list
        # Should be one call without frames arg (or frames=None/-1 implied)
        # But wait, read(dtype="float32")

        has_chunked_read = False
        has_full_read = False

        for call in calls:
            args, kwargs = call
            frames = kwargs.get('frames')
            if frames and frames > 0:
                has_chunked_read = True
            else:
                has_full_read = True

        self.assertTrue(has_full_read, "Should have used full reading")
        self.assertFalse(has_chunked_read, "Should not have used chunked reading")

if __name__ == '__main__':
    unittest.main()
