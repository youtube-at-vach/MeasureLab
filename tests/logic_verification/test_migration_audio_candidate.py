"""Exercise real Rust routing/queue boundary and detect invalid measurement claims."""

import copy
import subprocess

import numpy as np
import pytest

from scripts import migration_audio_candidate as audio
from scripts import migration_audio_hardware as hardware
from scripts import migration_fft_reference as fft


@pytest.fixture(scope="module")
def binary():
    return audio.build()[0]


def test_reviewed_route_rejections_taps_generations_and_multichannel_bytes():
    report = audio.verify()
    assert len(report["cases"]) == 10
    assert len(report["queues"]) == 4
    assert {case["id"] for case in report["queues"]} == {
        f"ac01-{n}ch-{dtype}" for n in (4, 8) for dtype in ("f4", "f8")
    }


@pytest.mark.parametrize("fault", ["count", "id", "gain", "null", "gap", "tap"])
def test_checker_rejects_corrupted_results(fault):
    cases = audio.reviewed_cases()
    observed = [{"id": case["id"], "observed": copy.deepcopy(case["expected"])} for case in cases]
    if fault == "count":
        observed.pop()
    elif fault == "id":
        observed[0]["id"] = "other"
    elif fault == "gain":
        observed[0]["observed"]["values"][0][0] += 1
    elif fault == "null":
        observed[0]["observed"]["values"][0][0] = None
    elif fault == "gap":
        observed[-1]["observed"][1]["missing"][0][0] += 1
    else:
        observed[-2]["observed"]["output.device_buffer"][0][0] = 1
    with pytest.raises(fft.ReferenceError):
        audio.validate_results(cases, observed)


@pytest.mark.parametrize("fault", ["duplicate_id", "dtype", "capacity", "rate", "shape", "extra", "existing_output"])
def test_queue_rejects_without_touching_saved_input(binary, tmp_path, fault):
    request = {
        "schema_version": 1,
        "channel_ids": ["a", "b"],
        "dtype": "<f8",
        "frames": 3,
        "chunk_frames": 2,
        "capacity": 4,
        "generation": 3,
        "rate": 48000,
    }
    source = tmp_path / "input.bin"
    source.write_bytes(np.arange(6, dtype="<f8").tobytes())
    output = tmp_path / "output"
    if fault == "duplicate_id":
        request["channel_ids"] = ["a", "a"]
    elif fault == "dtype":
        request["dtype"] = "<i4"
    elif fault == "capacity":
        request["capacity"] = 1
    elif fault == "rate":
        request["rate"] = 0
    elif fault == "shape":
        request["frames"] = 4
    elif fault == "extra":
        request["other"] = 1
    else:
        output.mkdir()
        (output / "keep").write_text("keep")
    path = tmp_path / "request.json"
    fft.write_json(path, request)
    before = source.read_bytes()
    result = subprocess.run(  # noqa: S603 - locally built evaluation binary, explicit argv, no shell
        [str(binary), "--queue", str(path), str(source), str(output)], capture_output=True, check=False
    )
    assert result.returncode != 0
    assert source.read_bytes() == before
    if fault == "existing_output":
        assert (output / "keep").read_text() == "keep"
    else:
        assert not output.exists()


def test_physical_measurement_checker_with_known_delay_gain_mute_and_phase(tmp_path):
    signal = hardware.stimulus()
    delay = 321
    output = np.column_stack([signal, np.zeros_like(signal)])
    output[slice(*hardware.MUTE)] = 0
    captured = np.zeros_like(output)
    captured[delay:, 0] = output[:-delay, 0] * 0.1
    captured[delay:, 1] = output[:-delay, 0]
    captured.tofile(tmp_path / "input.bin")
    output.tofile(tmp_path / "output.bin")
    metadata = {
        "frames": len(signal),
        "channels": 2,
        "dtype": "<f4",
        "samples": list(range(len(signal))),
        "seconds": (np.arange(len(signal)) / hardware.RATE).tolist(),
        "gaps": [],
    }
    fft.write_json(tmp_path / "manifest.json", {"input": metadata, "output": metadata})
    result = hardware.analyze(tmp_path, signal)
    assert result["status"] == "pass"
    assert result["marker_input_samples"] == [24000 + delay] * 2
    assert result["attenuation_db"] == pytest.approx(-20, abs=1e-6)
    assert result["raw_timestamp_marker_difference_ms"] == pytest.approx([1000 * delay / hardware.RATE] * 2)
    assert result["delay_accuracy_verdict"] == "unknown_timestamp_uncertainty"
    # Remove physical mute, while leaving submitted tap muted: detect the discrepancy.
    captured[delay:, 0] = signal[:-delay] * 0.1
    captured[delay:, 1] = signal[:-delay]
    captured.tofile(tmp_path / "input.bin")
    result = hardware.analyze(tmp_path, signal)
    assert result["status"] == "fail"
    assert result["checks"]["tap_mute"]
    assert not result["checks"]["physical_mute"]


def test_backend_difference_and_phase_wrap():
    baseline = {"peak_fs": [0.1, 1.0], "relative_phase_degrees": 179.9}
    same = {"peak_fs": [0.1, 1.0], "relative_phase_degrees": -179.9}
    assert hardware.compare_pair(baseline, same)["status"] == "pass"
    different = {**same, "peak_fs": [0.2, 1.0]}
    assert hardware.compare_pair(baseline, different)["status"] == "fail"


def test_hardware_cli_does_not_open_device_without_explicit_flag(monkeypatch, tmp_path):
    monkeypatch.setattr("sys.argv", ["migration_audio_hardware.py", "--output", str(tmp_path / "output")])
    with pytest.raises(SystemExit, match="2"):
        hardware.main()
    assert not (tmp_path / "output").exists()


def test_capture_rejects_truncated_bytes_and_nonfinite(tmp_path):
    metadata = {"frames": 2, "channels": 2, "dtype": "<f4", "samples": [0, 1], "seconds": [None, None], "gaps": []}
    fft.write_json(tmp_path / "manifest.json", {"input": metadata})
    path = tmp_path / "input.bin"
    path.write_bytes(np.zeros(3, dtype="<f4").tobytes())
    with pytest.raises(ValueError):
        hardware.load_capture(tmp_path, "input")
    path.write_bytes(np.array([0, np.nan, 0, 0], dtype="<f4").tobytes())
    with pytest.raises(ValueError):
        hardware.load_capture(tmp_path, "input")
