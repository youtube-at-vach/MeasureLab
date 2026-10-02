"""A reader receipt, unknown legacy provenance or clipped UI must not imply success."""

from copy import deepcopy
import json
import subprocess
import sys

import pytest

from scripts import migration_qt_import as reader


def ui(language):
    catalog = json.loads((reader.ROOT / f"src/assets/lang/{language}.json").read_text())
    labels = {
        key: catalog["migration.display." + suffix]
        for key, suffix in {
            "title": "import_open",
            "path": "import_path",
            "spec": "import_spec",
            "trace": "import_trace",
            "note": "import_note",
            "read": "import_open",
            "cancel": "import_cancel",
            "close": "calibration_close",
            "status": "import_loaded",
            "provenance": "import_unknown",
            "relation": "import_original",
        }.items()
    }
    return {
        "lifecycle": True,
        "blocked_gui_fft": 3,
        "minimum": [900, 600],
        "size": [1000, 640],
        "dialog": {"labels": labels, "labels_fit": True, "size": [720, 610]},
        "states": {key: catalog["migration.display.import_" + key] for key in ("failed", "rejected", "closed")},
    }


@pytest.mark.parametrize("language", reader.LANGUAGES)
def test_all_languages_preserve_import_meaning_and_geometry(language):
    reader.validate_ui(ui(language), language)


@pytest.mark.parametrize(
    "fault",
    ["language", "clipped", "oversize", "undersize", "nan", "lifecycle", "blocked", "failed", "rejected", "closed"],
)
def test_bad_import_ui_evidence_is_rejected(fault):
    record = ui("ja")
    if fault == "language":
        record["dialog"]["labels"] = ui("en")["dialog"]["labels"]
    elif fault == "clipped":
        record["dialog"]["labels_fit"] = False
    elif fault == "oversize":
        record["dialog"]["size"][1] = 691
    elif fault == "undersize":
        record["size"][0] = 600
    elif fault == "nan":
        record["size"][0] = float("nan")
    elif fault == "lifecycle":
        record["lifecycle"] = False
    elif fault in ("failed", "rejected", "closed"):
        record["states"][fault] = ""
    else:
        record["blocked_gui_fft"] = 0
    with pytest.raises(reader.fft.ReferenceError):
        reader.validate_ui(record, "ja")


def test_actual_exporters_import_with_unknown_provenance_and_preserved_secondary_axis(tmp_path):
    directory = tmp_path / "inputs"
    hashes = reader.prepare_inputs(directory)
    document = reader.compatibility.legacy_document()
    original = deepcopy(document)
    imported = reader.product.import_json(reader.product.read_file(directory / "legacy.json"))
    preview = reader.preview_for(imported)
    assert imported.acquisition == reader.product.UNKNOWN
    assert imported.snapshot is None
    assert preview["has_snapshot"] is False
    assert preview["invalid_spans"] is None
    assert preview["traces"][0]["rows"] == [
        {"index": 0, "x": 0.0, "y": -9.0, "y2": -180.0},
        {"index": 1, "x": 1.0, "y": -3.5, "y2": 0.0},
        {"index": 2, "x": 2.0, "y": 0.0, "y2": 180.0},
    ]
    assert preview["traces"][0]["y_axis"] == document["traces"][0]["y_axis"]
    assert reader.product.load_csv_pair(directory / "legacy.csv").document == document
    merged = reader.product.import_csv(
        reader.product.read_file(directory / "merged.csv"), json.loads((directory / "merged.spec.json").read_text())
    )
    assert merged.sample_relation == "merged_grid_may_be_interpolated"
    assert merged.snapshot is None and merged.acquisition == reader.product.UNKNOWN
    assert merged.document["traces"][0]["y_data"] == [-9.0, -6.25, -3.5, -1.75, 0.0]
    assert document == original
    assert all(reader.sha256(reader.Path(p)) == digest for p, digest in hashes.items())


@pytest.mark.parametrize("fault", ["no_marker", "duplicate_marker", "wrong_language", "no_teardown"])
def test_missing_lifecycle_markers_cannot_pass_even_with_zero_exit(tmp_path, fault):
    marker = "DISPLAY_IMPORT " + json.dumps(ui("en")) + "\n"
    text = "DISPLAY_LANGUAGE en\nDISPLAY_IMPORT_TEARDOWN sessions=0\n" + marker
    if fault == "no_marker":
        text = text.replace(marker, "")
    elif fault == "duplicate_marker":
        text += marker
    elif fault == "wrong_language":
        text = text.replace("DISPLAY_LANGUAGE en", "DISPLAY_LANGUAGE ja")
    else:
        text = text.replace("DISPLAY_IMPORT_TEARDOWN sessions=0", "")
    with pytest.raises(reader.fft.ReferenceError, match="lifecycle/language"):
        reader.validate_run(text, tmp_path, tmp_path / "inputs", {}, {}, "en", {})


def test_import_runner_keeps_gui_and_devices_out_of_python(tmp_path):
    result = subprocess.run(
        [sys.executable, "-c", "from scripts import migration_qt_import as r; r.fft.assert_headless()"],
        cwd=reader.ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("fault", [None, "number", "signed_zero", "nonfinite", "index", "value"])
def test_preview_decimal_tokens_keep_original_signed_zero_and_positions(fault):
    document = reader.compatibility.legacy_document()
    document["traces"][0]["y_data"][0] = -0.0
    imported = reader.product.import_document(document)
    preview = reader.preview_for(imported)
    for trace in preview["traces"]:
        for row in trace["rows"]:
            for key in ("x", "y", "y2"):
                if row[key] is not None:
                    row[key] = repr(row[key])
    row = preview["traces"][0]["rows"][0]
    if fault == "number":
        row["y"] = -0.0
    elif fault == "signed_zero":
        row["y"] = "0.0"
    elif fault == "nonfinite":
        row["y"] = "NaN"
    elif fault == "index":
        row["index"] = 1
    elif fault == "value":
        row["y"] = "-0.00001"
    if fault:
        with pytest.raises(reader.fft.ReferenceError):
            reader.validate_preview(preview, imported)
    else:
        reader.validate_preview(preview, imported)
