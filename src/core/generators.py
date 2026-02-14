import numpy as np


class PinkNoise:
    """Stateful pink-noise generator (Paul Kellet filter)."""

    def __init__(self):
        self.b0 = 0.0
        self.b1 = 0.0
        self.b2 = 0.0
        self.b3 = 0.0
        self.b4 = 0.0
        self.b5 = 0.0
        self.b6 = 0.0

    def generate(self, n: int):
        white = np.random.randn(n).astype(np.float32)

        out = np.empty(n, dtype=np.float32)
        b0 = self.b0
        b1 = self.b1
        b2 = self.b2
        b3 = self.b3
        b4 = self.b4
        b5 = self.b5
        b6 = self.b6

        # Coefficients from Paul Kellet's refined pink noise filter.
        for i in range(n):
            w = float(white[i])
            b0 = 0.99886 * b0 + w * 0.0555179
            b1 = 0.99332 * b1 + w * 0.0750759
            b2 = 0.96900 * b2 + w * 0.1538520
            b3 = 0.86650 * b3 + w * 0.3104856
            b4 = 0.55000 * b4 + w * 0.5329522
            b5 = -0.7616 * b5 - w * 0.0168980
            y = b0 + b1 + b2 + b3 + b4 + b5 + b6 + w * 0.5362
            b6 = w * 0.115926
            out[i] = y * 0.11

        self.b0, self.b1, self.b2, self.b3, self.b4, self.b5, self.b6 = b0, b1, b2, b3, b4, b5, b6
        return out
