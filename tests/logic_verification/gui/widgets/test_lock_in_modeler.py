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
    analyzer.measurement_queue.append((0, 0, 100.0, np.zeros(5, dtype=complex), True, 1.0))
    widget.update_plots()
    assert "100.0 Hz" in widget.lbl_current_freq.text()

    # Feed final block of first sweep
    last_block_idx = widget.max_blocks - 1
    analyzer.measurement_queue.append((last_block_idx, 0, 20000.0, np.zeros(5, dtype=complex), True, 1.0))
    widget.update_plots()
    assert "20000.0 Hz" in widget.lbl_current_freq.text()

    # 4. Simulate second sweep (sweep_idx=1)
    # Feed block 0 again (this is where it used to get stuck because all blocks already had block_counts > 0)
    # Increment current_sweep_idx to simulate audio thread state
    analyzer.current_sweep_idx = 1
    analyzer.current_block_idx = 1
    analyzer.measurement_queue.append((0, 1, 150.0, np.zeros(5, dtype=complex), True, 1.0))
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

    # Verify 2nd harmonic (H2) values in sweep mode (without frequency mapping):
    # - H2[2] should be NaN (since NaN was injected at index 2)
    # - H2[0] and other valid indices should retain their measured complex values without NaN propagation or frequency-ratio cutoff
    H2 = widget.H_freqs[1]
    assert len(H2) > 0
    assert not np.isnan(H2[0])
    assert np.isnan(H2[2])
    assert not np.isnan(H2[4])

    # Check that magnitude for valid indices is close to 0.5
    assert np.abs(H2[0]) > 0.4
    assert np.abs(H2[4]) > 0.4


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





def test_lock_in_modeler_complex_hammerstein_fit(qtbot, mock_audio_engine):
    # Initialize analyzer and widget
    analyzer = LockInModeler(mock_audio_engine)
    analyzer.latency_samples = 100.0
    widget = LockInModelerWidget(analyzer)
    qtbot.addWidget(widget)

    # Set Sweep Mode to "hammerstein"
    widget.combo_meas_mode.setCurrentIndex(1)  # Hammerstein mode
    widget.spin_amp_steps.setValue(5)
    widget.spin_averaging.setValue(1)

    # Start sweep
    widget.btn_toggle.click()
    assert analyzer.is_running
    assert widget.is_hammerstein_mode

    analyzer.engine = MagicMock()
    analyzer.engine.sweep_samples = 48000 * 5
    analyzer.engine.sample_rate = 48000

    # Fill accumulated results and simulate the sweeps using widget.max_blocks
    widget.max_blocks = 10
    widget.accumulated_results = np.zeros((widget.max_blocks, 5), dtype=complex)
    widget.block_counts = np.ones(widget.max_blocks, dtype=int)
    widget.plot_freqs_array = np.linspace(100, 1000, widget.max_blocks)

    # Populate raw_responses and raw_counts for 5 amplitudes
    widget.raw_responses = np.zeros((5, widget.max_blocks, 5), dtype=complex)
    widget.raw_counts = np.ones((5, widget.max_blocks), dtype=int)

    # Generate simulation-like dummy responses
    # True c = [1.0, 0.5, 0.2, 0.1, 0.05]
    c_dummy = np.array([1.0, 0.5, 0.2, 0.1, 0.05])
    phase_corrections = [(1j) ** p for p in range(5)]
    for amp_idx in range(5):
        amp = widget.amplitudes[amp_idx]
        for block_idx in range(widget.max_blocks):
            f = widget.plot_freqs_array[block_idx]
            # Simple LPF: H(f) = 1.0 / (1.0 + 1j * f / 1000.0)
            H_true = 1.0 / (1.0 + 1j * f / 1000.0)

            # Fundamental: A + 0.75 * c3 * A^3 + 0.625 * c5 * A^5
            f1_nl = amp + 0.75 * c_dummy[2] * (amp**3) + 0.625 * c_dummy[4] * (amp**5)
            widget.raw_responses[amp_idx, block_idx, 0] = f1_nl * H_true / phase_corrections[0]

            # 2nd harmonic: 0.5 * c2 * A^2 + 0.5 * c4 * A^4
            f2_nl = 0.5 * c_dummy[1] * (amp**2) + 0.5 * c_dummy[3] * (amp**4)
            widget.raw_responses[amp_idx, block_idx, 1] = f2_nl * H_true / phase_corrections[1]

            # 3rd harmonic: 0.25 * c3 * A^3 + 0.3125 * c5 * A^5
            f3_nl = 0.25 * c_dummy[2] * (amp**3) + 0.3125 * c_dummy[4] * (amp**5)
            widget.raw_responses[amp_idx, block_idx, 2] = f3_nl * H_true / phase_corrections[2]

            # 4th harmonic: 0.125 * c4 * A^4
            f4_nl = 0.125 * c_dummy[3] * (amp**4)
            widget.raw_responses[amp_idx, block_idx, 3] = f4_nl * H_true / phase_corrections[3]

            # 5th harmonic: 0.0625 * c5 * A^5
            f5_nl = 0.0625 * c_dummy[4] * (amp**5)
            widget.raw_responses[amp_idx, block_idx, 4] = f5_nl * H_true / phase_corrections[4]

    # Simulate finish
    analyzer.state = "FINISHED"
    widget.btn_toggle.click()  # Triggers finishing logic and calculate_hammerstein_kernels

    assert not analyzer.is_running
    # Verify that H_freqs are estimated
    assert len(widget.H_freqs) == 5
    assert len(widget.kernels_time) == 5
    assert widget.time_ms is not None
    assert len(widget.time_ms) > 0

    # Ensure no NaN remains in time-domain kernels or mapped H_freqs (where valid_idx applies)
    valid_meas_idx = np.where(widget.plot_freqs_array > 0)[0]
    for p in range(5):
        h_p = widget.H_freqs[p][valid_meas_idx]
        assert np.any(~np.isnan(h_p))
        assert np.any(np.abs(h_p) > 1e-12)

    # Kernels should have real values
    for p in range(5):
        assert not np.all(widget.kernels_time[p] == 0.0)
        assert not np.any(np.isnan(widget.kernels_time[p]))


def test_lock_in_modeler_amplitude_switching(qtbot, mock_audio_engine):
    # Initialize analyzer and widget
    analyzer = LockInModeler(mock_audio_engine)
    analyzer.latency_samples = 100.0
    widget = LockInModelerWidget(analyzer)
    qtbot.addWidget(widget)

    # 1. Non-hammerstein mode by default (combo box should be hidden)
    widget.combo_meas_mode.setCurrentIndex(0)  # Sweep mode
    assert widget.combo_amplitude_select.isHidden()

    # 2. Select Hammerstein mode (combo box should become visible)
    widget.combo_meas_mode.setCurrentIndex(1)  # Hammerstein mode
    assert not widget.combo_amplitude_select.isHidden()

    # Set steps and start sweep
    widget.spin_amp_steps.setValue(5)
    widget.spin_averaging.setValue(1)
    widget.btn_toggle.click()
    assert analyzer.is_running

    # Check populated items
    assert widget.combo_amplitude_select.count() == 6  # 1 combined + 5 amplitudes
    assert widget.combo_amplitude_select.itemText(0) == "Model Kernels"

    # Populate raw_responses and raw_counts with mock values
    widget.max_blocks = 10
    widget.accumulated_results = np.zeros((widget.max_blocks, 5), dtype=complex)
    widget.block_counts = np.ones(widget.max_blocks, dtype=int)
    widget.plot_freqs_array = np.linspace(100, 1000, widget.max_blocks)

    widget.raw_responses = np.zeros((5, widget.max_blocks, 5), dtype=complex)
    widget.raw_counts = np.ones((5, widget.max_blocks), dtype=int)

    # Fill amplitude 0 (index 0) with constant gain 0.5 (approx -6 dB)
    # Fill amplitude 1 (index 1) with constant gain 0.25 (approx -12 dB)
    widget.raw_responses[0, :, 0] = 0.5
    widget.raw_responses[1, :, 0] = 0.25

    # Switch to Amplitude 1 (combo index 1 -> amp_idx 0)
    widget.combo_amplitude_select.setCurrentIndex(1)
    # Check that magnitude plot data matches the selected amplitude's raw data
    mag_data = widget.mag_curves[0].yData
    np.testing.assert_allclose(mag_data[~np.isnan(mag_data)], 20 * np.log10(0.5), atol=1.0)
    assert not widget.plot_tabs.isTabEnabled(1)  # Impulse tab disabled

    # Switch to Amplitude 2 (combo index 2 -> amp_idx 1)
    widget.combo_amplitude_select.setCurrentIndex(2)
    mag_data2 = widget.mag_curves[0].yData
    np.testing.assert_allclose(mag_data2[~np.isnan(mag_data2)], 20 * np.log10(0.25), atol=1.0)
    assert not widget.plot_tabs.isTabEnabled(1)  # Impulse tab disabled

    # Switch back to Combined Model (combo index 0)
    # End sweep to trigger kernel calculation
    analyzer.state = "FINISHED"
    widget.btn_toggle.click()  # stop/finish
    widget.combo_amplitude_select.setCurrentIndex(0)
    assert widget.plot_tabs.isTabEnabled(1)  # Impulse tab re-enabled


def test_lock_in_modeler_sweep_bypasses_harmonic_cutoff(qtbot, mock_audio_engine):
    # Initialize analyzer and widget in standard sweep mode
    analyzer = LockInModeler(mock_audio_engine)
    analyzer.latency_samples = 100.0
    widget = LockInModelerWidget(analyzer)
    qtbot.addWidget(widget)

    widget.combo_meas_mode.setCurrentIndex(0)  # Standard sweep mode
    assert not widget.is_hammerstein_mode

    # Prepare frequency grid from 20 Hz to 20000 Hz
    max_blocks = 100
    widget.max_blocks = max_blocks
    widget.plot_freqs_array = np.linspace(20.0, 20000.0, max_blocks)
    widget.block_counts = np.ones(max_blocks, dtype=int)
    widget.accumulated_results = np.zeros((max_blocks, 5), dtype=complex)

    # Set non-zero responses for fundamental and 2nd..5th harmonics across all frequencies
    for p in range(5):
        widget.accumulated_results[:, p] = (0.1 ** p) * (1.0 + 0.0j)

    # Calculate kernels
    widget.calculate_hammerstein_kernels()

    # Verify that in standard sweep mode, H_freqs for higher harmonics (e.g. 2nd, 3rd, 5th)
    # are NOT cut off / set to NaN at higher frequencies (e.g. near 20 kHz)
    for p in range(5):
        H_freq = widget.H_freqs[p]
        # None of the values should be NaN
        assert not np.any(np.isnan(H_freq)), f"Harmonic order {p+1} contains NaNs unexpectedly in sweep mode"
        # High frequency end (e.g., block 90-99 near 20kHz) should retain valid non-zero data
        assert np.all(np.abs(H_freq[90:]) > 0.0), f"Harmonic order {p+1} was cut off at high frequencies"





