"""Paired-load source impedance analysis for complex transfer measurements.

The two captures must share a reference channel and acquisition conditions.  The
source impedance is inferred from the voltage-divider model, not from a single
trace or from display-normalized magnitude data.
"""

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class SweepConditions:
    sample_rate: float
    start_freq: float
    end_freq: float
    chirp_duration: float
    amplitude: float
    averages: int
    output_channel: str
    input_mode: str
    ref_channel_index: int
    meas_channel_index: int
    input_device: str | None = None
    output_device: str | None = None
    calibration_profile: str | None = None
    input_sensitivity: float | None = None
    output_gain: float | None = None


@dataclass(frozen=True)
class LoadCapture:
    load_ohms: float
    frequencies: np.ndarray
    transfer: np.ndarray
    coherence: np.ndarray
    conditions: SweepConditions

    @classmethod
    def create(
        cls,
        load_ohms: float,
        frequencies: np.ndarray,
        transfer: np.ndarray,
        coherence: np.ndarray,
        conditions: SweepConditions,
    ) -> "LoadCapture":
        freq = np.array(frequencies, dtype=float, copy=True)
        response = np.array(transfer, dtype=complex, copy=True)
        quality = np.array(coherence, dtype=float, copy=True)
        if not np.isfinite(load_ohms) or load_ohms <= 0:
            raise ValueError("Load resistance must be positive and finite.")
        if len(freq) < 2 or any(array.ndim != 1 or len(array) != len(freq) for array in (response, quality)):
            raise ValueError("Transfer arrays must have equal one-dimensional lengths of at least two.")
        if (
            not np.all(np.isfinite(freq))
            or not np.all(np.diff(freq) > 0)
            or freq[0] <= 0
            or not np.all(np.isfinite(response))
            or not np.all(np.isfinite(quality))
        ):
            raise ValueError("Transfer data must be finite and frequencies must increase above zero.")
        for array in (freq, response, quality):
            array.flags.writeable = False
        return cls(float(load_ohms), freq, response, quality, conditions)


@dataclass(frozen=True)
class LoadResult:
    frequencies: np.ndarray
    difference_db: np.ndarray
    source_ohms: np.ndarray
    predicted_difference_db: np.ndarray
    numerically_valid: np.ndarray
    repeat_resolved: np.ndarray
    low_coherence: np.ndarray
    repeat_available: bool
    count_a: int
    count_b: int


class PairedLoadStudy:
    """Retain independent sweeps and calculate without altering acquisition data."""

    def __init__(self) -> None:
        self.a: list[LoadCapture] = []
        self.b: list[LoadCapture] = []

    def clear(self) -> None:
        self.a.clear()
        self.b.clear()

    def add(self, group: str, capture: LoadCapture) -> None:
        if group not in {"A", "B"}:
            raise ValueError("Load group must be A or B.")
        own = self.a if group == "A" else self.b
        other = self.b if group == "A" else self.a
        if own and not np.isclose(capture.load_ohms, own[0].load_ohms, rtol=0, atol=1e-9):
            raise ValueError("The load resistance changed within a capture group.")
        if other and np.isclose(capture.load_ohms, other[0].load_ohms, rtol=1e-6):
            raise ValueError("A and B need different load resistances.")
        if self.a or self.b:
            first = (self.a or self.b)[0]
            if capture.conditions != first.conditions:
                raise ValueError("Sweep settings or channel routing differ from the stored captures.")
        own.append(capture)

    @staticmethod
    def align_capture(capture: LoadCapture, frequencies: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Resample a stored complex capture onto a grid already within its coverage."""
        if (
            len(frequencies) == 0
            or frequencies[0] < capture.frequencies[0]
            or frequencies[-1] > capture.frequencies[-1]
        ):
            raise ValueError("The output grid extends beyond a capture.")
        transfer = np.interp(frequencies, capture.frequencies, capture.transfer.real) + 1j * np.interp(
            frequencies, capture.frequencies, capture.transfer.imag
        )
        coherence = np.interp(frequencies, capture.frequencies, capture.coherence)
        return transfer, coherence

    def calculate(self, prediction_load_ohms: float, *, min_coherence: float = 0.8) -> LoadResult:
        if not self.a or not self.b:
            raise ValueError("Capture both load groups before calculating.")
        if not np.isfinite(prediction_load_ohms) or prediction_load_ohms <= 0:
            raise ValueError("Prediction load resistance must be positive and finite.")

        captures = self.a + self.b
        lower = max(item.frequencies[0] for item in captures)
        upper = min(item.frequencies[-1] for item in captures)
        grid = self.a[0].frequencies
        grid = grid[(grid >= lower) & (grid <= upper)]
        if len(grid) < 2:
            raise ValueError("The captures have no usable common frequency range.")

        def aligned(items: list[LoadCapture]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
            pairs = [self.align_capture(item, grid) for item in items]
            transfer = np.stack([pair[0] for pair in pairs])
            coherence = np.stack([pair[1] for pair in pairs])
            mean = np.mean(transfer, axis=0)
            standard_error = (
                np.sqrt(np.sum(np.abs(transfer - mean) ** 2, axis=0) / (len(items) * (len(items) - 1)))
                if len(items) > 1
                else np.zeros(len(grid))
            )
            return mean, np.min(coherence, axis=0), standard_error

        h_a, coh_a, error_a = aligned(self.a)
        h_b, coh_b, error_b = aligned(self.b)
        r_a = self.a[0].load_ohms
        r_b = self.b[0].load_ohms
        difference = 20 * np.log10(np.maximum(np.abs(h_b), 1e-15) / np.maximum(np.abs(h_a), 1e-15))
        denominator = h_a / r_a - h_b / r_b
        scale = np.abs(h_a / r_a) + np.abs(h_b / r_b)
        valid = (scale > 1e-15) & (np.abs(denominator) > 1e-6 * scale) & (np.abs(h_a) > 1e-12)
        source = np.full(len(grid), np.nan + 1j * np.nan)
        source[valid] = (h_b[valid] - h_a[valid]) / denominator[valid]
        valid &= np.isfinite(source)

        predicted = np.full(len(grid), np.nan)
        third_divisor = source + prediction_load_ohms
        good_prediction = valid & (np.abs(third_divisor) > 1e-12)
        predicted[good_prediction] = 20 * np.log10(
            np.abs(prediction_load_ohms * (source[good_prediction] + r_a) / (r_a * third_divisor[good_prediction]))
        )

        repeat_available = len(self.a) >= 2 and len(self.b) >= 2
        repeat_resolved = np.zeros(len(grid), dtype=bool)
        if repeat_available:
            combined_error = np.hypot(error_a, error_b)
            denominator_error = np.hypot(error_a / r_a, error_b / r_b)
            repeat_resolved = (
                valid & (np.abs(h_b - h_a) > 3 * combined_error) & (np.abs(denominator) > 3 * denominator_error)
            )
        low_coherence = (coh_a < min_coherence) | (coh_b < min_coherence)
        repeat_resolved &= ~low_coherence
        return LoadResult(
            grid.copy(),
            difference,
            source,
            predicted,
            valid,
            repeat_resolved,
            low_coherence,
            repeat_available,
            len(self.a),
            len(self.b),
        )
