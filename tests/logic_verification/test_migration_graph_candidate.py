"""Exercise the native graph boundary and reject dishonest/corrupt result records."""

import copy
import json
import subprocess

import numpy as np
import pytest

from scripts import migration_graph_candidate as graph
from scripts import migration_fft_reference as fft
from scripts import migration_fft_candidate as candidate


@pytest.fixture(scope="module")
def graph_binary():
    binary, _ = graph.build(graph.ROOT / "native")
    return binary


@pytest.fixture
def graph_output(graph_binary, tmp_path):
    directory = fft.DEFAULT_FIXTURES
    case = json.loads((directory / "manifest.json").read_bytes())["cases"][0]
    request_path = tmp_path / "request.json"
    fft.write_json(request_path, graph.request_for(case))
    input_path = directory / case["spec"]["id"] / "input.bin"
    output = tmp_path / "output"
    record = candidate.run_command([str(graph_binary), str(request_path), str(input_path), str(output)])
    assert record["exit_code"] == 0
    return case, output, request_path, input_path


def test_original_fixture_bytes_share_one_fft_and_release_graph(graph_binary):
    count = 0
    for directory, is_core in [(fft.DEFAULT_FIXTURES, False), (graph.core.DEFAULT_FIXTURES, True)]:
        manifest, _ = candidate.load_manifest(directory, is_core=is_core)
        for case in manifest["tones"] if is_core else manifest["cases"]:
            result = graph.verify_case(graph_binary, directory, case, is_core=is_core)
            assert result["graph"]["before_release"]["fft_evaluations"] == 1
            count += 1
    assert count == 18


@pytest.mark.parametrize(
    "fault",
    [
        "identity",
        "evaluation_count",
        "channel_order",
        "timebase",
        "interval",
        "retained_node",
        "array_shape",
        "unknown_field",
        "wrong_type",
        "null_stats",
    ],
)
def test_rejects_corrupt_identity_counts_metadata_and_shape(graph_output, fault):
    case, output, _, _ = graph_output
    path = output / "manifest.json"
    header = json.loads(path.read_bytes())
    if fault == "identity":
        header["spectrogram_result_id"]["serial"] += 1
    elif fault == "evaluation_count":
        header["before_release"]["fft_evaluations"] = 2
    elif fault == "channel_order":
        header["key"]["source"]["channel_ids"].reverse()
    elif fault == "timebase":
        header["key"]["source"]["timebase"]["origin_seconds"] = {"numerator": 0, "denominator": 1}
    elif fault == "interval":
        header["interval"][0] += 1
    elif fault == "retained_node":
        header["after_shutdown"]["nodes"] = 1
    elif fault == "array_shape":
        header["arrays"]["fft_over_n"]["shape"][1] = 1
    elif fault == "wrong_type":
        header["before_release"]["fft_evaluations"] = True
    elif fault == "null_stats":
        header["before_release"] = None
    else:
        header["unexpected"] = 1
    fft.write_json(path, header)
    with pytest.raises(fft.ReferenceError):
        graph.read_result(output, case)


@pytest.mark.parametrize("fault", ["truncated", "nonfinite", "path_escape"])
def test_rejects_bad_numeric_bytes_and_paths(graph_output, fault):
    case, output, _, _ = graph_output
    path = output / "fft_over_n.bin"
    if fault == "truncated":
        path.write_bytes(path.read_bytes()[:-1])
    elif fault == "nonfinite":
        raw = bytearray(path.read_bytes())
        raw[:8] = np.float64(np.nan).tobytes()
        path.write_bytes(raw)
    else:
        manifest = output / "manifest.json"
        header = json.loads(manifest.read_bytes())
        header["arrays"]["fft_over_n"]["file"] = "../fft_over_n.bin"
        fft.write_json(manifest, header)
    with pytest.raises(fft.ReferenceError):
        graph.read_result(output, case)


@pytest.mark.parametrize(
    "fault", ["zero_rate", "wrong_generation", "duplicate_channel", "bad_shape", "unknown_field", "output_exists"]
)
def test_native_adapter_rejects_invalid_request_without_touching_input(graph_binary, graph_output, tmp_path, fault):
    _, _, request_path, input_path = graph_output
    original_hash = fft.digest(input_path.read_bytes())
    request = json.loads(request_path.read_bytes())
    output = tmp_path / "rejected"
    if fault == "zero_rate":
        request["key"]["source"]["timebase"]["rate"]["numerator"] = 0
    elif fault == "wrong_generation":
        request["key"]["source"]["generation"] += 1
    elif fault == "duplicate_channel":
        request["key"]["source"]["channel_ids"][1] = request["key"]["source"]["channel_ids"][0]
    elif fault == "bad_shape":
        request["key"]["n"] += 1
    elif fault == "unknown_field":
        request["extra"] = "unsupported"
    else:
        output.mkdir()
        (output / "keep").write_text("preserved")
    fft.write_json(request_path, request)
    result = subprocess.run(  # noqa: S603 - locally built evaluation binary, explicit argv, no shell
        [str(graph_binary), str(request_path), str(input_path), str(output)], capture_output=True, check=False
    )
    assert result.returncode != 0
    assert fft.digest(input_path.read_bytes()) == original_hash
    if fault == "output_exists":
        assert (output / "keep").read_text() == "preserved"
    else:
        assert not output.exists()


def test_reference_metadata_mapping_preserves_unknown_time_and_logical_ids():
    manifest = json.loads((fft.DEFAULT_FIXTURES / "manifest.json").read_bytes())
    case = manifest["cases"][0]
    before = copy.deepcopy(case)
    request = graph.request_for(case)
    assert request["key"]["source"]["timebase"]["origin_seconds"] is None
    assert request["key"]["source"]["timebase"]["uncertainty_seconds"] is None
    assert request["key"]["source"]["channel_ids"] == case["metadata"]["channel_ids"]
    assert case == before
