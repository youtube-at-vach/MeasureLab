import json
import pytest
import numpy as np
from unittest.mock import patch
from src.core.hammerstein_model import (
    save_hammerstein_model,
    load_hammerstein_model,
    set_active_model,
    get_active_model,
    has_active_model,
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
    hm._ACTIVE_MODEL_CACHE = None

    assert has_active_model() is False
    assert get_active_model() is None

    set_active_model(sample_hammerstein_data)

    assert has_active_model() is True
    cached_model = get_active_model()
    assert cached_model is sample_hammerstein_data

    # Clean up state
    set_active_model(None)
    assert has_active_model() is False
