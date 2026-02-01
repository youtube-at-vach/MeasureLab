import sys
import os
import pytest
import numpy as np
from unittest.mock import MagicMock

# Add src to path
sys.path.insert(0, os.getcwd())

from src.gui.widgets.noise_profiler import NoiseProfiler, NoiseProfilerWidget
from PyQt6.QtWidgets import QApplication

# Set offscreen to avoid display issues
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

def test_noise_profiler_widget_update():
    # Ensure QApplication exists
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)

    # Mock AudioEngine
    mock_engine = MagicMock()
    mock_engine.sample_rate = 48000
    mock_engine.calibration.get_input_offset_db.return_value = 0.0
    mock_engine.register_callback.return_value = 123

    # Initialize Module
    module = NoiseProfiler(mock_engine)
    module.start_analysis() # Sets is_running = True

    # Fill input_data with random noise
    # Buffer size is 16384
    module.input_data = np.random.uniform(-0.1, 0.1, (16384, 2))

    # Initialize Widget
    widget = NoiseProfilerWidget(module)

    # Run update_analysis
    # This calls get_cached_window internally
    try:
        widget.update_analysis()
    except Exception as e:
        import traceback
        traceback.print_exc()
        pytest.fail(f"update_analysis raised exception: {e}")

    # Check if results were computed
    assert module.last_results, "Results should be computed"

    # Check plot data
    # widget.plot_curve
    x, y = widget.plot_curve.getData()
    assert x is not None
    assert y is not None
    assert len(x) > 0
    assert len(y) > 0

    print("Test passed: update_analysis ran successfully with get_cached_window")

    # Clean up
    module.stop_analysis()
