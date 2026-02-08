import sys
import unittest
from unittest.mock import MagicMock, patch
import numpy as np

class TestDistortionAnalyzerLogic(unittest.TestCase):
    def setUp(self):
        # Create a dictionary of mocks to inject into sys.modules
        self.modules_patcher = patch.dict(sys.modules, {})
        self.modules_patcher.start()

        # 1. Mock PyQt6 dependencies
        mock_pyqt6 = MagicMock()
        sys.modules["PyQt6"] = mock_pyqt6
        sys.modules["PyQt6.QtCore"] = mock_pyqt6.QtCore

        # Define a dummy QWidget to allow inheritance without Mock magic shadowing methods
        class MockQWidget:
            def __init__(self, *args, **kwargs):
                pass
            def setLayout(self, layout):
                pass
            def show(self):
                pass
            def close(self):
                pass
            def setFixedWidth(self, w):
                pass
            def setVisible(self, visible):
                pass
            def __getattr__(self, name):
                return MagicMock()

        mock_pyqt6.QtWidgets = MagicMock()
        mock_pyqt6.QtWidgets.QWidget = MockQWidget

        # Ensure QComboBox.currentText() returns a string to avoid logic errors
        mock_pyqt6.QtWidgets.QComboBox.return_value.currentText.return_value = "dBFS"
        mock_pyqt6.QtWidgets.QDoubleSpinBox.return_value.value.return_value = 1000.0
        mock_pyqt6.QtWidgets.QSpinBox.return_value.value.return_value = 1

        sys.modules["PyQt6.QtWidgets"] = mock_pyqt6.QtWidgets
        sys.modules["PyQt6.QtGui"] = mock_pyqt6.QtGui

        # 2. Mock pyqtgraph
        mock_pyqtgraph = MagicMock()
        sys.modules["pyqtgraph"] = mock_pyqtgraph

        # 3. Mock sounddevice
        mock_sd = MagicMock()
        sys.modules["sounddevice"] = mock_sd

        # 4. Mock AudioCalc to avoid heavy computation during logic tests
        # We need to mock src.core.analysis, but AudioCalc is a class inside it.
        # If we mock the whole module, we need to ensure structure is preserved if imported elsewhere.
        # But since we use patch.dict on sys.modules, we are safe to overwrite it for this test scope.
        self.mock_analysis = MagicMock()
        sys.modules["src.core.analysis"] = self.mock_analysis

        # Mock AudioCalc return values to prevent crashes in logic
        self.mock_analysis.AudioCalc.analyze_harmonics.return_value = {
            "thdn_percent": 0.01,
            "thdn_db": -80.0,
            "thd_percent": 0.005,
            "thd_db": -86.0,
            "sinad_db": 80.0,
            "basic_wave": {"amplitude_dbfs": -1.0, "frequency": 1000.0, "max_amplitude": 0.9},
            "harmonics": [],
            "fft_data": np.zeros(1024)
        }

        # 5. Mock FFT Manager
        mock_fft = MagicMock()
        sys.modules["src.core.fft_manager"] = mock_fft

        # 6. Mock Localization
        mock_localization = MagicMock()
        mock_localization.tr.side_effect = lambda x: str(x)
        sys.modules["src.core.localization"] = mock_localization

        # Import Module Under Test (INSIDE the patch)
        # We need to use importlib to ensure we get a fresh version using our mocks
        import importlib
        import src.gui.widgets.distortion_analyzer
        importlib.reload(src.gui.widgets.distortion_analyzer)

        self.DistortionAnalyzerWidget = src.gui.widgets.distortion_analyzer.DistortionAnalyzerWidget
        self.DistortionAnalyzer = src.gui.widgets.distortion_analyzer.DistortionAnalyzer

        # Create a mock AudioEngine
        self.mock_engine = MagicMock()
        self.mock_engine.sample_rate = 48000
        self.mock_engine.calibration.output_gain = 1.0

        # Create the module
        self.module = self.DistortionAnalyzer(self.mock_engine)

        # Mock the critical methods we want to verify are called
        self.module.request_capture = MagicMock(wraps=self.module.request_capture)

        # Instantiate the Widget
        self.widget = self.DistortionAnalyzerWidget(self.module)

        # Mock the UI components that update_realtime_analysis interacts with
        self.widget.spectrum_curve = MagicMock()
        self.widget.thdn_label = MagicMock()
        self.widget.thdn_db_label = MagicMock()
        self.widget.thd_label = MagicMock()
        self.widget.sinad_label = MagicMock()
        self.widget.detailed_label = MagicMock()
        self.widget.harmonics_table = MagicMock()
        self.widget.harmonics_bar_item = MagicMock()
        self.widget.harmonics_plot = MagicMock()

    def tearDown(self):
        # Stop patching sys.modules
        self.modules_patcher.stop()

        # Important: We must also remove the cached module of src.gui.widgets.distortion_analyzer
        # because we reloaded it with mocks. If we don't, subsequent tests might get this mocked version.
        if 'src.gui.widgets.distortion_analyzer' in sys.modules:
            del sys.modules['src.gui.widgets.distortion_analyzer']

    def test_update_realtime_analysis_race_condition_fix(self):
        """
        Verify that update_realtime_analysis uses the thread-safe capture mechanism.
        """
        # Setup: Module is running
        self.module.is_running = True
        self.module.capture_ready = False
        self.module.capture_requested = False

        # 1. First Call: Should NOT process data, but SHOULD request capture
        self.widget.update_realtime_analysis()

        # It should invoke request_capture because capture_requested was False
        self.module.request_capture.assert_called()
        self.assertTrue(self.module.capture_requested)

        # Let's check if analyze_harmonics was called.
        # If the bug exists, this will be > 0.
        call_count_bug = self.mock_analysis.AudioCalc.analyze_harmonics.call_count
        self.assertEqual(call_count_bug, 0, "Analysis should not run if capture is not ready")

        # Reset mocks
        self.mock_analysis.AudioCalc.analyze_harmonics.reset_mock()
        self.module.request_capture.reset_mock()

        # 2. Simulate Callback: Data is ready
        self.module.capture_ready = True
        self.module.captured_buffer = np.zeros(1024)
        # Note: In real logic, callback sets capture_requested = False.
        self.module.capture_requested = False

        # 3. Second Call: Should process data AND request NEXT capture
        self.widget.update_realtime_analysis()

        # Should have called analysis
        self.mock_analysis.AudioCalc.analyze_harmonics.assert_called()

        # Should have requested NEXT capture
        self.module.request_capture.assert_called()
        self.assertTrue(self.module.capture_requested)

if __name__ == '__main__':
    unittest.main()
