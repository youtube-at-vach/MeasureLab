
import sys
import os
import unittest
from unittest.mock import MagicMock
import numpy as np
import pytest

# Set offscreen
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

# Add repo root to sys.path
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# Mock sounddevice BEFORE importing any module that uses it
if 'sounddevice' not in sys.modules:
    mock_sd = MagicMock()
    sys.modules['sounddevice'] = mock_sd

from PyQt6.QtWidgets import QApplication
from src.gui.widgets.linearity_analyzer import LinearityAnalyzer, LinearityAnalyzerWidget
from src.core.audio_engine import AudioEngine

def test_linearity_analyzer_mono_input():
    """Verifies that mono input is correctly duplicated to stereo in the input buffer."""
    # Setup
    audio_engine = AudioEngine()
    audio_engine.register_callback = MagicMock(side_effect=lambda cb: 1)

    analyzer = LinearityAnalyzer(audio_engine)
    analyzer.start_analysis()

    args = audio_engine.register_callback.call_args[0]
    callback_func = args[0]

    # Create mono data (N, 1)
    frames = 100
    val = 0.5
    mono_data = np.ones((frames, 1), dtype=np.float32) * val
    out_data = np.zeros((frames, 2), dtype=np.float32)

    # Call callback
    callback_func(mono_data, out_data, frames, 0, 0)

    # Check input_data
    # Expectation: input_data should be filled with duplicated mono data
    last_samples = analyzer.input_data[-frames:]

    assert not np.all(last_samples == 0), "Mono input resulted in all-zeros buffer"
    assert np.allclose(last_samples[:, 0], val), "Left channel not matching mono input"
    assert np.allclose(last_samples[:, 1], val), "Right channel not matching mono input"

def test_linearity_analyzer_stereo_input():
    """Verifies that stereo input is correctly mapped to the input buffer."""
    # Setup
    audio_engine = AudioEngine()
    audio_engine.register_callback = MagicMock(side_effect=lambda cb: 1)

    analyzer = LinearityAnalyzer(audio_engine)
    analyzer.start_analysis()

    args = audio_engine.register_callback.call_args[0]
    callback_func = args[0]

    # Create stereo data (N, 2)
    frames = 100
    stereo_data = np.zeros((frames, 2), dtype=np.float32)
    stereo_data[:, 0] = 0.8 # Left
    stereo_data[:, 1] = 0.3 # Right
    out_data = np.zeros((frames, 2), dtype=np.float32)

    # Call callback
    callback_func(stereo_data, out_data, frames, 0, 0)

    # Check input_data
    last_samples = analyzer.input_data[-frames:]

    assert np.allclose(last_samples, stereo_data), "Stereo input was not preserved correctly"

class TestLinearityAnalyzerLogic(unittest.TestCase):
    def setUp(self):
        self.app = QApplication.instance()
        if self.app is None:
            self.app = QApplication(sys.argv)

        self.mock_engine = MagicMock()
        self.mock_engine.sample_rate = 48000
        self.mock_engine.calibration = MagicMock()
        # Default mock calibration values
        self.mock_engine.calibration.output_gain = 1.0
        self.mock_engine.calibration.input_sensitivity = 1.0

        self.module = LinearityAnalyzer(self.mock_engine)
        self.widget = LinearityAnalyzerWidget(self.module)

    def test_sweep_accumulation_and_plotting(self):
        """
        Verify that as results come in, they are added to the internal storage
        and the plots are updated with the correct number of points.
        """
        # 1. Setup Sweep
        steps = 5
        self.module.steps = steps

        # Mock the worker so we don't start actual threads
        self.module.start_sweep = MagicMock()
        worker_mock = MagicMock()
        self.module.start_sweep.return_value = worker_mock

        # 2. Start Sweep (Simulate Button Click)
        self.widget.start_btn.setChecked(True)
        self.widget.on_start_stop()

        # 3. Feed Results
        for i in range(steps):
            res = {
                'input_level': float(-i * 10),
                'linearity_error': 0.1 * i,
                'gain': 0.0,
                'measured_level': float(-i * 10),
                'snr': 60.0 - i,
                'phase': 0.0
            }
            self.widget.on_result(res)

            # 4. Verify Plot Data
            x_data, y_data = self.widget.error_curve.getData()

            # If x_data is None, that's an issue because we expect data
            self.assertIsNotNone(x_data)
            self.assertIsNotNone(y_data)

            self.assertEqual(len(x_data), i + 1, f"Plot X data length mismatch at step {i}")
            self.assertEqual(len(y_data), i + 1, f"Plot Y data length mismatch at step {i}")

            # Verify values (roughly)
            self.assertAlmostEqual(x_data[-1], -i * 10, places=5)
            self.assertAlmostEqual(y_data[-1], 0.1 * i, places=5)

    def test_initialization_reset(self):
        """
        Verify that starting a new sweep resets the data.
        """
        # Mock worker
        self.module.start_sweep = MagicMock()
        self.module.start_sweep.return_value = MagicMock()

        # Start once
        self.widget.start_btn.setChecked(True)
        self.widget.on_start_stop()

        # Add some data
        self.widget.on_result({
            'input_level': -10.0, 'linearity_error': 0.0, 'gain': 0.0,
            'measured_level': -10.0, 'snr': 60.0, 'phase': 0.0
        })

        # Stop
        self.widget.start_btn.setChecked(False)
        self.widget.on_start_stop()

        # Start again
        self.widget.start_btn.setChecked(True)
        self.widget.on_start_stop()

        # Verify empty
        x_data, y_data = self.widget.error_curve.getData()

        # pyqtgraph might return None if empty
        if x_data is None:
            # This is acceptable for "empty"
            pass
        else:
            self.assertEqual(len(x_data), 0)

        # Also verify internal storage is reset
        if isinstance(self.widget.results_x, list):
            self.assertEqual(len(self.widget.results_x), 0)
        else:
            # If we switch to array based, we check index
            pass

if __name__ == '__main__':
    unittest.main()
