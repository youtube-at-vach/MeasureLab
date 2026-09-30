"""Reviewed case definitions for MIG-003-C; expectations are independently derived."""

import numpy as np


CHANNEL_IDS = ["input.alpha", "input.beta"]
RATE_CASES = [
    {"rates": [0, 48000], "legacy": "same_object", "contract": "invalid_rate"},
    {"rates": [-1, 48000], "legacy": "same_object", "contract": "invalid_rate"},
    {"rates": [48000, 0], "legacy": "same_object", "contract": "invalid_rate"},
    {"rates": [48000, -1], "legacy": "same_object", "contract": "invalid_rate"},
    {"rates": [0, 0], "legacy": "same_object", "contract": "invalid_rate"},
    {"rates": [48000, 48000], "legacy": "same_object", "contract": "valid_rate_pair"},
]


def specs():
    result = []
    for signal in ("impulse-even", "impulse-odd", "dc", "tone", "gap"):
        result.append(
            {
                "id": f"fir-{signal}",
                "kind": "fir",
                "signal": signal,
                "n": 1031,
                "source_rate": 48000,
                "target_rate": 24000,
                "gaps": [[100, 104]] if signal == "gap" else [],
            }
        )
    for source, target in ((48000, 24000), (24000, 48000), (44100, 48000), (48000, 44100)):
        for signal in ("impulse-even", "dc", "tone"):
            result.append(
                {
                    "id": f"poly-{source}-{target}-{signal}",
                    "kind": "poly",
                    "signal": signal,
                    "n": source if signal == "tone" else 129,
                    "source_rate": source,
                    "target_rate": target,
                    "gaps": [],
                }
            )
    for signal in ("impulse-even", "impulse-center", "dc", "tone"):
        result.append(
            {
                "id": f"sos-lowpass-{signal}",
                "kind": "sos",
                "signal": signal,
                "n": 8192 if signal == "tone" else 1024,
                "source_rate": 48000,
                "target_rate": 48000,
                "gaps": [],
                "order": 8,
                "cutoff_hz": 4000,
            }
        )
    return result


def make_input(spec):
    x = np.zeros((spec["n"], 2), dtype="<f8")
    signal = spec["signal"]
    if signal.startswith("impulse"):
        location = 1 if signal == "impulse-odd" else spec["n"] // 2 if signal == "impulse-center" else 0
        x[location] = [1, -0.5]
    elif signal == "dc":
        x[:] = [0.25, -0.125]
    else:
        frequencies = [1000, 12000] if spec["kind"] == "sos" else [1000, 1000]
        n = np.arange(spec["n"])
        for channel, (amplitude, phase) in enumerate(((0.25, 0.0), (0.125, 0.375))):
            x[:, channel] = amplitude * np.cos(2 * np.pi * frequencies[channel] * n / spec["source_rate"] + phase)
    return x
