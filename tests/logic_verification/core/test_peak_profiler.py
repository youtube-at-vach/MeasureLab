import numpy as np
import pytest

from src.core.peak_profiler import PeakProfiler, PeakProfileSession
from src.core.true_peak import TruePeakMeter


def profile_signal(samples, block_size, threshold=0.0):
    core = PeakProfiler(48000, threshold)
    meter = TruePeakMeter(2)
    for start in range(0, len(samples), block_size):
        block = samples[start : start + block_size]
        core.process(block, meter.process_envelope(block), start, samples.shape[1])
    core.finish(meter.process_envelope(np.zeros((10, 2))))
    return core.snapshot()


@pytest.mark.parametrize("block_size", [1, 7, 64, 1024, 4000])
def test_histogram_events_and_duration_are_callback_invariant(block_size):
    samples = np.zeros((2081, 2))
    samples[40:150, 0] = 1.1
    samples[170:180, 0] = 1.2
    samples[30:2000, 1] = 0.9
    actual = profile_signal(samples, block_size)
    reference = profile_signal(samples, len(samples))
    assert actual.frames == len(samples)
    np.testing.assert_array_equal(actual.histogram.sum(axis=1), [len(samples)] * 2)
    for name in ("histogram", "exceedances", "events_started", "longest_frames"):
        np.testing.assert_array_equal(getattr(actual, name), getattr(reference, name))
    assert actual.exceedances[0, 0] == 120
    assert actual.events_started[0, 0] == 2
    assert actual.longest_frames[0, 0] == 110
    assert actual.exceedances[1, 0] == 0
    assert [(e.channel, e.kind, e.start, e.end, e.censored) for e in actual.events] == [
        (e.channel, e.kind, e.start, e.end, e.censored) for e in reference.events
    ]
    np.testing.assert_allclose([e.peak for e in actual.events], [e.peak for e in reference.events], atol=1e-12)


def test_intersample_only_events_and_source_clock_alignment():
    samples = np.column_stack((np.tile([0.99, 0.99, -0.99, -0.99], 300), np.zeros(1200)))
    result = profile_signal(samples, 64)
    assert result.exceedances[0, 0] == 0
    assert result.exceedances[0, 1] == 600
    assert result.events_started[0, 1] > 0
    assert not result.histogram.flags.writeable
    assert all(0 <= event.start < event.end <= 1200 for event in result.events)
    assert all(event.channel == 0 and event.kind == 1 for event in result.events)


@pytest.mark.parametrize("length", [1, 9, 10, 11])
def test_short_stream_drain_counts_no_synthetic_padding(length):
    result = profile_signal(np.ones((length, 2)), 1)
    assert result.frames == length
    assert result.exceedances[0, 0] == length


def test_silence_and_histogram_end_bins_and_threshold_equality():
    result = profile_signal(np.zeros((20, 2)), 4)
    assert result.histogram[0, 0] == 20
    assert not np.any(result.exceedances)
    result = profile_signal(np.full((100, 2), 4.0), 7, threshold=6)
    assert result.histogram[0, -1] == 100
    result = profile_signal(np.ones((100, 2)), 11)
    assert result.exceedances[0, 0] == 100  # inclusive comparison


def test_retention_is_bounded_but_counts_are_not_truncated():
    samples = np.column_stack((np.tile([1.1, 0.0], 5000), np.zeros(10000)))
    result = profile_signal(samples, 1000)
    assert result.events_started[0, 0] == 5000
    assert result.longest_frames[0, 0] == 1
    assert len(result.events) <= PeakProfiler.MAX_EVENTS
    assert result.evicted_events > 0
    assert result.events[-1].end > 9000


def test_gap_splits_duration_and_latches_until_new_profile():
    core = PeakProfiler(48000, 0)
    meter = TruePeakMeter(2)
    block = np.ones((100, 2))
    core.process(block, meter.process_envelope(block), 0, 2)
    core.break_continuity()
    meter.reset()
    core.process(block, meter.process_envelope(block), 200, 2)
    core.finish(meter.process_envelope(np.zeros((10, 2))))
    result = core.snapshot()
    assert "data_gap" in result.flags
    assert result.longest_frames[0, 0] == 100
    assert result.events_started[0, 0] == 2
    assert any(event.censored and event.end == 90 for event in result.events)
    assert any(event.start == 200 for event in result.events)
    assert not PeakProfiler(48000).snapshot().flags


def test_mono_is_not_counted_twice():
    core = PeakProfiler(48000, 0)
    meter = TruePeakMeter(2)
    block = np.ones((100, 2))
    core.process(block, meter.process_envelope(block), 0, 1)
    core.finish(meter.process_envelope(np.zeros((10, 2))))
    result = core.snapshot()
    assert result.channels == 1
    assert result.histogram[0].sum() == 100
    assert result.histogram[1].sum() == 0


@pytest.mark.parametrize("threshold", [np.nan, np.inf, -61, 7])
def test_invalid_threshold_rejected(threshold):
    with pytest.raises(ValueError):
        PeakProfiler(48000, threshold)


def test_mailbox_overload_is_nonblocking_and_visible_without_more_input():
    session = PeakProfileSession(48000, 0)
    # Stop the worker first so overload is deterministic, without scheduling assumptions.
    session.close(np.zeros((10, 2)))
    block = np.zeros((16, 2))
    for _ in range(session.CAPACITY + 1):
        session.submit(block, block, 2)
    assert session.written == session.CAPACITY
    assert session.position == 16 * (session.CAPACITY + 1)
    assert "queue_overflow" in session.snapshot().flags


def test_worker_failure_is_latched(monkeypatch):
    session = PeakProfileSession(48000, 0)

    def fail(*args):
        raise RuntimeError("synthetic DSP error")

    monkeypatch.setattr(session.core, "process", fail)
    session.submit(np.zeros((20, 2)), np.zeros((20, 2)), 2)
    session.close(np.zeros((10, 2)))
    assert "processing_error" in session.snapshot().flags
    assert not session._thread.is_alive()


def test_worker_and_gui_lock_cannot_block_producer_or_alias_source():
    import threading

    session = PeakProfileSession(48000, 0)
    block = np.ones((20, 2))
    complete = threading.Event()

    def produce():
        session.submit(block, block, 2)
        block.fill(0)  # AudioEngine may reuse the input immediately after submit.
        complete.set()

    with session._lock:
        thread = threading.Thread(target=produce)
        thread.start()
        assert complete.wait(0.5), "producer waited for the worker/GUI lock"
    thread.join()
    session.close(np.ones((10, 2)))
    result = session.snapshot()
    assert result.exceedances[0, 0] == 20
    assert not result.flags


def test_retention_keeps_latest_events_across_all_lanes():
    core = PeakProfiler(48000, 0)
    samples = np.column_stack([np.tile([1.1, 0.0], 1000)] * 2)
    core._accumulate(samples, samples, 0, 2)
    result = core.snapshot()
    assert {(event.channel, event.kind) for event in result.events} == {(0, 0), (0, 1), (1, 0), (1, 1)}
    assert min(event.start for event in result.events) >= 1746
    assert result.events_started.sum() == 4000
    assert len(result.events) + result.evicted_events == 4000
