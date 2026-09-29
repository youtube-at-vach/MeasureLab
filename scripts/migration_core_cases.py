"""Reviewed MIG-003-B examples; expectations do not call the executable model.

All small samples are literal JSON-compatible values. Helpers only assemble
metadata. Nonfinite requests use a string token, never non-standard JSON NaN.
"""

from copy import deepcopy
import math

CHANNEL_IDS = [f"input.{name}" for name in ("alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta")]


def tone_specs():
    bins = [37, 71, 113, 173, 251, 331, 419, 509]
    return [
        {
            "id": f"ac01-{count}ch-{dtype[1:]}",
            "n": 4096,
            "signal": "cosine",
            "window": "boxcar",
            "dtype": dtype,
            "tones": [[bins[c], (c + 1) / 32, c * math.pi / 16] for c in range(count)],
            "rate_hz": 48000,
        }
        for count in (4, 8)
        for dtype in ("<f8", "<f4")
    ]


def timebase():
    return {
        "id": "fixture.timebase.input",
        "clock_domain": "fixture.virtual",
        "generation": 3,
        "rate": [48000, 1],
        "nominal_rate": [48000, 1],
        "origin_sample": 0,
        "origin_seconds": [10, 1],
        "origin_kind": "virtual",
        "uncertainty_seconds": None,
    }


def provenance():
    return {
        "result_id": "fixture.result.001",
        "operation_revision": "rms-cosine-v1",
        "stream_id": "fixture.session.input",
        "generation": 3,
        "interval": [0, 4096],
        "timebase": timebase(),
        "trigger_id": "fixture.trigger.001",
        "route_revision": "route.1",
        "tap": "input.raw",
        "acquired_host_seconds": None,
        "result_host_seconds": [11, 1],
        "validity": [],
    }


def route(inputs, outputs, gains, revision="route.1"):
    return {"inputs": inputs, "outputs": outputs, "gains": gains, "revision": revision}


def scenarios():
    cases = []

    def add(name, ac, operation, data, expected):
        cases.append(
            {
                "id": name,
                "acceptance": ac,
                "origin": "new-contract-oracle",
                "operation": operation,
                "input": deepcopy(data),
                "expected": deepcopy(expected),
            }
        )

    a, b, c, d, e, f, g, h = CHANNEL_IDS
    # AC02: arithmetic anchors, distinct samples per channel; no implicit normalization.
    for name, ids, values, routing, output, contributors in [
        (
            "route-4-to-2",
            [a, b, c, d],
            [[2, 4, 6, 8], [-2, -4, -6, -8]],
            route([a, b, c, d], ["out.pick", "out.mix"], [[0, 0, 0, 1], [0.5, 0, 0.5, 0]]),
            [[8, 4], [-8, -4]],
            [[d], [a, c]],
        ),
        (
            "route-8-to-4",
            CHANNEL_IDS,
            [[2, 4, 6, 8, 10, 12, 14, 16]],
            route(
                CHANNEL_IDS,
                ["out.7", "out.1", "out.mix", "out.invert"],
                [
                    [0, 0, 0, 0, 0, 0, 0, 1],
                    [0, 1, 0, 0, 0, 0, 0, 0],
                    [0, 0, 0.5, 0, 0.5, 0, 0, 0],
                    [-1, 0, 0, 0, 0, 0, 0, 0],
                ],
            ),
            [[16, 4, 8, -2]],
            [[h], [b], [c, e], [a]],
        ),
        (
            "route-2-to-8",
            [a, b],
            [[0.25, -0.5]],
            route([a, b], [f"out.{n}" for n in range(8)], [[1, 0], [0, 1]] * 4),
            [[0.25, -0.5, 0.25, -0.5, 0.25, -0.5, 0.25, -0.5]],
            [[a], [b]] * 4,
        ),
        (
            "route-reordered-zero",
            [d, b, a, c],
            [[8, 4, 2, 6]],
            route([a, c, d], ["out.mix", "out.zero"], [[0.5, 0.5, 0], [0, 0, 0]]),
            [[4, 0]],
            [[a, c], []],
        ),
    ]:
        add(
            name,
            ["AC02"],
            "route",
            {"channel_ids": ids, "values": values, "start": 10, "unit": "FS", "route": routing, "validity": []},
            {
                "channel_ids": routing["outputs"],
                "values": output,
                "validity": [],
                "unit": "FS",
                "revision": "route.1",
                "input_calibration_ids": contributors,
                "single_v_per_fs": [None] * len(output[0]),
            },
        )

    add(
        "route-reason-union",
        ["AC02", "AC09"],
        "route",
        {
            "channel_ids": [a, b, c],
            "values": [[None, None, 2], [1, 3, 4]],
            "start": 100,
            "unit": "FS",
            "route": route([a, b, c], ["out.mix", "out.pick", "out.zero"], [[1, 0.5, 0], [0, 0, 1], [0, 0, 0]]),
            "validity": [
                {"channel_id": a, "interval": [100, 101], "reason": "missing"},
                {"channel_id": b, "interval": [100, 101], "reason": "nonfinite"},
            ],
        },
        {
            "channel_ids": ["out.mix", "out.pick", "out.zero"],
            "values": [[None, 2, 0], [2.5, 4, 0]],
            "validity": [{"channel_id": "out.mix", "interval": [100, 101], "reasons": ["missing", "nonfinite"]}],
            "unit": "FS",
            "revision": "route.1",
            "input_calibration_ids": [[a, b], [c], []],
            "single_v_per_fs": [None, None, None],
        },
    )
    wrong_unit = deepcopy(cases[0]["input"])
    wrong_unit["unit"] = "mixed-V-and-FS"
    add(
        "route-mixed-units-rejected",
        ["AC02", "AC12"],
        "route",
        wrong_unit,
        {"status": "rejected", "reason": "mix_requires_explicit_unit_conversion"},
    )

    initial = route([a, b], ["out.pick"], [[1, 0]], "route.0")
    changed = route([a, b], ["out.pick"], [[0, 1]], "route.1")
    requests = [{"id": "req.1", "requested_sample": 101, "next_block_start": 128, "route": changed}]
    expected = [
        {"request_id": "req.1", "status": "applied", "sample": 128, "revision": "route.1", "published_route": changed}
    ]
    for name, invalid, reason in [
        ("unknown", route(["input.unknown"], ["out.pick"], [[1]]), "unknown_or_duplicate_input"),
        ("duplicate-input", route([a, a], ["out.pick"], [[1, 1]]), "unknown_or_duplicate_input"),
        ("duplicate-output", route([a, b], ["out.pick", "out.pick"], [[1, 0], [0, 1]]), "duplicate_or_empty_output"),
        ("shape", route([a, b], ["out.pick"], [[1]]), "gain_shape"),
        ("nan", route([a, b], ["out.pick"], [["NaN", 0]]), "nonfinite_gain"),
    ]:
        requests.append({"id": name, "requested_sample": 150, "next_block_start": 256, "route": invalid})
        expected.append({"request_id": name, "status": "rejected", "reason": reason, "published_route": changed})
    requests.append({"id": "req.2", "requested_sample": 256, "next_block_start": 256, "route": initial})
    expected.append(
        {"request_id": "req.2", "status": "applied", "sample": 256, "revision": "route.0", "published_route": initial}
    )
    add(
        "route-boundary-and-rejections",
        ["AC03"],
        "route_changes",
        {"known_ids": [a, b], "initial": initial, "requests": requests},
        expected,
    )

    event = {
        "id": "fixture.trigger.001",
        "stream_id": "fixture.session.input",
        "generation": 3,
        "timebase_id": "fixture.timebase.input",
        "sample": [2048, 1],
        "source": "virtual",
        "kind": "edge",
        "polarity": "rising",
        "condition_revision": "condition.1",
        "validity": [],
    }
    history = {
        "event": event,
        "stream_id": "fixture.session.input",
        "generation": 3,
        "timebase_id": "fixture.timebase.input",
        "pre": 256,
        "post": 768,
        "capacity": 4096,
        "acquired_until": 2816,
        "acquired_intervals": [[0, 2816]],
        "reader_id": "reader.fast",
        "notification_host_seconds": 10,
    }
    snapshot = {
        "event_id": event["id"],
        "stream_id": "fixture.session.input",
        "generation": 3,
        "timebase_id": "fixture.timebase.input",
        "interval": [1792, 2816],
        "fractional_residual": [0, 1],
        "status": "snapshot",
        "missing": [],
        "pending": [],
        "reason": None,
    }
    add("history-reader-fast", ["AC08"], "history", history, snapshot)
    late = deepcopy(history)
    late.update(
        reader_id="reader.slow", notification_host_seconds=20, acquired_until=4096, acquired_intervals=[[0, 4096]]
    )
    add("history-reader-delayed", ["AC08"], "history", late, snapshot)
    expired = deepcopy(late)
    expired.update(acquired_until=6000, acquired_intervals=[[0, 6000]])
    add(
        "history-retention-overflow",
        ["AC08", "AC09"],
        "history",
        expired,
        dict(snapshot, status="gap", missing=[[1792, 1904]], reason="missing"),
    )
    pending = deepcopy(history)
    pending.update(acquired_until=2500, acquired_intervals=[[0, 2500]])
    add(
        "history-future-pending", ["AC08"], "history", pending, dict(snapshot, status="pending", pending=[[2500, 2816]])
    )
    fractional = deepcopy(history)
    fractional["event"]["sample"] = [4097, 2]
    add("history-fractional-trigger", ["AC08"], "history", fractional, dict(snapshot, fractional_residual=[1, 2]))
    early = deepcopy(history)
    early["event"]["sample"] = [2, 1]
    early.update(pre=4, post=4, acquired_until=10, acquired_intervals=[[0, 10]])
    add(
        "history-before-start",
        ["AC08"],
        "history",
        early,
        dict(snapshot, interval=[-2, 6], status="gap", missing=[[-2, 0]], reason="missing"),
    )
    gap = deepcopy(history)
    gap["event"]["sample"] = [102, 1]
    gap.update(pre=4, post=4, acquired_until=110, acquired_intervals=[[0, 100], [104, 110]])
    add(
        "history-gap-absolute-position",
        ["AC09"],
        "history",
        gap,
        dict(snapshot, interval=[98, 106], status="gap", missing=[[100, 104]], reason="missing"),
    )
    stale = deepcopy(history)
    stale["generation"] = 4
    add(
        "history-old-generation",
        ["AC09"],
        "history",
        stale,
        {"status": "rejected", "reason": "stale_generation", "event_id": event["id"]},
    )
    foreign = deepcopy(history)
    foreign["event"]["timebase_id"] = "another.timebase"
    add(
        "history-wrong-timebase",
        ["AC09"],
        "history",
        foreign,
        {"status": "rejected", "reason": "stream_or_timebase_mismatch", "event_id": event["id"]},
    )

    left, right = timebase(), timebase()
    add(
        "time-rational-origin",
        ["AC09"],
        "time",
        {"left": left, "right": right, "mapping": None, "sample": 1024},
        {"value": [3758, 375], "reason": None, "uncertainty_seconds": None},
    )
    right.update(id="device.other", clock_domain="device.independent")
    add(
        "time-nominal-rate-not-sync",
        ["AC09"],
        "time",
        {"left": left, "right": right, "mapping": None, "sample": 1024},
        {"value": None, "reason": "unsynchronized"},
    )
    mapping = {
        "from": [left["id"], 3],
        "to": [right["id"], 3],
        "offset": [1, 2],
        "ratio": [1, 1],
        "valid_interval": [0, 2048],
        "method": "fixture-exact",
        "uncertainty_samples": [0, 1],
    }
    add(
        "time-explicit-mapping",
        ["AC09"],
        "time",
        {"left": left, "right": right, "mapping": mapping, "sample": 1024},
        {"value": [2049, 2], "reason": None, "mapping": mapping},
    )
    add(
        "time-expired-mapping",
        ["AC09"],
        "time",
        {"left": left, "right": right, "mapping": mapping, "sample": 2048},
        {"value": None, "reason": "unsynchronized"},
    )

    taps = {
        "mixed": [[0.3, -0.6], [0.8, 0.1]],
        "mute": False,
        "gain": 0.5,
        "quantization_step": 0.25,
        "mapping": [1, 0],
        "dither": "none",
        "loopback_delay_frames": 2,
    }
    tap_expected = {
        "output.mixed": [[0.3, -0.6], [0.8, 0.1]],
        "output.device_buffer": [[-0.25, 0.25], [0, 0.5]],
        "physical_output": {"value": None, "reason": "not_measured"},
        "virtual_loopback": {
            "source_tap": "output.mixed",
            "delay_frames": 2,
            "initial_validity": {"interval": [0, 2], "reason": "warmup"},
        },
    }
    add("taps-gain-map-quantization", ["AC11"], "taps", taps, tap_expected)
    add(
        "taps-muted-device-only",
        ["AC11"],
        "taps",
        dict(taps, mute=True),
        dict(tap_expected, **{"output.device_buffer": [[0, 0], [0, 0]]}),
    )
    block = {
        "generation": 3,
        "start": 0,
        "frames": 2,
        "channel_ids": [a, b],
        "values": [[1, 2], [3, 4]],
        "dtype": "<f8",
        "rate": [48000, 1],
        "clock_domain": "virtual",
        "binding": [0, 1],
    }
    after_gap = dict(block, start=6)
    reordered = dict(block, channel_ids=[b, a], start=8)
    restarted = dict(reordered, generation=4, start=0)
    add(
        "blocks-gap-reorder-restart",
        ["AC09"],
        "blocks",
        {
            "blocks": [
                block,
                after_gap,
                block,
                reordered,
                restarted,
                after_gap,
                dict(restarted, start=2, frames=3),
                dict(restarted, start=2, frames=0, values=[]),
            ]
        },
        [
            {"status": "accepted", "generation": 3, "interval": [0, 2], "missing": []},
            {"status": "accepted", "generation": 3, "interval": [6, 8], "missing": [[2, 6]]},
            {"status": "rejected", "reason": "overlap_or_reverse"},
            {"status": "rejected", "reason": "configuration_requires_new_generation"},
            {"status": "accepted", "generation": 4, "interval": [0, 2], "missing": []},
            {"status": "rejected", "reason": "stale_generation"},
            {"status": "rejected", "reason": "frame_shape"},
            {"status": "rejected", "reason": "frame_shape"},
        ],
    )
    add(
        "analysis-gap-nonfinite",
        ["AC09"],
        "analysis_validity",
        {
            "channel_ids": [a],
            "interval": [98, 106],
            "validity": [
                {"channel_id": a, "interval": [100, 104], "reason": "missing"},
                {"channel_id": a, "interval": [104, 105], "reason": "nonfinite"},
                {"channel_id": b, "interval": [98, 106], "reason": "unsupported"},
            ],
        },
        {"status": "invalid", "value": None, "reasons": ["missing", "nonfinite"]},
    )
    add(
        "analysis-outside-invalid-support",
        ["AC09"],
        "analysis_validity",
        {
            "channel_ids": [a],
            "interval": [104, 110],
            "validity": [{"channel_id": a, "interval": [100, 104], "reason": "missing"}],
        },
        {"status": "eligible"},
    )
    cases.extend(calibration_cases())
    return cases


def calibration_cases():
    a, b, c, d = CHANNEL_IDS[:4]
    profiles = {
        ch: {
            "revision": "profile.1",
            "v_per_fs": scale,
            "is_calibrated": calibrated,
            "device_binding": {"device": "virtual.device", "port": port},
            "applied_interval": [0, 4096],
        }
        for ch, scale, calibrated, port in [(a, 1, True, 0), (b, 1.25, False, 1), (c, 1.5, True, 2), (d, 1.75, True, 3)]
    }
    data = {
        "channel_order": [d, a, c, b],
        "profiles": profiles,
        "peak_fs": {a: 0.03125, b: 0.0625, c: 0.09375, d: 0.125},
        "provenance": provenance(),
        "frequency_hz": [1000, 2000],
        "frequency_correction": 1.0001,
    }
    # Explicit scalar anchors: A/sqrt(2), A/sqrt(2)*(1+c/4), 20 log10(V_RMS).
    channels = []
    for ch, peak, rms, volts, dbv in [
        (d, 0.125, 0.08838834764831843, 0.15467960838455724, -16.211338722752796),
        (a, 0.03125, 0.022097086912079608, 0.022097086912079608, -33.11329952303793),
        (c, 0.09375, 0.06629126073623882, 0.09943689110435824, -20.04904924753106),
        (b, 0.0625, 0.044194173824159216, None, None),
    ]:
        channels.append(
            {
                "id": ch,
                "peak_fs": peak,
                "rms_fs": rms,
                "rms_v": volts,
                "dbv": dbv,
                "spl": None,
                "validity": {"rms_v": "uncalibrated" if ch == b else None, "spl": "uncalibrated"},
                "calibration": deepcopy(profiles[ch]),
            }
        )
    expected = {
        **provenance(),
        "channels": channels,
        "axis": {
            "dimension": "frequency",
            "unit": "Hz",
            "nominal": [1000, 2000],
            "corrected": [1000.1, 2000.2],
            "correction": 1.0001,
        },
        "units": {"peak_fs": "FS_peak", "rms_fs": "FS_RMS", "rms_v": "V_RMS", "dbv": "dBV_RMS", "spl": "dBSPL"},
    }
    identity_data, identity_expected = deepcopy(data), deepcopy(expected)
    identity_data["frequency_correction"] = 1
    identity_expected["axis"].update(corrected=[1000, 2000], correction=1)
    return [
        {
            "id": name,
            "acceptance": ["AC12"],
            "origin": "new-contract-oracle",
            "operation": "calibration",
            "input": inputs,
            "expected": outputs,
        }
        for name, inputs, outputs in [
            ("calibration-reorder-and-unknown", data, expected),
            ("calibration-nominal-axis", identity_data, identity_expected),
        ]
    ]
