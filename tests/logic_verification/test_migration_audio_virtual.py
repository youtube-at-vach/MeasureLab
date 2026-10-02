"""Reject incorrect port mapping, mute, gaps and false virtual-device claims."""

import json

import numpy as np
import pytest

from scripts import migration_audio_virtual as virtual
from scripts import migration_fft_reference as fft


def write_capture(directory, expected, delay=256):
    frames = len(expected) + 512
    output = np.zeros((frames, expected.shape[1]), dtype="<f4")
    output[: len(expected)] = expected
    captured = np.zeros_like(output)
    captured[delay : delay + len(expected)] = expected
    captured.tofile(directory / "input.bin")
    output.tofile(directory / "output.bin")
    metadata = {
        "frames": frames,
        "channels": expected.shape[1],
        "dtype": "<f4",
        "samples": list(range(frames)),
        "seconds": [None] * frames,
        "gaps": [],
    }
    fft.write_json(
        directory / "manifest.json",
        {"state": "stopped", "input": metadata, "output": metadata, "errors": 0, "xruns": 0, "callback_rejections": 0},
    )
    return captured, output


@pytest.fixture(scope="module")
def stereo():
    case = virtual.cases()[0]
    source = virtual.stimulus(case["sources"])
    return source, virtual.routed(source, case["gains"])


def test_distinct_stereo_ports_unknown_timestamps_and_known_frame_offset(tmp_path, stereo):
    source, expected = stereo
    write_capture(tmp_path, expected)
    result = virtual.analyze(tmp_path, expected, source)
    assert result["status"] == "pass"
    assert result["marker_offset_frames_by_active_port"] == [256, 256]
    assert result["physical_delay_ms"] is None
    assert result["delay_accuracy_verdict"] == "virtual_loopback_unverified_clock_mapping"
    assert result["input_max_abs_error_by_port"] == [0, 0]


@pytest.mark.parametrize("fault", ["swapped_ports", "input_mute", "output_mute", "gain", "xrun", "stopped"])
def test_measurement_checker_detects_corruption(tmp_path, stereo, fault):
    source, expected = stereo
    captured, output = write_capture(tmp_path, expected)
    if fault == "swapped_ports":
        captured = captured[:, ::-1].copy()
    elif fault == "input_mute":
        captured[116000 + 256 : 124000 + 256] = source[116000:124000]
    elif fault == "output_mute":
        output[slice(*virtual.MUTE)] = source[slice(*virtual.MUTE)]
    elif fault == "gain":
        captured[:, 1] *= 0.5
    else:
        path = tmp_path / "manifest.json"
        raw = json.loads(path.read_bytes())
        if fault == "xrun":
            raw["xruns"] = 1
        else:
            raw["state"] = "running"
        fft.write_json(path, raw)
    captured.tofile(tmp_path / "input.bin")
    output.tofile(tmp_path / "output.bin")
    assert virtual.analyze(tmp_path, expected, source)["status"] == "fail"


def test_four_channel_route_checks_duplicate_mix_and_silent_physical_ports(tmp_path):
    case = virtual.cases()[2]
    source = virtual.stimulus(4)
    expected = virtual.routed(source, case["gains"])
    assert np.array_equal(expected[48000:96000, :4], source[48000:96000, ::-1])
    assert np.array_equal(expected[48000:96000, 4], source[48000:96000, 0])
    assert np.all(expected[:, 6:] == 0)
    captured, _ = write_capture(tmp_path, expected)
    assert virtual.analyze(tmp_path, expected, source)["status"] == "pass"
    captured[50000, 15] = 0.001
    captured.tofile(tmp_path / "input.bin")
    result = virtual.analyze(tmp_path, expected, source)
    assert not result["checks"]["all_input_ports"]
    assert result["input_max_abs_error_by_port"][15] > virtual.TOLERANCES["sample_abs"]


@pytest.mark.parametrize("fault", ["gap", "sample", "shape", "nan", "infinite_clock"])
def test_corrupt_capture_is_not_accepted(tmp_path, stereo, fault):
    _, expected = stereo
    captured, _ = write_capture(tmp_path, expected)
    path = tmp_path / "manifest.json"
    raw = json.loads(path.read_bytes())
    if fault == "gap":
        raw["input"]["gaps"] = [[40, 41]]
    elif fault == "sample":
        raw["input"]["samples"][40] = 41
    elif fault == "shape":
        raw["input"]["channels"] = 16
    elif fault == "nan":
        captured[40, 0] = np.nan
        captured.tofile(tmp_path / "input.bin")
    else:
        raw["input"]["seconds"][40] = float("inf")
    # Deliberately corrupt JSON, bypassing the production finite-value writer.
    path.write_text(json.dumps(raw))
    with pytest.raises(ValueError):
        virtual.load_capture(tmp_path, "input", 2)


def test_backend_amplitude_and_active_port_mismatch():
    baseline = {"active_ports": [0, 1], "rms_fs_by_port": [0.01, 0.02]}
    assert virtual.compare_pair(baseline, baseline)["status"] == "pass"
    assert virtual.compare_pair(baseline, {**baseline, "rms_fs_by_port": [0.01, 0.04]})["status"] == "fail"
    with pytest.raises(ValueError):
        virtual.compare_pair(baseline, {**baseline, "active_ports": [0]})


def test_device_io_requires_opt_in_and_never_falls_back(monkeypatch, tmp_path):
    monkeypatch.setattr("sys.argv", ["migration_audio_virtual.py", "--output", str(tmp_path / "capture")])
    with pytest.raises(SystemExit, match="2"):
        virtual.main()
    assert not (tmp_path / "capture").exists()
    with pytest.raises(ValueError, match="Only exact"):
        virtual.exact_device("ZOOM UAC-232")
    monkeypatch.setattr("sounddevice.query_devices", lambda: [])
    with pytest.raises(ValueError, match="uniquely"):
        virtual.exact_device("BlackHole 2ch")


def test_existing_capture_cannot_be_overwritten(monkeypatch, tmp_path):
    output = tmp_path / "capture"
    output.mkdir()
    keep = output / "keep"
    keep.write_text("keep")
    monkeypatch.setattr("sys.argv", ["migration_audio_virtual.py", "--virtual-device", "--output", str(output)])
    with pytest.raises(SystemExit, match="2"):
        virtual.main()
    assert keep.read_text() == "keep"
