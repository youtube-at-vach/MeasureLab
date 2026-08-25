"""Manual spectrogram orientation rendering benchmark.

Run from the repository root. GUI timing is intentionally reported rather than
asserted because shared CI runners are too noisy for a stable performance gate.
Use ``--include-large`` to include the memory-intensive FFT 65536 case.
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
sys.modules.setdefault("sounddevice", MagicMock())
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import numpy as np  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from src.gui.widgets.spectrogram import (  # noqa: E402
    ORIENTATION_FREQUENCY_X,
    ORIENTATION_TIME_X,
    Spectrogram,
    SpectrogramWidget,
)


@dataclass(frozen=True)
class BenchmarkResult:
    fft_size: int
    orientation: str
    median_ms: float
    p95_ms: float
    qimage_mib: float


class MockAudioEngine:
    sample_rate = 48000

    def register_callback(self, callback):
        return 1

    def unregister_callback(self, callback_id):
        pass


def _set_orientation(widget: SpectrogramWidget, orientation: str) -> None:
    index = widget.direction_combo.findData(orientation)
    if index < 0:
        raise AssertionError(f"Missing orientation: {orientation}")
    widget.direction_combo.setCurrentIndex(index)


def _force_image_render(widget: SpectrogramWidget) -> None:
    widget.img_old.render()
    widget.img_new.render()


def _measure_updates(
    widget: SpectrogramWidget,
    orientation: str,
    iterations: int,
) -> BenchmarkResult:
    _set_orientation(widget, orientation)
    widget.module.spectrogram_ptr = widget.module.history_length // 2
    widget._render_current_spectrogram()
    _force_image_render(widget)

    samples_ms = []
    for _ in range(iterations):
        widget.module.spectrogram_ptr = (widget.module.spectrogram_ptr + 1) % widget.module.history_length
        started = time.perf_counter_ns()
        widget._render_current_spectrogram()
        _force_image_render(widget)
        samples_ms.append((time.perf_counter_ns() - started) / 1_000_000.0)

    qimage_bytes = widget.img_old.qimage.sizeInBytes() + widget.img_new.qimage.sizeInBytes()
    return BenchmarkResult(
        fft_size=widget.module.fft_size,
        orientation=orientation,
        median_ms=median(samples_ms),
        p95_ms=float(np.percentile(samples_ms, 95)),
        qimage_mib=qimage_bytes / (1024 * 1024),
    )


def _measure_switch(widget: SpectrogramWidget, target_orientation: str) -> float:
    started = time.perf_counter_ns()
    _set_orientation(widget, target_orientation)
    _force_image_render(widget)
    return (time.perf_counter_ns() - started) / 1_000_000.0


def _configure_fft(widget: SpectrogramWidget, fft_size: int) -> None:
    widget.module.fft_size = fft_size
    widget.module.reset_buffers()
    rng = np.random.default_rng(fft_size)
    widget.module.spectrogram_buffer[:] = rng.uniform(-120.0, 0.0, widget.module.spectrogram_buffer.shape)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--include-large",
        action="store_true",
        help="Also benchmark FFT 65536, which uses a large history image.",
    )
    parser.add_argument(
        "--lut-size",
        type=int,
        choices=(256, 512),
        default=512,
        help="Force a LUT size so the pyqtgraph fast path can be compared.",
    )
    args = parser.parse_args()

    app = QApplication.instance() or QApplication([])
    module = Spectrogram(MockAudioEngine())
    widget = SpectrogramWidget(module)
    widget.timer.stop()
    widget.scale_combo.setCurrentText("Linear")
    lut = widget.hist.gradient.getLookupTable(args.lut_size)
    widget.img_old.setLookupTable(lut)
    widget.img_new.setLookupTable(lut)

    fft_sizes = [2048, 8192]
    if args.include_large:
        fft_sizes.append(65536)

    print(f"lut_size={args.lut_size}")
    print("fft_size,orientation,median_ms,p95_ms,qimage_mib")
    for fft_size in fft_sizes:
        _configure_fft(widget, fft_size)
        iterations = 3 if fft_size == 65536 else 10
        results = (
            _measure_updates(widget, ORIENTATION_TIME_X, iterations),
            _measure_updates(widget, ORIENTATION_FREQUENCY_X, iterations),
        )
        for result in results:
            print(
                f"{result.fft_size},{result.orientation},{result.median_ms:.3f},"
                f"{result.p95_ms:.3f},{result.qimage_mib:.1f}"
            )

        _set_orientation(widget, ORIENTATION_TIME_X)
        _force_image_render(widget)
        to_waterfall_ms = _measure_switch(widget, ORIENTATION_FREQUENCY_X)
        to_time_x_ms = _measure_switch(widget, ORIENTATION_TIME_X)
        print(
            f"switch,{fft_size},time_x_to_frequency_x={to_waterfall_ms:.3f}ms,"
            f"frequency_x_to_time_x={to_time_x_ms:.3f}ms"
        )

    widget.close()
    app.processEvents()


if __name__ == "__main__":
    main()
