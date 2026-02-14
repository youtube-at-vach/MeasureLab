
import sys
import unittest
import os
import numpy as np
from unittest.mock import MagicMock, patch

# Ensure src can be imported
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

class TestSignalGeneratorMLS(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Mock PyQt6
        cls.mock_qt = MagicMock()
        cls.mock_qt_core = MagicMock()
        cls.mock_qt_widgets = MagicMock()

        # Patch modules globally for the test class
        cls.module_patcher = patch.dict(sys.modules, {
            'PyQt6': cls.mock_qt,
            'PyQt6.QtCore': cls.mock_qt_core,
            'PyQt6.QtWidgets': cls.mock_qt_widgets,
            'sounddevice': MagicMock(),
            'scipy': None,
            'scipy.signal': None
        })
        cls.module_patcher.start()

    @classmethod
    def tearDownClass(cls):
        cls.module_patcher.stop()

    def setUp(self):
        # We need to ensure SignalGenerator is imported AFTER mocking
        # So we import inside test or setUp if not already imported
        pass

    def test_mls_fallback_properties(self):
        # Import here to use mocks
        from src.gui.widgets.signal_generator import SignalGenerator, SignalParameters
        from src.core.audio_engine import AudioEngine

        # Mock AudioEngine
        mock_audio_engine = MagicMock(spec=AudioEngine)
        mock_audio_engine.sample_rate = 48000

        sg = SignalGenerator(mock_audio_engine)

        # Orders to test
        orders = [10, 12, 15]

        for order in orders:
            params = SignalParameters()
            params.mls_order = order

            # Since we mocked scipy in setUpClass, fallback should be used.
            # However, SignalGenerator might have imported scipy inside the method.
            # But the import statement is inside the method:
            # try: import scipy.signal ...
            # Since sys.modules['scipy'] is None (or mocked), the import might fail or return None.
            # If we set it to None, import usually raises ModuleNotFoundError or ImportError?
            # Let's verify.

            # Wait, if we set sys.modules['scipy'] = None, import scipy raises ModuleNotFoundError.
            # Perfect.

            signal = sg._generate_mls(params, 48000)

            expected_len = 2**order - 1
            self.assertEqual(len(signal), expected_len, f"Order {order} length mismatch")

            # Sum should be close to 1.0 (mls balance property)
            # signal is +/- 1.
            self.assertAlmostEqual(np.sum(signal), 1.0, delta=0.1, msg=f"Order {order} sum mismatch")

            # Check values are +/- 1
            self.assertTrue(np.all(np.abs(np.abs(signal) - 1.0) < 1e-5), f"Order {order} values are not +/- 1")

if __name__ == "__main__":
    unittest.main()
