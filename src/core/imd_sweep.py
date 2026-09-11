"""IMD amplitude sweep v1: explicit FFT-band metrics, not standards certification."""

import csv
import io
import json
import math
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
from scipy.signal.windows import blackmanharris


@dataclass(frozen=True)
class Profile:
    profile_id: str
    name: str
    f1: float
    f2: float
    ratio: float

    @property
    def components(self) -> dict[str, float]:
        result = {"carrier_1": self.f1, "carrier_2": self.f2}
        if self.profile_id == "ccif_d2_v1":
            result.update(d2=self.f2 - self.f1, d3_low=2 * self.f1 - self.f2, d3_high=2 * self.f2 - self.f1)
        else:
            for n in range(1, 4):
                result[f"sideband_{n}_lower"] = self.f2 - n * self.f1
                result[f"sideband_{n}_upper"] = self.f2 + n * self.f1
        return result


PROFILES = {
    p.profile_id: p
    for p in (
        Profile("smpte_fft_v1", "SMPTE stimulus / FFT sideband IMD", 60, 7000, 4),
        Profile("din_fft_v1", "DIN stimulus / FFT sideband IMD", 250, 8000, 4),
        Profile("ccif_d2_v1", "CCIF stimulus / d2", 19000, 20000, 1),
    )
}


@dataclass(frozen=True)
class SweepSettings:
    profile_id: str = "smpte_fft_v1"
    start_dbfs: float = -40
    end_dbfs: float = -3
    steps: int = 20
    settling_ms: int = 500
    capture_ms: int = 500
    averages: int = 4
    fade_ms: float = 20

    def validate(self):
        if self.profile_id not in PROFILES:
            raise ValueError("unknown_profile")
        for value in (self.start_dbfs, self.end_dbfs):
            if not math.isfinite(value) or not -100 <= value <= 0:
                raise ValueError("invalid_level")
        if self.start_dbfs == self.end_dbfs:
            raise ValueError("equal_levels")
        for value, lo, hi in (
            (self.steps, 2, 1000),
            (self.settling_ms, 100, 30000),
            (self.capture_ms, 200, 2000),
            (self.averages, 1, 32),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or not lo <= value <= hi:
                raise ValueError("invalid_acquisition_settings")
        if self.capture_ms % 100 or not math.isfinite(self.fade_ms) or not 20 <= self.fade_ms <= 30000:
            raise ValueError("invalid_acquisition_settings")

    @property
    def levels(self):
        self.validate()
        return np.linspace(self.start_dbfs, self.end_dbfs, self.steps).tolist()


class BandPlan:
    def __init__(self, settings: SweepSettings, sample_rate: float):
        settings.validate()
        if not math.isfinite(sample_rate) or sample_rate <= 0:
            raise ValueError("invalid_sample_rate")
        self.settings = settings
        self.profile = PROFILES[settings.profile_id]
        self.sample_rate = sample_rate
        self.n = math.ceil(sample_rate * settings.capture_ms / 1000)
        if not 1 <= self.n <= 1048576:
            raise ValueError("capture_too_large")
        self.df = sample_rate / self.n
        self.hz = np.fft.rfftfreq(self.n, 1 / sample_rate)
        self.bands: dict[str, tuple[float, float]] = {}
        self.indices: dict[str, np.ndarray] = {}
        self.noise_indices: dict[str, np.ndarray] = {}
        self.warnings: list[str] = []
        used = np.zeros(len(self.hz), dtype=bool)
        for key, f in self.profile.components.items():
            width = 4 * self.df + 0.001 * f
            lo, hi = f - width, f + width
            if lo <= 0 or hi >= sample_rate / 2:
                raise ValueError("band_out_of_range")
            if any(lo <= b and hi >= a for a, b in self.bands.values()):
                raise ValueError("overlapping_bands")
            mask = (self.hz >= lo) & (self.hz <= hi) & (self.hz > 0) & (self.hz < sample_rate / 2)
            if not np.any(mask):
                raise ValueError("empty_band")
            self.bands[key] = (lo, hi)
            self.indices[key] = np.flatnonzero(mask)
            used |= mask
            if hi >= 0.9 * sample_rate / 2 and "near_nyquist" not in self.warnings:
                self.warnings.append("near_nyquist")
        for key in ("carrier_1", "carrier_2"):
            f = self.profile.components[key]
            width = 4 * self.df + 0.001 * f
            mask = (abs(self.hz - f) <= max(100, 10 * width)) & ~used
            mask &= (self.hz > 0) & (self.hz < sample_rate / 2)
            self.noise_indices[key] = np.flatnonzero(mask)
            if mask.sum() < 10:
                raise ValueError("insufficient_noise_bins")
        self.window = blackmanharris(self.n, sym=False)
        self.power_scale = 2 / (self.n * float(np.sum(self.window**2)))

    def metadata(self):
        return {
            **asdict(self.settings),
            **asdict(self.profile),
            "method_version": 1,
            "sample_rate": self.sample_rate,
            "N": self.n,
            "df": self.df,
            "capture_seconds": self.n / self.sample_rate,
            "window": "blackmanharris_periodic_4term",
            "band_half_width": "4*df+0.001*f",
            "bands_hz": self.bands,
            "filter": "none",
            "frequency_correction": "off",
            "dc_removal": "record_mean",
            "averaging": "linear_power",
            "level_reference": "dBFS_peak_sum",
            "input_level_reference": "dBFS_sine_rms",
            "levels": self.settings.levels,
        }


class PowerAverage:
    """Only one record and one scalar per band survive each analysis."""

    def __init__(self, plan: BandPlan):
        self.plan = plan
        self.powers = dict.fromkeys(plan.indices, 0.0)
        self.count = 0
        self.flags: set[str] = set()
        self.peak = 0.0

    def add(self, data: np.ndarray):
        p = self.plan
        if data.shape != (p.n,):
            raise ValueError("input_discontinuity")
        if not np.all(np.isfinite(data)):
            raise ValueError("nonfinite_input")
        self.peak = max(self.peak, float(np.max(np.abs(data))))
        if self.peak >= 1 - 1e-7:
            raise ValueError("input_full_scale")
        spectrum = abs(np.fft.rfft((data - np.mean(data)) * p.window)) ** 2
        for key, indices in p.indices.items():
            power = float(np.sum(spectrum[indices]) * p.power_scale)
            self.powers[key] += power
            if key in p.noise_indices:
                f = p.profile.components[key]
                peak_index = indices[np.argmax(spectrum[indices])]
                noise = float(np.median(spectrum[p.noise_indices[key]]))
                if math.sqrt(power) < 1e-6:
                    self.flags.add("carrier_below_threshold")
                if spectrum[peak_index] < 100 * noise or spectrum[peak_index] == 0:
                    self.flags.add("carrier_not_prominent")
                if abs(p.hz[peak_index] - f) > max(p.df, 0.001 * f) + 1e-9:
                    self.flags.add("carrier_frequency_mismatch")
        self.count += 1

    def result(self, sensitivity: float | None = None) -> dict[str, Any]:
        if self.count != self.plan.settings.averages:
            raise ValueError("incomplete_average")
        amplitudes = {k: math.sqrt(v / self.count) for k, v in self.powers.items()}
        ref = (
            (amplitudes["carrier_1"] + amplitudes["carrier_2"]) / 2
            if self.plan.profile.profile_id == "ccif_d2_v1"
            else amplitudes["carrier_2"]
        )
        valid = not self.flags and ref > 0
        numerator = (
            amplitudes["d2"]
            if "d2" in amplitudes
            else math.sqrt(sum(v * v for k, v in amplitudes.items() if k.startswith("sideband")))
        )
        ratio = numerator / ref if valid else None
        components = []
        for key, a in amplitudes.items():
            r = a / ref if valid else None
            volts = a * sensitivity if sensitivity is not None else None
            components.append(
                {
                    "component_id": key,
                    "frequency": self.plan.profile.components[key],
                    "band_hz": self.plan.bands[key],
                    "level_rms_FS": a,
                    "level_dBFS": db(a * math.sqrt(2)),
                    "Vrms": volts,
                    "dBV": db(volts),
                    "ratio": r,
                    "percent": None if r is None else 100 * r,
                    "relative_dB": db(r),
                }
            )
        return {
            "level_rms_FS": numerator if valid else None,
            "level_dBFS": db(numerator * math.sqrt(2)) if valid else None,
            "reference_rms_FS": ref if valid else None,
            "Vrms": numerator * sensitivity if valid and sensitivity is not None else None,
            "dBV": db(numerator * sensitivity) if valid and sensitivity is not None else None,
            "ratio": ratio,
            "percent": None if ratio is None else 100 * ratio,
            "relative_dB": db(ratio),
            "zero_numerator": ratio == 0,
            "components": components,
            "carrier_difference_dB": db(amplitudes["carrier_1"] / amplitudes["carrier_2"]) if valid else None,
            "input_peak": self.peak,
            "flags": sorted(self.flags),
        }


def db(value: float | None) -> float | None:
    return 20 * math.log10(value) if value is not None and value > 0 else None


def snapshot_copy(snapshot):
    """Strict JSON is also the immutable boundary between worker, UI and exporter."""
    return json.loads(json.dumps(snapshot, allow_nan=False))


def serialize(snapshot: dict, format: str) -> str:
    snapshot = snapshot_copy(snapshot)
    if format == "json":
        return json.dumps(snapshot, ensure_ascii=False, allow_nan=False, indent=2) + "\n"
    if format != "csv":
        raise ValueError("Unsupported format")
    output = io.StringIO(newline="")
    columns = [
        "run_id",
        "step_index",
        "status",
        "complete",
        "quality",
        "validity",
        "flags",
        "command_dbfs",
        "A1",
        "A2",
        "component_id",
        "frequency",
        "level_rms_FS",
        "level_dBFS",
        "Vrms",
        "dBV",
        "ratio",
        "percent",
        "relative_dB",
        "run_metadata_json",
    ]
    writer = csv.DictWriter(output, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    metadata = json.dumps({k: v for k, v in snapshot.items() if k != "steps"}, allow_nan=False, ensure_ascii=False)
    for step in snapshot["steps"]:
        common = {
            **step,
            **{k: snapshot[k] for k in ("run_id", "status", "complete", "quality")},
            "step_index": step["index"],
            "flags": json.dumps(step["flags"]),
            "run_metadata_json": metadata,
        }
        writer.writerow({**common, "component_id": "aggregate"})
        for component in step["components"]:
            writer.writerow({**common, **component})
    # Rejected starts have no component rows; retain their diagnostic metadata.
    if not snapshot["steps"]:
        writer.writerow(
            {
                "run_id": snapshot["run_id"],
                "status": snapshot["status"],
                "complete": False,
                "quality": snapshot["quality"],
                "run_metadata_json": metadata,
            }
        )
    return output.getvalue()


def valid_segments(snapshot, percent=False, *, display_floor=False):
    """Preserve numeric values for comparison; apply a floor only for drawing."""
    segments = []
    current = []
    for step in snapshot["steps"]:
        value = step["percent"] if percent else step["relative_dB"]
        valid = step["validity"] != "invalid" and step["ratio"] is not None
        if valid and not percent and display_floor:
            value = max(value if value is not None else -160, -160)
        if not valid or value is None:
            if current:
                segments.append(current)
                current = []
        else:
            current.append((step["command_dbfs"], value))
    if current:
        segments.append(current)
    return segments
