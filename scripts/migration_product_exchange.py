"""MIG-006-E-compat evaluation adapter; does not change the product file schema.

Use the actual ExportTrace/exporters on a file worker, never an audio callback or GUI.
Legacy traces are observations with unknown acquisition provenance, not invented Results.
"""

from __future__ import annotations

import copy
import csv
from dataclasses import dataclass
import hashlib
import io
import math
import os
from pathlib import Path
import tempfile

from scripts import migration_core_reference as core
from scripts import migration_fft_candidate as candidate
from scripts import migration_fft_reference as fft
from src.core.export.csv_exporter import CsvTraceExporter
from src.core.export.json_exporter import JsonTraceExporter
from src.core.export.trace import ExportTrace

MAX_BYTES = 256 * 1024 * 1024
MAX_VALUES = 4_000_000
MARKER = "mig_006_e_snapshot"
CSV_KIND = "MIG-006-E-product-csv"
UNKNOWN = dict.fromkeys(
    ("stream_id", "generation", "channel_ids", "interval", "timebase", "trigger", "route_revision", "tap")
)
TRACE_KEYS = {
    "id",
    "name",
    "source_module",
    "timestamp",
    "plot_type",
    "x_axis",
    "y_axis",
    "y2_axis",
    "x_data",
    "y_data",
    "y2_data",
    "calibration",
    "metadata",
}
AXIS_KEYS = {"dimension", "base_unit", "display_unit", "is_log"}
CALIBRATION_KEYS = {"is_calibrated", "input_sensitivity", "applied_offset_db", "reference_level"}


def read_file(path):
    with Path(path).open("rb") as stream:
        data = stream.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise fft.ReferenceError("Product file capacity exceeded")
    return data


def unique_json(payload):
    if len(payload) > MAX_BYTES:
        raise fft.ReferenceError("Product file capacity exceeded")
    return core.read_json(payload)


def finite(value):
    try:
        return type(value) in (int, float) and math.isfinite(value) and float(value) == value
    except OverflowError:
        return False


def validate_axis(axis):
    if (
        not isinstance(axis, dict)
        or set(axis) != AXIS_KEYS
        or any(not isinstance(axis[k], str) for k in AXIS_KEYS - {"is_log"})
        or type(axis["is_log"]) is not bool
    ):
        raise fft.ReferenceError("Invalid legacy axis metadata")


def validate_document(document):
    if (
        not isinstance(document, dict)
        or set(document) != {"version", "traces"}
        or document["version"] != "1.0"
        or not isinstance(document["traces"], list)
        or len(document["traces"]) > 1024
    ):
        raise fft.ReferenceError("Unsupported product JSON schema")
    document = copy.deepcopy(document)
    ids, count = set(), 0
    for trace in document["traces"]:
        if not isinstance(trace, dict) or set(trace) != TRACE_KEYS:
            raise fft.ReferenceError("Invalid ExportTrace fields")
        if any(not isinstance(trace[k], str) for k in ("id", "name", "source_module", "timestamp", "plot_type")):
            raise fft.ReferenceError("Invalid legacy trace identity")
        if not trace["id"] or trace["id"] in ids or not isinstance(trace["metadata"], dict):
            raise fft.ReferenceError("Duplicate/empty trace ID or invalid metadata")
        ids.add(trace["id"])
        for key in ("x_axis", "y_axis"):
            validate_axis(trace[key])
        y2 = trace["y2_data"] is not None
        if y2 != (trace["y2_axis"] is not None):
            raise fft.ReferenceError("Secondary axis/data mismatch")
        if y2:
            validate_axis(trace["y2_axis"])
        for key in ("x_data", "y_data", "y2_data") if y2 else ("x_data", "y_data"):
            values = trace[key]
            if not isinstance(values, list) or any(not finite(v) for v in values):
                raise fft.ReferenceError("Legacy trace requires finite arrays")
            trace[key] = [float(v) for v in values]
            count += len(values)
        if len(trace["x_data"]) != len(trace["y_data"]) or (y2 and len(trace["x_data"]) != len(trace["y2_data"])):
            raise fft.ReferenceError("Legacy trace array length mismatch")
        c = trace["calibration"]
        if (
            not isinstance(c, dict)
            or set(c) != CALIBRATION_KEYS
            or type(c["is_calibrated"]) is not bool
            or not finite(c["input_sensitivity"])
            or c["input_sensitivity"] <= 0
            or not finite(c["applied_offset_db"])
            or c["reference_level"] not in ("relative", "absolute")
        ):
            raise fft.ReferenceError("Invalid legacy calibration")
    if count > MAX_VALUES:
        raise fft.ReferenceError("Product trace numeric capacity exceeded")
    # Also reject nonfinite numbers nested in arbitrary legacy metadata.
    core.json_bytes(document)
    return document


class NativeCodec:
    """Reuse the Rust Result reader as the authority; no second numeric contract."""

    def __init__(self, binary):
        self.binary = Path(binary)
        self.commands = []

    def decode(self, payload, fmt="json"):
        if fmt not in ("json", "csv") or len(payload) > MAX_BYTES:
            raise fft.ReferenceError("Invalid snapshot format/capacity")
        with tempfile.TemporaryDirectory(prefix="migration-product-read-") as temp:
            directory = Path(temp)
            path, output = directory / f"input.{fmt}", directory / "decoded"
            path.write_bytes(payload)
            self.commands.append(candidate.run_command([str(self.binary), f"--read-{fmt}", str(path), str(output)]))
            return unique_json(read_file(output / "result.json"))


def axis(dimension, unit):
    return {"dimension": dimension, "base_unit": unit, "display_unit": unit, "is_log": False}


def projection(snapshot):
    """Project validated native arrays without calibration, interpolation or decimation.

    The carrier preserves the entire snapshot once. Old ExportTrace cannot consume null
    numeric elements; those projections are explicitly listed as omitted, never zeroed.
    """
    source, columns = snapshot["source"], snapshot["columns"]
    channels = source["channel_ids"]
    n = snapshot["interval"][1] - snapshot["interval"][0]
    carrier = {
        "id": "mig.snapshot",
        "name": "Snapshot metadata (no measurement values)",
        "source_module": "MIG-006-E",
        "timestamp": "",  # Monotonic host seconds are not an ISO wall-clock timestamp.
        "plot_type": "spectrum",
        "x_axis": axis("frequency", "Hz"),
        "y_axis": axis("unknown", ""),
        "y2_axis": None,
        "x_data": [],
        "y_data": [],
        "y2_data": None,
        "calibration": {
            "is_calibrated": False,
            "input_sensitivity": 1.0,
            "applied_offset_db": 0.0,
            "reference_level": "relative",
        },
        "metadata": {},
    }
    traces, omitted = [carrier], []
    for metric, column in sorted(columns.items()):
        shape = column["shape"]
        for channel_index in range(1 if metric == "window" else len(channels)):
            channel_id = None if metric == "window" else channels[channel_index]
            y2 = None
            if metric == "window":
                indexes = list(range(n))
                x, x_axis = list(range(n)), axis("sample_offset", "sample")
            elif metric == "fft_over_n":
                indexes = list(range(2 * channel_index, len(column["values"]), 2 * len(channels)))
                y2 = [column["values"][i + 1] for i in indexes]
                x, x_axis = snapshot["axis"]["nominal"], axis("frequency", "Hz")
            elif metric == "inverse_windowed":
                indexes = list(range(channel_index, len(column["values"]), len(channels)))
                x, x_axis = list(range(n)), axis("sample_offset", "sample")
            elif len(shape) == 1:
                indexes = [channel_index]
                x, x_axis = [channel_index], axis("channel_index", "1")
            else:
                indexes = list(range(channel_index, len(column["values"]), len(channels)))
                x = snapshot["axis"]["corrected" if metric == "psd_v2_hz" else "nominal"]
                x_axis = axis("frequency", "Hz")
            y = [column["values"][i] for i in indexes]
            reason_indexes = indexes + ([i + 1 for i in indexes] if y2 is not None else [])
            reasons = [column["reasons"][i] for i in reason_indexes]
            if any(reason is not None for reason in reasons):
                omitted.append({"metric": metric, "channel_id": channel_id, "reasons": reasons})
                continue
            absolute = metric in {"rms_v", "dbv", "psd_v2_hz", "spl"}
            profile = None if channel_id is None else snapshot["calibration"][channel_index]["profile"]
            trace = copy.deepcopy(carrier)
            trace.update(
                {
                    "id": f"mig.{metric}.{channel_index}",
                    "name": f"{metric}: {channel_id or 'window'}",
                    "plot_type": "spectrum" if x_axis["dimension"] == "frequency" else "xy_plot",
                    "x_axis": x_axis,
                    "y_axis": axis("voltage" if absolute else "amplitude", column["unit"]),
                    "y2_axis": axis("amplitude", column["unit"]) if y2 is not None else None,
                    "x_data": x,
                    "y_data": y,
                    "y2_data": y2,
                    "calibration": {
                        "is_calibrated": bool(absolute and profile and profile["is_calibrated"]),
                        "input_sensitivity": profile["v_per_fs"] if profile else 1.0,
                        "applied_offset_db": 0.0,
                        "reference_level": "absolute" if absolute else "relative",
                    },
                    "metadata": {"metric": metric, "channel_id": channel_id, "precision": column["precision"]},
                }
            )
            traces.append(trace)
    carrier["metadata"][MARKER] = {"version": 1, "snapshot": copy.deepcopy(snapshot), "omitted": omitted}
    return validate_document({"version": "1.0", "traces": traces})


@dataclass
class Imported:
    document: dict
    snapshot: dict | None
    acquisition: dict
    sample_relation: str


def import_document(document, codec=None, *, relation="original_trace_arrays"):
    document = copy.deepcopy(validate_document(document))
    marked = [t for t in document["traces"] if MARKER in t["metadata"]]
    snapshot = None
    acquisition = UNKNOWN.copy()
    if marked:
        if codec is None or len(marked) != 1 or marked[0] is not document["traces"][0]:
            raise fft.ReferenceError("Snapshot carrier requires native validation and first/unique position")
        envelope = marked[0]["metadata"][MARKER]
        if (
            not isinstance(envelope, dict)
            or set(envelope) != {"version", "snapshot", "omitted"}
            or type(envelope["version"]) is not int
            or envelope["version"] != 1
        ):
            raise fft.ReferenceError("Unsupported snapshot compatibility envelope")
        snapshot = codec.decode(core.json_bytes(envelope["snapshot"]))
        if core.json_bytes(projection(snapshot)) != core.json_bytes(document):
            raise fft.ReferenceError("Product projections disagree with the retained snapshot")
        s = snapshot["source"]
        acquisition = {
            "stream_id": s["stream_id"],
            "generation": s["generation"],
            "channel_ids": s["channel_ids"],
            "interval": snapshot["interval"],
            "timebase": s["timebase"],
            "trigger": snapshot["capture"]["trigger"],
            "route_revision": s["route_revision"],
            "tap": s["tap"],
        }
    return Imported(document, snapshot, acquisition, relation)


def import_json(payload, codec=None):
    return import_document(unique_json(payload), codec)


def csv_spec(
    document, *, layout="independent", delimiter="comma", include_headers=True, include_metadata=True, utf8_bom=False
):
    """Explicit column descriptors. Never infer units/calibration from translated headers."""
    document = validate_document(document)
    if layout not in ("independent", "merged") or delimiter not in ("comma", "tab"):
        raise fft.ReferenceError("Unsupported CSV layout/delimiter")
    return {
        "options": {
            "layout": layout,
            "delimiter": delimiter,
            "include_headers": include_headers,
            "include_metadata": include_metadata,
            "utf8_bom": utf8_bom,
        },
        "descriptors": [
            {k: copy.deepcopy(v) for k, v in t.items() if k not in {"x_data", "y_data", "y2_data"}}
            for t in document["traces"]
        ],
    }


def import_csv(payload, spec, codec=None):
    if len(payload) > MAX_BYTES or not isinstance(spec, dict) or set(spec) != {"options", "descriptors"}:
        raise fft.ReferenceError("Invalid CSV capacity/descriptors")
    options, descriptors = spec["options"], spec["descriptors"]
    if (
        not isinstance(options, dict)
        or set(options) != {"layout", "delimiter", "include_headers", "include_metadata", "utf8_bom"}
        or options["layout"] not in ("independent", "merged")
        or options["delimiter"] not in ("comma", "tab")
        or any(type(options[k]) is not bool for k in ("include_headers", "include_metadata", "utf8_bom"))
        or not isinstance(descriptors, list)
    ):
        raise fft.ReferenceError("Unsupported CSV options")
    document = {"version": "1.0", "traces": []}
    for descriptor in descriptors:
        if not isinstance(descriptor, dict) or set(descriptor) != TRACE_KEYS - {"x_data", "y_data", "y2_data"}:
            raise fft.ReferenceError("Invalid CSV descriptor")
        document["traces"].append(
            {
                **copy.deepcopy(descriptor),
                "x_data": [],
                "y_data": [],
                "y2_data": [] if descriptor["y2_axis"] is not None else None,
            }
        )
    validate_document(document)
    text = payload.decode("utf-8-sig" if options["utf8_bom"] else "utf-8")
    try:
        rows = list(
            csv.reader(
                io.StringIO(text, newline=""), delimiter="," if options["delimiter"] == "comma" else "\t", strict=True
            )
        )
    except csv.Error as error:
        raise fft.ReferenceError(f"Invalid product CSV: {error}") from error
    if options["include_metadata"]:
        expected = [["# MeasureLab Exported Traces"]]
        exporter = CsvTraceExporter()
        for t in document["traces"]:
            name = exporter._sanitize_csv_field(t["name"])
            source = exporter._sanitize_csv_field(t["source_module"])
            expected.append([f"# Trace: {name} (Source: {source}, Timestamp: {t['timestamp']})"])
        expected.append([])
        if rows[: len(expected)] != expected:
            raise fft.ReferenceError("CSV metadata does not match the supplied descriptors")
        rows = rows[len(expected) :]
    independent = options["layout"] == "independent"
    width = (
        sum(2 + (t["y2_data"] is not None) for t in document["traces"])
        if independent
        else 1 + sum(1 + (t["y2_data"] is not None) for t in document["traces"])
    )
    if options["include_headers"]:
        # Labels are display strings, not trustworthy machine-readable unit definitions.
        if not rows or len(rows[0]) != width:
            raise fft.ReferenceError("CSV header width mismatch")
        rows = rows[1:]
    ended = set()
    for row in rows:
        if len(row) != width:
            raise fft.ReferenceError("CSV data width mismatch")
        shared_x = None
        if not independent:
            try:
                shared_x = float(row[0])
            except ValueError as error:
                raise fft.ReferenceError("CSV shared axis is not numeric") from error
            if not math.isfinite(shared_x):
                raise fft.ReferenceError("CSV shared axis is not finite")
        offset = 0 if independent else 1
        for i, t in enumerate(document["traces"]):
            keys = ["x_data", "y_data"] if independent else ["y_data"]
            if t["y2_data"] is not None:
                keys.append("y2_data")
            cells = row[offset : offset + len(keys)]
            offset += len(keys)
            if all(cell == "" for cell in cells):
                ended.add(i)
                continue
            if i in ended or any(cell == "" for cell in cells):
                raise fft.ReferenceError("CSV missing value or interior padding")
            for key, cell in zip(keys, cells, strict=True):
                try:
                    value = float(cell)
                except ValueError as error:
                    raise fft.ReferenceError("CSV value is not numeric") from error
                if not math.isfinite(value):
                    raise fft.ReferenceError("CSV value is not finite")
                t[key].append(value)
            if not independent:
                t["x_data"].append(shared_x)
    return import_document(
        document, codec, relation="original_trace_arrays" if independent else "merged_grid_may_be_interpolated"
    )


def publish_new(path, write):
    """Per-file no-clobber publication after sync; no pair transaction or crash claim."""
    path = Path(path)
    descriptor, name = tempfile.mkstemp(prefix=".migration-product-", suffix=".tmp", dir=path.parent)
    os.close(descriptor)
    temp = Path(name)
    try:
        write(temp)
        with temp.open("rb") as stream:
            os.fsync(stream.fileno())
        os.link(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def save_json(path, document):
    document = copy.deepcopy(validate_document(document))
    traces = [ExportTrace.from_dict(t) for t in document["traces"]]

    def write(temp):
        if not JsonTraceExporter().export_traces(str(temp), traces, {}):
            raise OSError("Product JSON exporter failed")
        if core.json_bytes(unique_json(read_file(temp))) != core.json_bytes(document):
            raise fft.ReferenceError("Product JSON exporter changed the traces")

    publish_new(path, write)


def save_csv_pair(path, document):
    """Independent columns only. A failed sidecar leaves a CSV that is not restorable."""
    document = copy.deepcopy(validate_document(document))
    spec = csv_spec(document)
    traces = [ExportTrace.from_dict(t) for t in document["traces"]]

    def write(temp):
        if not CsvTraceExporter().export_traces(str(temp), traces, spec["options"]):
            raise OSError("Product CSV exporter failed")

    publish_new(path, write)
    payload = read_file(path)
    sidecar = {"schema_version": 1, "kind": CSV_KIND, "csv_sha256": hashlib.sha256(payload).hexdigest(), **spec}
    destination = Path(str(path) + ".metadata.json")
    publish_new(destination, lambda temp: temp.write_bytes(core.json_bytes(sidecar)))
    return destination


def load_csv_pair(path, codec=None):
    payload = read_file(path)
    sidecar = unique_json(read_file(str(path) + ".metadata.json"))
    if (
        not isinstance(sidecar, dict)
        or set(sidecar) != {"schema_version", "kind", "csv_sha256", "options", "descriptors"}
        or type(sidecar["schema_version"]) is not int
        or sidecar["schema_version"] != 1
        or sidecar["kind"] != CSV_KIND
        or sidecar["csv_sha256"] != hashlib.sha256(payload).hexdigest()
        or not isinstance(sidecar["options"], dict)
        or "layout" not in sidecar["options"]
        or sidecar["options"]["layout"] != "independent"
    ):
        raise fft.ReferenceError("Missing, mismatched or unsupported CSV metadata sidecar")
    return import_csv(payload, {k: sidecar[k] for k in ("options", "descriptors")}, codec)
