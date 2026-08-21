from unittest.mock import MagicMock

import numpy as np
import pytest

from src.gui.widgets.distortion_analyzer import DistortionAnalyzer


@pytest.fixture
def audio_engine():
    engine = MagicMock()
    engine.sample_rate = 48000
    engine.register_callback.return_value = "distortion-callback"
    engine.is_active.return_value = True
    return engine


def _registered_callback(engine):
    return engine.register_callback.call_args.args[0]


def test_start_failure_rolls_back_callback_state(audio_engine):
    audio_engine.register_callback.side_effect = RuntimeError("device unavailable")
    analyzer = DistortionAnalyzer(audio_engine)

    with pytest.raises(RuntimeError, match="device unavailable"):
        analyzer.start_analysis()

    assert not analyzer.is_running
    assert analyzer.callback_id is None


def test_inactive_stream_after_registration_is_unregistered(audio_engine):
    audio_engine.is_active.return_value = False
    analyzer = DistortionAnalyzer(audio_engine)

    with pytest.raises(RuntimeError, match="Audio stream failed to start"):
        analyzer.start_analysis()

    audio_engine.unregister_callback.assert_called_once_with("distortion-callback")
    assert not analyzer.is_running
    assert analyzer.callback_id is None


def test_input_clipping_is_latched_until_a_new_run(audio_engine):
    analyzer = DistortionAnalyzer(audio_engine)
    analyzer.start_analysis()
    callback = _registered_callback(audio_engine)
    indata = np.ones((64, 2), dtype=float)
    outdata = np.zeros((64, 2), dtype=float)

    callback(indata, outdata, len(indata), None, None)

    integrity = analyzer.get_integrity_snapshot()
    assert not integrity["measurement_valid"]
    assert integrity["input_clipping"]
    assert integrity["reasons"] == ["Input clipping detected"]

    analyzer.stop_analysis()
    analyzer.start_analysis()
    assert analyzer.measurement_valid
    assert analyzer.get_integrity_snapshot()["reasons"] == []


def test_xrun_and_data_gap_invalidate_the_run(audio_engine):
    class CallbackStatus:
        input_overflow = True
        input_underflow = False
        output_overflow = False
        output_underflow = False

    analyzer = DistortionAnalyzer(audio_engine)
    analyzer.start_analysis()
    callback = _registered_callback(audio_engine)

    callback(np.zeros((32, 1)), np.zeros((32, 2)), 31, None, CallbackStatus())

    integrity = analyzer.get_integrity_snapshot()
    assert not integrity["measurement_valid"]
    assert integrity["xrun"]
    assert integrity["data_gap"]
    assert "Audio stream XRUN" in integrity["reasons"]
    assert "Input frame count mismatch" in integrity["reasons"]
    assert "Output frame count mismatch" in integrity["reasons"]


def test_nonfinite_or_overloaded_generated_output_is_made_safe(audio_engine):
    analyzer = DistortionAnalyzer(audio_engine)
    analyzer.signal_type = "smpte"
    analyzer._generate_dual_tone = MagicMock(
        return_value=np.array([np.nan, np.inf, -np.inf, 2.0], dtype=float)
    )
    analyzer.start_analysis()
    callback = _registered_callback(audio_engine)
    outdata = np.zeros((4, 2), dtype=float)

    callback(np.zeros((4, 2)), outdata, 4, None, None)

    assert np.all(np.isfinite(outdata))
    assert np.max(np.abs(outdata)) <= 1.0
    integrity = analyzer.get_integrity_snapshot()
    assert integrity["nonfinite_data"]
    assert integrity["output_overload"]
    assert not integrity["measurement_valid"]


@pytest.mark.parametrize("value", [1.1, 10.0, np.inf, np.nan])
def test_generator_amplitude_never_exceeds_full_scale(audio_engine, value):
    analyzer = DistortionAnalyzer(audio_engine)
    analyzer.gen_amplitude = value

    assert np.isfinite(analyzer.gen_amplitude)
    assert 0.0 <= analyzer.gen_amplitude <= 1.0


def test_din_generator_uses_four_to_one_tone_ratio(audio_engine):
    analyzer = DistortionAnalyzer(audio_engine)
    analyzer.imd_standard = "din"
    analyzer.imd_f1 = 250.0
    analyzer.imd_f2 = 8000.0
    analyzer.imd_ratio = 4.0
    analyzer.gen_amplitude = 1.0

    signal = analyzer._generate_dual_tone(48000, 48000)
    timeline = np.arange(len(signal)) / 48000
    low_amplitude = 2 * np.mean(signal * np.sin(2 * np.pi * 250.0 * timeline))
    high_amplitude = 2 * np.mean(signal * np.sin(2 * np.pi * 8000.0 * timeline))

    assert low_amplitude / high_amplitude == pytest.approx(4.0)
