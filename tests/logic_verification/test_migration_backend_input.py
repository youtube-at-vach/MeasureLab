"""Common backend binding/worker transport: oracle and malformed evidence rejection."""

import json
import struct
import subprocess

import numpy as np
import pytest

from scripts import migration_backend_input as backend
from scripts import migration_fft_candidate as candidate
from scripts import migration_fft_reference as fft


@pytest.fixture(scope="module")
def binary():
    return backend.build()[0]


@pytest.fixture
def saved(binary, tmp_path):
    manifest, _ = candidate.load_manifest(backend.core.DEFAULT_FIXTURES, portable=True, is_core=True)
    case = manifest["tones"][0]
    request = backend.request_for(case, "PortAudio", reverse=True)
    raw = backend.core.checked_file(backend.core.DEFAULT_FIXTURES / case["spec"]["id"], case["arrays"]["input"])
    fft.write_json(tmp_path / "request.json", request)
    (tmp_path / "wire.bin").write_bytes(backend.wire_bytes(request, raw))
    output = tmp_path / "output"
    candidate.run_command([str(binary), str(tmp_path / "request.json"), str(tmp_path / "wire.bin"), str(output)])
    return request, raw, output


@pytest.mark.native
def test_native_stdin_transport_keeps_original_precision_and_complete_snapshot(binary, saved, tmp_path):
    request, raw, output = saved
    checked = backend.validate(output, request, raw)
    assert checked["windows"] == 1
    wire = backend.wire_bytes(request, raw, pattern=(256,))
    process = subprocess.run(  # noqa: S603 - built local test executable
        [str(binary), str(tmp_path / "request.json"), "-", str(tmp_path / "stdin")],
        input=wire,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert process.returncode == 0, process.stderr
    assert backend.validate(tmp_path / "stdin", request, raw)["windows"] == 1


@pytest.mark.native
@pytest.mark.parametrize(
    "fault",
    [
        "backend",
        "precision",
        "port",
        "clock",
        "generation",
        "frames",
        "stamps",
        "share",
        "numeric",
        "evaluation",
        "retained",
        "queue",
        "stats_type",
        "offset",
        "interval",
        "result_id",
        "unknown",
        "extra",
    ],
)
def test_rejects_false_manifest_evidence(saved, fault):
    request, raw, output = saved
    path = output / "manifest.json"
    document = json.loads(path.read_bytes())
    if fault == "backend":
        document["binding"]["backend"] = "Cpal"
    elif fault == "precision":
        document["source"]["precision"] = "F32"
    elif fault == "port":
        document["binding"]["format"]["input_ports"].reverse()
    elif fault == "clock":
        document["source"]["timebase"]["uncertainty_seconds"] = {"numerator": 0, "denominator": 1}
    elif fault == "generation":
        document["source"]["generation"] += 1
    elif fault in ("frames", "stamps"):
        document[fault] -= 1
    elif fault == "share":
        document["windows"][0]["shared_allocation"] = False
    elif fault == "numeric":
        document["windows"][0]["numeric"] = False
    elif fault == "evaluation":
        document["before_release"]["fft_evaluations"] += 1
    elif fault == "retained":
        document["after_stop"]["nodes"] = 1
    elif fault == "queue":
        document["queue"]["channels"] += 1
    elif fault == "stats_type":
        document["after_stop"]["nodes"] = False
    elif fault == "offset":
        document["windows"][0]["complex_offset"] += 1
    elif fault == "interval":
        document["windows"][0]["history"]["interval"][0] += 1
    elif fault == "result_id":
        document["windows"][0]["result_id"]["serial"] = True
    elif fault == "unknown":
        document["held_after_stop"]["capture"]["clock_mapping"] = {}
    else:
        document["extra"] = None
    fft.write_json(path, document)
    with pytest.raises(fft.ReferenceError):
        backend.validate(output, request, raw)


@pytest.mark.native
@pytest.mark.parametrize("name", ["input.bin", "complex.bin", "result.json", "result.csv"])
def test_corrupted_artifacts_are_rejected(saved, name):
    request, raw, output = saved
    path = output / name
    data = bytearray(path.read_bytes())
    if name == "complex.bin":
        data[:8] = struct.pack("<d", float("nan"))
    else:
        data[0] ^= 1
    path.write_bytes(data)
    with pytest.raises((fft.ReferenceError, ValueError)):
        backend.validate(output, request, raw)


@pytest.mark.native
@pytest.mark.parametrize(
    "fault",
    [
        "schema",
        "dtype",
        "binding",
        "backend_clock",
        "capacity",
        "empty",
        "short_header",
        "short_payload",
        "no_terminal",
        "trailing",
        "stale",
        "future_generation",
        "position",
        "time",
        "terminal_flags",
        "existing",
    ],
)
def test_bad_requests_and_transport_never_modify_existing_output(binary, saved, tmp_path, fault):
    request, raw, existing = saved
    wire = bytearray(backend.wire_bytes(request, raw))
    if fault == "schema":
        request["schema_version"] = 2
    elif fault == "dtype":
        request["binding"]["sample_format"] = "F32"
    elif fault == "binding":
        request["binding"]["format"]["input_ports"][0] = 999
    elif fault == "backend_clock":
        request["binding"]["backend"] = "Cpal"
    elif fault == "capacity":
        wire[:4] = struct.pack("<I", 8193)
    elif fault == "empty":
        wire = b""
    elif fault == "short_header":
        wire = wire[:31]
    elif fault == "short_payload":
        wire = wire[: backend.HEADER.size + 3]
    elif fault == "no_terminal":
        wire = wire[: -backend.HEADER.size]
    elif fault == "trailing":
        wire += b"unexpected"
    elif fault in ("stale", "future_generation"):
        generation = request["binding"]["format"]["generation"] + (-1 if fault == "stale" else 1)
        wire[16:24] = struct.pack("<Q", generation)
    elif fault == "position":
        wire[8:16] = struct.pack("<Q", 1)
    elif fault == "time":
        wire[24:32] = struct.pack("<d", float("inf"))
    elif fault == "terminal_flags":
        wire[-28:-24] = struct.pack("<I", 1)
    fft.write_json(tmp_path / "bad.json", request)
    output = existing if fault == "existing" else tmp_path / "rejected"
    before = {p.name: p.read_bytes() for p in existing.iterdir()}
    process = subprocess.run(  # noqa: S603 - built local test executable
        [str(binary), str(tmp_path / "bad.json"), "-", str(output)],
        input=wire,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert process.returncode != 0
    assert {p.name: p.read_bytes() for p in existing.iterdir()} == before
    if output != existing:
        assert not output.exists()


@pytest.mark.native
@pytest.mark.parametrize("fault", ["flags", "nonfinite", "overwrite"])
def test_invalid_backend_intervals_never_publish_normal_fft(binary, saved, tmp_path, fault):
    request, raw, _ = saved
    request["n"] = 8
    request["max_frames"] = 16
    if fault == "overwrite":
        request["queue_frames"] = 4
    dtype = "<f4" if request["binding"]["sample_format"] == "F32" else "<f8"
    values = np.frombuffer(raw, dtype=dtype).reshape(-1, request["binding"]["device_channels"])[:16].copy()
    if fault == "nonfinite":
        values[:, :] = np.nan
    data = backend.packet(request, 0, values.tobytes(), flags=1 if fault == "flags" else 0) + backend.packet(
        request, 16
    )
    fft.write_json(tmp_path / "invalid.json", request)
    output = tmp_path / "invalid"
    process = subprocess.run(  # noqa: S603 - built local test executable
        [str(binary), str(tmp_path / "invalid.json"), "-", str(output)],
        input=data,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert process.returncode == 0, process.stderr
    header = json.loads((output / "manifest.json").read_bytes())
    assert header["complex_bytes"] == 0
    assert all(not w["numeric"] for w in header["windows"])
    assert header["before_release"]["fft_evaluations"] == 0
    assert header["after_stop"]["nodes"] == 0
    if fault == "overwrite":
        assert header["gaps"] == [[0, 12]]
        assert header["held_after_stop"] is None
    else:
        assert header["held_after_stop"]["validity"]


@pytest.mark.native
@pytest.mark.parametrize("fault", ["foreign_graph", "reverse_identity"])
def test_continuous_windows_require_one_graph_and_increasing_identity(binary, saved, tmp_path, fault):
    request, raw, _ = saved
    request["max_frames"] = 2 * request["n"]
    fft.write_json(tmp_path / "two-windows.json", request)
    output = tmp_path / "two-windows"
    process = subprocess.run(  # noqa: S603 - built local test executable
        [str(binary), str(tmp_path / "two-windows.json"), "-", str(output)],
        input=backend.wire_bytes(request, raw * 2),
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert process.returncode == 0, process.stderr
    assert backend.validate(output, request, raw * 2)["windows"] == 2
    path = output / "manifest.json"
    document = json.loads(path.read_bytes())
    first = document["windows"][0]["result_id"]
    if fault == "foreign_graph":
        first["graph"] += 100
    else:
        first["serial"] = document["windows"][1]["result_id"]["serial"] + 1
    fft.write_json(path, document)
    with pytest.raises(fft.ReferenceError):
        backend.validate(output, request, raw * 2)


def test_transport_packets_cannot_pad_wrong_shapes_or_exceed_bounds():
    request = backend.live_request(backend.LIVE_CASES[0])
    with pytest.raises(ValueError):
        backend.packet(request, 0, b"x")
    with pytest.raises(ValueError):
        backend.packet(request, 0, bytes(8193 * 2 * 4))
    with pytest.raises(ValueError):
        backend.packet(request, request["max_frames"], bytes(2 * 4))
