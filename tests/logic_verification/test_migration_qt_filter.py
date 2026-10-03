"""Independent finite-sum and evidence corruption checks; no GUI/device needed."""

from copy import deepcopy
import json

import numpy as np
import pytest

from scripts import migration_qt_filter as runner


def request():
    return dict(
        precision="F32",
        n=4,
        window="Boxcar",
        filter=dict(input_conversion="F32ToF64Exact"),
        format=dict(
            stream_id="input",
            generation=1,
            timebase_id="clock",
            clock_domain="unknown.device",
            rate=[48000, 1],
            input_ids=["right", "left"],
            input_ports=[1, 0],
            output_ids=[],
            output_ports=[],
        ),
    )


def test_finite_sum_start_and_delayed_support_use_absolute_positions():
    raw = np.array([[i, -i] for i in range(16)], dtype="<f4")
    np.testing.assert_array_equal(runner.finite_sum(raw, [0, 4]), [[0, 0], [1, -1], [3, -3], [5, -5]])
    np.testing.assert_array_equal(
        runner.finite_sum(raw[6:16], [4, 8], origin=6), [[7, -7], [9, -9], [11, -11], [13, -13]]
    )
    with pytest.raises(runner.fft.ReferenceError, match="missing parent"):
        runner.finite_sum(raw[8:16], [4, 8], origin=8)


@pytest.mark.parametrize("corruption", ["bytes", "port", "generation", "nonfinite", "interval"])
def test_parent_evidence_rejects_corrupt_bytes_and_binding(tmp_path, corruption):
    config = request()
    stem = tmp_path / "capture"
    raw = np.array([[i, -i] for i in range(6, 16)], dtype="<f4")
    metadata = dict(source=runner.expected_metadata(config, 1)["parent"], interval=[6, 16], byte_count=raw.nbytes)
    stem.with_suffix(".parent.json").write_text(json.dumps(metadata))
    stem.with_suffix(".parent.f32").write_bytes(raw.tobytes())
    np.testing.assert_array_equal(
        runner.parent_samples(stem, config, [4, 8], 1), [[7, -7], [9, -9], [11, -11], [13, -13]]
    )
    if corruption == "bytes":
        stem.with_suffix(".parent.f32").write_bytes(raw.tobytes()[:-4])
    elif corruption == "port":
        metadata["source"]["channel_ids"].reverse()
    elif corruption == "generation":
        metadata["source"]["generation"] = 2
    elif corruption == "nonfinite":
        raw[0, 0] = np.nan
        stem.with_suffix(".parent.f32").write_bytes(raw.tobytes())
    else:
        metadata["interval"] = [8, 18]
    stem.with_suffix(".parent.json").write_text(json.dumps(metadata))
    with pytest.raises(runner.fft.ReferenceError):
        runner.parent_samples(stem, config, [4, 8], 1)


def test_metadata_keeps_parent_precision_and_exact_conversion_separate():
    config = request()
    before = deepcopy(config)
    metadata = runner.expected_metadata(config, 3)
    assert metadata["parent"]["precision"] == "F32"
    assert metadata["output"]["precision"] == "F64"
    assert metadata["parent"]["generation"] == metadata["output"]["generation"] == 3
    assert metadata["signal_delay_output_samples"] == dict(numerator=1, denominator=2)
    assert metadata["processing_latency_seconds"] is None
    assert config == before


@pytest.mark.parametrize(("n", "bin_index"), [(8, 0), (8, 4), (8, 2), (9, 0), (9, 4)])
def test_tone_rms_oracle_agrees_with_time_domain_constant_nyquist_and_interior(n, bin_index):
    signal = 0.125 * np.cos(2 * np.pi * bin_index * np.arange(n) / n)
    peaks = np.abs(np.fft.rfft(signal)) * 2 / n
    peaks[0] *= 0.5
    if n % 2 == 0:
        peaks[-1] *= 0.5
    rms = runner.trigger.tone_rms_from_peak(peaks, n)
    assert rms[bin_index] == pytest.approx(np.sqrt(np.mean(signal**2)), abs=1e-15)
