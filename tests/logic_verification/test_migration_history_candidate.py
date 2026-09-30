"""Validate immutable-history/native boundary and reject corrupt evidence."""

import copy
import json
import subprocess

import numpy as np
import pytest

from scripts import migration_fft_candidate as candidate
from scripts import migration_fft_reference as fft
from scripts import migration_history_candidate as history


@pytest.fixture(scope="module")
def history_binary():
    binary, _ = history.build()
    return binary


@pytest.fixture
def corpus_output(history_binary, tmp_path):
    manifest = json.loads((history.core.DEFAULT_FIXTURES / "manifest.json").read_bytes())
    case = manifest["tones"][0]
    request = tmp_path / "request.json"
    fft.write_json(request, history.request_for(case))
    input_path = history.core.DEFAULT_FIXTURES / case["spec"]["id"] / "input.bin"
    output = tmp_path / "output"
    candidate.run_command([str(history_binary), "--corpus", str(request), str(input_path), str(output)])
    return case, output, request, input_path


def test_saved_history_time_contracts_and_original_4_8ch_bytes(history_binary, tmp_path):
    cases = history.reviewed_cases()
    request = tmp_path / "request.json"
    fft.write_json(
        request, {"schema_version": 1, "cases": [{k: c[k] for k in ("id", "operation", "input")} for c in cases]}
    )
    output = tmp_path / "observed.json"
    candidate.run_command([str(history_binary), "--cases", str(request), str(output)])
    history.validate_results(cases, json.loads(output.read_bytes()))
    assert len(cases) == 13
    manifest = json.loads((history.core.DEFAULT_FIXTURES / "manifest.json").read_bytes())
    for case in manifest["tones"]:
        result = history.verify_case(history_binary, case)
        assert result["history_graph"]["before_release"]["fft_evaluations"] == 1
    assert len(manifest["tones"]) == 4


@pytest.mark.parametrize("fault", ["position", "reason", "integer_type", "identity", "count", "unknown_field"])
def test_rejects_corrupt_contract_evidence(fault):
    cases = history.reviewed_cases()
    observed = [{"id": c["id"], "observed": copy.deepcopy(c["expected"])} for c in cases]
    if fault == "position":
        observed[0]["observed"]["interval"][0] += 1
    elif fault == "reason":
        observed[0]["observed"]["reason"] = "missing"
    elif fault == "integer_type":
        observed[0]["observed"]["generation"] = 3.0
    elif fault == "identity":
        observed[0]["id"] = "foreign"
    elif fault == "count":
        observed.pop()
    else:
        observed[0]["observed"]["extra"] = True
    with pytest.raises(fft.ReferenceError):
        history.validate_results(cases, observed)


@pytest.mark.parametrize(
    "fault",
    [
        "cursor",
        "source",
        "origin",
        "retention",
        "identity",
        "sharing",
        "count",
        "retained_node",
        "wrong_type",
        "unknown_field",
    ],
)
def test_rejects_corrupt_history_graph_manifest(corpus_output, fault):
    case, output, _, _ = corpus_output
    path = output / "manifest.json"
    header = json.loads(path.read_bytes())
    if fault == "cursor":
        header["reader_positions"][1] += 1
    elif fault == "source":
        header["source"]["channel_ids"].reverse()
    elif fault == "origin":
        header["source"]["timebase"]["origin_seconds"] = {"numerator": 0, "denominator": 1}
    elif fault == "retention":
        header["expired"]["missing"][0][0] += 1
    elif fault == "identity":
        header["second_result_id"]["serial"] += 1
    elif fault == "sharing":
        header["shared_allocation"] = False
    elif fault == "count":
        header["before_release"]["fft_evaluations"] = 2
    elif fault == "retained_node":
        header["after_shutdown"]["nodes"] = 1
    elif fault == "wrong_type":
        header["before_release"]["in_flight"] = False
    else:
        header["extra"] = True
    fft.write_json(path, header)
    with pytest.raises(fft.ReferenceError):
        history.read_corpus(output, case)


@pytest.mark.parametrize("fault", ["snapshot", "delayed", "fft_shape", "nonfinite"])
def test_rejects_changed_original_bytes_or_fft(corpus_output, fault):
    case, output, _, _ = corpus_output
    name = fault if fault in {"snapshot", "delayed"} else "fft_over_n"
    path = output / f"{name}.bin"
    raw = bytearray(path.read_bytes())
    if fault == "fft_shape":
        raw = raw[:-1]
    elif fault == "nonfinite":
        raw[:8] = np.float64(np.nan).tobytes()
    else:
        raw[0] ^= 1
    path.write_bytes(raw)
    with pytest.raises(fft.ReferenceError):
        history.read_corpus(output, case)


@pytest.mark.parametrize("fault", ["rate", "generation", "shape", "unknown_field", "existing_output"])
def test_native_corpus_rejects_malformed_request_and_preserves_input(history_binary, corpus_output, tmp_path, fault):
    _, _, request_path, input_path = corpus_output
    request = json.loads(request_path.read_bytes())
    output = tmp_path / "rejected"
    if fault == "rate":
        request["source"]["timebase"]["rate"]["numerator"] = 0
    elif fault == "generation":
        request["source"]["generation"] += 1
    elif fault == "shape":
        request["n"] += 1
    elif fault == "unknown_field":
        request["expected"] = "must not be consumed"
    else:
        output.mkdir()
        (output / "keep").write_text("preserved")
    fft.write_json(request_path, request)
    before = input_path.read_bytes()
    result = subprocess.run(  # noqa: S603 - local candidate with explicit argv, no shell
        [str(history_binary), "--corpus", str(request_path), str(input_path), str(output)],
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert input_path.read_bytes() == before
    if fault == "existing_output":
        assert (output / "keep").read_text() == "preserved"
    else:
        assert not output.exists()


def test_native_cases_reject_expected_answers_and_preserve_existing_output(history_binary, tmp_path):
    case = history.reviewed_cases()[0]
    request, output = tmp_path / "request.json", tmp_path / "output.json"
    fft.write_json(request, {"schema_version": 1, "cases": [case]})
    result = subprocess.run(  # noqa: S603 - local candidate, explicit argv
        [str(history_binary), "--cases", str(request), str(output)], capture_output=True, check=False
    )
    assert result.returncode != 0
    assert not output.exists()
    fft.write_json(request, {"schema_version": 1, "cases": [{k: case[k] for k in ("id", "operation", "input")}]})
    output.write_text("preserved")
    result = subprocess.run(  # noqa: S603 - local candidate, explicit argv
        [str(history_binary), "--cases", str(request), str(output)], capture_output=True, check=False
    )
    assert result.returncode != 0
    assert output.read_text() == "preserved"
