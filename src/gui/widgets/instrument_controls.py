"""Reusable controls that follow conventional measurement-instrument stepping."""

import math

import numpy as np
from PyQt6.QtWidgets import QDoubleSpinBox


class PreferredNumberSpinBox(QDoubleSpinBox):
    """Numeric input whose step keys follow the instrument-standard 1-2-5 series."""

    _MANTISSAS = (1.0, 2.0, 5.0)

    @classmethod
    def _preferred_values_around(cls, value: float) -> list[float]:
        reference = max(abs(float(value)), 1e-12)
        exponent = int(math.floor(math.log10(reference)))
        return sorted(
            mantissa * (10.0**candidate_exponent)
            for candidate_exponent in range(exponent - 2, exponent + 3)
            for mantissa in cls._MANTISSAS
        )

    def _step_once(self, value: float, direction: int) -> float:
        if value <= 0.0:
            if direction < 0:
                return value
            smallest_visible = 10.0 ** (-self.decimals())
            seed = max(self.minimum(), self.singleStep(), smallest_visible)
            candidates = self._preferred_values_around(seed)
            return next(candidate for candidate in candidates if candidate >= seed)

        epsilon = max(abs(value), 1.0) * 1e-12
        candidates = self._preferred_values_around(value)
        if direction > 0:
            next_values = [candidate for candidate in candidates if candidate > value + epsilon]
            return next_values[0] if next_values else value

        previous_values = [candidate for candidate in candidates if candidate < value - epsilon]
        return previous_values[-1] if previous_values else value

    def stepBy(self, steps: int):  # noqa: N802 - Qt virtual method name
        if steps == 0:
            return

        # Shared sweep controls use negative dB values, where a logarithmic
        # preferred-number series is not meaningful.
        if self.value() <= 0.0:
            super().stepBy(steps)
            return

        value = self.value()
        direction = 1 if steps > 0 else -1
        for _ in range(abs(steps)):
            value = self._step_once(value, direction)
        self.setValue(float(np.clip(value, self.minimum(), self.maximum())))
