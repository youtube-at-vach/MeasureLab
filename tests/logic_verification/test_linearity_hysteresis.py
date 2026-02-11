
import numpy as np
import pytest
from unittest.mock import MagicMock, patch
from src.gui.widgets.linearity_analyzer import LinearityAnalyzerWidget, LinearityAnalyzer

@pytest.fixture
def linearity_widget(qtbot):
    # Mock audio engine
    mock_engine = MagicMock()
    mock_engine.sample_rate = 48000
    mock_engine.calibration = MagicMock()
    mock_engine.calibration.output_gain = 1.0
    mock_engine.calibration.input_sensitivity = 1.0

    # Mock module
    module = LinearityAnalyzer(mock_engine)
    module.hysteresis_mode = True

    # Create widget
    widget = LinearityAnalyzerWidget(module)
    qtbot.addWidget(widget)
    return widget

def test_hysteresis_calculation(linearity_widget):
    """Verifies that the hysteresis calculation is correct and robust."""
    widget = linearity_widget

    # Setup synthetic results
    # Forward sweep: 0 to -10 dB
    x_fwd = np.linspace(0, -10, 11) # 0, -1, ..., -10
    g_fwd = np.zeros_like(x_fwd) # Gain 0

    # Reverse sweep: -10 to 0 dB
    x_rev = x_fwd[::-1]
    g_rev = np.zeros_like(x_rev)

    # Add hysteresis: at -5dB, gain is 1.0 in reverse (diff = 1.0)
    # x_rev is [-10, -9, ..., -5, ..., 0]
    # index 5 is -5.0
    g_rev[5] = 1.0

    # Populate widget results
    widget.results_x = list(np.concatenate((x_fwd, x_rev)))
    widget.results_gain = list(np.concatenate((g_fwd, g_rev)))
    widget.results_direction = ["fwd"] * len(x_fwd) + ["rev"] * len(x_rev)
    # dummy other fields
    widget.results_error = [0] * len(widget.results_x)
    widget.results_measured = [0] * len(widget.results_x)
    widget.results_snr = [100] * len(widget.results_x)

    # Trigger update_stats
    widget.update_stats()

    # Check hysteresis label
    # Should be 1.000 dB
    text = widget.stat_hysteresis.text()
    assert "1.000 dB" in text

def test_hysteresis_no_match(linearity_widget):
    """Verifies behavior when fwd and rev sweeps don't match exactly (but close)."""
    widget = linearity_widget

    # Fwd: [0, -1]
    # Rev: [-1.0000001, 0] (should match due to rounding)

    x_fwd = [0.0, -1.0]
    g_fwd = [0.0, 0.0]

    x_rev = [-1.0000001, 0.0]
    g_rev = [0.5, 0.0] # 0.5 diff at -1.0

    widget.results_x = x_fwd + x_rev
    widget.results_gain = g_fwd + g_rev
    widget.results_direction = ["fwd"]*2 + ["rev"]*2
    widget.results_error = [0]*4
    widget.results_measured = [0]*4
    widget.results_snr = [100]*4

    widget.update_stats()

    text = widget.stat_hysteresis.text()
    # Should find the 0.5 diff
    assert "0.500 dB" in text

def test_hysteresis_disjoint(linearity_widget):
    """Verifies behavior when sweeps are disjoint."""
    widget = linearity_widget

    x_fwd = [0.0, -1.0]
    g_fwd = [0.0, 0.0]

    x_rev = [-2.0, -3.0] # No overlap
    g_rev = [0.5, 0.5]

    widget.results_x = x_fwd + x_rev
    widget.results_gain = g_fwd + g_rev
    widget.results_direction = ["fwd"]*2 + ["rev"]*2
    widget.results_error = [0]*4
    widget.results_measured = [0]*4
    widget.results_snr = [100]*4

    widget.update_stats()

    text = widget.stat_hysteresis.text()
    # Should be 0.000 dB
    assert "0.000 dB" in text

def test_hysteresis_duplicates(linearity_widget):
    """Verifies that duplicate handling mimics 'Last-Win' for Fwd and 'Check-All' for Rev."""
    widget = linearity_widget

    # 1. Forward Sweep Duplicates (Last-Win)
    # x: 0, 0 (first has gain 10, second has gain 20)
    # Dictionary logic would overwrite 10 with 20.
    x_fwd = [0.0, 0.0]
    g_fwd = [10.0, 20.0]

    # 2. Reverse Sweep Duplicates (Check-All)
    # x: 0, 0 (first has gain 25, second has gain 22)
    # Should compare both against the "Last" forward gain (20).
    # Diff 1: |25 - 20| = 5.0
    # Diff 2: |22 - 20| = 2.0
    # Max hysteresis should be 5.0.

    x_rev = [0.0, 0.0]
    g_rev = [25.0, 22.0]

    # Add a stabilizing point to avoid polyfit error (singular matrix with all x=0)
    x_fwd = [-100.0] + x_fwd
    g_fwd = [0.0] + g_fwd
    x_rev = [-100.0] + x_rev
    g_rev = [0.0] + g_rev

    widget.results_x = x_fwd + x_rev
    widget.results_gain = g_fwd + g_rev
    widget.results_direction = ["fwd"]*len(x_fwd) + ["rev"]*len(x_rev)
    widget.results_error = [0]*len(widget.results_x)
    widget.results_measured = [0]*len(widget.results_x)
    widget.results_snr = [100]*len(widget.results_x)

    widget.update_stats()

    text = widget.stat_hysteresis.text()
    # Should be 5.000 dB exactly
    # Note: text might contain "5.000 dB", but we want to avoid matching "15.000 dB"
    assert text == "5.000 dB"

def test_hysteresis_empty_fwd(linearity_widget):
    """Verifies robustness when forward sweep is missing."""
    widget = linearity_widget

    x_fwd = []
    g_fwd = []

    x_rev = [0.0, -1.0]
    g_rev = [10.0, 20.0]

    # Need at least 2 points total to avoid polyfit crash?
    # Or just len > 1 check in update_stats handles it if results_x > 1.
    # Here results_x len is 2. So polyfit runs.
    # x_fwd is empty though.
    # Logic should handle empty x_fwd without crash.

    widget.results_x = x_rev
    widget.results_gain = g_rev
    widget.results_direction = ["rev"]*2
    widget.results_error = [0]*2
    widget.results_measured = [0]*2
    widget.results_snr = [100]*2

    # Should not crash
    widget.update_stats()

    text = widget.stat_hysteresis.text()
    # Should be 0.000 dB or --?
    # Logic: if "rev" in dirs... separates masks... x_fwd is empty.
    # Hysteresis code runs. max_hyst = 0.0.
    # Text sets to max_hyst.
    assert "0.000 dB" in text
