import pytest
from unittest.mock import MagicMock
import numpy as np

from src.gui.widgets.realtime_sss_analyzer import (
    RealtimeSSSAnalyzer,
    RealtimeSSSAnalyzerWidget,
)


@pytest.fixture
def mock_audio_engine():
    engine = MagicMock()
    engine.sample_rate = 48000
    engine.block_size = 512
    engine.calibration.output_gain = 1.0
    return engine


def test_realtime_sss_analyzer_averaging_freq_update(qtbot, mock_audio_engine):
    # 1. Initialize analyzer and widget
    analyzer = RealtimeSSSAnalyzer(mock_audio_engine)
    widget = RealtimeSSSAnalyzerWidget(analyzer)
    qtbot.addWidget(widget)

    # Set parameters: start_freq=100.0, end_freq=20000.0, averaging=2
    widget.spin_start_freq.setValue(100.0)
    widget.spin_end_freq.setValue(20000.0)
    widget.spin_averaging.setValue(2)

    # 2. Start the sweep
    widget.btn_toggle.click()
    assert analyzer.is_running
    assert analyzer.averaging_count == 2
    assert widget.max_blocks > 0

    # Ensure engine mock settings
    analyzer.engine = MagicMock()
    analyzer.engine.sweep_samples = 48000 * 10  # 10s duration

    # 3. Simulate first sweep (sweep_idx=0)
    # Feed block 0
    analyzer.measurement_queue.append((0, 0, 100.0, np.zeros(5, dtype=complex), None, True))
    widget.update_plots()
    assert "100.0 Hz" in widget.lbl_current_freq.text()

    # Feed final block of first sweep
    last_block_idx = widget.max_blocks - 1
    analyzer.measurement_queue.append((last_block_idx, 0, 20000.0, np.zeros(5, dtype=complex), None, True))
    widget.update_plots()
    assert "20000.0 Hz" in widget.lbl_current_freq.text()

    # 4. Simulate second sweep (sweep_idx=1)
    # Feed block 0 again (this is where it used to get stuck because all blocks already had block_counts > 0)
    # Increment current_sweep_idx to simulate audio thread state
    analyzer.current_sweep_idx = 1
    analyzer.current_block_idx = 1
    analyzer.measurement_queue.append((0, 1, 150.0, np.zeros(5, dtype=complex), None, True))
    widget.update_plots()

    # Verify that the frequency display updates to the new sweep's frequency (150.0 Hz)
    assert "150.0 Hz" in widget.lbl_current_freq.text()

    # Clean up
    widget.btn_toggle.click()
    assert not analyzer.is_running
