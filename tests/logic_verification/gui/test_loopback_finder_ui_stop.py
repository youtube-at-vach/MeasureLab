import sys
import unittest
from unittest.mock import MagicMock
import importlib


class TestLoopbackFinderWidgetStopScan(unittest.TestCase):
    def setUp(self):
        # Patch modules needed by the GUI module
        self._patched_modules = [
            "PyQt6.QtCore",
            "PyQt6.QtWidgets",
            "sounddevice",
            "numpy",
            "src.core.audio_engine",
            "src.core.fft_manager",
            "src.core.localization",
            "src.measurement_modules.base",
        ]
        self._original_modules = {}

        for mod in self._patched_modules:
            if mod in sys.modules:
                self._original_modules[mod] = sys.modules[mod]
            sys.modules[mod] = MagicMock()

        # Specific mocks for PyQt6 to support class definitions
        mock_qt_core = sys.modules["PyQt6.QtCore"]

        class MockBase:
            def __init__(self, *args, **kwargs):
                pass

        mock_qt_core.QThread = type("QThread", (MockBase,), {})
        mock_qt_core.pyqtSignal = MagicMock(return_value=MagicMock())

        # Mock QWidget and layout elements
        mock_qt_widgets = sys.modules["PyQt6.QtWidgets"]
        for widget in [
            "QWidget",
            "QVBoxLayout",
            "QHBoxLayout",
            "QLabel",
            "QPushButton",
            "QProgressBar",
            "QTableWidget",
            "QHeaderView",
        ]:
            setattr(
                mock_qt_widgets,
                widget,
                type(
                    widget, (MockBase,), {"addWidget": MagicMock(), "addLayout": MagicMock(), "setLayout": MagicMock()}
                ),
            )

        # Mock localization
        mock_localization = sys.modules["src.core.localization"]
        mock_localization.tr = MagicMock(side_effect=lambda x: x)

        # Mock MeasurementModule base
        mock_base = sys.modules["src.measurement_modules.base"]
        mock_base.MeasurementModule = type("MeasurementModule", (MockBase,), {})

        # Import/Reload module under test
        if "src.gui.widgets.loopback_finder" in sys.modules:
            importlib.reload(sys.modules["src.gui.widgets.loopback_finder"])
        else:
            importlib.import_module("src.gui.widgets.loopback_finder")

        self.module_under_test = sys.modules["src.gui.widgets.loopback_finder"]

    def tearDown(self):
        # Restore modules
        for mod in self._patched_modules:
            if mod in self._original_modules:
                sys.modules[mod] = self._original_modules[mod]
            else:
                if mod in sys.modules:
                    del sys.modules[mod]

        if "src.gui.widgets.loopback_finder" in sys.modules:
            del sys.modules["src.gui.widgets.loopback_finder"]

    def test_stop_scan_with_worker(self):
        # Instantiate Module and Widget
        mock_module = MagicMock()
        mock_worker = MagicMock()
        mock_module.worker = mock_worker

        # Mock the widget UI initialization to avoid QT dependence
        self.module_under_test.LoopbackFinderWidget.init_ui = MagicMock()
        self.module_under_test.LoopbackFinderWidget._update_availability = MagicMock()
        widget = self.module_under_test.LoopbackFinderWidget(mock_module)

        # We need to mock scan_finished since it interacts with UI components we skipped initializing
        widget.scan_finished = MagicMock()

        # Call stop_scan
        widget.stop_scan()

        # Verify worker stop and wait were called
        mock_worker.stop.assert_called_once()
        mock_worker.wait.assert_called_once()

        # Verify scan_finished was called
        widget.scan_finished.assert_called_once()

    def test_stop_scan_without_worker(self):
        # Instantiate Module and Widget
        mock_module = MagicMock()
        mock_module.worker = None

        # Mock the widget UI initialization to avoid QT dependence
        self.module_under_test.LoopbackFinderWidget.init_ui = MagicMock()
        self.module_under_test.LoopbackFinderWidget._update_availability = MagicMock()
        widget = self.module_under_test.LoopbackFinderWidget(mock_module)

        # We need to mock scan_finished since it interacts with UI components we skipped initializing
        widget.scan_finished = MagicMock()

        # Call stop_scan
        widget.stop_scan()

        # Verify scan_finished was called despite no worker
        widget.scan_finished.assert_called_once()


if __name__ == "__main__":
    unittest.main()
