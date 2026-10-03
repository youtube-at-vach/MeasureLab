"""Native live-filter evidence rejection without Qt, devices or sounddevice imports."""

import copy

import pytest

from scripts import migration_fft_reference as fft
from scripts import migration_filter_live as live


def metrics(backend):
    request = live.request_for(live.CASES[0], backend, "/absolute/libportaudio.dylib")
    report = {
        "schema_version": 1,
        "binding": copy.deepcopy(request["binding"]),
        "input": {
            "callbacks": 32,
            "frames": live.FRAMES,
            "errors": 0,
            "xruns": 0,
            "rejected": 0,
            "closed": True,
            "terminated": True,
            "reported_rate": 48000.0,
        },
        "queue": {"capacity_frames": 8192, "channels": 2},
        "stop_ms": 1.0,
        "error": None,
        "failed": False,
    }
    return report, request


@pytest.mark.parametrize("backend", ["Cpal", "PortAudio"])
def test_closed_backend_metrics_are_accepted_without_devices(backend):
    report, request = metrics(backend)
    live.validate_metrics(report, request)


@pytest.mark.parametrize(
    "fault",
    [
        "field",
        "binding",
        "error",
        "failed",
        "xrun",
        "closed",
        "frames",
        "boolean_counter",
        "terminate",
        "rate",
        "stop",
        "queue",
    ],
)
def test_live_filter_failure_or_incomplete_reclamation_is_rejected(fault):
    report, request = metrics("PortAudio")
    if fault == "field":
        report["extra"] = True
    elif fault == "binding":
        report["binding"]["format"]["input_ports"].reverse()
    elif fault == "error":
        report["error"] = "gap"
    elif fault == "failed":
        report["failed"] = True
    elif fault == "xrun":
        report["input"]["xruns"] = 1
    elif fault == "closed":
        report["input"]["closed"] = False
    elif fault == "frames":
        report["input"]["frames"] -= 1
    elif fault == "boolean_counter":
        report["input"]["errors"] = False
    elif fault == "terminate":
        report["input"]["terminated"] = False
    elif fault == "rate":
        report["input"]["reported_rate"] = 44100.0
    elif fault == "stop":
        report["stop_ms"] = None
    else:
        report["queue"]["channels"] = 16
    with pytest.raises(fft.ReferenceError):
        live.validate_metrics(report, request)
