"""Reject misbound calibration, fabricated voltage, lost relative data and CSV corruption."""

from copy import deepcopy
import csv
import io
import json
import subprocess
import sys

import numpy as np
import pytest

from scripts import migration_qt_calibration as calibration
from scripts.migration_qt_display import projection_for


@pytest.fixture
def proof():
    request = {
        "format": {
            "stream_id": "saved.test",
            "generation": 2,
            "timebase_id": "clock.test",
            "clock_domain": "saved.test",
            "rate": [48000, 1],
            "input_ids": ["a", "b", "c", "d"],
            "input_ports": [3, 1, 0, 2],
            "output_ids": [],
            "output_ports": [],
        },
        "n": 8,
        "precision": "F64",
        "window": "Boxcar",
    }
    request["calibration"] = calibration.diagnostic_profiles(request)
    samples = np.arange(32, dtype=float).reshape(8, 4) / 128
    z = np.fft.rfft(samples, axis=0) / 8
    arrays = calibration.oracle.quantities(z, np.ones(8), samples, 48000)
    arrays.pop("frequency_hz")
    arrays.update(
        window=np.ones(8),
        inverse_windowed=samples,
        fft_over_n=np.stack((z.real, z.imag), axis=-1),
        tone_rms_fs=arrays["peak_fs"] / np.sqrt(2),
        asd_fs_sqrt_hz=np.sqrt(arrays["psd_fs2_hz"]),
    )
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
            "shape": list(array.shape),
            "unit": units[name],
            "precision": "F64",
            "values": array.ravel().tolist(),
            "reasons": [None] * array.size,
        }
        for name, array in arrays.items()
    }
    factors = np.array([2, 2.25, 2.5, 1])
    voltage = arrays["rms_fs"] * factors
    for name, values, unit in (
        ("rms_v", voltage, "V_RMS"),
        ("dbv", 20 * np.log10(voltage), "dBV_RMS"),
        ("psd_v2_hz", arrays["psd_fs2_hz"] * factors**2, "V2/Hz"),
        ("spl", np.zeros(4), "dBSPL"),
    ):
        enabled = [name != "spl" and i % 4 < 2 for i in range(values.size)]
        columns[name] = {
            "shape": list(values.shape),
            "unit": unit,
            "precision": "F64",
            "values": [float(v) if enabled[i] else None for i, v in enumerate(values.ravel())],
            "reasons": [None if e else "uncalibrated" for e in enabled],
        }
    source = calibration.audio.expected_source(request)
    document = {
        "schema_version": 1,
        "source": source,
        "operation_revision": calibration.trigger.graph.TRANSFORM_REVISION,
        "interval": [8, 16],
        "raw_result_id": [3, 4],
        "validity": [],
        "error": None,
        "capture": {
            "result_id": "3:4",
            "trigger_id": None,
            "trigger": None,
            "acquired_host_seconds": None,
            "result_host_seconds": None,
            "clock_mapping": None,
        },
        "conditions": {
            "source": source,
            "n": 8,
            "hop": 8,
            "alignment": 0,
            "window": "Boxcar",
            "remove_dc": False,
            "input_gains": [],
        },
        "calibration": calibration.expected_calibration(request, [8, 16]),
        "axis": {
            "dimension": "frequency",
            "unit": "Hz",
            "nominal": [float(i * 6000) for i in range(5)],
            "corrected": [float(i * 6000) for i in range(5)],
            "correction": 1.0,
        },
        "columns": columns,
    }
    return request, samples, document


def test_all_relative_arrays_and_partial_voltage_from_input(proof):
    request, samples, document = proof
    comparisons = calibration.validate_result(document, request, samples)
    assert set(comparisons) >= {"rms_v", "dbv", "psd_v2_hz", "fft_over_n", "inverse_windowed"}
    projection = projection_for(document)
    assert projection["calibration"] == "partial"
    assert projection["channel_calibration"] == document["calibration"]


@pytest.mark.parametrize(
    "fault",
    [
        "port",
        "device",
        "channel",
        "revision",
        "interval",
        "disabled",
        "missing",
        "factor",
        "voltage",
        "psd",
        "dbv",
        "spl",
        "unit",
        "precision",
        "shape",
        "reason",
        "raw",
        "clock",
        "generation",
        "id",
    ],
)
def test_calibration_proof_corruption_is_rejected(proof, fault):
    request, samples, document = proof
    p = document["calibration"][0]["profile"]
    if fault in ("port", "device"):
        p["device_binding"][fault] = 1 if fault == "port" else "other"
    elif fault == "channel":
        document["calibration"].reverse()
    elif fault == "revision":
        p["revision"] = "replacement"
    elif fault == "interval":
        p["applied_interval"] = [0, 8]
    elif fault == "disabled":
        document["columns"]["rms_v"]["values"][2] = 1
    elif fault == "missing":
        document["columns"]["dbv"]["values"][3] = 0
    elif fault == "factor":
        p["v_per_fs"] = 1
    elif fault in ("voltage", "psd", "dbv", "spl"):
        name = {"voltage": "rms_v", "psd": "psd_v2_hz"}.get(fault, fault)
        document["columns"][name]["values"][0] = 999
    elif fault in ("unit", "precision", "shape", "reason"):
        name, value = {
            "unit": ("unit", "FS"),
            "precision": ("precision", "F32"),
            "shape": ("shape", [2, 2]),
            "reason": ("reasons", [None] * 4),
        }[fault]
        document["columns"]["rms_v"][name] = value
    elif fault == "raw":
        document["columns"]["peak_fs"]["values"][0] = 999
    elif fault == "clock":
        document["source"]["timebase"]["origin_seconds"] = {"numerator": 0, "denominator": 1}
    elif fault == "generation":
        document["source"]["generation"] = 1
    else:
        document["capture"]["result_id"] = "old:3:4"
    with pytest.raises(calibration.fft.ReferenceError):
        calibration.validate_result(document, request, samples)


def exchange(path, document):
    metadata = deepcopy(document)
    for c in metadata["columns"].values():
        c["values"], c["reasons"] = [], []
    rows = [["# MIG-006-E exchange v1", json.dumps(metadata)], ["metric", "index", "value", "reason"]]
    for name, c in document["columns"].items():
        rows += [
            [name, str(i), "" if v is None else str(v), r or ""]
            for i, (v, r) in enumerate(zip(c["values"], c["reasons"], strict=True))
        ]
    stream = io.StringIO(newline="")
    csv.writer(stream, quoting=csv.QUOTE_ALL, lineterminator="\n").writerows(rows)
    path.write_text(json.dumps(document))
    path.with_suffix(".csv").write_text(stream.getvalue())


def test_full_exchange_roundtrip_rejects_lost_rows_and_changed_revision(tmp_path, proof):
    _, _, document = proof
    path = tmp_path / "generation.json"
    exchange(path, document)
    assert len(calibration.validate_exchange(path)) == 2
    csv_path = path.with_suffix(".csv")
    original = csv_path.read_text()
    csv_path.write_text(original[: original.rfind("\n", 0, -1) + 1])
    with pytest.raises(calibration.fft.ReferenceError):
        calibration.validate_exchange(path)
    csv_path.write_text(original.replace("diag.c0", "wrong.c0"))
    with pytest.raises(calibration.fft.ReferenceError):
        calibration.validate_exchange(path)


def test_import_is_headless():
    result = subprocess.run(
        [sys.executable, "-c", "from scripts import migration_qt_calibration as c; c.fft.assert_headless()"],
        cwd=calibration.ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def ui_record(document, language):
    catalog = json.loads((calibration.ROOT / f"src/assets/lang/{language}.json").read_text())

    def text(key, *values):
        result = catalog["migration.display." + key]
        for index, value in enumerate(values, 1):
            result = result.replace(f"%{index}", str(value))
        return result

    profile = document["calibration"][0]["profile"]
    return {
        "calibration": {
            "result_id": document["capture"]["result_id"],
            "labels_fit": True,
            "spectrum": {
                "channel": 0,
                "voltage": text(
                    "voltage",
                    format(document["columns"]["rms_v"]["values"][0], ".8g"),
                    format(document["columns"]["dbv"]["values"][0], ".8g"),
                ),
                "profile": text(
                    "calibration_profile", profile["v_per_fs"], profile["revision"], profile["device_binding"]["port"]
                ),
            },
            "spectrogram": {"channel": 3, "voltage": text("voltage_uncalibrated"), "profile": ""},
        }
    }


@pytest.mark.parametrize("language", calibration.LANGUAGES)
def test_voltage_and_profile_labels_use_result_and_translation(tmp_path, proof, language):
    _, _, document = proof
    (tmp_path / "trigger-2-2-complete.result.json").write_text(json.dumps(document))
    assert calibration.validate_ui(ui_record(document, language), tmp_path, language)


@pytest.mark.parametrize(
    "fault", ["result", "value", "revision", "port", "channel", "language", "clipped", "uncalibrated"]
)
def test_displayed_calibration_corruption_rejected(tmp_path, proof, fault):
    _, _, document = proof
    (tmp_path / "trigger-2-2-complete.result.json").write_text(json.dumps(document))
    record = ui_record(document, "ja")
    current = record["calibration"]
    if fault == "result":
        current["result_id"] = "old"
    elif fault == "value":
        current["spectrum"]["voltage"] = current["spectrum"]["voltage"].replace(": ", ": 9", 1)
    elif fault == "revision":
        current["spectrum"]["profile"] = current["spectrum"]["profile"].replace("diag.c0", "old")
    elif fault == "port":
        current["spectrum"]["profile"] = current["spectrum"]["profile"].replace("ポート 3", "ポート 1")
    elif fault == "channel":
        current["spectrum"]["channel"] = 1
    elif fault == "language":
        record = ui_record(document, "en")
    elif fault == "clipped":
        current["labels_fit"] = False
    else:
        current["spectrogram"]["voltage"] = "0 V"
    with pytest.raises(calibration.fft.ReferenceError):
        calibration.validate_ui(record, tmp_path, "ja")
