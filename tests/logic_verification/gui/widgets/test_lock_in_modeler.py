import pytest
from unittest.mock import MagicMock
import numpy as np

from src.gui.widgets.lock_in_modeler import (
    LockInModeler,
    LockInModelerWidget,
)


@pytest.fixture
def mock_audio_engine():
    engine = MagicMock()
    engine.sample_rate = 48000
    engine.block_size = 512
    engine.calibration.output_gain = 1.0
    return engine


def test_lock_in_modeler_averaging_freq_update(qtbot, mock_audio_engine):
    # 1. Initialize analyzer and widget
    analyzer = LockInModeler(mock_audio_engine)
    analyzer.latency_samples = 100.0  # Set mock latency so Start Sweep button is enabled
    widget = LockInModelerWidget(analyzer)
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


def test_lock_in_modeler_sweep_kernels_calculation(qtbot, mock_audio_engine):
    # 1. Initialize analyzer and widget
    analyzer = LockInModeler(mock_audio_engine)
    analyzer.latency_samples = 100.0
    widget = LockInModelerWidget(analyzer)
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
    assert len(widget.H_freqs) == 5  # self.module.max_harmonic defaults to 5
    assert len(widget.kernels_time) == 5
    assert widget.time_ms is not None
    assert len(widget.time_ms) > 0

    # Tab 2 (Impulse tab) should be enabled
    assert widget.plot_tabs.isTabEnabled(1)


def test_lock_in_modeler_hammerstein_curves_not_cleared(qtbot, mock_audio_engine):
    # 1. Initialize analyzer and widget
    analyzer = LockInModeler(mock_audio_engine)
    analyzer.latency_samples = 100.0
    widget = LockInModelerWidget(analyzer)
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


def test_lock_in_modeler_relative_mode(qtbot, mock_audio_engine):
    # 1. Initialize analyzer and widget
    analyzer = LockInModeler(mock_audio_engine)
    analyzer.latency_samples = 100.0
    widget = LockInModelerWidget(analyzer)
    qtbot.addWidget(widget)

    # Set Sweep Mode to "sweep" (standard sweep mode)
    widget.combo_meas_mode.setCurrentIndex(0)  # Sweep mode

    # 2. Start the sweep
    widget.btn_toggle.click()
    assert analyzer.is_running

    analyzer.engine = MagicMock()
    analyzer.engine.sweep_samples = 48000 * 5
    analyzer.engine.sample_rate = 48000

    # Fill accumulated results with dummy values
    widget.max_blocks = 10
    widget.accumulated_results = np.zeros((widget.max_blocks, 5), dtype=complex)
    widget.block_counts = np.zeros(widget.max_blocks, dtype=int)
    widget.plot_freqs_array = np.linspace(100, 1000, widget.max_blocks)

    for i in range(widget.max_blocks):
        # Fundamental (H1) gain = 0.5, H2 gain = 0.05
        widget.accumulated_results[i, 0] = 0.5
        widget.accumulated_results[i, 1] = 0.05
        widget.block_counts[i] = 1

    # 3. Finish sweep
    analyzer.state = "FINISHED"
    widget.btn_toggle.click()  # Triggers finishing logic

    # 4. Relative option checked = False
    widget.chk_relative.setChecked(False)
    # Get magnitude of H1 and H2
    h1_mag_abs = widget.mag_curves[0].yData
    h2_mag_abs = widget.mag_curves[1].yData

    # Check absolute values
    # Filter out NaNs before asserting (frequency mapping generates NaNs at edges)
    h1_valid = h1_mag_abs[~np.isnan(h1_mag_abs)]
    h2_valid = h2_mag_abs[~np.isnan(h2_mag_abs)]
    assert len(h1_valid) > 0
    assert len(h2_valid) > 0
    np.testing.assert_allclose(h1_valid, 20 * np.log10(0.5), atol=1.0)
    np.testing.assert_allclose(h2_valid, 20 * np.log10(0.05), atol=1.0)

    # 5. Check relative option = True
    widget.chk_relative.setChecked(True)
    h1_mag_rel = widget.mag_curves[0].yData
    h2_mag_rel = widget.mag_curves[1].yData

    h1_rel_valid = h1_mag_rel[~np.isnan(h1_mag_rel)]
    h2_rel_valid = h2_mag_rel[~np.isnan(h2_mag_rel)]
    assert len(h1_rel_valid) > 0
    assert len(h2_rel_valid) > 0

    # H1 relative gain should be exactly 0 dB (relative to itself)
    np.testing.assert_allclose(h1_rel_valid, 0.0, atol=1e-5)
    # H2 relative gain should be around 20*log10(0.05/0.5) = -20 dB
    np.testing.assert_allclose(h2_rel_valid, -20.0, atol=1.0)

    # Clean up
    widget.chk_relative.setChecked(False)


def test_lock_in_modeler_unwrap_mode(qtbot, mock_audio_engine):
    # 1. Initialize analyzer and widget
    analyzer = LockInModeler(mock_audio_engine)
    analyzer.latency_samples = 100.0
    widget = LockInModelerWidget(analyzer)
    qtbot.addWidget(widget)

    # Set Sweep Mode to "sweep" (standard sweep mode)
    widget.combo_meas_mode.setCurrentIndex(0)  # Sweep mode

    # 2. Start the sweep
    widget.btn_toggle.click()
    assert analyzer.is_running

    analyzer.engine = MagicMock()
    analyzer.engine.sweep_samples = 48000 * 5
    analyzer.engine.sample_rate = 48000

    # Fill accumulated results with dummy values
    widget.max_blocks = 10
    widget.accumulated_results = np.zeros((widget.max_blocks, 5), dtype=complex)
    widget.block_counts = np.zeros(widget.max_blocks, dtype=int)
    widget.plot_freqs_array = np.linspace(100, 1000, widget.max_blocks)

    # Generate a large phase wrap (e.g., phase jumping by 200 degrees each step)
    for i in range(widget.max_blocks):
        phase_rad = (200.0 * i) * (np.pi / 180.0)
        widget.accumulated_results[i, 0] = np.exp(1j * phase_rad)
        widget.block_counts[i] = 1

    # 3. Finish sweep (triggers kernel calculation and H_freqs mapping)
    analyzer.state = "FINISHED"
    widget.btn_toggle.click()  # Triggers finishing logic

    # 4. Unwrap option checked = False
    widget.chk_unwrap.setChecked(False)
    h1_phase_wrapped = widget.phase_curves[0].yData
    h1_phase_wrapped_valid = h1_phase_wrapped[~np.isnan(h1_phase_wrapped)]
    assert np.all(h1_phase_wrapped_valid >= -180.0)
    assert np.all(h1_phase_wrapped_valid <= 180.0)

    # 5. Unwrap option checked = True
    widget.chk_unwrap.setChecked(True)
    h1_phase_unwrapped = widget.phase_curves[0].yData
    h1_phase_unwrapped_valid = h1_phase_unwrapped[~np.isnan(h1_phase_unwrapped)]

    # Check if unwrapping actually happened (i.e. phase exceeds 180 or is continuous without wrap)
    assert np.any(np.abs(h1_phase_unwrapped_valid) > 180.0)


def test_lock_in_modeler_nan_propagation(qtbot, mock_audio_engine):
    # Initialize analyzer and widget
    analyzer = LockInModeler(mock_audio_engine)
    analyzer.latency_samples = 100.0
    widget = LockInModelerWidget(analyzer)
    qtbot.addWidget(widget)

    # Set Sweep Mode to "sweep" (standard sweep mode)
    widget.combo_meas_mode.setCurrentIndex(0)  # Sweep mode

    # Start the sweep
    widget.btn_toggle.click()
    assert analyzer.is_running

    analyzer.engine = MagicMock()
    analyzer.engine.sweep_samples = 48000 * 5
    analyzer.engine.sample_rate = 48000

    # Fill accumulated results with dummy values, but inject NaN at index 2
    widget.max_blocks = 10
    widget.accumulated_results = np.zeros((widget.max_blocks, 5), dtype=complex)
    widget.block_counts = np.zeros(widget.max_blocks, dtype=int)
    widget.plot_freqs_array = np.linspace(100, 1000, widget.max_blocks)

    for i in range(widget.max_blocks):
        widget.block_counts[i] = 1
        widget.accumulated_results[i, 0] = 1.0 + 0.0j
        # 2nd harmonic: inject NaN at index 2 (300 Hz)
        if i == 2:
            widget.accumulated_results[i, 1] = np.nan
        else:
            widget.accumulated_results[i, 1] = 0.5 + 0.0j

    # Finish sweep (triggers kernel calculation and H_freqs mapping)
    analyzer.state = "FINISHED"
    widget.btn_toggle.click()  # Triggers finishing logic

    # Verify 2nd harmonic (H2) values.
    # Due to polar interpolation with NaN:
    # f_lookups = sorted_freqs / 2 -> [50, 100, 150, 200, 250, 300, 350, 400, 450, 500]
    # For H2 (p=1), if sorted_freqs[2] = 300 is NaN, then:
    # - f_lookups=250 (interpolated between 200 and 300) becomes NaN
    # - f_lookups=300 (at 300) becomes NaN
    # - f_lookups=350 (interpolated between 300 and 400) becomes NaN
    # Thus, multiple points in H_mapped become NaN and are cleared to 0.0.
    H2 = widget.H_freqs[1]
    assert len(H2) > 0

    # After our fix, NaN propagation is prevented:
    # - Index 0 (50Hz) remains NaN because it's left of sorted_freqs range (left=np.nan).
    # - Indices 4, 5, 6 (corresponding to 500Hz, 600Hz, 700Hz in H_full, mapped from f_lookups=250, 300, 350)
    #   must now be successfully interpolated from the adjacent valid points (200Hz and 400Hz) and should NOT be NaN.
    assert np.isnan(H2[0])
    assert not np.isnan(H2[4])
    assert not np.isnan(H2[5])
    assert not np.isnan(H2[6])

    # Check that magnitude is close to the valid 0.5 value
    assert np.abs(H2[4]) > 0.4
    assert np.abs(H2[5]) > 0.4
    assert np.abs(H2[6]) > 0.4


def test_lock_in_modeler_smoothing_in_sweep_mode(qtbot, mock_audio_engine):
    # 1. Initialize analyzer and widget
    analyzer = LockInModeler(mock_audio_engine)
    analyzer.latency_samples = 100.0
    widget = LockInModelerWidget(analyzer)
    qtbot.addWidget(widget)

    # Sweep mode is set
    widget.combo_meas_mode.setCurrentIndex(0)  # Sweep mode

    # Verify that the smoothing controls are not hidden in sweep mode
    assert not widget.combo_smoothing.isHidden()
    assert not widget.lbl_smoothing.isHidden()

    # Start sweep
    widget.btn_toggle.click()
    assert analyzer.is_running

    analyzer.engine = MagicMock()
    analyzer.engine.sweep_samples = 48000 * 5
    analyzer.engine.sample_rate = 48000

    # Fill accumulated results with a noisy signal
    widget.max_blocks = 100  # large enough to allow smoothing filter to run (len >= 15)
    widget.accumulated_results = np.zeros((widget.max_blocks, 5), dtype=complex)
    widget.block_counts = np.ones(widget.max_blocks, dtype=int)
    widget.plot_freqs_array = np.linspace(100, 1000, widget.max_blocks)

    # Let's create a noisy step or sine wave in magnitude
    np.random.seed(42)
    noise = np.random.normal(0, 5.0, widget.max_blocks)  # 5 dB variation
    for i in range(widget.max_blocks):
        # Base gain 0 dB + noise
        widget.accumulated_results[i, 0] = 10 ** ((noise[i]) / 20.0)

    # 1. Test with "None" smoothing
    widget.combo_smoothing.setCurrentIndex(0)  # "None"
    widget.redraw_plots()
    h1_none = widget.mag_curves[0].yData.copy()

    # 2. Test with "Low Smoothing" (Light)
    widget.combo_smoothing.setCurrentIndex(1)  # "Light"
    widget.redraw_plots()
    h1_light = widget.mag_curves[0].yData.copy()

    # 3. Test with "High Smoothing" (Heavy)
    widget.combo_smoothing.setCurrentIndex(3)  # "Heavy"
    widget.redraw_plots()
    h1_heavy = widget.mag_curves[0].yData.copy()

    # Asserts:
    # yData should not be identical when smoothed
    assert not np.allclose(h1_none, h1_light, atol=1e-5)
    assert not np.allclose(h1_light, h1_heavy, atol=1e-5)

    # The variance (noise) should be reduced by smoothing
    var_none = np.var(h1_none)
    var_light = np.var(h1_light)
    var_heavy = np.var(h1_heavy)

    assert var_light < var_none
    assert var_heavy < var_light

    # Clean up
    widget.btn_toggle.click()


def test_lock_in_modeler_predistortion_sweep_mode(qtbot, mock_audio_engine):
    # 1. Initialize analyzer and widget
    analyzer = LockInModeler(mock_audio_engine)
    analyzer.latency_samples = 100.0
    widget = LockInModelerWidget(analyzer)
    qtbot.addWidget(widget)

    # 2. Select Predistortion Sweep mode
    # Index 2: "Predistortion Sweep"
    widget.combo_meas_mode.setCurrentIndex(2)
    assert not widget.spin_predistortion_iterations.isHidden()
    assert not widget.spin_predistortion_mu.isHidden()

    # Start sweep
    widget.btn_toggle.click()
    assert analyzer.is_running
    assert widget.is_predistortion_sweep_mode

    # Mock engine sweep parameters
    analyzer.engine = MagicMock()
    analyzer.engine.sweep_samples = 48000 * 5
    analyzer.engine.sample_rate = 48000
    analyzer.engine.meas_freqs = np.linspace(100, 1000, 10)

    # Mock F_corr and results
    widget.max_blocks = 10
    widget.accumulated_results = np.zeros((widget.max_blocks, 5), dtype=complex)
    widget.block_counts = np.ones(widget.max_blocks, dtype=int)
    widget.plot_freqs_array = np.linspace(100, 1000, widget.max_blocks)

    # Initialize predistortion_manager for test
    from src.core.predistortion import PredistortionManager
    widget.predistortion_manager = PredistortionManager(
        start_freq=100.0, end_freq=1000.0, meas_freqs=analyzer.engine.meas_freqs, max_harmonic=3
    )
    # Set mock correction value at harmonic 2 (index 2 in F_corr)
    # 0.1j gain correction
    widget.predistortion_manager.F_corr[2][:] = 0.1j

    for i in range(widget.max_blocks):
        widget.accumulated_results[i, 0] = 0.5  # H1 (fundamental)
        widget.accumulated_results[i, 1] = 0.01  # H2 (raw suppressed distortion)
        widget.block_counts[i] = 1

    # 3. Verify with Restore True DUT Response ON
    widget.chk_show_restored.setChecked(True)
    widget.redraw_plots()
    h2_restored = widget.mag_curves[1].yData.copy()

    # 4. Verify with Show Restored OFF
    widget.chk_show_restored.setChecked(False)
    widget.redraw_plots()
    h2_raw = widget.mag_curves[1].yData.copy()

    # The restored response should be different from raw because F_corr was applied
    assert not np.allclose(h2_restored, h2_raw, atol=1e-5)

    # H2 raw should be around 20*log10(0.01) = -40 dB
    # H2 restored should be: raw (0.01) - F_corr (0.1j) * H1 (0.5) = 0.01 - 0.05j -> magnitude approx 0.051 -> -25.8 dB
    np.testing.assert_allclose(h2_raw, 20 * np.log10(0.01), atol=1.0)
    np.testing.assert_allclose(h2_restored, 20 * np.log10(np.abs(0.01 - 0.05j)), atol=1.0)

    # 5. Finish sweep and test post-sweep toggling
    analyzer.state = "FINISHED"
    widget.btn_toggle.click()  # Triggers finishing logic

    # Toggle checkbox to ON post-sweep and assert H_freqs rebuilds
    widget.chk_show_restored.setChecked(True)
    h2_post_restored = widget.mag_curves[1].yData.copy()
    np.testing.assert_allclose(h2_post_restored, 20 * np.log10(np.abs(0.01 - 0.05j)), atol=1.0)

    widget.chk_show_restored.setChecked(False)
    h2_post_raw = widget.mag_curves[1].yData.copy()
    np.testing.assert_allclose(h2_post_raw, 20 * np.log10(0.01), atol=1.0)


def test_lock_in_modeler_inverse_hammerstein_mode(qtbot, mock_audio_engine):
    # 1. Initialize analyzer and widget
    analyzer = LockInModeler(mock_audio_engine)
    analyzer.latency_samples = 100.0
    widget = LockInModelerWidget(analyzer)
    qtbot.addWidget(widget)

    # 2. Select Inverse Hammerstein mode
    # Index 3: "Inverse Hammerstein"
    widget.combo_meas_mode.setCurrentIndex(3)
    assert not widget.spin_amp_steps.isHidden()
    assert not widget.spin_predistortion_iterations.isHidden()

    # Set parameters: 5 amplitudes (minimum allowed is 5), 2 predistortion iterations (3 sweeps per amp, 15 sweeps total)
    widget.spin_amp_steps.setValue(5)
    widget.spin_predistortion_iterations.setValue(2)

    # Start sweep
    widget.btn_toggle.click()
    assert analyzer.is_running
    assert widget.is_predistortion_sweep_mode
    assert widget.is_hammerstein_mode
    assert widget.is_inverse_hammerstein_mode
    assert analyzer.averaging_count == 15  # 5 amplitudes * (2 iterations + 1)

    # Use the real engine but patch meas_freqs to match our dummy test sizes
    analyzer.engine.meas_freqs = np.linspace(100, 1000, 10)

    # Fill accumulated results and simulate the sweeps using widget.max_blocks
    max_blks = widget.max_blocks
    widget.accumulated_results = np.zeros((max_blks, 5), dtype=complex)
    widget.block_counts = np.ones(max_blks, dtype=int)
    widget.plot_freqs_array = np.linspace(100, 1000, max_blks)

    # We will mock raw_responses structure
    widget.raw_responses = np.zeros((5, max_blks, 5), dtype=complex)
    widget.raw_counts = np.zeros((5, max_blks), dtype=int)

    # Initialize predistortion_manager with patched size
    from src.core.predistortion import PredistortionManager
    widget.predistortion_manager = PredistortionManager(
        start_freq=100.0, end_freq=1000.0, meas_freqs=analyzer.engine.meas_freqs, max_harmonic=5
    )
    # Set mock correction value at harmonic 2 (index 2 in F_corr) for the first amplitude step
    widget.predistortion_manager.F_corr[2][:] = 0.1j

    # Feed blocks for sweep_idx=0 (iter_idx=0)
    # Since iter_idx != 2, raw_responses should not accumulate
    for block_idx in range(max_blks):
        widget.on_block_calculated(block_idx, 0, widget.plot_freqs_array[block_idx], np.array([0.5, 0.01, 0.0, 0.0, 0.0]), True)
    widget.process_remaining_queue()
    assert np.sum(widget.raw_counts[0]) == 0

    # Simulate sweep_finished for sweep_idx=0 (iter_idx=0) -> moves to sweep_idx=1, same amplitude
    widget.on_sweep_finished(0)
    assert analyzer.current_sweep_idx == 1
    assert np.any(widget.predistortion_manager.F_corr[2] != 0.0j) # F_corr should update inside amplitude step

    # Set F_corr for iteration 1
    widget.predistortion_manager.F_corr[2][:] = 0.2j

    # Simulate sweep 1 (iter_idx=1) finished
    widget.on_sweep_finished(1)
    assert analyzer.current_sweep_idx == 2

    # Set final F_corr for iteration 2 (measurement sweep)
    widget.predistortion_manager.F_corr[2][:] = 0.3j

    # Feed blocks for sweep_idx=2 (iter_idx=2) -> measurement sweep
    for block_idx in range(max_blks):
        widget.on_block_calculated(block_idx, 2, widget.plot_freqs_array[block_idx], np.array([0.5, 0.01, 0.0, 0.0, 0.0]), True)
    widget.process_remaining_queue()
    # It should accumulate since iter_idx == N_adapt (2)
    assert np.all(widget.raw_counts[0] == 1)

    # Simulate sweep_finished for sweep_idx=2 (iter_idx=2) -> transitions to amplitude step 1 (sweep_idx=3)
    widget.on_sweep_finished(2)
    assert analyzer.current_sweep_idx == 3
    # F_corr for amp_idx=0 should be saved
    assert widget.predistortion_managers[0] is not None
    assert np.all(widget.predistortion_managers[0].F_corr[2] == 0.3j)
    # F_corr should be reset to zero for the new amplitude
    assert np.all(widget.predistortion_manager.F_corr[2] == 0.0j)

    # Simulate finish
    analyzer.state = "FINISHED"
    widget.btn_toggle.click()
    assert not analyzer.is_running


def test_lock_in_modeler_change_harmonic_settings_midway(qtbot, mock_audio_engine):
    # Initialize analyzer and widget
    analyzer = LockInModeler(mock_audio_engine)
    analyzer.latency_samples = 100.0
    widget = LockInModelerWidget(analyzer)
    qtbot.addWidget(widget)

    # 1. Start sweep in predistortion mode
    widget.combo_meas_mode.setCurrentIndex(2) # Predistortion Sweep
    widget.spin_max_harmonic.setValue(3)
    widget.chk_show_restored.setChecked(True)
    widget.btn_toggle.click()
    assert analyzer.is_running

    analyzer.engine.meas_freqs = np.linspace(100, 1000, 10)
    widget.max_blocks = 10
    widget.accumulated_results = np.zeros((widget.max_blocks, 5), dtype=complex)
    widget.block_counts = np.ones(widget.max_blocks, dtype=int)
    widget.plot_freqs_array = np.linspace(100, 1000, widget.max_blocks)

    # Simulate some data measurement and F_corr populating for max_harmonic = 3 (harmonic indices 2, 3)
    from src.core.predistortion import PredistortionManager
    widget.predistortion_manager = PredistortionManager(
        start_freq=100.0, end_freq=1000.0, meas_freqs=analyzer.engine.meas_freqs, max_harmonic=3
    )
    widget.predistortion_manager.F_corr[2] = np.ones(10, dtype=complex) * 0.1j
    widget.predistortion_manager.F_corr[3] = np.ones(10, dtype=complex) * 0.2j
    for block_idx in range(10):
        widget.accumulated_results[block_idx, 0] = 0.5
        widget.accumulated_results[block_idx, 1] = 0.01

    # 2. Stop sweep
    widget.btn_toggle.click()
    assert not analyzer.is_running

    # 3. Increase max harmonic settings to 4 (which loops redraw_plots for n=2,3,4)
    widget.spin_max_harmonic.setValue(4)
    analyzer.max_harmonic = 4

    # 4. Start sweep again. This calls redraw_plots() first, which accesses F_corr[4] (KeyError risk).
    # This should not raise KeyError or crash.
    try:
        widget.btn_toggle.click()
        assert analyzer.is_running
    finally:
        # Clean up
        if analyzer.is_running:
            widget.btn_toggle.click()


def test_lock_in_modeler_predistortion_sweep_inverse_kernels_calculation(qtbot, mock_audio_engine):
    # Initialize analyzer and widget
    analyzer = LockInModeler(mock_audio_engine)
    analyzer.latency_samples = 100.0
    widget = LockInModelerWidget(analyzer)
    qtbot.addWidget(widget)

    # Start sweep in predistortion mode
    widget.combo_meas_mode.setCurrentIndex(2) # Predistortion Sweep
    widget.btn_toggle.click()
    assert analyzer.is_running

    analyzer.engine = MagicMock()
    analyzer.engine.sweep_samples = 48000 * 5
    analyzer.engine.sample_rate = 48000
    analyzer.engine.meas_freqs = np.linspace(100, 1000, 10)

    # Set output amplitude
    analyzer.output_amplitude = 0.5
    widget.output_amplitude = 0.5

    widget.max_blocks = 10
    widget.accumulated_results = np.zeros((widget.max_blocks, 5), dtype=complex)
    widget.block_counts = np.ones(widget.max_blocks, dtype=int)
    widget.plot_freqs_array = np.linspace(100, 1000, widget.max_blocks)

    # Setup predistortion manager and mock F_corr
    from src.core.predistortion import PredistortionManager
    widget.predistortion_manager = PredistortionManager(
        start_freq=100.0, end_freq=1000.0, meas_freqs=analyzer.engine.meas_freqs, max_harmonic=5
    )
    # Set a dummy linear baseline H0_1 response (0.5 for all freqs)
    widget.predistortion_manager.H0_1 = np.ones(10, dtype=complex) * 0.5
    # Set a dummy F_corr value (0.1j for 2nd order)
    widget.predistortion_manager.F_corr[2][:] = 0.1j

    # Setup dummy measurements (H1 measured average complex response = 0.5)
    for block_idx in range(10):
        widget.accumulated_results[block_idx, 0] = 0.5
        widget.accumulated_results[block_idx, 1] = 0.01 # measured H2

    # Set status to FINISHED to trigger calculate_hammerstein_kernels on stop
    analyzer.state = "FINISHED"

    # Stop sweep to trigger calculate_hammerstein_kernels()
    widget.btn_toggle.click()
    assert not analyzer.is_running

    # Retrieve cache data from active model
    from src.core.hammerstein_model import get_active_model
    cache_data = get_active_model()
    assert cache_data is not None

    meta = cache_data.get("metadata", {})
    assert meta.get("model_direction") == "inverse"

    # Verify G1 and G2 calculations
    # H1_base = 0.5 (from H0_1) -> G1 = np.conj(H1_base) / (|H1_base|^2 + eps^2)
    # Since H1_base = 0.5, and eps = 1e-3 * 0.5 = 5e-4
    # G1 ~ 0.5 / (0.25 + 2.5e-7) ~ 2.0
    G1_calculated = widget.H_freqs[0]
    valid_mask_g1 = (widget.block_counts > 0) & (~np.isnan(G1_calculated))
    assert np.any(valid_mask_g1)
    assert np.allclose(G1_calculated[valid_mask_g1], 2.0, rtol=1e-2)

    # G2 = 2 * F_corr_2 / R = 2 * 0.1j / 0.5 = 0.4j
    G2_calculated = widget.H_freqs[1]
    valid_mask_g2 = (widget.block_counts > 0) & (~np.isnan(G2_calculated))
    assert np.any(valid_mask_g2)
    assert np.allclose(G2_calculated[valid_mask_g2], 0.4j, rtol=1e-2)
