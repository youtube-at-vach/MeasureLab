import pytest
import os
import numpy as np
import soundfile as sf
from unittest.mock import MagicMock

from src.gui.widgets.feedforward_compensator import (
    OfflineFFCompWorker,
    LICFFEngine,
    FeedforwardCompensator,
    FeedforwardCompensatorWidget,
)


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
        "time_domain": {"kernels": kernels},
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
    worker = OfflineFFCompWorker(input_path, output_path, engine, iterative=True, iters=3, clip_limit=1.5)

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


def test_direct_kernel_mapping(temp_wav_files):
    _, _, sr = temp_wav_files
    N = 8
    # Test direct copy mapping of kernels:
    # q0 should be all zeros.
    # q1..q5 should be exact copies of h1..h5.

    h1 = np.zeros(N)
    h1[0] = 1.0
    h2 = np.zeros(N)
    h2[0] = 0.1
    h3 = np.zeros(N)
    h3[0] = 0.08
    h4 = np.zeros(N)
    h4[0] = 0.04
    h5 = np.zeros(N)
    h5[0] = 0.02

    model_data = {
        "metadata": {
            "sample_rate": sr,
        },
        "time_domain": {
            "kernels": {
                "h1": h1.tolist(),
                "h2": h2.tolist(),
                "h3": h3.tolist(),
                "h4": h4.tolist(),
                "h5": h5.tolist(),
            }
        },
    }

    engine = LICFFEngine(model_data, f_min=60, f_max=17000)

    # Check that computed power-series kernels match original ones directly
    assert np.allclose(engine.q0, np.zeros(N))
    assert np.allclose(engine.q1, h1)
    assert np.allclose(engine.q2, h2)
    assert np.allclose(engine.q3, h3)
    assert np.allclose(engine.q4, h4)
    assert np.allclose(engine.q5, h5)


def test_noise_thresholding(temp_wav_files):
    _, _, sr = temp_wav_files
    N = 8
    h1 = np.zeros(N)
    h1[0] = 1.0
    h2 = np.zeros(N)
    h2[0] = 0.1  # -20 dB -> should NOT be zeroed if threshold is -40 dB
    h3 = np.zeros(N)
    h3[0] = 0.001  # -60 dB -> SHOULD be zeroed if threshold is -40 dB
    h4 = np.zeros(N)
    h4[0] = 0.03  # -30.4 dB -> should NOT be zeroed if threshold is -40 dB
    h5 = np.zeros(N)
    h5[0] = 0.0001  # -80 dB -> SHOULD be zeroed if threshold is -40 dB

    model_data = {
        "metadata": {
            "sample_rate": sr,
        },
        "time_domain": {
            "kernels": {
                "h1": h1.tolist(),
                "h2": h2.tolist(),
                "h3": h3.tolist(),
                "h4": h4.tolist(),
                "h5": h5.tolist(),
            }
        },
    }

    # threshold_db = -40.0 dB
    engine = LICFFEngine(model_data, f_min=60, f_max=17000, threshold_db=-40.0)

    assert np.allclose(engine.q1, h1)
    assert np.allclose(engine.q2, h2)
    assert np.allclose(engine.q3, np.zeros(N))  # zeroed out!
    assert np.allclose(engine.q4, h4)
    assert np.allclose(engine.q5, np.zeros(N))  # zeroed out!


def test_feedforward_compensator_widget_simulation(qtbot, dummy_model_data):
    audio_engine = MagicMock()
    module = FeedforwardCompensator(audio_engine)
    widget = FeedforwardCompensatorWidget(module)
    qtbot.addWidget(widget)

    # Initially run_simulation should do nothing if no engine is loaded
    widget.run_simulation()

    # Load model
    widget.module.engine = LICFFEngine(dummy_model_data, f_min=60, f_max=17000)
    widget.model_data = dummy_model_data

    # Test all signal types in the combobox to ensure they compile/run without exception
    for i in range(widget.combo_signal.count()):
        widget.combo_signal.setCurrentIndex(i)
        widget.run_simulation()


def test_compensate_delay_cancellation_nonlinear(dummy_model_data):
    # Setup model with a known delay of 10 samples
    N = 128
    h1 = np.zeros(N)
    h1[10] = 1.0  # 10 samples delay

    dummy_model_data["time_domain"]["kernels"]["h1"] = h1.tolist()

    engine = LICFFEngine(dummy_model_data, f_min=60, f_max=17000)

    # Test signal: sine wave
    t = np.arange(N) / 48000.0
    u = 0.5 * np.sin(2 * np.pi * 1000.0 * t)

    # Original linear compensate cancels delay
    u_comp_lin = engine.compensate(u, linear_only=True)
    y_comp_lin = engine.forward_model(u_comp_lin)

    # Corrected nonlinear compensate should ALSO cancel delay!
    u_comp_nonlin = engine.compensate(u, linear_only=False, iterative=True, iters=2)
    y_comp_nonlin = engine.forward_model(u_comp_nonlin)

    # Calculate cross-correlation to find peak delay relative to input u
    C_lin = np.fft.irfft(np.fft.rfft(y_comp_lin) * np.conj(np.fft.rfft(u)), n=N)
    delay_lin = np.argmax(np.abs(C_lin))
    if delay_lin > N // 2:
        delay_lin -= N

    C_nonlin = np.fft.irfft(np.fft.rfft(y_comp_nonlin) * np.conj(np.fft.rfft(u)), n=N)
    delay_nonlin = np.argmax(np.abs(C_nonlin))
    if delay_nonlin > N // 2:
        delay_nonlin -= N

    # Both should have 0 delay (fully cancelled) instead of 10 samples delay
    assert abs(delay_lin) <= 1
    assert abs(delay_nonlin) <= 1


def test_transient_no_wraparound(qtbot, dummy_model_data):
    # Setup model with delay
    N = 256
    h1 = np.zeros(N)
    h1[20] = 1.0  # 20 samples delay
    dummy_model_data["time_domain"]["kernels"]["h1"] = h1.tolist()

    audio_engine = MagicMock()
    module = FeedforwardCompensator(audio_engine)
    widget = FeedforwardCompensatorWidget(module)
    qtbot.addWidget(widget)

    widget.module.engine = LICFFEngine(dummy_model_data, f_min=60, f_max=17000)
    widget.model_data = dummy_model_data

    # Run Step Response simulation
    widget.combo_signal.setCurrentText("Step Response")
    widget.run_simulation()

    # Verify the aligned compensated data
    t_axis, y_comp_aligned = widget.curve_t_comp.getData()

    assert np.all(np.abs(y_comp_aligned[:20]) < 0.05)


def test_regularization_modes(qtbot, dummy_model_data):
    audio_engine = MagicMock()
    module = FeedforwardCompensator(audio_engine)
    widget = FeedforwardCompensatorWidget(module)
    qtbot.addWidget(widget)

    # Initially configure and load model
    widget.module.engine = LICFFEngine(dummy_model_data, f_min=60, f_max=17000)
    widget.model_data = dummy_model_data

    # Test get_reg_params and UI combo settings
    # 0: Auto (Broadband / Music)
    widget.combo_reg_mode.setCurrentIndex(0)
    mode, val = widget.get_reg_params()
    assert mode == "auto_broadband"
    assert not widget.spin_reg_val.isEnabled()
    assert widget.spin_reg_val.suffix() == " dB"

    # 1: Auto (Pure Tones)
    widget.combo_reg_mode.setCurrentIndex(1)
    mode, val = widget.get_reg_params()
    assert mode == "auto_tones"
    assert not widget.spin_reg_val.isEnabled()

    # 2: Manual (Max Boost)
    widget.combo_reg_mode.setCurrentIndex(2)
    mode, val = widget.get_reg_params()
    assert mode == "manual_boost"
    assert widget.spin_reg_val.isEnabled()

    # 3: Manual (Tikhonov)
    widget.combo_reg_mode.setCurrentIndex(3)
    mode, val = widget.get_reg_params()
    assert mode == "manual_tikhonov"
    assert widget.spin_reg_val.isEnabled()
    assert widget.spin_reg_val.suffix() == ""

    # Test engine bisection solver with a custom model having a deep notch
    N = 1024
    h1 = np.zeros(N)
    h1[0] = 1.0
    h1[2] = -0.9  # Creates a deep notch in frequency response
    dummy_model_data["time_domain"]["kernels"]["h1"] = h1.tolist()
    engine = LICFFEngine(dummy_model_data, f_min=60, f_max=17000, reg_mode="manual_boost", reg_val=6.0)

    # Check that resolved eps_in limits the maximum filter boost to exactly 6 dB
    _, F_inv, _ = engine._prepare_buffers_for_length(N)
    max_boost = np.max(np.abs(F_inv))
    max_boost_db = 20 * np.log10(max_boost)
    # The actual boost should be very close to the target of 6.0 dB
    assert abs(max_boost_db - 6.0) < 0.1


def test_clipping_and_instability_detection(temp_wav_files, dummy_model_data):
    input_path, output_path, sr = temp_wav_files
    engine = LICFFEngine(dummy_model_data, f_min=60, f_max=17000)

    # 1. Test compensate statistics with intentional clipping
    t = np.arange(1024) / 48000.0
    u_large = 2.0 * np.sin(2 * np.pi * 1000.0 * t)  # Amp = 2.0 > clip_limit = 1.5

    stats_clip = {}
    _ = engine.compensate(u_large, iterative=True, iters=3, clip_limit=1.5, stats=stats_clip)
    assert stats_clip["clipping_count"] > 0
    assert not stats_clip["instability_detected"]

    # 2. Test compensate instability detection (force huge signal or NaN to trigger runaway)
    u_huge = 100.0 * np.sin(2 * np.pi * 1000.0 * t)
    stats_instability = {}
    _ = engine.compensate(u_huge, iterative=True, iters=3, clip_limit=1.5, stats=stats_instability)
    assert stats_instability["instability_detected"]

    # 3. Test OfflineFFCompWorker output message containing stats
    worker = OfflineFFCompWorker(input_path, output_path, engine, iterative=True, iters=3, clip_limit=0.5)

    finished_spy = MagicMock()
    worker.finished.connect(finished_spy)
    worker.run()

    finished_spy.assert_called_once()
    success, msg = finished_spy.call_args[0]
    assert success
    # Check that message contains statistical labels
    assert "Clips" in msg or "クリップ数" in msg or "Stats" in msg or "統計" in msg
    assert "Oscillation" in msg or "発振" in msg


def test_abort_on_instability(temp_wav_files, dummy_model_data):
    input_path, output_path, sr = temp_wav_files

    # We do not overwrite the input file. The default input has peak amplitude 1.0.
    # By setting clip_limit=0.05, the signal peak (1.0) exceeds 10 * clip_limit (0.5),
    # which triggers the instability detection logic.
    engine = LICFFEngine(dummy_model_data, f_min=60, f_max=17000)

    # When abort_on_instability=True, it should fail (success=False) with an instability error message.
    worker = OfflineFFCompWorker(
        input_path, output_path, engine, iterative=True, iters=3, clip_limit=0.05, abort_on_instability=True
    )

    finished_spy = MagicMock()
    worker.finished.connect(finished_spy)
    worker.run()

    finished_spy.assert_called_once()
    success, msg = finished_spy.call_args[0]
    assert not success
    assert "Instability/runaway detected" in msg or "フィルターの暴走" in msg

    # When abort_on_instability=False, it should complete successfully (success=True) even with instability warnings.
    worker_no_abort = OfflineFFCompWorker(
        input_path, output_path, engine, iterative=True, iters=3, clip_limit=0.05, abort_on_instability=False
    )

    finished_spy_no_abort = MagicMock()
    worker_no_abort.finished.connect(finished_spy_no_abort)
    worker_no_abort.run()

    finished_spy_no_abort.assert_called_once()
    success_na, msg_na = finished_spy_no_abort.call_args[0]
    assert success_na




