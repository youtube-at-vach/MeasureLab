"""Independent anchors, state transitions and exchange corruption for MIG-003-B."""

from copy import deepcopy
import random
import shutil
import subprocess
import sys

import numpy as np
import pytest

from scripts import migration_core_cases as cases
from scripts import migration_core_oracle as model
from scripts import migration_core_reference as reference
from scripts import migration_fft_reference as fft


def example(name):
    return next(case for case in cases.scenarios() if case["id"] == name)


@pytest.mark.parametrize("case", cases.scenarios(), ids=lambda case: case["id"])
def test_independent_hand_calculated_examples(case):
    reference.compare_tree(model.evaluate(case), case["expected"])


def test_history_interval_oracle_against_discrete_sample_sets():
    rng = random.Random(3003)  # noqa: S311 -- deterministic interval test, no secrets
    for _ in range(100):
        query = deepcopy(example("history-reader-fast")["input"])
        acquired = rng.randrange(1, 50)
        capacity = rng.randrange(1, 50)
        k = rng.randrange(0, 50)
        query["event"]["sample"] = [k, 1]
        query.update(
            pre=3,
            post=5,
            capacity=capacity,
            acquired_until=acquired,
            acquired_intervals=[[0, 10], [14, 20], [22, acquired]],
        )
        result = model.history_query(query)
        available = {n for n in range(max(0, acquired - capacity), acquired) if n < 10 or 14 <= n < 20 or n >= 22}
        expected_missing = {n for n in range(k - 3, min(k + 5, acquired)) if n not in available}
        actual_missing = {n for start, end in result["missing"] for n in range(start, end)}
        assert actual_missing == expected_missing
        assert {n for start, end in result["pending"] for n in range(start, end)} == set(
            range(max(k - 3, acquired), k + 5)
        )


def test_history_readers_notifications_and_published_snapshots_are_independent():
    fast = example("history-reader-fast")["input"]
    slow = example("history-reader-delayed")["input"]
    published = model.history_query(fast)
    assert model.history_query(fast) == model.history_query(slow) == published
    slow["event"]["sample"] = [0, 1]
    slow["generation"] = 4
    assert model.history_query(slow)["reason"] == "stale_generation"
    assert published["interval"] == [1792, 2816]
    assert model.history_query(fast) == published


def test_rejected_route_does_not_modify_current_or_published_route():
    data = example("route-boundary-and-rejections")["input"]
    records = model.route_changes(data)
    for record in records[1:-1]:
        assert record["status"] == "rejected"
        assert record["published_route"]["revision"] == "route.1"
    assert records[0]["sample"] == 128
    assert records[-1]["sample"] == 256
    records[-1]["published_route"]["gains"][0][0] = 999
    data["requests"][0]["route"]["gains"][0][1] = 999
    assert records[0]["published_route"]["gains"] == [[0, 1]]


def test_unlabelled_null_cannot_borrow_another_channels_reason():
    case = example("route-reason-union")
    case["input"]["validity"].pop()
    assert model.evaluate(case) == {"status": "rejected", "reason": "null_without_reason"}


@pytest.mark.parametrize(
    "field,value", [("rate", [24000, 1]), ("dtype", "<f4"), ("binding", [1, 0]), ("clock_domain", "other")]
)
def test_configuration_change_requires_new_generation(field, value):
    block = example("blocks-gap-reorder-restart")["input"]["blocks"][0]
    changed = dict(block, start=2, **{field: value})
    assert model.stream_blocks({"blocks": [block, changed]})[-1]["reason"] == "configuration_requires_new_generation"
    changed.update(generation=4, start=0)
    assert model.stream_blocks({"blocks": [block, changed]})[-1]["status"] == "accepted"


def test_profile_changes_cannot_revise_existing_result_or_axis():
    case = example("calibration-reorder-and-unknown")
    result = model.measurement_result(case["input"])
    case["input"]["profiles"]["input.alpha"].update(revision="profile.2", v_per_fs=2)
    case["input"]["frequency_correction"] = 1
    updated = model.measurement_result(case["input"])
    reference.compare_tree(result, case["expected"])
    assert updated["channels"][1]["rms_v"] == 2 * result["channels"][1]["rms_v"]
    assert result["channels"][1]["calibration"]["revision"] == "profile.1"
    assert result["axis"]["corrected"] == [1000.1, 2000.2]
    assert updated["axis"]["corrected"] == [1000, 2000]
    # A default coefficient, even 1.25, is not proof of an actual calibration.
    unknown = result["channels"][-1]
    assert unknown["peak_fs"] == 0.0625
    assert unknown["rms_v"] is None and unknown["spl"] is None


@pytest.mark.parametrize("format_id", ["json", "csv"])
def test_result_roundtrip_and_save_failure(tmp_path, format_id):
    result = example("calibration-reorder-and-unknown")["expected"]
    path = tmp_path / f"result.{format_id}"
    reference.save_result(path, result, format_id)
    decode = reference.read_json if format_id == "json" else reference.read_csv
    reference.compare_tree(decode(path.read_bytes()), result)
    before = path.read_bytes()
    with pytest.raises(FileExistsError):
        reference.save_result(path, result, format_id)
    assert path.read_bytes() == before
    with pytest.raises(OSError):
        reference.save_result(tmp_path / "missing" / "result", result, format_id)


@pytest.mark.parametrize(
    "actual,expected",
    [
        ({"generation": 3.0}, {"generation": 3}),
        ({"interval": [1792, 2817]}, {"interval": [1792, 2816]}),
        ({"fractional_residual": [2, 4]}, {"fractional_residual": [1, 2]}),
        ({"reason": None}, {"reason": "uncalibrated"}),
        ({"values": [[float("nan")]]}, {"values": [[0]]}),
        ({"values": [[0]]}, {"values": [[None]]}),
        ({"values": [[1.0001]]}, {"values": [[1]]}),
    ],
)
def test_exact_metadata_null_and_numeric_errors_are_rejected(actual, expected):
    with pytest.raises(fft.ReferenceError):
        reference.compare_tree(actual, expected)


@pytest.mark.parametrize("data", [b'{"value":NaN}', b'{"value":Infinity}', b'{"a":1,"a":2}'])
def test_nonstandard_or_duplicate_json_rejected(data):
    with pytest.raises(fft.ReferenceError):
        reference.read_json(data)


def manifest():
    return reference.read_json((reference.DEFAULT_FIXTURES / "manifest.json").read_bytes())


@pytest.mark.parametrize(
    "field",
    [
        "schema_version",
        "contract",
        "source_sha256",
        "generator_sha256",
        "contract_sha256",
        "reference_commit",
        "core_tolerances",
        "fft_tolerances",
    ],
)
def test_manifest_provenance_cannot_be_silently_changed(field):
    value = manifest()
    value[field] = "changed"
    with pytest.raises(fft.ReferenceError, match=field):
        reference.validate_manifest(value, portable=True)


def test_environment_override_is_explicit():
    value = manifest()
    value["environment"] = reference.fft.environment()
    value["environment"]["packages"]["numpy"] = "0"
    with pytest.raises(fft.ReferenceError, match="environment"):
        reference.validate_manifest(value)
    reference.validate_manifest(value, portable=True)


@pytest.mark.parametrize("mutation", ["shape", "dtype", "encoding", "origin", "missing", "path"])
def test_array_schema_rejected(mutation):
    case = manifest()["tones"][0]
    entry = case["arrays"]["input"]
    if mutation == "shape":
        entry["shape"].reverse()
    elif mutation == "dtype":
        entry["dtype"] = ">f8"
    elif mutation == "encoding":
        entry["complex"] = "real-imag-last-axis"
    elif mutation == "origin":
        entry["origin"] = "current"
    elif mutation == "missing":
        del case["arrays"]["current.rms_fs"]
    else:
        entry["file"] = "../input.bin"
    with pytest.raises(fft.ReferenceError):
        reference.load_tone(reference.DEFAULT_FIXTURES, case)


def run_reference(*args):
    return subprocess.run(  # noqa: S603 -- fixed repository script, test-controlled paths
        [sys.executable, str(reference.ROOT / "scripts/migration_core_reference.py"), *map(str, args)],
        cwd=reference.ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


def test_saved_fixture_in_fresh_headless_process(tmp_path):
    files = {path: fft.digest(path.read_bytes()) for path in reference.DEFAULT_FIXTURES.rglob("*") if path.is_file()}
    report = tmp_path / "report.json"
    result = run_reference("verify", "--portable", "--report", report)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "no GUI/device imports" in result.stdout
    saved = reference.read_json(report.read_bytes())
    assert saved["mode"] == "portable-comparison"
    assert len(saved["scenarios"]) == 27
    assert len(saved["tones"]) == 4
    assert saved["exports"] == 4
    assert all(fft.digest(path.read_bytes()) == sha for path, sha in files.items())
    # Direct scalar AC01 anchors, independently of the analytic FFT oracle.
    for entry in manifest()["tones"]:
        arrays = reference.load_tone(reference.DEFAULT_FIXTURES, entry)
        for c, (bin_index, amplitude, phase) in enumerate(entry["spec"]["tones"]):
            assert arrays["current.peak_fs"][bin_index, c] == pytest.approx((c + 1) / 32, abs=2e-6)
            assert arrays["current.rms_fs"][c] == pytest.approx(amplitude / np.sqrt(2), abs=2e-6)
            assert np.angle(arrays["current.fft_over_n"][bin_index, c]) == pytest.approx(phase, abs=1e-4)


@pytest.mark.parametrize("mutation", ["hash", "reviewed-data", "export-null", "metadata"])
def test_saved_corruption_rejected(tmp_path, mutation):
    directory = tmp_path / "fixture"
    shutil.copytree(reference.DEFAULT_FIXTURES, directory)
    value = manifest()
    if mutation in ("hash", "reviewed-data"):
        path = directory / "scenarios.json"
        examples = reference.read_json(path.read_bytes())
        examples[0]["expected"]["values"][0][0] = 0
        path.write_bytes(reference.json_bytes(examples))
        if mutation == "reviewed-data":
            value["scenarios"]["sha256"] = fft.digest(path.read_bytes())
    elif mutation == "export-null":
        entry = value["exports"][0]
        path = directory / entry["file"]
        result = reference.read_json(path.read_bytes())
        result["channels"][-1]["rms_v"] = 0
        path.write_bytes(reference.json_bytes(result))
        entry["sha256"] = fft.digest(path.read_bytes())
    else:
        value["tones"][0]["metadata"]["channel_ids"].reverse()
    (directory / "manifest.json").write_bytes(reference.json_bytes(value))
    result = run_reference("verify", "--portable", "--fixtures", directory)
    assert result.returncode == 1, result.stdout + result.stderr


def test_generate_and_report_cannot_overwrite_saved_files(tmp_path):
    result = run_reference("generate", "--output", reference.DEFAULT_FIXTURES)
    assert result.returncode == 1 and "new directory" in result.stderr
    for target in [reference.DEFAULT_FIXTURES / "new-report.json", tmp_path / "exists.json"]:
        if target.parent == tmp_path:
            target.write_text("keep", encoding="utf-8")
        result = run_reference("verify", "--portable", "--report", target)
        assert result.returncode == 1 and "new file outside" in result.stderr


def test_tone_and_scenario_inventory_are_not_optional():
    for field in ("tones", "exports"):
        value = manifest()
        value[field].pop()
        with pytest.raises(fft.ReferenceError):
            reference.validate_manifest(value, portable=True)
