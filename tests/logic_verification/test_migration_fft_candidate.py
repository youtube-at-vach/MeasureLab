"""Real executable comparisons and rejection of corrupt FFT file boundaries."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

from scripts import migration_fft_candidate as candidate
from scripts import migration_fft_iteration as iteration
from scripts import migration_fft_reference as fft


@pytest.fixture(scope="module")
def binary():
    return candidate.build(candidate.ROOT / "native")[0]


@pytest.fixture
def valid_case():
    manifest, _ = candidate.load_manifest(fft.DEFAULT_FIXTURES, portable=True)
    return manifest["cases"][0]


def invoke(binary, tmp_path, request, data):
    request_path = tmp_path / "request.json"
    input_path = tmp_path / "input.bin"
    output = tmp_path / "output"
    fft.write_json(request_path, request)
    input_path.write_bytes(data)
    result = subprocess.run(  # noqa: S603 - built test executable or repository runner, no shell
        [str(binary), str(request_path), str(input_path), str(output)], capture_output=True, check=False
    )
    return result, output


@pytest.mark.native
def test_real_candidate_matches_all_small_and_multichannel_bytes(tmp_path):
    report = tmp_path / "report.json"
    result = subprocess.run(  # noqa: S603 - built test executable or repository runner, no shell
        [
            sys.executable,
            str(candidate.ROOT / "scripts/migration_fft_candidate.py"),
            "--portable",
            "--report",
            str(report),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(report.read_bytes())
    assert data["status"] == "pass"
    assert [len(s["cases"]) for s in data["suites"]] == [14, 4]
    assert data["environment"]["fft_precision"] == ["f32", "f64"]
    assert all(set(c["comparisons"]) == {"theory", "current"} for s in data["suites"] for c in s["cases"])
    assert data["binary_sha256"]


@pytest.mark.native
@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", 2),
        ("n", 2),
        ("n", 4_194_305),
        ("dtype", ">f8"),
        ("window", "periodic-hann"),
        ("rate_hz", 0),
        ("rate_hz", -48000),
        ("channel_ids", ["same", "same"]),
        ("channel_ids", ["", "second"]),
        ("extra", True),
    ],
)
def test_cli_rejects_invalid_request_without_output(binary, tmp_path, valid_case, field, value):
    request = candidate.request_for(valid_case)
    request[field] = value
    data = (fft.DEFAULT_FIXTURES / valid_case["spec"]["id"] / "input.bin").read_bytes()
    result, output = invoke(binary, tmp_path, request, data)
    assert result.returncode == 1
    assert not output.exists()
    assert b"FFT candidate failed" in result.stderr


@pytest.mark.native
@pytest.mark.parametrize("data", [b"", b"\0" * 7, np.full(8192, np.nan, dtype="<f8").tobytes()])
def test_cli_rejects_bytecount_and_nonfinite_input(binary, tmp_path, valid_case, data):
    result, output = invoke(binary, tmp_path, candidate.request_for(valid_case), data)
    assert result.returncode == 1
    assert not output.exists()


@pytest.mark.native
def test_cli_keeps_f32_transform_and_inverse(binary, tmp_path):
    manifest, _ = candidate.load_manifest(fft.DEFAULT_FIXTURES, portable=True)
    case = next(c for c in manifest["cases"] if c["spec"]["dtype"] == "<f4")
    request = candidate.request_for(case)
    data = (fft.DEFAULT_FIXTURES / case["spec"]["id"] / "input.bin").read_bytes()
    result, output = invoke(binary, tmp_path, request, data)
    assert result.returncode == 0, result.stderr
    arrays, _ = candidate.read_candidate(output, request)
    assert arrays["inverse_windowed"].dtype.str == "<f4"
    saved = fft.read_array(fft.DEFAULT_FIXTURES / case["spec"]["id"], case["arrays"]["current.fft_over_n"])
    fft.compare(arrays["fft_over_n"], saved, fft.TOLERANCES["f32"], "f32 FFT")


@pytest.mark.native
@pytest.mark.parametrize("mutation", ["ids", "units", "shape", "dtype", "path", "nonfinite"])
def test_reader_rejects_corrupt_candidate(binary, tmp_path, valid_case, mutation):
    request = candidate.request_for(valid_case)
    data = (fft.DEFAULT_FIXTURES / valid_case["spec"]["id"] / "input.bin").read_bytes()
    result, output = invoke(binary, tmp_path, request, data)
    assert result.returncode == 0
    manifest_path = output / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    if mutation == "ids":
        manifest["channel_ids"].reverse()
    elif mutation == "units":
        manifest["units"]["psd_fs2_hz"] = "FS/sqrt(Hz)"
    elif mutation == "shape":
        manifest["arrays"]["fft_over_n"]["shape"][0] -= 1
    elif mutation == "dtype":
        manifest["arrays"]["inverse_windowed"]["dtype"] = "<f4"
    elif mutation == "path":
        manifest["arrays"]["window"]["file"] = "../window.bin"
    else:
        path = output / "peak_fs.bin"
        values = np.frombuffer(path.read_bytes(), dtype="<f8").copy()
        values[0] = np.nan
        path.write_bytes(values.tobytes())
    fft.write_json(manifest_path, manifest)
    with pytest.raises(fft.ReferenceError):
        candidate.read_candidate(output, request)


def test_reader_rejects_modified_input_hash(tmp_path, valid_case):
    case_dir = tmp_path / valid_case["spec"]["id"]
    case_dir.mkdir()
    entry = valid_case["arrays"]["input"]
    data = bytearray((fft.DEFAULT_FIXTURES / valid_case["spec"]["id"] / entry["file"]).read_bytes())
    data[0] ^= 1
    (case_dir / entry["file"]).write_bytes(data)
    with pytest.raises(fft.ReferenceError, match="SHA-256"):
        fft.read_array(case_dir, entry)


def test_manifest_rejects_tolerance_change_even_portable(tmp_path):
    manifest, _ = candidate.load_manifest(fft.DEFAULT_FIXTURES, portable=True)
    manifest = copy.deepcopy(manifest)
    manifest["tolerances"]["f64"]["atol"] = 1e-2
    fft.write_json(tmp_path / "manifest.json", manifest)
    with pytest.raises(fft.ReferenceError, match="tolerances"):
        candidate.load_manifest(tmp_path, portable=True)


def test_report_cannot_overwrite_fixture_or_existing_file(tmp_path):
    existing = tmp_path / "report.json"
    existing.write_text("keep")
    for path in [existing, fft.DEFAULT_FIXTURES / "new-report.json"]:
        result = subprocess.run(  # noqa: S603 - built test executable or repository runner, no shell
            [
                sys.executable,
                str(candidate.ROOT / "scripts/migration_fft_candidate.py"),
                "--portable",
                "--report",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 2
        assert "Report must be new" in result.stderr
    assert existing.read_text() == "keep"


def test_iteration_keeps_checkout_and_lock_and_repeats_same_patch(tmp_path, monkeypatch):
    native = tmp_path / "native"
    source = native / "dsp-core/src/lib.rs"
    source.parent.mkdir(parents=True)
    baseline = "fn factor() {\n" + iteration.BASE + "\n}\n"
    source.write_text(baseline)
    (native / "rust-toolchain.toml").write_text('[toolchain]\nchannel = "1.98.1"\n')
    (native / "Cargo.lock").write_text("immutable lock")
    (native / "target").mkdir()
    (native / "target/do-not-copy").write_text("existing build")
    monkeypatch.setattr(iteration, "ROOT", tmp_path)
    monkeypatch.setattr(candidate, "rust_tool", lambda *_: "/resolved/cargo")
    commands = []
    verifications = []

    def command(argv, **_):
        copied = Path(argv[argv.index("--manifest-path") + 1]).parent
        assert copied != native
        assert (copied / "Cargo.lock").read_text() == "immutable lock"
        assert not (copied / "target/do-not-copy").exists()
        commands.append((copied / "dsp-core/src/lib.rs").read_text())
        return {"exit_code": 0}

    def verify(suites, *, native_root):
        verifications.append((native_root / "dsp-core/src/lib.rs").read_text())
        assert len(suites) == 3
        return {"status": "pass"}

    monkeypatch.setattr(candidate, "run_command", command)
    monkeypatch.setattr(candidate, "verify", verify)
    result = iteration.measure(tmp_path / "extended")
    edited = iteration.edited_source(baseline)
    assert commands == [baseline] + [value for _ in range(5) for value in (edited, baseline)]
    assert verifications == [baseline] + [edited] * 5
    assert source.read_text() == baseline
    assert (native / "Cargo.lock").read_text() == "immutable lock"
    assert len(result["samples"]) == 5
    with pytest.raises(fft.ReferenceError, match="patch no longer matches"):
        iteration.edited_source("unrelated source")
