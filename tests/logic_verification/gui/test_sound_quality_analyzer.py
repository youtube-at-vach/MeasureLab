import sys
import unittest
from unittest.mock import MagicMock, patch
import numpy as np
import importlib
from PyQt6.QtWidgets import QApplication

class TestSoundQualityAnalyzerLogging(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Initialize QApplication in offscreen mode to allow QThread usage
        if not QApplication.instance():
            cls.app = QApplication(sys.argv + ['-platform', 'offscreen'])

    def setUp(self):
        # Mock sounddevice and soundfile
        self.mock_sd = MagicMock()
        self.mock_sf = MagicMock()

        # Patch sys.modules to inject mocks for sound libraries
        self.modules_patcher = patch.dict(sys.modules, {
            "sounddevice": self.mock_sd,
            "soundfile": self.mock_sf
        })
        self.modules_patcher.start()

    def tearDown(self):
        self.modules_patcher.stop()
        # Clean up the imported module to avoid side effects
        if "src.gui.widgets.sound_quality_analyzer" in sys.modules:
             del sys.modules["src.gui.widgets.sound_quality_analyzer"]

    def test_calc_loudness_logs_warning_on_wrong_sr(self):
        # Ensure the module is loaded with the current mocks
        import src.gui.widgets.sound_quality_analyzer
        importlib.reload(src.gui.widgets.sound_quality_analyzer)
        from src.gui.widgets.sound_quality_analyzer import AnalysisWorker

        # Instantiate worker
        # AnalysisWorker.__init__ calls super().__init__() (QThread)
        worker = AnalysisWorker("dummy_path.wav", 48000)

        audio = np.zeros(1000)
        wrong_sr = 44100

        # Assert that a warning is logged
        with self.assertLogs(level='WARNING') as cm:
            worker._calc_loudness(audio, wrong_sr)

        self.assertTrue(any("48kHz" in r for r in cm.output),
                        f"Expected log message about 48kHz, got: {cm.output}")

class TestSoundQualityAnalyzerPlaybackToggle(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Initialize QApplication in offscreen mode to allow QThread usage
        if not QApplication.instance():
            cls.app = QApplication(sys.argv + ['-platform', 'offscreen'])

    def setUp(self):
        # Mock dependencies
        self.mock_sd = MagicMock()
        self.mock_sf = MagicMock()
        self.mock_pg = MagicMock()

        self.modules_patcher = patch.dict(sys.modules, {
            "sounddevice": self.mock_sd,
            "soundfile": self.mock_sf,
            "pyqtgraph": self.mock_pg,
        })
        self.modules_patcher.start()

    def tearDown(self):
        self.modules_patcher.stop()

    @patch('src.core.localization.tr', side_effect=lambda x: x, create=True)
    def test_toggle_playback_no_data(self, mock_tr):
        from src.gui.widgets.sound_quality_analyzer import SoundQualityAnalyzer, SoundQualityAnalyzerWidget

        mock_engine = MagicMock()
        module = SoundQualityAnalyzer(mock_engine)
        widget = SoundQualityAnalyzerWidget(module)

        widget.audio_data = None
        widget.is_playing = False

        widget.toggle_playback()

        self.assertFalse(widget.is_playing)
        mock_engine.register_callback.assert_not_called()

    @patch('src.core.localization.tr', side_effect=lambda x: x, create=True)
    def test_toggle_playback_start_playing(self, mock_tr):
        from src.gui.widgets.sound_quality_analyzer import SoundQualityAnalyzer, SoundQualityAnalyzerWidget

        mock_engine = MagicMock()
        mock_engine.register_callback.return_value = 123
        module = SoundQualityAnalyzer(mock_engine)
        widget = SoundQualityAnalyzerWidget(module)

        widget.audio_data = np.zeros(100)
        widget.is_playing = False
        widget.playback_position = 100 # At end
        widget.playback_timer = MagicMock()

        widget.toggle_playback()

        self.assertTrue(widget.is_playing)
        self.assertEqual(widget.play_btn.text(), "⏸")
        self.assertEqual(widget.playback_position, 0)
        mock_engine.register_callback.assert_called_once_with(widget.audio_callback)
        self.assertEqual(widget.callback_id, 123)
        widget.playback_timer.start.assert_called_once()

    @patch('src.core.localization.tr', side_effect=lambda x: x, create=True)
    def test_toggle_playback_stop_playing(self, mock_tr):
        from src.gui.widgets.sound_quality_analyzer import SoundQualityAnalyzer, SoundQualityAnalyzerWidget

        mock_engine = MagicMock()
        module = SoundQualityAnalyzer(mock_engine)
        widget = SoundQualityAnalyzerWidget(module)

        widget.audio_data = np.zeros(100)
        widget.is_playing = True
        widget.callback_id = 123
        widget.playback_timer = MagicMock()

        widget.toggle_playback()

        self.assertFalse(widget.is_playing)
        self.assertEqual(widget.play_btn.text(), "▶")
        mock_engine.unregister_callback.assert_called_once_with(123)
        self.assertIsNone(widget.callback_id)
        widget.playback_timer.stop.assert_called_once()
