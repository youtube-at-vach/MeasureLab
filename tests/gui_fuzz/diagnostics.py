"""Persist a deterministic reproduction trace whenever a scenario fails."""

from __future__ import annotations

import contextlib
import io
import json
import logging
import os
import sys
import traceback
import warnings
from pathlib import Path

import numpy as np
from PyQt6.QtCore import QtMsgType, qInstallMessageHandler


ARTIFACT_ROOT = Path(os.environ.get("MEASURELAB_GUI_FUZZ_ARTIFACTS", "artifacts/gui_fuzz"))
RUN_TOTALS = {"scenarios": 0, "operations": 0, "audio_blocks": 0}
OFFSCREEN_PLUGIN_WARNINGS = (
    "This plugin does not support propagateSizeHints()",
    "This plugin does not support raise()",
    # Qt's offscreen font database falls back to an available family once per process.
    "Populating font family aliases took",
)


class Scenario:
    def __init__(self, widget_key: str, seed: int, *, strict_runtime_warnings: bool = False):
        self.widget_key = widget_key
        self.seed = seed
        self.steps: list[str] = []
        self.last_state_before: dict[str, object] = {}
        self.qt_messages: list[tuple[str, str]] = []
        self.unhandled: list[str] = []
        self.log_errors: list[str] = []
        self.widget = None
        self.module = None
        self.engine = None
        self.stdout = io.StringIO()
        self.stderr = io.StringIO()
        self._active = False
        self.strict_runtime_warnings = strict_runtime_warnings

    def __enter__(self):
        self._active = True
        self._old_excepthook = sys.excepthook
        self._warning_context = warnings.catch_warnings()
        self._warning_context.__enter__()
        if self.strict_runtime_warnings:
            warnings.simplefilter("error", RuntimeWarning)
        self._old_qt_handler = qInstallMessageHandler(self._qt_message)
        self._log_handler = _ErrorLogHandler(self.log_errors)
        logging.getLogger().addHandler(self._log_handler)
        self._stdout_redirect = contextlib.redirect_stdout(self.stdout)
        self._stderr_redirect = contextlib.redirect_stderr(self.stderr)
        self._stdout_redirect.__enter__()
        self._stderr_redirect.__enter__()
        sys.excepthook = self._unhandled
        self._write_progress()
        return self

    def __exit__(self, exc_type, exc, tb):
        if not self._active:
            return False
        self._active = False
        sys.excepthook = self._old_excepthook
        qInstallMessageHandler(self._old_qt_handler)
        logging.getLogger().removeHandler(self._log_handler)
        self._warning_context.__exit__(exc_type, exc, tb)
        self._stderr_redirect.__exit__(exc_type, exc, tb)
        self._stdout_redirect.__exit__(exc_type, exc, tb)
        if exc is not None or self.unhandled:
            self.save("".join(traceback.format_exception(exc_type, exc, tb)) if exc else "\n".join(self.unhandled))
        RUN_TOTALS["scenarios"] += 1
        RUN_TOTALS["operations"] += sum(not step.startswith("candidate_controls_seen=") for step in self.steps)
        RUN_TOTALS["audio_blocks"] += sum(step.startswith("feed(") for step in self.steps)
        return False

    def _unhandled(self, exc_type, exc, tb):
        self.unhandled.append("".join(traceback.format_exception(exc_type, exc, tb)))

    def _qt_message(self, kind, context, message):
        self.qt_messages.append((kind.name, message))

    def record(self, step: str):
        self.last_state_before = self._state()
        self.steps.append(step)
        self._write_progress()

    def _write_progress(self):
        """Keep the last intended step on disk even if Qt terminates the process."""
        directory = ARTIFACT_ROOT / f"{self.widget_key.replace(' ', '_')}_{self.seed}"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "trace.json").write_text(
            json.dumps(
                {
                    "widget": self.widget_key,
                    "seed": self.seed,
                    "steps": self.steps,
                    "state_before": self.last_state_before,
                },
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )

    def _state(self) -> dict[str, object]:
        state = {}
        if self.module is not None:
            for name in ("is_running", "callback_id", "channel_mode", "analysis_mode", "sample_rate"):
                value = getattr(self.module, name, None)
                if isinstance(value, (str, bool, int, float)) or value is None:
                    state[name] = value
            for name in ("input_data", "data_buffer"):
                value = getattr(self.module, name, None)
                if isinstance(value, np.ndarray):
                    state[f"{name}_shape"] = list(value.shape)
                    state[f"{name}_finite"] = bool(np.isfinite(value).all())
        if self.engine is not None:
            state["engine_sample_rate"] = self.engine.sample_rate
            state["engine_callbacks"] = list(self.engine.callbacks)
            state["callback_error_count"] = self.engine.callback_error_count
        return state

    def assert_clean(self):
        if self.unhandled:
            raise AssertionError(f"Unhandled Qt slot exception: {self.unhandled[-1]}")
        if self.log_errors:
            raise AssertionError(f"Logged error: {self.log_errors[-1]}")
        errors = [
            f"{kind}: {message}"
            for kind, message in self.qt_messages
            if kind in {QtMsgType.QtCriticalMsg.name, QtMsgType.QtFatalMsg.name}
            or (kind == QtMsgType.QtWarningMsg.name and not message.startswith(OFFSCREEN_PLUGIN_WARNINGS))
        ]
        if errors:
            raise AssertionError("Qt warning/critical: " + "; ".join(errors))
        if self.stderr.getvalue().strip():
            raise AssertionError("stderr: " + self.stderr.getvalue()[-1500:])

    def save(self, error: str):
        directory = ARTIFACT_ROOT / f"{self.widget_key.replace(' ', '_')}_{self.seed}"
        directory.mkdir(parents=True, exist_ok=True)
        report = {
            "widget": self.widget_key,
            "seed": self.seed,
            "steps": self.steps,
            "state_before": self.last_state_before,
            "state": self._state(),
            "error": error,
            "qt_messages": self.qt_messages,
            "log_errors": self.log_errors,
            "stdout": self.stdout.getvalue(),
            "stderr": self.stderr.getvalue(),
            "replay": f"MEASURELAB_GUI_FUZZ_SEED={self.seed} ./.venv/bin/pytest -q tests/gui/",
            "hypothesis": "Hypothesis shrinks failing sequences and prints a reproduction blob when enabled.",
        }
        (directory / "failure.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        if self.widget is not None:
            try:
                self.widget.grab().save(str(directory / "last.png"))
            except (RuntimeError, OSError):
                pass


class _ErrorLogHandler(logging.Handler):
    def __init__(self, errors: list[str]):
        super().__init__(logging.ERROR)
        self.errors = errors

    def emit(self, record):
        self.errors.append(self.format(record))
