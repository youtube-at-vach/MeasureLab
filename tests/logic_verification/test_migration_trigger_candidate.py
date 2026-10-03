"""Trigger proof rejection stays NumPy-only; original-byte execution uses native CI."""

import copy
import json
import subprocess
import sys

import numpy as np
import pytest

from scripts import migration_trigger_candidate as trigger


@pytest.fixture
def proof():
    request = {
        "n": 8,
        "precision": "F64",
        "window": "Boxcar",
        "format": {
            "stream_id": "virtual.input",
            "generation": 3,
            "timebase_id": "virtual.clock",
            "clock_domain": "virtual",
            "rate": [48000, 1],
            "input_ids": ["left", "right"],
            "input_ports": [0, 1],
            "output_ids": [],
            "output_ports": [],
        },
    }
    fmt = request["format"]
    stats = {
        "nodes": 1,
        "subscriptions": 2,
        "cache_results": 2,
        "cache_numeric_bytes": 1024,
        "in_flight": 0,
        "fft_evaluations": 2,
        "display_replacements": 0,
    }
    reads = {}
    for name in (*trigger.NAMES, "pending", "expired", "expired_shifted"):
        start = int(name in ("shifted", "repeated", "expired_shifted"))
        status = "pending" if name == "pending" else "gap" if name.startswith("expired") else "snapshot"
        reads[name] = {
            "request_id": "aligned"
            if name in ("pending", "expired")
            else "shifted"
            if name == "expired_shifted"
            else name,
            "event": trigger.event_for(request, name),
            "residual": {"numerator": 1, "denominator": 2},
            "history": {
                "stream_id": fmt["stream_id"],
                "generation": 3,
                "timebase_id": fmt["timebase_id"],
                "interval": [start, start + 8],
                "status": status,
                "missing": [[start, 8]] if status == "gap" else [],
                "pending": [[0, 8]] if status == "pending" else [],
                "reason": "missing" if status == "gap" else None,
            },
            "has_snapshot": status == "snapshot",
            "has_result": status == "snapshot",
            "result_id": f"trigger:{2 if start else 1}:{2 if start else 3}:{name}:{len(reads) + 1}"
            if status == "snapshot"
            else None,
            "raw_result_id": {"graph": 2 if start else 1, "serial": 2 if start else 3}
            if status == "snapshot"
            else None,
            "fft_origin": "computed"
            if name == "shifted"
            else "trigger-cache"
            if name == "repeated"
            else "continuous-cache"
            if status == "snapshot"
            else "none",
        }
    header = {
        "schema_version": 1,
        "format": fmt,
        "source": trigger.audio.expected_source(request),
        "shared_continuous": True,
        "shared_trigger": True,
        "latest_interval": [8, 16],
        "latest_map_interval": [8, 16],
        "latest_average_count": 2,
        "trigger_evaluations": 1,
        "stale_error": "stale_generation",
        "stopped_error": "capture_not_running",
        "history_released": True,
        "reads": reads,
        "continuous_before": stats,
        "continuous_after": copy.deepcopy(stats),
        "after_stop": {
            **stats,
            "nodes": 0,
            "subscriptions": 0,
            "cache_results": 0,
            "cache_numeric_bytes": 0,
            "fft_evaluations": 3,
        },
    }
    samples = np.column_stack((np.arange(8) / 16, -np.arange(8) / 32))
    case = {"spec": {"n": 8, "rate_hz": 48000, "window": "boxcar"}}
    z = np.fft.rfft(samples, axis=0) / 8
    arrays = trigger.oracle.quantities(z, np.ones(8), samples, 48000)
    arrays.pop("frequency_hz")
    arrays.update(
        window=np.ones(8),
        inverse_windowed=samples,
        fft_over_n=np.stack((z.real, z.imag), axis=-1),
        tone_rms_fs=arrays["peak_fs"] / np.sqrt(2),
        asd_fs_sqrt_hz=np.sqrt(arrays["psd_fs2_hz"]),
    )
    # The ramp's mean and alternating component have constant magnitude.
    arrays["tone_rms_fs"][[0, -1]] = [[7 / 32, 7 / 64], [1 / 32, 1 / 64]]
    units = {
        "window": "1",
        "inverse_windowed": "FS",
        "fft_over_n": "FS",
        "peak_fs": "FS_peak",
        "tone_rms_fs": "FS_RMS",
        "rms_fs": "FS_RMS",
        "psd_fs2_hz": "FS2/Hz",
        "asd_fs_sqrt_hz": "FS/sqrt(Hz)",
        "integrated_power_fs2": "FS2",
        "time_window_power_fs2": "FS2",
    }
    columns = {
        name: {
            "unit": units[name],
            "shape": list(array.shape),
            "precision": "F64",
            "values": array.ravel().tolist(),
            "reasons": [None] * array.size,
        }
        for name, array in arrays.items()
    }
    for name, shape, unit in (
        ("rms_v", [2], "V_RMS"),
        ("dbv", [2], "dBV_RMS"),
        ("spl", [2], "dBSPL"),
        ("psd_v2_hz", [5, 2], "V2/Hz"),
    ):
        count = int(np.prod(shape))
        columns[name] = {
            "shape": shape,
            "precision": "F64",
            "unit": unit,
            "values": [None] * count,
            "reasons": ["uncalibrated"] * count,
        }
    source = header["source"]
    event = reads["shifted"]["event"]
    document = {
        "schema_version": 1,
        "source": source,
        "operation_revision": trigger.graph.TRANSFORM_REVISION,
        "interval": [1, 9],
        "raw_result_id": [2, 2],
        "validity": [],
        "error": None,
        "capture": {
            "result_id": "trigger:2:2:shifted:3",
            "trigger_id": "virtual.shifted",
            "trigger": event,
            "acquired_host_seconds": None,
            "result_host_seconds": None,
            "clock_mapping": None,
        },
        "conditions": {
            "source": source,
            "n": 8,
            "hop": 8,
            "alignment": 1,
            "window": "Boxcar",
            "remove_dc": False,
            "input_gains": [],
        },
        "calibration": [{"channel_id": c, "profile": None, "application": "after_analysis"} for c in fmt["input_ids"]],
        "axis": {
            "dimension": "frequency",
            "unit": "Hz",
            "nominal": [0.0, 6000.0, 12000.0, 18000.0, 24000.0],
            "corrected": [0.0, 6000.0, 12000.0, 18000.0, 24000.0],
            "correction": 1.0,
        },
        "columns": columns,
    }
    return request, case, header, document, samples


def test_valid_proof_has_exact_positions_and_all_numeric_columns(proof):
    request, case, header, document, samples = proof
    trigger.validate_manifest(header, request)
    assert len(trigger.validate_document(document, header["reads"]["shifted"], request, case, samples)) == 10


@pytest.mark.parametrize(
    "fault",
    [
        "pending_numeric",
        "expired_snapshot",
        "missing_interval",
        "generation",
        "residual",
        "clock",
        "same_id",
        "share",
        "continuous",
        "average",
        "extra_fft",
        "leak",
        "id_type",
        "extra",
    ],
)
def test_rejects_false_trigger_lifecycle_proof(proof, fault):
    request, _, header, _, _ = proof
    reads = header["reads"]
    if fault == "pending_numeric":
        reads["pending"]["has_result"] = True
    elif fault == "expired_snapshot":
        reads["expired"]["has_snapshot"] = True
    elif fault == "missing_interval":
        reads["expired_shifted"]["history"]["missing"] = [[0, 8]]
    elif fault == "generation":
        reads["shifted"]["event"]["generation"] += 1
    elif fault == "residual":
        reads["shifted"]["residual"]["numerator"] = 0
    elif fault == "clock":
        header["source"]["timebase"]["origin_seconds"] = {"numerator": 0, "denominator": 1}
    elif fault == "same_id":
        reads["repeated"]["raw_result_id"]["serial"] += 1
    elif fault == "share":
        header["shared_trigger"] = False
    elif fault == "continuous":
        header["continuous_after"]["fft_evaluations"] += 1
    elif fault == "average":
        header["latest_average_count"] = 1
    elif fault == "extra_fft":
        header["trigger_evaluations"] = 2
    elif fault == "leak":
        header["after_stop"]["nodes"] = 1
    elif fault == "id_type":
        reads["shifted"]["raw_result_id"]["graph"] = True
    else:
        header["extra"] = None
    with pytest.raises(trigger.fft.ReferenceError):
        trigger.validate_manifest(header, request)


@pytest.mark.parametrize(
    "fault",
    [
        "trigger_id",
        "trigger_sample",
        "received_time",
        "precision",
        "interval",
        "condition",
        "binding",
        "profile",
        "zero_voltage",
        "reason",
        "axis",
        "shape",
        "unit",
        "nonfinite",
        "wrong_fft",
        "missing_column",
        "extra",
    ],
)
def test_rejects_false_trigger_measurement(proof, fault):
    request, case, header, document, samples = proof
    # Decouple event/source objects from the expected read; a corrupted document must not rewrite its oracle.
    document = copy.deepcopy(document)
    if fault == "trigger_id":
        document["capture"]["trigger_id"] = "wrong"
    elif fault == "trigger_sample":
        document["capture"]["trigger"]["sample"]["numerator"] += 1
    elif fault == "received_time":
        document["capture"]["trigger"]["received_host_seconds"] = None
    elif fault == "precision":
        document["columns"]["inverse_windowed"]["precision"] = "F32"
    elif fault == "interval":
        document["interval"][0] += 1
    elif fault == "condition":
        document["conditions"]["alignment"] = 0
    elif fault == "binding":
        document["source"]["channel_ids"].reverse()
    elif fault == "profile":
        document["calibration"][0]["profile"] = {}
    elif fault == "zero_voltage":
        document["columns"]["rms_v"]["values"][0] = 0.0
    elif fault == "reason":
        document["columns"]["rms_v"]["reasons"][0] = None
    elif fault == "axis":
        document["axis"]["corrected"][1] += 1
    elif fault == "shape":
        document["columns"]["fft_over_n"]["shape"][0] += 1
    elif fault == "unit":
        document["columns"]["peak_fs"]["unit"] = "V"
    elif fault == "nonfinite":
        document["columns"]["fft_over_n"]["values"][0] = float("nan")
    elif fault == "wrong_fft":
        document["columns"]["fft_over_n"]["values"][0] += 0.1
    elif fault == "missing_column":
        document["columns"].pop("time_window_power_fs2")
    else:
        document["extra"] = None
    with pytest.raises(trigger.fft.ReferenceError):
        trigger.validate_document(document, header["reads"]["shifted"], request, case, samples)


@pytest.mark.native
def test_original_precision_and_binding_corpus_and_headless_process(tmp_path):
    # Separate process ensures Qt/sounddevice imports from the product test suite cannot mask isolation.
    output = tmp_path / "corpus"
    trigger.candidate.run_command(
        [
            sys.executable,
            str(trigger.ROOT / "scripts/migration_trigger_candidate.py"),
            "--portable",
            "--output",
            str(output),
        ]
    )
    report = json.loads((output / "report.json").read_bytes())
    assert len(report["corpus"]) == 8
    assert report["status"] == "pass"
    for record in report["corpus"]:
        assert record["manifest"]["trigger_evaluations"] == 1
    case = json.loads((trigger.core.DEFAULT_FIXTURES / "manifest.json").read_bytes())["tones"][0]
    evidence = output / (case["spec"]["id"] + "-identity") / "evidence"
    data = bytearray((evidence / "shifted.bin").read_bytes())
    data[0] ^= 1
    (evidence / "shifted.bin").write_bytes(data)
    with pytest.raises(trigger.fft.ReferenceError):
        trigger.read_result(evidence, case)


@pytest.mark.native
@pytest.mark.parametrize("fault", ["shape", "binding", "schema", "existing_output"])
def test_native_rejects_invalid_request_without_overwriting(tmp_path, fault):
    binary, _ = trigger.build()
    case = json.loads((trigger.core.DEFAULT_FIXTURES / "manifest.json").read_bytes())["tones"][0]
    request = trigger.audio.request_for(case)
    source = trigger.core.DEFAULT_FIXTURES / case["spec"]["id"] / case["arrays"]["input"]["file"]
    if fault == "shape":
        request["n"] += 1
    elif fault == "binding":
        request["format"]["input_ports"][0] = 99
    elif fault == "schema":
        request["schema_version"] = 2
    path = tmp_path / "request.json"
    trigger.fft.write_json(path, request)
    output = tmp_path / "output"
    if fault == "existing_output":
        output.mkdir()
        (output / "sentinel").write_bytes(b"keep")
    completed = subprocess.run(  # noqa: S603 - fixed local evaluation binary
        [str(binary), str(path), str(source), str(output)], capture_output=True, timeout=30, check=False
    )
    assert completed.returncode != 0
    if fault == "existing_output":
        assert (output / "sentinel").read_bytes() == b"keep"
    else:
        assert not output.exists()
