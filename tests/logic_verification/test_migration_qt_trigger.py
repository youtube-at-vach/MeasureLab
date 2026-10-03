"""Qt trigger evidence checks stay runnable with NumPy alone and no devices."""

import json
import subprocess
import sys

import pytest

from scripts import migration_qt_trigger as qt


@pytest.fixture
def receipt():
    request = {"n": 8, "format": {"stream_id": "saved.input", "generation": 1, "timebase_id": "saved.clock"}}
    result = {
        "schema_version": 1,
        "revision": 1,
        "request": {
            "request_id": "qt.manual.1",
            "pre": 4,
            "post": 4,
            "event": {
                "id": "qt.event.1",
                "stream_id": "saved.input",
                "generation": 1,
                "timebase_id": "saved.clock",
                "sample": {"numerator": 41, "denominator": 2},
                "source": "qt.manual",
                "kind": "manual",
                "polarity": "none",
                "condition_revision": "manual.v1",
                "validity": [],
                "received_host_seconds": None,
            },
        },
        "status": "pending",
        "reason": None,
        "fractional_residual": {"numerator": 1, "denominator": 2},
        "history": {
            "stream_id": "saved.input",
            "generation": 1,
            "timebase_id": "saved.clock",
            "interval": [16, 24],
            "status": "pending",
            "pending": [[16, 24]],
            "missing": [],
            "reason": None,
        },
        "frame": None,
        "fft_origin": "none",
        "acquired_until": 8,
        "trigger_evaluations": 0,
        "continuous_evaluations": 1,
    }
    return request, result


def test_sample_interval_uses_event_and_preserves_fraction(receipt):
    request, observed = receipt
    assert qt.validate_receipt(observed, request) == 16
    observed["acquired_until"] = 20
    observed["history"]["pending"] = [[20, 24]]
    assert qt.validate_receipt(observed, request) == 16


@pytest.mark.parametrize(
    "fault",
    [
        "frame",
        "generation",
        "interval",
        "pending",
        "fraction",
        "received_time",
        "counter",
        "revision_type",
        "extra",
        "false_complete",
        "fft_origin",
        "schema_type",
    ],
)
def test_rejects_fabricated_trigger_receipt(receipt, fault):
    request, observed = receipt
    if fault == "frame":
        observed["frame"] = {"peak_fs": {"values": [0]}}
    elif fault == "generation":
        observed["request"]["event"]["generation"] = 2
    elif fault == "interval":
        observed["history"]["interval"] = [17, 25]
    elif fault == "pending":
        observed["history"]["pending"] = []
    elif fault == "fraction":
        observed["fractional_residual"]["numerator"] = 0
    elif fault == "received_time":
        observed["request"]["event"]["received_host_seconds"] = {"numerator": 20, "denominator": 1}
    elif fault == "counter":
        observed["trigger_evaluations"] = True
    elif fault == "revision_type":
        observed["revision"] = True
    elif fault == "extra":
        observed["ignored"] = 1
    elif fault == "false_complete":
        observed["status"] = "complete"
    elif fault == "fft_origin":
        observed["fft_origin"] = "computed"
    else:
        observed["schema_version"] = True
    with pytest.raises(qt.fft.ReferenceError):
        qt.validate_receipt(observed, request)


def ui_record(language="ja"):
    catalog = json.loads((qt.ROOT / f"src/assets/lang/{language}.json").read_text())
    return {
        **dict.fromkeys(qt.LIFECYCLE, True),
        "blocked_gui_fft": 3,
        "buttons_fit": True,
        "minimum": [900, 560],
        "size": [1000, 640],
        "labels": {
            k: catalog["migration.display.trigger_" + suffix]
            for k, suffix in {
                "capture": "capture",
                "retry": "retry",
                "release": "release",
                "sample": "sample",
                "status": "complete",
            }.items()
        },
    }


@pytest.mark.parametrize("language", qt.LANGUAGES)
def test_translated_trigger_ui_evidence(language):
    record = ui_record(language)
    output = f"DISPLAY_LANGUAGE {language}\nDISPLAY_TRIGGER {json.dumps(record)}\n"
    assert qt.validate_ui(output, language) == record


@pytest.mark.parametrize(
    "fault", ["lifecycle", "clipping", "translation", "size", "size_type", "language", "duplicate", "no_acquisition"]
)
def test_rejects_missing_hold_lifetime_and_clipped_ui(fault):
    record = ui_record()
    if fault == "lifecycle":
        record["hold_continued"] = False
    elif fault == "clipping":
        record["buttons_fit"] = False
    elif fault == "translation":
        record["labels"]["capture"] = "Hold at trigger"
    elif fault == "size":
        record["minimum"][0] = 1181
    elif fault == "size_type":
        record["minimum"][0] = True
    elif fault == "no_acquisition":
        record["blocked_gui_fft"] = 0
    output = f"DISPLAY_LANGUAGE {'en' if fault == 'language' else 'ja'}\nDISPLAY_TRIGGER {json.dumps(record)}\n"
    if fault == "duplicate":
        output += f"DISPLAY_TRIGGER {json.dumps(record)}\n"
    with pytest.raises(qt.fft.ReferenceError):
        qt.validate_ui(output, "ja")


def test_runner_import_does_not_load_gui_or_audio_runtime():
    result = subprocess.run(
        [sys.executable, "-c", "from scripts import migration_qt_trigger; migration_qt_trigger.fft.assert_headless()"],
        cwd=qt.ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
