import os
import tempfile
import numpy as np
from src.core.hammerstein_model import save_hammerstein_model, load_hammerstein_model


def test_hammerstein_model_serialization():
    # Construct mock data payload
    mock_data = {
        "metadata": {
            "module": "TestModule",
            "sample_rate": 48000,
            "start_freq": 20.0,
            "end_freq": 20000.0,
            "P": 5,
        },
        "time_domain": {
            "time_ms": np.linspace(-5.0, 35.0, 100),
            "kernels": {
                "h1": np.random.rand(100),
                "h2": np.random.rand(100),
                "h3": np.random.rand(100),
                "h4": np.random.rand(100),
                "h5": np.random.rand(100),
            },
        },
        "frequency_domain": {
            "freqs": np.linspace(20.0, 20000.0, 50),
            "magnitudes_db": {
                "h1": np.linspace(0, -10, 50),
                "h2": np.linspace(-40, -50, 50),
                "h3": np.linspace(-50, -60, 50),
                "h4": np.linspace(-60, -70, 50),
                "h5": np.linspace(-70, -80, 50),
            },
            "phases_deg": {
                "h1": np.zeros(50),
                "h2": np.zeros(50),
                "h3": np.zeros(50),
                "h4": np.zeros(50),
                "h5": np.zeros(50),
                "ref_phase": np.zeros(50),
            },
        },
    }

    # Save to a temporary file
    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = os.path.join(tmpdir, "test_model.json")
        save_hammerstein_model(filepath, mock_data)

        # Load back
        loaded_data = load_hammerstein_model(filepath)

        # Assert metadata
        assert loaded_data["metadata"]["module"] == "TestModule"
        assert loaded_data["metadata"]["sample_rate"] == 48000
        assert loaded_data["metadata"]["start_freq"] == 20.0
        assert loaded_data["metadata"]["end_freq"] == 20000.0
        assert loaded_data["metadata"]["P"] == 5
        assert "export_timestamp" in loaded_data["metadata"]

        # Assert time domain
        np.testing.assert_allclose(
            loaded_data["time_domain"]["time_ms"], mock_data["time_domain"]["time_ms"]
        )
        for k in ["h1", "h2", "h3", "h4", "h5"]:
            np.testing.assert_allclose(
                loaded_data["time_domain"]["kernels"][k],
                mock_data["time_domain"]["kernels"][k],
            )

        # Assert frequency domain
        np.testing.assert_allclose(
            loaded_data["frequency_domain"]["freqs"], mock_data["frequency_domain"]["freqs"]
        )
        for k in ["h1", "h2", "h3", "h4", "h5"]:
            np.testing.assert_allclose(
                loaded_data["frequency_domain"]["magnitudes_db"][k],
                mock_data["frequency_domain"]["magnitudes_db"][k],
            )
            np.testing.assert_allclose(
                loaded_data["frequency_domain"]["phases_deg"][k],
                mock_data["frequency_domain"]["phases_deg"][k],
            )
        np.testing.assert_allclose(
            loaded_data["frequency_domain"]["phases_deg"]["ref_phase"],
            mock_data["frequency_domain"]["phases_deg"]["ref_phase"],
        )
