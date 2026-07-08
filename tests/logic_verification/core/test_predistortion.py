import numpy as np
from src.core.predistortion import PredistortionManager


def test_predistortion_manager_init():
    meas_freqs = np.logspace(1, 4, 100)
    manager = PredistortionManager(start_freq=20.0, end_freq=20000.0, meas_freqs=meas_freqs, max_harmonic=3)

    assert manager.start_freq == 20.0
    assert manager.end_freq == 20000.0
    assert len(manager.meas_freqs) == 100
    assert manager.max_harmonic == 3
    assert 2 in manager.F_corr
    assert 3 in manager.F_corr
    assert 4 not in manager.F_corr
    assert np.all(manager.F_corr[2] == 0.0)


def test_generate_predistorted_sweep():
    meas_freqs = np.logspace(1, 4, 100)
    manager = PredistortionManager(start_freq=20.0, end_freq=20000.0, meas_freqs=meas_freqs, max_harmonic=3)

    # Initialize correction with some values
    manager.F_corr[2] = np.ones(100) * 0.1
    manager.F_corr[3] = np.ones(100) * 0.05

    fs = 48000
    sweep_samples = 48000  # 1 second
    k_param = 10.0
    L_param = 1.0
    amplitude = 0.5

    x_corr = manager.generate_predistorted_sweep(
        sample_rate=fs, sweep_samples=sweep_samples, k_param=k_param, L_param=L_param, amplitude=amplitude
    )

    assert isinstance(x_corr, np.ndarray)
    assert len(x_corr) == sweep_samples
    assert np.max(np.abs(x_corr)) <= amplitude * 1.5  # base sweep (1.0) + corrections (0.1 + 0.05) = 1.15 * amplitude


def test_update_correction():
    meas_freqs = np.logspace(1, 4, 100)
    manager = PredistortionManager(start_freq=20.0, end_freq=20000.0, meas_freqs=meas_freqs, max_harmonic=3)

    # Mock measurement results
    num_blocks = 50
    x_data = np.linspace(20.0, 20000.0, num_blocks)
    block_counts = np.ones(num_blocks, dtype=int)

    # H1 is 1.0, H2 (distortion) is 0.1, H3 is 0.05
    raw_results = np.zeros((num_blocks, 3), dtype=complex)
    raw_results[:, 0] = 1.0  # H1
    raw_results[:, 1] = 0.1  # H2
    raw_results[:, 2] = 0.05  # H3

    # First iteration stores H0_1
    manager.update_correction(iteration=0, x_data=x_data, raw_results=raw_results, block_counts=block_counts, mu=0.5)

    assert manager.H0_1 is not None
    assert len(manager.H0_1) == len(meas_freqs)
    # H0_1 should be close to 1.0
    assert np.allclose(np.abs(manager.H0_1), 1.0, atol=1e-2)

    # Reset raw_results for second iteration update
    # In next iteration, we still measure distortion, so correction should accumulate
    manager.update_correction(iteration=1, x_data=x_data, raw_results=raw_results, block_counts=block_counts, mu=0.5)

    # F_corr should now have non-zero (negative) values to cancel distortion
    # e.g., F_corr = F_corr - mu * Hn / H1(nf)
    # H2 is 0.1, H1 is 1.0, mu is 0.5 => delta is -0.05. F_corr[2] should be negative
    # Low frequency fadeout should prevent update below 40Hz
    assert np.all(manager.F_corr[2][meas_freqs > 80.0] < 0.0)
    assert np.allclose(manager.F_corr[2][meas_freqs < 40.0], 0.0)


def test_restore_true_response():
    meas_freqs = np.logspace(1, 4, 100)
    manager = PredistortionManager(start_freq=20.0, end_freq=20000.0, meas_freqs=meas_freqs, max_harmonic=3)

    manager.F_corr[2] = np.ones(100) * 0.1
    # Base H1 response
    H1_base = np.ones(100) * 1.0
    freq_base = meas_freqs

    target_freqs = np.array([100.0, 1000.0])
    # Measured response includes predistortion contribution: H_measured = H_true + F_corr * H1
    # Say H_true is 0.0, and F_corr is 0.1, H1 is 1.0 => H_measured is 0.1
    measured_complex = np.array([0.1, 0.1], dtype=complex)

    restored = manager.restore_true_response(
        harmonic_order=2,
        target_freqs=target_freqs,
        measured_complex=measured_complex,
        H1_base=H1_base,
        freq_base=freq_base,
    )

    # Restored response should subtract the predistortion contribution and be close to 0.0
    assert np.allclose(restored, 0.0, atol=1e-5)
