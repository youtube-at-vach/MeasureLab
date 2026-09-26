"""Seeded stateful exploration through real Qt control methods and DSP callbacks."""

from __future__ import annotations

import os
import random

import pytest

from src.gui.module_registry import MODULE_REGISTRY
from tests.gui_fuzz.actions import available_actions, reveal_control
from tests.gui_fuzz.diagnostics import Scenario
from tests.gui_fuzz.discovery import create_module_widget, module_keys
from tests.gui_fuzz.invariants import (
    check,
    check_closed,
    owned_resources,
    plot_data_count,
    refresh_active_timers,
    scene_item_count,
)


INTERACTIVE_KEYS = (
    "Spectrum Analyzer",
    "Sound Level Meter",
    "LUFS Meter",
    "Oscilloscope",
    "Raw Time Series",
    "Event Detector",
    "Frequency Counter",
    "Spectrogram",
    "Goniometer",
    "Stereo Alignment Monitor",
)
SIGNALS = ("silence", "sine", "noise", "tiny", "full", "clipping", "dc", "left", "right", "different")


@pytest.mark.parametrize("module_key", INTERACTIVE_KEYS)
def test_seeded_interaction_explorer(module_key, qapp, fuzz_engine):
    seed = int(os.environ.get("MEASURELAB_GUI_FUZZ_SEED", "24681357"))
    rng = random.Random(seed)  # noqa: S311 - deterministic exploration, not cryptography
    with Scenario(module_key, seed, strict_runtime_warnings=True) as trace:
        module, widget = create_module_widget(module_key, fuzz_engine)
        trace.module, trace.widget, trace.engine = module, widget, fuzz_engine
        widget.show()
        qapp.processEvents()
        primary_name = MODULE_REGISTRY[module_key].capabilities.console_primary_action.button_attribute
        primary = getattr(widget, primary_name)
        plot_count = plot_data_count(widget)
        resource_count = tuple(map(len, owned_resources(widget, module)))
        assert available_actions(widget, primary_button=primary)

        # Fixed lifecycle prefixes cover ordering; the remainder explores only current enabled controls.
        for step in range(36):
            actions = available_actions(widget, primary_button=primary)
            if step in (0, 9, 18, 27):
                for transition in reveal_control(widget, primary):
                    trace.record(transition.description)
                    transition.execute()
                actions = available_actions(widget, primary_button=primary)
                action = next(action for action in actions if action.target is primary)
            else:
                settings = [action for action in actions if action.target is not primary]
                action = rng.choice(settings or actions)
            trace.record(action.description)
            action.execute()
            if getattr(module, "is_running", False):
                signal = SIGNALS[step % len(SIGNALS)]
                frames = 64 if step % 5 == 0 else 1024
                if step in (12, 24):
                    new_rate = 44100 if step == 12 else 96000
                    trace.record(f"sample_rate={new_rate}")
                    fuzz_engine.sample_rate = new_rate
                trace.record(f"feed({signal!r}, {frames})")
                fuzz_engine.feed(signal, frames)
                refresh_active_timers(widget, module)
            for _ in range(2):
                qapp.processEvents()
            check(
                widget,
                module,
                fuzz_engine,
                initial_plot_count=plot_count,
                initial_resources=resource_count,
                primary=primary,
            )
            trace.assert_clean()

        # A stable signal should not create new scene objects on every repaint.
        for transition in reveal_control(widget, primary):
            trace.record(transition.description)
            transition.execute()
        if not primary.isChecked():
            trace.record("primary.click() [plot stability]")
            primary.click()
        trace.record("feed('silence', 1024) [plot warmup]")
        fuzz_engine.feed("silence", 1024)
        refresh_active_timers(widget, module)
        qapp.processEvents()
        stable_count = scene_item_count(widget)
        for _ in range(12):
            trace.record("feed('silence', 1024) [plot stability]")
            fuzz_engine.feed("silence", 1024)
            refresh_active_timers(widget, module)
            qapp.processEvents()
        assert scene_item_count(widget) <= stable_count + 2
        check(
            widget,
            module,
            fuzz_engine,
            initial_plot_count=plot_count,
            initial_resources=resource_count,
            primary=primary,
        )
        trace.assert_clean()

        if primary.isChecked():
            trace.record("primary.click() [cleanup]")
            primary.click()
        widget.close()
        qapp.processEvents()
        check_closed(widget, module, fuzz_engine)
        trace.assert_clean()
        widget.deleteLater()


@pytest.mark.parametrize("module_key", module_keys())
def test_registered_widget_safe_control_walk(module_key, qapp, fuzz_engine):
    """Exercise setting controls on every page without invoking work or external I/O."""
    seed = 92517
    rng = random.Random(seed)  # noqa: S311 - deterministic exploration, not cryptography
    with Scenario(module_key, seed) as trace:
        module, widget = create_module_widget(module_key, fuzz_engine)
        trace.module, trace.widget, trace.engine = module, widget, fuzz_engine
        widget.show()
        qapp.processEvents()
        primary_name = MODULE_REGISTRY[module_key].capabilities.console_primary_action.button_attribute
        primary = getattr(widget, primary_name) if primary_name else None
        candidates_seen = 0
        for _ in range(8):
            actions = [
                action
                for action in available_actions(widget, primary_button=primary)
                if action.kind != "click" and action.target is not primary
            ]
            if not actions:
                break
            candidates_seen += len(actions)
            action = rng.choice(actions)
            trace.record(action.description)
            action.execute()
            qapp.processEvents()
            trace.assert_clean()
        trace.record(f"candidate_controls_seen={candidates_seen}")
        widget.close()
        qapp.processEvents()
        check_closed(widget, module, fuzz_engine)
        trace.assert_clean()
        widget.deleteLater()
