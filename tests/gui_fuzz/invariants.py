"""Cross-widget checks that run after every explored transition."""

from __future__ import annotations

import math

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import QThread, QTimer
from PyQt6.QtWidgets import QApplication


def owned_resources(widget, module) -> tuple[list[QTimer], list[QThread]]:
    objects = list(widget.findChildren(QTimer)) + list(widget.findChildren(QThread))
    for owner in (widget, module):
        for value in vars(owner).values():
            if isinstance(value, (QTimer, QThread)):
                objects.append(value)
    timers = list({id(value): value for value in objects if isinstance(value, QTimer)}.values())
    threads = list({id(value): value for value in objects if isinstance(value, QThread)}.values())
    return timers, threads


def plot_items(widget) -> list[pg.PlotItem]:
    items = {}
    for graph_type in (pg.PlotWidget, pg.GraphicsLayoutWidget):
        for graph in widget.findChildren(graph_type):
            for item in graph.scene().items():
                if isinstance(item, pg.PlotItem):
                    items[id(item)] = item
    return list(items.values())


def plot_data_count(widget) -> int:
    return sum(len(plot.listDataItems()) for plot in plot_items(widget))


def scene_item_count(widget) -> int:
    scenes = {}
    for graph_type in (pg.PlotWidget, pg.GraphicsLayoutWidget):
        for graph in widget.findChildren(graph_type):
            scenes[id(graph.scene())] = graph.scene()
    return sum(len(scene.items()) for scene in scenes.values())


def refresh_active_timers(widget, module) -> None:
    """Force the same timeout slots as Qt's clock, independent of wall time."""
    timers, _threads = owned_resources(widget, module)
    for timer in timers:
        if timer.isActive():
            timer.timeout.emit()


def check(widget, module, engine, *, initial_plot_count: int, initial_resources: tuple[int, int], primary=None) -> None:
    responded = []
    QTimer.singleShot(0, lambda: responded.append(True))
    QApplication.processEvents()
    if not responded:
        raise AssertionError("UI event loop did not respond to a queued timer")
    if engine.last_callback_error is not None or engine.callback_error_count:
        raise AssertionError(f"Audio callback failure: {engine.last_callback_error!r}")
    if hasattr(module, "is_running") and hasattr(module, "callback_id"):
        callback_id = module.callback_id
        if module.is_running != (callback_id in engine.callbacks):
            raise AssertionError(f"Run/callback mismatch: running={module.is_running}, callback={callback_id}")
    if primary is not None and primary.isCheckable() and hasattr(module, "is_running"):
        if primary.isChecked() != bool(module.is_running):
            raise AssertionError(
                f"Start/Stop button mismatch: checked={primary.isChecked()}, running={module.is_running}"
            )

    for name in ("input_data", "data_buffer", "last_results"):
        value = getattr(module, name, None)
        if isinstance(value, np.ndarray):
            if value.ndim == 2 and value.shape[1] not in (1, 2):
                raise AssertionError(f"{name}: unexpected channel shape {value.shape}")
            if not np.isfinite(value).all():
                raise AssertionError(f"{name}: NaN/Inf")

    plots = plot_items(widget)
    if not plots:
        raise AssertionError("Measurement widget has no plot object")
    count = plot_data_count(widget)
    if count > initial_plot_count + 32:
        raise AssertionError(f"Plot item growth: {initial_plot_count} -> {count}")
    for plot in plots:
        for data_item in plot.listDataItems():
            x, y = data_item.getData()
            if x is None or y is None:
                continue
            # pyqtgraph's stepMode="center" requires N+1 bin edges for N heights.
            expected_x = len(y) + (data_item.opts.get("stepMode") == "center")
            if len(x) != expected_x:
                raise AssertionError(
                    f"Plot {data_item.name()!r} x/y length mismatch: {len(x)} != {len(y)} "
                    f"(stepMode={data_item.opts.get('stepMode')!r})"
                )
            if np.isinf(x).any() or np.isinf(y).any():
                raise AssertionError(f"Plot {data_item.name()!r} contains Inf")
            if (np.isnan(x).any() or np.isnan(y).any()) and data_item.opts.get("connect") != "finite":
                # LUFS uses connect="finite" with NaN gaps for not-yet-available
                # short-term values and separated peak event intervals.
                raise AssertionError(f"Plot {data_item.name()!r} contains unexpected NaN")
        for low, high in plot.getViewBox().viewRange():
            if not (math.isfinite(low) and math.isfinite(high) and high > low):
                raise AssertionError(f"Invalid plot range: {(low, high)}")
    for image in widget.findChildren(pg.GraphicsLayoutWidget):
        for item in image.scene().items():
            if isinstance(item, pg.ImageItem) and item.image is not None and not np.isfinite(item.image).all():
                raise AssertionError("Plot image contains NaN/Inf")

    timers, threads = owned_resources(widget, module)
    if len(timers) > initial_resources[0] + 4 or len(threads) > initial_resources[1] + 2:
        raise AssertionError(f"Timer/thread growth: {initial_resources} -> {(len(timers), len(threads))}")


def check_closed(widget, module, engine) -> None:
    if engine.callbacks:
        raise AssertionError(f"Callbacks remain after close: {list(engine.callbacks)}")
    timers, threads = owned_resources(widget, module)
    active = [repr(timer) for timer in timers if timer.isActive()]
    running = [repr(thread) for thread in threads if thread.isRunning()]
    if active or running:
        raise AssertionError(f"Resources remain after close: timers={active}, threads={running}")
