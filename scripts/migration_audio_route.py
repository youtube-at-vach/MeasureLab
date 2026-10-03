"""MIG-005 dynamic output routes through the real control/callback mailbox.

Default: saved f32 inputs, independent block/ack oracle, no devices/Qt/SciPy.
--virtual-device: opt-in short BlackHole diagnostic; never establishes physical latency.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tempfile

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import migration_audio_candidate as audio  # noqa: E402
from scripts import migration_core_reference as core  # noqa: E402
from scripts import migration_fft_candidate as candidate  # noqa: E402
from scripts import migration_fft_reference as fft  # noqa: E402


def routes_for(ids, outputs):
    """Explicit selection, permutation, duplication, mix, sign and zero; stable port IDs."""
    count = len(ids)
    matrices = [
        [[float(column == port % count) for column in range(count)] for port in range(outputs)],
        [[float(column == (count - 1 - port % count)) for column in range(count)] for port in range(outputs)],
        [
            [
                (0.5 if column in (0, count - 1) else 0.0)
                if port % 3 == 0
                else float(column == 1) * (1 if port % 3 == 1 else -1)
                for column in range(count)
            ]
            for port in range(outputs)
        ],
        [[0.0] * count for _ in range(outputs)],
    ]
    return [
        {
            "inputs": ids,
            "outputs": [f"output.port.{p}" for p in range(outputs)],
            "gains": gains,
            "revision": f"route.{i}",
        }
        for i, gains in enumerate(matrices)
    ]


def request_for(ids, outputs, frames, blocks, ack_every):
    routes = routes_for(ids, outputs)
    return {
        "schema_version": 1,
        "source_ids": ids,
        "generation": 7,
        "frames": frames,
        "block_frames": blocks,
        "ack_every_blocks": ack_every,
        "mute_interval": [512, 1024],
        "initial": routes[0],
        "updates": [
            {"route": route, "generation": 7, "requested_sample": requested, "send_after_sample": sent}
            for route, requested, sent in zip(routes[1:], [257, 1025, 2049], [0, 1536, 2048], strict=True)
        ],
    }


def control_oracle(request):
    """Model independently in sample positions; never consume candidate acks as expectations."""
    blocks, events = [], []
    pending = None
    next_update = active = start = 0
    while start < request["frames"]:
        if len(blocks) % request["ack_every_blocks"] == 0 and pending is not None and pending[1] is not None:
            events.append(pending[1])
            pending = None
        if pending is None and next_update < len(request["updates"]):
            update = request["updates"][next_update]
            if start >= update["send_after_sample"]:
                next_update += 1
                pending = (next_update, None)
        if pending is not None and pending[1] is None:
            sequence = pending[0]
            update = request["updates"][sequence - 1]
            if start >= update["requested_sample"]:
                active = sequence
                pending = (
                    sequence,
                    {
                        "generation": request["generation"],
                        "sequence": sequence,
                        "revision": update["route"]["revision"],
                        "requested_sample": update["requested_sample"],
                        "applied_sample": start,
                        "status": "applied",
                    },
                )
        count = min(request["block_frames"][len(blocks) % len(request["block_frames"])], request["frames"] - start)
        blocks.append({"generation": request["generation"], "sequence": active, "interval": [start, start + count]})
        start += count
    if pending is not None and pending[1] is not None:
        events.append(pending[1])
    if len(events) != len(request["updates"]):
        raise fft.ReferenceError("Oracle schedule did not complete")
    return blocks, events


def route_values(values, route, ids):
    # IEEE addition's signed-zero identity matches the existing compiled route's empty sum.
    output = np.full((len(values), len(route["outputs"])), -0.0, dtype=np.float64)
    for port, gains in enumerate(route["gains"]):
        for channel, gain in zip(route["inputs"], gains, strict=True):
            if gain != 0:
                output[:, port] += values[:, ids.index(channel)].astype(np.float64) * gain
    return output.astype("<f4")


def expected_values(source, initial, updates, events, ids, frames, mute):
    # Pad only the submitted diagnostic tail after the finite source, never missing acquisition.
    padded = np.zeros((frames, len(ids)), dtype="<f4")
    count = min(frames, len(source))
    padded[:count] = source[:count]
    mixed = np.zeros((frames, len(initial["outputs"])), dtype="<f4")
    starts = [0, *[event["applied_sample"] for event in events], frames]
    for first, last, route in zip(starts, starts[1:], [initial, *[u["route"] for u in updates]], strict=False):
        mixed[first:last] = route_values(padded[first:last], route, ids)
    device = mixed.copy()
    device[slice(*mute)] = 0
    return mixed, device


def validate_offline(directory, request, source):
    raw = json.loads((directory / "manifest.json").read_bytes())
    blocks, events = control_oracle(request)
    expected_metadata = {
        "schema_version": 1,
        "request": request,
        "blocks": blocks,
        "events": events,
        "rendered_through": len(source),
        "dtype": "<f4",
        "taps": ["output.mixed", "output.device_buffer"],
        "physical_output": None,
    }
    if raw != expected_metadata:
        raise fft.ReferenceError("Dynamic route boundary/ack/revision/metadata mismatch")
    mixed, device = expected_values(
        source,
        request["initial"],
        request["updates"],
        events,
        request["source_ids"],
        len(source),
        request["mute_interval"],
    )
    for name, expected in [("mixed.bin", mixed), ("device.bin", device)]:
        if (directory / name).read_bytes() != expected.tobytes():
            raise fft.ReferenceError(f"Dynamic route sample bytes/tap mismatch: {name}")
    if not np.any(mixed[slice(*request["mute_interval"])] != 0):
        raise fft.ReferenceError("Muted mixed tap did not retain source")
    return {
        "blocks": len(blocks),
        "applied_samples": [e["applied_sample"] for e in events],
        "events": events,
        "status": "pass",
    }


def source_hashes():
    paths = [Path(__file__), ROOT / "native/Cargo.lock"]
    paths += [
        ROOT / "scripts" / name
        for name in [
            "migration_audio_candidate.py",
            "migration_audio_virtual.py",
            "migration_audio_graph.py",
            "migration_fft_candidate.py",
            "migration_core_reference.py",
        ]
    ]
    for crate in ["audio-core", "audio-probe", "graph-core", "dsp-core"]:
        paths += [ROOT / "native" / crate / "Cargo.toml", *sorted((ROOT / "native" / crate / "src").rglob("*.rs"))]
    return {str(p.relative_to(ROOT)): fft.digest(p.read_bytes()) for p in paths}


def verify(*, portable=False):
    _, build = audio.build()
    binary = ROOT / "native/target/debug/route-candidate"
    manifest, manifest_hash = candidate.load_manifest(core.DEFAULT_FIXTURES, portable=portable, is_core=True)
    report = {
        "schema_version": 1,
        "task": "MIG-005-dynamic-route",
        "source_sha256": source_hashes(),
        "binary_sha256": fft.digest(binary.read_bytes()),
        "fixture_manifest_sha256": manifest_hash,
        "cases": [],
        "commands": [build],
    }
    for case in manifest["tones"]:
        if case["spec"]["dtype"] != "<f4":
            continue
        core.load_tone(core.DEFAULT_FIXTURES, case)
        source_path = core.DEFAULT_FIXTURES / case["spec"]["id"] / case["arrays"]["input"]["file"]
        ids = case["metadata"]["channel_ids"]
        source = np.frombuffer(source_path.read_bytes(), dtype="<f4").reshape(-1, len(ids))
        for outputs in [2, 8] if len(ids) == 4 else [4, 16]:
            for blocks, ack_every in [([256], 1), ([1, 127, 256, 511], 1), ([127, 256], 4)]:
                request = request_for(ids, outputs, len(source), blocks, ack_every)
                with tempfile.TemporaryDirectory(prefix="migration-route-") as temp:
                    path = Path(temp) / "request.json"
                    directory = Path(temp) / "output"
                    fft.write_json(path, request)
                    command = candidate.run_command([str(binary), str(path), str(source_path), str(directory)])
                    result = validate_offline(directory, request, source)
                report["cases"].append(
                    {
                        "id": f"{case['spec']['id']}-{outputs}out-{blocks}-ack{ack_every}",
                        "input_sha256": fft.digest(source_path.read_bytes()),
                        "command": command,
                        **result,
                    }
                )
    report["status"] = "pass"
    return report


def virtual_request(sources, ports, generation, device):
    ids = [f"generator.{i}" for i in range(sources)]
    routes = routes_for(ids, ports)
    return {
        "schema_version": 1,
        "device": device,
        "session_id": f"dynamic.{sources}.{ports}.{generation}",
        "generation": generation,
        "duration_seconds": 4,
        "input_channels": ports,
        "output_channels": ports,
        "source_ids": ids,
        "route": routes[0],
        "mute_interval": [108032, 132096],
        "route_updates": [
            {"route": route, "generation": generation, "requested_sample": requested, "send_after_sample": sent}
            for route, requested, sent in zip(routes[1:], [48001, 96001, 144001], [0, 100000, 144000], strict=True)
        ],
    }


def validate_virtual_events(raw, request):
    from scripts import migration_audio_graph as acquisition

    acquisition.validate_device_graph(raw)
    metadata = raw["dynamic_routes"]
    events = metadata["events"]
    updates = request["route_updates"]
    if (
        metadata["initial_sequence"] != 0
        or metadata["sample_domain"] != "output-callback.frame"
        or metadata["initial_revision"] != request["route"]["revision"]
        or metadata["submitted_count"] != len(updates)
        or metadata["unsubmitted_count"] != 0
        or metadata["rendered_through"] != raw["output"]["frames"]
        or len(events) != len(updates)
    ):
        raise fft.ReferenceError("Incomplete virtual route schedule")
    previous = -1
    for sequence, (event, update) in enumerate(zip(events, updates, strict=True), 1):
        applied = event.get("applied_sample")
        if (
            set(event) != {"generation", "sequence", "revision", "requested_sample", "applied_sample", "status"}
            or event["generation"] != request["generation"]
            or event["sequence"] != sequence
            or event["revision"] != update["route"]["revision"]
            or event["requested_sample"] != update["requested_sample"]
            or event["status"] != "applied"
            or type(applied) is not int
            or applied < max(update["requested_sample"], update["send_after_sample"])
            or applied <= previous
            or applied >= raw["output"]["frames"]
            or applied % 256
        ):
            raise fft.ReferenceError("Virtual route ack/generation/revision/block boundary mismatch")
        previous = applied
    if any(raw["output_callback"][key] != 256 for key in ["min_frames", "max_frames"]):
        raise fft.ReferenceError("Virtual diagnostic block size changed")
    return events


def virtual_verify(output, runs):
    from scripts import migration_audio_virtual as virtual

    import sounddevice as sd

    if output.exists():
        raise fft.ReferenceError("Output directory exists; choose a new run path")
    devices = {name: dict(sd.query_devices(virtual.exact_device(name))) for name in virtual.DEVICES}
    output.mkdir(parents=True)
    report = {
        "schema_version": 1,
        "task": "MIG-005-dynamic-route-BlackHole",
        "devices": devices,
        "source_sha256": source_hashes(),
        "tolerances": virtual.TOLERANCES,
        "runs": [],
        "cancels": [],
        "commands": [],
        "limitations": [
            "Short CPAL diagnostic; no PortAudio dynamic comparison or performance verdict",
            "No physical delay/clock accuracy, USB recovery, Qt or full tap/graph integration",
        ],
    }
    success = False
    try:
        binary, build = audio.build("audio-probe", release=True)
        report["commands"].append(build)
        report["binary_sha256"] = fft.digest(binary.read_bytes())
        generation = 0
        for sources, ports, device in [(2, 2, "BlackHole 2ch"), (4, 16, "BlackHole 16ch"), (8, 16, "BlackHole 16ch")]:
            source = virtual.stimulus(sources)
            signal = output / f"{sources}-{ports}-source.f32"
            signal.write_bytes(source.tobytes())
            for run in range(1, runs + 1):
                generation += 1
                request = virtual_request(sources, ports, generation, device)
                path = output / f"{sources}-{ports}-{run}-request.json"
                directory = output / f"{sources}-{ports}-{run}"
                fft.write_json(path, request)
                command = candidate.run_command([str(binary), str(path), str(signal), str(directory)], timeout=30)
                report["commands"].append(command)
                raw = json.loads((directory / "manifest.json").read_bytes())
                events = validate_virtual_events(raw, request)
                _, expected = expected_values(
                    source,
                    request["route"],
                    request["route_updates"],
                    events,
                    request["source_ids"],
                    raw["output"]["frames"],
                    request["mute_interval"],
                )
                result = virtual.analyze(directory, expected, source)
                report["runs"].append(
                    {
                        "sources": sources,
                        "ports": ports,
                        "run": run,
                        "events": events,
                        "source_sha256": fft.digest(signal.read_bytes()),
                        "metrics": result,
                        "analysis_graph": raw["analysis_graph"],
                        "output_callback": raw["output_callback"],
                    }
                )
                fft.write_json(output / "report.json", report)
                if result["status"] != "pass":
                    raise fft.ReferenceError("Dynamic BlackHole sample/route/mute regression")
                print(f"BlackHole dynamic route: {sources} -> {ports}, run {run}: pass", flush=True)
            generation += 1
            request = {**virtual_request(sources, ports, generation, device), "cancel_preparing": True}
            path = output / f"{sources}-{ports}-cancel-request.json"
            directory = output / f"{sources}-{ports}-cancel"
            fft.write_json(path, request)
            report["commands"].append(
                candidate.run_command([str(binary), str(path), str(signal), str(directory)], timeout=30)
            )
            raw = json.loads((directory / "manifest.json").read_bytes())
            expected_cancel = {
                "generation": generation,
                "sequence": 1,
                "revision": "route.1",
                "requested_sample": 48001,
                "applied_sample": None,
                "status": "cancelled",
            }
            if (
                raw["state"] != "cancelled"
                or raw["dynamic_routes"]["events"] != [expected_cancel]
                or raw["input"]["frames"] != 0
                or raw["output"]["frames"] != 0
            ):
                raise fft.ReferenceError("Preparing cancel did not cancel the pending route")
            report["cancels"].append(
                {
                    "sources": sources,
                    "ports": ports,
                    "event": expected_cancel,
                    "manifest_sha256": fft.digest((directory / "manifest.json").read_bytes()),
                    "status": "pass",
                }
            )
        success = True
    finally:
        report["status"] = "pass" if success else "fail"
        fft.write_json(output / "report.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--portable", action="store_true")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--virtual-device", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--runs", type=int, choices=range(1, 4), default=3)
    args = parser.parse_args()
    if args.virtual_device:
        if args.output is None or args.portable:
            parser.error("BlackHole requires --virtual-device --output and the local environment")
        report = virtual_verify(args.output, args.runs)
    else:
        if args.output is not None:
            parser.error("Device I/O requires explicit --virtual-device")
        report = verify(portable=args.portable)
    if args.report:
        fft.write_json(args.report, report)
    if args.virtual_device:
        print(f"Dynamic BlackHole OK: {len(report['runs'])} captures, {len(report['cancels'])} pending-route cancels")
    else:
        print(f"Dynamic route OK: {len(report['cases'])} saved-input/block/ack cases; exact mixed/device bytes")


if __name__ == "__main__":
    main()
