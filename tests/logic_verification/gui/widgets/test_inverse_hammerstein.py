import pytest
import os
import numpy as np
import soundfile as sf
from unittest.mock import MagicMock

from src.gui.widgets.inverse_hammerstein import WaveProcessWorker


@pytest.fixture
def temp_wav_files(tmp_path):
    input_path = tmp_path / "input.wav"
    output_path = tmp_path / "output.wav"

    # Create a 1-second sine wave at 48000 Hz, stereo
    sr = 48000
    t = np.linspace(0, 1.0, sr, endpoint=False)
    # Stereo: channel 0 is 1kHz sine, channel 1 is 2kHz sine
    data = np.stack([np.sin(2 * np.pi * 1000 * t), np.sin(2 * np.pi * 2000 * t)], axis=1)

    sf.write(str(input_path), data, sr, subtype="PCM_16")

    return str(input_path), str(output_path), sr


@pytest.fixture
def dummy_inverse_model(temp_wav_files):
    _, _, sr = temp_wav_files
    # Simple model with h1=1, other kernels=0
    N = 1024
    h1 = np.zeros(N)
    h1[0] = 1.0  # Identity filter

    kernels = {
        "h1": h1.tolist(),
        "h2": np.zeros(N).tolist(),
        "h3": np.zeros(N).tolist(),
        "h4": np.zeros(N).tolist(),
        "h5": np.zeros(N).tolist(),
    }

    return {
        "metadata": {
            "sample_rate": sr,
        },
        "time_domain": {
            "kernels": kernels
        }
    }


def test_wave_process_worker_same_sr(qtbot, temp_wav_files, dummy_inverse_model):
    input_path, output_path, sr = temp_wav_files

    worker = WaveProcessWorker(input_path, output_path, dummy_inverse_model)

    # Spy on finished signal
    finished_spy = MagicMock()
    worker.finished.connect(finished_spy)

    worker.run()

    # Assert successful completion
    finished_spy.assert_called_once()
    success, msg = finished_spy.call_args[0]
    assert success

    # Read output and verify it exists and is correct
    assert os.path.exists(output_path)
    out_data, out_sr = sf.read(output_path)
    assert out_sr == sr
    assert out_data.shape == (sr, 2)

    # Since h1[0] = 1.0 and others are 0, it should be an identity mapping
    in_data, _ = sf.read(input_path)
    # Compare with some tolerance (due to oversampling filter decay at edges)
    # Let's check the middle section where edge transients have died down
    np.testing.assert_allclose(out_data[8192:-8192], in_data[8192:-8192], atol=1e-4)


def test_wave_process_worker_resampling(qtbot, temp_wav_files, dummy_inverse_model):
    input_path, output_path, _ = temp_wav_files

    # Change model sample rate to force resampling (e.g. 44100 Hz model on 48000 Hz file)
    dummy_inverse_model["metadata"]["sample_rate"] = 44100

    worker = WaveProcessWorker(input_path, output_path, dummy_inverse_model)

    finished_spy = MagicMock()
    worker.finished.connect(finished_spy)

    worker.run()

    finished_spy.assert_called_once()
    success, msg = finished_spy.call_args[0]
    assert success
    assert "Resampled" in msg

    assert os.path.exists(output_path)
    out_data, out_sr = sf.read(output_path)
    assert out_sr == 44100
