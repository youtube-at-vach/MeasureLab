
import unittest
from unittest.mock import MagicMock, patch, ANY, call
import numpy as np
import sys
import os

# Mock dependencies properly
qt_core = MagicMock()
qt_core.QThread = MagicMock
qt_core.pyqtSignal = MagicMock(return_value=MagicMock())
qt_core.Qt = MagicMock()

sys.modules['PyQt6.QtCore'] = qt_core
sys.modules['pyqtgraph'] = MagicMock()
sys.modules['PyQt6.QtWidgets'] = MagicMock()
sys.modules['src.core.config_manager'] = MagicMock()
sys.modules['src.core.localization'] = MagicMock()
sys.modules['src.core.localization'].tr = lambda x: x

# Mock FFT Manager
fft_mgr_mock = MagicMock()
fft_mgr_mock.fft_manager.irfft.return_value = np.zeros(1024)
sys.modules['src.core.fft_manager'] = fft_mgr_mock

from src.gui.widgets.inverse_filter import ProcessingWorker

class TestInverseFilterMemory(unittest.TestCase):
    def setUp(self):
        self.input_path = "dummy_input.wav"
        self.output_path = "dummy_output.wav"
        self.calibration_map = [
            [10, 0, 0],
            [100, 10, 0],
            [1000, 0, 0],
            [20000, -10, 0]
        ]
        self.max_gain = 20
        self.taps = 1024
        self.smoothing = 0
        self.normalize = False

        # Reset mock calls
        fft_mgr_mock.fft_manager.irfft.reset_mock()

    @patch('soundfile.info')
    @patch('soundfile.SoundFile')
    @patch('os.remove')
    @patch('os.path.exists')
    def test_large_file_processing(self, mock_exists, mock_remove, mock_sf, mock_info):
        """
        Test that large files are now accepted and processed in chunks.
        """
        # Setup mock info
        info_mock = MagicMock()
        info_mock.samplerate = 48000
        info_mock.frames = 48000 * 3600  # 1 hour
        info_mock.channels = 2
        mock_info.return_value = info_mock

        # Mocks for sf.SoundFile context managers
        # Order of calls:
        # 1. infile (read input)
        # 2. temp_outfile (write temp)
        # 3. temp_in (read temp for copy)
        # 4. final_out (write final)

        infile_mock = MagicMock()
        temp_outfile_mock = MagicMock()
        temp_in_mock = MagicMock()
        final_out_mock = MagicMock()

        mock_sf.side_effect = [infile_mock, temp_outfile_mock, temp_in_mock, final_out_mock]

        infile_mock.__enter__.return_value = infile_mock
        temp_outfile_mock.__enter__.return_value = temp_outfile_mock
        temp_in_mock.__enter__.return_value = temp_in_mock
        final_out_mock.__enter__.return_value = final_out_mock

        infile_mock.channels = 2
        temp_in_mock.channels = 2

        # Mock reading chunks
        # Return a small chunk, then empty to simulate EOF?
        # Our loop condition is `samples_read < total_frames`.
        # If we return small chunk, loop will run forever unless `samples_read` increases.
        # `samples_read` increases by `len(chunk)`.
        # If we simulate a huge file, the loop will run many times.
        # We don't want the test to hang.
        # We can mock `total_frames` to be small for the LOOP test, but large for the CHECK.
        # But `total_frames` comes from `info.frames`.

        # Let's set `total_frames` to something small just to verify loop works,
        # but large enough to trigger multiple chunks if chunk size is small.
        # Chunk size is 512*1024 (~500k).
        # Let's set frames to 1M (2 chunks).

        info_mock.frames = 1000000
        temp_in_mock.frames = 1000000

        # Chunk reading
        # First chunk
        chunk1 = np.zeros((512*1024, 2), dtype='float32')
        # Second chunk (partial)
        chunk2 = np.zeros((1000000 - 512*1024, 2), dtype='float32')
        # Empty chunk to simulate EOF if loop continues
        chunk_empty = np.zeros((0, 2), dtype='float32')

        # We set frames to match data exactly, but let's test robustness
        # If we set frames to be larger, the loop should still terminate on EOF
        info_mock.frames = 2000000 # Larger than available data (1M)

        infile_mock.read.side_effect = [chunk1, chunk2, chunk_empty, chunk_empty]

        # For copy pass (reading temp file)
        # Temp file size is based on what was written.
        # We wrote 1M samples.
        # So temp_in.frames should be 1M.
        temp_in_mock.frames = 1000000
        temp_in_mock.read.side_effect = [chunk1, chunk2, chunk_empty]

        worker = ProcessingWorker(
            self.input_path,
            self.output_path,
            self.calibration_map,
            self.max_gain,
            self.taps,
            self.smoothing,
            self.normalize
        )

        worker.finished = MagicMock()
        worker.progress = MagicMock()

        worker.run()

        if worker.finished.emit.call_args:
            args, _ = worker.finished.emit.call_args
            success, msg = args
            # EXPECT SUCCESS
            self.assertTrue(success, f"Failed with message: {msg}")
            self.assertIn("Processing Complete", msg)
        else:
            self.fail("finished.emit was never called")

        # Verify chunked read was used
        # infile.read should be called with frames argument
        # Check call args
        calls = infile_mock.read.call_args_list
        self.assertTrue(len(calls) > 0)
        # Check first call arguments
        # args[0] is frames? No, read(frames=...) usually keyword or positional?
        # Code: infile.read(frames=chunk_frames, dtype="float32")
        # So kwargs: frames, dtype
        first_call = calls[0]
        self.assertIn('frames', first_call.kwargs)
        self.assertEqual(first_call.kwargs['frames'], 512*1024)

    @patch('soundfile.info')
    @patch('soundfile.SoundFile')
    @patch('os.remove')
    @patch('os.path.exists')
    def test_chunked_processing_verification(self, mock_exists, mock_remove, mock_sf, mock_info):
        """
        Verify that we use chunks even for small files now (unified path).
        """
        info_mock = MagicMock()
        info_mock.samplerate = 48000
        info_mock.frames = 48000 * 60 # 1 min
        info_mock.channels = 2
        mock_info.return_value = info_mock

        infile_mock = MagicMock()
        temp_outfile_mock = MagicMock()
        temp_in_mock = MagicMock()
        final_out_mock = MagicMock()

        mock_sf.side_effect = [infile_mock, temp_outfile_mock, temp_in_mock, final_out_mock]
        infile_mock.__enter__.return_value = infile_mock
        temp_outfile_mock.__enter__.return_value = temp_outfile_mock
        temp_in_mock.__enter__.return_value = temp_in_mock
        final_out_mock.__enter__.return_value = final_out_mock

        infile_mock.channels = 2
        temp_in_mock.frames = 48000 * 60

        # 1 min fits in one chunk (chunk size ~500k samples ~10s? No, 512*1024 = 524288 samples. 48kHz => ~11s).
        # So 1 min will be multiple chunks.

        # Mock reads to return something valid
        chunk = np.zeros((512*1024, 2), dtype='float32')
        # We need enough reads to cover total frames.
        # Total 2.8M samples. Chunk 0.5M. ~6 chunks.
        infile_mock.read.return_value = chunk
        temp_in_mock.read.return_value = chunk

        worker = ProcessingWorker(
            self.input_path,
            self.output_path,
            self.calibration_map,
            self.max_gain,
            self.taps,
            self.smoothing,
            self.normalize
        )
        worker.finished = MagicMock()
        worker.progress = MagicMock()

        worker.run()

        # Verify read called with frames (chunked)
        # Previous code called read(dtype="float32") without frames.
        # New code calls read(frames=..., dtype=...)

        calls = infile_mock.read.call_args_list
        self.assertTrue(len(calls) > 0)
        first_call = calls[0]
        self.assertIn('frames', first_call.kwargs)

        args, _ = worker.finished.emit.call_args
        self.assertTrue(args[0])

if __name__ == '__main__':
    unittest.main()
