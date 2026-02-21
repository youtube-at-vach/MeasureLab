import unittest
from unittest.mock import MagicMock
import sys
import os
import numpy as np

# Ensure src is in path (3 levels up from tests/logic_verification/instruments/)
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../')))

# Mock dependencies before importing GUI modules
mock_modules = [
    'PyQt6',
    'PyQt6.QtCore',
    'PyQt6.QtGui',
    'PyQt6.QtWidgets',
    'pyqtgraph',
    'sounddevice'
]

for mod in mock_modules:
    sys.modules[mod] = MagicMock()

# Now import
try:
    from src.gui.widgets.impedance_analyzer import ImpedanceAnalyzer, ImpedanceResultsWidget, ImpedanceAnalyzerWidget
except ImportError:
    ImpedanceAnalyzer = None

class TestImpedanceAnalyzerAttributes(unittest.TestCase):
    def setUp(self):
        if ImpedanceAnalyzer is None:
            self.skipTest("ImpedanceAnalyzer could not be imported")

        self.mock_audio_engine = MagicMock()
        self.mock_audio_engine.sample_rate = 48000
        self.analyzer = ImpedanceAnalyzer(self.mock_audio_engine)

    def test_gen_frequency_initialization(self):
        self.assertEqual(self.analyzer._gen_frequency, 1000.0)
        self.assertEqual(self.analyzer.gen_frequency, 1000.0)

        self.analyzer.gen_frequency = 500.0
        self.assertEqual(self.analyzer._gen_frequency, 500.0)
        self.assertEqual(self.analyzer.gen_frequency, 500.0)

        # Check invalid setter (negative) -> clamped to 0.0
        self.analyzer.gen_frequency = -100.0
        self.assertEqual(self.analyzer.gen_frequency, 0.0)

        # Check invalid setter (nan) -> ignored (stays 0.0)
        self.analyzer.gen_frequency = float('nan')
        self.assertEqual(self.analyzer.gen_frequency, 0.0)

    def test_other_defensive_properties(self):
        self.assertEqual(self.analyzer.base_buffer_size, 4096)
        self.assertEqual(self.analyzer.max_buffer_multiplier, 16)
        self.assertEqual(self.analyzer.dynamic_buffer_threshold_hz, 100.0)
        self.assertEqual(self.analyzer.dynamic_buffer_min_cycles, 8.0)
        self.assertEqual(self.analyzer.buffer_size, 4096)
        self.assertEqual(self.analyzer.postmix_lpf_order, 4)
        self.assertEqual(self.analyzer.postmix_lpf_tau_s, 0.0)

    def test_dynamic_buffering_integration(self):
        # Use a low frequency to trigger multiplier change
        # 50Hz < 100Hz threshold
        # required = 8 * 48000 / 50 = 7680
        # mul = ceil(7680 / 4096) = 2
        # target = 4096 * 2 = 8192
        self.analyzer.gen_frequency = 50.0
        self.assertEqual(self.analyzer.buffer_size, 8192)

class TestImpedanceWidgetsAttributes(unittest.TestCase):
    def setUp(self):
        if ImpedanceAnalyzer is None:
            self.skipTest("ImpedanceAnalyzer could not be imported")
        self.mock_audio_engine = MagicMock()
        self.mock_audio_engine.sample_rate = 48000
        self.analyzer = ImpedanceAnalyzer(self.mock_audio_engine)

    def test_results_widget_access(self):
        widget = ImpedanceResultsWidget()
        # Verify attributes exist
        self.assertTrue(hasattr(widget, '_default_z_sig_figs'))
        self.assertTrue(hasattr(widget, '_default_phase_places'))

        # Test update_data calls (should not crash)
        widget.update_data(100+10j, 1+0j, 0.1+0j, 1000.0)

    def test_analyzer_widget_access(self):
        widget = ImpedanceAnalyzerWidget(self.analyzer)

        # Test update_ui (logic path that reads attributes)
        self.analyzer.is_running = True

        # Mock history buffers as they are used in update_ui logic
        self.analyzer.history_v = [1+0j, 1+0j]
        self.analyzer.history_i = [0.1+0j, 0.1+0j]
        self.analyzer.averaging_count = 2

        # This will trigger getattr(self.module, "averaging_count", 1) logic replacement
        try:
            widget.update_ui()
        except Exception as e:
            self.fail(f"update_ui raised exception: {e}")

if __name__ == '__main__':
    unittest.main()
