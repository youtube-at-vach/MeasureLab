"""MIG-006-D: immutable FIR/polyphase/SOS bytes through graph-owned Rust state.

NumPy-only reader; no SciPy, Qt, devices, regenerated expectations or new dependencies.
The complete reviewed manifest is pinned, including schema, tolerances and provenance.
"""

from __future__ import annotations

import argparse
import copy
from fractions import Fraction
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import time
import tomllib

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import migration_core_reference as core  # noqa: E402
from scripts import migration_fft_candidate as candidate  # noqa: E402
from scripts import migration_fft_reference as fft  # noqa: E402

FIXTURES = ROOT / "migration/fixtures/filter-v1"
MANIFEST_SHA256 = "134dbba8301d52e585e0cb15abb550da6713c44c36a782df8bd299d0dfba1599"
CHUNKS = {"whole": [65536], "one": [1], "127": [127], "256": [256], "irregular": [3, 128, 1, 7, 256, 2]}


def rational(value):
    value = Fraction(value)
    return {"numerator": value.numerator, "denominator": value.denominator}


def load_manifest(*, portable=False, directory=FIXTURES):
    data = (directory / "manifest.json").read_bytes()
    if fft.digest(data) != MANIFEST_SHA256:
        raise fft.ReferenceError("Reviewed filter manifest changed (schema, provenance or tolerances)")
    manifest = json.loads(data)
    for section in ("source_sha256", "generator_sha256", "contract_sha256"):
        if core.hashes(tuple(manifest[section])) != manifest[section]:
            raise fft.ReferenceError(f"Filter {section} mismatch")
    if not portable:
        env = fft.environment()
        env["fft"] = {"backend": "numpy", "use": "polyphase output peak-frequency diagnostic only"}
        if core.json_bytes(env) != core.json_bytes(manifest["environment"]):
            raise fft.ReferenceError(
                "Pinned filter environment mismatch; use explicit --portable for another environment"
            )
    # Every saved array, including expectations unused by an individual transform, is checked.
    for case in manifest["cases"]:
        for entry in case["arrays"].values():
            fft.read_array(directory / case["spec"]["id"], entry)
    return manifest


def build():
    native = ROOT / "native"
    env = candidate.cargo_environment()
    version = tomllib.loads((native / "rust-toolchain.toml").read_text())["toolchain"]["channel"]
    record = candidate.run_command(
        [
            candidate.rust_tool("cargo", env),
            f"+{version}",
            "build",
            "--offline",
            "--locked",
            "--manifest-path",
            str(native / "Cargo.toml"),
            "--target-dir",
            str(native / "target"),
            "-p",
            "graph-core",
            "--bin",
            "filter-candidate",
        ],
        env=env,
    )
    return native / "target/debug" / ("filter-candidate.exe" if os.name == "nt" else "filter-candidate"), record


def request_for(case, *, acquisition=False):
    spec, meta = case["spec"], case["metadata"]
    coefficients = fft.read_array(FIXTURES / spec["id"], case["arrays"]["coefficients"])
    config = {
        "kind": "Sos" if spec["kind"] == "sos" else "Fir",
        "coefficients": coefficients.tolist(),
        "revision": "saved-sos-v1"
        if spec["kind"] == "sos"
        else "saved-poly-v1"
        if spec["kind"] == "poly"
        else "causal-3tap-v1",
    }
    if spec["kind"] != "sos":
        config.update(target_rate=rational(spec["target_rate"]), centered=spec["kind"] == "poly")
    source = {
        "stream_id": "fixture.input",
        "generation": 0,
        "channel_ids": list(meta["channel_ids"]),
        "precision": "F64",
        "timebase": {
            "id": f"fixture.clock.{spec['source_rate']}",
            "revision": 0,
            "clock_domain": "fixture.virtual",
            "generation": 0,
            "rate": rational(spec["source_rate"]),
            "nominal_rate": rational(spec["source_rate"]),
            "origin_sample": 0,
            "origin_seconds": None,
            "origin_kind": "virtual",
            "uncertainty_seconds": None,
        },
        "route_revision": "identity-v1",
        "tap": "InputRaw",
        "filter_state_revision": "none",
        "calibration_revision": "uncalibrated-FS",
    }
    if acquisition:
        source["route_revision"] = "input-physical-binding"
        source["calibration_revision"] = "none"
        source["timebase"]["origin_kind"] = "backend-unverified"
    frequencies = (
        fft.read_array(FIXTURES / spec["id"], case["arrays"]["frequency_hz"]).tolist() if spec["kind"] == "sos" else []
    )
    return {
        "schema_version": 1,
        "source": source,
        "output_stream": f"fixture.{spec['kind']}",
        "output_timebase": f"fixture.{spec['kind']}.clock.{spec['target_rate']}",
        "config": config,
        "frames": spec["n"],
        "gaps": copy.deepcopy(spec["gaps"]),
        "chunks": copy.deepcopy(CHUNKS),
        "trigger": rational(1024),
        "frequencies": frequencies,
    }


def expected_metadata(request):
    source, config = request["source"], request["config"]
    target = config.get("target_rate", source["timebase"]["rate"])

    def as_fraction(r):
        return Fraction(r["numerator"], r["denominator"])

    rate = as_fraction(source["timebase"]["rate"])
    ratio = as_fraction(target) / rate
    output = copy.deepcopy(source)
    conversion = request.get("input_conversion")
    if conversion is not None:
        if conversion != "F32ToF64Exact" or source["precision"] != "F32":
            raise fft.ReferenceError("Unsupported explicit filter input conversion")
        output["precision"] = "F64"
    output["stream_id"] = request["output_stream"]
    output["timebase"]["id"] = request["output_timebase"]
    output["timebase"]["rate"] = target
    output["timebase"]["nominal_rate"] = target
    coefficients = np.asarray(config["coefficients"]).flat
    bits = "".join(f"{struct.unpack('<Q', struct.pack('<d', float(v)))[0]:016x}" for v in coefficients)
    centered = config.get("centered", False)
    output["filter_state_revision"] = (
        f"{source['filter_state_revision']}{'/f32-to-f64-exact-v1' if conversion else ''}"
        f"/{config['kind'].lower()}:{config['revision']}:{ratio.numerator}:{ratio.denominator}:{str(centered).lower()}:{bits}"
    )
    delay = Fraction(len(config["coefficients"]) - 1, 2 * ratio.numerator) if config["kind"] == "Fir" else None
    metadata = {
        "parent": source,
        "output": output,
        "rate_ratio": rational(ratio),
        "output_m_to_input": rational(1 / ratio),
        "origin_mapping": [rational(0), rational(0)],
        "signal_delay_input_samples": rational(delay) if delay is not None else None,
        "signal_delay_output_samples": rational(delay * ratio) if delay is not None else None,
        "signal_delay_seconds": rational(delay / rate) if delay is not None else None,
        "delay_compensated": centered,
        "processing_latency_seconds": None,
        "processing_latency_reason": "not_measured",
        "initial_state": "zero-padding-with-validity"
        if config["kind"] == "Fir"
        else "zero-state-transient-no-valid-after-cutoff",
        "tail_flush": False,
    }
    if conversion is not None:
        metadata["input_conversion"] = conversion
    return metadata


def spans_for(request):
    config = request["config"]
    if config["kind"] == "Sos":
        return [
            {
                "start": 0,
                "end": request["frames"],
                "channel_id": None,
                "reason": "warmup",
                "origin": "sos.zero-state-transient",
            }
        ]
    source_rate = request["source"]["timebase"]["rate"]["numerator"]
    target_rate = config["target_rate"]["numerator"]
    ratio = Fraction(target_rate, source_rate)
    up, down = ratio.numerator, ratio.denominator
    count = (request["frames"] * up + down - 1) // down
    centers = np.arange(count) * down + ((len(config["coefficients"]) - 1) // 2 if config["centered"] else 0)
    first = (centers - len(config["coefficients"]) + up) // up  # ceil of the first support index
    last = centers // up
    masks = [("warmup", "filter.endpoint-padding", (first < 0) | (last >= request["frames"]))]
    missing = np.zeros(count, dtype=bool)
    for start, end in request["gaps"]:
        missing |= (last >= start) & (first < end)
    masks.append(("gap", "filter.input-missing", missing))
    result = []
    for reason, origin, mask in masks:
        transitions = np.diff(np.r_[False, mask, False].astype(int))
        for start, end in zip(np.flatnonzero(transitions == 1), np.flatnonzero(transitions == -1), strict=True):
            result.append(
                {"start": int(start), "end": int(end), "channel_id": None, "reason": reason, "origin": origin}
            )
    return normalize_spans(result, count)


def normalize_spans(spans, count):
    if not isinstance(spans, list):
        raise fft.ReferenceError("Validity must be a list")
    for s in spans:
        if (
            not isinstance(s, dict)
            or set(s) != {"start", "end", "channel_id", "reason", "origin"}
            or type(s["start"]) is not int
            or type(s["end"]) is not int
            or not 0 <= s["start"] < s["end"] <= count
            or s["channel_id"] is not None
            or not isinstance(s["reason"], str)
            or not isinstance(s["origin"], str)
        ):
            raise fft.ReferenceError("Validity shape, channel or position mismatch")
    result = []
    for s in sorted(spans, key=lambda s: (s["reason"], s["origin"], s["start"], s["end"])):
        if (
            result
            and result[-1]["reason"] == s["reason"]
            and result[-1]["origin"] == s["origin"]
            and result[-1]["end"] >= s["start"]
        ):
            result[-1]["end"] = max(result[-1]["end"], s["end"])
        else:
            result.append(s.copy())
    return result


def validate_header(header, request, *, acquisition=False):
    meta = expected_metadata(request)
    ratio = meta["rate_ratio"]
    count = (request["frames"] * ratio["numerator"] + ratio["denominator"] - 1) // ratio["denominator"]
    if not isinstance(header, dict) or set(header) != {
        "schema_version",
        "metadata",
        "trigger_output",
        "output_interval",
        "runs",
        "arrays",
    }:
        raise fft.ReferenceError("Filter manifest fields mismatch")
    for key, expected in {
        "schema_version": 1,
        "metadata": meta,
        "trigger_output": rational(Fraction(1024) * Fraction(ratio["numerator"], ratio["denominator"])),
        "output_interval": [0, count],
    }.items():
        if core.json_bytes(header[key]) != core.json_bytes(expected):
            raise fft.ReferenceError(f"Filter {key} mismatch")
    if not isinstance(header["runs"], dict) or set(header["runs"]) != set(request["chunks"]):
        raise fft.ReferenceError("Filter chunk inventory mismatch")
    expected_spans = spans_for(request)
    for run in header["runs"].values():
        fields = {
            "validity",
            "windows",
            "before_release",
            "after_release",
            "after_shutdown",
            "filters_before",
            "filters_released",
            "filters_after",
        }
        if acquisition:
            fields.add("acquisition")
        if not isinstance(run, dict) or set(run) != fields:
            raise fft.ReferenceError("Filter run fields mismatch")
        if acquisition:
            validate_acquisition(run["acquisition"], request)
        if normalize_spans(run["validity"], count) != expected_spans:
            raise fft.ReferenceError("Filter support/gap/warmup mismatch")
        if core.json_bytes(
            [run[k] for k in ("filters_before", "filters_released", "filters_after")]
        ) != core.json_bytes([1, 0, 0]):
            raise fft.ReferenceError("Filter state not released")
        windows = run["windows"]
        if not isinstance(windows, list) or len(windows) != count // 64:
            raise fft.ReferenceError("Filtered FFT window count mismatch")
        evaluations, average, seen, graph_id = 0, 0, set(), None
        for i, window in enumerate(windows):
            start, end = i * 64, (i + 1) * 64
            if not isinstance(window, dict) or set(window) != {
                "interval",
                "result_id",
                "second_result_id",
                "shared_allocation",
                "validity",
                "numeric",
                "average_count",
            }:
                raise fft.ReferenceError("Filtered FFT proof fields mismatch")
            clipped = normalize_spans(
                [
                    {**s, "start": max(start, s["start"]), "end": min(end, s["end"])}
                    for s in expected_spans
                    if s["start"] < end and s["end"] > start
                ],
                count,
            )
            numeric = not clipped
            average = average + 1 if numeric else 0
            evaluations += int(numeric)
            for key, value in {
                "interval": [start, end],
                "shared_allocation": True,
                "numeric": numeric,
                "average_count": average,
            }.items():
                if core.json_bytes(window[key]) != core.json_bytes(value):
                    raise fft.ReferenceError("Filtered FFT interval, sharing or average reset mismatch")
            if normalize_spans(window["validity"], count) != clipped:
                raise fft.ReferenceError("Filtered FFT lost validity")
            rid = window["result_id"]
            if (
                not isinstance(rid, dict)
                or set(rid) != {"graph", "serial"}
                or any(type(v) is not int or v <= 0 for v in rid.values())
                or core.json_bytes(window["second_result_id"]) != core.json_bytes(rid)
            ):
                raise fft.ReferenceError("Filtered FFT identity mismatch")
            if rid["serial"] in seen or (graph_id is not None and rid["graph"] != graph_id):
                raise fft.ReferenceError("Filtered FFT reused identity")
            seen.add(rid["serial"])
            graph_id = rid["graph"]
        for phase in ("before_release", "after_release", "after_shutdown"):
            stats = run[phase]
            if (
                not isinstance(stats, dict)
                or set(stats)
                != {
                    "nodes",
                    "subscriptions",
                    "in_flight",
                    "cache_results",
                    "cache_numeric_bytes",
                    "fft_evaluations",
                    "display_replacements",
                }
                or any(type(v) is not int or v < 0 for v in stats.values())
            ):
                raise fft.ReferenceError("Graph stats types/fields mismatch")
            expected = {
                "nodes": 1 if phase == "before_release" else 0,
                "subscriptions": 2 if phase == "before_release" else 0,
                "in_flight": 0,
                "fft_evaluations": evaluations,
                "display_replacements": 0,
            }
            if any(stats[k] != v for k, v in expected.items()):
                raise fft.ReferenceError("Filtered graph evaluation or resource count mismatch")
            if phase != "before_release" and (stats["cache_results"] != 0 or stats["cache_numeric_bytes"] != 0):
                raise fft.ReferenceError("Filtered graph retained cache")
            if phase == "before_release" and (
                stats["cache_results"] != min(8, count // 64) or stats["cache_numeric_bytes"] > 64 * 1024**2
            ):
                raise fft.ReferenceError("Filtered graph cache bound mismatch")
    shapes = {f"{name}.output": [count, len(request["source"]["channel_ids"])] for name in request["chunks"]}
    if acquisition and request["source"]["precision"] == "F32":
        acquired = request["frames"] - sum(end - start for start, end in request["gaps"])
        shapes.update(
            {f"{name}.raw_f32_as_f64": [acquired, len(request["source"]["channel_ids"])] for name in request["chunks"]}
        )
    for name, run in header["runs"].items():
        if any(w["numeric"] for w in run["windows"]):
            shapes[f"{name}.fft_over_n"] = [33, len(request["source"]["channel_ids"]), 2]
    if request["config"]["kind"] == "Sos":
        shapes.update({f"{name}.state": [4, 2, 2] for name in request["chunks"]})
        shapes.update({"offline.output": [count, 2], "response": [len(request["frequencies"]), 2]})
    arrays = {
        name: {"file": f"{name}.bin", "values": int(np.prod(shape)), "dtype": "<f8"} for name, shape in shapes.items()
    }
    if core.json_bytes(header["arrays"]) != core.json_bytes(arrays):
        raise fft.ReferenceError("Filter array shape/dtype mismatch")
    return shapes


def validate_acquisition(evidence, request):
    fields = {
        "acquired_frames",
        "gaps",
        "max_deliveries",
        "max_raw_windows",
        "max_filtered_windows",
        "history_released",
        "queue_released",
        "state",
    }
    if not isinstance(evidence, dict) or set(evidence) != fields:
        raise fft.ReferenceError("Acquisition proof fields mismatch")
    expected = {
        "acquired_frames": request["frames"] - sum(end - start for start, end in request["gaps"]),
        "gaps": request["gaps"],
        "history_released": True,
        "queue_released": True,
        "state": "Stopped",
    }
    if any(core.json_bytes(evidence[k]) != core.json_bytes(v) for k, v in expected.items()):
        raise fft.ReferenceError("Acquisition positions, gaps or resource release mismatch")
    for key, maximum in {"max_deliveries": 8192, "max_raw_windows": 1, "max_filtered_windows": 1}.items():
        if type(evidence[key]) is not int or not 0 < evidence[key] <= maximum:
            raise fft.ReferenceError("Acquisition poll budget mismatch")


def read_result(directory, request, *, acquisition=False):
    header = json.loads((directory / "manifest.json").read_bytes())
    shapes = validate_header(header, request, acquisition=acquisition)
    arrays, hashes = {}, {}
    for name, shape in shapes.items():
        raw = (directory / f"{name}.bin").read_bytes()
        if len(raw) != int(np.prod(shape)) * 8:
            raise fft.ReferenceError("Filter output byte count mismatch")
        arrays[name] = np.frombuffer(raw, dtype="<f8").reshape(shape)
        if not np.isfinite(arrays[name]).all():
            raise fft.ReferenceError("Nonfinite filter output")
        hashes[name] = fft.digest(raw)
    return arrays, hashes, header


def verify_case(binary, case, tolerances, *, acquisition=False):
    request = request_for(case, acquisition=acquisition)
    folder = FIXTURES / case["spec"]["id"]
    with tempfile.TemporaryDirectory(prefix="migration-filter-candidate-") as temp:
        temp = Path(temp)
        path = temp / "request.json"
        fft.write_json(path, request)
        command = [
            str(binary),
            *(["--acquisition"] if acquisition else []),
            str(path),
            str(folder / "input.bin"),
            str(temp / "output"),
        ]
        record = candidate.run_command(command)
        if fft.digest((folder / "input.bin").read_bytes()) != case["arrays"]["input"]["sha256"]:
            raise fft.ReferenceError("Candidate changed original filter input")
        arrays, hashes, header = read_result(temp / "output", request, acquisition=acquisition)
        comparisons = {}
        kind = case["spec"]["kind"]
        for name, array in arrays.items():
            if name.endswith(".fft_over_n"):
                run = header["runs"][name.removesuffix(".fft_over_n")]
                start, end = next(w["interval"] for w in run["windows"] if w["numeric"])
                # Independent FFT of the immutable filtered reference for this exact interval.
                expected = fft.read_array(folder, case["arrays"]["theory.output"])[start:end]
                observed = array[..., 0] + 1j * array[..., 1]
                comparisons[f"{name}:theory"] = fft.compare(
                    observed, np.fft.rfft(expected, axis=0) / 64, fft.TOLERANCES["f64"], "filtered shared FFT"
                )
                continue
            if name == "response":
                array = array[:, 0] + 1j * array[:, 1]
            key = (
                "response"
                if name == "response"
                else "final_state"
                if name.endswith(".state")
                else "causal"
                if kind == "sos" and name != "offline.output"
                else "output"
            )
            for origin in ("theory", "model") if kind == "fir" else ("theory", "current"):
                expected = fft.read_array(folder, case["arrays"][f"{origin}.{key}"])
                comparisons[f"{name}:{origin}"] = fft.compare(
                    array, expected, tolerances[kind], f"{case['spec']['id']} {name} {origin}"
                )
            if name.endswith(".output") and name != "offline.output":
                # Same algorithm/state yields byte-identical output across chunk boundaries.
                if hashes[name] != hashes["whole.output"]:
                    raise fft.ReferenceError("Filter chunk phase/state differs from whole input")
    return {
        "id": case["spec"]["id"],
        "input_sha256": case["arrays"]["input"]["sha256"],
        "output_sha256": hashes,
        "comparisons": comparisons,
        "graph": header,
        "command": record,
    }


def source_hashes():
    native = ROOT / "native"
    paths = [
        native / p
        for p in (
            "Cargo.toml",
            "Cargo.lock",
            "rust-toolchain.toml",
            "graph-core/Cargo.toml",
            "dsp-core/Cargo.toml",
            "audio-core/Cargo.toml",
        )
    ]
    paths += [
        *sorted((native / "graph-core").rglob("*.rs")),
        *sorted((native / "dsp-core").rglob("*.rs")),
        *sorted((native / "audio-core").rglob("*.rs")),
    ]
    return {str(p.relative_to(native)): fft.digest(p.read_bytes()) for p in paths}


RUNNERS = (
    "scripts/migration_filter_candidate.py",
    "scripts/migration_fft_candidate.py",
    "scripts/migration_fft_reference.py",
    "scripts/migration_core_reference.py",
)


def verify(*, portable=False, acquisition=False):
    started = time.perf_counter()
    manifest = load_manifest(portable=portable)
    source = source_hashes()
    runners = core.hashes(RUNNERS)
    binary, build_record = build()
    binary_hash = fft.digest(binary.read_bytes())
    with tempfile.TemporaryDirectory(prefix="migration-filter-rates-") as temp:
        temp = Path(temp)
        request, output = temp / "request.json", temp / "output.json"
        fft.write_json(request, {"schema_version": 1, "rates": [r["rates"] for r in manifest["rate_cases"]]})
        rate_command = candidate.run_command([str(binary), "--rates", str(request), str(output)])
        rates = json.loads(output.read_bytes())
        expected = [
            {
                "status": r["contract"],
                "ratio": rational(Fraction(r["rates"][1], r["rates"][0]))
                if r["contract"] == "valid_rate_pair"
                else None,
            }
            for r in manifest["rate_cases"]
        ]
        if core.json_bytes(rates) != core.json_bytes(expected):
            raise fft.ReferenceError("Rate validation differs from saved contract")
    corpus = [verify_case(binary, case, manifest["tolerances"], acquisition=acquisition) for case in manifest["cases"]]
    fft.assert_headless()
    if source_hashes() != source or core.hashes(RUNNERS) != runners or fft.digest(binary.read_bytes()) != binary_hash:
        raise fft.ReferenceError("Source, runner or executable changed during filter comparison")
    return {
        "schema_version": 1,
        "task": "MIG-006-D-integration" if acquisition else "MIG-006-D",
        "status": "pass",
        "mode": "portable" if portable else "pinned-reference",
        "fixture_manifest_sha256": MANIFEST_SHA256,
        "environment": fft.environment(),
        "binary_sha256": binary_hash,
        "source_sha256": source,
        "runner_sha256": runners,
        "build": build_record,
        "rate_command": rate_command,
        "rates": rates,
        "corpus": corpus,
        "elapsed_seconds": time.perf_counter() - started,
        "limitations": [
            "f64 saved coefficients; no production filter selection or f32 filter validation",
            "Single f64 worker transform stage; Qt integration and performance acceptance unverified",
            "Queue-backed acquisition scheduler exercised"
            if acquisition
            else "Pure filter only; acquisition scheduler not exercised",
            "SOS zero-state transient remains warmup; gaps/invalid input explicitly unsupported",
            "Forward/backward SOS is a bounded offline adapter, never restarted per streaming chunk",
            "Processing latency unknown; other OS, long runs and physical audio unverified",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--portable", action="store_true")
    parser.add_argument(
        "--acquisition", action="store_true", help="Compare through the actual queue/history/FFT acquisition owner"
    )
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if args.report:
        report = args.report.resolve()
        if report.exists() or report.is_relative_to((ROOT / "migration/fixtures").resolve()):
            parser.error("Report must be new and outside fixtures")
        report.parent.mkdir(parents=True, exist_ok=True)
    try:
        result = verify(portable=args.portable, acquisition=args.acquisition)
        if args.report:
            fft.write_json(args.report, result)
        print(
            f"Filter candidate OK: {len(result['corpus'])} saved cases × 5 chunks, {len(result['rates'])} rate boundaries"
        )
        return 0
    except (fft.ReferenceError, OSError, ValueError, subprocess.TimeoutExpired) as error:
        print(f"Filter candidate failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
