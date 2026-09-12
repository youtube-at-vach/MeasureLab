"""Compare actual analyzer widgets and capture reproducible peak-marker views.

Use --baseline-source with a pre-change spectrum_analyzer.py to compare the same
input and viewport. Timings include update_plot and Qt painting, without audio
hardware. No timing assertions: repeat on an otherwise idle machine.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
from pathlib import Path
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import numpy as np
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication, QDialog

from tests.benchmarks.gui.benchmark_spectrum_analyzer_split import (
    CASES,
    BenchmarkCase,
    _configure_case,
    _make_engine,
    _resize_for_plot_size,
)
from src.core.localization import get_manager
from src.core.module_constants import MODULE_SPECTRUM_ANALYZER
from src.gui.module_registry import MODULE_REGISTRY
from src.gui.widgets.detachable_wrapper import DetachableWidgetWrapper
from src.gui.widgets import spectrum_analyzer


def measure_paired_off(app, baseline, iterations):
    """Alternate baseline/new rendering within each case to reduce timing drift."""
    widgets = [
        impl.SpectrumAnalyzerWidget(impl.SpectrumAnalyzer(_make_engine())) for impl in (baseline, spectrum_analyzer)
    ]
    wrappers = [
        DetachableWidgetWrapper(
            w, "Spectrum Analyzer", capabilities=MODULE_REGISTRY[MODULE_SPECTRUM_ANALYZER].capabilities
        )
        for w in widgets
    ]
    print("state,case,baseline_median_ms,off_median_ms,baseline_p95_ms,off_p95_ms")
    for state in ["normal", "compact", "split"]:
        for w, wrapper in zip(widgets, wrappers, strict=True):
            if state == "compact":
                w.set_compact_mode(True)
            elif state == "split":
                w.set_compact_mode(False)
                wrapper.split()
        for case in CASES:
            sizes = []
            for w, wrapper in zip(widgets, wrappers, strict=True):
                _configure_case(w.module, case)
                host = wrapper.split_display_window if state == "split" else wrapper
                sizes.append(_resize_for_plot_size(app, host, w))
                for _ in range(10):
                    w.update_plot()
                    app.processEvents()
            assert sizes[0] == sizes[1], sizes
            samples = [[], []]
            for index in range(iterations):
                for side in (0, 1) if index % 2 else (1, 0):
                    start = time.perf_counter_ns()
                    widgets[side].update_plot()
                    app.processEvents()
                    samples[side].append((time.perf_counter_ns() - start) / 1e6)
            print(
                f"{state},{case.name},{np.median(samples[0]):.3f},{np.median(samples[1]):.3f},"
                f"{np.percentile(samples[0], 95):.3f},{np.percentile(samples[1], 95):.3f}",
                flush=True,
            )
    for wrapper in wrappers:
        wrapper.close()
    app.processEvents()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-source", type=Path)
    parser.add_argument("--mode", choices=["off", "display", "raw"], default="off")
    parser.add_argument("--capture-dir", type=Path)
    parser.add_argument("--language", default="en")
    parser.add_argument("--iterations", type=int, default=80)
    parser.add_argument("--detector-only", action="store_true")
    parser.add_argument("--paired-off", action="store_true")
    args = parser.parse_args()
    if args.detector_only:
        from src.core.spectrum_peaks import detect_spectrum_peaks

        print("bins,input,median_ms,p95_ms,peaks")
        for bins in [32769, 524289, 2097153]:
            f = np.arange(bins, dtype=float)
            for kind in ["noise", "comb", "rejected-comb", "ramp"]:
                y = np.random.default_rng(0).uniform(-100, -20, bins)
                if kind in {"comb", "rejected-comb"}:
                    y[:] = -100
                    y[1::2] = -20
                elif kind == "ramp":
                    y = np.linspace(-100, -20, bins) + 0.3 * np.sin(f)
                samples = []
                for _ in range(10):
                    start = time.perf_counter_ns()
                    peaks = detect_spectrum_peaks(f, y, prominence=81 if kind == "rejected-comb" else 6)
                    samples.append((time.perf_counter_ns() - start) / 1e6)
                print(
                    f"{bins},{kind},{np.median(samples):.3f},{np.percentile(samples, 95):.3f},{len(peaks)}", flush=True
                )
        return
    implementation = spectrum_analyzer
    if args.baseline_source:
        spec = importlib.util.spec_from_file_location("baseline_spectrum", args.baseline_source)
        implementation = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(implementation)
    app = QApplication.instance() or QApplication([])
    get_manager().load_language(args.language)
    if args.paired_off:
        if not args.baseline_source:
            parser.error("--paired-off requires --baseline-source")
        measure_paired_off(app, implementation, args.iterations)
        return
    module = implementation.SpectrumAnalyzer(_make_engine())
    widget = implementation.SpectrumAnalyzerWidget(module)
    widget.marker_mode = args.mode
    wrapper = DetachableWidgetWrapper(
        widget, "Spectrum Analyzer", capabilities=MODULE_REGISTRY[MODULE_SPECTRUM_ANALYZER].capabilities
    )
    tones = BenchmarkCase("four-tones", bins=32769)
    print("state,case,mode,median_ms,p95_ms,max_ms,plot_width,plot_height")
    for state in ["normal", "compact", "split"]:
        if state == "compact":
            widget.set_compact_mode(True)
        elif state == "split":
            widget.set_compact_mode(False)
            wrapper.split()
        host = wrapper.split_display_window if state == "split" else wrapper
        for case in (*CASES, tones):
            _configure_case(module, case)
            if case == tones:
                widget.fft_combo.setCurrentText("65536")
                f = np.linspace(0, 24000, case.bins)
                y = -100 + 2 * np.sin(f * 0.017)
                for hz, level in [(100, -30), (1000, -12), (3000, -40), (8000, -55)]:
                    y += (level + 100) * np.exp(-0.5 * ((f - hz) / 3) ** 2)
                module.compute_spectrum = lambda f=f, y=y: dict(
                    freqs=f, magnitude=y, overall_weighted_db=-15, peak_magnitude=None
                )
            width, height = _resize_for_plot_size(app, host, widget)
            if hasattr(widget, "_clear_peak_markers"):
                widget._clear_peak_markers()
            for _ in range(10):
                widget.update_plot()
                app.processEvents()
            samples = []
            for _ in range(args.iterations):
                start = time.perf_counter_ns()
                widget.update_plot()
                app.processEvents()
                samples.append((time.perf_counter_ns() - start) / 1e6)
            print(
                f"{state},{case.name},{args.mode},{np.median(samples):.3f},"
                f"{np.percentile(samples, 95):.3f},{max(samples):.3f},{width:.1f},{height:.1f}",
                flush=True,
            )
            if args.capture_dir and case == tones:
                args.capture_dir.mkdir(parents=True, exist_ok=True)
                host.grab().save(str(args.capture_dir / f"{state}.png"))
                if state == "split":
                    wrapper.split_control_window.grab().save(str(args.capture_dir / "split-controls.png"))
        if args.capture_dir and state == "normal" and hasattr(widget, "configure_peak_markers"):

            def capture_dialog():
                for dialog in app.topLevelWidgets():
                    if isinstance(dialog, QDialog) and dialog.isVisible():
                        dialog.grab().save(str(args.capture_dir / "settings.png"))
                        hint = dialog.minimumSizeHint()
                        print(f"dialog minimumSizeHint: {hint.width()}x{hint.height()}", flush=True)
                        dialog.reject()

            QTimer.singleShot(100, capture_dialog)
            widget.configure_peak_markers()
    wrapper.close()
    app.processEvents()


if __name__ == "__main__":
    main()
