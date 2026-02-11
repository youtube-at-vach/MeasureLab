
import unittest
from unittest.mock import MagicMock, patch
import sys
import numpy as np

# --- Mocking Setup to Import SpectrogramWidget without GUI ---

# Define mocks globally so they can be pickled if needed (unlikely for tests but cleaner)
class MockQWidget:
    def __init__(self, *args, **kwargs):
        pass
    def setLayout(self, layout):
        pass
    def closeEvent(self, event):
        pass
    # Add sizePolicy for buttons
    def sizePolicy(self):
        m = MagicMock()
        m.horizontalPolicy.return_value = MagicMock()
        m.verticalPolicy.return_value = MagicMock()
        return m

class MockMeasurementModule:
    """Mock base class for MeasurementModule since we can't import the real one easily without deps."""
    def __init__(self, audio_engine=None):
        self.audio_engine = audio_engine
        self.is_running = False
    def stop_analysis(self):
        pass

class TestSpectrogramLogic(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Create mocks for PyQt6 modules
        mock_qt_widgets = MagicMock()
        mock_qt_widgets.QWidget = MockQWidget
        mock_qt_widgets.QGroupBox = MagicMock()
        mock_qt_widgets.QHBoxLayout = MagicMock()
        mock_qt_widgets.QVBoxLayout = MagicMock()
        mock_qt_widgets.QGridLayout = MagicMock()
        mock_qt_widgets.QLabel = MagicMock()
        mock_qt_widgets.QPushButton = MagicMock()

        # Configure QComboBox mock specifically to handle logic
        class MockQComboBox(MagicMock):
            def findText(self, text):
                return -1 # Default to not found for init logic
        mock_qt_widgets.QComboBox = MockQComboBox

        # Make QSpinBox return distinct mocks for each instantiation
        mock_qt_widgets.QSpinBox.side_effect = lambda *args, **kwargs: MagicMock()

        mock_qt_widgets.QApplication = MagicMock()

        mock_qt_core = MagicMock()
        mock_qt_core.QTimer = MagicMock()
        # Mock Qt enum if needed
        mock_qt_core.Qt = MagicMock()

        mock_qt_gui = MagicMock()
        mock_qt_gui.QTransform = MagicMock()

        # Mock pyqtgraph
        mock_pg = MagicMock()
        mock_pg.GraphicsLayoutWidget = MagicMock()
        mock_pg.ImageItem = MagicMock()
        mock_pg.HistogramLUTItem = MagicMock()

        # Mock application-specific modules
        mock_audio_engine = MagicMock()
        mock_analysis = MagicMock()
        mock_localization = MagicMock()
        mock_localization.tr = lambda x: x # Simple identity for translation

        # Prepare the patcher
        # We patch sys.modules so that when `src.gui.widgets.spectrogram` imports these, it gets our mocks.
        cls.modules_patcher = patch.dict(sys.modules, {
            "PyQt6": MagicMock(),
            "PyQt6.QtCore": mock_qt_core,
            "PyQt6.QtGui": mock_qt_gui,
            "PyQt6.QtWidgets": mock_qt_widgets,
            "pyqtgraph": mock_pg,
            "src.core.audio_engine": mock_audio_engine,
            "src.core.analysis": mock_analysis,
            "src.core.localization": mock_localization,
            "src.measurement_modules.base": MagicMock(), # Will inject class below
            "src.core.fft_manager": MagicMock(),
            "src.gui.styles": MagicMock(),
        })
        cls.modules_patcher.start()

        # Inject the base class into the mocked module
        sys.modules["src.measurement_modules.base"].MeasurementModule = MockMeasurementModule

        # Import the module under test
        try:
            # Force remove the module from sys.modules if it was already loaded
            # This ensures we get a fresh import using our mocked dependencies (PyQt6, etc.)
            # The patcher will restore the original module (if any) when stopped.
            if "src.gui.widgets.spectrogram" in sys.modules:
                del sys.modules["src.gui.widgets.spectrogram"]

            from src.gui.widgets import spectrogram
            cls.spectrogram_module = spectrogram
        except ImportError as e:
            # If import fails, stop patcher and fail
            cls.modules_patcher.stop()
            raise RuntimeError(f"Failed to import spectrogram module: {e}") from e

    @classmethod
    def tearDownClass(cls):
        cls.modules_patcher.stop()

    def setUp(self):
        # Create a mock Spectrogram module (the data model, not the python module)
        self.mock_spec_model = MagicMock()
        self.mock_spec_model.fft_size = 2048
        self.mock_spec_model.window_type = "hann"
        self.mock_spec_model.min_freq = 20
        self.mock_spec_model.max_freq = 20000
        # Mock other attributes accessed during init
        self.mock_spec_model.channel_mode = "Left"
        self.mock_spec_model.sweep_speed_index = 0
        self.mock_spec_model.accumulator = None
        self.mock_spec_model.acc_count = 0
        self.mock_spec_model.is_running = False

        # Instantiate the widget
        SpectrogramWidget = self.spectrogram_module.SpectrogramWidget
        self.widget = SpectrogramWidget(self.mock_spec_model)

        # Configure the UI elements on the widget instance
        self.widget.min_freq_spin.value.return_value = 20
        self.widget.max_freq_spin.value.return_value = 20000
        self.widget.scale_combo.currentText.return_value = "Linear"

        # Reset mock calls accumulated during init (like setYRange)
        self.widget.plot.reset_mock()

    def test_mocks_are_distinct(self):
        # Debug test
        self.assertIsNot(self.widget.min_freq_spin, self.widget.max_freq_spin,
                         "Spinboxes should be distinct mocks")

    def test_linear_scale(self):
        # Setup
        self.widget.scale_combo.currentText.return_value = "Linear"
        val_min = 100
        val_max = 5000

        # Ensure distinct return values
        self.widget.min_freq_spin.value.return_value = val_min
        self.widget.max_freq_spin.value.return_value = val_max

        # Execute
        self.widget.on_freq_range_changed()

        # Verify Module Updates
        self.assertEqual(self.widget.module.min_freq, val_min)
        self.assertEqual(self.widget.module.max_freq, val_max)

        # Verify Plot Updates
        # Note: mocks might receive specific types, usually we compare loosely or ensure types match.
        # But here logic passes float(val_min).
        self.widget.plot.setYRange.assert_called_with(float(val_min), float(val_max))

    def test_log_scale(self):
        # Setup
        self.widget.scale_combo.currentText.return_value = "Log"
        val_min = 20
        val_max = 20000

        self.widget.min_freq_spin.value.return_value = val_min
        self.widget.max_freq_spin.value.return_value = val_max

        # Reset mock to clear previous calls
        self.widget.plot.reset_mock()

        # Execute
        self.widget.on_freq_range_changed()

        # Verify
        expected_min = np.log10(val_min)
        expected_max = np.log10(val_max)

        self.widget.plot.setYRange.assert_called_with(expected_min, expected_max)

    def test_log_scale_correction(self):
        # Test edge case where min_freq <= 0
        self.widget.scale_combo.currentText.return_value = "Log"
        val_min = 0
        val_max = 100

        self.widget.min_freq_spin.value.return_value = val_min
        self.widget.max_freq_spin.value.return_value = val_max

        self.widget.plot.reset_mock()

        # Execute
        self.widget.on_freq_range_changed()

        # Logic corrects min to 1.0 if <= 0
        expected_min = np.log10(1.0)
        expected_max = np.log10(100.0)

        self.widget.plot.setYRange.assert_called_with(expected_min, expected_max)

    def test_missing_attributes(self):
        # Simulate missing spinboxes (e.g. during init)
        del self.widget.min_freq_spin

        # Execute
        self.widget.on_freq_range_changed()

        # Verify no crash and no calls
        self.widget.plot.setYRange.assert_not_called()

if __name__ == '__main__':
    unittest.main()
