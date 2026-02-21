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
