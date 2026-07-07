import numpy as np
from src.core.nonlinear_response_analyzer_core import (
    generate_schroeder_multisine,
    generate_gaussian_noise,
    identify_bussgang,
    identify_bla_ls,
    identify_tsa_svd,
    SimulatedNonlinearResponseSystem,
    stabilize_poly,
)


def test_signal_generation():
    sample_rate = 44100
    duration = 1.0
    start_freq = 50.0
    end_freq = 5000.0
    amp_db = -6.0

    # Test Schroeder multisine
    u_multi = generate_schroeder_multisine(sample_rate, duration, start_freq, end_freq, amp_db)
    assert len(u_multi) == int(sample_rate * duration)
    assert np.abs(np.max(np.abs(u_multi)) - 10 ** (amp_db / 20.0)) < 1e-3

    # Test Gaussian noise
    u_gauss = generate_gaussian_noise(sample_rate, duration, start_freq, end_freq, amp_db)
    assert len(u_gauss) == int(sample_rate * duration)
    assert np.abs(np.max(np.abs(u_gauss)) - 10 ** (amp_db / 20.0)) < 1e-3


def test_simulated_system():
    sample_rate = 16000
    sim = SimulatedNonlinearResponseSystem(sample_rate)

    u = np.random.normal(0, 0.2, 5000)
    y = sim.process(u, noise_std=0.0)

    assert len(y) == len(u)
    assert not np.any(np.isnan(y))


def test_identify_bussgang():
    sample_rate = 16000
    sim = SimulatedNonlinearResponseSystem(sample_rate)

    # Bussgang is sensitive, needs Gaussian inputs and enough length
    u = generate_gaussian_noise(sample_rate, duration=3.0, start_freq=50.0, end_freq=7000.0, amplitude_db=-6.0)
    y = sim.process(u, noise_std=0.001)

    # Bussgang theorem identification
    g, c, fit_ratio, y_pred, x_est = identify_bussgang(u, y, P=4, lti_len=32)

    assert len(g) == 32
    assert len(c) == 4
    assert fit_ratio > 0.8
    assert len(y_pred) == len(y)
    assert len(x_est) == len(u)


def test_identify_bla_ls():
    sample_rate = 16000
    sim = SimulatedNonlinearResponseSystem(sample_rate)

    # BLA + LS works well with Schroeder multisine
    u = generate_schroeder_multisine(sample_rate, duration=2.0, start_freq=40.0, end_freq=7000.0, amplitude_db=-6.0)
    y = sim.process(u, noise_std=0.001)

    b, a, c, fit_ratio, y_pred, x_est = identify_bla_ls(u, y, P=4, na=2, nb=2)

    assert len(b) == 3
    assert len(a) == 3
    assert len(c) == 4
    assert fit_ratio > 0.95
    assert len(y_pred) == len(y)


def test_identify_tsa_svd():
    sample_rate = 16000
    sim = SimulatedNonlinearResponseSystem(sample_rate)

    # TSA + SVD works well under low noise with rich input
    u = generate_schroeder_multisine(sample_rate, duration=2.0, start_freq=40.0, end_freq=7000.0, amplitude_db=-6.0)
    y = sim.process(u, noise_std=0.0001)

    b, a, c, fit_ratio, y_pred, x_est = identify_tsa_svd(u, y, P=4, na=2, nb=2)

    assert len(b) == 3
    assert len(a) == 3
    assert len(c) == 4
    assert fit_ratio > 0.90
    assert len(y_pred) == len(y)


def test_stabilize_poly():
    # 1. Already stable poly (roots inside unit circle)
    # roots at 0.5 and -0.5 -> poly = (z-0.5)(z+0.5) = z^2 - 0.25 -> [1.0, 0.0, -0.25]
    a_stable = np.array([1.0, 0.0, -0.25])
    a_out = stabilize_poly(a_stable)
    assert np.allclose(a_stable, a_out)

    # 2. Unstable poly (roots outside unit circle)
    # roots at 2.0 and -2.0 -> poly = (z-2.0)(z+2.0) = z^2 - 4.0 -> [1.0, 0.0, -4.0]
    # stabilized roots should be 0.5 and -0.5 -> [1.0, 0.0, -0.25]
    a_unstable = np.array([1.0, 0.0, -4.0])
    a_stabilized = stabilize_poly(a_unstable)
    assert np.allclose(a_stabilized, np.array([1.0, 0.0, -0.25]))

    # 3. Unstable poly with root on unit circle (root at 1.0)
    # roots at 1.0 -> poly = z - 1.0 -> [1.0, -1.0]
    # stabilized root should be pushed slightly inside (0.99) -> [1.0, -0.99]
    a_marginal = np.array([1.0, -1.0])
    a_stabilized_marginal = stabilize_poly(a_marginal)
    assert np.allclose(a_stabilized_marginal, np.array([1.0, -0.99]))
