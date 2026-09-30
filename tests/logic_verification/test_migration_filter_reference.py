"""Independent anchors, continuity and fixture corruption checks for MIG-003-C."""

from copy import deepcopy
from fractions import Fraction
import shutil
import subprocess
import sys

import numpy as np
import pytest

from scripts import migration_core_reference as exchange
from scripts import migration_fft_reference as fft
from scripts import migration_filter_cases as cases
from scripts import migration_filter_oracle as oracle
from scripts import migration_filter_reference as reference


def manifest():
    return exchange.read_json((reference.DEFAULT_FIXTURES / "manifest.json").read_bytes())


def run(*args):
    return subprocess.run(  # noqa: S603 -- fixed local runner and test-owned paths
        [sys.executable, "scripts/migration_filter_reference.py", *map(str, args)],
        cwd=reference.ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


@pytest.mark.parametrize(
    "signal,expected", [("impulse-even", [0.25, 0.25, 0]), ("impulse-odd", [0, 0.5, 0]), ("dc", [0.0625, 0.25, 0.25])]
)
def test_hand_calculated_fir_anchors(signal, expected):
    spec = next(spec for spec in cases.specs() if spec["id"] == f"fir-{signal}")
    x = cases.make_input(spec)
    for pattern in oracle.CHUNKS.values():
        actual, reasons = oracle.stream_fir(x, [], pattern)
        np.testing.assert_array_equal(actual[:3, 0], expected)
        assert reasons == {"warmup": [[0, 1]], "gap": []}
    np.testing.assert_array_equal(oracle.fir_sum(x)[:3, 0], expected)


def test_exact_rate_trigger_and_gap_anchor():
    value = oracle.fir_metadata(1031, [[100, 104]])
    assert value["invalid_intervals"] == {"warmup": [[0, 1]], "gap": [[50, 53]]}
    assert oracle.map_position(1024, 48000, 24000) == 512
    assert oracle.map_position(1025, 48000, 24000) == Fraction(1025, 2)
    assert oracle.map_position(1, 48000, 24000) == Fraction(1, 2)
    assert oracle.map_position(Fraction(3, 2), 48000, 24000) == Fraction(3, 4)
    assert oracle.map_position(160, 48000, 44100) == 147
    assert value["output_interval"] == [0, 516]
    assert value["processing_latency_seconds"] is None


def test_random_gaps_partitions_channels_and_odd_ends_against_convolution():
    rng = np.random.default_rng(3003)
    for n in (5, 128, 129, 256, 1031):
        x = rng.normal(size=(n, 4))
        for gap_start in (0, 1, n // 2):
            gaps = [[gap_start, min(n - 1, gap_start + 2)]]
            observed = x.copy()
            observed[gaps[0][0] : gaps[0][1]] = 0
            expected = np.column_stack([np.convolve(channel, [0.25, 0.5, 0.25])[:n:2] for channel in observed.T])
            output, flags = oracle.stream_fir(x, gaps, [1, 7, 2, 31])
            np.testing.assert_allclose(output, expected, atol=1e-12, rtol=1e-12)
            np.testing.assert_allclose(oracle.fir_sum(x, gaps), expected, atol=1e-12, rtol=1e-12)
            missing = set(range(*gaps[0]))
            expected_flags = {m for m in range((n + 1) // 2) if set(range(2 * m - 2, 2 * m + 1)) & missing}
            actual_flags = {m for start, stop in flags["gap"] for m in range(start, stop)}
            assert actual_flags == expected_flags
            assert flags == oracle.fir_metadata(n, gaps)["invalid_intervals"]


def test_gap_values_cannot_affect_output_and_snapshot_is_owned():
    x = np.ones((257, 2))
    gaps = [[100, 104], [127, 130]]
    before, flags = oracle.stream_fir(x, gaps, [127])
    x[100:104] = 12345
    x[127:130] = -54321
    after, after_flags = oracle.stream_fir(x, gaps, [1])
    np.testing.assert_array_equal(before, after)
    assert flags == after_flags
    model = oracle.StreamingFir(2)
    block = np.ones((3, 2))
    published, _ = model.process(0, block)
    block[:] = 999
    following, _ = model.process(3, np.ones((2, 2)))
    np.testing.assert_array_equal(published, [[0.25, 0.25], [1, 1]])
    np.testing.assert_array_equal(following, [[1, 1]])


@pytest.mark.parametrize(
    "rates", [(0, 24000), (-1, 24000), (48000, 0), (48000, -1), (float("nan"), 24000), (48000, float("inf"))]
)
def test_new_contract_rejects_invalid_rate(rates):
    with pytest.raises(ValueError, match="invalid_rate"):
        oracle.StreamingFir(2, *rates)


def test_unsupported_rate_and_invalid_blocks_do_not_advance_state():
    with pytest.raises(ValueError, match="unsupported"):
        oracle.StreamingFir(2, 44100, 48000)
    model = oracle.StreamingFir(2)
    model.process(0, np.ones((3, 2)))
    for start, block in (
        (2, np.ones((2, 2))),
        (3, np.ones((2, 3))),
        (3, np.ones((0, 2))),
        (3, np.full((2, 2), np.nan)),
    ):
        with pytest.raises(ValueError):
            model.process(start, block)
        assert model.cursor == 3
    output, _ = model.process(3, np.ones((2, 2)))
    np.testing.assert_array_equal(output, [[1, 1]])


def test_polyphase_centering_with_hand_calculated_coefficients():
    x = np.array([[1.0], [0], [0]])
    h = np.array([0.25, 0.5, 0.25])
    np.testing.assert_array_equal(oracle.polyphase_sum(x, h, 2, 1).ravel(), [1, 0.5, 0, 0, 0, 0])
    np.testing.assert_array_equal(oracle.polyphase_sum(x, h, 1, 2).ravel(), [0.5, 0])
    for up, down in ((1, 2), (2, 1), (160, 147), (147, 160)):
        h = oracle.kaiser_coefficients(up, down)
        np.testing.assert_allclose(h, h[::-1], atol=1e-15)
        assert np.sum(h) == pytest.approx(1, abs=1e-15)


def test_sos_recurrence_anchors_and_dc_initial_conditions():
    sos = np.array([[0.5, 0, 0, 1, -0.5, 0]])
    impulse = np.zeros((8, 1))
    impulse[0] = 1
    output, state = oracle.sos_recurrence(impulse, sos)
    np.testing.assert_array_equal(output[:, 0], [0.5**n for n in range(1, 9)])
    np.testing.assert_array_equal(state, [[[0.5**9], [0]]])
    response = oracle.sos_response(sos, [0, 12000, 24000], 48000)
    np.testing.assert_allclose(response, [1, 0.4 - 0.2j, 1 / 3], atol=1e-15)
    dc = np.ones((128, 2))
    steady, _ = oracle.sos_recurrence(dc, sos, steady=True)
    np.testing.assert_array_equal(steady, dc)
    np.testing.assert_array_equal(oracle.sos_forward_backward(dc, sos), dc)


@pytest.mark.parametrize(
    "field",
    [
        "schema_version",
        "contract",
        "reference_commit",
        "source_sha256",
        "generator_sha256",
        "contract_sha256",
        "tolerances",
        "rate_cases",
    ],
)
def test_manifest_provenance_rejected_even_in_portable_mode(field):
    value = manifest()
    value[field] = "changed"
    with pytest.raises(fft.ReferenceError, match=field):
        reference.validate_manifest(value, portable=True)


def test_portable_mode_only_relaxes_environment():
    value = manifest()
    value["environment"]["python"] = "0.0"
    with pytest.raises(fft.ReferenceError, match="environment"):
        reference.validate_manifest(value)
    reference.validate_manifest(value, portable=True)
    value["cases"][0]["metadata"]["generation"] = 0.0
    with pytest.raises(fft.ReferenceError, match="metadata"):
        reference.validate_manifest(value, portable=True)


@pytest.mark.parametrize("change", ["spec", "missing", "duplicate", "channel_order", "warmup", "trigger", "null"])
def test_exact_cases_and_metadata(change):
    value = manifest()
    case = value["cases"][0]
    if change == "spec":
        case["spec"]["n"] += 1
    elif change == "missing":
        value["cases"].pop()
    elif change == "duplicate":
        value["cases"].append(deepcopy(case))
    elif change == "channel_order":
        case["metadata"]["channel_ids"].reverse()
    elif change == "warmup":
        case["metadata"]["invalid_intervals"]["warmup"] = []
    elif change == "trigger":
        case["metadata"]["trigger"]["output"] = [512.5, 1]
    else:
        case["metadata"]["processing_latency_seconds"] = 0
    with pytest.raises(fft.ReferenceError):
        reference.validate_manifest(value, portable=True)


@pytest.mark.parametrize(
    "field,value",
    [
        ("dtype", "<f4"),
        ("shape", [2, 1031]),
        ("origin", "theory"),
        ("file", "../input.bin"),
        ("complex", "real-imag-last-axis"),
        ("layout", "channel-major"),
        ("byte_order", "big"),
    ],
)
def test_array_schema_rejected(field, value):
    case = manifest()["cases"][0]
    case["arrays"]["input"][field] = value
    with pytest.raises(fft.ReferenceError, match="schema"):
        reference.load_case(reference.DEFAULT_FIXTURES, case)


@pytest.mark.parametrize("bad", ["hash", "nan", "truncated"])
def test_corrupt_fixture_bytes_rejected(tmp_path, bad):
    case = manifest()["cases"][0]
    target = tmp_path / case["spec"]["id"]
    shutil.copytree(reference.DEFAULT_FIXTURES / case["spec"]["id"], target)
    entry = case["arrays"]["input"]
    path = target / entry["file"]
    data = bytearray(path.read_bytes())
    if bad == "hash":
        data[0] ^= 255
    elif bad == "nan":
        data[:8] = np.array([np.nan], dtype="<f8").tobytes()
    else:
        data = data[:-8]
    path.write_bytes(data)
    if bad != "hash":
        entry["sha256"] = fft.digest(data)
    with pytest.raises(fft.ReferenceError):
        reference.load_case(tmp_path, case)


def test_cli_portable_verify_is_read_only_and_report_is_explicit(tmp_path):
    files = list(reference.DEFAULT_FIXTURES.rglob("*"))
    before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in files if path.is_file()}
    report = tmp_path / "report.json"
    result = run("verify", "--portable", "--report", report)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "21 cases, 6 rate cases" in result.stdout
    assert "no GUI/device imports" in result.stdout
    value = exchange.read_json(report.read_bytes())
    assert value["status"] == "pass"
    assert value["mode"] == "portable-comparison"
    assert len(value["cases"]) == 21
    assert all((path.read_bytes(), path.stat().st_mtime_ns) == snapshot for path, snapshot in before.items())
    assert run("verify", "--report", report).returncode == 1
    assert run("verify", "--report", reference.DEFAULT_FIXTURES / "forbidden.json").returncode == 1
    assert run("generate", "--output", reference.DEFAULT_FIXTURES).returncode == 1


def test_regeneration_matches_every_saved_byte(tmp_path):
    if manifest()["environment"] != reference.environment():
        pytest.skip(
            "Byte-identical regeneration requires the recorded reference environment; portable verification still runs"
        )
    output = tmp_path / "regenerated"
    result = run("generate", "--output", output)
    assert result.returncode == 0, result.stdout + result.stderr
    expected = {
        path.relative_to(reference.DEFAULT_FIXTURES): path.read_bytes()
        for path in reference.DEFAULT_FIXTURES.rglob("*")
        if path.is_file()
    }
    actual = {path.relative_to(output): path.read_bytes() for path in output.rglob("*") if path.is_file()}
    assert actual == expected


def test_finite_wrong_expectation_is_rejected_even_with_updated_hash(tmp_path):
    directory = tmp_path / "changed"
    shutil.copytree(reference.DEFAULT_FIXTURES, directory)
    value = manifest()
    case = value["cases"][0]
    entry = case["arrays"]["theory.output"]
    path = directory / case["spec"]["id"] / entry["file"]
    array = np.frombuffer(path.read_bytes(), dtype="<f8").copy()
    array[0] += 0.01
    path.write_bytes(array.tobytes())
    entry["sha256"] = fft.digest(path.read_bytes())
    (directory / "manifest.json").write_bytes(exchange.json_bytes(value))
    result = run("verify", "--portable", "--fixtures", directory)
    assert result.returncode == 1
    assert "numerical mismatch" in result.stderr
