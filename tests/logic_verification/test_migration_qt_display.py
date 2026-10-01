"""Reject false display passes, stale result metadata, and empty plot images."""

import json
import os
import struct
import sys
import zlib

import numpy as np
import pytest

from scripts import migration_audio_graph as audio
from scripts import migration_core_reference as core
from scripts import migration_fft_reference as fft
from scripts.migration_qt_display import PASS, inspect_png, run_display, validate_evidence


@pytest.fixture
def case():
    return json.loads((core.DEFAULT_FIXTURES / "manifest.json").read_bytes())["tones"][0]


def executable(tmp_path, output, code=0, sleep=0):
    path = tmp_path / "display"
    path.write_text(
        f"#!{sys.executable}\nimport time\nprint({output!r}, flush=True)\ntime.sleep({sleep})\nraise SystemExit({code})\n"
    )
    path.chmod(0o700)
    return path


@pytest.mark.parametrize(
    "extra,code", [("", 0), ("DISPLAY_FAIL broken", 0), ("TypeError: bad", 0), ("Binding loop", 0), ("", 1)]
)
def test_clean_exit_or_markers_without_artifacts_do_not_pass(tmp_path, case, extra, code):
    output = f"DISPLAY_READY\n{PASS}\nDISPLAY_IMAGE_OK\nDISPLAY_TEARDOWN workers=0 models=0\n{extra}"
    binary = executable(tmp_path, output, code)
    result = run_display(binary, dict(os.environ), tmp_path / "run", case, 2)
    assert not result["passed"]


def test_timeout_preserves_partial_output(tmp_path, case):
    result = run_display(executable(tmp_path, "DISPLAY_READY", sleep=10), dict(os.environ), tmp_path / "run", case, 0.1)
    assert not result["passed"] and result["reason"] == "timeout"
    assert "DISPLAY_READY" in result["output"]


def evidence(tmp_path, case):
    source = core.DEFAULT_FIXTURES / case["spec"]["id"]
    peaks = fft.read_array(source, case["arrays"]["theory.peak_fs"])
    axis = fft.read_array(source, case["arrays"]["theory.frequency_hz"])
    document = {
        "source": audio.expected_source(audio.request_for(case)),
        "interval": [0, case["spec"]["n"]],
        "validity": [],
        "error": None,
        "axis": {"unit": "Hz", "corrected": axis.tolist()},
        "columns": {
            "peak_fs": {"shape": list(peaks.shape), "values": peaks.ravel().tolist()},
            "rms_v": {"values": [None] * peaks.shape[1], "reasons": ["uncalibrated"] * peaks.shape[1]},
        },
    }
    for generation in (3, 4, 5):
        document["source"]["generation"] = document["source"]["timebase"]["generation"] = generation
        (tmp_path / f"generation-{generation}.json").write_text(json.dumps(document))
    return tmp_path / "generation-5.json"


def test_three_independent_fixture_results_pass(tmp_path, case):
    evidence(tmp_path, case)
    assert len(validate_evidence(tmp_path, case)) == 3


@pytest.mark.parametrize("mutation", ["clock", "channels", "interval", "numeric", "calibration", "generation", "axis"])
def test_bad_result_evidence_rejected(tmp_path, case, mutation):
    path = evidence(tmp_path, case)
    document = json.loads(path.read_bytes())
    if mutation == "clock":
        document["source"]["timebase"]["origin_seconds"] = 0
    elif mutation == "channels":
        document["source"]["channel_ids"].reverse()
    elif mutation == "interval":
        document["interval"][0] = 1
    elif mutation == "numeric":
        document["columns"]["peak_fs"]["values"][37 * 4] = 1
    elif mutation == "calibration":
        document["columns"]["rms_v"]["values"][0] = 1
    elif mutation == "generation":
        document["source"]["generation"] = document["source"]["timebase"]["generation"] = 4
    else:
        document["axis"]["corrected"][37] += 1
    path.write_text(json.dumps(document))
    with pytest.raises(fft.ReferenceError):
        validate_evidence(tmp_path, case)


def png(path, populated):
    def chunk(kind, payload):
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload))

    rgb = np.zeros((640, 1000, 3), dtype=np.uint8)
    if populated:
        rgb[220:230, 100:110] = [98, 216, 233]
        rgb[220:230, 600:610] = [30, 120, 200]
    rows = b"".join(b"\0" + row.tobytes() for row in rgb)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1000, 640, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


def test_saved_image_requires_both_plots_and_valid_crc(tmp_path):
    path = tmp_path / "image.png"
    png(path, True)
    assert inspect_png(path)["cyan_line_pixels"] == 100
    png(path, False)
    with pytest.raises(fft.ReferenceError, match="missing rendered"):
        inspect_png(path)
    png(path, True)
    data = bytearray(path.read_bytes())
    data[-5] ^= 1
    path.write_bytes(data)
    with pytest.raises(fft.ReferenceError, match="CRC"):
        inspect_png(path)
