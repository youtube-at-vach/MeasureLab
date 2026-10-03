"""Live passes require acquired bytes, correct mapping and released stream evidence."""

import json
import subprocess
import sys
from types import SimpleNamespace

import numpy as np
import pytest

from scripts import migration_audio_graph as audio
from scripts import migration_fft_reference as fft
from scripts import migration_qt_live as live


def evidence(directory, case):
    request = live.request_for(case, directory)
    samples = live.stimulus(case)[:, case["ports"]]
    peak = np.abs(np.fft.rfft(samples.astype(np.float64), axis=0)) * (2 / live.N)
    peak[[0, -1]] *= 0.5
    channels = len(case["ports"])
    for generation in (3, 4, 5):
        source = audio.expected_source(request)
        source["generation"] = source["timebase"]["generation"] = generation
        document = {
            "schema_version": 1,
            "source": source,
            "interval": [0, live.N],
            "validity": [],
            "error": None,
            "axis": {"unit": "Hz", "corrected": (np.arange(live.N // 2 + 1) * live.RATE / live.N).tolist()},
            "columns": {
                "peak_fs": {"shape": list(peak.shape), "values": peak.ravel().tolist()},
                "rms_v": {"values": [None] * channels, "reasons": ["uncalibrated"] * channels},
            },
        }
        metrics = {
            "schema_version": 1,
            "generation": generation,
            "device": case["device"],
            "backend": case.get("backend", "Cpal"),
            "format": {**request["format"], "generation": generation},
            "input": {"callbacks": 4, "frames": live.N, "errors": 0, "xruns": 0, "rejected": 0, "closed": True},
            "captured_frames": live.N,
            "fft_evaluations": 1,
            "reclaimed": True,
            "error": None,
            "queue": {"channels": request["live"]["device_channels"], "capacity_frames": 8192, "max_depth_frames": 256},
            "stop_ms": 1.5,
        }
        if case.get("backend") == "PortAudio":
            metrics["input"].update(
                terminated=True,
                transport="native PortAudio callback -> common f32 input queue",
                api_version=19 << 16,
                reported_rate=live.RATE,
                stream_info_version=0,
            )
        (directory / f"generation-{generation}.json").write_text(json.dumps(document))
        (directory / f"live-{generation}.json").write_text(json.dumps(metrics))
        samples.tofile(directory / f"input-{generation}.f32")
    return request


@pytest.mark.parametrize("case", live.cases(), ids=lambda case: case["id"])
def test_acquired_bytes_and_explicit_mapping_pass(tmp_path, case):
    assert len(live.validate_evidence(tmp_path, evidence(tmp_path, case))) == 3


@pytest.mark.parametrize("mutation", [None, "backend", "terminated", "transport", "version", "rate"])
def test_portaudio_requires_direct_callback_and_termination(tmp_path, mutation):
    case = {**live.cases()[1], "backend": "PortAudio", "library": "/trusted/portaudio"}
    request = evidence(tmp_path, case)
    assert request["format"]["clock_domain"] == "portaudio.device:BlackHole 16ch"
    path = tmp_path / "live-5.json"
    metrics = json.loads(path.read_bytes())
    if mutation == "backend":
        metrics["backend"] = "Cpal"
    elif mutation == "terminated":
        metrics["input"]["terminated"] = False
    elif mutation == "transport":
        metrics["input"]["transport"] = "blocking worker -> pipe"
    elif mutation == "version":
        metrics["input"]["api_version"] = 18 << 16
    elif mutation == "rate":
        metrics["input"]["reported_rate"] = 44100
    path.write_text(json.dumps(metrics))
    if mutation is None:
        assert len(live.validate_evidence(tmp_path, request)) == 3
    else:
        with pytest.raises(fft.ReferenceError):
            live.validate_evidence(tmp_path, request)


@pytest.mark.parametrize(
    "mutation",
    [
        "numeric",
        "clock",
        "generation",
        "channels",
        "interval",
        "calibration",
        "axis",
        "closed",
        "xrun",
        "reclaimed",
        "format",
        "frames",
        "missing",
        "bytes",
        "zero",
    ],
)
def test_invalid_live_evidence_rejected(tmp_path, mutation):
    case = live.cases()[1]
    request = evidence(tmp_path, case)
    path = tmp_path / "generation-5.json"
    metrics_path = tmp_path / "live-5.json"
    document = json.loads(path.read_bytes())
    metrics = json.loads(metrics_path.read_bytes())
    if mutation == "numeric":
        document["columns"]["peak_fs"]["values"][37 * 4] += 0.001
    elif mutation == "clock":
        document["source"]["timebase"]["origin_seconds"] = 0
    elif mutation == "generation":
        document["source"]["generation"] = 4
    elif mutation == "channels":
        document["source"]["channel_ids"].reverse()
    elif mutation == "interval":
        document["interval"] = [1, live.N + 1]
    elif mutation == "calibration":
        document["columns"]["rms_v"]["values"][0] = 1
    elif mutation == "axis":
        document["axis"]["corrected"][1] += 1
    elif mutation == "closed":
        metrics["input"]["closed"] = False
    elif mutation == "xrun":
        metrics["input"]["xruns"] = 1
    elif mutation == "reclaimed":
        metrics["reclaimed"] = False
    elif mutation == "format":
        metrics["format"]["input_ports"].reverse()
    elif mutation == "frames":
        metrics["input"]["frames"] = 0
    elif mutation == "missing":
        (tmp_path / "input-5.f32").unlink()
    elif mutation == "bytes":
        (tmp_path / "input-5.f32").write_bytes(b"\x00")
    elif mutation == "zero":
        np.zeros((live.N, 4), dtype="<f4").tofile(tmp_path / "input-5.f32")
        document["columns"]["peak_fs"]["values"] = [0.0] * len(document["columns"]["peak_fs"]["values"])
    path.write_text(json.dumps(document))
    metrics_path.write_text(json.dumps(metrics))
    with pytest.raises((fft.ReferenceError, OSError, ValueError)):
        live.validate_evidence(tmp_path, request)


def test_without_explicit_device_flag_exits_before_creating_run(tmp_path):
    output = tmp_path / "run"
    result = subprocess.run(  # noqa: S603 - repository script
        [sys.executable, live.__file__, "--qt-prefix", str(tmp_path), "--output", str(output)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2 and "explicit --virtual-device" in result.stderr
    assert not output.exists()


def test_qt_pass_markers_without_live_artifacts_are_rejected(tmp_path, monkeypatch):
    class OutputStream:
        active = True

        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setitem(
        sys.modules,
        "sounddevice",
        SimpleNamespace(
            OutputStream=OutputStream, CoreAudioSettings=lambda **kwargs: None, PortAudioError=RuntimeError
        ),
    )
    monkeypatch.setattr(live.virtual, "exact_device", lambda name: 0)
    output = f"DISPLAY_READY\n{live.PASS}\nDISPLAY_IMAGE_OK\nDISPLAY_TEARDOWN workers=0 models=0\n"
    monkeypatch.setattr(
        live.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=output, stderr="")
    )
    binary = tmp_path / "display"
    binary.write_bytes(b"unused")
    run = live.run_display(binary, {}, tmp_path / "run", live.cases()[0], 1)
    assert not run["passed"] and run["exit_code"] == 0
