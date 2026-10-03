"""Exact-widened f32 acquisition evidence and explicit boundary rejections."""

import copy
import json
import subprocess

import numpy as np
import pytest

from scripts import migration_fft_reference as fft
from scripts import migration_filter_candidate as filters
from scripts import migration_filter_input as widening

pytestmark = pytest.mark.native


@pytest.fixture(scope="module")
def binary():
    return filters.build()[0]


@pytest.fixture(scope="module")
def manifest():
    return filters.load_manifest(portable=True)


@pytest.fixture
def result(binary, manifest, tmp_path):
    case = next(case for case in manifest["cases"] if case["spec"]["id"] == "fir-gap")
    directory = tmp_path / "run"
    widening.verify_case(binary, case, 4, True, directory, manifest["tolerances"])
    request, values = widening.prepare(case, 4, True)
    return directory, request, values


def test_p2_fir_f32_two_four_eight_channels_and_both_port_orders(binary, manifest, tmp_path):
    for case in (case for case in manifest["cases"] if case["spec"]["kind"] == "fir"):
        for channels in (2, 4, 8):
            for reverse in (False, True):
                report = widening.verify_case(
                    binary,
                    case,
                    channels,
                    reverse,
                    tmp_path / f"{case['spec']['id']}-{channels}-{reverse}",
                    manifest["tolerances"],
                )
                assert report["graph"]["metadata"]["input_conversion"] == "F32ToF64Exact"
                assert len(report["graph"]["runs"]) == 5


@pytest.mark.parametrize("fault", ["parent_precision", "conversion", "revision", "raw_bytes", "output_bytes"])
def test_false_widening_provenance_or_mutated_input_is_rejected(result, manifest, fault):
    directory, request, values = result
    output = directory / "output"
    if fault in {"raw_bytes", "output_bytes"}:
        path = output / ("whole.raw_f32_as_f64.bin" if fault == "raw_bytes" else "whole.output.bin")
        data = np.frombuffer(path.read_bytes(), dtype="<f8").copy()
        data[5] += 0.01
        path.write_bytes(data.tobytes())
    else:
        path = output / "manifest.json"
        header = json.loads(path.read_bytes())
        meta = header["metadata"]
        if fault == "parent_precision":
            meta["parent"]["precision"] = "F64"
        elif fault == "conversion":
            meta.pop("input_conversion")
        else:
            meta["output"]["filter_state_revision"] = meta["output"]["filter_state_revision"].replace(
                "/f32-to-f64-exact-v1", ""
            )
        fft.write_json(path, header)
    with pytest.raises(fft.ReferenceError):
        widening.check_output(output, request, values, manifest["tolerances"])


@pytest.mark.parametrize(
    "fault", ["implicit", "policy", "wrong_precision", "duplicate_ports", "nonfinite", "truncated"]
)
def test_native_refuses_implicit_or_inconsistent_conversion(binary, result, tmp_path, fault):
    directory, original, _ = result
    request = copy.deepcopy(original)
    raw = (directory / "input.f32.bin").read_bytes()
    if fault == "implicit":
        request.pop("input_conversion")
    elif fault == "policy":
        request["input_conversion"] = "F64ToF32"
    elif fault == "wrong_precision":
        request["source"]["precision"] = "F64"
    elif fault == "duplicate_ports":
        request["input_ports"] = [0, 0, 1, 2]
    elif fault == "nonfinite":
        raw = np.array([np.inf], dtype="<f4").tobytes() + raw[4:]
    else:
        raw = raw[:-1]
    input_path, request_path, output = tmp_path / "input.bin", tmp_path / "request.json", tmp_path / "rejected"
    input_path.write_bytes(raw)
    fft.write_json(request_path, request)
    completed = subprocess.run(  # noqa: S603 - local locked candidate and explicit argv
        [str(binary), "--acquisition", str(request_path), str(input_path), str(output)],
        capture_output=True,
        check=False,
    )
    assert completed.returncode != 0
    assert input_path.read_bytes() == raw
    assert not output.exists()
