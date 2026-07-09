import pytest
import numpy as np
from src.core.predistortion_applicator import PredistortionApplicator


@pytest.fixture
def dummy_model_data():
    """Generates a dummy Hammerstein inverse model for testing."""
    fs = 48000
    t = np.arange(100) / fs
    # Create simple impulse response kernels (decaying exponentials)
    h1 = np.exp(-1000 * t)
    h2 = 0.1 * np.exp(-2000 * t)
    h3 = 0.05 * np.exp(-3000 * t)

    return {
        "metadata": {
            "sample_rate": fs,
            "model_direction": "inverse",
        },
        "time_domain": {
            "kernels": {
                "h1": h1.tolist(),
                "h2": h2.tolist(),
                "h3": h3.tolist(),
            }
        },
    }


def test_load_model_and_reset(dummy_model_data):
    applicator = PredistortionApplicator()
    applicator.load_model(dummy_model_data)

    assert applicator.sample_rate == 48000
    assert applicator.P == 3
    assert len(applicator.g_kernels) == 3
    assert len(applicator.h_kernels) == 3
    # Check that kernels are loaded exactly as raw kernels (no approximation)
    for idx in range(3):
        h_key = f"h{idx+1}"
        expected = np.array(dummy_model_data["time_domain"]["kernels"][h_key], dtype=np.float32)
        np.testing.assert_array_equal(applicator.g_kernels[idx], expected)
        np.testing.assert_array_equal(applicator.h_kernels[idx], expected)
    assert len(applicator.g_zi) == 3

    # Check reset_states
    applicator.reset_states()
    assert len(applicator.g_zi) == 3
    for idx, zi in enumerate(applicator.g_zi):
        assert len(zi) == len(applicator.g_kernels[idx]) - 1


def test_apply_predistortion_block_no_os(dummy_model_data):
    applicator = PredistortionApplicator()
    applicator.load_model(dummy_model_data)
    applicator.os_factor = 1  # No oversampling

    # Process block
    block_in = np.sin(2.0 * np.pi * 1000.0 * np.arange(512) / 48000.0).astype(np.float32)
    block_out = applicator.apply_predistortion_block(block_in)

    assert len(block_out) == len(block_in)
    assert not np.any(np.isnan(block_out))
    assert not np.any(np.isinf(block_out))


def test_apply_predistortion_block_with_os(dummy_model_data):
    applicator = PredistortionApplicator()
    applicator.load_model(dummy_model_data)
    applicator.os_factor = 4  # 4x oversampling

    block_in = np.sin(2.0 * np.pi * 1000.0 * np.arange(512) / 48000.0).astype(np.float32)
    block_out = applicator.apply_predistortion_block(block_in)

    assert len(block_out) == len(block_in)
    assert not np.any(np.isnan(block_out))
    assert not np.any(np.isinf(block_out))


def test_run_simulation(dummy_model_data):
    applicator = PredistortionApplicator()
    applicator.load_model(dummy_model_data)

    input_sig = np.sin(2.0 * np.pi * 1000.0 * np.arange(2048) / 48000.0).astype(np.float32)
    comp_sig, raw_dut, comp_dut = applicator.run_simulation(input_sig)

    assert len(comp_sig) == len(input_sig)
    assert len(raw_dut) == len(input_sig)
    assert len(comp_dut) == len(input_sig)

    assert not np.any(np.isnan(comp_sig))
    assert not np.any(np.isnan(raw_dut))
    assert not np.any(np.isnan(comp_dut))
