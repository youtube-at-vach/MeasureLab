import pytest
import os
import numpy as np
import soundfile as sf
from unittest.mock import MagicMock

from src.gui.widgets.feedforward_compensator import OfflineFFCompWorker, LICFFEngine


@pytest.fixture
def temp_wav_files(tmp_path):
    input_path = tmp_path / "input.wav"
    output_path = tmp_path / "output.wav"

    # Create a 0.5-second sine wave at 48000 Hz, stereo
    sr = 48000
    t = np.linspace(0, 0.5, int(sr * 0.5), endpoint=False)
    # Stereo: channel 0 is 1kHz sine, channel 1 is 2kHz sine
    data = np.stack([np.sin(2 * np.pi * 1000 * t), np.sin(2 * np.pi * 2000 * t)], axis=1)

    sf.write(str(input_path), data, sr, subtype="PCM_16")

    return str(input_path), str(output_path), sr


@pytest.fixture
def dummy_model_data(temp_wav_files):
    _, _, sr = temp_wav_files
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


def test_licff_engine_basic(dummy_model_data):
    engine = LICFFEngine(dummy_model_data, f_min=60, f_max=17000)
    assert engine.sample_rate == 48000
    assert engine.N == 1024

    # Test forward_model with zeros should output zeros (modulo scaling/q0)
    # In our dummy, h1[0]=1.0 -> q1[0]=1.0 -> G_scale=1.0. All others are 0.
    # The linear output should be identity (with bandpass filter applied)
    # Generate 1 kHz sine inside passband
    t = np.arange(1024) / 48000.0
    u = 0.5 * np.sin(2 * np.pi * 1000.0 * t)
    y_lin = engine.linear_output(u)

    # Output should not be completely zero
    assert np.max(np.abs(y_lin)) > 0.1


def test_offline_ff_worker(qtbot, temp_wav_files, dummy_model_data):
    input_path, output_path, sr = temp_wav_files

    engine = LICFFEngine(dummy_model_data, f_min=60, f_max=17000)
    worker = OfflineFFCompWorker(
        input_path,
        output_path,
        engine,
        iterative=True,
        iters=3,
        clip_limit=1.5
    )

    finished_spy = MagicMock()
    worker.finished.connect(finished_spy)

    worker.run()

    # Assert successful completion
    finished_spy.assert_called_once()
    success, msg = finished_spy.call_args[0]
    assert success

    # Verify output file
    assert os.path.exists(output_path)
    out_data, out_sr = sf.read(output_path)
    assert out_sr == sr
    assert len(out_data) == int(sr * 0.5)
