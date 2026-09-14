"""Bounded-memory, four-times interpolated peak estimates (not a compliance meter)."""

import numpy as np
from scipy import signal


class TruePeakMeter:
    """Causal polyphase FIR with history across blocks and ten samples of delay.

    Input and output levels use 1.0 as full scale. No limiting is performed.
    Reset at acquisition discontinuities; flush only at the end of a finite file.
    """

    def __init__(self, channels: int):
        self.channels = channels
        coefficients = signal.firwin(81, 0.25, window=("kaiser", 5.0)) * 4
        self.phases = [coefficients[i::4] for i in range(4)]
        self.reset()

    def reset(self):
        self.states = [np.zeros((len(phase) - 1, self.channels)) for phase in self.phases]

    def process(self, data: np.ndarray) -> np.ndarray:
        samples = np.asarray(data, dtype=np.float64)
        envelope = self.process_envelope(samples)
        if not len(envelope):
            return np.zeros(self.channels)
        if samples.ndim == 1:
            samples = samples[:, None]
        # Include unfiltered samples still awaiting FIR delay.
        return np.maximum(np.max(np.abs(samples), axis=0), np.max(envelope, axis=0))

    def process_envelope(self, data: np.ndarray) -> np.ndarray:
        """Maximum absolute interpolant per input frame, delayed ten frames.

        Each row covers four FIR phases; callers aligning source timestamps
        must discard the first ten rows and drain ten rows at a finite end.
        """
        samples = np.asarray(data, dtype=np.float64)
        if samples.ndim == 1:
            samples = samples[:, None]
        if samples.ndim != 2 or samples.shape[1] != self.channels:
            raise ValueError("Channel count changed; create a new true peak meter")
        if not np.all(np.isfinite(samples)):
            self.reset()
            raise ValueError("True peak input must be finite")
        if not len(samples):
            return np.empty((0, self.channels))
        envelope = np.zeros_like(samples)
        for i, phase in enumerate(self.phases):
            interpolated, self.states[i] = signal.lfilter(phase, [1.0], samples, axis=0, zi=self.states[i])
            np.maximum(envelope, np.abs(interpolated), out=envelope)
        return envelope

    def flush(self) -> np.ndarray:
        """Include the finite signal's trailing filter response, then reset."""
        peaks = self.process(np.zeros((20, self.channels)))
        self.reset()
        return peaks


def estimate_true_peak(data: np.ndarray) -> float:
    """Estimate a finite file's peak, including zero-extended edges, in chunks."""
    samples = np.asarray(data)
    meter = TruePeakMeter(1 if samples.ndim == 1 else samples.shape[1])
    peak = 0.0
    for start in range(0, len(samples), 16384):
        peak = max(peak, float(np.max(meter.process(samples[start : start + 16384]))))
    return max(peak, float(np.max(meter.flush())))


# Margin for interpolation under-reading and subsequent PCM quantization.
# This is an estimated ceiling, not a guarantee for every DAC/filter.
EXPORT_TRUE_PEAK_CEILING = 10 ** (-1.0 / 20.0)
