"""Manual State A/State C rendering benchmark for Spectrum Analyzer.

Run from the repository root. This intentionally is not a pytest performance
assertion because GUI timing on shared CI runners is too noisy for a stable gate.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import numpy as np
from PyQt6.QtWidgets import QApplication

from src.core.module_constants import MODULE_SPECTRUM_ANALYZER
from src.gui.module_registry import MODULE_REGISTRY
from src.gui.widgets.detachable_wrapper import DetachableWidgetWrapper
from src.gui.widgets.spectrum_analyzer import SpectrumAnalyzer, SpectrumAnalyzerWidget


@dataclass(frozen=True)
class BenchmarkCase:
    name: str
    bins: int
    channel_mode: str = "Average"
    octave_smoothing: str = "None"
    peak_hold: bool = False
    rta_mode: bool = False
    iterations: int = 30
    warmup: int = 5


@dataclass(frozen=True)
class BenchmarkResult:
    state: str
    case: str
    median_ms: float
    p95_ms: float
    viewport_width: float
    viewport_height: float
    rendered_points: int


CASES = (
    BenchmarkCase("interactive", bins=2049, iterations=60, warmup=10),
    BenchmarkCase("dense-dual-peak", bins=32769, channel_mode="Dual", peak_hold=True),
    BenchmarkCase("large-envelope", bins=524289, iterations=8, warmup=2),
    BenchmarkCase(
        "rta-third-octave",
        bins=32769,
        octave_smoothing="1/3 Octave",
        rta_mode=True,
        iterations=15,
        warmup=3,
    ),
)


def _make_engine() -> MagicMock:
    engine = MagicMock()
    engine.sample_rate = 48000
    engine.calibration = MagicMock()
    engine.calibration.input_sensitivity = 1.0
    engine.calibration.output_gain = 1.0
    engine.calibration.get_input_offset_db.return_value = 0.0
    engine.calibration.get_spl_offset_db.return_value = None
    engine.register_callback.return_value = 1
    return engine


def _configure_case(module: SpectrumAnalyzer, case: BenchmarkCase) -> None:
    freqs = np.linspace(0.0, 24000.0, case.bins, dtype=np.float64)
    base = -72.0 + 8.0 * np.sin(np.linspace(0.0, 30.0, case.bins, dtype=np.float64))
    if case.channel_mode == "Dual":
        magnitude = np.column_stack((base, base - 3.0))
    else:
        magnitude = base

    peak_magnitude = magnitude.copy() if case.peak_hold else None
    payload = {
        "freqs": freqs,
        "magnitude": magnitude,
        "overall_weighted_db": -24.0,
        "peak_magnitude": peak_magnitude,
    }

    module.is_running = True
    module.analysis_mode = "Spectrum"
    module.channel_mode = case.channel_mode
    module.octave_smoothing = case.octave_smoothing
    module.peak_hold = case.peak_hold
    module.rta_mode = case.rta_mode
    module.process_queue = lambda: None
    module.compute_spectrum = lambda: payload


def _resize_for_plot_size(
    app: QApplication,
    host,
    widget: SpectrumAnalyzerWidget,
    target_width: int = 1000,
    target_height: int = 520,
) -> tuple[float, float]:
    host.resize(1200, 900)
    host.show()
    app.processEvents()
    for _ in range(5):
        current_width = float(widget.plot_widget.plotItem.vb.width())
        current_height = float(widget.plot_widget.plotItem.vb.height())
        if abs(current_width - target_width) <= 1.0 and abs(current_height - target_height) <= 1.0:
            break
        host.resize(
            max(400, host.width() + round(target_width - current_width)),
            max(300, host.height() + round(target_height - current_height)),
        )
        app.processEvents()
    return (
        float(widget.plot_widget.plotItem.vb.width()),
        float(widget.plot_widget.plotItem.vb.height()),
    )


def _rendered_points(widget: SpectrumAnalyzerWidget) -> int:
    if widget.module.rta_mode:
        bars = (widget.rta_bar_main, widget.rta_bar_left, widget.rta_bar_right)
        return max((len(bar.opts.get("x", ())) for bar in bars if bar.isVisible()), default=0)

    curves = (widget.plot_curve, widget.plot_curve_2, widget.peak_curve)
    return max((len(curve.xData) for curve in curves if curve.xData is not None), default=0)


def _object_identities(widget: SpectrumAnalyzerWidget) -> dict[str, int]:
    names = (
        "timer",
        "plot_widget",
        "proxy",
        "v_line",
        "h_line",
        "plot_curve",
        "plot_curve_2",
        "peak_curve",
        "rta_bar_main",
        "rta_bar_left",
        "rta_bar_right",
        "controls_group",
        "display_widget",
    )
    return {name: id(getattr(widget, name)) for name in names if hasattr(widget, name)}


def _measure_case(
    app: QApplication,
    host,
    widget: SpectrumAnalyzerWidget,
    state: str,
    case: BenchmarkCase,
) -> BenchmarkResult:
    _configure_case(widget.module, case)
    viewport_width, viewport_height = _resize_for_plot_size(app, host, widget)

    for _ in range(case.warmup):
        widget.update_plot()
        app.processEvents()

    samples_ms = []
    for _ in range(case.iterations):
        started = time.perf_counter_ns()
        widget.update_plot()
        app.processEvents()
        samples_ms.append((time.perf_counter_ns() - started) / 1_000_000.0)

    return BenchmarkResult(
        state=state,
        case=case.name,
        median_ms=median(samples_ms),
        p95_ms=float(np.percentile(samples_ms, 95)),
        viewport_width=viewport_width,
        viewport_height=viewport_height,
        rendered_points=_rendered_points(widget),
    )


def _print_results(results: list[BenchmarkResult]) -> None:
    print("state,case,median_ms,p95_ms,viewport_width,viewport_height,rendered_points")
    for result in results:
        print(
            f"{result.state},{result.case},{result.median_ms:.3f},{result.p95_ms:.3f},"
            f"{result.viewport_width:.1f},{result.viewport_height:.1f},{result.rendered_points}"
        )

    by_key = {(result.state, result.case): result for result in results}
    for case in CASES:
        normal = by_key.get(("A", case.name))
        split = by_key.get(("C", case.name))
        if normal is None or split is None:
            continue
        median_limit = normal.median_ms + max(normal.median_ms * 0.05, 0.2)
        p95_limit = normal.p95_ms + max(normal.p95_ms * 0.05, 0.2)
        status = "PASS" if split.median_ms <= median_limit and split.p95_ms <= p95_limit else "REVIEW"
        print(
            f"{status}: {case.name} A->C "
            f"median={split.median_ms - normal.median_ms:+.3f} ms, "
            f"p95={split.p95_ms - normal.p95_ms:+.3f} ms"
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--state-a-only",
        action="store_true",
        help="Measure only the current normal hierarchy (used for the pre-change baseline).",
    )
    args = parser.parse_args()

    app = QApplication.instance() or QApplication([])
    module = SpectrumAnalyzer(_make_engine())
    widget = SpectrumAnalyzerWidget(module)
    wrapper = DetachableWidgetWrapper(
        widget,
        "Spectrum Analyzer Benchmark",
        capabilities=MODULE_REGISTRY[MODULE_SPECTRUM_ANALYZER].capabilities,
    )
    identities = _object_identities(widget)

    results = [_measure_case(app, wrapper, widget, "A", case) for case in CASES]

    if not args.state_a_only and wrapper.is_splittable:
        wrapper.split()
        app.processEvents()
        if identities != _object_identities(widget):
            raise AssertionError("Split recreated a performance-sensitive object")
        results.extend(_measure_case(app, wrapper.split_display_window, widget, "C", case) for case in CASES)

        wrapper.reattach_all()
        app.processEvents()
        if identities != _object_identities(widget):
            raise AssertionError("Reattach recreated a performance-sensitive object")

    _print_results(results)
    wrapper.close()
    app.processEvents()


if __name__ == "__main__":
    main()
