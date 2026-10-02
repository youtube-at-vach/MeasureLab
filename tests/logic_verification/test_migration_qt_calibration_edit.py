"""Reject stale/misbound edited-profile evidence and clipped/untranslated editors."""

from copy import deepcopy
import json
import subprocess
import sys

import pytest

from scripts import migration_qt_calibration_edit as edit


def request():
    config = {
        "live": None,
        "format": {
            "stream_id": "saved.test",
            "generation": 1,
            "input_ids": ["a", "b", "c", "d"],
            "input_ports": [3, 1, 0, 2],
        },
    }
    config["calibration"] = edit.calibration.diagnostic_profiles(config)
    return config


def proof(directory):
    config = request()
    profiles = edit.edited_profiles(config)
    channels = [
        {"channel_id": c, "device_binding": {"device": "saved:saved.test", "port": p}}
        for c, p in zip(config["format"]["input_ids"], config["format"]["input_ports"], strict=True)
    ]
    record = {}
    for key, revision, status, profile_key in (
        ("initial", 0, "ready", "initial"),
        ("edited", 1, "applied", "edited"),
        ("rejected", 2, "rejected", "edited"),
        ("disabled", 3, "applied", "disabled"),
        ("added", 4, "applied", "added"),
    ):
        record[key] = {
            "schema_version": 1,
            "generation": 1,
            "revision": revision,
            "status": status,
            "reason": "display_calibration_binding" if key == "rejected" else None,
            "channels": deepcopy(channels),
            "profiles": deepcopy(profiles[profile_key]),
        }
        if revision:
            (directory / f"calibration-1-{revision}.json").write_text(json.dumps(record[key]))
    for revision in (1, 3, 4):
        (directory / f"calibration-1-{revision}.result.json").write_text("{}")
    return config, record


def ui(language):
    catalog = json.loads((edit.ROOT / f"src/assets/lang/{language}.json").read_text())
    suffixes = {
        "title": "edit",
        "channel": "channel",
        "factor": "factor",
        "revision": "revision",
        "calibrated": "enabled",
        "apply": "apply",
        "close": "close",
        "note": "note",
        "status": "rejected",
    }
    return {
        "shared_raw": True,
        "hold_immutable": True,
        "detached_hold": True,
        "restart": True,
        "recreate": True,
        "blocked_gui_fft": 3,
        "minimum": [700, 578],
        "size": [1000, 640],
        "editor": {
            "labels_fit": True,
            "size": [480, 400],
            "labels": {k: catalog["migration.display.calibration_" + v] for k, v in suffixes.items()},
        },
    }


def output(record, language):
    return f"DISPLAY_LANGUAGE {language}\nqml: DISPLAY_CALIBRATION_EDIT {json.dumps(record)}\n"


@pytest.mark.parametrize("language", edit.LANGUAGES)
def test_actual_translation_editor_inventory_and_geometry(language):
    record = ui(language)
    assert edit.validate_ui(output(record, language), language) == record


@pytest.mark.parametrize(
    "fault", ["labels", "clipped", "width", "height", "minimum", "undersized", "lifecycle", "advance", "repeated"]
)
def test_untranslated_clipped_or_incomplete_editor_rejected(fault):
    record = ui("ja")
    if fault == "labels":
        record["editor"]["labels"] = ui("en")["editor"]["labels"]
    elif fault == "clipped":
        record["editor"]["labels_fit"] = False
    elif fault in ("width", "height"):
        record["editor"]["size"][int(fault == "height")] = 2000
    elif fault == "minimum":
        record["minimum"][0] = 1181
    elif fault == "undersized":
        record["size"][0] = 100
    elif fault == "lifecycle":
        record["hold_immutable"] = False
    elif fault == "advance":
        record["blocked_gui_fft"] = 0
    text = output(record, "ja")
    if fault == "repeated":
        text += text
    with pytest.raises(edit.fft.ReferenceError):
        edit.validate_ui(text, "ja")


def test_edited_profiles_follow_ids_and_preserve_disabled_absent_bindings(tmp_path):
    config, record = proof(tmp_path)
    original = deepcopy(config)
    _, states = edit.validate_configurations(record, tmp_path, config)
    assert config == original
    assert states["edited"][-1]["channel_id"] == "a"
    assert states["edited"][-1]["device_binding"]["port"] == 3
    assert states["disabled"][-1]["is_calibrated"] is False
    assert states["added"][-1]["channel_id"] == "d"
    assert states["added"][-1]["device_binding"]["port"] == 2


@pytest.mark.parametrize(
    "fault",
    [
        "generation",
        "revision",
        "status",
        "reason",
        "channel",
        "port",
        "factor",
        "enabled",
        "rejection_atomicity",
        "file",
        "missing",
        "extra",
    ],
)
def test_mutated_profile_or_receipt_evidence_rejected(tmp_path, fault):
    config, record = proof(tmp_path)
    if fault in ("generation", "revision", "status", "reason"):
        record["edited"][fault] = {"generation": 2, "revision": 99, "status": "queued", "reason": "failed"}[fault]
    elif fault in ("channel", "port", "factor", "enabled"):
        profile = record["edited"]["profiles"][-1]
        if fault == "channel":
            profile["channel_id"] = "d"
        elif fault == "port":
            profile["device_binding"]["port"] = 2
        elif fault == "factor":
            profile["v_per_fs"] = 3.6
        else:
            profile["is_calibrated"] = False
    elif fault == "rejection_atomicity":
        record["rejected"]["profiles"][-1]["revision"] = "partial.apply"
    elif fault == "file":
        (tmp_path / "calibration-1-1.json").write_text(json.dumps(record["initial"]))
    elif fault == "missing":
        (tmp_path / "calibration-1-3.result.json").unlink()
    else:
        (tmp_path / "calibration-1-99.json").write_text("{}")
    with pytest.raises((edit.fft.ReferenceError, OSError)):
        edit.validate_configurations(record, tmp_path, config)


def test_qml_integer_spelling_preserves_values_and_rejects_identity_or_bool_coercion():
    expected = {"value": 2.0, "revision": 2}
    edit.exact_qml({"value": 2, "revision": 2}, expected, "numbers")
    for broken in ({"value": 2.1, "revision": 2}, {"value": True, "revision": 2}, {"value": 2, "revision": 2.0}):
        with pytest.raises(edit.fft.ReferenceError):
            edit.exact_qml(broken, expected, "numbers")


def test_edit_runner_import_remains_headless():
    result = subprocess.run(
        [sys.executable, "-c", "from scripts import migration_qt_calibration_edit as e; e.fft.assert_headless()"],
        cwd=edit.ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
