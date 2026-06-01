import numpy as np
from scipy.signal import lfilter


class PinkNoise:
    """Stateful pink-noise generator (Paul Kellet filter)."""

    def __init__(self):
        # We must keep b0-b6 for backward compatibility with tests
        self.b0 = 0.0
        self.b1 = 0.0
        self.b2 = 0.0
        self.b3 = 0.0
        self.b4 = 0.0
        self.b5 = 0.0
        self.b6 = 0.0

        # Internal state arrays for lfilter
        self._zi0 = np.array([0.0])
        self._zi1 = np.array([0.0])
        self._zi2 = np.array([0.0])
        self._zi3 = np.array([0.0])
        self._zi4 = np.array([0.0])
        self._zi5 = np.array([0.0])

    def generate(self, n: int):
        if n <= 0:
            return np.empty(0, dtype=np.float32)

        white = np.random.randn(n).astype(np.float32)

        # Vectorized implementation of Paul Kellet's refined pink noise filter.
        b0_arr, self._zi0 = lfilter([0.0555179], [1.0, -0.99886], white, zi=self._zi0)
        b1_arr, self._zi1 = lfilter([0.0750759], [1.0, -0.99332], white, zi=self._zi1)
        b2_arr, self._zi2 = lfilter([0.1538520], [1.0, -0.96900], white, zi=self._zi2)
        b3_arr, self._zi3 = lfilter([0.3104856], [1.0, -0.86650], white, zi=self._zi3)
        b4_arr, self._zi4 = lfilter([0.5329522], [1.0, -0.55000], white, zi=self._zi4)
        b5_arr, self._zi5 = lfilter([-0.0168980], [1.0, 0.7616], white, zi=self._zi5)

        b6_arr = np.empty(n, dtype=np.float32)
        b6_arr[0] = self.b6
        if n > 1:
            b6_arr[1:] = white[:-1] * 0.115926

        self.b6 = float(white[-1] * 0.115926)

        # Sync the public attributes with the last internal state for backwards compatibility
        self.b0 = float(b0_arr[-1])
        self.b1 = float(b1_arr[-1])
        self.b2 = float(b2_arr[-1])
        self.b3 = float(b3_arr[-1])
        self.b4 = float(b4_arr[-1])
        self.b5 = float(b5_arr[-1])

        y = b0_arr + b1_arr + b2_arr + b3_arr + b4_arr + b5_arr + b6_arr + white * 0.5362
        return (y * 0.11).astype(np.float32)
