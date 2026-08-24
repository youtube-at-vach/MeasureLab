import numpy as np
from src.core.predistortion import PredistortionManager


def test_predistortion_manager_init():
    meas_freqs = np.logspace(1, 4, 100)
    manager = PredistortionManager(
        start_freq=20.0, end_freq=20000.0, meas_freqs=meas_freqs, max_harmonic=3, algorithm="secant"
    )

    assert manager.start_freq == 20.0
    assert manager.end_freq == 20000.0
    assert len(manager.meas_freqs) == 100
    assert manager.max_harmonic == 3
    assert manager.algorithm == "secant"
    assert 2 in manager.F_corr
    assert 3 in manager.F_corr
    assert 4 not in manager.F_corr
    assert np.all(manager.F_corr[2] == 0.0)


def test_generate_predistorted_sweep_and_block():
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

    x_corr, x_base = manager.generate_predistorted_sweep(
        sample_rate=fs, sweep_samples=sweep_samples, k_param=k_param, L_param=L_param, amplitude=amplitude
    )

    assert isinstance(x_corr, np.ndarray)
    assert len(x_corr) == sweep_samples
    assert len(x_base) == sweep_samples
    assert np.max(np.abs(x_corr)) <= amplitude * 1.5

    # Test on-the-fly block generation
    frames = 512
    block_sig, block_ref = manager.generate_predistorted_block(
        block_idx=0,
        frames=frames,
        sample_rate=fs,
        sweep_samples=sweep_samples,
        k_param=k_param,
        L_param=L_param,
        amplitude=amplitude,
        generate_ref=True,
    )
    assert len(block_sig) == frames
    assert len(block_ref) == frames


def test_update_correction_secant_and_newton():
    meas_freqs = np.logspace(1, 4, 100)

    # Test Newton-LM algorithm
    manager_newton = PredistortionManager(
        start_freq=20.0, end_freq=20000.0, meas_freqs=meas_freqs, max_harmonic=3, algorithm="newton"
    )
    num_blocks = 50
    x_data = np.linspace(20.0, 20000.0, num_blocks)
    block_counts = np.ones(num_blocks, dtype=int)

    raw_results = np.zeros((num_blocks, 3), dtype=complex)
    raw_results[:, 0] = 1.0  # H1
    raw_results[:, 1] = 0.1  # H2
    raw_results[:, 2] = 0.05  # H3

    # Iteration 0
    manager_newton.update_correction(
        iteration=0, x_data=x_data, raw_results=raw_results, block_counts=block_counts, mu=0.5
    )
    assert manager_newton.H0_1 is not None

    # Iteration 1
    manager_newton.update_correction(
        iteration=1, x_data=x_data, raw_results=raw_results, block_counts=block_counts, mu=0.5
    )
    assert np.all(manager_newton.F_corr[2][meas_freqs > 80.0] < 0.0)

    # Test Secant algorithm
    manager_secant = PredistortionManager(
        start_freq=20.0, end_freq=20000.0, meas_freqs=meas_freqs, max_harmonic=3, algorithm="secant"
    )
    manager_secant.update_correction(
        iteration=0, x_data=x_data, raw_results=raw_results, block_counts=block_counts, mu=1.0
    )
    manager_secant.update_correction(
        iteration=1, x_data=x_data, raw_results=raw_results, block_counts=block_counts, mu=1.0
    )
    assert len(manager_secant.F_history[2]) == 2
    assert len(manager_secant.H_history[2]) == 2


def test_restore_true_response_and_get_counter_models():
    meas_freqs = np.logspace(1, 4, 100)
    manager = PredistortionManager(start_freq=20.0, end_freq=20000.0, meas_freqs=meas_freqs, max_harmonic=3)

    manager.F_corr[2] = np.ones(100) * 0.1
    H1_base = np.ones(100) * 1.0
    freq_base = meas_freqs

    target_freqs = np.array([100.0, 1000.0])
    measured_complex = np.array([0.1, 0.1], dtype=complex)

    restored = manager.restore_true_response(
        harmonic_order=2,
        target_freqs=target_freqs,
        measured_complex=measured_complex,
        H1_base=H1_base,
        freq_base=freq_base,
    )
    assert np.allclose(restored, 0.0, atol=1e-5)

    models = manager.get_counter_models()
    assert "meas_freqs" in models
    assert "F_corr" in models
    assert 2 in models["F_corr"]
