"""Independent anchors and failure modes for the versioned, headless reference."""

from copy import deepcopy
import json
import shutil
import subprocess
import sys

import numpy as np
import pytest

from scripts import migration_fft_oracle as oracle
from scripts import migration_fft_reference as reference


@pytest.mark.parametrize("n", [15, 16])
@pytest.mark.parametrize("window", ["boxcar", "hann"])
@pytest.mark.parametrize("signal", ["cosine", "dc", "nyquist", "impulse", "silence"])
def test_analytic_oracle_against_direct_dft(n, window, signal):
    if signal == "nyquist" and n % 2:
        pytest.skip("The Nyquist fixture is defined only for even N")
    spec = dict(n=n, window=window, signal=signal, tones=[[3, 0.25, 0.3]], dtype="<f8", rate_hz=48000)
    x = oracle.make_input(spec)
    w = oracle.window_values(n, window)
    matrix = np.exp(-2j * np.pi * np.arange(n // 2 + 1)[:, None] * np.arange(n)[None, :] / n)
    expected = matrix @ (x * w[:, None]) / n
    np.testing.assert_allclose(oracle.analytic_fft(spec), expected, atol=2e-14, rtol=2e-14)


def test_hand_calculated_peak_rms_and_endpoints():
    specs = {spec["id"]: spec for spec in oracle.cases("small")}
    tone = specs["tone-quarter"]
    values = oracle.theory(tone, oracle.make_input(tone))
    assert values["peak_fs"][37, 0] == pytest.approx(0.25, abs=1e-12)
    assert values["rms_fs"][0] == pytest.approx(0.25 / np.sqrt(2), abs=1e-12)
    assert values["integrated_power_fs2"][0] == pytest.approx(0.25**2 / 2, abs=1e-12)
    for name, index in [("dc-boxcar", 0), ("nyquist-boxcar", 2048), ("odd-last-bin", 2047)]:
        spec = specs[name]
        values = oracle.theory(spec, oracle.make_input(spec))
        assert values["peak_fs"][index, 0] == pytest.approx(0.125, abs=1e-12)
        rms = 0.125 / np.sqrt(2) if name == "odd-last-bin" else 0.125
        assert values["rms_fs"][0] == pytest.approx(rms, abs=1e-12)
    assert np.angle(values["fft_over_n"][2047, 0]) == pytest.approx(0.3, abs=1e-12)


def test_parseval_is_windowed_power_not_unwindowed_rms():
    spec = next(spec for spec in oracle.cases("small") if spec["id"] == "impulse-hann")
    values = oracle.theory(spec, oracle.make_input(spec))
    assert values["rms_fs"][0] == 1 / 64
    assert values["integrated_power_fs2"][0] == 0
    assert values["time_window_power_fs2"][0] == 0


@pytest.mark.parametrize("n", [0, 1, 2])
def test_undefined_small_windows_rejected(n):
    with pytest.raises(ValueError, match="N >= 3"):
        oracle.window_values(n, "hann")


def test_comparator_rejects_nonfinite_and_normalization_error():
    for actual in ([np.nan], [np.inf], [2.0]):
        with pytest.raises(reference.ReferenceError):
            reference.compare(actual, [1.0], reference.TOLERANCES["f64"], "test")
    with pytest.raises(reference.ReferenceError, match="shape"):
        reference.compare([[1.0]], [1.0], reference.TOLERANCES["f64"], "test")
    # A component-wise complex check would incorrectly accept this diagonal error.
    with pytest.raises(reference.ReferenceError, match="numerical"):
        reference.compare([0.8 + 0.8j], [0j], {"atol": 1, "rtol": 0}, "complex modulus")


def manifest():
    return json.loads((reference.DEFAULT_FIXTURES / "manifest.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "field", ["schema_version", "contract", "reference_commit", "source_sha256", "generator_sha256", "tolerances"]
)
def test_manifest_version_and_provenance_rejected(field):
    value = manifest()
    value[field] = "wrong-version"
    with pytest.raises(reference.ReferenceError, match=field):
        reference.validate_manifest(value, strict_environment=False)


def test_changed_dependency_version_is_not_silently_accepted():
    value = manifest()
    value["environment"] = reference.environment()
    value["environment"]["packages"]["numpy"] = "0.0.0"
    with pytest.raises(reference.ReferenceError, match="Environment/version"):
        reference.validate_manifest(value)
    reference.validate_manifest(value, strict_environment=False)


@pytest.mark.parametrize(
    "mutation", ["shape", "dtype", "encoding", "origin", "metadata", "missing", "spec", "duplicate"]
)
def test_manifest_schema_and_metadata_rejected(mutation):
    value = manifest()
    case = value["cases"][0]
    entry = case["arrays"]["input"]
    if mutation == "shape":
        entry["shape"].reverse()  # Same bytes, different shape must still fail.
    elif mutation == "dtype":
        entry["dtype"] = ">f8"
    elif mutation == "encoding":
        entry["complex"] = "real-imag-last-axis"
    elif mutation == "origin":
        entry["origin"] = "theory"
    elif mutation == "metadata":
        case["metadata"]["channel_ids"].reverse()
    elif mutation == "missing":
        del case["arrays"]["theory.psd_fs2_hz"]
    elif mutation == "spec":
        case["spec"]["n"] = 1
    else:
        value["cases"].append(deepcopy(case))
    with pytest.raises(reference.ReferenceError):
        reference.validate_manifest(value, strict_environment=False)


def test_changed_product_source_is_rejected(tmp_path):
    for name in reference.PINNED_SOURCE_SHA256:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(reference.ROOT / name, target)
    target.write_text("changed", encoding="utf-8")
    with pytest.raises(reference.ReferenceError, match="Reference source differs"):
        reference.source_hashes(tmp_path)


def test_array_hash_byte_count_and_nonfinite_rejected(tmp_path):
    values = np.array([[1.0, 0.125]])
    entry = reference.store_array(tmp_path, "input", values, "fixed-input")
    path = tmp_path / entry["file"]
    path.write_bytes(path.read_bytes()[:-1] + b"\xff")
    with pytest.raises(reference.ReferenceError, match="SHA-256"):
        reference.read_array(tmp_path, entry)
    entry = reference.store_array(tmp_path, "input", values, "fixed-input")
    entry["shape"] = [3]
    with pytest.raises(reference.ReferenceError, match="byte count"):
        reference.read_array(tmp_path, entry)
    entry = reference.store_array(tmp_path, "input", np.array([np.nan]), "fixed-input")
    with pytest.raises(reference.ReferenceError, match="nonfinite"):
        reference.read_array(tmp_path, entry)
    entry["file"] = "../input.bin"
    with pytest.raises(reference.ReferenceError, match="path"):
        reference.read_array(tmp_path, entry)


def run_reference(*args):
    return subprocess.run(  # noqa: S603 -- fixed repository script and test-controlled paths
        [sys.executable, str(reference.ROOT / "scripts/migration_fft_reference.py"), *map(str, args)],
        cwd=reference.ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


def test_versioned_corpus_in_fresh_headless_process(tmp_path):
    # CI may have different package/OS versions: it must explicitly label that run.
    report_path = tmp_path / "run.json"
    before = {p: reference.digest(p.read_bytes()) for p in reference.DEFAULT_FIXTURES.rglob("*") if p.is_file()}
    result = run_reference("verify", "--portable", "--report", report_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "no GUI/device imports" in result.stdout
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["mode"] == "portable-numerical-comparison"
    assert len(report["cases"]) == 14
    assert all(reference.digest(path.read_bytes()) == sha for path, sha in before.items())
    for case in report["cases"]:
        for difference in case["known_differences"]:
            offset = (
                6.02059991328
                if difference["mode"] == "Spectrum" and difference["display_unit"] == "dBFS"
                else 3.01029995664
            )
            assert difference["difference_db"] == pytest.approx(offset, abs=1e-8)


def test_generate_is_explicit_deterministic_and_never_overwrites(tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    for directory in (first, second):
        result = run_reference("generate", "--output", directory)
        assert result.returncode == 0, result.stdout + result.stderr
    # Includes input/expected bytes, source/dependency versions and generator hash.
    for path in first.rglob("*"):
        if path.is_file():
            assert path.read_bytes() == (second / path.relative_to(first)).read_bytes()
    retry = run_reference("generate", "--output", first)
    assert retry.returncode == 1
    assert "never overwritten" in retry.stderr
    checked = run_reference("verify", "--fixtures", first)
    assert checked.returncode == 0, checked.stdout + checked.stderr


def test_saved_input_is_verified_without_regenerating_signal():
    code = """
from scripts import migration_fft_reference as ref
def forbidden(*args):
    raise AssertionError('verify must read saved input bytes')
ref.oracle.make_input = forbidden
assert ref.verify(ref.DEFAULT_FIXTURES, portable=True)['status'] == 'pass'
"""
    result = subprocess.run(  # noqa: S603 -- fixed test code
        [sys.executable, "-c", code], cwd=reference.ROOT, capture_output=True, text=True, check=False, timeout=60
    )
    assert result.returncode == 0, result.stdout + result.stderr
