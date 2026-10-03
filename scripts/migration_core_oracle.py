"""Small executable model of MIG-002 core semantics, NOT the legacy engine.

This deliberately uses immutable copies, rational positions and interval algebra.
It is an offline oracle, not a streaming buffer, graph, backend or product API.
Hand-authored input/expected examples live separately in migration_core_cases.py.
"""

from __future__ import annotations

from copy import deepcopy
from fractions import Fraction
import math


class ContractError(ValueError):
    """Rejected input; the reason is part of the exchange fixture."""


def fraction(pair):
    return Fraction(*pair)


def rational(value):
    return [value.numerator, value.denominator]


def validate_route(route, known_ids):
    inputs, outputs, gains = route["inputs"], route["outputs"], route["gains"]
    if len(set(inputs)) != len(inputs) or any(ch not in known_ids for ch in inputs):
        raise ContractError("unknown_or_duplicate_input")
    if not outputs or len(set(outputs)) != len(outputs):
        raise ContractError("duplicate_or_empty_output")
    if len(gains) != len(outputs) or any(len(row) != len(inputs) for row in gains):
        raise ContractError("gain_shape")
    # JSON cannot encode NaN: malformed test requests use the token "NaN".
    if any(type(gain) not in (int, float) or not math.isfinite(gain) for row in gains for gain in row):
        raise ContractError("nonfinite_gain")


def route_values(data):
    ids, route = data["channel_ids"], data["route"]
    if not ids or len(set(ids)) != len(ids):
        raise ContractError("channel_ids")
    if not data["values"] or any(len(row) != len(ids) for row in data["values"]):
        raise ContractError("frame_shape")
    validate_route(route, ids)
    if data["unit"] != "FS":
        raise ContractError("mix_requires_explicit_unit_conversion")
    indices = [ids.index(ch) for ch in route["inputs"]]
    values, validity = [], []
    for offset, row in enumerate(data["values"]):
        sample = data["start"] + offset
        output = []
        for channel, gains in zip(route["outputs"], route["gains"], strict=True):
            reasons = set()
            total = 0.0
            for ch, index, gain in zip(route["inputs"], indices, gains, strict=True):
                if gain == 0:
                    continue
                input_reasons = {
                    item["reason"]
                    for item in data["validity"]
                    if item["channel_id"] == ch and item["interval"][0] <= sample < item["interval"][1]
                }
                reasons.update(input_reasons)
                value = row[index]
                if value is None:
                    if not input_reasons:
                        raise ContractError("null_without_reason")
                elif not math.isfinite(value):
                    raise ContractError("nonfinite_without_encoding")
                else:
                    total += gain * value
            output.append(None if reasons else total)
            if reasons:
                validity.append({"channel_id": channel, "interval": [sample, sample + 1], "reasons": sorted(reasons)})
        values.append(output)
    return {
        "channel_ids": list(route["outputs"]),
        "values": values,
        "validity": validity,
        "unit": "FS",
        "revision": route["revision"],
        "input_calibration_ids": [
            [ch for ch, gain in zip(route["inputs"], row, strict=True) if gain != 0] for row in route["gains"]
        ],
        "single_v_per_fs": [None] * len(route["outputs"]),
    }


def route_changes(data):
    """Each request is processed before its stated next block boundary."""
    current = deepcopy(data["initial"])
    validate_route(current, data["known_ids"])
    records = []
    for request in data["requests"]:
        try:
            validate_route(request["route"], data["known_ids"])
            if request["requested_sample"] > request["next_block_start"]:
                raise ContractError("boundary_before_request")
        except ContractError as exc:
            records.append({"request_id": request["id"], "status": "rejected", "reason": str(exc)})
        else:
            current = deepcopy(request["route"])
            records.append(
                {
                    "request_id": request["id"],
                    "status": "applied",
                    "sample": request["next_block_start"],
                    "revision": current["revision"],
                }
            )
        # Copy at publication: subsequent requests cannot revise an old block.
        records[-1]["published_route"] = deepcopy(current)
    return records


def merge_intervals(intervals):
    result = []
    for start, end in sorted(intervals):
        if start >= end:
            continue
        if result and start <= result[-1][1]:
            result[-1][1] = max(end, result[-1][1])
        else:
            result.append([start, end])
    return result


def missing_intervals(start, end, available):
    cursor, missing = start, []
    for left, right in merge_intervals(available):
        if right <= cursor or left >= end:
            continue
        if left > cursor:
            missing.append([cursor, min(left, end)])
        cursor = max(cursor, min(right, end))
    if cursor < end:
        missing.append([cursor, end])
    return missing


def history_query(data):
    event = data["event"]
    if event["generation"] != data["generation"]:
        return {"status": "rejected", "reason": "stale_generation", "event_id": event["id"]}
    if event["stream_id"] != data["stream_id"] or event["timebase_id"] != data["timebase_id"]:
        return {"status": "rejected", "reason": "stream_or_timebase_mismatch", "event_id": event["id"]}
    position = fraction(event["sample"])
    anchor = math.floor(position)
    start, end = anchor - data["pre"], anchor + data["post"]
    if data["capacity"] <= 0 or end <= start or min(data["pre"], data["post"]) < 0:
        raise ContractError("history_request")
    high = data["acquired_until"]
    floor = max(0, high - data["capacity"])
    available = [[max(a, floor), min(b, high)] for a, b in data["acquired_intervals"]]
    missing = missing_intervals(start, min(end, high), available)
    pending = [[max(start, high), end]] if end > high else []
    return {
        "event_id": event["id"],
        "stream_id": data["stream_id"],
        "generation": data["generation"],
        "timebase_id": data["timebase_id"],
        "interval": [start, end],
        "fractional_residual": rational(position - anchor),
        "status": "gap" if missing else "pending" if pending else "snapshot",
        "missing": missing,
        "pending": pending,
        "reason": "missing" if missing else None,
    }


def stream_blocks(data):
    """Validate a trace of block deliveries; rejected blocks do not advance state."""
    state = None
    records = []
    for block in data["blocks"]:
        try:
            ids = block["channel_ids"]
            if not ids or len(set(ids)) != len(ids):
                raise ContractError("channel_ids")
            if block["frames"] <= 0 or len(block["values"]) != block["frames"]:
                raise ContractError("frame_shape")
            if any(len(row) != len(ids) for row in block["values"]):
                raise ContractError("frame_shape")
            if block["start"] < 0 or block["generation"] < 0:
                raise ContractError("negative_position_or_generation")
            fields = ("channel_ids", "rate", "dtype", "clock_domain", "binding")
            if state is not None:
                if block["generation"] < state["generation"]:
                    raise ContractError("stale_generation")
                if block["generation"] == state["generation"]:
                    if any(block[key] != state[key] for key in fields):
                        raise ContractError("configuration_requires_new_generation")
                    if block["start"] < state["start"] + state["frames"]:
                        raise ContractError("overlap_or_reverse")
            prior_end = state["start"] + state["frames"] if state and state["generation"] == block["generation"] else 0
            records.append(
                {
                    "status": "accepted",
                    "generation": block["generation"],
                    "interval": [block["start"], block["start"] + block["frames"]],
                    "missing": [[prior_end, block["start"]]] if block["start"] > prior_end else [],
                }
            )
            state = deepcopy(block)
        except ContractError as exc:
            records.append({"status": "rejected", "reason": str(exc)})
    return records


def analysis_validity(data):
    start, end = data["interval"]
    reasons = sorted(
        {
            item["reason"]
            for item in data["validity"]
            if item["channel_id"] in data["channel_ids"] and item["interval"][0] < end and item["interval"][1] > start
        }
    )
    return {"value": None, "reasons": reasons, "status": "invalid"} if reasons else {"status": "eligible"}


def time_relation(data):
    left, right = data["left"], data["right"]
    if left["clock_domain"] != right["clock_domain"] and data["mapping"] is None:
        return {"value": None, "reason": "unsynchronized"}
    mapping = data["mapping"]
    if mapping is not None:
        if (
            mapping["from"] != [left["id"], left["generation"]]
            or mapping["to"] != [right["id"], right["generation"]]
            or not mapping["valid_interval"][0] <= data["sample"] < mapping["valid_interval"][1]
        ):
            return {"value": None, "reason": "unsynchronized"}
        value = fraction(mapping["offset"]) + data["sample"] * fraction(mapping["ratio"])
        return {"value": rational(value), "reason": None, "mapping": deepcopy(mapping)}
    if left["origin_seconds"] is None:
        return {"value": None, "reason": "unknown_origin"}
    value = fraction(left["origin_seconds"]) + Fraction(data["sample"] - left["origin_sample"]) / fraction(left["rate"])
    return {"value": rational(value), "reason": None, "uncertainty_seconds": left["uncertainty_seconds"]}


def monitor_taps(data):
    mixed = deepcopy(data["mixed"])
    if data["mute"]:
        submitted = [[0.0 for _ in data["mapping"]] for _ in mixed]
    else:
        # Explicit deterministic fixture choice: no dither, ties-to-even rounding.
        step = data["quantization_step"]
        submitted = [[round(row[index] * data["gain"] / step) * step for index in data["mapping"]] for row in mixed]
    delay = data["loopback_delay_frames"]
    return {
        "output.mixed": mixed,
        "output.device_buffer": submitted,
        "physical_output": {"value": None, "reason": "not_measured"},
        "virtual_loopback": {
            "source_tap": "output.mixed",
            "delay_frames": delay,
            "initial_validity": {"interval": [0, delay], "reason": "warmup"},
        },
    }


def measurement_result(data):
    """Capture channel calibration and provenance; never retain caller aliases."""
    result = deepcopy(data["provenance"])
    order = data["channel_order"]
    channels = []
    for ch in order:
        profile = deepcopy(data["profiles"][ch])
        value = data["peak_fs"][ch]
        rms = value / math.sqrt(2)
        calibrated = profile["is_calibrated"]
        v_rms = rms * profile["v_per_fs"] if calibrated else None
        channels.append(
            {
                "id": ch,
                "peak_fs": value,
                "rms_fs": rms,
                "rms_v": v_rms,
                "dbv": 20 * math.log10(v_rms) if v_rms is not None and v_rms > 0 else None,
                "spl": None,
                "validity": {"rms_v": None if calibrated else "uncalibrated", "spl": "uncalibrated"},
                "calibration": profile,
            }
        )
    result["channels"] = channels
    result["axis"] = {
        "dimension": "frequency",
        "unit": "Hz",
        "nominal": deepcopy(data["frequency_hz"]),
        "corrected": [value * data["frequency_correction"] for value in data["frequency_hz"]],
        "correction": data["frequency_correction"],
    }
    result["units"] = {"peak_fs": "FS_peak", "rms_fs": "FS_RMS", "rms_v": "V_RMS", "dbv": "dBV_RMS", "spl": "dBSPL"}
    return result


def evaluate(case):
    operations = {
        "route": route_values,
        "route_changes": route_changes,
        "history": history_query,
        "time": time_relation,
        "taps": monitor_taps,
        "calibration": measurement_result,
        "blocks": stream_blocks,
        "analysis_validity": analysis_validity,
    }
    try:
        return operations[case["operation"]](case["input"])
    except ContractError as exc:
        return {"status": "rejected", "reason": str(exc)}
