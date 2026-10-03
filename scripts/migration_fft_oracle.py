"""Independent, finite-sum/analytic MIG-003-A oracle (never imports product DSP)."""

from __future__ import annotations

import numpy as np


def cases(suite: str) -> list[dict]:
    """The small corpus is versioned; extended arrays are materialized locally."""
    result = []

    def add(name, n, signal, window="boxcar", dtype="<f8", tones=None):
        result.append(dict(id=name, n=n, signal=signal, window=window, dtype=dtype, tones=tones or [], rate_hz=48000))

    if suite == "small":
        stereo = [[37, 1 / 32, 0.0], [71, 2 / 32, np.pi / 16]]
        for window in ("boxcar", "hann"):
            add(f"ac01-{window}-f64", 4096, "cosine", window, tones=stereo)
            add(f"ac01-{window}-f32", 4096, "cosine", window, "<f4", stereo)
            for signal in ("dc", "nyquist", "impulse", "silence"):
                add(f"{signal}-{window}", 4096, signal, window)
        add("tone-quarter", 4096, "cosine", tones=[[37, 0.25, 0.0]])
        # The last odd-N bin is not Nyquist and must be doubled.
        add("odd-last-bin", 4095, "cosine", tones=[[2047, 0.125, 0.3]])
    elif suite == "extended":
        for n in (24000, 48000, 4194304):
            for window in ("boxcar", "hann"):
                add(f"tone-{n}-{window}", n, "cosine", window, tones=[[37, 0.25, 0.0]])
    else:
        raise ValueError(f"Unknown suite: {suite}")
    return result


def make_input(spec: dict) -> np.ndarray:
    n = spec["n"]
    t = np.arange(n, dtype=np.float64)
    match spec["signal"]:
        case "cosine":
            x = np.column_stack([a * np.cos(2 * np.pi * k * t / n + p) for k, a, p in spec["tones"]])
        case "dc":
            x = np.full((n, 1), 0.125)
        case "nyquist":
            x = (0.125 * (1 - 2 * (np.arange(n) % 2)))[:, None]
        case "impulse":
            x = np.zeros((n, 1))
            x[0, 0] = 1
        case "silence":
            x = np.zeros((n, 1))
        case _:
            raise ValueError("Unknown signal")
    return np.ascontiguousarray(x, dtype=spec["dtype"])


def window_values(n: int, name: str) -> np.ndarray:
    if n < 3:
        raise ValueError("Window requires N >= 3")
    if name == "boxcar":
        return np.ones(n)
    if name != "hann":
        raise ValueError("Unknown window")
    return 0.5 - 0.5 * np.cos(2 * np.pi * np.arange(n) / (n - 1))


def kernel(offset: np.ndarray, n: int) -> np.ndarray:
    """(1/N) sum exp(-2πi offset*j/N), evaluated without FFT or an NxN matrix."""
    # Reduce modulo N before sinc evaluation, including aliases at Nyquist.
    offset = (offset + n / 2) % n - n / 2
    return np.exp(-1j * np.pi * offset * ((n - 1) / n)) * np.sinc(offset) / np.sinc(offset / n)


def analytic_fft(spec: dict) -> np.ndarray:
    """Ideal, unquantized X/N. f32 comparisons explicitly allow input quantization."""
    n = spec["n"]
    bins = np.arange(n // 2 + 1, dtype=np.float64)

    def unwindowed(at):
        match spec["signal"]:
            case "cosine":
                return np.column_stack(
                    [
                        a / 2 * (np.exp(1j * p) * kernel(at - k, n) + np.exp(-1j * p) * kernel(at + k, n))
                        for k, a, p in spec["tones"]
                    ]
                )
            case "dc":
                return (0.125 * kernel(at, n))[:, None]
            case "nyquist":
                return (0.125 * kernel(at - n / 2, n))[:, None]
            case "impulse":
                return np.full((len(at), 1), 1 / n, dtype=np.complex128)
            case "silence":
                return np.zeros((len(at), 1), dtype=np.complex128)
            case _:
                raise ValueError("Unknown signal")

    if spec["window"] == "boxcar":
        return unwindowed(bins)
    shift = n / (n - 1)
    return 0.5 * unwindowed(bins) - 0.25 * unwindowed(bins - shift) - 0.25 * unwindowed(bins + shift)


def quantities(z: np.ndarray, w: np.ndarray, x: np.ndarray, rate: int) -> dict[str, np.ndarray]:
    """Contract normalization; z is X/N, x is the saved, quantized input."""
    n = len(w)
    factor = np.full(len(z), 2.0)
    factor[0] = 1
    if n % 2 == 0:
        factor[-1] = 1
    magnitude = np.abs(z) * n
    psd = factor[:, None] * magnitude**2 / (rate * np.sum(w**2))
    return {
        "frequency_hz": np.arange(len(z)) * (rate / n),
        "peak_fs": factor[:, None] * magnitude / np.sum(w),
        "psd_fs2_hz": psd,
        "rms_fs": np.sqrt(np.mean(x.astype(np.float64) ** 2, axis=0)),
        "integrated_power_fs2": np.sum(psd, axis=0) * (rate / n),
        "time_window_power_fs2": np.sum((x * w[:, None]) ** 2, axis=0) / np.sum(w**2),
    }


def theory(spec: dict, x: np.ndarray) -> dict[str, np.ndarray]:
    w = window_values(spec["n"], spec["window"])
    z = analytic_fft(spec)
    return {"window": w, "fft_over_n": z, "inverse_windowed": x * w[:, None], **quantities(z, w, x, spec["rate_hz"])}
