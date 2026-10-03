"""MIG-006-D: explicit filter -> both Qt views/derived Trigger/immutable saves.

Original fixtures stay unchanged. Expected finite sums and NumPy FFT arrays remain
in this runner. BlackHole requires explicit opt-in; no implicit build or fallback.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import platform
import re
import subprocess
import sys
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import migration_audio_graph as audio  # noqa: E402
from scripts import migration_fft_candidate as candidate  # noqa: E402
from scripts import migration_fft_reference as fft  # noqa: E402
from scripts import migration_qt_calibration as calibration  # noqa: E402
from scripts import migration_qt_calibration_edit as calibration_edit  # noqa: E402
from scripts import migration_qt_save as saving  # noqa: E402
from scripts import migration_qt_trigger as trigger_ui  # noqa: E402
from scripts import migration_trigger_candidate as trigger  # noqa: E402
from scripts.migration_qt_display import inspect_png, plot_regions, projection_for, qt_environment  # noqa: E402
from scripts.migration_qt_probe import sha256  # noqa: E402
from scripts.migration_qt_workspace import LANGUAGES  # noqa: E402

FIR_TOLERANCE = audio.core.read_json((ROOT / "migration/fixtures/filter-v1/manifest.json").read_bytes())["tolerances"][
    "fir"
]


def expected_metadata(request, generation):
    parent = deepcopy(audio.expected_source({**request, "format": {**request["format"], "generation": generation}}))
    source = deepcopy(parent)
    source["precision"] = "F64"
    source["stream_id"] += ".fir"
    source["timebase"]["id"] += ".fir"
    for field in ("rate", "nominal_rate"):
        source["timebase"][field] = dict(numerator=24000, denominator=1)
    source["filter_state_revision"] = (
        "none/"
        + ("f32-to-f64-exact-v1/" if request["precision"] == "F32" else "")
        + "fir:causal-3tap-v1:1:2:false:3fd00000000000003fe00000000000003fd0000000000000"
    )
    metadata = dict(
        parent=parent,
        output=source,
        rate_ratio=dict(numerator=1, denominator=2),
        output_m_to_input=dict(numerator=2, denominator=1),
        origin_mapping=[dict(numerator=0, denominator=1)] * 2,
        signal_delay_input_samples=dict(numerator=1, denominator=1),
        signal_delay_output_samples=dict(numerator=1, denominator=2),
        signal_delay_seconds=dict(numerator=1, denominator=48000),
        delay_compensated=False,
        processing_latency_seconds=None,
        processing_latency_reason="not_measured",
        initial_state="zero-padding-with-validity",
        tail_flush=False,
    )
    if request["precision"] == "F32":
        metadata["input_conversion"] = "F32ToF64Exact"
    return metadata


def finite_sum(samples, interval, *, origin=0, periodic=False):
    """Independent causal y[m]=sum(h[k]*x[2m-k]); only true start uses zero padding."""
    samples = np.asarray(samples, dtype=np.float64)
    positions = 2 * np.arange(*interval)
    result = np.zeros((len(positions), samples.shape[1]))
    for k, coefficient in enumerate((0.25, 0.5, 0.25)):
        indices = positions - k
        present = indices >= 0
        relative = indices[present] - origin
        if periodic:
            relative %= len(samples)
        elif np.any(relative < 0) or np.any(relative >= len(samples)):
            raise fft.ReferenceError("missing parent filter support")
        result[present] += coefficient * samples[relative]
    return result


def parent_samples(stem, request, interval, generation):
    metadata = audio.core.read_json(stem.with_suffix(".parent.json").read_bytes())
    raw = stem.with_suffix(".parent.f32").read_bytes()
    support = [max(0, 2 * interval[0] - 2), 2 * interval[1]]
    channels = len(request["format"]["input_ids"])
    trigger.exact(
        metadata,
        dict(
            source=expected_metadata(request, generation)["parent"],
            interval=support,
            byte_count=(support[1] - support[0]) * channels * 4,
        ),
        "parent evidence binding",
    )
    if len(raw) != metadata["byte_count"]:
        raise fft.ReferenceError("parent evidence bytes")
    values = np.frombuffer(raw, dtype="<f4").reshape(-1, channels)
    if not np.all(np.isfinite(values)):
        raise fft.ReferenceError("parent evidence nonfinite")
    return finite_sum(values, interval, origin=support[0])


def validate_result(document, request, samples, *, receipt=None):
    generation = document["source"]["generation"]
    metadata = expected_metadata(request, generation)
    trigger.exact(document["source"], metadata["output"], "derived source")
    trigger.exact(document["conditions"]["filter"], metadata, "filter provenance")
    baseline = deepcopy(document)
    del baseline["conditions"]["filter"]
    # The existing numeric oracle assumes input.raw. Normalize only identity that
    # was independently checked above; preserve every numeric value and profile.
    derived = {
        **request,
        "precision": "F64",
        "format": {
            **request["format"],
            "generation": generation,
            "stream_id": metadata["output"]["stream_id"],
            "timebase_id": metadata["output"]["timebase"]["id"],
            "rate": [24000, 1],
        },
    }
    normalized = audio.expected_source(derived)
    baseline["source"] = baseline["conditions"]["source"] = normalized
    read = None
    if receipt is not None:
        rid = document["raw_result_id"]
        read = dict(
            history=receipt["history"],
            raw_result_id=dict(graph=rid[0], serial=rid[1]),
            result_id=document["capture"]["result_id"],
            event=receipt["request"]["event"],
        )
    return calibration.validate_result(
        baseline,
        derived,
        samples,
        {"spec": {"rate_hz": 24000, "window": "hann" if request["window"] == "SymmetricHann" else "boxcar"}},
        read=read,
    )


def validate_run(output, directory, request, original, codec):
    records = re.findall(r"FILTER_DISPLAY (.+)", output)
    if len(records) != 1:
        raise fft.ReferenceError("missing filter UI evidence")
    record = audio.core.read_json(records[0])
    for key in ("normal_saved", "pending", "shared_hold", "trigger_saved", "gap", "restart", "recreate", "buttons_fit"):
        if record.get(key) is not True:
            raise fft.ReferenceError("incomplete filter UI lifecycle: " + key)
    if (
        type(record["blocked_gui_fft"]) is not int
        or record["blocked_gui_fft"] < 2
        or record["minimum"][0] > 1180
        or record["minimum"][1] > 690
    ):
        raise fft.ReferenceError("filter UI progress or size")
    evidence, saves = directory / "results", directory / "saves"
    paths = sorted(evidence.glob("generation-*.json"))
    if len(paths) != 2:
        raise fft.ReferenceError("missing filter restart generations")
    generations = [audio.core.read_json(p.read_bytes())["source"]["generation"] for p in paths]
    if not 0 < generations[0] < generations[1]:
        raise fft.ReferenceError("filter generations")
    archives = {}
    if original is None:
        channels = len(request["format"]["input_ids"])
        for generation in generations:
            stem = evidence / f"filter-raw-{generation}"
            archive = audio.core.read_json(stem.with_suffix(".json").read_bytes())
            raw = stem.with_suffix(".f32").read_bytes()
            end = archive["interval"][1]
            trigger.exact(
                archive,
                dict(
                    format={**request["format"], "generation": generation},
                    interval=[0, end],
                    byte_count=end * channels * 4,
                    max_bytes=32 * 1024 * 1024,
                ),
                "raw filter archive",
            )
            if len(raw) != archive["byte_count"] or len(raw) > archive["max_bytes"] or end < 4096:
                raise fft.ReferenceError("live raw archive capacity or coverage")
            values = np.frombuffer(raw, dtype="<f4").reshape(end, channels)
            if not np.all(np.isfinite(values)):
                raise fft.ReferenceError("live raw nonfinite")
            peaks = np.abs(np.fft.rfft(values[:4096].astype(float), axis=0)) * 2 / 4096
            bins = [37, 71, 113, 173, 251, 331, 419, 509][:channels]
            if peaks.argmax(axis=0).tolist() != bins or not np.allclose(
                peaks[bins, np.arange(channels)], np.arange(1, channels + 1) / 32, atol=1e-7, rtol=0
            ):
                raise fft.ReferenceError("live selected port/tone/amplitude mismatch")
            archives[generation] = values
    receipt = record["trigger"]
    bound = {**request, "format": {**request["format"], "generation": generations[0]}}
    metadata = expected_metadata(request, generations[0])
    derived = {
        **bound,
        "format": {
            **bound["format"],
            "stream_id": metadata["output"]["stream_id"],
            "timebase_id": metadata["output"]["timebase"]["id"],
        },
    }
    trigger_ui.validate_receipt(receipt, derived)
    captures = {}
    for path in evidence.glob(f"trigger-{generations[0]}-*.json"):
        if path.name.endswith((".result.json", ".parent.json")):
            continue
        observed = audio.core.read_json(path.read_bytes())
        trigger_ui.validate_receipt(observed, derived)
        captures[observed["revision"], observed["status"]] = observed
        if observed["status"] != "complete" and path.with_suffix(".result.json").exists():
            raise fft.ReferenceError("pending/gap contains saved numbers")
    if set(captures) != {(1, "pending"), (1, "complete"), (2, "complete"), (3, "gap")}:
        raise fft.ReferenceError("filter pending/retry/shared/gap inventory")
    trigger.exact(captures[1, "pending"]["request"], captures[1, "complete"]["request"], "explicit retry")
    if (
        captures[1, "complete"]["frame"]["raw_result_id"] != receipt["frame"]["raw_result_id"]
        or captures[2, "complete"]["trigger_evaluations"] != captures[1, "complete"]["trigger_evaluations"]
    ):
        raise fft.ReferenceError("filter trigger FFT not shared")
    comparisons = []
    for revision in (1, 2):
        capture = captures[revision, "complete"]
        stem = evidence / f"trigger-{generations[0]}-{revision}-complete"
        document = audio.core.read_json(stem.with_suffix(".result.json").read_bytes())
        samples = (
            parent_samples(stem, request, document["interval"], generations[0])
            if original is None
            else finite_sum(original, document["interval"], periodic=True)
        )
        actual = np.frombuffer(stem.with_suffix(".bin").read_bytes(), dtype="<f8").reshape(request["n"], -1)
        fft.compare(actual, samples, FIR_TOLERANCE, "derived trigger independent finite sum")
        trigger.exact(capture["frame"], projection_for(document), "trigger projection")
        comparisons.append(validate_result(document, request, samples, receipt=capture))
    names = [
        f"{kind}{suffix}"
        for kind in ("normal", "trigger")
        for suffix in (".json", ".csv", ".product.json", ".product.csv")
    ]
    frames = [record["normal"]] * 4 + [receipt["frame"]] * 4
    if len(record["receipts"]) != len(names):
        raise fft.ReferenceError("missing filter save receipts")
    for index, (receipt_record, frame, name) in enumerate(zip(record["receipts"], frames, names, strict=True), 1):
        expected_format = ("product_" if ".product." in name else "") + Path(name).suffix[1:]
        for field, value in dict(
            operation_id=index,
            destination=str(saves.resolve() / name),
            format=expected_format,
            result_id=frame["result_id"],
            generation=frame["source"]["generation"],
            interval=frame["interval"],
        ).items():
            trigger.exact(receipt_record[field], value, "filter save receipt " + field)
        if receipt_record["status"] != {"state": "saved"}:
            raise fft.ReferenceError("filter save not complete")
    documents = []
    for index, name in enumerate(names):
        document = saving.read_document(saves / name, product=".product." in name, codec=codec)
        calibration_edit.exact_qml(frames[index], projection_for(document), "pinned full result")
        documents.append(document)
        if index % 4:
            trigger.exact(document, documents[index - index % 4], "four formats keep identical snapshot")
        elif original is not None:
            comparisons.append(
                validate_result(
                    document,
                    request,
                    finite_sum(original, document["interval"], periodic=True),
                    receipt=receipt if index == 4 else None,
                )
            )
        else:
            comparisons.append(
                validate_result(
                    document,
                    request,
                    finite_sum(archives[generations[0]], document["interval"]),
                    receipt=receipt if index == 4 else None,
                )
            )
    for path in paths:
        document = audio.core.read_json(path.read_bytes())
        trigger.exact(
            document["conditions"]["filter"],
            expected_metadata(request, document["source"]["generation"]),
            "first window metadata",
        )
        trigger.exact(document["interval"], [0, request["n"]], "first window interval")
        trigger.exact(
            document["validity"],
            [dict(start=0, end=1, channel_id=None, reason="warmup", origin="filter.endpoint-padding")],
            "first window warmup",
        )
        if document["error"] is not None or any(v is not None for v in document["columns"]["peak_fs"]["values"]):
            raise fft.ReferenceError("filter warmup fabricated normal numbers")
    if original is None:
        for generation in generations:
            metrics = audio.core.read_json((evidence / f"live-{generation}.json").read_bytes())
            if (
                metrics["error"] is not None
                or not metrics["reclaimed"]
                or metrics["backend"] != request["live"]["backend"]
                or metrics["captured_frames"] != len(archives[generation])
                or metrics["queue"]["max_depth_frames"] > metrics["queue"]["capacity_frames"]
            ):
                raise fft.ReferenceError("live filter gap/failure/reclamation")
            backend = metrics["input"]
            if not backend["closed"] or any(backend[key] for key in ("errors", "xruns", "rejected")):
                raise fft.ReferenceError("live filter backend lifetime")
            if request["live"]["backend"] == "PortAudio" and (
                not backend["terminated"] or backend["reported_rate"] != 48000
            ):
                raise fft.ReferenceError("PortAudio filter clock/lifetime")
            document = audio.core.read_json((evidence / f"generation-{generation}.json").read_bytes())
            samples = parent_samples(evidence / f"input-{generation}", request, [0, request["n"]], generation)
            actual = np.fromfile(evidence / f"input-{generation}.f64", dtype="<f8").reshape(request["n"], -1)
            fft.compare(actual, samples, FIR_TOLERANCE, "live first filter window finite sum")
    image = inspect_png(directory / "display.png", regions=plot_regions(output))
    return dict(comparisons=comparisons, image=image, generations=generations, ui=record)


def run(binary, env, directory, request, original, language, timeout, codec, stimulus=None):
    directory.mkdir()
    (directory / "results").mkdir()
    (directory / "saves").mkdir()
    request = deepcopy(request)
    request["evidence"] = str((directory / "results").resolve())
    request["calibration"] = calibration.diagnostic_profiles(request)
    if original is not None:
        physical = original[:, np.argsort(request["format"]["input_ports"])]
        physical.tofile(directory / "input.bin")
        request["input"] = str((directory / "input.bin").resolve())
    path = directory / "request.json"
    path.write_text(json.dumps(request) + "\n")
    command = [
        str(binary),
        "--self-test",
        "--filter-test",
        "--language",
        language,
        "--snapshot",
        str((directory / "display.png").resolve()),
        "--save-directory",
        str((directory / "saves").resolve()),
    ]
    if stimulus is not None:
        command.append("--live-input")
    child_env = {**env, "MEASURELAB_DISPLAY_REQUEST": str(path.resolve())}
    started = time.monotonic()
    output, details, code, reason = "", None, None, None
    try:
        if stimulus is None:
            completed = subprocess.run(  # noqa: S603 - explicit local evaluation binary
                command, cwd=ROOT, env=child_env, capture_output=True, text=True, timeout=timeout, check=False
            )
        else:
            from scripts import migration_audio_virtual as virtual
            import sounddevice as sd

            cursor, statuses = 0, []

            def callback(outdata, frames, times, status):
                nonlocal cursor
                outdata[:] = stimulus[(np.arange(frames) + cursor) % len(stimulus)]
                cursor += frames
                if status:
                    statuses.append(str(status))

            stimulus.tofile(directory / "stimulus.f32")
            with sd.OutputStream(
                device=virtual.exact_device(request["live"]["device"]),
                samplerate=48000,
                blocksize=256,
                channels=stimulus.shape[1],
                dtype="float32",
                callback=callback,
                extra_settings=sd.CoreAudioSettings(change_device_parameters=True, fail_if_conversion_required=True),
            ) as stream:
                time.sleep(0.25)
                completed = subprocess.run(  # noqa: S603 - explicit local evaluation binary
                    command, cwd=ROOT, env=child_env, capture_output=True, text=True, timeout=timeout, check=False
                )
                if not stream.active or statuses:
                    raise fft.ReferenceError("stimulus stopped/XRUN")
        code, output = completed.returncode, completed.stdout + completed.stderr
        if (
            code
            or any(
                marker not in output
                for marker in ("FILTER_DISPLAY_PASS", "DISPLAY_IMAGE_OK", "DISPLAY_TEARDOWN workers=0 models=0")
            )
            or any(
                error in output
                for error in ("DISPLAY_FAIL", "TypeError", "ReferenceError", "Binding loop", "Unable to assign")
            )
        ):
            raise fft.ReferenceError("filter Qt failure/missing lifecycle markers")
        details = validate_run(output, directory, request, original, codec)
    except (fft.ReferenceError, ValueError, OSError, KeyError, subprocess.TimeoutExpired) as exc:
        reason = str(exc)
        if isinstance(exc, subprocess.TimeoutExpired):
            output = "".join(
                v.decode(errors="replace") if isinstance(v, bytes) else v or "" for v in (exc.stdout, exc.stderr)
            )
    (directory / "output.log").write_text(output)
    return dict(
        binary=binary.name,
        binary_sha256=sha256(binary),
        language=language,
        passed=reason is None,
        reason=reason,
        command=command,
        returncode=code,
        duration_seconds=time.monotonic() - started,
        details=details,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qt-prefix", type=Path, required=True)
    parser.add_argument("--target-dir", type=Path, default=ROOT / "native/target/debug")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--language", choices=LANGUAGES, action="append")
    parser.add_argument("--channels", type=int, choices=(2, 4, 8), action="append")
    parser.add_argument("--precision", choices=("F32", "F64"), action="append")
    parser.add_argument("--window", choices=("Boxcar", "SymmetricHann"), action="append")
    parser.add_argument("--forward", action="store_true")
    parser.add_argument("--virtual-device", action="store_true")
    parser.add_argument("--portaudio-library", type=Path)
    parser.add_argument("--portable", action="store_true")
    parser.add_argument("--timeout", type=float, default=60)
    args = parser.parse_args()
    if args.output.exists() or not np.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("new output and positive timeout required")
    if args.virtual_device and (
        sys.platform != "darwin"
        or args.portaudio_library is None
        or not args.portaudio_library.is_absolute()
        or not args.portaudio_library.is_file()
    ):
        parser.error("BlackHole requires macOS and an absolute existing PortAudio library")
    env, version = qt_environment(args.qt_prefix)
    binaries = [args.target_dir.resolve() / name for name in ("cxxqt-display", "qtbridge-display")]
    from scripts.migration_product_exchange import NativeCodec

    codec = NativeCodec(args.target_dir.resolve() / "result-candidate")
    if not all(p.is_file() for p in (*binaries, codec.binary)):
        parser.error("build both Qt displays and result-candidate first")
    manifest, manifest_hash = candidate.load_manifest(audio.core.DEFAULT_FIXTURES, portable=args.portable, is_core=True)
    paths = [
        p
        for p in (ROOT / "native").rglob("*")
        if p.is_file() and "target" not in p.parts and p.suffix in (".rs", ".qml", ".toml", ".lock")
    ]
    paths += sorted((ROOT / "scripts").glob("migration_*.py")) + sorted((ROOT / "src/assets/lang").glob("*.json"))
    paths += sorted((ROOT / "src/core/export").glob("*.py"))
    paths += [ROOT / "src/core/localization.py", ROOT / "src/core/utils.py"]
    before = {str(p.relative_to(ROOT)): sha256(p) for p in sorted(paths)}
    binaries_before = {p.name: sha256(p) for p in (*binaries, codec.binary)}
    library_hash = sha256(args.portaudio_library) if args.virtual_device else None
    args.output.mkdir(parents=True)
    runs = []
    for precision in ("F32",) if args.virtual_device else args.precision or ("F32", "F64"):
        for channels in args.channels or (2, 4, 8):
            case = next(
                c
                for c in manifest["tones"]
                if c["spec"]["dtype"] == ("<f4" if precision == "F32" else "<f8")
                and c["arrays"]["input"]["shape"][1] == max(4, channels)
            )
            original = fft.read_array(audio.core.DEFAULT_FIXTURES / case["spec"]["id"], case["arrays"]["input"])[
                :, :channels
            ]
            base = audio.request_for(case)
            base["n"] //= 2
            base["format"]["input_ids"] = base["format"]["input_ids"][:channels]
            base["format"]["input_ports"] = list(range(channels)) if args.forward else list(reversed(range(channels)))
            base["filter"] = {"input_conversion": "F32ToF64Exact" if precision == "F32" else None}
            base = {k: base[k] for k in ("format", "precision", "n", "window", "filter")}
            for window in args.window or ("Boxcar", "SymmetricHann"):
                base["window"] = window
                for backend in ("Cpal", "PortAudio") if args.virtual_device else ("saved",):
                    request, period = deepcopy(base), None
                    if args.virtual_device:
                        count = 2 if channels == 2 else 16
                        device = f"BlackHole {count}ch"
                        ports = (
                            list(reversed(range(channels))) if count == 2 else list(range(15, 15 - 2 * channels, -2))
                        )
                        request["format"].update(
                            stream_id=f"live.filter.{channels}",
                            timebase_id=f"live.filter.clock.{channels}",
                            input_ports=ports,
                            clock_domain=f"{backend.lower()}.device:{device}",
                        )
                        request["live"] = dict(
                            device=device,
                            device_channels=count,
                            backend=backend,
                            library=str(args.portaudio_library) if backend == "PortAudio" else None,
                        )
                        period = np.full((len(original), count), 0.001, dtype="<f4")
                        period[:, ports] = original
                    for language in args.language or ("en",):
                        for binary in binaries:
                            name = f"{precision}-{channels}-{window}-{backend}-{language}-{binary.stem}"
                            result = run(
                                binary,
                                env,
                                args.output / name,
                                request,
                                None if period is not None else original[:, request["format"]["input_ports"]],
                                language,
                                args.timeout,
                                codec,
                                period,
                            )
                            runs.append(result)
                            print(
                                f"{name}: {'PASS' if result['passed'] else 'FAIL'} {result['reason'] or ''}", flush=True
                            )
    unchanged = (
        before == {str(p.relative_to(ROOT)): sha256(p) for p in sorted(paths)}
        and binaries_before == {p.name: sha256(p) for p in (*binaries, codec.binary)}
        and (library_hash is None or library_hash == sha256(args.portaudio_library))
    )
    for relative in before:
        target = args.output / "source-snapshot" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / relative).read_bytes())
    for p in (*binaries, codec.binary, *((args.portaudio_library,) if args.virtual_device else ())):
        target = args.output / "binaries" / p.name
        target.parent.mkdir(exist_ok=True)
        target.write_bytes(p.read_bytes())
    passed = unchanged and bool(runs) and all(r["passed"] for r in runs)
    fft.write_json(
        args.output / "report.json",
        dict(
            schema_version=1,
            task="MIG-006-D-filter-Qt",
            passed=passed,
            source_binary_library_unchanged=unchanged,
            source_sha256=before,
            binary_sha256=binaries_before,
            portaudio_library_sha256=library_hash,
            fixture_manifest_sha256=manifest_hash,
            filter_manifest_sha256=sha256(ROOT / "migration/fixtures/filter-v1/manifest.json"),
            fir_tolerance=FIR_TOLERANCE,
            qt_version=version,
            host=dict(os=platform.system(), release=platform.release(), machine=platform.machine()),
            measurement_kind="BlackHole_correctness_only" if args.virtual_device else "saved_input_correctness_only",
            runs=runs,
            codec_commands=codec.commands,
            limitations=[
                "fixed causal 3-tap 48-to-24 kHz only",
                "explicit derived-domain manual Trigger; no parent-event adapter",
                "no dynamic route/full taps/profile persistence/008-A acceptance",
                "short correctness; no performance/physical clock/other OS acceptance",
            ],
        ),
    )
    fft.write_json(
        args.output / "evidence-audit.json",
        {str(p.relative_to(args.output)): sha256(p) for p in sorted(args.output.rglob("*")) if p.is_file()},
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
