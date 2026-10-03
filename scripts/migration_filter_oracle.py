"""Independent finite sums and scalar recurrences for MIG-003-C (no SciPy)."""

from __future__ import annotations

from collections import deque
from fractions import Fraction
import math

import numpy as np


FIR = np.array([0.25, 0.5, 0.25])
CHUNKS = {"whole": [100000], "one": [1], "127": [127], "256": [256], "irregular": [3, 128, 1, 7, 256, 2]}


def fraction(value):
    value = Fraction(value)
    return [value.numerator, value.denominator]


def valid_rates(source, target):
    if source <= 0 or target <= 0 or not math.isfinite(source) or not math.isfinite(target):
        raise ValueError("invalid_rate")


def map_position(position, source, target):
    valid_rates(source, target)
    return Fraction(position) * Fraction(target) / Fraction(source)


def intervals(indices):
    result = []
    for index in indices:
        if result and result[-1][1] == index:
            result[-1][1] += 1
        else:
            result.append([index, index + 1])
    return result


def fir_metadata(n, gaps):
    """Interval algebra; independent of the streaming model's per-frame flags."""
    count = (n + 1) // 2
    invalid = set()
    for start, stop in gaps:
        # 2m >= start and 2m-2 < stop.
        invalid.update(range((start + 1) // 2, min(count, (stop + 3) // 2)))
    return {
        "input_interval": [0, n],
        "output_interval": [0, count],
        "input_gaps": gaps,
        "invalid_intervals": {"warmup": [[0, 1]], "gap": intervals(sorted(invalid))},
        "source_stream": "fixture.input",
        "output_stream": "fixture.fir",
        "source_timebase": "fixture.clock.48k",
        "output_timebase": "fixture.clock.24k",
        "generation": 0,
        "rate_ratio": [1, 2],
        "source_rate_hz": [48000, 1],
        "output_rate_hz": [24000, 1],
        "origin_mapping": {"input": [0, 1], "output": [0, 1]},
        "output_m_to_input": [2, 1],
        "signal_delay_input_samples": [1, 1],
        "signal_delay_output_samples": [1, 2],
        "signal_delay_seconds": [1, 48000],
        "delay_compensated": False,
        "processing_latency_seconds": None,
        "processing_latency_reason": "not_measured",
        "trigger": {"input": [1024, 1], "output": [512, 1], "delayed_feature_center": [1025, 2]},
        "filter_revision": "causal-3tap-v1",
        "tail_flush": False,
        "gap_numeric_policy": "missing input is computational zero; every affected output stays invalid",
    }


def fir_sum(x, gaps=()):
    observed = np.array(x, dtype=np.float64, copy=True)
    for start, end in gaps:
        observed[start:end] = 0
    return np.array(
        [
            [math.fsum(FIR[j] * observed[2 * m - j, c] for j in range(3) if 2 * m >= j) for c in range(x.shape[1])]
            for m in range((len(x) + 1) // 2)
        ]
    )


class StreamingFir:
    """New-contract oracle only. Missing blocks keep their absolute positions."""

    def __init__(self, channels, source_rate=48000, target_rate=24000):
        valid_rates(source_rate, target_rate)
        if (source_rate, target_rate) != (48000, 24000):
            raise ValueError("unsupported_rate_pair")
        self.channels = channels
        self.cursor = 0
        self.history = deque([(np.zeros(channels), {"warmup"}) for _ in range(2)], maxlen=3)

    def process(self, start, values):
        values = np.asarray(values, dtype=np.float64)
        if type(start) is not int or start < self.cursor:
            raise ValueError("overlap_or_reorder")
        if values.ndim != 2 or values.shape[1] != self.channels or not len(values) or not np.isfinite(values).all():
            raise ValueError("invalid_block")
        output, flags = [], []
        for position in range(self.cursor, start + len(values)):
            missing = position < start
            self.history.append(
                (np.zeros(self.channels) if missing else values[position - start].copy(), {"gap"} if missing else set())
            )
            if position % 2 == 0:
                rows = list(self.history)
                output.append(0.25 * rows[0][0] + 0.5 * rows[1][0] + 0.25 * rows[2][0])
                flags.append(set.union(*(row[1] for row in rows)))
        self.cursor = start + len(values)
        return np.asarray(output).reshape(-1, self.channels), flags


def slices(length, pattern):
    offset, index = 0, 0
    while offset < length:
        end = min(length, offset + pattern[index % len(pattern)])
        yield offset, end
        offset, index = end, index + 1


def stream_fir(x, gaps, pattern):
    model = StreamingFir(x.shape[1])
    pieces, flags = [], []
    available = [(0, gaps[0][0])] if gaps else [(0, len(x))]
    if gaps:
        available += [(end, gaps[i + 1][0] if i + 1 < len(gaps) else len(x)) for i, (_, end) in enumerate(gaps)]
    if gaps and gaps[-1][1] >= len(x):
        raise ValueError("trailing gap requires a later block or explicit end-of-stream; fixture does not infer it")
    for start, end in available:
        for left, right in slices(end - start, pattern):
            output, reasons = model.process(start + left, x[start + left : start + right])
            pieces.append(output)
            flags.extend(reasons)
    return np.concatenate(pieces), {
        reason: intervals(i for i, reasons in enumerate(flags) if reason in reasons) for reason in ("warmup", "gap")
    }


def kaiser_coefficients(up, down):
    half = 10 * max(up, down)
    positions = np.arange(-half, half + 1, dtype=np.float64)
    cutoff = 1 / max(up, down)
    window = np.i0(5 * np.sqrt(np.maximum(0, 1 - (positions / half) ** 2))) / np.i0(5.0)
    coefficients = cutoff * np.sinc(cutoff * positions) * window
    return coefficients / math.fsum(coefficients)


def polyphase_sum(x, coefficients, up, down):
    """Centered finite sum. No resample_poly/upfirdn, zero-insertion, or FFT."""
    half = (len(coefficients) - 1) // 2
    n_out = (len(x) * up + down - 1) // down
    out = np.zeros((n_out, x.shape[1]))
    centers = np.arange(n_out) * down + half
    # At most ~21 input frames contribute per output in the selected ratios.
    first = np.maximum(0, (centers - len(coefficients) + up) // up)
    last = np.minimum(len(x) - 1, centers // up)
    for offset in range(int(np.max(last - first)) + 1):
        source = first + offset
        valid = source <= last
        indices = centers[valid] - source[valid] * up
        out[valid] += coefficients[indices, None] * up * x[source[valid]]
    return out


def sos_recurrence(x, sos, steady=False):
    """Direct form I scalar recurrence, independent of SciPy's DF-II state."""
    result = np.array(x, dtype=np.float64, copy=True)
    final_state = []
    initial = result[0].copy() if steady else np.zeros(x.shape[1])
    for b0, b1, b2, a0, a1, a2 in sos:
        if a0 != 1:
            raise ValueError("SOS a0 must be normalized")
        gain = (b0 + b1 + b2) / (a0 + a1 + a2)
        x1, x2 = initial.copy(), initial.copy()
        y1, y2 = initial * gain, initial * gain
        for index in range(len(result)):
            sample = result[index].copy()
            value = b0 * sample + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
            result[index] = value
            x2, x1, y2, y1 = x1, sample, y1, value
        final_state.append(np.stack((b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2, b2 * x1 - a2 * y1)))
        initial *= gain
    return result, np.asarray(final_state)


def sos_forward_backward(x, sos, padlen=27):
    """Odd extension, steady initial history, forward and backward recurrences."""
    if len(x) <= padlen:
        raise ValueError("too_short")
    extended = np.concatenate((2 * x[0] - x[1 : padlen + 1][::-1], x, 2 * x[-1] - x[-padlen - 1 : -1][::-1]))
    forward, _ = sos_recurrence(extended, sos, steady=True)
    backward, _ = sos_recurrence(forward[::-1], sos, steady=True)
    return backward[::-1][padlen:-padlen]


def sos_response(sos, frequencies, rate):
    response = []
    for frequency in frequencies:
        z = complex(math.cos(2 * math.pi * frequency / rate), -math.sin(2 * math.pi * frequency / rate))
        response.append(
            np.prod([(b0 + b1 * z + b2 * z**2) / (a0 + a1 * z + a2 * z**2) for b0, b1, b2, a0, a1, a2 in sos])
        )
    return np.asarray(response)
