import pytest
import numpy as np
from unittest.mock import patch
from src.core.hammerstein_model import (
    save_hammerstein_model,
    load_hammerstein_model,
    set_active_model,
    get_active_model,
    has_active_model,
    estimate_hammerstein_kernels,
)


@pytest.fixture
def sample_hammerstein_data():
    return {
        "metadata": {"setup_name": "test_setup"},
        "time_domain": {
            "time_ms": np.array([0.0, 1.0, 2.0], dtype=float),
            "kernels": {
                "h1": np.array([0.1, 0.2, 0.3], dtype=float),
                "h2": np.array([0.4, 0.5, 0.6], dtype=float),
            },
        },
        "frequency_domain": {
            "freqs": np.array([100.0, 1000.0], dtype=float),
            "magnitudes_db": {"h1": np.array([-10.0, -20.0], dtype=float)},
            "phases_deg": {"h1": np.array([45.0, 90.0], dtype=float)},
        },
    }


def test_save_and_load_hammerstein_model(tmp_path, sample_hammerstein_data):
    filepath = tmp_path / "test_model.json"

    # Test saving
    save_hammerstein_model(filepath, sample_hammerstein_data)
    assert filepath.exists()

    # Test loading
    loaded_data = load_hammerstein_model(filepath)

    # Verify metadata
    assert "format_version" in loaded_data["metadata"]
    assert loaded_data["metadata"]["setup_name"] == "test_setup"

    # Verify time_domain arrays
    np.testing.assert_allclose(loaded_data["time_domain"]["time_ms"], sample_hammerstein_data["time_domain"]["time_ms"])
    np.testing.assert_allclose(
        loaded_data["time_domain"]["kernels"]["h1"], sample_hammerstein_data["time_domain"]["kernels"]["h1"]
    )

    # Verify frequency_domain arrays
    np.testing.assert_allclose(
        loaded_data["frequency_domain"]["freqs"], sample_hammerstein_data["frequency_domain"]["freqs"]
    )
    np.testing.assert_allclose(
        loaded_data["frequency_domain"]["magnitudes_db"]["h1"],
        sample_hammerstein_data["frequency_domain"]["magnitudes_db"]["h1"],
    )
    np.testing.assert_allclose(
        loaded_data["frequency_domain"]["phases_deg"]["h1"],
        sample_hammerstein_data["frequency_domain"]["phases_deg"]["h1"],
    )


def test_save_hammerstein_model_error_mocked(tmp_path, sample_hammerstein_data):
    # Use mock to force an error during JSON dumping to ensure exception handling and logging are tested
    filepath = tmp_path / "test_model_error.json"
    with patch("src.core.hammerstein_model.json.dump") as mock_dump:
        mock_dump.side_effect = TypeError("Mocked JSON dump error")
        with patch("src.core.hammerstein_model.logger") as mock_logger:
            with pytest.raises(TypeError, match="Mocked JSON dump error"):
                save_hammerstein_model(filepath, sample_hammerstein_data)

            # Verify the error was logged
            mock_logger.error.assert_called_once()
            args, kwargs = mock_logger.error.call_args
            assert "Failed to save Hammerstein model" in args[0]


def test_active_model_cache(sample_hammerstein_data):
    import src.core.hammerstein_model as hm

    # Reset state before testing
    hm.set_active_model(None)

    assert has_active_model() is False
    assert get_active_model() is None

    set_active_model(sample_hammerstein_data)

    assert has_active_model() is True
    cached_model = get_active_model()
    assert cached_model is sample_hammerstein_data

    # Clean up state
    set_active_model(None)
    assert has_active_model() is False


def test_estimate_hammerstein_kernels_invalid_freqs():
    # Test when valid frequencies < 2
    amplitudes = np.array([1.0, 2.0])
    plot_freqs = np.array([0.0, -100.0])  # Invalid frequencies (<= 0)
    avg_responses = np.zeros((2, 2, 3), dtype=complex)

    H_freqs, sorted_freqs = estimate_hammerstein_kernels(
        amplitudes=amplitudes,
        avg_responses=avg_responses,
        plot_freqs=plot_freqs,
        max_harmonic=3,
        sample_rate=48000
    )

    assert len(H_freqs) == 3
    for H in H_freqs:
        np.testing.assert_array_equal(H, np.zeros(2, dtype=complex))
    np.testing.assert_array_equal(sorted_freqs, np.zeros(0))


def test_estimate_hammerstein_kernels_linear():
    # Test a perfectly linear system (only H1 active)
    amplitudes = np.array([0.5, 1.0, 2.0])
    plot_freqs = np.array([100.0, 200.0, 300.0])
    max_harmonic = 3
    sample_rate = 48000

    # K=3 amplitudes, J=3 frequencies, P=3 harmonics
    avg_responses = np.zeros((3, 3, 3), dtype=complex)

    # In XFER mode, if it's perfectly linear, the response Y1 = H1 * R * phase_correction
    # In estimate_hammerstein_kernels:
    # g_scaled = avg_response * R * phase_correction
    # For H1 = 1.0, we want H1 output to be 1.0
    # Let's set avg_responses such that H1 becomes 1.0
    # For p=0 (harmonic 1), phase_correction is 1.0
    # So g1_scaled = avg_responses * R * 1.0
    # H1 is calculated as sum(g1 * R) / sum(R^2).
    # If avg_responses = 1.0 for all R and J, then g1 = 1.0 * R.
    # sum(g1 * R) = sum(R^2). H1 = 1.0.

    for k, r in enumerate(amplitudes):
        avg_responses[k, :, 0] = 1.0

    H_freqs, sorted_freqs = estimate_hammerstein_kernels(
        amplitudes=amplitudes,
        avg_responses=avg_responses,
        plot_freqs=plot_freqs,
        max_harmonic=max_harmonic,
        sample_rate=sample_rate,
        input_mode="XFER"
    )

    assert len(H_freqs) == max_harmonic

    # H1 should be approx 1.0 at all frequencies
    np.testing.assert_allclose(np.real(H_freqs[0]), np.ones(3), atol=1e-5)
    np.testing.assert_allclose(np.imag(H_freqs[0]), np.zeros(3), atol=1e-5)

    # Higher harmonics should be approx 0 (excluding NaNs from out-of-bounds interpolation)
    for p in range(1, max_harmonic):
        mask = ~np.isnan(H_freqs[p])
        np.testing.assert_allclose(np.abs(H_freqs[p][mask]), np.zeros(np.sum(mask)), atol=1e-5)


def test_estimate_hammerstein_kernels_nonlinear():
    # Test a system with known nonlinear components
    amplitudes = np.array([1.0, 2.0])
    plot_freqs = np.array([100.0, 1000.0])
    max_harmonic = 3
    sample_rate = 48000

    avg_responses = np.zeros((2, 2, 3), dtype=complex)

    # Let's simulate that g1 and g3 have specific values.
    # We'll set avg_responses such that:
    # for p=0 (h1): val = 2.0 / R
    # for p=2 (h3): val = 3.0 / R
    # Wait, g_scaled[amp_idx, :, p] = val * R * phase_corrections[p]
    # For p=0, phase = 1.0. If val = 2.0 / R, g_scaled = 2.0
    # For p=2, phase = -1.0. If val = -3.0 / R, g_scaled = 3.0

    # Then g1 = 2.0, g3 = 3.0
    # H3 = 4 * sum(g3 * R^3) / sum(R^6)
    # R = [1, 2]. R^3 = [1, 8]. R^6 = [1, 64]. sum(R^6) = 65
    # sum(g3 * R^3) = sum(3.0 * R^3) = 3.0 * (1 + 8) = 27
    # H3 = 4 * 27 / 65 = 108 / 65 ≈ 1.661538

    # H1 = sum( (g1 - 0.75 * H3 * R^3) * R ) / sum(R^2)
    # H3 = 108/65
    # g1 = 2.0
    # term1 for R=1: (2.0 - 0.75 * 108/65 * 1) * 1 = (2.0 - 81/65) = 49/65
    # term2 for R=2: (2.0 - 0.75 * 108/65 * 8) * 2 = (2.0 - 648/65) * 2 = (130/65 - 648/65) * 2 = -518/65 * 2 = -1036/65
    # sum = 49/65 - 1036/65 = -987/65
    # sum(R^2) = 1 + 4 = 5
    # H1 = -987 / (65 * 5) = -987 / 325 ≈ -3.0369

    # To keep things simpler, let's just assert that the calculation matches expected formula.

    for k, r in enumerate(amplitudes):
        avg_responses[k, :, 0] = 2.0 / r
        avg_responses[k, :, 2] = -3.0 / r  # To cancel the -1.0 phase correction

    H_freqs, sorted_freqs = estimate_hammerstein_kernels(
        amplitudes=amplitudes,
        avg_responses=avg_responses,
        plot_freqs=plot_freqs,
        max_harmonic=max_harmonic,
        sample_rate=sample_rate,
        input_mode="XFER"
    )

    expected_H3 = 108.0 / 65.0
    expected_H1 = -987.0 / 325.0

    # H1 gets no low-pass filter
    np.testing.assert_allclose(np.real(H_freqs[0]), np.full(2, expected_H1), atol=1e-5)
    np.testing.assert_allclose(np.imag(H_freqs[0]), np.zeros(2), atol=1e-5)

    # For H3 (p=2), it maps valid H3 to f_lookups (freq/3).
    # Since f_lookups (33.33, 333.33) are mostly < min(xp) (100.0), they become NaN.
    # We test that H2 is exactly 0 and H3 has NaNs where expected, and the valid parts match expected values.

    # H2 is not stimulated, should be exactly 0 where valid.
    mask_h2 = ~np.isnan(H_freqs[1])
    np.testing.assert_allclose(np.abs(H_freqs[1][mask_h2]), np.zeros(np.sum(mask_h2)), atol=1e-5)

    # H3 is stimulated. Check non-NaN values against expected_H3 (with LPF).
    f_cut = min(20000.0, 1.15 * sample_rate / 2)
    mask_h3 = ~np.isnan(H_freqs[2])

    lpf = 1.0 / np.sqrt(1.0 + (sorted_freqs[mask_h3] / f_cut) ** 16)

    np.testing.assert_allclose(np.real(H_freqs[2][mask_h3]), np.full(np.sum(mask_h3), expected_H3) * lpf, atol=1e-5)
    np.testing.assert_allclose(np.imag(H_freqs[2][mask_h3]), np.zeros(np.sum(mask_h3)), atol=1e-5)
