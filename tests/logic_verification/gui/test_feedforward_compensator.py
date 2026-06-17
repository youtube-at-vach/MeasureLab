import os
import pytest
import numpy as np
import soundfile as sf
from src.gui.widgets.feedforward_compensator import LICFFEngine, OfflineFFCompWorker


@pytest.fixture
def dummy_model_data():
    return {
        "metadata": {
            "sample_rate": 48000,
            "g_ref": 1.0
        },
        "time_domain": {
            "kernels": {
                # Simple h1 impulse response (unit gain)
                "h1": [0.0, 1.0, 0.0]
            }
        }
    }


@pytest.fixture
def engine(dummy_model_data):
    return LICFFEngine(dummy_model_data, f_min=20.0, f_max=20000.0, max_boost_db=12.0)


def test_offline_ff_comp_worker_none_mode(tmp_path, engine):
    # Create a dummy input audio file (peaks at 1.5, which is > 1.0 to check warning / raw behavior)
    input_path = os.path.join(tmp_path, "input.wav")
    output_path = os.path.join(tmp_path, "output_none.wav")

    fs = 48000
    t = np.linspace(0, 0.1, int(fs * 0.1), endpoint=False)
    # Generates a signal that peaks at 1.5
    data = 1.5 * np.sin(2 * np.pi * 1000 * t)
    # Save as 32-bit float input
    sf.write(input_path, data, fs, subtype="FLOAT")

    # Initialize worker with "none" volume matching
    worker = OfflineFFCompWorker(
        input_path=input_path,
        output_path=output_path,
        engine=engine,
        iterative=False,
        iters=1,
        clip_limit=2.0, # allow peak up to 2.0 without clipping in compensate()
        linear_only=True,
        volume_matching="none"
    )

    # Run processing synchronously
    worker.run()

    # Check output
    assert os.path.exists(output_path)
    out_data, out_fs = sf.read(output_path)
    info = sf.info(output_path)

    assert out_fs == fs
    assert info.subtype == "FLOAT"
    # In 'none' mode with 32-bit float output, the signal should be exported raw (peaks at ~1.5)
    # because we disabled auto-normalization.
    assert np.max(np.abs(out_data)) > 1.0
    assert np.allclose(np.max(np.abs(out_data)), 1.5, atol=0.1)


def test_offline_ff_comp_worker_normalize_peak_mode(tmp_path, engine):
    input_path = os.path.join(tmp_path, "input.wav")
    output_path = os.path.join(tmp_path, "output_normalize.wav")

    fs = 48000
    t = np.linspace(0, 0.1, int(fs * 0.1), endpoint=False)
    data = 1.5 * np.sin(2 * np.pi * 1000 * t)
    sf.write(input_path, data, fs, subtype="FLOAT")

    worker = OfflineFFCompWorker(
        input_path=input_path,
        output_path=output_path,
        engine=engine,
        iterative=False,
        iters=1,
        clip_limit=2.0,
        linear_only=True,
        volume_matching="normalize_peak"
    )

    worker.run()

    assert os.path.exists(output_path)
    out_data, out_fs = sf.read(output_path)
    info = sf.info(output_path)

    assert out_fs == fs
    assert info.subtype == "FLOAT"
    # Should be normalized to peak exactly at 1.0 (or extremely close)
    assert np.allclose(np.max(np.abs(out_data)), 1.0, atol=1e-5)


def test_offline_ff_comp_worker_match_peak_mode(tmp_path, engine):
    input_path = os.path.join(tmp_path, "input.wav")
    output_path = os.path.join(tmp_path, "output_match_peak.wav")

    fs = 48000
    t = np.linspace(0, 0.1, int(fs * 0.1), endpoint=False)
    # Normal input peaks at 0.5
    data = 0.5 * np.sin(2 * np.pi * 1000 * t)
    sf.write(input_path, data, fs, subtype="FLOAT")

    worker = OfflineFFCompWorker(
        input_path=input_path,
        output_path=output_path,
        engine=engine,
        iterative=False,
        iters=1,
        clip_limit=2.0,
        linear_only=True,
        volume_matching="match_peak"
    )

    worker.run()

    assert os.path.exists(output_path)
    out_data, out_fs = sf.read(output_path)

    assert out_fs == fs
    # Peak should match the input peak (0.5)
    assert np.allclose(np.max(np.abs(out_data)), 0.5, atol=0.05)


def test_offline_ff_comp_worker_match_peak_clipping_safety(tmp_path, engine):
    input_path = os.path.join(tmp_path, "input.wav")
    output_path = os.path.join(tmp_path, "output_match_peak_safe.wav")

    fs = 48000
    t = np.linspace(0, 0.1, int(fs * 0.1), endpoint=False)
    # Input peaks above 1.0
    data = 1.3 * np.sin(2 * np.pi * 1000 * t)
    sf.write(input_path, data, fs, subtype="FLOAT")

    worker = OfflineFFCompWorker(
        input_path=input_path,
        output_path=output_path,
        engine=engine,
        iterative=False,
        iters=1,
        clip_limit=2.0,
        linear_only=True,
        volume_matching="match_peak"
    )

    worker.run()

    assert os.path.exists(output_path)
    out_data, out_fs = sf.read(output_path)
    # Output peak should be clamped to 1.0 to prevent clipping even if input peak is 1.3
    assert np.allclose(np.max(np.abs(out_data)), 1.0, atol=1e-5)


def test_offline_ff_comp_worker_match_rms_mode(tmp_path, engine):
    input_path = os.path.join(tmp_path, "input.wav")
    output_path = os.path.join(tmp_path, "output_match_rms.wav")
    matched_orig_path = os.path.join(tmp_path, "output_match_rms_matched_orig.wav")

    fs = 48000
    t = np.linspace(0, 0.1, int(fs * 0.1), endpoint=False)
    # Input signal peaking at 0.5 (low RMS)
    data = 0.5 * np.sin(2 * np.pi * 1000 * t)
    sf.write(input_path, data, fs, subtype="FLOAT")

    worker = OfflineFFCompWorker(
        input_path=input_path,
        output_path=output_path,
        engine=engine,
        iterative=False,
        iters=1,
        clip_limit=2.0,
        linear_only=True,
        volume_matching="match_rms"
    )

    worker.run()

    assert os.path.exists(output_path)
    # In match_rms mode, the matched original file must ALWAYS be exported
    assert os.path.exists(matched_orig_path)

    out_data, _ = sf.read(output_path)
    orig_data, _ = sf.read(matched_orig_path)

    # Verify both are written in float format
    assert sf.info(output_path).subtype == "FLOAT"
    assert sf.info(matched_orig_path).subtype == "FLOAT"

    # Verify output and original RMS values match
    rms_out = np.sqrt(np.mean(out_data**2))
    rms_orig = np.sqrt(np.mean(orig_data**2))
    assert np.allclose(rms_out, rms_orig, rtol=1e-2)


def test_compensate_linear_only_no_clipping(engine):
    # Setup a signal that exceeds the clip limit (1.0)
    # We use a 1 kHz sine wave, which is inside the passband.
    t = np.arange(1024) / engine.sample_rate
    u = 1.5 * np.sin(2 * np.pi * 1000.0 * t)

    # linear_only=True: output should not be clipped (peaks at around 1.5)
    u_comp_linear = engine.compensate(u, linear_only=True, clip_limit=1.0)
    assert np.max(np.abs(u_comp_linear)) > 1.4

    # linear_only=False: output should be clipped (peaks at 1.0)
    u_comp_nonlinear = engine.compensate(u, linear_only=False, clip_limit=1.0)
    assert np.max(np.abs(u_comp_nonlinear)) <= 1.01

