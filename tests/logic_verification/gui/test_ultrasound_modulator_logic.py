import sys
import os
import unittest
from unittest.mock import MagicMock, patch

# Ensure root is in path
sys.path.append(os.getcwd())

# Mock Classes for Qt
class MockQWidget:
    def __init__(self, *args, **kwargs):
        pass
    def setLayout(self, layout):
        pass

class MockMeasurementModule:
    def __init__(self, *args, **kwargs):
        pass

class TestUltrasoundModulatorLogic(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Prepare Mocks
        cls.qt_widgets = MagicMock()
        cls.qt_widgets.QWidget = MockQWidget

        # Setup sys.modules patching
        cls.modules_patch = patch.dict(sys.modules, {
            "PyQt6": MagicMock(),
            "PyQt6.QtCore": MagicMock(),
            "PyQt6.QtWidgets": cls.qt_widgets,
            "scipy": MagicMock(),
            "scipy.signal": MagicMock(),
            "src.core.audio_engine": MagicMock(),
            "src.core.localization": MagicMock(),
            "src.measurement_modules.base": MagicMock(),
        })
        cls.modules_patch.start()

        # Specific configurations
        sys.modules["src.core.localization"].tr = lambda x: x
        sys.modules["src.measurement_modules.base"].MeasurementModule = MockMeasurementModule

        # Import Target
        # Note: Do NOT reload or delete sys.modules entries for modules that import numpy extension modules,
        # as it can cause "ImportError: cannot load module more than once per process".
        # Instead, rely on patching only affecting future imports or existing mocks.

        from src.gui.widgets.ultrasound_modulator import UltrasoundModulatorWidget, UltrasoundModulator
        cls.UltrasoundModulatorWidget = UltrasoundModulatorWidget
        cls.UltrasoundModulator = UltrasoundModulator

    @classmethod
    def tearDownClass(cls):
        cls.modules_patch.stop()

    def _create_mock_module(self):
        mod_mock = MagicMock(spec=self.UltrasoundModulator)
        mod_mock.carrier_freq = 40000.0
        mod_mock.input_gain = 1.0
        mod_mock.output_gain = 1.0
        mod_mock.lpf_cutoff = 8000.0
        mod_mock.modulation_depth = 1.0
        mod_mock.modulation_mode = "DSB"
        mod_mock.input_mode = "L"
        mod_mock.output_mode = "R"
        mod_mock.enable_predistortion = False
        mod_mock.bypass = False
        mod_mock.is_running = False
        mod_mock.input_level = 0.0
        mod_mock.output_level = 0.0
        return mod_mock

    def test_freq_to_slider_robustness(self):
        """Test conversion of frequency to slider position handles edge cases."""
        mod_mock = self._create_mock_module()
        widget = self.UltrasoundModulatorWidget(mod_mock)

        # 1. Test Valid Frequency
        val_valid = widget._freq_to_slider(40000.0, 2000.0, 96000.0)
        self.assertTrue(0 <= val_valid <= 1000, f"Valid value out of range: {val_valid}")

        # 2. Test Zero Frequency (The Bug)
        try:
            val_zero = widget._freq_to_slider(0.0, 2000.0, 96000.0)
            # If fixed, it should return 0 (clamped to min)
            self.assertEqual(val_zero, 0, "Zero frequency should map to slider 0")
        except (ValueError, OverflowError, RuntimeWarning) as e:
            self.fail(f"Zero frequency caused crash: {e}")

        # 3. Test Negative Frequency
        try:
            val_neg = widget._freq_to_slider(-100.0, 2000.0, 96000.0)
            self.assertEqual(val_neg, 0, "Negative frequency should map to slider 0")
        except (ValueError, OverflowError) as e:
             self.fail(f"Negative frequency caused crash: {e}")

    def test_slider_to_freq_robustness(self):
        """Test conversion of slider position to frequency handles edge cases."""
        mod_mock = self._create_mock_module()
        widget = self.UltrasoundModulatorWidget(mod_mock)

        # 1. Valid
        f = widget._slider_to_freq(500, 100.0, 10000.0) # Mid point log scale
        # log(100)=2, log(10000)=4. Mid=3 -> 1000Hz.
        self.assertAlmostEqual(f, 1000.0, delta=1.0)

        # 2. Invalid Min Freq (<= 0)
        # Should be clamped internally to small positive
        try:
            f = widget._slider_to_freq(0, 0.0, 10000.0)
            self.assertTrue(f > 0, "Frequency must be positive")
        except (ValueError, OverflowError, RuntimeWarning) as e:
            self.fail(f"Zero min_f caused crash: {e}")

if __name__ == "__main__":
    unittest.main()
