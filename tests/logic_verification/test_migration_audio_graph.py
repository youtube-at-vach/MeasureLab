"""Validate acquisition evidence against fixed inputs; reject corrupted result and lifecycle data."""

import copy
import json
import subprocess
import sys

import pytest

from scripts import migration_audio_graph as acquisition
from scripts import migration_fft_candidate as candidate
from scripts import migration_fft_reference as fft


@pytest.fixture(scope="module")
def binary():
    return acquisition.build()[0]


@pytest.fixture
def output(binary, tmp_path):
    manifest = json.loads((acquisition.core.DEFAULT_FIXTURES / "manifest.json").read_bytes())
    case = manifest["tones"][0]
    request = tmp_path / "request.json"
    fft.write_json(request, acquisition.request_for(case, reverse=True))
    source = acquisition.core.DEFAULT_FIXTURES / case["spec"]["id"] / case["arrays"]["input"]["file"]
    directory = tmp_path / "output"
    candidate.run_command([str(binary), str(request), str(source), str(directory)])
    return case, directory, request, source


def test_four_original_precision_channel_cases_with_two_explicit_bindings(binary, tmp_path):
    manifest, _ = candidate.load_manifest(acquisition.core.DEFAULT_FIXTURES, is_core=True, portable=False)
    for case in manifest["tones"]:
        for reverse in (False, True):
            result = acquisition.verify_case(binary, case, reverse=reverse)
            assert result["acquisition_graph"]["before_release"]["fft_evaluations"] == 1
            assert result["acquisition_graph"]["save_only"]["subscriptions"] == 1
    # Shared conftest imports Qt/audio. Verify import isolation in a fresh runner process.
    candidate.run_command(
        [
            sys.executable,
            str(acquisition.ROOT / "scripts/migration_audio_graph.py"),
            "--report",
            str(tmp_path / "headless.json"),
        ]
    )


@pytest.mark.parametrize(
    "fault",
    [
        "port",
        "id",
        "origin",
        "precision",
        "interval",
        "share",
        "result_id",
        "save_demand",
        "evaluation",
        "retained_node",
        "queue",
        "type",
        "stats_type",
        "extra",
    ],
)
def test_rejects_corrupt_acquisition_manifest(output, fault):
    case, directory, _, _ = output
    path = directory / "manifest.json"
    header = json.loads(path.read_bytes())
    if fault == "port":
        header["format"]["input_ports"][0] = 0
    elif fault == "id":
        header["source"]["channel_ids"][0] = "foreign"
    elif fault == "origin":
        header["source"]["timebase"]["origin_seconds"] = {"numerator": 0, "denominator": 1}
    elif fault == "precision":
        header["source"]["precision"] = "F32"
    elif fault == "interval":
        header["session_interval"][0] += 1
    elif fault == "share":
        header["shared_allocation"] = False
    elif fault == "result_id":
        header["save_result_id"]["serial"] += 1
    elif fault == "save_demand":
        header["save_only"]["subscriptions"] = 0
    elif fault == "evaluation":
        header["before_release"]["fft_evaluations"] = 2
    elif fault == "retained_node":
        header["after_stop"]["nodes"] = 1
    elif fault == "queue":
        header["queue"]["max_depth_frames"] = 1025
    elif fault == "type":
        header["before_release"]["fft_evaluations"] = True
    elif fault == "stats_type":
        header["before_release"] = []
    else:
        header["extra"] = None
    fft.write_json(path, header)
    with pytest.raises(fft.ReferenceError):
        acquisition.read_result(directory, case, reverse=True)


@pytest.mark.parametrize("name", ["poll_raw", "snapshot", "held_after_stop", "fft_over_n"])
def test_rejects_corrupted_or_nonfinite_arrays(output, name):
    case, directory, _, _ = output
    path = directory / f"{name}.bin"
    data = bytearray(path.read_bytes())
    if name == "fft_over_n":
        data[:8] = bytes.fromhex("000000000000f87f")
    else:
        data[0] ^= 1
    path.write_bytes(data)
    with pytest.raises(fft.ReferenceError):
        acquisition.read_result(directory, case, reverse=True)


@pytest.mark.parametrize("fault", ["schema", "binding", "precision", "shape", "existing_output"])
def test_native_rejects_bad_inputs_without_modifying_existing_files(binary, output, tmp_path, fault):
    _, directory, request, source = output
    header = json.loads(request.read_bytes())
    original = (directory / "manifest.json").read_bytes()
    if fault == "schema":
        header["schema_version"] = 2
    elif fault == "binding":
        header["format"]["input_ports"][0] = 99
    elif fault == "precision":
        header["precision"] = "F32"
    elif fault == "shape":
        header["n"] += 1
    fft.write_json(request, header)
    target = directory if fault == "existing_output" else tmp_path / "rejected"
    result = subprocess.run(  # noqa: S603 - fixed locally built binary and generated test paths
        [str(binary), str(request), str(source), str(target)], capture_output=True, text=True, timeout=30, check=False
    )
    assert result.returncode != 0
    assert (directory / "manifest.json").read_bytes() == original
    if fault != "existing_output":
        assert not target.exists()


def device_report(*, cancel=False):
    case = json.loads((acquisition.core.DEFAULT_FIXTURES / "manifest.json").read_bytes())["tones"][0]
    request = acquisition.request_for(case)
    request["precision"] = "F32"
    fmt = request["format"]
    before = {
        "nodes": 1,
        "subscriptions": 2,
        "in_flight": 0,
        "cache_results": 0 if cancel else 3,
        "cache_numeric_bytes": 0 if cancel else 10000,
        "fft_evaluations": 0 if cancel else 3,
        "display_replacements": 0 if cancel else 2,
    }
    return {
        "format": fmt,
        "input": {"samples": [] if cancel else list(range(2048)), "gaps": []},
        "analysis_graph": {
            "source": acquisition.expected_source(request),
            "windows": 0 if cancel else 3,
            "numeric_windows": 0 if cancel else 3,
            "gap_windows": 0,
            "shared_notifications": 0 if cancel else 2,
            "before_stop": before,
            "after_stop": {**before, "nodes": 0, "subscriptions": 0, "cache_results": 0, "cache_numeric_bytes": 0},
            "retained_history_frames": 0 if cancel else 2048,
        },
    }


@pytest.mark.parametrize("cancel", [False, True])
def test_device_graph_accepts_real_path_and_preparing_cancel(cancel):
    raw = device_report(cancel=cancel)
    assert acquisition.validate_device_graph(raw) == raw["analysis_graph"]


@pytest.mark.parametrize(
    "fault", ["missing", "identity", "origin", "evaluation", "sharing", "retained_node", "gap", "bool", "malformed"]
)
def test_device_graph_rejects_wrong_live_evidence(fault):
    raw = copy.deepcopy(device_report())
    graph = raw["analysis_graph"]
    if fault == "missing":
        del raw["analysis_graph"]
    elif fault == "identity":
        graph["source"]["stream_id"] = "foreign"
    elif fault == "origin":
        graph["source"]["timebase"]["uncertainty_seconds"] = {"numerator": 0, "denominator": 1}
    elif fault == "evaluation":
        graph["before_stop"]["fft_evaluations"] += 1
    elif fault == "sharing":
        graph["shared_notifications"] = 0
    elif fault == "retained_node":
        graph["after_stop"]["nodes"] = 1
    elif fault == "gap":
        raw["input"]["gaps"] = [[0, 1]]
    elif fault == "bool":
        graph["gap_windows"] = False
    else:
        graph["before_stop"] = []
    with pytest.raises(fft.ReferenceError):
        acquisition.validate_device_graph(raw)
