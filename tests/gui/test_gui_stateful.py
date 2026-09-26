"""Hypothesis shrinks failing MeasureLab control and signal sequences."""

from __future__ import annotations

import pytest
from hypothesis import HealthCheck, settings, strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, precondition, rule, run_state_machine_as_test

from src.gui.module_registry import MODULE_REGISTRY
from tests.gui_fuzz.actions import available_actions
from tests.gui_fuzz.audio import FuzzAudioEngine
from tests.gui_fuzz.diagnostics import Scenario
from tests.gui_fuzz.discovery import create_module_widget
from tests.gui_fuzz.invariants import check, check_closed, owned_resources, plot_data_count, refresh_active_timers


@pytest.mark.parametrize("module_key", ("Spectrum Analyzer", "Oscilloscope"))
def test_hypothesis_stateful(module_key, qapp, monkeypatch):
    import sounddevice as sd

    def blocked(*args, **kwargs):
        raise AssertionError("Physical audio access")

    monkeypatch.setattr(sd, "Stream", blocked)

    class Machine(RuleBasedStateMachine):
        def __init__(self):
            super().__init__()
            self.engine = FuzzAudioEngine()
            self.trace = Scenario(module_key, 0, strict_runtime_warnings=True)
            self.trace.__enter__()
            try:
                self.module, self.widget = create_module_widget(module_key, self.engine)
                self.trace.module, self.trace.widget, self.trace.engine = self.module, self.widget, self.engine
                self.widget.show()
                qapp.processEvents()
                primary_name = MODULE_REGISTRY[module_key].capabilities.console_primary_action.button_attribute
                self.primary = getattr(self.widget, primary_name)
                self.plot_count = plot_data_count(self.widget)
                self.resources = tuple(map(len, owned_resources(self.widget, self.module)))
            except BaseException:
                self.trace.__exit__(*__import__("sys").exc_info())
                raise

        @rule(selector=st.integers(min_value=0, max_value=2**32 - 1))
        def control(self, selector):
            actions = available_actions(self.widget, primary_button=self.primary)
            if actions:
                action = actions[selector % len(actions)]
                self.trace.record(action.description)
                try:
                    action.execute()
                    qapp.processEvents()
                except BaseException:
                    self.trace.__exit__(*__import__("sys").exc_info())
                    raise

        @precondition(lambda self: bool(getattr(self.module, "is_running", False)))
        @rule(
            kind=st.sampled_from(
                ("silence", "sine", "noise", "tiny", "full", "clipping", "dc", "left", "right", "different")
            ),
            frames=st.sampled_from((64, 1024)),
        )
        def audio(self, kind, frames):
            if getattr(self.module, "is_running", False):
                self.trace.record(f"feed({kind!r}, {frames})")
                self.engine.feed(kind, frames)
                refresh_active_timers(self.widget, self.module)
                qapp.processEvents()

        @invariant()
        def consistent(self):
            try:
                check(
                    self.widget,
                    self.module,
                    self.engine,
                    initial_plot_count=self.plot_count,
                    initial_resources=self.resources,
                    primary=self.primary,
                )
                self.trace.assert_clean()
            except BaseException:
                self.trace.save("".join(__import__("traceback").format_exc()))
                raise

        def teardown(self):
            try:
                if self.primary.isChecked():
                    self.primary.click()
                self.widget.close()
                qapp.processEvents()
                check_closed(self.widget, self.module, self.engine)
                self.trace.assert_clean()
            finally:
                self.engine.stop_stream(force=True)
                self.trace.__exit__(None, None, None)
                self.widget.deleteLater()

    run_state_machine_as_test(
        Machine,
        settings=settings(
            max_examples=12,
            stateful_step_count=18,
            deadline=None,
            derandomize=True,
            print_blob=True,
            suppress_health_check=[HealthCheck.too_slow],
        ),
    )
