import unittest
from unittest.mock import MagicMock, patch
import sys

class TestUnboundedLoading(unittest.TestCase):
    def setUp(self):
        # Create dummy Qt classes
        class MockQThread:
            def __init__(self):
                pass
            def start(self):
                self.run()
            def wait(self):
                pass
            def run(self):
                pass
            def terminate(self):
                pass

        # Mock pyqtSignal to return a MagicMock
        def MockPyqtSignal(*args):
            m = MagicMock()
            m.emit = MagicMock()
            return m

        # Create mock module for QtCore
        mock_qt_core = MagicMock()
        mock_qt_core.QThread = MockQThread
        mock_qt_core.pyqtSignal = MockPyqtSignal
        mock_qt_core.Qt = MagicMock()

        # Patch sys.modules to mock dependencies that might cause issues in headless env
        self.modules_patcher = patch.dict(sys.modules, {
            'sounddevice': MagicMock(),
            'PyQt6.QtCore': mock_qt_core,
            'PyQt6.QtWidgets': MagicMock(),
            'pyqtgraph': MagicMock(),
            'numpy': MagicMock(),
            'scipy': MagicMock(),
            'scipy.signal': MagicMock(),
            'scipy.optimize': MagicMock(),
            'scipy.interpolate': MagicMock(),
            'netCDF4': MagicMock(),
            'soundfile': MagicMock(), # We will patch functions individually but the module needs to exist
        })
        self.modules_patcher.start()

        # Import AudioCalc locally
        from src.core.analysis import AudioCalc
        self.AudioCalc = AudioCalc

    def tearDown(self):
        self.modules_patcher.stop()

    def test_audiocalc_validation(self):
        """Test AudioCalc.validate_audio_file_size directly."""
        with patch('soundfile.info') as mock_info:
            # Case 1: Small file (OK)
            mock_info.return_value = MagicMock(frames=1000, channels=2, samplerate=48000)
            valid, msg = self.AudioCalc.validate_audio_file_size("dummy.wav")
            self.assertTrue(valid, f"Validation failed for small file. Msg: {msg}")
            self.assertEqual(msg, "OK")

            # Case 2: Huge file (Fail)
            # Limit is 500,000,000
            # 300M * 2 = 600M > 500M
            mock_info.return_value = MagicMock(frames=300_000_000, channels=2, samplerate=48000)
            valid, msg = self.AudioCalc.validate_audio_file_size("huge.wav")
            self.assertFalse(valid)
            self.assertIn("File too large", msg)

            # Case 3: Error reading info
            mock_info.side_effect = Exception("Corrupt file")
            valid, msg = self.AudioCalc.validate_audio_file_size("corrupt.wav")
            self.assertFalse(valid)
            self.assertIn("Failed to read file info", msg)

    def test_recorder_player_rejects_large_file(self):
        """Test RecorderPlayer rejects large files."""
        # Ensure module is re-imported if needed or just imported
        if 'src.gui.widgets.recorder_player' in sys.modules:
            del sys.modules['src.gui.widgets.recorder_player']

        from src.gui.widgets.recorder_player import FileLoadWorker

        worker = FileLoadWorker("huge.wav", 48000)

        # Manually attach a mock emit because the class attribute mock might be shared or tricky
        worker.finished = MagicMock()
        worker.finished.emit = MagicMock()

        with patch('soundfile.info') as mock_info, \
             patch('soundfile.read') as mock_read:

            # Simulate large file
            mock_info.return_value = MagicMock(frames=300_000_000, channels=2, samplerate=48000)

            worker.run()

            # Should have emitted False
            worker.finished.emit.assert_called_with(False, None, unittest.mock.ANY)
            args, _ = worker.finished.emit.call_args
            self.assertIn("File too large", args[2])

            # Should NOT have called read
            mock_read.assert_not_called()

    def test_sound_quality_analyzer_rejects_large_file(self):
        """Test SoundQualityAnalyzer rejects large files."""
        if 'src.gui.widgets.sound_quality_analyzer' in sys.modules:
            del sys.modules['src.gui.widgets.sound_quality_analyzer']

        from src.gui.widgets.sound_quality_analyzer import AnalysisWorker

        worker = AnalysisWorker("huge.wav", 48000)

        # Setup mocks for signals
        worker.error_occurred = MagicMock()
        worker.error_occurred.emit = MagicMock()
        worker.progress_update = MagicMock()
        worker.progress_update.emit = MagicMock()
        worker.results_ready = MagicMock()

        with patch('soundfile.info') as mock_info, \
             patch('soundfile.read') as mock_read:

            # Simulate large file
            mock_info.return_value = MagicMock(frames=300_000_000, channels=2, samplerate=48000)

            worker.run()

            # Should have emitted error
            worker.error_occurred.emit.assert_called_with(unittest.mock.ANY)
            args, _ = worker.error_occurred.emit.call_args
            self.assertIn("File too large", args[0])

            # Should NOT have called read
            mock_read.assert_not_called()

    def test_hrtf_player_rejects_large_music(self):
        """Test HRTFPlayer rejects large music files."""
        if 'src.gui.widgets.hrtf_player' in sys.modules:
            del sys.modules['src.gui.widgets.hrtf_player']

        from src.gui.widgets.hrtf_player import HRTFPlayer

        audio_engine = MagicMock()
        player = HRTFPlayer(audio_engine)

        with patch('soundfile.info') as mock_info, \
             patch('soundfile.read') as mock_read:

            # Simulate large file
            mock_info.return_value = MagicMock(frames=300_000_000, channels=2, samplerate=48000)

            success, msg = player.load_music("huge.wav")

            self.assertFalse(success)
            self.assertIn("File too large", msg)
            mock_read.assert_not_called()

if __name__ == '__main__':
    unittest.main()
