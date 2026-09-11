import csv
import io
from dataclasses import replace

import numpy as np
import pytest

from src.core.imd_sweep import BandPlan, PROFILES, PowerAverage, SweepSettings, serialize, valid_segments


def signal(plan, db=-40, ppm=0, phase=0, all_bands=False):
    p = plan.profile
    t = np.arange(plan.n) / plan.sample_rate * (1 + ppm / 1e6)
    carrier = 0.2 if p.ratio == 1 else 0.1
    wave = p.ratio * carrier * np.sin(2 * np.pi * p.f1 * t + phase) + carrier * np.sin(2 * np.pi * p.f2 * t + phase)
    ratio = 10 ** (db / 20)
    products = {k: f for k, f in p.components.items() if k.startswith("sideband") or k == "d2"}
    if not all_bands:
        products = dict(list(products.items())[:1])
    for f in products.values():
        wave += carrier * ratio / np.sqrt(len(products)) * np.sin(2 * np.pi * f * t + phase * 0.7)
    return wave


@pytest.mark.parametrize("rate", [44100, 48000, 96000])
@pytest.mark.parametrize("duration", [200, 500])
@pytest.mark.parametrize("profile", list(PROFILES))
@pytest.mark.parametrize("ppm", [-500, 0, 500])
@pytest.mark.parametrize("level", [-80, -40, -20])
def test_injected_products(rate, duration, profile, ppm, level):
    plan = BandPlan(SweepSettings(profile_id=profile, capture_ms=duration, averages=1), rate)
    avg = PowerAverage(plan)
    avg.add(signal(plan, level, ppm, phase=0.4))
    result = avg.result()
    assert not result["flags"]
    tolerance = 0.1 if ppm == 0 else 0.5 if duration == 200 else 0.2
    assert result["relative_dB"] == pytest.approx(level, abs=tolerance)
    assert result["percent"] == pytest.approx(100 * 10 ** (level / 20), rel=0.06)


@pytest.mark.parametrize("profile", list(PROFILES))
def test_rss_power_averaging_calibration_and_gain(profile):
    plan = BandPlan(SweepSettings(profile_id=profile, averages=2), 48000)
    avg = PowerAverage(plan)
    avg.add(signal(plan, -40, all_bands=True))
    avg.add(signal(plan, -20, all_bands=True))
    res = avg.result(2.0)
    assert res["ratio"] == pytest.approx(np.sqrt((0.01**2 + 0.1**2) / 2), rel=1e-5)
    for component in res["components"]:
        assert component["Vrms"] == component["level_rms_FS"] * 2
    avg2 = PowerAverage(plan)
    avg2.add(0.25 * signal(plan, -40, all_bands=True))
    avg2.add(0.25 * signal(plan, -20, all_bands=True))
    assert avg2.result()["ratio"] == pytest.approx(res["ratio"])


def test_ccif_d3_not_included():
    plan = BandPlan(SweepSettings(profile_id="ccif_d2_v1", averages=1), 48000)
    data = signal(plan)
    t = np.arange(plan.n) / plan.sample_rate
    data += 0.02 * np.sin(2 * np.pi * 18000 * t) + 0.03 * np.sin(2 * np.pi * 21000 * t)
    avg = PowerAverage(plan)
    avg.add(data)
    result = avg.result()
    assert result["percent"] == pytest.approx(1, abs=1e-5)
    assert result["components"][3]["ratio"] == pytest.approx(0.1, abs=1e-5)


@pytest.mark.parametrize("bad", ["silence", "noise", "missing", "weak", "frequency"])
def test_invalid_carriers_do_not_return_normal_zero(bad):
    plan = BandPlan(SweepSettings(averages=1), 48000)
    data = signal(plan)
    t = np.arange(plan.n) / plan.sample_rate
    if bad == "silence":
        data *= 0
    elif bad == "noise":
        data = np.random.default_rng(4).normal(0, 0.01, plan.n)
    elif bad == "missing":
        data = 0.4 * np.sin(2 * np.pi * 60 * t)
    elif bad == "weak":
        data *= 1e-7
    elif bad == "frequency":
        data = signal(plan, ppm=1800)
    avg = PowerAverage(plan)
    avg.add(data)
    result = avg.result()
    assert result["flags"]
    assert result["ratio"] is None and result["relative_dB"] is None


@pytest.mark.parametrize(
    "value,reason",
    [(np.nan, "nonfinite_input"), (np.inf, "nonfinite_input"), (1.0, "input_full_scale"), (-1.0, "input_full_scale")],
)
def test_nonfinite_and_clip(value, reason):
    plan = BandPlan(SweepSettings(averages=1), 48000)
    data = signal(plan)
    data[0] = value
    with pytest.raises(ValueError, match=reason):
        PowerAverage(plan).add(data)


def test_zero_numerator_is_not_db_floor():
    plan = BandPlan(SweepSettings(averages=1), 48000)
    avg = PowerAverage(plan)
    avg.count = 1
    avg.powers.update(carrier_1=0.08, carrier_2=0.005)
    res = avg.result()
    assert res["ratio"] == 0 and res["relative_dB"] is None and res["zero_numerator"]


def test_band_preflight():
    settings = SweepSettings(profile_id="ccif_d2_v1")
    with pytest.raises(ValueError, match="band_out_of_range"):
        BandPlan(settings, 32000)
    assert BandPlan(settings, 44100).warnings == ["near_nyquist"]
    assert BandPlan(settings, 48000).warnings == []
    for rate in [np.nan, 0, -1]:
        with pytest.raises(ValueError):
            BandPlan(settings, rate)
    with pytest.raises(ValueError, match="capture_too_large"):
        BandPlan(settings, 1e8)


@pytest.mark.parametrize(
    "change",
    [
        {"start_dbfs": np.nan},
        {"end_dbfs": 1},
        {"start_dbfs": -101},
        {"end_dbfs": -40},
        {"steps": 1001},
        {"steps": 2.5},
        {"averages": 0},
        {"capture_ms": 250},
        {"settling_ms": 99},
        {"fade_ms": 19},
    ],
)
def test_model_rejects_settings(change):
    with pytest.raises(ValueError):
        BandPlan(replace(SweepSettings(), **change), 48000)


def test_export_strict_and_gaps():
    step = {
        "index": 0,
        "command_dbfs": -40,
        "validity": "valid",
        "flags": [],
        "ratio": 0.01,
        "percent": 1,
        "relative_dB": -40,
        "components": [],
    }
    snap = {
        "run_id": "test",
        "status": "cancelled",
        "complete": False,
        "quality": "invalid",
        "metadata": {"level_reference": "dBFS_peak_sum"},
        "steps": [
            step,
            {**step, "index": 1, "ratio": None, "relative_dB": None, "validity": "invalid"},
            {**step, "index": 2},
        ],
    }
    assert len(valid_segments(snap)) == 2
    assert "null" in serialize(snap, "json")
    rows = list(csv.DictReader(io.StringIO(serialize(snap, "csv"))))
    assert len(rows) == 3 and rows[1]["ratio"] == ""
    assert "dBFS_peak_sum" in rows[0]["run_metadata_json"]
    snap["metadata"]["bad"] = np.nan
    with pytest.raises(ValueError):
        serialize(snap, "json")
