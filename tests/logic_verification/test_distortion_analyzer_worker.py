import sys
import unittest
from unittest.mock import MagicMock, patch
import numpy as np

# --- Mocks for Dependencies ---
# We mock these BEFORE importing the module under test to avoid ImportErrors
# in environments without GUI/Audio libraries.

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

sys.modules["PyQt6.QtWidgets"] = mock_pyqt6.QtWidgets
sys.modules["PyQt6.QtGui"] = mock_pyqt6.QtGui

mock_pyqtgraph = MagicMock()
sys.modules["pyqtgraph"] = mock_pyqtgraph

# Mock sounddevice
mock_sd = MagicMock()
sys.modules["sounddevice"] = mock_sd

# Mock AudioCalc to avoid heavy computation during logic tests
mock_analysis = MagicMock()
sys.modules["src.core.analysis"] = mock_analysis

# Mock FFT Manager
mock_fft = MagicMock()
sys.modules["src.core.fft_manager"] = mock_fft

# Mock Localization
mock_localization = MagicMock()
mock_localization.tr.side_effect = lambda x: str(x)
sys.modules["src.core.localization"] = mock_localization

# Ensure QComboBox.currentText() returns a string to avoid logic errors
mock_pyqt6.QtWidgets.QComboBox.return_value.currentText.return_value = "dBFS"
mock_pyqt6.QtWidgets.QDoubleSpinBox.return_value.value.return_value = 1000.0
mock_pyqt6.QtWidgets.QSpinBox.return_value.value.return_value = 1

# --- Import Module Under Test ---
# Now it's safe to import
# Note: We need to import the exact classes we are testing
# But since we mocked the imports inside it, we have to rely on `importlib` or standard import
# provided the file structure matches.

# Since we are in tests/logic_verification/, and src/ is at root.
# We need to make sure src is in path. It usually is in pytest.

from src.gui.widgets.distortion_analyzer import DistortionAnalyzerWidget, DistortionAnalyzer

class TestDistortionAnalyzerLogic(unittest.TestCase):
    def setUp(self):
        # Create a mock AudioEngine
        self.mock_engine = MagicMock()
        self.mock_engine.sample_rate = 48000
        self.mock_engine.calibration.output_gain = 1.0

        # Create the module
        self.module = DistortionAnalyzer(self.mock_engine)

        # Mock the critical methods we want to verify are called
        self.module.request_capture = MagicMock(wraps=self.module.request_capture)

        # Instantiate the Widget
        # We need to patch QWidget.__init__ because the real one is mocked but might need handling
        # Actually, since PyQt6 is mocked, QWidget is a MagicMock.
        # Calling DistortionAnalyzerWidget(module) will call QWidget.__init__, which is fine on a Mock.

        # However, init_ui calls many QT methods.
        # We want to ensure it doesn't crash.
        self.widget = DistortionAnalyzerWidget(self.module)

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

        # Mock AudioCalc return values to prevent crashes in logic
        mock_analysis.AudioCalc.analyze_harmonics.return_value = {
            "thdn_percent": 0.01,
            "thdn_db": -80.0,
            "thd_percent": 0.005,
            "thd_db": -86.0,
            "sinad_db": 80.0,
            "basic_wave": {"amplitude_dbfs": -1.0, "frequency": 1000.0, "max_amplitude": 0.9},
            "harmonics": [],
            "fft_data": np.zeros(1024)
        }

    def tearDown(self):
        # Clean up if needed
        pass

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

        # It should NOT have called analyze_harmonics (because capture wasn't ready)
        # Wait, the CURRENT buggy implementation accesses input_data directly and calls analyze_harmonics.
        # So in the buggy version, this assertion will FAIL (it WILL call analyze_harmonics).
        # In the FIXED version, it should NOT call analyze_harmonics until capture is ready.

        # Let's check if analyze_harmonics was called.
        # If the bug exists, this will be > 0.
        call_count_bug = mock_analysis.AudioCalc.analyze_harmonics.call_count
        self.assertEqual(call_count_bug, 0, "Analysis should not run if capture is not ready")

        # Reset mocks
        mock_analysis.AudioCalc.analyze_harmonics.reset_mock()
        self.module.request_capture.reset_mock()

        # 2. Simulate Callback: Data is ready
        self.module.capture_ready = True
        self.module.captured_buffer = np.zeros(1024)
        # Note: In real logic, callback sets capture_requested = False.
        self.module.capture_requested = False

        # 3. Second Call: Should process data AND request NEXT capture
        self.widget.update_realtime_analysis()

        # Should have called analysis
        mock_analysis.AudioCalc.analyze_harmonics.assert_called()

        # Should have requested NEXT capture
        self.module.request_capture.assert_called()
        self.assertTrue(self.module.capture_requested)

if __name__ == '__main__':
    unittest.main()
