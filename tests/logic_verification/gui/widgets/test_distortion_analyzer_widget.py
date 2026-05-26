import pytest
import warnings
from unittest.mock import MagicMock

from src.gui.widgets.distortion_analyzer import (
    DistortionAnalyzer,
    DistortionAnalyzerWidget,
)


@pytest.fixture
def mock_audio_engine():
    engine = MagicMock()
    engine.sample_rate = 48000
    engine.calibration.output_gain = 1.0
    return engine


def test_distortion_analyzer_widget_sweep_unit_switch_warning(qtbot, mock_audio_engine):
    analyzer = DistortionAnalyzer(mock_audio_engine)
    widget = DistortionAnalyzerWidget(analyzer)
    qtbot.addWidget(widget)

    # Change to Frequency Sweep Mode
    widget.mode_combo.setCurrentIndex(1)  # Frequency Sweep

    # Add dummy results
    analyzer.sweep_results = [
        {"sweep_param": 100.0, "thdn_percent": 0.1, "thdn_db": -60.0},
        {"sweep_param": 1000.0, "thdn_percent": 0.01, "thdn_db": -80.0},
    ]

    # Initialize Y unit to dB
    widget.sweep_y_unit_combo.setCurrentIndex(0)  # dB
    widget.on_sweep_result(None)  # Draw initial plot

    # Switch from dB to Percent and check for warnings
    with warnings.catch_warnings(record=True) as caught_warnings:
        warnings.simplefilter("always")

        # Trigger switch to Percent (%)
        widget.sweep_y_unit_combo.setCurrentIndex(1)

        # Check if there were any RuntimeWarnings about all-NaN slices
        for w in caught_warnings:
            if issubclass(w.category, RuntimeWarning) and "All-NaN" in str(w.message):
                pytest.fail(f"Warning raised: {w.message}")
