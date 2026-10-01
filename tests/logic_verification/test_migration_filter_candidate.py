"""Saved numerical/state contracts and malformed evidence at the native worker boundary."""

import copy
import json
import shutil
import subprocess

import numpy as np
import pytest

from scripts import migration_fft_candidate as candidate
from scripts import migration_fft_reference as fft
from scripts import migration_filter_candidate as filters


@pytest.fixture(scope="module")
def filter_binary():
    return filters.build()[0]


@pytest.fixture(scope="module")
def filter_manifest():
    return filters.load_manifest(portable=True)


@pytest.fixture
def result(filter_binary, filter_manifest, tmp_path):
    case = filter_manifest["cases"][4]  # warmup and exact acquisition-gap propagation
    request = filters.request_for(case)
    path = tmp_path / "request.json"
    fft.write_json(path, request)
    input_path = filters.FIXTURES / case["spec"]["id"] / "input.bin"
    output = tmp_path / "output"
    candidate.run_command([str(filter_binary), str(path), str(input_path), str(output)])
    return request, output, path, input_path


@pytest.mark.native
def test_saved_21_cases_five_chunks_and_graph_state(filter_binary, filter_manifest):
    for case in filter_manifest["cases"]:
        report = filters.verify_case(filter_binary, case, filter_manifest["tolerances"])
        assert set(report["graph"]["runs"]) == set(filters.CHUNKS)
    assert len(filter_manifest["cases"]) == 21


@pytest.mark.parametrize("fault", ["metadata", "tolerance", "coefficient_bytes", "input_bytes"])
def test_saved_manifest_and_original_bytes_are_pinned(filter_manifest, tmp_path, fault):
    if fault in {"metadata", "tolerance"}:
        manifest = copy.deepcopy(filter_manifest)
        if fault == "metadata":
            manifest["cases"][0]["metadata"]["generation"] += 1
        else:
            manifest["tolerances"]["fir"]["atol"] *= 2
        fft.write_json(tmp_path / "manifest.json", manifest)
    else:
        shutil.copy(filters.FIXTURES / "manifest.json", tmp_path)
        case = filter_manifest["cases"][0]
        folder = tmp_path / case["spec"]["id"]
        shutil.copytree(filters.FIXTURES / case["spec"]["id"], folder)
        path = folder / ("input.bin" if fault == "input_bytes" else "coefficients.bin")
        data = bytearray(path.read_bytes())
        data[0] ^= 1
        path.write_bytes(data)
    with pytest.raises(fft.ReferenceError):
        filters.load_manifest(portable=True, directory=tmp_path)


@pytest.mark.native
@pytest.mark.parametrize(
    "fault",
    [
        "delay",
        "unknown_latency",
        "source",
        "channel",
        "origin",
        "generation",
        "trigger",
        "integer_type",
        "gap",
        "sharing",
        "id",
        "duplicate_id",
        "fft_validity",
        "numeric_invalid",
        "average",
        "filters_retained",
        "cache_retained",
        "evaluation_count",
        "array_shape",
        "unknown_field",
    ],
)
def test_rejects_changed_metadata_validity_sharing_or_ownership(result, fault):
    request, output, _, _ = result
    path = output / "manifest.json"
    h = json.loads(path.read_bytes())
    run = h["runs"]["whole"]
    if fault == "delay":
        h["metadata"]["signal_delay_output_samples"]["numerator"] += 1
    elif fault == "unknown_latency":
        h["metadata"]["processing_latency_seconds"] = filters.rational(0)
    elif fault == "source":
        h["metadata"]["parent"]["stream_id"] = "foreign"
    elif fault == "channel":
        h["metadata"]["output"]["channel_ids"].reverse()
    elif fault == "origin":
        h["metadata"]["output"]["timebase"]["origin_seconds"] = filters.rational(0)
    elif fault == "generation":
        h["metadata"]["output"]["generation"] += 1
    elif fault == "trigger":
        h["trigger_output"]["denominator"] += 1
    elif fault == "integer_type":
        run["filters_before"] = True
    elif fault == "gap":
        run["validity"] = [s for s in run["validity"] if s["reason"] != "gap"]
    elif fault == "sharing":
        run["windows"][0]["shared_allocation"] = False
    elif fault == "id":
        run["windows"][0]["second_result_id"]["serial"] += 1
    elif fault == "duplicate_id":
        run["windows"][1]["result_id"] = copy.deepcopy(run["windows"][0]["result_id"])
        run["windows"][1]["second_result_id"] = copy.deepcopy(run["windows"][0]["result_id"])
    elif fault == "fft_validity":
        run["windows"][0]["validity"] = []
    elif fault == "numeric_invalid":
        run["windows"][0]["numeric"] = True
    elif fault == "average":
        run["windows"][0]["average_count"] = 1
    elif fault == "filters_retained":
        run["filters_released"] = 1
    elif fault == "cache_retained":
        run["after_release"]["cache_results"] = 1
    elif fault == "evaluation_count":
        run["before_release"]["fft_evaluations"] += 1
    elif fault == "array_shape":
        h["arrays"]["whole.output"]["values"] += 1
    else:
        h["extra"] = True
    fft.write_json(path, h)
    with pytest.raises(fft.ReferenceError):
        filters.read_result(output, request)


@pytest.mark.native
@pytest.mark.parametrize("fault", ["truncated", "nonfinite"])
def test_rejects_corrupt_result_bytes(result, fault):
    request, output, _, _ = result
    path = output / "whole.output.bin"
    data = path.read_bytes()
    path.write_bytes(data[:-1] if fault == "truncated" else np.float64(np.nan).tobytes() + data[8:])
    with pytest.raises(fft.ReferenceError):
        filters.read_result(output, request)


@pytest.mark.native
@pytest.mark.parametrize(
    "fault",
    [
        "unknown_field",
        "frames",
        "gap_order",
        "chunk_zero",
        "source_rate",
        "target_rate",
        "precision",
        "coefficients",
        "existing_output",
    ],
)
def test_native_rejections_preserve_input_and_output(filter_binary, result, tmp_path, fault):
    request, _, path, input_path = result
    output = tmp_path / "rejected"
    if fault == "unknown_field":
        request["expected"] = "candidate must not receive expectations"
    elif fault == "frames":
        request["frames"] += 1
    elif fault == "gap_order":
        request["gaps"] = [[200, 204], [100, 104]]
    elif fault == "chunk_zero":
        request["chunks"]["one"] = [0]
    elif fault == "source_rate":
        request["source"]["timebase"]["rate"]["numerator"] = 0
    elif fault == "target_rate":
        request["config"]["target_rate"]["numerator"] = -1
    elif fault == "precision":
        request["source"]["precision"] = "F32"
    elif fault == "coefficients":
        request["config"]["coefficients"][0] = 0.125
    else:
        output.mkdir()
        (output / "keep").write_text("preserved")
    fft.write_json(path, request)
    before = input_path.read_bytes()
    completed = subprocess.run(  # noqa: S603 - local locked candidate, explicit argv without shell
        [str(filter_binary), str(path), str(input_path), str(output)],
        capture_output=True,
        check=False,
    )
    assert completed.returncode != 0
    assert input_path.read_bytes() == before
    if fault == "existing_output":
        assert (output / "keep").read_text() == "preserved"
    else:
        assert not output.exists()


@pytest.mark.native
def test_saved_rate_rejections_and_identity(filter_binary, filter_manifest, tmp_path):
    path = tmp_path / "rates.json"
    output = tmp_path / "observed.json"
    fft.write_json(path, {"schema_version": 1, "rates": [c["rates"] for c in filter_manifest["rate_cases"]]})
    candidate.run_command([str(filter_binary), "--rates", str(path), str(output)])
    values = json.loads(output.read_bytes())
    assert [v["status"] for v in values] == [c["contract"] for c in filter_manifest["rate_cases"]]
    assert all(v["ratio"] is None for v in values[:-1])
    assert values[-1]["ratio"] == filters.rational(1)
