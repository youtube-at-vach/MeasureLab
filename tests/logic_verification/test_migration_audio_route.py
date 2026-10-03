"""Exercise the native mailbox and independent rejection/metadata/numeric checks."""

import copy
import json
import subprocess

import numpy as np
import pytest

from scripts import migration_audio_route as route
from scripts import migration_fft_reference as fft


@pytest.fixture(scope="module")
def binary():
    route.audio.build()
    return route.ROOT / "native/target/debug/route-candidate"


def run_case(binary, tmp_path, request=None):
    source = np.arange(4096 * 4, dtype="<f4").reshape(4096, 4) / 10000
    request = request or route.request_for(["a", "b", "c", "d"], 2, 4096, [256], 1)
    source_path = tmp_path / "source.f32"
    source_path.write_bytes(source.tobytes())
    path = tmp_path / "request.json"
    fft.write_json(path, request)
    output = tmp_path / "output"
    result = subprocess.run(  # noqa: S603 - local evaluation executable; no shell
        [str(binary), str(path), str(source_path), str(output)], capture_output=True, check=False
    )
    return result, output, request, source


@pytest.mark.native
def test_saved_input_bytes_routes_mute_variable_blocks_and_slow_acks():
    report = route.verify(portable=True)
    assert report["status"] == "pass"
    assert len(report["cases"]) == 12
    assert all(len(case["events"]) == 3 for case in report["cases"])


@pytest.mark.parametrize(
    ("blocks", "ack_every", "expected"),
    [([256], 1, [512, 1536, 2304]), ([1, 127, 256, 511], 1, [384, 1790, 2174]), ([127, 256], 4, [383, 1659, 2298])],
)
def test_independent_oracle_has_hand_computed_requested_and_late_boundaries(blocks, ack_every, expected):
    request = route.request_for(["a", "b", "c", "d"], 2, 4096, blocks, ack_every)
    _, events = route.control_oracle(request)
    assert [event["applied_sample"] for event in events] == expected
    assert [event["requested_sample"] for event in events] == [257, 1025, 2049]


@pytest.mark.native
@pytest.mark.parametrize(
    "fault", ["revision", "generation", "requested", "actual", "interval", "sequence", "tap", "sample", "missing_event"]
)
def test_checker_rejects_corrupt_candidate_output(binary, tmp_path, fault):
    result, output, request, source = run_case(binary, tmp_path)
    assert result.returncode == 0, result.stderr
    route.validate_offline(output, request, source)
    path = output / "manifest.json"
    raw = json.loads(path.read_bytes())
    if fault in ["revision", "generation", "requested", "actual", "sequence"]:
        key = {"requested": "requested_sample", "actual": "applied_sample"}.get(fault, fault)
        raw["events"][0][key] = "wrong" if fault == "revision" else raw["events"][0][key] + 1
    elif fault == "interval":
        raw["blocks"][2]["interval"][0] += 1
    elif fault == "missing_event":
        raw["events"].pop()
    elif fault == "tap":
        raw["taps"][0] = "input.raw"
    else:
        values = np.frombuffer((output / "mixed.bin").read_bytes(), dtype="<f4").copy()
        values[100] += 0.1
        (output / "mixed.bin").write_bytes(values.tobytes())
    fft.write_json(path, raw)
    with pytest.raises(fft.ReferenceError):
        route.validate_offline(output, request, source)


@pytest.mark.native
@pytest.mark.parametrize(
    "fault",
    [
        "version",
        "duplicate",
        "block",
        "ack",
        "generation",
        "binding",
        "unknown",
        "shape",
        "revision",
        "order",
        "future",
        "extra",
    ],
)
def test_rejects_invalid_schedule_before_creating_output(binary, tmp_path, fault):
    request = route.request_for(["a", "b", "c", "d"], 2, 4096, [256], 1)
    update = request["updates"][1]
    if fault == "version":
        request["schema_version"] = 2
    elif fault == "duplicate":
        request["source_ids"][1] = "a"
    elif fault == "block":
        request["block_frames"] = [0]
    elif fault == "ack":
        request["ack_every_blocks"] = 0
    elif fault == "generation":
        update["generation"] = 6
    elif fault == "binding":
        update["route"]["outputs"].reverse()
    elif fault == "unknown":
        update["route"]["inputs"] = ["unknown"]
    elif fault == "shape":
        update["route"]["gains"] = [[1]]
    elif fault == "revision":
        update["route"]["revision"] = "route.1"
    elif fault == "order":
        update["requested_sample"] = 1
    elif fault == "future":
        update["send_after_sample"] = 4096
    else:
        update["extra"] = 1
    result, output, _, source = run_case(binary, tmp_path, request)
    assert result.returncode != 0
    assert not output.exists()
    assert (tmp_path / "source.f32").read_bytes() == source.tobytes()


def test_cli_requires_explicit_device_flag_before_any_work(monkeypatch, tmp_path):
    monkeypatch.setattr("sys.argv", ["migration_audio_route.py", "--output", str(tmp_path / "output")])
    with pytest.raises(SystemExit, match="2"):
        route.main()
    assert not (tmp_path / "output").exists()


@pytest.mark.parametrize("fault", ["revision", "generation", "requested", "actual", "count", "boundary", "cancelled"])
def test_virtual_ack_checker_detects_unapplied_or_stale_revision(monkeypatch, fault):
    from scripts import migration_audio_graph as acquisition

    # The existing acquisition validator has its own full metadata/corruption tests.
    monkeypatch.setattr(acquisition, "validate_device_graph", lambda raw: None)
    request = route.virtual_request(2, 2, 7, "BlackHole 2ch")
    events = [
        {
            "generation": 7,
            "sequence": i,
            "revision": update["route"]["revision"],
            "requested_sample": update["requested_sample"],
            "applied_sample": sample,
            "status": "applied",
        }
        for i, (update, sample) in enumerate(zip(request["route_updates"], [48128, 100096, 144128], strict=True), 1)
    ]
    raw = {
        "dynamic_routes": {
            "initial_sequence": 0,
            "sample_domain": "output-callback.frame",
            "initial_revision": "route.0",
            "submitted_count": 3,
            "unsubmitted_count": 0,
            "rendered_through": 200000,
            "events": events,
        },
        "output": {"frames": 200000},
        "output_callback": {"min_frames": 256, "max_frames": 256},
    }
    assert route.validate_virtual_events(raw, request) == events
    raw = copy.deepcopy(raw)
    if fault == "count":
        raw["dynamic_routes"]["events"].pop()
    elif fault == "boundary":
        raw["dynamic_routes"]["events"][0]["applied_sample"] += 1
    else:
        key = {"requested": "requested_sample", "actual": "applied_sample", "cancelled": "status"}.get(fault, fault)
        raw["dynamic_routes"]["events"][0][key] = {
            "revision": "wrong",
            "generation": 6,
            "requested": 1,
            "actual": 0,
            "cancelled": "cancelled",
        }[fault]
    with pytest.raises(fft.ReferenceError):
        route.validate_virtual_events(raw, request)
