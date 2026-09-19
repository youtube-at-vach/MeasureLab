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
            cls.app = QApplication(sys.argv + ["-platform", "offscreen"])

    def setUp(self):
        # Mock sounddevice and soundfile
        self.mock_sd = MagicMock()
        self.mock_sf = MagicMock()

        # Patch sys.modules to inject mocks for sound libraries
        self.modules_patcher = patch.dict(sys.modules, {"sounddevice": self.mock_sd, "soundfile": self.mock_sf})
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
        with self.assertLogs(level="WARNING") as cm:
            worker._calc_loudness(audio, wrong_sr)

        self.assertTrue(any("48kHz" in r for r in cm.output), f"Expected log message about 48kHz, got: {cm.output}")


class TestSoundQualityAnalyzerPlaybackToggle(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Initialize QApplication in offscreen mode to allow QThread usage
        if not QApplication.instance():
            cls.app = QApplication(sys.argv + ["-platform", "offscreen"])

    def setUp(self):
        # Mock dependencies
        self.mock_sd = MagicMock()
        self.mock_sf = MagicMock()
        self.mock_pg = MagicMock()

        self.modules_patcher = patch.dict(
            sys.modules,
            {
                "sounddevice": self.mock_sd,
                "soundfile": self.mock_sf,
                "pyqtgraph": self.mock_pg,
            },
        )
        self.modules_patcher.start()

    def tearDown(self):
        self.modules_patcher.stop()

    @patch("src.core.localization.tr", side_effect=lambda x: x, create=True)
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

    @patch("src.core.localization.tr", side_effect=lambda x: x, create=True)
    def test_toggle_playback_start_playing(self, mock_tr):
        from src.gui.widgets.sound_quality_analyzer import SoundQualityAnalyzer, SoundQualityAnalyzerWidget

        mock_engine = MagicMock()
        mock_engine.register_callback.return_value = 123
        module = SoundQualityAnalyzer(mock_engine)
        widget = SoundQualityAnalyzerWidget(module)

        widget.audio_data = np.zeros(100)
        widget.is_playing = False
        widget.playback_position = 100  # At end
        widget.playback_timer = MagicMock()

        widget.toggle_playback()

        self.assertTrue(widget.is_playing)
        self.assertEqual(widget.play_btn.text(), "⏸")
        self.assertEqual(widget.playback_position, 0)
        mock_engine.register_callback.assert_called_once_with(widget.audio_callback)
        self.assertEqual(widget.callback_id, 123)
        widget.playback_timer.start.assert_called_once()

    @patch("src.core.localization.tr", side_effect=lambda x: x, create=True)
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


class TestSoundQualityAnalyzerResultIntegrity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not QApplication.instance():
            cls.app = QApplication(sys.argv + ["-platform", "offscreen"])

    def test_analysis_is_independent_of_playback_sample_rate(self):
        from src.gui.widgets import sound_quality_analyzer as analyzer

        # A 10 kHz component is lost in 16 kHz playback, but must remain in analysis.
        for source_sr in (44100, 48000):
            with self.subTest(source_sr=source_sr):
                t = np.arange(source_sr) / source_sr
                audio = np.column_stack((0.1 * np.sin(2 * np.pi * 10000 * t), 0.2 * np.sin(2 * np.pi * 1000 * t)))
                results = []
                for target_sr in (48000, 16000, 44100):
                    worker = analyzer.AnalysisWorker("source.wav", target_sr)
                    errors = []
                    worker.results_ready.connect(results.append)
                    worker.error_occurred.connect(errors.append)
                    with (
                        patch.object(analyzer.sf, "read", return_value=(audio, source_sr)),
                        patch.object(analyzer.AudioCalc, "validate_audio_file_size", return_value=(True, "")),
                    ):
                        worker.run()
                    self.assertEqual(errors, [])
                    result = results[-1]
                    self.assertEqual(result["samplerate"], target_sr)
                    self.assertEqual(result["audio_data"].shape, (target_sr, 2))
                    self.assertEqual(result["audio_data"].dtype, np.float32)
                    self.assertAlmostEqual(result["duration"], 1.0)

                self.assertEqual(len(results), 3)
                for result in results[1:]:
                    for expected, actual in zip(results[0]["channels"], result["channels"], strict=True):
                        self.assertEqual(expected.keys(), actual.keys())
                        for key in expected:
                            if key == "name":
                                self.assertEqual(expected[key], actual[key])
                            else:
                                np.testing.assert_allclose(actual[key], expected[key], rtol=1e-12, atol=1e-12)

    def _widget_with_results(self):
        from src.gui.widgets.sound_quality_analyzer import SoundQualityAnalyzer, SoundQualityAnalyzerWidget

        engine = MagicMock(sample_rate=48000)
        widget = SoundQualityAnalyzerWidget(SoundQualityAnalyzer(engine))
        self.addCleanup(widget.close)
        widget.current_file = "old.wav"
        widget.file_label.setText(widget.current_file)
        widget.plot_series = MagicMock()
        results = {
            "samplerate": 48000,
            "audio_data": np.zeros(48000, dtype=np.float32),
            "channels": [
                {
                    "name": "Mono",
                    "integrated_lufs": -20.0,
                    "mean_sharpness": 1.0,
                    "mean_roughness": 0.1,
                    "mean_tonality": 0.8,
                    "mean_fluctuation": 0.2,
                    "mean_ai": 0.5,
                }
            ],
        }
        widget.on_results(results)
        return widget, engine, results

    def _assert_results_cleared(self, widget):
        self.assertIsNone(widget.analysis_results)
        self.assertIsNone(widget.audio_data)
        self.assertFalse(widget.is_playing)
        self.assertIsNone(widget.callback_id)
        self.assertFalse(widget.playback_timer.isActive())
        self.assertEqual(widget.playback_position, 0)
        for button in (widget.play_btn, widget.stop_btn, widget.export_btn):
            self.assertFalse(button.isEnabled())
        self.assertEqual(widget.summary_table.item(0, 1).text(), "-")
        self.assertEqual(widget.cursors, [])
        self.assertIsNone(widget.p1)
        widget.toggle_playback()
        self.assertFalse(widget.is_playing)
        with patch("src.gui.widgets.sound_quality_analyzer.QFileDialog.getSaveFileName") as save:
            widget.export_csv()
        save.assert_not_called()

    def test_selecting_new_file_discards_old_results_and_stops_playback(self):
        widget, engine, _ = self._widget_with_results()
        engine.register_callback.return_value = 123
        widget.toggle_playback()
        widget.cursors = [MagicMock()]
        with patch("src.gui.widgets.sound_quality_analyzer.QFileDialog.getOpenFileName", return_value=("new.wav", "")):
            widget.load_file()
        self.assertEqual(widget.current_file, "new.wav")
        self.assertEqual(widget.file_label.text(), "new.wav")
        self.assertTrue(widget.analyze_btn.isEnabled())
        engine.unregister_callback.assert_called_once_with(123)
        self._assert_results_cleared(widget)

    def test_cancelling_file_dialog_preserves_results(self):
        widget, _, results = self._widget_with_results()
        with patch("src.gui.widgets.sound_quality_analyzer.QFileDialog.getOpenFileName", return_value=("", "")):
            widget.load_file()
        self.assertEqual(widget.current_file, "old.wav")
        self.assertIs(widget.analysis_results, results)
        self.assertIs(widget.audio_data, results["audio_data"])
        self.assertTrue(widget.export_btn.isEnabled())
        self.assertTrue(widget.play_btn.isEnabled())

    def test_reanalysis_clears_results_and_failure_keeps_them_unavailable(self):
        widget, _, results = self._widget_with_results()
        with patch("src.gui.widgets.sound_quality_analyzer.AnalysisWorker") as worker_type:
            worker_type.return_value.isRunning.return_value = False
            widget.start_analysis()
        self._assert_results_cleared(widget)
        self.assertFalse(widget.analyze_btn.isEnabled())
        self.assertFalse(widget.load_btn.isEnabled())
        worker_type.assert_called_once_with("old.wav", 48000)
        worker_type.return_value.start.assert_called_once()

        widget.on_error("Cannot read file")
        self._assert_results_cleared(widget)
        self.assertTrue(widget.analyze_btn.isEnabled())
        self.assertTrue(widget.load_btn.isEnabled())

        # A successful retry makes its new results available again.
        widget.on_results(results)
        self.assertIs(widget.analysis_results, results)
        self.assertIs(widget.audio_data, results["audio_data"])
        self.assertTrue(widget.play_btn.isEnabled())
        self.assertTrue(widget.stop_btn.isEnabled())
        self.assertTrue(widget.export_btn.isEnabled())
        self.assertEqual(widget.summary_table.item(0, 1).text(), "-20.0")
