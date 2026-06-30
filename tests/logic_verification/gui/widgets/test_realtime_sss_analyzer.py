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
    analyzer.latency_samples = 100.0  # Set mock latency so Start Sweep button is enabled
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
    analyzer.measurement_queue.append((0, 0, 100.0, np.zeros(5, dtype=complex), True))
    widget.update_plots()
    assert "100.0 Hz" in widget.lbl_current_freq.text()

    # Feed final block of first sweep
    last_block_idx = widget.max_blocks - 1
    analyzer.measurement_queue.append((last_block_idx, 0, 20000.0, np.zeros(5, dtype=complex), True))
    widget.update_plots()
    assert "20000.0 Hz" in widget.lbl_current_freq.text()

    # 4. Simulate second sweep (sweep_idx=1)
    # Feed block 0 again (this is where it used to get stuck because all blocks already had block_counts > 0)
    # Increment current_sweep_idx to simulate audio thread state
    analyzer.current_sweep_idx = 1
    analyzer.current_block_idx = 1
    analyzer.measurement_queue.append((0, 1, 150.0, np.zeros(5, dtype=complex), True))
    widget.update_plots()

    # Verify that the frequency display updates to the new sweep's frequency (150.0 Hz)
    assert "150.0 Hz" in widget.lbl_current_freq.text()

    # Clean up
    widget.btn_toggle.click()
    assert not analyzer.is_running


def test_realtime_sss_analyzer_sweep_kernels_calculation(qtbot, mock_audio_engine):
    # 1. Initialize analyzer and widget
    analyzer = RealtimeSSSAnalyzer(mock_audio_engine)
    analyzer.latency_samples = 100.0
    widget = RealtimeSSSAnalyzerWidget(analyzer)
    qtbot.addWidget(widget)

    # Set Sweep Mode to "sweep" (standard sweep mode)
    widget.combo_meas_mode.setCurrentIndex(0)  # Sweep mode

    # 2. Start the sweep
    widget.btn_toggle.click()
    assert analyzer.is_running
    assert not widget.is_hammerstein_mode

    # Mock engine sweep parameters
    analyzer.engine = MagicMock()
    analyzer.engine.sweep_samples = 48000 * 5  # 5s
    analyzer.engine.sample_rate = 48000

    # Fill accumulated results with dummy values (simulate a simple flat gain with phase)
    # widget.max_blocks blocks are expected.
    widget.max_blocks = 10
    widget.accumulated_results = np.zeros((widget.max_blocks, 5), dtype=complex)
    widget.block_counts = np.zeros(widget.max_blocks, dtype=int)
    widget.plot_freqs_array = np.linspace(20, 20000, widget.max_blocks)

    for i in range(widget.max_blocks):
        # Let's mock results for 3 harmonics (Fundamental, 2nd, 3rd)
        # Apply some phase rotation to simulate delay/impulse shape
        freq = widget.plot_freqs_array[i]
        phase = -2.0 * np.pi * freq * 0.002  # 2 ms delay
        widget.accumulated_results[i, 0] = np.exp(1j * phase)
        widget.accumulated_results[i, 1] = 0.1 * np.exp(1j * phase * 2)
        widget.accumulated_results[i, 2] = 0.05 * np.exp(1j * phase * 3)
        widget.block_counts[i] = 1

    # 3. Simulate finish
    analyzer.state = "FINISHED"
    # End the sweep which triggers was_finished logic
    widget.btn_toggle.click()

    assert not analyzer.is_running
    # Verify that kernels are calculated
    assert len(widget.H_freqs) == 3  # self.module.max_harmonic defaults to 3
    assert len(widget.kernels_time) == 3
    assert widget.time_ms is not None
    assert len(widget.time_ms) > 0

    # Tab 2 (Impulse tab) should be enabled
    assert widget.plot_tabs.isTabEnabled(2)


def test_realtime_sss_analyzer_hammerstein_curves_not_cleared(qtbot, mock_audio_engine):
    # 1. Initialize analyzer and widget
    analyzer = RealtimeSSSAnalyzer(mock_audio_engine)
    analyzer.latency_samples = 100.0
    widget = RealtimeSSSAnalyzerWidget(analyzer)
    qtbot.addWidget(widget)

    # Set Sweep Mode to "hammerstein"
    widget.combo_meas_mode.setCurrentIndex(1)  # Hammerstein mode

    # Ensure we have curves registered
    initial_items_count = len(widget.plot_kernel.listDataItems())
    assert initial_items_count == 5  # 5 orders of curves

    # 2. Start the sweep
    widget.btn_toggle.click()
    assert analyzer.is_running
    assert widget.is_hammerstein_mode

    # Check that starting the sweep did NOT clear the plot curves from the widget items
    items_count_after_start = len(widget.plot_kernel.listDataItems())
    assert items_count_after_start == 5

    # Clean up
    widget.btn_toggle.click()


