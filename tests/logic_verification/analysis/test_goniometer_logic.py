import math

import numpy as np
import pytest

from src.gui.widgets.goniometer import (
    CorrelationValidity,
    Goniometer,
    GoniometerQualityFlag,
    GoniometerRunState,
)


class MockAudioEngine:
    def __init__(self, sample_rate: int = 48000, *, fail_start: bool = False):
        self.sample_rate = sample_rate
        self.fail_start = fail_start
        self.callback = None
        self.unregistered: list[int] = []

    def register_callback(self, callback):
        if self.fail_start:
            raise RuntimeError("no input device")
        self.callback = callback
        return 7

    def unregister_callback(self, callback_id: int):
        self.unregistered.append(callback_id)


class InputOverflow:
    input_underflow = False
    input_overflow = True

    def __bool__(self):
        return True


def _invoke(module: Goniometer, data: np.ndarray, status=None) -> None:
    output = np.ones((len(data), 2), dtype=np.float64)
    module._callback(data, output, len(data), None, status)
    assert np.all(output == 0.0)


def _tone(frames: int = 4800, frequency: float = 1000.0, sample_rate: int = 48000) -> np.ndarray:
    sample_time = np.arange(frames, dtype=np.float64) / sample_rate
    return 0.5 * np.sin(2.0 * np.pi * frequency * sample_time)


@pytest.mark.parametrize(
    ("right_factory", "expected"),
    [
        (lambda left: left, 1.0),
        (lambda left: -left, -1.0),
        (lambda left: 0.5 * np.cos(np.linspace(0.0, 200.0 * np.pi, len(left), endpoint=False)), 0.0),
    ],
)
def test_correlation_for_known_phase_relationships(right_factory, expected):
    module = Goniometer(MockAudioEngine())
    left = _tone()
    right = right_factory(left)

    _invoke(module, np.column_stack((left, right)))

    assert module.correlation_validity is CorrelationValidity.VALID
    assert module.correlation == pytest.approx(expected, abs=1e-12)


def test_uncorrelated_noise_is_close_to_zero():
    module = Goniometer(MockAudioEngine())
    rng = np.random.default_rng(42)
    data = rng.normal(0.0, 0.1, size=(48000, 2))

    _invoke(module, data)

    assert module.correlation_validity is CorrelationValidity.VALID
    assert module.correlation is not None
    assert abs(module.correlation) < 0.02


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (np.zeros((1024, 2)), CorrelationValidity.NO_SIGNAL),
        (np.column_stack((_tone(1024), np.zeros(1024))), CorrelationValidity.ONE_CHANNEL_LOW),
        (_tone(1024)[:, None], CorrelationValidity.MONO_INPUT),
    ],
)
def test_undefined_correlation_is_not_reported_as_zero(data, expected):
    module = Goniometer(MockAudioEngine())

    _invoke(module, data)

    assert module.correlation is None
    assert module.correlation_validity is expected


def test_nonfinite_input_is_rejected_and_latched():
    module = Goniometer(MockAudioEngine())
    data = np.column_stack((_tone(1024), _tone(1024)))
    data[10, 0] = np.nan

    _invoke(module, data)
    snapshot = module.get_snapshot()

    assert snapshot is not None
    assert snapshot.total_samples == 0
    assert snapshot.correlation is None
    assert snapshot.correlation_validity is CorrelationValidity.NONFINITE
    assert snapshot.quality_flags & GoniometerQualityFlag.NONFINITE


def test_clipping_and_io_error_invalidate_and_latch_quality():
    module = Goniometer(MockAudioEngine())
    clipped = np.tile(np.array([-1.0, 1.0]), 512)

    _invoke(module, np.column_stack((clipped, clipped)), InputOverflow())
    snapshot = module.get_snapshot()

    assert snapshot is not None
    assert snapshot.correlation is None
    assert snapshot.correlation_validity is CorrelationValidity.IO_ERROR
    assert snapshot.quality_flags & GoniometerQualityFlag.CLIPPED_LEFT
    assert snapshot.quality_flags & GoniometerQualityFlag.CLIPPED_RIGHT
    assert snapshot.quality_flags & GoniometerQualityFlag.IO_ERROR


def test_ring_buffer_wraps_chronologically_and_reports_display_drop():
    module = Goniometer(MockAudioEngine())
    sample_numbers = np.arange(6000, dtype=np.float64) / 10000.0
    data = np.column_stack((sample_numbers, -sample_numbers))

    _invoke(module, data[:3000])
    _invoke(module, data[3000:])
    snapshot = module.get_snapshot(since_total_samples=0)

    assert snapshot is not None
    assert snapshot.audio.shape == (module.buffer_size, 2)
    assert snapshot.display_dropped_samples == 6000 - module.buffer_size
    np.testing.assert_allclose(snapshot.audio[:, 0], sample_numbers[-module.buffer_size :])
    np.testing.assert_allclose(snapshot.audio[:, 1], -sample_numbers[-module.buffer_size :])


def _correlation_after_transition(block_size: int) -> float:
    sample_rate = 48000
    module = Goniometer(MockAudioEngine(sample_rate))
    tone = _tone(block_size, sample_rate=sample_rate)
    in_phase = np.column_stack((tone, tone))
    anti_phase = np.column_stack((tone, -tone))

    for _ in range(math.ceil(0.9 * sample_rate / block_size)):
        _invoke(module, in_phase)
    for _ in range(math.ceil(0.3 * sample_rate / block_size)):
        _invoke(module, anti_phase)

    assert module.correlation is not None
    return module.correlation


def test_correlation_response_is_independent_of_callback_block_size():
    small_blocks = _correlation_after_transition(240)
    large_blocks = _correlation_after_transition(480)

    assert small_blocks == pytest.approx(large_blocks, abs=0.02)


def test_start_failure_rolls_back_running_state():
    module = Goniometer(MockAudioEngine(fail_start=True))

    assert not module.start_analysis()
    assert not module.is_running
    assert module.callback_id is None
    assert module.run_state is GoniometerRunState.FAILED
    assert module.error_message == "no input device"


def test_start_stop_and_clear_lifecycle():
    engine = MockAudioEngine()
    module = Goniometer(engine)

    assert module.start_analysis()
    assert module.run_state is GoniometerRunState.RUNNING
    assert module.callback_id == 7

    _invoke(module, np.column_stack((_tone(1024), _tone(1024))))
    module.stop_analysis()
    module.clear_measurement()

    assert engine.unregistered == [7]
    assert module.run_state is GoniometerRunState.IDLE
    snapshot = module.get_snapshot()
    assert snapshot is not None
    assert snapshot.total_samples == 0
    assert snapshot.correlation_validity is CorrelationValidity.WAITING
