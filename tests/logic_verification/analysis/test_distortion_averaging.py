import sys
from unittest.mock import MagicMock, patch
import unittest
import numpy as np

# Mock GUI dependencies BEFORE import
mock_qt_core = MagicMock()


class MockQObject:
    def __init__(self):
        pass


class MockQThread:
    def __init__(self):
        pass


mock_qt_core.QObject = MockQObject
mock_qt_core.QThread = MockQThread
mock_qt_core.pyqtSignal = MagicMock(side_effect=lambda *args: MagicMock())
mock_qt_core.Qt.AlignmentFlag.AlignRight = 1
mock_qt_core.Qt.AlignmentFlag.AlignVCenter = 2
mock_qt_core.Qt.AlignmentFlag.AlignLeft = 3
mock_qt_core.Qt.AlignmentFlag.AlignTop = 4

class MockQWidget:
    def __init__(self, *args, **kwargs):
        pass

class MockQHeaderView(MagicMock):
    class ResizeMode:
        Stretch = 1

class DummyQtWidgets:
    QWidget = MockQWidget
    QHeaderView = MockQHeaderView
    QComboBox = MagicMock
    QDoubleSpinBox = MagicMock
    QFormLayout = MagicMock
    QGroupBox = MagicMock
    QHBoxLayout = MagicMock
    QLabel = MagicMock
    QPushButton = MagicMock
    QSpinBox = MagicMock
    QStackedWidget = MagicMock
    QTableWidget = MagicMock
    QTableWidgetItem = MagicMock
    QTabWidget = MagicMock
    QVBoxLayout = MagicMock

mock_widgets = DummyQtWidgets()

mock_modules = {
    "PyQt6": MagicMock(),
    "PyQt6.QtCore": mock_qt_core,
    "PyQt6.QtGui": MagicMock(),
    "PyQt6.QtWidgets": mock_widgets,
    "pyqtgraph": MagicMock(),
}


class MockAudioEngine:
    def __init__(self):
        self.sample_rate = 48000
        self.calibration = MagicMock()
        self.calibration.output_gain = 1.0

    def register_callback(self, cb):
        return 1

    def unregister_callback(self, cid):
        pass


class TestDistortionAveraging(unittest.TestCase):
    def setUp(self):
        self.patcher = patch.dict(sys.modules, mock_modules)
        self.patcher.start()
        # Force reload
        if "src.gui.widgets.distortion_analyzer" in sys.modules:
            del sys.modules["src.gui.widgets.distortion_analyzer"]

    def tearDown(self):
        self.patcher.stop()

    def test_thd_validity_logic(self):
        from src.gui.widgets.distortion_analyzer import DistortionAnalyzer

        engine = MockAudioEngine()
        analyzer = DistortionAnalyzer(engine)

        # Helper from verify_lo_logic.py
        def make_results(fund_rms, res_rms, harmonics, fund_amp=1.0):
            thd_linear = np.sqrt(np.sum(harmonics**2)) / fund_amp if fund_amp > 0 else 0
            thdn_linear = res_rms / fund_rms if fund_rms > 0 else 0

            return {
                "raw_fund_rms": fund_rms,
                "raw_res_rms": res_rms,
                "raw_fund_amp": fund_amp,
                "basic_wave": {"frequency": 1000, "amplitude_dbfs": -1.0},
                "raw_harmonics": harmonics,
                "fft_data": np.zeros(10),
                "thd_percent": thd_linear * 100,
                "thdn_percent": thdn_linear * 100,
            }

        # Case 1: No Averaging, Invalid (THD+N < THD)
        analyzer.average_count = 1  # Verify logic handles count=1 too

        # THD = 1%, THD+N = 0.5% (Impossible)
        results_invalid_no_avg = make_results(fund_rms=1.0, res_rms=0.005, harmonics=np.array([0.01]))

        out_1 = analyzer._apply_result_averaging(results_invalid_no_avg)
        self.assertFalse(out_1.get("thd_valid"), "Case 1 failed: Should be invalid")

        # Case 2: Averaging ON, Valid
        analyzer.average_count = 5  # Set some averaging
        analyzer.reset_averaging_state()

        # THD = 1%, THD+N = 1.41% (Valid)
        # Noise = Distortion level => RMS = sqrt(dist^2 + noise^2)
        results_valid_avg = make_results(fund_rms=1.0, res_rms=np.sqrt(0.01**2 + 0.01**2), harmonics=np.array([0.01]))

        # Feed twice to start averaging
        out_2 = analyzer._apply_result_averaging(results_valid_avg)
        self.assertTrue(out_2.get("thd_valid"), "Case 2 failed: Should be valid")

        # Case 3: Averaging ON, Invalid
        analyzer.reset_averaging_state()
        # THD = 1%, THD+N = 0.5% (Impossible)
        results_invalid_avg = make_results(fund_rms=1.0, res_rms=0.005, harmonics=np.array([0.01]))

        out_3 = analyzer._apply_result_averaging(results_invalid_avg)
        self.assertFalse(out_3.get("thd_valid"), "Case 3 failed: Should be invalid")


if __name__ == "__main__":
    unittest.main()
